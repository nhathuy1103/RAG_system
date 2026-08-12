"""Chat application service: orchestrates retrieval, generation, and persistence."""

from __future__ import annotations

import asyncio
import json
import logging
from collections.abc import AsyncIterator, Mapping, Sequence
from dataclasses import dataclass, field, replace
from typing import Literal
from uuid import UUID

from app.chat.application.document_scope_planner import (
    DeterministicDocumentScopePlanner,
    DocumentScopePlan,
)
from app.chat.domain.models import (
    AnswerCitation,
    AnswerDone,
    AnswerFailed,
    AnswerToken,
    ChatEvent,
    Conversation,
    ConversationStarted,
    Message,
    NewCitation,
)
from app.chat.ports.repositories import ChatRepository, ChatRepositoryError
from app.documents.domain.models import Document
from app.documents.ports.repositories import (
    DocumentRepository,
    DocumentRepositoryError,
)
from app.generation.application.citation_validation import (
    CitationValidationError,
    build_evidence_aliases,
    validate_answer_citations,
    validate_citation_hit,
    validate_p5_citation_contract,
)
from app.generation.application.evidence_context import (
    EvidenceContextPolicy,
    build_generation_context,
)
from app.generation.application.no_answer_policy import no_answer_message
from app.generation.domain import CitationHit, TokenChunk, UsageInfo
from app.generation.domain.evidence import GenerationContext, NoAnswerReason
from app.generation.ports import AnswerGeneratorPort
from app.infrastructure.telemetry import Observation, Telemetry
from app.knowledge_quality.domain.models import (
    DocumentRelation,
    RelationStatus,
    RelationType,
)
from app.knowledge_quality.ports.repositories import (
    KnowledgeQualityRepository,
    KnowledgeQualityRepositoryError,
)
from app.notebooks.ports.repositories import (
    NotebookRepository,
    NotebookRepositoryError,
)
from app.retrieval.application.handle_retrieval_request import (
    ClarificationNeeded,
    FixedAnswer,
    RetrievalRequestHandler,
)
from app.retrieval.application.query_context import (
    QueryContext,
    QueryIntent,
    parse_query_context,
)
from app.retrieval.application.temporal_query import (
    QueryTimeRange,
    extract_query_time_range,
)
from app.retrieval.domain.metadata import EvidenceMetadata, MetadataValue
from app.retrieval.domain.models import (
    AgenticRetrievalResult,
    EvidenceChunk,
    RetrievalCandidate,
    RetrievalFilters,
)
from app.structured_facts.application.query import (
    StructuredFactQueryIntent,
    parse_structured_fact_query,
)
from app.structured_facts.ports.repositories import (
    StructuredFactEvidence,
    StructuredFactReader,
    StructuredFactRepositoryError,
    StructuredFactSearch,
)

LOGGER = logging.getLogger(__name__)

RETRIEVAL_TOP_K = 6
HISTORY_LIMIT = 6
READY_DOCUMENTS_LIMIT = 100
QUALITY_RELATIONS_LIMIT = 100
CONTROLLED_NO_ANSWER = (
    "Chưa có đủ thông tin trong các tài liệu bạn được phép truy cập để trả lời câu hỏi này."
)
CITATION_VALIDATION_FAILURE = "Không thể xác minh nguồn trích dẫn của câu trả lời"


class ChatServiceError(RuntimeError):
    """Raised when the chat use case cannot complete safely."""


class NotebookNotFoundError(ChatServiceError):
    """The requested notebook does not exist (or isn't owned by the caller)."""


class ConversationNotFoundError(ChatServiceError):
    """The requested conversation does not exist in this notebook."""


@dataclass(frozen=True)
class ChatContext:
    """Everything ``respond`` needs, resolved up front by ``prepare``."""

    owner_id: UUID
    notebook_id: UUID
    conversation_id: UUID
    assistant_message_id: UUID
    question: str
    history: tuple[str, ...]
    allowed_document_ids: tuple[UUID, ...]
    document_titles: dict[UUID, str]
    document_scope_plan: DocumentScopePlan | None = None
    document_scope_execution_mode: Literal["off", "shadow", "on"] = "off"
    confirmed_conflict_pairs: tuple[tuple[UUID, UUID], ...] = ()
    structured_query: StructuredFactQueryIntent | None = None
    structured_document_ids: tuple[UUID, ...] | None = None
    trace_id: str = ""
    query_context: QueryContext | None = None


def _derive_title(question: str) -> str:
    stripped = " ".join(question.split())
    return stripped[:197] + "..." if len(stripped) > 200 else stripped or "New chat"


def _typed_metadata(metadata: Mapping[str, MetadataValue]) -> EvidenceMetadata:
    if isinstance(metadata, EvidenceMetadata):
        return metadata
    return EvidenceMetadata.from_mapping(metadata)


def _parse_page_number(metadata: Mapping[str, MetadataValue]) -> int | None:
    page_number = _typed_metadata(metadata).page_number
    if page_number is None:
        return None
    return page_number if page_number > 0 else None


def _parse_section_title(metadata: Mapping[str, MetadataValue]) -> str | None:
    return _typed_metadata(metadata).section_title


def _format_page_or_section(
    page_number: int | None,
    section_title: str | None,
) -> str | None:
    parts = [f"Trang {page_number}" if page_number else "", section_title or ""]
    formatted = " · ".join(part for part in parts if part)
    return formatted or None


