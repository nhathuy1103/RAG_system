"""Governance and enterprise knowledge interaction use cases."""

from __future__ import annotations

import asyncio
import logging
import math
import re
from dataclasses import dataclass, replace
from datetime import date
from typing import Final
from uuid import UUID

from app.generation.application.citation_validation import (
    CitationValidationError,
    anchor_grouped_inline_citations,
    build_evidence_aliases,
    validate_answer_citations,
    validate_citation_hit,
    validate_p5_citation_contract,
)
from app.generation.application.enterprise_context import build_enterprise_generation_context
from app.generation.application.evidence_context import (
    EvidenceContextPolicy,
)
from app.generation.domain import CitationHit, TokenChunk, UsageInfo
from app.generation.domain.evidence import GenerationContext, NoAnswerReason
from app.generation.ports import AnswerGeneratorPort
from app.governance.domain.models import (
    AnalyticsSummary,
    AnswerFeedback,
    AnswerReport,
    AskQuestionResult,
    AuditLog,
    ConversationDetail,
    EnterpriseCitation,
    EnterpriseConversation,
    EnterpriseDocumentRelation,
    EnterpriseDocumentRelationEvidence,
    EnterpriseMessage,
    SearchHit,
)
from app.governance.ports.repositories import GovernanceRepository, NewEnterpriseCitation
from app.infrastructure.telemetry import Observation, Telemetry
from app.pipeline.indexing.ports.embedding_provider import EmbeddingProvider
from app.retrieval.adapters.local_sufficiency import KeywordOverlapSufficiencyChecker
from app.retrieval.adapters.mmr_reranker import MaximalMarginalRelevanceReranker
from app.retrieval.application.conversation_query import resolve_conversation_query
from app.retrieval.application.enterprise_evidence import (
    EnterpriseEvidenceDiagnostics,
    select_enterprise_evidence,
)
from app.retrieval.application.query_context import QueryContext, parse_query_context
from app.retrieval.domain.metadata import EvidenceMetadata
from app.retrieval.domain.models import (
    EvidenceChunk,
    RetrievalCandidate,
    RetrievalFilters,
)

LOGGER = logging.getLogger(__name__)

CONTROLLED_NO_ANSWER: Final = (
    "Không tìm thấy đủ bằng chứng trong các tài liệu bạn được phép truy cập để trả lời câu hỏi này."
)
GENERATION_FAILED_ANSWER: Final = "Không thể tạo câu trả lời vào lúc này. Vui lòng thử lại."
_CITATION_RETRY_INSTRUCTION: Final = (
    "\n\nYÊU CẦU SỬA TRÍCH DẪN: Hãy trả lời lại toàn bộ câu hỏi chỉ từ "
    "các nguồn đã cung cấp. Mọi nhận định dùng thông tin từ nguồn phải "
    "có ít nhất một marker [SRC-<số>] hợp lệ ngay sau nhận định. "
    "Nếu kết luận nguồn không có hoặc không đủ dữ liệu được hỏi, nhận định "
    "giới hạn đó cũng phải trích dẫn nguồn đã kiểm tra. "
    "Không được tự tạo nhãn nguồn mới."
)
_RETRIABLE_CITATION_CODES: Final = frozenset(
    {
        "EMPTY_GROUNDED_ANSWER",
        "MISSING_CITATION_MARKER",
        "UNCITED_MATERIAL_STATEMENT",
    }
)
_CANONICAL_BUSINESS_FILTERS: Final = frozenset(
    {
        "document_type",
        "category",
        "domain",
        "department_code",
        "project_code",
        "year",
        "reference_years",
        "year_from",
        "year_to",
        "effective_at",
        "effective_status",
    }
)
_ALLOWED_FILTERS: Final = _CANONICAL_BUSINESS_FILTERS | {"document_id", "metadata"}
_ENTERPRISE_EMBEDDING_DIMENSIONS: Final = 1536
_MAX_CONTEXTUAL_QUERY_CHARS: Final = 4000
_MAX_HISTORY_QUESTION_CHARS: Final = 1000
_DOCUMENT_NUMBER = re.compile(
    r"(?<!\w)[A-ZÀ-ỸĐ]{1,10}(?:[-\s][A-ZÀ-ỸĐ]{1,10})*"
    r"[-\s]?\d{1,6}/\d{4}(?:/[A-ZÀ-ỸĐ0-9.-]{1,20})?(?!\w)",
    re.IGNORECASE,
)
_BROAD_CONTEXT_TERMS = re.compile(
    r"\b(toàn bộ|đầy đủ|quy trình|các bước|điều kiện|ngoại lệ|"
    r"complete|entire|process|steps|conditions|exceptions)\b",
    re.IGNORECASE,
)


class GovernanceValidationError(ValueError):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


@dataclass(frozen=True)
class _GenerationAttempt:
    answer: str
    citations: tuple[NewEnterpriseCitation, ...]
    accepted_source_ids: tuple[str, ...]
    usage: UsageInfo | None


