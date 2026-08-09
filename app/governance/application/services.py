"""Governance and enterprise knowledge interaction use cases."""

from __future__ import annotations

import asyncio
import logging
import math
from dataclasses import replace
from typing import Final
from uuid import UUID

from app.generation.application.citation_validation import (
    CitationValidationError,
    build_evidence_aliases,
    validate_answer_citations,
    validate_citation_hit,
)
from app.generation.domain import CitationHit, TokenChunk, UsageInfo
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
    EnterpriseMessage,
    SearchHit,
)
from app.governance.ports.repositories import GovernanceRepository, NewEnterpriseCitation
from app.pipeline.indexing.ports.embedding_provider import EmbeddingProvider
from app.retrieval.adapters.local_sufficiency import KeywordOverlapSufficiencyChecker
from app.retrieval.adapters.mmr_reranker import MaximalMarginalRelevanceReranker
from app.retrieval.domain.metadata import EvidenceMetadata
from app.retrieval.domain.models import EvidenceChunk, RetrievalCandidate

LOGGER = logging.getLogger(__name__)

CONTROLLED_NO_ANSWER: Final = (
    "Không tìm thấy đủ bằng chứng trong các tài liệu bạn được phép truy cập "
    "để trả lời câu hỏi này."
)
GENERATION_FAILED_ANSWER: Final = "Không thể tạo câu trả lời vào lúc này. Vui lòng thử lại."
_ALLOWED_FILTERS: Final = frozenset({"document_type", "category", "document_id", "metadata"})
_ENTERPRISE_EMBEDDING_DIMENSIONS: Final = 1536
_MAX_CONTEXTUAL_QUERY_CHARS: Final = 4000
_MAX_HISTORY_QUESTION_CHARS: Final = 1000


class GovernanceValidationError(ValueError):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