def _resolve_allowed_document_ids(
    documents: Sequence[Document],
    requested_document_ids: tuple[UUID, ...] | None,
    *,
    valid_time: QueryTimeRange | None = None,
) -> tuple[UUID, ...]:
    documents_by_id = {document.id: document for document in documents}
    allowed_ids: set[UUID] = set()
    if requested_document_ids is None:
        if valid_time is None:
            allowed_ids.update(
                document.id
                for document in documents
                if document.is_current and document.canonical_document_id is None
            )
        else:
            allowed_ids.update(
                document.id
                for document in documents
                if (
                    document.canonical_document_id is None
                    and document.effective_from is not None
                    and document.effective_from <= valid_time.end
                    and (document.effective_to is None or document.effective_to >= valid_time.start)
                )
            )
    else:
        for requested_id in requested_document_ids:
            document = documents_by_id.get(requested_id)
            if document is None:
                continue
            canonical_id = document.canonical_document_id
            if canonical_id is not None and canonical_id in documents_by_id:
                allowed_ids.add(canonical_id)
            else:
                # Explicit selection may intentionally target an older
                # confirmed version for historical comparison.
                allowed_ids.add(document.id)
    return tuple(sorted(allowed_ids, key=str))


def _resolve_structured_document_ids(
    documents: Sequence[Document],
    requested_document_ids: tuple[UUID, ...] | None,
) -> tuple[UUID, ...]:
    """Resolve claim-search scope without applying document-level valid time.

    Structured claims carry their own effective interval. Filtering documents
    by a missing coarse interval first would hide otherwise valid row-level
    facts before the fail-closed SQL claim filter can inspect them.
    """

    documents_by_id = {document.id: document for document in documents}
    if requested_document_ids is None:
        return tuple(
            sorted(
                (
                    document.id
                    for document in documents
                    if document.is_active and document.canonical_document_id is None
                ),
                key=str,
            )
        )

    allowed_ids: set[UUID] = set()
    for requested_id in requested_document_ids:
        document = documents_by_id.get(requested_id)
        if document is None:
            continue
        canonical_id = document.canonical_document_id
        if canonical_id is not None and canonical_id in documents_by_id:
            allowed_ids.add(canonical_id)
        else:
            allowed_ids.add(document.id)
    return tuple(sorted(allowed_ids, key=str))


def _resolve_p5_document_ids(
    documents: Sequence[Document],
    requested_document_ids: tuple[UUID, ...] | None,
    query: QueryContext,
) -> tuple[UUID, ...]:
    """Keep active historical/version candidates only when query semantics require them."""

    if requested_document_ids is not None:
        return _resolve_allowed_document_ids(documents, requested_document_ids)
    if query.intent not in {
        QueryIntent.HISTORICAL_FACT,
        QueryIntent.TEMPORAL_COMPARISON,
        QueryIntent.VERSION_COMPARISON,
    }:
        return _resolve_allowed_document_ids(documents, None)
    return tuple(
        sorted(
            (
                document.id
                for document in documents
                if document.is_active and document.canonical_document_id is None
            ),
            key=str,
        )
    )


def _build_structured_fact_search(
    context: ChatContext,
    intent: StructuredFactQueryIntent,
    *,
    retrieval_top_k: int,
) -> StructuredFactSearch:
    document_ids = (
        context.structured_document_ids
        if context.structured_document_ids is not None
        else context.allowed_document_ids
    )
    return StructuredFactSearch(
        notebook_id=context.notebook_id,
        document_ids=document_ids,
        predicate=intent.predicate,
        subject_query=intent.subject_query,
        valid_from=intent.valid_time.start if intent.valid_time else None,
        valid_to=intent.valid_time.end if intent.valid_time else None,
        limit=max(retrieval_top_k * 2, retrieval_top_k),
        qualifiers=intent.qualifiers,
    )


def _resolve_legacy_document_ids(
    documents: Sequence[Document],
    requested_document_ids: tuple[UUID, ...] | None,
) -> tuple[UUID, ...]:
    """Return the pre-quality document scope used by off and shadow modes."""
    available_ids = {document.id for document in documents}
    if requested_document_ids is None:
        return tuple(sorted(available_ids, key=str))
    return tuple(
        sorted(
            (document_id for document_id in requested_document_ids if document_id in available_ids),
            key=str,
        )
    )


def _apply_preferred_relations(
    allowed_document_ids: tuple[UUID, ...],
    relations: Sequence[DocumentRelation],
) -> tuple[UUID, ...]:
    """Keep both conflict sides available; preference is advisory, not suppression."""
    del relations
    return tuple(sorted(set(allowed_document_ids), key=str))


def _annotate_confirmed_conflicts(
    evidence: tuple[RetrievalCandidate, ...],
    conflict_pairs: tuple[tuple[UUID, UUID], ...],
) -> tuple[RetrievalCandidate, ...]:
    """Attach only in-scope confirmed conflict peers to retrieved evidence."""
    peers_by_document: dict[str, set[str]] = {}
    evidence_document_ids = {item.chunk.document_id for item in evidence}
    for left_id, right_id in conflict_pairs:
        left = str(left_id)
        right = str(right_id)
        if left not in evidence_document_ids or right not in evidence_document_ids:
            continue
        peers_by_document.setdefault(left, set()).add(right)
        peers_by_document.setdefault(right, set()).add(left)

    annotated: list[RetrievalCandidate] = []
    for candidate in evidence:
        peers = peers_by_document.get(candidate.chunk.document_id)
        if not peers:
            annotated.append(candidate)
            continue
        metadata = dict(candidate.chunk.metadata)
        metadata["confirmed_conflict_peer_document_ids"] = ",".join(sorted(peers))
        annotated.append(
            replace(
                candidate,
                chunk=replace(candidate.chunk, metadata=metadata),
            )
        )
    return tuple(annotated)