class GovernanceService:
    def __init__(self, repository: GovernanceRepository) -> None:
        self._repository = repository

    async def search(
        self, query: str, *, limit: int, filters: dict[str, object]
    ) -> list[SearchHit]:
        normalized = query.strip()
        if not normalized:
            raise GovernanceValidationError("EMPTY_QUERY", "Search query must not be empty")
        safe_filters = await _route_exact_document_number(
            self._repository,
            normalized,
            _validated_filters(filters),
        )
        query_context = parse_query_context(
            normalized,
            owner_id="authenticated-enterprise-user",
            notebook_id=None,
        )
        safe_filters = _query_temporal_filters(query_context, safe_filters)
        return await self._repository.search(
            query_context.retrieval_query,
            limit=limit,
            filters=safe_filters,
        )

    async def create_conversation(self, title: str | None) -> EnterpriseConversation:
        normalized = title.strip() if title else None
        return await self._repository.create_conversation(normalized or None)

    async def get_conversation(self, conversation_id: UUID) -> ConversationDetail | None:
        return await self._repository.get_conversation(conversation_id)

    async def append_user_message(self, conversation_id: UUID, content: str) -> EnterpriseMessage:
        normalized = content.strip()
        if not normalized:
            raise GovernanceValidationError("EMPTY_MESSAGE", "Message content must not be empty")
        return await self._repository.append_user_message(conversation_id, normalized)

    async def submit_feedback(
        self,
        message_id: UUID,
        user_id: UUID,
        *,
        rating: str,
        comment: str | None,
    ) -> AnswerFeedback:
        return await self._repository.submit_feedback(
            message_id, user_id, rating=rating, comment=comment
        )

    async def submit_report(
        self,
        message_id: UUID,
        user_id: UUID,
        *,
        reason_code: str,
        details: str | None,
    ) -> AnswerReport:
        normalized = reason_code.strip().upper()
        if not normalized:
            raise GovernanceValidationError("REPORT_REASON_REQUIRED", "Report reason is required")
        return await self._repository.submit_report(
            message_id, user_id, reason_code=normalized, details=details
        )

    async def list_audit_logs(self, *, limit: int, offset: int) -> tuple[list[AuditLog], int]:
        return await self._repository.list_audit_logs(limit=limit, offset=offset)

    async def analytics_summary(self) -> AnalyticsSummary:
        return await self._repository.analytics_summary()

    async def list_answer_reports(
        self, *, report_status: str | None, limit: int, offset: int
    ) -> tuple[list[AnswerReport], int]:
        return await self._repository.list_answer_reports(
            report_status=report_status, limit=limit, offset=offset
        )

    async def resolve_answer_report(
        self, report_id: UUID, *, status: str, resolution_note: str
    ) -> AnswerReport | None:
        note = resolution_note.strip()
        if not note:
            raise GovernanceValidationError(
                "RESOLUTION_NOTE_REQUIRED", "A resolution note is required"
            )
        return await self._repository.resolve_answer_report(
            report_id, status=status, resolution_note=note
        )

    async def list_document_relations(
        self,
        *,
        relation_status: str | None,
        limit: int,
        offset: int,
    ) -> tuple[list[EnterpriseDocumentRelation], int]:
        return await self._repository.list_document_relations(
            relation_status=relation_status,
            limit=limit,
            offset=offset,
        )

    async def get_document_relation_evidence(
        self, relation_id: UUID
    ) -> EnterpriseDocumentRelationEvidence | None:
        return await self._repository.get_document_relation_evidence(relation_id)

    async def resolve_document_relation(
        self,
        relation_id: UUID,
        *,
        action: str,
        reason: str | None,
        expected_updated_at: str | None,
    ) -> EnterpriseDocumentRelation:
        normalized_action = action.strip().lower()
        allowed_actions = {
            "confirm_duplicate",
            "mark_version",
            "confirm_conflict",
            "keep_separate",
            "prefer_source",
            "prefer_target",
            "dismiss",
            "defer_review",
        }
        if normalized_action not in allowed_actions:
            raise GovernanceValidationError(
                "INVALID_RELATION_ACTION",
                "Relation resolution action is invalid",
            )
        normalized_reason = reason.strip() if reason else None
        if normalized_action != "defer_review" and not normalized_reason:
            raise GovernanceValidationError(
                "RELATION_REASON_REQUIRED",
                "A reason is required for this relation decision",
            )
        return await self._repository.resolve_document_relation(
            relation_id,
            action=normalized_action,
            reason=normalized_reason,
            expected_updated_at=expected_updated_at,
        )