class GovernanceService:
    def __init__(self, repository: GovernanceRepository) -> None:
        self._repository = repository

    async def search(
        self, query: str, *, limit: int, filters: dict[str, object]
    ) -> list[SearchHit]:
        normalized = query.strip()
        if not normalized:
            raise GovernanceValidationError("EMPTY_QUERY", "Search query must not be empty")
        return await self._repository.search(
            normalized,
            limit=limit,
            filters=_validated_filters(filters),
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
    ) -> AskQuestionResult:
        normalized = question.strip()
        if not normalized:
            raise GovernanceValidationError("EMPTY_MESSAGE", "Message content must not be empty")
        if len(normalized) > _MAX_CONTEXTUAL_QUERY_CHARS:
            raise GovernanceValidationError(
                "MESSAGE_TOO_LONG",
                "Message content must not exceed 4000 characters",
            )
        safe_filters = _validated_filters(filters)
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
        user_message = await self._repository.append_user_message(
            conversation_id,
            normalized,
        )
        try:
            hits, retrieval_strategy = await self._retrieve_hits(
                contextual_query,
                sparse_query=sparse_query,
                filters=safe_filters,
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
                trace_id=trace_id,
                error_code="RETRIEVAL_FAILED",
                retrieval_strategy="secure_retrieval_failed",
            )
        evidence, hits_by_chunk, gate_reason = _build_enterprise_evidence(
            hits,
            minimum_score=None,
        )
        if gate_reason is None:
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
            verdict = self._sufficiency_checker.check(sufficiency_query, evidence)
            if not verdict.sufficient:
                gate_reason = "insufficient_evidence"

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
                trace_id=trace_id,
            )

        aliases = build_evidence_aliases(evidence)
        text_parts: list[str] = []
        accepted_source_ids: list[str] = []
        pending_citations: list[NewEnterpriseCitation] = []
        usage: UsageInfo | None = None
        try:
            async for event in self._answer_generator.stream(
                question=contextual_query,
                evidence=evidence,
            ):
                if isinstance(event, TokenChunk):
                    text_parts.append(event.text)
                elif isinstance(event, CitationHit):
                    candidate = validate_citation_hit(
                        event,
                        evidence_by_alias=aliases,
                        accepted_source_ids=accepted_source_ids,
                    )
                    accepted_source_ids.append(event.source_id)
                    hit = hits_by_chunk[UUID(candidate.chunk.id)]
                    pending_citations.append(
                        NewEnterpriseCitation(
                            document_id=hit.document_id,
                            document_version_id=hit.document_version_id,
                            chunk_id=hit.chunk_id,
                            quote_text=hit.content,
                            citation_order=event.ordinal,
                            page_number=(
                                hit.page_start
                                if hit.page_start is not None and hit.page_start > 0
                                else None
                            ),
                            retrieval_score=hit.score,
                        )
                    )
                elif isinstance(event, UsageInfo):
                    usage = event
            answer = "".join(text_parts)
            validate_answer_citations(
                answer,
                evidence_by_alias=aliases,
                accepted_source_ids=accepted_source_ids,
            )
        except CitationValidationError:
            LOGGER.warning(
                "Enterprise citation validation rejected generated output",
                extra={"conversation_id": str(conversation_id)},
                exc_info=True,
            )
            return await self._complete_failed(
                conversation_id,
                user_message=user_message,
                evidence_count=len(evidence),
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
                trace_id=trace_id,
                error_code="GENERATION_FAILED",
                retrieval_strategy=retrieval_strategy,
            )

        assistant, persisted = await self._answer_repository.complete_answer(
            conversation_id,
            content=answer,
            answer_status="COMPLETED",
            model=self._model_name,
            input_tokens=usage.input_tokens if usage else None,
            output_tokens=usage.output_tokens if usage else None,
            error_code=None,
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
            trace_id=trace_id,
        )

    async def _complete_failed(
        self,
        conversation_id: UUID,
        *,
        user_message: EnterpriseMessage,
        evidence_count: int,
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
                if (
                    len(query_embedding) != _ENTERPRISE_EMBEDDING_DIMENSIONS
                    or not all(math.isfinite(value) for value in query_embedding)
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
                    dense_hits = [
                        hit for hit in dense_hits if hit.score >= self._minimum_score
                    ]
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
            scores[hit.chunk_id] = scores.get(hit.chunk_id, 0.0) + 1.0 / (
                rank_constant + rank
            )
    ordered = sorted(scores, key=lambda chunk_id: (-scores[chunk_id], str(chunk_id)))
    return [
        replace(canonical[chunk_id], score=scores[chunk_id])
        for chunk_id in ordered[:top_k]
    ]


def _limit_chunks_per_document(
    candidates: tuple[RetrievalCandidate, ...],
    *,
    top_k: int,
    max_chunks_per_document: int,
) -> tuple[RetrievalCandidate, ...]:
    selected: list[RetrievalCandidate] = []
    counts: dict[str, int] = {}
    for candidate in candidates:
        document_id = candidate.chunk.document_id
        if counts.get(document_id, 0) >= max_chunks_per_document:
            continue
        selected.append(candidate)
        counts[document_id] = counts.get(document_id, 0) + 1
        if len(selected) >= top_k:
            break
    return tuple(selected)


def _validated_filters(filters: dict[str, object]) -> dict[str, object]:
    unknown = set(filters) - _ALLOWED_FILTERS
    if unknown:
        raise GovernanceValidationError(
            "UNSUPPORTED_SEARCH_FILTER",
            "Unsupported search filter: " + ", ".join(sorted(unknown)),
        )
    normalized = dict(filters)
    document_id = normalized.get("document_id")
    if document_id is not None:
        try:
            normalized["document_id"] = str(UUID(str(document_id)))
        except ValueError as exc:
            raise GovernanceValidationError(
                "INVALID_DOCUMENT_FILTER",
                "document_id filter must be a UUID",
            ) from exc
    metadata = normalized.get("metadata")
    if metadata is not None and not isinstance(metadata, dict):
        raise GovernanceValidationError(
            "INVALID_METADATA_FILTER",
            "metadata filter must be an object",
        )
    return normalized


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