def _structured_candidates(
    facts: Sequence[StructuredFactEvidence],
) -> tuple[RetrievalCandidate, ...]:
    """Project cell-backed facts into the existing citation-safe evidence type."""

    candidates: list[RetrievalCandidate] = []
    for rank, fact in enumerate(facts, start=1):
        provenance = fact.provenance
        page_number = _safe_positive_int(provenance.get("page_number"))
        table_id = str(provenance.get("table_id") or "").strip()
        row = provenance.get("data_row_ordinal", provenance.get("row_index"))
        location = " Â· ".join(
            part
            for part in (
                f"Báº£ng {table_id}" if table_id else "Báº£ng dá»¯ liá»‡u",
                f"dÃ²ng {row}" if row is not None else "",
            )
            if part
        )
        source_text = fact.source_text.strip()
        value_text = json.dumps(
            dict(fact.normalized_value),
            ensure_ascii=False,
            sort_keys=True,
        )
        qualifiers_text = json.dumps(
            dict(fact.qualifiers),
            ensure_ascii=False,
            sort_keys=True,
        )
        temporal_text = json.dumps(
            dict(fact.temporal),
            ensure_ascii=False,
            sort_keys=True,
        )
        authority = dict(fact.authority)
        authority_text = json.dumps(
            authority,
            ensure_ascii=False,
            sort_keys=True,
        )
        relation_warnings = [dict(warning) for warning in fact.relation_warnings]
        lines = [
            f"Subject: {fact.subject_key}",
            f"Predicate: {fact.predicate}",
            f"Normalized value: {value_text}",
            f"Qualifiers: {qualifiers_text}",
            f"Temporal validity: {temporal_text}",
        ]
        if authority:
            lines.append(f"Source authority: {authority_text}")
        if source_text:
            lines.insert(0, f"Source cell: {source_text}")
        if relation_warnings:
            lines.append(
                "Relation warnings: "
                + json.dumps(relation_warnings, ensure_ascii=False, sort_keys=True)
            )
        candidates.append(
            RetrievalCandidate(
                chunk=EvidenceChunk(
                    id=str(fact.source_chunk_id),
                    document_id=str(fact.document_id),
                    text="\n".join(lines),
                    metadata=EvidenceMetadata.from_mapping(
                        {
                            "page_number": page_number,
                            "section_title": location,
                            "document_version": fact.document_version,
                            "content_kind": "structured_fact",
                            "structured_claim_id": fact.claim_id,
                            "structured_subject": fact.subject_key,
                            "structured_predicate": fact.predicate,
                            "structured_value": dict(fact.normalized_value),
                            "structured_qualifiers": dict(fact.qualifiers),
                            "structured_temporal": dict(fact.temporal),
                            "structured_provenance": dict(fact.provenance),
                            "structured_relation_warnings": relation_warnings,
                            "structured_authority": authority,
                        }
                    ),
                ),
                score=1.0 + max(0.0, min(fact.confidence, 1.0)),
                rank=rank,
                source="structured",
            )
        )
    return tuple(candidates)


def _safe_positive_int(value: object) -> int | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        parsed = value
    elif isinstance(value, str | float):
        try:
            parsed = int(value)
        except (TypeError, ValueError, OverflowError):
            return None
    else:
        return None
    return parsed if parsed > 0 else None


def _deduplicate_citations(
    citations: Sequence[NewCitation],
) -> tuple[NewCitation, ...]:
    """Respect message citation uniqueness while keeping first-use order."""

    selected: list[NewCitation] = []
    seen_chunks: set[UUID] = set()
    seen_ordinals: set[int] = set()
    for citation in citations:
        if citation.chunk_id in seen_chunks or citation.ordinal in seen_ordinals:
            continue
        seen_chunks.add(citation.chunk_id)
        seen_ordinals.add(citation.ordinal)
        selected.append(citation)
    return tuple(selected)


def _merge_structured_candidates(
    structured: tuple[RetrievalCandidate, ...],
    vector: tuple[RetrievalCandidate, ...],
    *,
    top_k: int,
) -> tuple[RetrievalCandidate, ...]:
    selected = list(structured[:top_k])
    structured_chunk_ids = {item.chunk.id for item in selected}
    selected.extend(item for item in vector if item.chunk.id not in structured_chunk_ids)
    return tuple(replace(item, rank=index) for index, item in enumerate(selected[:top_k], 1))


def _evidence_gate_reason(
    *,
    result: AgenticRetrievalResult | None,
    use_structured: bool,
    evidence: tuple[RetrievalCandidate, ...],
    authorized_document_ids: tuple[UUID, ...],
) -> str | None:
    """Return why evidence must not cross the generation boundary.

    Retrieval adapters are treated as untrusted at this boundary.  A result is
    allowed through only when it has a positive sufficiency verdict and every
    candidate belongs to the request's already-authorised document scope.
    Structured facts are exact-query evidence and therefore carry their own
    non-empty gate, but are subject to the same authorisation check.
    """

    if not evidence:
        return "no_evidence"
    if not use_structured:
        if result is None:
            return "missing_retrieval_result"
        if result.gave_up:
            return "retrieval_gave_up"
        if not result.trace or not result.trace[-1].sufficiency.sufficient:
            return "insufficient_evidence"

    authorized = set(authorized_document_ids)
    for candidate in evidence:
        try:
            document_id = UUID(candidate.chunk.document_id)
            UUID(candidate.chunk.id)
        except (TypeError, ValueError, AttributeError):
            return "malformed_evidence_identity"
        if document_id not in authorized:
            return "unauthorized_evidence"
    return None