class EnterpriseQuestionService:
    """One non-streaming, version-bound Enterprise RAG turn.

    Retrieval is delegated exclusively to the ACL/lifecycle-gated PostgreSQL
    RPC. The generator is treated as untrusted: every citation event and final
    marker is checked against the exact evidence tuple from this turn before
    the atomic answer transaction is allowed to persist it.
    """

    def __init__(
        self,
        repository: GovernanceRepository,
        answer_generator: AnswerGeneratorPort,
        *,
        answer_repository: GovernanceRepository | None = None,
        model_name: str,
        retrieval_top_k: int = 6,
        minimum_score: float | None = None,
        sufficiency_checker: KeywordOverlapSufficiencyChecker | None = None,
        embedding_provider: EmbeddingProvider | None = None,
        sparse_top_k: int | None = None,
        dense_top_k: int | None = None,
        rrf_rank_constant: int = 60,
        mmr_lambda: float = 0.7,
        max_chunks_per_document: int = 2,
        history_limit: int = 6,
        rag_mode: str = "off",
        context_max_items: int = 10,
        context_max_characters: int = 12_000,
        context_characters_per_token: float = 4.0,
        near_duplicate_representatives: int = 1,
        telemetry: Telemetry | None = None,
    ) -> None:
        if not model_name.strip():
            raise ValueError("model_name must not be blank")
        if retrieval_top_k <= 0:
            raise ValueError("retrieval_top_k must be > 0")
        if sparse_top_k is not None and sparse_top_k <= 0:
            raise ValueError("sparse_top_k must be > 0")
        if dense_top_k is not None and dense_top_k <= 0:
            raise ValueError("dense_top_k must be > 0")
        if rrf_rank_constant <= 0:
            raise ValueError("rrf_rank_constant must be > 0")
        if max_chunks_per_document <= 0:
            raise ValueError("max_chunks_per_document must be > 0")
        if history_limit <= 0:
            raise ValueError("history_limit must be > 0")
        if rag_mode not in {"off", "shadow", "on"}:
            raise ValueError("rag_mode must be off, shadow, or on")
        self._repository = repository
        self._answer_repository = answer_repository or repository
        self._answer_generator = answer_generator
        self._model_name = model_name
        self._retrieval_top_k = retrieval_top_k
        self._minimum_score = minimum_score
        self._embedding_provider = embedding_provider
        self._sparse_top_k = sparse_top_k or retrieval_top_k
        self._dense_top_k = dense_top_k or retrieval_top_k
        self._rrf_rank_constant = rrf_rank_constant
        self._max_chunks_per_document = max_chunks_per_document
        self._history_limit = history_limit
        self._rag_mode = rag_mode
        self._near_duplicate_representatives = near_duplicate_representatives
        self._context_policy = EvidenceContextPolicy(
            max_evidence_items=context_max_items,
            max_characters=context_max_characters,
            characters_per_token=context_characters_per_token,
            max_near_duplicate_representatives=near_duplicate_representatives,
            version="p6-enterprise-generation-context-v1",
        )
        self._telemetry = telemetry or Telemetry()
        self._reranker = MaximalMarginalRelevanceReranker(lambda_param=mmr_lambda)
        self._sufficiency_checker = sufficiency_checker or KeywordOverlapSufficiencyChecker(
            min_overlap_ratio=0.3
        )

    async def ask_question(
        self,
        conversation_id: UUID,
        question: str,
        *,
        filters: dict[str, object],
        trace_id: str | None = None,
        user_id: UUID | None = None,
    ) -> AskQuestionResult:
        langfuse_trace_id = (
            self._telemetry.create_trace_id(seed=f"enterprise-question:{trace_id}")
            if trace_id
            else self._telemetry.create_trace_id()
        )
        with self._telemetry.observe(
            "enterprise.answer_question",
            as_type="chain",
            trace_id=langfuse_trace_id,
            input={
                "question": self._telemetry.content(question),
                "conversation_id": str(conversation_id),
                "requested_filter_fields": sorted(filters),
            },
            metadata={
                "request_id": trace_id or "",
                "conversation_id": str(conversation_id),
                "requested_filter_fields": ",".join(sorted(filters)) or "none",
                "retrieval_top_k": self._retrieval_top_k,
                "sparse_top_k": self._sparse_top_k,
                "dense_top_k": self._dense_top_k,
                "chat_model": self._model_name,
                "rag_p5_mode": self._rag_mode,
            },
            user_id=str(user_id) if user_id else None,
            session_id=str(conversation_id),
            tags=("rag", "enterprise", "chat"),
            trace_name="enterprise-rag-chat",
        ) as observation:
            result = await self._ask_question(
                conversation_id,
                question,
                filters=filters,
                trace_id=trace_id,
                user_id=user_id,
                root_observation=observation,
            )
            cited_document_ids = sorted({str(item.document_id) for item in result.citations})
            cited_version_ids = sorted({str(item.document_version_id) for item in result.citations})
            observation.update(
                metadata={
                    "answer_status": result.assistant_message.answer_status,
                    "retrieval_strategy": result.retrieval_strategy,
                    "candidate_count": result.candidate_count,
                    "evidence_count": result.evidence_count,
                    "gate_reason": result.gate_reason or "none",
                    "error_code": result.error_code or "none",
                    "citation_count": len(result.citations),
                    "cited_document_ids": ",".join(cited_document_ids) or "none",
                    "cited_document_version_ids": ",".join(cited_version_ids) or "none",
                },
                output={
                    "answer": self._telemetry.content(result.assistant_message.content),
                    "answer_status": result.assistant_message.answer_status,
                    "retrieval_strategy": result.retrieval_strategy,
                    "candidate_count": result.candidate_count,
                    "evidence_count": result.evidence_count,
                    "gate_reason": result.gate_reason,
                    "error_code": result.error_code,
                    "citation_count": len(result.citations),
                    "document_ids": cited_document_ids,
                    "document_version_ids": cited_version_ids,
                },
            )
            return result

    async def _ask_question(
        self,
        conversation_id: UUID,
        question: str,
        *,
        filters: dict[str, object],
        trace_id: str | None,
        user_id: UUID | None,
        root_observation: Observation,
    ) -> AskQuestionResult:
        normalized = question.strip()
        if not normalized:
            raise GovernanceValidationError("EMPTY_MESSAGE", "Message content must not be empty")
        if len(normalized) > _MAX_CONTEXTUAL_QUERY_CHARS:
            raise GovernanceValidationError(
                "MESSAGE_TOO_LONG",
                "Message content must not exceed 4000 characters",
            )
        safe_filters = await _route_exact_document_number(
            self._repository,
            normalized,
            _validated_filters(filters),
        )
        root_observation.update(metadata=_filter_trace_metadata(safe_filters))
        conversation = await self._repository.get_conversation(conversation_id)
        if conversation is None:
            raise GovernanceValidationError(
                "CONVERSATION_NOT_FOUND",
                "Conversation was not found or is not accessible",
            )
        contextual_query, sparse_query, sufficiency_query = _contextual_queries(
            normalized,
            conversation.messages,
            history_limit=self._history_limit,
        )
        owner_id = str(user_id or conversation.conversation.user_id)
        query_context = resolve_conversation_query(
            normalized,
            tuple(message.content for message in conversation.messages if message.role == "USER"),
            owner_id=owner_id,
            notebook_id=None,
            history_limit=self._history_limit,
        )
        p6_filters = _query_temporal_filters(query_context, safe_filters)
        active_query = query_context.retrieval_query if self._rag_mode == "on" else contextual_query
        active_sparse_query = (
            query_context.retrieval_query if self._rag_mode == "on" else sparse_query
        )
        active_filters = p6_filters if self._rag_mode == "on" else safe_filters
        user_message = await self._repository.append_user_message(
            conversation_id,
            normalized,
        )
        try:
            metadata_before_retrieval = {
                **_filter_trace_metadata(safe_filters),
                "metadata_stage": "before_retrieval",
                "query_mode": (
                    "p6_resolved"
                    if self._rag_mode == "on"
                    else ("contextual" if contextual_query != normalized else "direct")
                ),
                "raw_query": normalized,
                "resolved_query": query_context.retrieval_query,
                "query_intent": str(query_context.intent),
                "reference_years": ",".join(str(value) for value in query_context.reference_years)
                or "none",
                "inherited_dimensions": ",".join(query_context.inherited_dimensions) or "none",
                "rag_p5_mode": self._rag_mode,
                "history_message_count": min(
                    len(conversation.messages),
                    self._history_limit,
                ),
                "retrieval_top_k": self._retrieval_top_k,
                "sparse_top_k": self._sparse_top_k,
                "dense_top_k": self._dense_top_k,
                "dense_enabled": self._embedding_provider is not None,
                "embedding_model": (
                    getattr(self._embedding_provider, "model_name", "unknown")
                    if self._embedding_provider is not None
                    else "disabled"
                ),
                "acl_scope": "published_active_readable_documents",
            }
            with self._telemetry.observe(
                "retrieve-enterprise-context",
                as_type="retriever",
                input={
                    "query": self._telemetry.content(active_query),
                    "sparse_query": self._telemetry.content(active_sparse_query),
                    "metadata_before_retrieval": {
                        "effective_filters": dict(active_filters),
                        "effective_filter_fields": sorted(active_filters),
                        "available_filter_fields": sorted(
                            _CANONICAL_BUSINESS_FILTERS | {"document_id"}
                        ),
                    },
                },
                metadata=metadata_before_retrieval,
            ) as retrieval_observation:
                hits, retrieval_strategy = await self._retrieve_hits(
                    active_query,
                    sparse_query=active_sparse_query,
                    filters=active_filters,
                )
                shadow_hits: list[SearchHit] | None = None
                if self._rag_mode == "shadow":
                    shadow_hits, _ = await self._retrieve_hits(
                        query_context.retrieval_query,
                        sparse_query=query_context.retrieval_query,
                        filters=p6_filters,
                    )
                retrieval_observation.update(
                    metadata={
                        "metadata_stage": "after_retrieval",
                        "retrieval_strategy": retrieval_strategy,
                        "candidate_count": len(hits),
                        "candidate_document_count": len({hit.document_id for hit in hits}),
                    },
                    output={
                        "retrieval_strategy": retrieval_strategy,
                        "candidate_count": len(hits),
                        "candidate_document_count": len({hit.document_id for hit in hits}),
                        "candidate_chunk_ids": [str(hit.chunk_id) for hit in hits],
                    },
                )
        except Exception:
            LOGGER.exception(
                "Enterprise retrieval failed",
                extra={"conversation_id": str(conversation_id)},
            )
            return await self._complete_failed(
                conversation_id,
                user_message=user_message,
                evidence_count=0,
                candidate_count=0,
                trace_id=trace_id,
                error_code="RETRIEVAL_FAILED",
                retrieval_strategy="secure_retrieval_failed",
            )
        candidate_count = len(hits)
        generation_context: GenerationContext | None = None
        p6_diagnostics: EnterpriseEvidenceDiagnostics | None = None
        evidence, hits_by_chunk, gate_reason = _build_enterprise_evidence(
            hits,
            minimum_score=None,
        )
        sufficiency_verdict = None
        if self._rag_mode in {"shadow", "on"}:
            proposed_hits = hits if self._rag_mode == "on" else (shadow_hits or [])
            try:
                (
                    proposed_evidence,
                    proposed_hits_by_chunk,
                    proposed_gate,
                    proposed_context,
                    p6_diagnostics,
                ) = await self._select_p6_context(
                    query_context,
                    proposed_hits,
                    filters=p6_filters,
                    owner_id=owner_id,
                )
            except Exception:
                LOGGER.exception(
                    "Enterprise P6 query-time policy failed",
                    extra={
                        "conversation_id": str(conversation_id),
                        "failure_category": "RELATION_POLICY_ERROR",
                    },
                )
                if self._rag_mode == "on":
                    return await self._complete_failed(
                        conversation_id,
                        user_message=user_message,
                        evidence_count=0,
                        candidate_count=candidate_count,
                        trace_id=trace_id,
                        error_code="RELATION_POLICY_ERROR",
                        retrieval_strategy="secure_p6_policy_failed",
                    )
            else:
                if self._rag_mode == "on":
                    evidence = proposed_evidence
                    hits_by_chunk = proposed_hits_by_chunk
                    gate_reason = proposed_gate
                    generation_context = proposed_context
                    retrieval_strategy += "_p6_relation_context"
                root_observation.update(
                    metadata={
                        "p6_proposed_evidence_ids": ",".join(p6_diagnostics.final_ids) or "none",
                        "p6_suppressed_duplicate_ids": ",".join(
                            p6_diagnostics.duplicate_suppressed_ids
                        )
                        or "none",
                        "p6_temporal_reserved_ids": ",".join(p6_diagnostics.temporal_reserved_ids)
                        or "none",
                        "p6_conflict_reserved_ids": ",".join(p6_diagnostics.conflict_reserved_ids)
                        or "none",
                        "p6_final_document_ids": ",".join(p6_diagnostics.final_document_ids)
                        or "none",
                        "p6_final_years": ",".join(
                            str(value) for value in p6_diagnostics.final_years
                        )
                        or "none",
                        "p6_temporal_completeness": (
                            proposed_context.diagnostics.temporal_completeness
                        ),
                        "p6_conflict_completeness": (
                            proposed_context.diagnostics.conflict_pair_completeness
                        ),
                    }
                )

        if gate_reason is None and self._rag_mode != "on":
            reranked = self._reranker.rerank(
                contextual_query,
                evidence,
                top_k=len(evidence),
            )
            evidence = _limit_chunks_per_document(
                reranked,
                top_k=self._retrieval_top_k,
                max_chunks_per_document=self._max_chunks_per_document,
            )
            hits_by_chunk = {
                UUID(candidate.chunk.id): hits_by_chunk[UUID(candidate.chunk.id)]
                for candidate in evidence
            }
            expanded_hits = await self._expand_context_if_needed(
                normalized,
                list(hits_by_chunk.values()),
            )
            if expanded_hits is not None:
                evidence, hits_by_chunk, gate_reason = _build_enterprise_evidence(
                    expanded_hits,
                    minimum_score=None,
                )
            verdict = self._sufficiency_checker.check(sufficiency_query, evidence)
            sufficiency_verdict = verdict
            if not verdict.sufficient:
                LOGGER.info(
                    "Enterprise keyword sufficiency shadow check would have rejected evidence",
                    extra={
                        "conversation_id": str(conversation_id),
                        "evidence_count": len(evidence),
                        "missing_keywords": verdict.missing or "",
                    },
                )

        evidence_document_count = len({candidate.chunk.document_id for candidate in evidence})
        root_observation.update(
            metadata={
                "retrieval_candidate_count": candidate_count,
                "evidence_count_after_selection": len(evidence),
                "evidence_document_count": evidence_document_count,
                "evidence_gate_reason": gate_reason or "passed",
                "keyword_sufficiency_mode": "shadow",
                "keyword_sufficiency_sufficient": (
                    sufficiency_verdict.sufficient if sufficiency_verdict is not None else None
                ),
                "keyword_sufficiency_missing": (
                    (sufficiency_verdict.missing or "")[:500]
                    if sufficiency_verdict is not None
                    else ""
                ),
            }
        )

        if gate_reason is not None:
            LOGGER.info(
                "Enterprise evidence gate returned a controlled no-answer: %s",
                gate_reason,
                extra={"conversation_id": str(conversation_id)},
            )
            assistant, citations = await self._answer_repository.complete_answer(
                conversation_id,
                content=CONTROLLED_NO_ANSWER,
                answer_status="CONTROLLED_NO_ANSWER",
                model=None,
                input_tokens=None,
                output_tokens=None,
                error_code=gate_reason.upper(),
                trace_id=trace_id,
                citations=(),
            )
            return AskQuestionResult(
                user_message=user_message,
                assistant_message=assistant,
                citations=citations,
                retrieval_strategy=retrieval_strategy,
                evidence_count=len(evidence),
                candidate_count=candidate_count,
                gate_reason=gate_reason,
                error_code=gate_reason.upper(),
                trace_id=trace_id,
            )

        aliases = build_evidence_aliases(evidence)
        usage: UsageInfo | None = None
        completion_error_code: str | None = None
        generation_outcome = "generated"
        citation_attempt_count = 1
        try:
            attempt = await self._collect_generation_attempt(
                contextual_query,
                evidence=evidence,
                evidence_by_alias=aliases,
                hits_by_chunk=hits_by_chunk,
                generation_context=generation_context,
            )
            usage = attempt.usage
            try:
                _validate_generation_attempt(
                    attempt,
                    evidence_by_alias=aliases,
                    generation_context=generation_context,
                )
            except CitationValidationError as first_error:
                if first_error.code not in _RETRIABLE_CITATION_CODES:
                    raise
                root_observation.update(metadata={"citation_first_error_code": first_error.code})
                citation_attempt_count = 2
                LOGGER.info(
                    "Enterprise generated answer had no usable citation; retrying once",
                    extra={
                        "conversation_id": str(conversation_id),
                        "citation_error_code": first_error.code,
                    },
                )
                retry_attempt = await self._collect_generation_attempt(
                    _citation_retry_question(contextual_query, aliases),
                    evidence=evidence,
                    evidence_by_alias=aliases,
                    hits_by_chunk=hits_by_chunk,
                    generation_context=generation_context,
                )
                usage = _merge_usage(attempt.usage, retry_attempt.usage)
                try:
                    _validate_generation_attempt(
                        retry_attempt,
                        evidence_by_alias=aliases,
                        generation_context=generation_context,
                    )
                except CitationValidationError as retry_error:
                    if retry_error.code not in _RETRIABLE_CITATION_CODES:
                        raise
                    root_observation.update(
                        metadata={
                            "citation_first_error_code": first_error.code,
                            "citation_retry_error_code": retry_error.code,
                        }
                    )
                    answer, pending_citations = _grounded_evidence_fallback(
                        evidence,
                        hits_by_chunk=hits_by_chunk,
                    )
                    completion_error_code = "CITATION_FALLBACK_USED"
                    generation_outcome = "citation_fallback_used"
                else:
                    answer = retry_attempt.answer
                    pending_citations = retry_attempt.citations
                    completion_error_code = "CITATION_RETRY_RECOVERED"
                    generation_outcome = "citation_retry_recovered"
            else:
                answer = attempt.answer
                pending_citations = attempt.citations
        except CitationValidationError as exc:
            LOGGER.warning(
                "Enterprise citation validation rejected generated output",
                extra={
                    "conversation_id": str(conversation_id),
                    "citation_error_code": exc.code,
                },
                exc_info=True,
            )
            root_observation.update(
                metadata={
                    "generation_outcome": "citation_integrity_failed",
                    "citation_error_code": exc.code,
                    "citation_attempt_count": citation_attempt_count,
                }
            )
            return await self._complete_failed(
                conversation_id,
                user_message=user_message,
                evidence_count=len(evidence),
                candidate_count=candidate_count,
                trace_id=trace_id,
                error_code="CITATION_VALIDATION_FAILED",
                retrieval_strategy=retrieval_strategy,
            )
        except Exception:
            LOGGER.exception(
                "Enterprise answer generation failed",
                extra={"conversation_id": str(conversation_id)},
            )
            return await self._complete_failed(
                conversation_id,
                user_message=user_message,
                evidence_count=len(evidence),
                candidate_count=candidate_count,
                trace_id=trace_id,
                error_code="GENERATION_FAILED",
                retrieval_strategy=retrieval_strategy,
            )

        root_observation.update(
            metadata={
                "generation_outcome": generation_outcome,
                "citation_attempt_count": citation_attempt_count,
                "persisted_citation_count": len(pending_citations),
            }
        )

        assistant, persisted = await self._answer_repository.complete_answer(
            conversation_id,
            content=answer,
            answer_status="COMPLETED",
            model=self._model_name,
            input_tokens=usage.input_tokens if usage else None,
            output_tokens=usage.output_tokens if usage else None,
            error_code=completion_error_code,
            trace_id=trace_id,
            citations=tuple(pending_citations),
        )
        enriched = tuple(
            _enrich_citation(item, hits_by_chunk.get(item.chunk_id)) for item in persisted
        )
        return AskQuestionResult(
            user_message=user_message,
            assistant_message=assistant,
            citations=enriched,
            retrieval_strategy=retrieval_strategy,
            evidence_count=len(evidence),
            candidate_count=candidate_count,
            gate_reason=None,
            error_code=completion_error_code,
            trace_id=trace_id,
        )

    async def _collect_generation_attempt(
        self,
        question: str,
        *,
        evidence: tuple[RetrievalCandidate, ...],
        evidence_by_alias: dict[str, RetrievalCandidate],
        hits_by_chunk: dict[UUID, SearchHit],
        generation_context: GenerationContext | None = None,
    ) -> _GenerationAttempt:
        text_parts: list[str] = []
        accepted_source_ids: list[str] = []
        pending_citations: list[NewEnterpriseCitation] = []
        usage: UsageInfo | None = None
        stream_kwargs: dict[str, object] = {
            "question": question,
            "evidence": evidence,
        }
        if generation_context is not None:
            stream_kwargs["generation_context"] = generation_context
        async for event in self._answer_generator.stream(**stream_kwargs):  # type: ignore[arg-type]
            if isinstance(event, TokenChunk):
                text_parts.append(event.text)
            elif isinstance(event, CitationHit):
                candidate = validate_citation_hit(
                    event,
                    evidence_by_alias=evidence_by_alias,
                    accepted_source_ids=accepted_source_ids,
                )
                accepted_source_ids.append(event.source_id)
                hit = hits_by_chunk[UUID(candidate.chunk.id)]
                pending_citations.append(_new_enterprise_citation(hit, ordinal=event.ordinal))
            elif isinstance(event, UsageInfo):
                usage = event
        return _GenerationAttempt(
            answer=anchor_grouped_inline_citations("".join(text_parts)),
            citations=tuple(pending_citations),
            accepted_source_ids=tuple(accepted_source_ids),
            usage=usage,
        )

    async def _select_p6_context(
        self,
        query_context: QueryContext,
        hits: list[SearchHit],
        *,
        filters: dict[str, object],
        owner_id: str,
    ) -> tuple[
        tuple[RetrievalCandidate, ...],
        dict[UUID, SearchHit],
        str | None,
        GenerationContext,
        EnterpriseEvidenceDiagnostics,
    ]:
        candidates, hits_by_chunk, gate = _build_enterprise_evidence(
            hits,
            minimum_score=None,
        )
        retrieval_filters = RetrievalFilters(
            owner_id=owner_id,
            document_ids=(
                (str(filters["document_id"]),) if filters.get("document_id") is not None else None
            ),
        )
        enricher = getattr(self._repository, "enrich_relations", None)
        if candidates and enricher is not None:
            candidates = await enricher(candidates, retrieval_filters)
        selection = select_enterprise_evidence(
            query_context,
            candidates,
            filters=retrieval_filters,
            top_k=self._retrieval_top_k,
            max_chunks_per_document=self._max_chunks_per_document,
            mmr_lambda=self._reranker.lambda_param,
            max_near_duplicate_representatives=self._near_duplicate_representatives,
        )
        selected_hits = {
            UUID(item.chunk.id): hits_by_chunk[UUID(item.chunk.id)]
            for item in selection.evidence
            if UUID(item.chunk.id) in hits_by_chunk
        }
        context = build_enterprise_generation_context(
            query_context,
            selection.evidence,
            authorized_document_ids=frozenset(item.chunk.document_id for item in candidates),
            policy=self._context_policy,
        )
        selected = context.candidates
        selected_hits = {
            UUID(item.chunk.id): selected_hits[UUID(item.chunk.id)]
            for item in selected
            if UUID(item.chunk.id) in selected_hits
        }
        if gate is None and not selected:
            gate = (
                NoAnswerReason.TEMPORAL_EVIDENCE_MISSING.value.casefold()
                if query_context.reference_years
                else NoAnswerReason.NO_RELEVANT_EVIDENCE.value.casefold()
            )
        if gate is None and context.no_answer_reason is not None:
            gate = context.no_answer_reason.value.casefold()
        return selected, selected_hits, gate, context, selection.diagnostics

    async def _complete_failed(
        self,
        conversation_id: UUID,
        *,
        user_message: EnterpriseMessage,
        evidence_count: int,
        candidate_count: int,
        trace_id: str | None,
        error_code: str,
        retrieval_strategy: str,
    ) -> AskQuestionResult:
        assistant, citations = await self._answer_repository.complete_answer(
            conversation_id,
            content=GENERATION_FAILED_ANSWER,
            answer_status="FAILED",
            model=None,
            input_tokens=None,
            output_tokens=None,
            error_code=error_code,
            trace_id=trace_id,
            citations=(),
        )
        return AskQuestionResult(
            user_message=user_message,
            assistant_message=assistant,
            citations=citations,
            retrieval_strategy=retrieval_strategy,
            evidence_count=evidence_count,
            candidate_count=candidate_count,
            gate_reason=None,
            error_code=error_code,
            trace_id=trace_id,
        )

    async def _retrieve_hits(
        self,
        query: str,
        *,
        sparse_query: str,
        filters: dict[str, object],
    ) -> tuple[list[SearchHit], str]:
        sparse_task = asyncio.create_task(
            self._repository.search(
                sparse_query,
                limit=self._sparse_top_k,
                filters=filters,
            )
        )
        query_embedding: list[float] | None = None
        if self._embedding_provider is not None:
            try:
                vectors = await asyncio.to_thread(self._embedding_provider.embed, [query])
                if len(vectors) != 1:
                    raise ValueError("Query embedding provider returned an invalid count")
                query_embedding = [float(value) for value in vectors[0]]
                if len(query_embedding) != _ENTERPRISE_EMBEDDING_DIMENSIONS or not all(
                    math.isfinite(value) for value in query_embedding
                ):
                    raise ValueError("Query embedding has an invalid shape or value")
            except Exception:
                LOGGER.warning(
                    "Enterprise dense query embedding failed; using sparse retrieval",
                    exc_info=True,
                )

        sparse_hits: list[SearchHit] | None
        sparse_error: Exception | None = None
        try:
            sparse_hits = await sparse_task
        except Exception as exc:
            sparse_hits = None
            sparse_error = exc

        dense_hits: list[SearchHit] | None = None
        dense_error: Exception | None = None
        if query_embedding is not None:
            try:
                dense_hits = await self._repository.search_dense(
                    query_embedding,
                    limit=self._dense_top_k,
                    filters=filters,
                )
                if self._minimum_score is not None:
                    dense_hits = [hit for hit in dense_hits if hit.score >= self._minimum_score]
            except Exception as exc:
                dense_error = exc
                LOGGER.warning(
                    "Enterprise dense search failed; using sparse retrieval",
                    exc_info=True,
                )

        if sparse_hits is None and dense_hits is None:
            error = sparse_error or dense_error or RuntimeError("No retrieval channel available")
            raise RuntimeError("All Enterprise retrieval channels failed") from error
        if sparse_hits is None:
            LOGGER.warning("Enterprise sparse search failed; using ACL-gated dense results")
            return list(dense_hits or ()), "secure_dense_mmr"
        if dense_hits is None:
            return sparse_hits, "secure_keyword_mmr"
        fused = _fuse_search_hits(
            {"sparse": sparse_hits, "dense": dense_hits},
            top_k=max(self._sparse_top_k, self._dense_top_k),
            rank_constant=self._rrf_rank_constant,
        )
        return fused, "secure_hybrid_rrf_mmr"

    async def _expand_context_if_needed(
        self,
        query: str,
        primary_hits: list[SearchHit],
    ) -> list[SearchHit] | None:
        if not primary_hits or not _should_expand_context(query, primary_hits):
            return None
        expand = getattr(self._repository, "expand_context", None)
        if expand is None:
            return None
        try:
            expanded = await expand(
                tuple(hit.chunk_id for hit in primary_hits),
                sibling_window=1,
                limit=min(self._retrieval_top_k * 3, 30),
            )
        except Exception:
            LOGGER.warning("Enterprise parent/sibling expansion failed", exc_info=True)
            return None
        return _pack_expanded_hits(
            primary_hits,
            expanded,
            top_k=self._retrieval_top_k,
            broad_intent=bool(_BROAD_CONTEXT_TERMS.search(query)),
        )


async def _route_exact_document_number(
    repository: GovernanceRepository,
    query: str,
    filters: dict[str, object],
) -> dict[str, object]:
    if "document_id" in filters:
        return filters
    matched = _DOCUMENT_NUMBER.search(query)
    resolver = getattr(repository, "resolve_document_number", None)
    if matched is None or resolver is None:
        return filters
    try:
        document_ids = await resolver(matched.group(0))
    except Exception:
        LOGGER.warning("Enterprise exact document-number routing failed", exc_info=True)
        return filters
    unique_ids = tuple(dict.fromkeys(document_ids))
    if len(unique_ids) != 1:
        return filters
    return {**filters, "document_id": str(unique_ids[0])}


def _should_expand_context(query: str, hits: list[SearchHit]) -> bool:
    if _BROAD_CONTEXT_TERMS.search(query):
        return True
    parent_counts: dict[str, int] = {}
    for hit in hits:
        parent_id = str(hit.metadata.get("parent_id") or "").strip()
        if parent_id:
            parent_counts[parent_id] = parent_counts.get(parent_id, 0) + 1
    return any(count >= 2 for count in parent_counts.values())


def _pack_expanded_hits(
    primary_hits: list[SearchHit],
    expanded_hits: list[SearchHit],
    *,
    top_k: int,
    broad_intent: bool,
) -> list[SearchHit]:
    expanded_by_id = {hit.chunk_id: hit for hit in expanded_hits}
    refreshed: list[SearchHit] = []
    primary_ids = {hit.chunk_id for hit in primary_hits}
    for primary in primary_hits:
        candidate = expanded_by_id.get(primary.chunk_id)
        if (
            candidate is not None
            and candidate.document_id == primary.document_id
            and candidate.document_version_id == primary.document_version_id
            and candidate.content == primary.content
        ):
            refreshed.append(replace(candidate, score=primary.score))
        else:
            refreshed.append(primary)

    sibling_budget = min(2 if broad_intent else 1, max(top_k - 1, 0))
    siblings = [
        hit
        for hit in expanded_hits
        if hit.chunk_id not in primary_ids
        and str(hit.metadata.get("expansion_kind") or "") == "sibling"
    ][:sibling_budget]
    if not siblings:
        return refreshed[:top_k]

    room = max(top_k - len(refreshed), 0)
    append_count = min(room, len(siblings))
    packed = [*refreshed, *siblings[:append_count]]
    remaining = siblings[append_count:]
    if remaining:
        keep_count = max(top_k - len(remaining), 1)
        packed = [*refreshed[:keep_count], *remaining]
    floor_score = min((hit.score for hit in primary_hits), default=0.0)
    return [
        replace(hit, score=floor_score * 0.95) if hit.chunk_id not in primary_ids else hit
        for hit in packed[:top_k]
    ]