@dataclass
class ChatService:
    """Coordinates notebook/document scope, retrieval, generation, and persistence."""

    notebook_repository: NotebookRepository
    document_repository: DocumentRepository
    chat_repository: ChatRepository
    retrieval_handler: RetrievalRequestHandler
    answer_generator: AnswerGeneratorPort
    chat_model_name: str
    quality_repository: KnowledgeQualityRepository | None = None
    knowledge_quality_mode: Literal["off", "shadow", "on"] = "off"
    structured_fact_mode: Literal["off", "shadow", "on"] = "off"
    structured_fact_reader: StructuredFactReader | None = None
    retrieval_top_k: int = RETRIEVAL_TOP_K
    history_limit: int = HISTORY_LIMIT
    telemetry: Telemetry = field(default_factory=Telemetry)
    document_scope_planner: DeterministicDocumentScopePlanner | None = None
    document_scope_planner_mode: Literal["off", "shadow", "on"] = "off"
    p5_mode: Literal["off", "shadow", "on"] = "shadow"
    p5_context_policy: EvidenceContextPolicy = field(default_factory=EvidenceContextPolicy)

    def __post_init__(self) -> None:
        if self.knowledge_quality_mode not in {"off", "shadow", "on"}:
            raise ValueError("knowledge_quality_mode must be off, shadow, or on")
        if self.structured_fact_mode not in {"off", "shadow", "on"}:
            raise ValueError("structured_fact_mode must be off, shadow, or on")
        if self.document_scope_planner_mode not in {"off", "shadow", "on"}:
            raise ValueError("document_scope_planner_mode must be off, shadow, or on")
        if self.p5_mode not in {"off", "shadow", "on"}:
            raise ValueError("p5_mode must be off, shadow, or on")

    async def prepare(
        self,
        *,
        owner_id: UUID,
        notebook_id: UUID,
        conversation_id: UUID | None,
        question: str,
        requested_document_ids: tuple[UUID, ...] | None,
    ) -> ChatContext:
        trace_id = self.telemetry.create_trace_id()
        with self.telemetry.observe(
            "rag.chat.prepare",
            as_type="chain",
            trace_id=trace_id,
            input={
                "question": self.telemetry.content(question),
                "notebook_id": str(notebook_id),
                "conversation_id": str(conversation_id) if conversation_id else None,
                "requested_document_count": (
                    len(requested_document_ids) if requested_document_ids is not None else None
                ),
            },
            metadata={
                "notebook_id": str(notebook_id),
                "requested_document_count": (
                    len(requested_document_ids) if requested_document_ids is not None else "all"
                ),
            },
            user_id=str(owner_id),
            session_id=str(conversation_id) if conversation_id else None,
            tags=("rag", "chat", "prepare"),
            trace_name="rag-chat",
        ) as observation:
            context = await self._prepare(
                owner_id=owner_id,
                notebook_id=notebook_id,
                conversation_id=conversation_id,
                question=question,
                requested_document_ids=requested_document_ids,
                trace_id=trace_id,
            )
            observation.update(
                output={
                    "conversation_id": str(context.conversation_id),
                    "assistant_message_id": str(context.assistant_message_id),
                    "history_turns": len(context.history),
                    "allowed_document_count": len(context.allowed_document_ids),
                }
            )
            return context

    async def _prepare(
        self,
        *,
        owner_id: UUID,
        notebook_id: UUID,
        conversation_id: UUID | None,
        question: str,
        requested_document_ids: tuple[UUID, ...] | None,
        trace_id: str,
    ) -> ChatContext:
        try:
            with self.telemetry.observe(
                "chat.authorize_notebook",
                as_type="guardrail",
                input={"notebook_id": str(notebook_id)},
            ) as observation:
                notebook_exists = await self.notebook_repository.exists_owned(notebook_id)
                observation.update(output={"owned": notebook_exists})
        except NotebookRepositoryError as exc:
            raise ChatServiceError("Notebook storage is unavailable") from exc
        if not notebook_exists:
            raise NotebookNotFoundError("Notebook not found")

        try:
            with self.telemetry.observe(
                "chat.list_ready_documents",
                as_type="tool",
                input={"notebook_id": str(notebook_id), "status": "ready"},
            ) as observation:
                documents, total_documents = await self.document_repository.list_by_notebook(
                    notebook_id,
                    status="ready",
                    limit=READY_DOCUMENTS_LIMIT,
                    offset=0,
                )
                while len(documents) < total_documents:
                    page, _ = await self.document_repository.list_by_notebook(
                        notebook_id,
                        status="ready",
                        limit=READY_DOCUMENTS_LIMIT,
                        offset=len(documents),
                    )
                    if not page:
                        break
                    documents.extend(page)
                observation.update(
                    output={
                        "ready_document_count": len(documents),
                        "ready_document_total": total_documents,
                    }
                )
        except DocumentRepositoryError as exc:
            raise ChatServiceError("Document storage is unavailable") from exc

        query_context = parse_query_context(
            question,
            owner_id=str(owner_id),
            notebook_id=str(notebook_id),
        )
        legacy_allowed_ids = _resolve_legacy_document_ids(
            documents,
            requested_document_ids,
        )
        structured_document_ids = _resolve_structured_document_ids(
            documents,
            requested_document_ids,
        )
        valid_time = (
            extract_query_time_range(question) if self.structured_fact_mode == "on" else None
        )
        structured_query = (
            parse_structured_fact_query(question) if self.structured_fact_mode != "off" else None
        )
        quality_allowed_ids = _resolve_allowed_document_ids(
            documents,
            requested_document_ids,
            valid_time=valid_time,
        )
        allowed_ids = (
            _resolve_p5_document_ids(documents, requested_document_ids, query_context)
            if self.p5_mode == "on"
            else (
                quality_allowed_ids
                if self.knowledge_quality_mode == "on" or valid_time is not None
                else legacy_allowed_ids
            )
        )
        scope_plan: DocumentScopePlan | None = None
        with self.telemetry.observe(
            "retrieval.document_scope_plan",
            as_type="chain",
            input={
                "query": self.telemetry.content(question),
                "planner_enabled": self.document_scope_planner is not None,
                "source_fields": ["documents.id", "documents.original_filename"],
                "authorized_document_ids": [str(value) for value in allowed_ids],
                "authoritative_documents": [
                    {
                        "document_id": str(document.id),
                        "original_filename": document.original_filename,
                    }
                    for document in documents
                    if document.id in set(allowed_ids)
                ],
            },
        ) as observation:
            if self.document_scope_planner is not None:
                scope_plan = self.document_scope_planner.plan(question, documents, allowed_ids)
                if self.document_scope_planner_mode == "on":
                    allowed_ids = scope_plan.after_document_ids
            observation.update(
                output={
                    "execution_mode": self.document_scope_planner_mode,
                    "applied": bool(
                        scope_plan
                        and scope_plan.applied
                        and self.document_scope_planner_mode == "on"
                    ),
                    "reason": scope_plan.reason if scope_plan else "planner_disabled",
                    "before_document_count": (
                        len(scope_plan.before_document_ids) if scope_plan else len(allowed_ids)
                    ),
                    "after_document_count": len(allowed_ids),
                    "selected_document_ids": [str(value) for value in allowed_ids],
                    "counterfactual_document_ids": (
                        [str(value) for value in scope_plan.after_document_ids]
                        if scope_plan
                        else [str(value) for value in allowed_ids]
                    ),
                    "matched_titles": list(scope_plan.matched_titles) if scope_plan else [],
                    "matched_tokens": list(scope_plan.matched_tokens) if scope_plan else [],
                    "fail_open": not bool(
                        scope_plan
                        and scope_plan.applied
                        and self.document_scope_planner_mode == "on"
                    ),
                }
            )
        confirmed_conflict_pairs: tuple[tuple[UUID, UUID], ...] = ()
        if self.knowledge_quality_mode == "on" and self.quality_repository is not None:
            confirmed_conflict_pairs = await self._load_confirmed_conflict_pairs(
                notebook_id,
                set(allowed_ids),
            )
        with self.telemetry.observe(
            "chat.knowledge_quality_scope",
            as_type="guardrail",
            input={
                "mode": self.knowledge_quality_mode,
                "legacy_document_count": len(legacy_allowed_ids),
                "valid_time_start": valid_time.start.isoformat() if valid_time else None,
                "valid_time_end": valid_time.end.isoformat() if valid_time else None,
            },
        ) as observation:
            observation.update(
                output={
                    "applied": self.knowledge_quality_mode == "on",
                    "allowed_document_count": len(allowed_ids),
                    "counterfactual_document_count": len(quality_allowed_ids),
                    "counterfactual_suppressed_count": len(
                        set(legacy_allowed_ids) - set(quality_allowed_ids)
                    ),
                    "temporal_filter_applied": valid_time is not None,
                }
            )
        title_document_ids = set(allowed_ids)
        if structured_query is not None:
            title_document_ids.update(structured_document_ids)
        document_titles = {
            document.id: document.original_filename
            for document in documents
            if document.id in title_document_ids
        }

        try:
            with self.telemetry.observe(
                "chat.prepare_conversation",
                as_type="tool",
                input={
                    "conversation_id": str(conversation_id) if conversation_id else None,
                    "history_limit": self.history_limit,
                },
            ) as observation:
                conversation, history, assistant_message = await self._prepare_conversation(
                    owner_id=owner_id,
                    notebook_id=notebook_id,
                    conversation_id=conversation_id,
                    question=question,
                )
                observation.update(
                    output={
                        "conversation_id": str(conversation.id),
                        "assistant_message_id": str(assistant_message.id),
                        "history_turns": len(history),
                    }
                )
        except ConversationNotFoundError:
            raise
        except ChatRepositoryError as exc:
            raise ChatServiceError("Chat storage is unavailable") from exc

        return ChatContext(
            owner_id=owner_id,
            notebook_id=notebook_id,
            conversation_id=conversation.id,
            assistant_message_id=assistant_message.id,
            question=question,
            history=history,
            allowed_document_ids=allowed_ids,
            document_titles=document_titles,
            document_scope_plan=scope_plan,
            document_scope_execution_mode=self.document_scope_planner_mode,
            confirmed_conflict_pairs=confirmed_conflict_pairs,
            structured_query=structured_query,
            structured_document_ids=structured_document_ids,
            trace_id=trace_id,
            query_context=query_context,
        )

    async def _load_confirmed_conflict_pairs(
        self,
        notebook_id: UUID,
        allowed_ids: set[UUID],
    ) -> tuple[tuple[UUID, UUID], ...]:
        if self.quality_repository is None or not allowed_ids:
            return ()
        relations: list[DocumentRelation] = []
        offset = 0
        try:
            while True:
                page, total = await self.quality_repository.list_relations(
                    notebook_id,
                    relation_status=RelationStatus.CONFIRMED,
                    relation_type=RelationType.CONFLICT,
                    limit=QUALITY_RELATIONS_LIMIT,
                    offset=offset,
                )
                relations.extend(page)
                offset += len(page)
                if not page or offset >= total:
                    break
        except KnowledgeQualityRepositoryError:
            LOGGER.exception(
                "Could not load confirmed conflicts for notebook %s",
                notebook_id,
            )
            return ()
        pairs: set[tuple[UUID, UUID]] = set()
        for relation in relations:
            if (
                relation.source_document_id not in allowed_ids
                or relation.target_document_id not in allowed_ids
            ):
                continue
            ordered = sorted(
                (relation.source_document_id, relation.target_document_id),
                key=str,
            )
            pairs.add((ordered[0], ordered[1]))
        return tuple(sorted(pairs, key=lambda pair: (str(pair[0]), str(pair[1]))))

    async def _prepare_conversation(
        self,
        *,
        owner_id: UUID,
        notebook_id: UUID,
        conversation_id: UUID | None,
        question: str,
    ) -> tuple[Conversation, tuple[str, ...], Message]:
        try:
            if conversation_id is None:
                conversation = await self.chat_repository.create_conversation(
                    owner_id=owner_id,
                    notebook_id=notebook_id,
                    title=_derive_title(question),
                )
            else:
                found = await self.chat_repository.get_conversation(conversation_id, notebook_id)
                if found is None:
                    raise ConversationNotFoundError("Conversation not found")
                conversation = found

            history = await self.chat_repository.list_recent_user_questions(
                conversation.id, notebook_id, limit=self.history_limit
            )
            await self.chat_repository.insert_user_message(
                owner_id=owner_id,
                notebook_id=notebook_id,
                conversation_id=conversation.id,
                content=question,
            )
            assistant_message = await self.chat_repository.insert_pending_assistant_message(
                owner_id=owner_id,
                notebook_id=notebook_id,
                conversation_id=conversation.id,
            )
            return conversation, history, assistant_message
        except ChatRepositoryError:
            raise

    async def respond(self, context: ChatContext) -> AsyncIterator[ChatEvent]:
        """Retrieve, generate, and persist an answer, yielding events as they occur."""
        with self.telemetry.observe(
            "rag.chat.respond",
            as_type="chain",
            trace_id=context.trace_id,
            input={
                "question": self.telemetry.content(context.question),
                "history": self.telemetry.content(list(context.history)),
                "allowed_document_ids": [
                    str(document_id) for document_id in context.allowed_document_ids
                ],
                "document_scope_plan": (
                    {
                        "execution_mode": context.document_scope_execution_mode,
                        "counterfactual_match": context.document_scope_plan.applied,
                        "applied": (
                            context.document_scope_plan.applied
                            and context.document_scope_execution_mode == "on"
                        ),
                        "reason": context.document_scope_plan.reason,
                        "matched_titles": list(context.document_scope_plan.matched_titles),
                        "matched_tokens": list(context.document_scope_plan.matched_tokens),
                    }
                    if context.document_scope_plan
                    else None
                ),
            },
            metadata={
                "notebook_id": str(context.notebook_id),
                "conversation_id": str(context.conversation_id),
                "assistant_message_id": str(context.assistant_message_id),
                "document_count": len(context.allowed_document_ids),
                "retrieval_top_k": self.retrieval_top_k,
                "chat_model": self.chat_model_name,
            },
            user_id=str(context.owner_id),
            session_id=str(context.conversation_id),
            tags=("rag", "chat", "streaming"),
            trace_name="rag-chat",
        ) as observation:
            async for event in self._respond(context, observation):
                yield event

    async def _respond(
        self,
        context: ChatContext,
        root_observation: Observation,
    ) -> AsyncIterator[ChatEvent]:
        yield ConversationStarted(conversation_id=context.conversation_id)

        filters = RetrievalFilters(
            owner_id=str(context.owner_id),
            notebook_id=str(context.notebook_id),
            document_ids=tuple(str(doc_id) for doc_id in context.allowed_document_ids),
        )

        structured_evidence: tuple[RetrievalCandidate, ...] = ()
        if context.structured_query is not None and self.structured_fact_reader is not None:
            intent = context.structured_query
            try:
                facts = await asyncio.to_thread(
                    self.structured_fact_reader.search,
                    _build_structured_fact_search(
                        context,
                        intent,
                        retrieval_top_k=self.retrieval_top_k,
                    ),
                )
                structured_evidence = _structured_candidates(facts)
            except StructuredFactRepositoryError:
                LOGGER.exception(
                    "Structured lookup failed for conversation %s; using vector retrieval",
                    context.conversation_id,
                )

        use_structured = self.structured_fact_mode == "on" and bool(structured_evidence)
        result = None
        if not use_structured:
            try:
                result = await asyncio.to_thread(
                    self.retrieval_handler.handle,
                    message=context.question,
                    history=context.history,
                    filters=filters,
                    top_k=self.retrieval_top_k,
                )
            except Exception:
                LOGGER.exception("Retrieval failed for conversation %s", context.conversation_id)
                await self._safe_fail(context, "Không thể truy hồi tài liệu")
                root_observation.update(
                    output={"status": "retrieval_failed"},
                    level="ERROR",
                    status_message="Retrieval failed",
                )
                yield AnswerFailed(message="Không thể truy hồi tài liệu")
                return

        if isinstance(result, ClarificationNeeded | FixedAnswer):
            text = (
                result.clarifying_question
                if isinstance(result, ClarificationNeeded)
                else result.answer
            )
            yield AnswerToken(text=text)
            await self._safe_complete(context, content=text, model=None, tokens=None)
            root_observation.update(
                output={
                    "status": "completed_without_generation",
                    "decision": type(result).__name__,
                    "answer": self.telemetry.content(text),
                }
            )
            yield AnswerDone()
            return

        vector_evidence = result.evidence if result is not None else ()
        evidence = _merge_structured_candidates(
            structured_evidence if use_structured else (),
            vector_evidence,
            top_k=self.retrieval_top_k,
        )
        authorized_document_ids = (
            context.structured_document_ids
            if use_structured and context.structured_document_ids is not None
            else context.allowed_document_ids
        )
        evidence_gate_reason = _evidence_gate_reason(
            result=result,
            use_structured=use_structured,
            evidence=evidence,
            authorized_document_ids=authorized_document_ids,
        )
        if evidence_gate_reason is not None:
            LOGGER.info(
                "Evidence gate returned a controlled no-answer for conversation %s: %s",
                context.conversation_id,
                evidence_gate_reason,
            )
            yield AnswerToken(text=CONTROLLED_NO_ANSWER)
            await self._safe_complete(
                context,
                content=CONTROLLED_NO_ANSWER,
                model=None,
                tokens=None,
            )
            root_observation.update(
                output={
                    "status": "controlled_no_answer",
                    "evidence_gate_reason": evidence_gate_reason,
                    "evidence_count": len(evidence),
                    "generator_called": False,
                },
                level=(
                    "WARNING"
                    if evidence_gate_reason
                    in {"unauthorized_evidence", "malformed_evidence_identity"}
                    else "DEFAULT"
                ),
                status_message="Evidence was not eligible for generation",
            )
            yield AnswerDone()
            return

        evidence = _annotate_confirmed_conflicts(
            evidence,
            context.confirmed_conflict_pairs,
        )
        p5_context: GenerationContext | None = None
        if self.p5_mode != "off":
            query_context = context.query_context or parse_query_context(
                context.question,
                owner_id=str(context.owner_id),
                notebook_id=str(context.notebook_id),
            )
            with self.telemetry.observe(
                "generation.p5_evidence_context",
                as_type="chain",
                input={
                    "mode": self.p5_mode,
                    "query_intent": query_context.intent,
                    "evidence_count": len(evidence),
                },
            ) as observation:
                p5_context = build_generation_context(
                    query_context,
                    evidence,
                    authorized_document_ids=frozenset(
                        str(document_id) for document_id in authorized_document_ids
                    ),
                    policy=self.p5_context_policy,
                )
                observation.update(
                    output={
                        "selected_evidence_ids": [item.evidence_id for item in p5_context.evidence],
                        "selected_chunk_ids": [item.chunk_id for item in p5_context.evidence],
                        "suppressed_ids": list(p5_context.diagnostics.suppressed_ids),
                        "unauthorized_ids": list(p5_context.diagnostics.unauthorized_ids),
                        "conflicts_preserved": (p5_context.diagnostics.conflict_pair_count),
                        "context_tokens_before": (p5_context.diagnostics.estimated_input_tokens),
                        "context_tokens_after": (p5_context.diagnostics.estimated_selected_tokens),
                        "no_answer_reason": p5_context.no_answer_reason,
                    }
                )
            if self.p5_mode == "on" and p5_context.no_answer_reason is not None:
                safe_answer = no_answer_message(
                    p5_context.no_answer_reason,
                    follow_up=p5_context.follow_up,
                )
                yield AnswerToken(text=safe_answer)
                await self._safe_complete(
                    context,
                    content=safe_answer,
                    model=None,
                    tokens=None,
                )
                root_observation.update(
                    output={
                        "status": "p5_controlled_no_answer",
                        "no_answer_reason": p5_context.no_answer_reason,
                        "generator_called": False,
                    }
                )
                yield AnswerDone()
                return
            if self.p5_mode == "on":
                evidence = p5_context.candidates
        evidence_by_alias = build_evidence_aliases(evidence)
        text_parts: list[str] = []
        new_citations: list[NewCitation] = []
        pending_citation_events: list[AnswerCitation] = []
        accepted_source_ids: list[str] = []
        usage: UsageInfo | None = None

        try:
            generation_stream = (
                self.answer_generator.stream(
                    question=context.question,
                    evidence=evidence,
                    generation_context=p5_context,
                )
                if self.p5_mode == "on" and p5_context is not None
                else self.answer_generator.stream(
                    question=context.question,
                    evidence=evidence,
                )
            )
            async for event in generation_stream:
                if isinstance(event, TokenChunk):
                    text_parts.append(event.text)
                    if self.p5_mode != "on":
                        yield AnswerToken(text=event.text)
                elif isinstance(event, CitationHit):
                    candidate = validate_citation_hit(
                        event,
                        evidence_by_alias=evidence_by_alias,
                        accepted_source_ids=accepted_source_ids,
                    )
                    accepted_source_ids.append(event.source_id)
                    chunk = candidate.chunk
                    document_id = UUID(chunk.document_id)
                    page_number = _parse_page_number(chunk.metadata)
                    section_title = _parse_section_title(chunk.metadata)
                    semantic_evidence = (
                        p5_context.evidence_by_id.get(event.source_id)
                        if p5_context is not None
                        else None
                    )
                    raw_provenance = chunk.metadata.get("structured_provenance")
                    structured_provenance = (
                        raw_provenance if isinstance(raw_provenance, Mapping) else {}
                    )
                    new_citations.append(
                        NewCitation(
                            document_id=document_id,
                            chunk_id=UUID(chunk.id),
                            ordinal=event.ordinal,
                            quote=chunk.text,
                            retrieval_score=candidate.score,
                        )
                    )
                    pending_citation_events.append(
                        AnswerCitation(
                            source_id=event.source_id,
                            document_id=document_id,
                            document_title=context.document_titles.get(document_id, "Tài liệu"),
                            page_number=page_number,
                            section_title=section_title,
                            page_or_section=_format_page_or_section(
                                page_number,
                                section_title,
                            ),
                            document_version=chunk.typed_metadata.document_version,
                            excerpt=chunk.text,
                            retrieval_score=candidate.score,
                            claim_ids=(
                                semantic_evidence.claim_ids if semantic_evidence is not None else ()
                            ),
                            table_id=(
                                str(structured_provenance.get("table_id") or "").strip() or None
                            ),
                            row_ordinal=_safe_positive_int(
                                structured_provenance.get(
                                    "data_row_ordinal",
                                    structured_provenance.get("row_index"),
                                )
                            ),
                            evidence_group_id=(
                                semantic_evidence.evidence_group_id
                                if semantic_evidence is not None
                                else None
                            ),
                            occurrence_count=(
                                semantic_evidence.provenance.occurrence_count
                                if semantic_evidence is not None
                                else 1
                            ),
                            independent_source_count=(
                                semantic_evidence.independent_source_count
                                if semantic_evidence is not None
                                else 1
                            ),
                            relation_type=(
                                semantic_evidence.relation_type
                                if semantic_evidence is not None
                                else None
                            ),
                            evidence_status=(
                                semantic_evidence.status if semantic_evidence is not None else None
                            ),
                            authority_level=(
                                semantic_evidence.authority.authority_level
                                if semantic_evidence is not None
                                else None
                            ),
                            source_type=(
                                semantic_evidence.authority.source_type
                                if semantic_evidence is not None
                                else None
                            ),
                            approval_status=(
                                semantic_evidence.authority.approval_status
                                if semantic_evidence is not None
                                else None
                            ),
                            authority_reason=(
                                semantic_evidence.authority.authority_reason
                                if semantic_evidence is not None
                                else None
                            ),
                        )
                    )
                elif isinstance(event, UsageInfo):
                    usage = event
            if self.p5_mode == "on" and p5_context is not None:
                citation_diagnostics = validate_p5_citation_contract(
                    "".join(text_parts),
                    context=p5_context,
                    accepted_source_ids=accepted_source_ids,
                )
                root_observation.update(
                    metadata={
                        "p5_citation_coverage": citation_diagnostics.citation_coverage,
                        "p5_numeric_support_accuracy": (
                            citation_diagnostics.numeric_support_accuracy
                        ),
                        "p5_conflict_citations_complete": (
                            citation_diagnostics.complete_conflict_bundle_count
                        ),
                    }
                )
            else:
                validate_answer_citations(
                    "".join(text_parts),
                    evidence_by_alias=evidence_by_alias,
                    accepted_source_ids=accepted_source_ids,
                )
        except CitationValidationError as exc:
            LOGGER.warning(
                "Citation validation rejected an answer for conversation %s",
                context.conversation_id,
                exc_info=True,
            )
            if self.p5_mode == "on":
                safe_answer = no_answer_message(
                    p5_context.no_answer_reason
                    if p5_context and p5_context.no_answer_reason
                    else NoAnswerReason.LOW_CONFIDENCE_EVIDENCE
                )
                yield AnswerToken(text=safe_answer)
                await self._safe_complete(
                    context,
                    content=safe_answer,
                    model=None,
                    tokens=usage,
                )
                root_observation.update(
                    output={
                        "status": "p5_citation_validation_abstention",
                        "citation_validation_code": exc.code,
                        "citation_count": 0,
                    },
                    level="WARNING",
                    status_message="P5 returned controlled uncertainty",
                )
                yield AnswerDone()
                return
            await self._safe_fail(context, CITATION_VALIDATION_FAILURE)
            root_observation.update(
                output={
                    "status": "citation_validation_failed",
                    "citation_count": 0,
                },
                level="ERROR",
                status_message="Citation validation failed",
            )
            yield AnswerFailed(message=CITATION_VALIDATION_FAILURE)
            return
        except Exception:
            LOGGER.exception(
                "Answer generation failed for conversation %s", context.conversation_id
            )
            await self._safe_fail(
                context,
                "Không thể sinh câu trả lời",
                partial_content="".join(text_parts),
            )
            root_observation.update(
                output={
                    "status": "generation_failed",
                    "partial_answer": self.telemetry.content("".join(text_parts)),
                },
                level="ERROR",
                status_message="Answer generation failed",
            )
            yield AnswerFailed(message="Không thể sinh câu trả lời")
            return

        if self.p5_mode == "on":
            yield AnswerToken(text="".join(text_parts))
        for citation_event in pending_citation_events:
            yield citation_event
        persisted_citations = _deduplicate_citations(new_citations)
        await self._safe_complete(
            context,
            content="".join(text_parts),
            model=self.chat_model_name,
            tokens=usage,
            citations=persisted_citations,
        )
        root_observation.update(
            output={
                "status": "completed",
                "answer": self.telemetry.content("".join(text_parts)),
                "citation_count": len(persisted_citations),
                "retrieval_path": "structured" if use_structured else "vector",
                "input_tokens": usage.input_tokens if usage else None,
                "output_tokens": usage.output_tokens if usage else None,
            }
        )
        yield AnswerDone()

    async def _safe_complete(
        self,
        context: ChatContext,
        *,
        content: str,
        model: str | None,
        tokens: UsageInfo | None,
        citations: tuple[NewCitation, ...] = (),
    ) -> None:
        try:
            with self.telemetry.observe(
                "chat.persist_answer",
                as_type="tool",
                input={
                    "assistant_message_id": str(context.assistant_message_id),
                    "content": self.telemetry.content(content),
                    "model": model,
                    "citation_count": len(citations),
                },
            ) as observation:
                await self.chat_repository.complete_assistant_message(
                    context.assistant_message_id,
                    context.notebook_id,
                    content=content,
                    model=model,
                    input_tokens=tokens.input_tokens if tokens else None,
                    output_tokens=tokens.output_tokens if tokens else None,
                )
                await self.chat_repository.insert_citations(
                    owner_id=context.owner_id,
                    notebook_id=context.notebook_id,
                    message_id=context.assistant_message_id,
                    citations=citations,
                )
                observation.update(output={"persisted": True})
        except ChatRepositoryError:
            LOGGER.exception(
                "Failed to persist completed answer for conversation %s",
                context.conversation_id,
            )

    async def _safe_fail(
        self,
        context: ChatContext,
        error_message: str,
        *,
        partial_content: str | None = None,
    ) -> None:
        try:
            with self.telemetry.observe(
                "chat.persist_failure",
                as_type="tool",
                input={
                    "assistant_message_id": str(context.assistant_message_id),
                    "error_message": error_message,
                    "partial_content": self.telemetry.content(partial_content),
                },
            ) as observation:
                await self.chat_repository.fail_assistant_message(
                    context.assistant_message_id,
                    context.notebook_id,
                    error_message=error_message,
                    content=partial_content or None,
                )
                observation.update(output={"persisted": True})
        except ChatRepositoryError:
            LOGGER.exception(
                "Failed to persist failed answer for conversation %s",
                context.conversation_id,
            )


__all__ = [
    "ChatContext",
    "ChatService",
    "ChatServiceError",
    "ConversationNotFoundError",
    "NotebookNotFoundError",
]