def _contextual_queries(
    question: str,
    messages: tuple[EnterpriseMessage, ...],
    *,
    history_limit: int,
) -> tuple[str, str, str]:
    previous_questions = [
        message.content.strip()[:_MAX_HISTORY_QUESTION_CHARS]
        for message in messages
        if message.role == "USER" and message.content.strip()
    ][-history_limit:]
    if not previous_questions:
        return question, question, question
    available = max(_MAX_CONTEXTUAL_QUERY_CHARS - len(question) - 80, 0)
    selected: list[str] = []
    for previous in reversed(previous_questions):
        if available <= 0:
            break
        bounded = previous[:available]
        selected.append(bounded)
        available -= len(bounded) + 3
    selected.reverse()
    if not selected:
        return question, question, question
    history = " | ".join(selected)
    contextual = f"Ngữ cảnh các câu hỏi trước: {history}\nCâu hỏi hiện tại: {question}"
    sparse = " OR ".join([*selected, question])
    sufficiency = " ".join([*selected, question])
    return contextual, sparse, sufficiency


def _fuse_search_hits(
    rankings: dict[str, list[SearchHit]],
    *,
    top_k: int,
    rank_constant: int,
) -> list[SearchHit]:
    scores: dict[UUID, float] = {}
    canonical: dict[UUID, SearchHit] = {}
    for hits in rankings.values():
        seen: set[UUID] = set()
        for rank, hit in enumerate(hits, start=1):
            if not math.isfinite(hit.score):
                raise ValueError("Retrieval channel returned a non-finite score")
            if hit.chunk_id in seen:
                continue
            seen.add(hit.chunk_id)
            existing = canonical.get(hit.chunk_id)
            if existing is not None and (
                existing.document_id != hit.document_id
                or existing.document_version_id != hit.document_version_id
                or existing.content != hit.content
            ):
                raise ValueError("Retrieval channels returned conflicting chunk identity")
            canonical.setdefault(hit.chunk_id, hit)
            scores[hit.chunk_id] = scores.get(hit.chunk_id, 0.0) + 1.0 / (rank_constant + rank)
    ordered = sorted(scores, key=lambda chunk_id: (-scores[chunk_id], str(chunk_id)))
    return [replace(canonical[chunk_id], score=scores[chunk_id]) for chunk_id in ordered[:top_k]]


def _limit_chunks_per_document(
    candidates: tuple[RetrievalCandidate, ...],
    *,
    top_k: int,
    max_chunks_per_document: int,
) -> tuple[RetrievalCandidate, ...]:
    """Prefer document diversity, then backfill so the cap never drops evidence.

    ``max_chunks_per_document`` is a diversity target rather than a hard gate.
    A query whose useful evidence lives in one document can therefore still
    use the full ``top_k`` context budget.
    """

    if top_k <= 0 or not candidates:
        return ()
    if len({candidate.chunk.document_id for candidate in candidates}) <= 1:
        return candidates[:top_k]

    selected: list[RetrievalCandidate] = []
    deferred: list[RetrievalCandidate] = []
    counts: dict[str, int] = {}
    for candidate in candidates:
        document_id = candidate.chunk.document_id
        if counts.get(document_id, 0) >= max_chunks_per_document:
            deferred.append(candidate)
            continue
        selected.append(candidate)
        counts[document_id] = counts.get(document_id, 0) + 1
        if len(selected) >= top_k:
            break
    for candidate in deferred:
        if len(selected) >= top_k:
            break
        selected.append(candidate)
    return tuple(selected)


def _validate_generation_attempt(
    attempt: _GenerationAttempt,
    *,
    evidence_by_alias: dict[str, RetrievalCandidate],
    generation_context: GenerationContext | None = None,
) -> None:
    if generation_context is not None:
        validate_p5_citation_contract(
            attempt.answer,
            context=generation_context,
            accepted_source_ids=attempt.accepted_source_ids,
        )
    else:
        validate_answer_citations(
            attempt.answer,
            evidence_by_alias=evidence_by_alias,
            accepted_source_ids=attempt.accepted_source_ids,
        )


def _new_enterprise_citation(
    hit: SearchHit,
    *,
    ordinal: int,
) -> NewEnterpriseCitation:
    return NewEnterpriseCitation(
        document_id=hit.document_id,
        document_version_id=hit.document_version_id,
        chunk_id=hit.chunk_id,
        quote_text=hit.content,
        citation_order=ordinal,
        page_number=(hit.page_start if hit.page_start is not None and hit.page_start > 0 else None),
        retrieval_score=hit.score,
    )


def _merge_usage(left: UsageInfo | None, right: UsageInfo | None) -> UsageInfo | None:
    if left is None and right is None:
        return None

    def total(field_name: str) -> int | None:
        values = [
            value
            for usage in (left, right)
            if usage is not None
            for value in (getattr(usage, field_name),)
            if value is not None
        ]
        return sum(values) if values else None

    return UsageInfo(
        input_tokens=total("input_tokens"),
        output_tokens=total("output_tokens"),
    )


def _grounded_evidence_fallback(
    evidence: tuple[RetrievalCandidate, ...],
    *,
    hits_by_chunk: dict[UUID, SearchHit],
) -> tuple[str, tuple[NewEnterpriseCitation, ...]]:
    """Return a concise, cited no-answer when citation repair still fails."""

    candidate = evidence[0]
    hit = hits_by_chunk[UUID(candidate.chunk.id)]
    answer = (
        "Chưa tìm thấy đủ bằng chứng trực tiếp để trả lời câu hỏi này một cách "
        "đáng tin cậy. Nguồn gần nhất đã được đính kèm để bạn đối chiếu hoặc "
        "diễn đạt lại câu hỏi cụ thể hơn [SRC-1]."
    )
    return answer, (_new_enterprise_citation(hit, ordinal=1),)


def _citation_retry_question(
    question: str,
    evidence_by_alias: dict[str, RetrievalCandidate],
) -> str:
    valid_markers = ", ".join(f"[{source_id}]" for source_id in evidence_by_alias)
    return (
        f"{question}{_CITATION_RETRY_INSTRUCTION}\n"
        f"Các marker nguồn hợp lệ duy nhất cho lượt này: {valid_markers}."
    )


def _validated_filters(filters: dict[str, object]) -> dict[str, object]:
    unknown = set(filters) - _ALLOWED_FILTERS
    if unknown:
        raise GovernanceValidationError(
            "UNSUPPORTED_SEARCH_FILTER",
            "Unsupported search filter: " + ", ".join(sorted(unknown)),
        )
    normalized = {key: value for key, value in filters.items() if key != "metadata"}
    metadata = filters.get("metadata")
    if metadata is not None and not isinstance(metadata, dict):
        raise GovernanceValidationError(
            "INVALID_METADATA_FILTER",
            "metadata filter must be an object",
        )
    if isinstance(metadata, dict):
        unsupported_metadata = set(metadata) - _CANONICAL_BUSINESS_FILTERS
        if unsupported_metadata:
            raise GovernanceValidationError(
                "UNSUPPORTED_SEARCH_FILTER",
                "Unsupported canonical metadata filter: " + ", ".join(sorted(unsupported_metadata)),
            )
        conflicts = set(metadata).intersection(normalized)
        if conflicts:
            raise GovernanceValidationError(
                "CONFLICTING_SEARCH_FILTER",
                "Search filter is specified twice: " + ", ".join(sorted(conflicts)),
            )
        normalized.update(metadata)
    document_id = normalized.get("document_id")
    if document_id is not None:
        try:
            normalized["document_id"] = str(UUID(str(document_id)))
        except (TypeError, ValueError) as exc:
            raise GovernanceValidationError(
                "INVALID_DOCUMENT_FILTER",
                "document_id filter must be a UUID",
            ) from exc
    for field_name in ("document_type", "department_code", "project_code"):
        if field_name in normalized:
            value = str(normalized[field_name]).strip().upper()
            if not value:
                raise GovernanceValidationError(
                    "INVALID_METADATA_FILTER", f"{field_name} must not be blank"
                )
            normalized[field_name] = value
    for field_name in ("category", "domain"):
        if field_name in normalized:
            value = str(normalized[field_name]).strip()
            if not value:
                raise GovernanceValidationError(
                    "INVALID_METADATA_FILTER", f"{field_name} must not be blank"
                )
            normalized[field_name] = value
    if "year" in normalized:
        raw_year = normalized["year"]
        if isinstance(raw_year, bool):
            year = 0
        else:
            try:
                year = int(str(raw_year))
            except (TypeError, ValueError):
                year = 0
        if not 1900 <= year <= 2100:
            raise GovernanceValidationError(
                "INVALID_METADATA_FILTER", "year must be between 1900 and 2100"
            )
        normalized["year"] = year
    if "reference_years" in normalized:
        raw_years = normalized["reference_years"]
        if not isinstance(raw_years, list | tuple) or not raw_years or len(raw_years) > 20:
            raise GovernanceValidationError(
                "INVALID_METADATA_FILTER",
                "reference_years must contain between 1 and 20 years",
            )
        years: list[int] = []
        for raw_year in raw_years:
            try:
                year = int(str(raw_year))
            except (TypeError, ValueError):
                year = 0
            if not 1900 <= year <= 2100:
                raise GovernanceValidationError(
                    "INVALID_METADATA_FILTER",
                    "reference_years must contain years between 1900 and 2100",
                )
            years.append(year)
        normalized["reference_years"] = list(dict.fromkeys(years))
    for field_name in ("year_from", "year_to"):
        if field_name not in normalized:
            continue
        try:
            year = int(str(normalized[field_name]))
        except (TypeError, ValueError):
            year = 0
        if not 1900 <= year <= 2100:
            raise GovernanceValidationError(
                "INVALID_METADATA_FILTER",
                f"{field_name} must be between 1900 and 2100",
            )
        normalized[field_name] = year
    year_from = normalized.get("year_from")
    year_to = normalized.get("year_to")
    if (
        isinstance(year_from, int)
        and not isinstance(year_from, bool)
        and isinstance(year_to, int)
        and not isinstance(year_to, bool)
        and year_from > year_to
    ):
        raise GovernanceValidationError(
            "INVALID_METADATA_FILTER",
            "year_from must not be greater than year_to",
        )
    if "effective_at" in normalized:
        try:
            normalized["effective_at"] = date.fromisoformat(
                str(normalized["effective_at"])
            ).isoformat()
        except ValueError as exc:
            raise GovernanceValidationError(
                "INVALID_METADATA_FILTER", "effective_at must use YYYY-MM-DD"
            ) from exc
    return normalized


def _query_temporal_filters(
    query: QueryContext,
    filters: dict[str, object],
) -> dict[str, object]:
    """Apply structural temporal intent without fabricating unknown scope."""

    output = dict(filters)
    explicit_filter = any(
        key in output
        for key in (
            "year",
            "reference_years",
            "year_from",
            "year_to",
            "effective_at",
            "effective_status",
        )
    )
    if explicit_filter:
        return output
    if len(query.reference_years) == 1:
        output["year"] = query.reference_years[0]
    elif len(query.reference_years) > 1:
        output["reference_years"] = list(query.reference_years)
    elif query.current_requested:
        output["effective_status"] = "CURRENT"
    return output


def _filter_trace_metadata(filters: dict[str, object]) -> dict[str, object]:
    """Return bounded, canonical filter values suitable for Langfuse metadata."""

    metadata: dict[str, object] = {
        "effective_filter_fields": ",".join(sorted(filters)) or "none",
        "effective_filter_count": len(filters),
    }
    for field_name, value in filters.items():
        if value is None or isinstance(value, dict | list | tuple | set):
            continue
        metadata[f"filter_{field_name}"] = str(value)[:200]
    return metadata


def _build_enterprise_evidence(
    hits: list[SearchHit],
    *,
    minimum_score: float | None,
) -> tuple[
    tuple[RetrievalCandidate, ...],
    dict[UUID, SearchHit],
    str | None,
]:
    if not hits:
        return (), {}, "no_evidence"
    evidence: list[RetrievalCandidate] = []
    hits_by_chunk: dict[UUID, SearchHit] = {}
    for rank, hit in enumerate(hits, start=1):
        if (
            not hit.title.strip()
            or not hit.content.strip()
            or not math.isfinite(hit.score)
            or hit.chunk_id in hits_by_chunk
        ):
            return (), {}, "malformed_evidence"
        if minimum_score is not None and hit.score < minimum_score:
            continue
        metadata = EvidenceMetadata.from_mapping(
            hit.metadata,
            title=hit.title,
            page_number=hit.page_start,
            section_path=hit.section_path,
            document_version_id=str(hit.document_version_id),
        )
        candidate = RetrievalCandidate(
            chunk=EvidenceChunk(
                id=str(hit.chunk_id),
                document_id=str(hit.document_id),
                text=hit.content,
                metadata=metadata,
            ),
            score=hit.score,
            rank=rank,
            source="enterprise_secure_keyword",
        )
        evidence.append(candidate)
        hits_by_chunk[hit.chunk_id] = hit
    if not evidence:
        return (), {}, "below_score_threshold"
    return tuple(evidence), hits_by_chunk, None


def _enrich_citation(
    citation: EnterpriseCitation,
    hit: SearchHit | None,
) -> EnterpriseCitation:
    if hit is None:
        return citation
    return replace(
        citation,
        document_title=hit.title,
        section_path=hit.section_path,
    )
