from __future__ import annotations

from collections.abc import AsyncIterator, Iterator
from contextlib import contextmanager
from dataclasses import replace
from datetime import UTC, datetime
from uuid import UUID

import pytest

from app.generation.domain import CitationHit, GenerationEvent, TokenChunk, UsageInfo
from app.generation.domain.evidence import GenerationContext
from app.governance.application.services import (
    EnterpriseQuestionService,
    GovernanceValidationError,
)
from app.governance.domain.models import (
    ConversationDetail,
    EnterpriseCitation,
    EnterpriseConversation,
    EnterpriseMessage,
    SearchHit,
)
from app.governance.ports.repositories import NewEnterpriseCitation
from app.retrieval.domain.models import (
    EvidenceChunk,
    RetrievalCandidate,
    SufficiencyCheck,
)

CONVERSATION_ID = UUID("10000000-0000-0000-0000-000000000001")
USER_MESSAGE_ID = UUID("20000000-0000-0000-0000-000000000002")
ASSISTANT_MESSAGE_ID = UUID("30000000-0000-0000-0000-000000000003")
DOCUMENT_ID = UUID("40000000-0000-0000-0000-000000000004")
VERSION_ID = UUID("50000000-0000-0000-0000-000000000005")
CHUNK_ID = UUID("60000000-0000-0000-0000-000000000006")
CITATION_ID = UUID("70000000-0000-0000-0000-000000000007")
NOW = datetime(2026, 8, 8, tzinfo=UTC)


def _message(message_id: UUID, role: str, content: str, status: str) -> EnterpriseMessage:
    return EnterpriseMessage(
        id=message_id,
        conversation_id=CONVERSATION_ID,
        role=role,
        content=content,
        created_at=NOW,
        answer_status=status,
    )


def _hit() -> SearchHit:
    return SearchHit(
        chunk_id=CHUNK_ID,
        document_id=DOCUMENT_ID,
        document_version_id=VERSION_ID,
        title="Security policy",
        content="The security policy requires annual access review.",
        score=0.82,
        page_start=3,
        section_path="Access review",
    )


class RepositoryStub:
    def __init__(
        self,
        hits: list[SearchHit],
        *,
        dense_hits: list[SearchHit] | None = None,
        history: tuple[EnterpriseMessage, ...] = (),
        document_routes: dict[str, list[UUID]] | None = None,
        expanded_hits: list[SearchHit] | None = None,
    ) -> None:
        self.hits = hits
        self.dense_hits = dense_hits
        self.history = history
        self.appended: list[str] = []
        self.completions: list[dict[str, object]] = []
        self.search_queries: list[str] = []
        self.dense_queries: list[list[float]] = []
        self.search_filters: list[dict[str, object]] = []
        self.document_routes = document_routes or {}
        self.resolver_calls: list[str] = []
        self.expanded_hits = expanded_hits or []
        self.expansion_calls: list[tuple[UUID, ...]] = []

    async def get_conversation(self, conversation_id: UUID) -> ConversationDetail:
        assert conversation_id == CONVERSATION_ID
        return ConversationDetail(
            conversation=EnterpriseConversation(
                id=conversation_id,
                user_id=USER_MESSAGE_ID,
                title="Security",
                created_at=NOW,
                updated_at=NOW,
            ),
            messages=self.history,
        )

    async def append_user_message(self, conversation_id: UUID, content: str) -> EnterpriseMessage:
        assert conversation_id == CONVERSATION_ID
        self.appended.append(content)
        return _message(USER_MESSAGE_ID, "USER", content, "COMPLETED")

    async def search(
        self, query: str, *, limit: int, filters: dict[str, object]
    ) -> list[SearchHit]:
        assert query
        assert limit == 6
        self.search_queries.append(query)
        self.search_filters.append(filters)
        return self.hits

    async def search_dense(
        self,
        query_embedding: list[float],
        *,
        limit: int,
        filters: dict[str, object],
    ) -> list[SearchHit]:
        assert limit == 6
        self.dense_queries.append(query_embedding)
        return list(self.dense_hits or ())

    async def resolve_document_number(self, document_number: str) -> list[UUID]:
        self.resolver_calls.append(document_number)
        return self.document_routes.get(document_number, [])

    async def expand_context(
        self,
        chunk_ids: tuple[UUID, ...],
        *,
        sibling_window: int,
        limit: int,
    ) -> list[SearchHit]:
        assert sibling_window == 1
        assert limit == 18
        self.expansion_calls.append(chunk_ids)
        return self.expanded_hits

    async def complete_answer(
        self,
        conversation_id: UUID,
        *,
        content: str,
        answer_status: str,
        model: str | None,
        input_tokens: int | None,
        output_tokens: int | None,
        error_code: str | None,
        trace_id: str | None,
        citations: tuple[NewEnterpriseCitation, ...],
    ) -> tuple[EnterpriseMessage, tuple[EnterpriseCitation, ...]]:
        assert conversation_id == CONVERSATION_ID
        self.completions.append(
            {
                "content": content,
                "answer_status": answer_status,
                "model": model,
                "input_tokens": input_tokens,
                "output_tokens": output_tokens,
                "error_code": error_code,
                "trace_id": trace_id,
                "citations": citations,
            }
        )
        persisted = tuple(
            EnterpriseCitation(
                id=CITATION_ID,
                answer_message_id=ASSISTANT_MESSAGE_ID,
                document_id=item.document_id,
                document_version_id=item.document_version_id,
                chunk_id=item.chunk_id,
                quote_text=item.quote_text,
                citation_order=item.citation_order,
                page_number=item.page_number,
                retrieval_score=item.retrieval_score,
            )
            for item in citations
        )
        return (
            _message(ASSISTANT_MESSAGE_ID, "ASSISTANT", content, answer_status),
            persisted,
        )


class GeneratorStub:
    def __init__(self, *, forge_candidate: bool = False) -> None:
        self.called = False
        self.forge_candidate = forge_candidate
        self.questions: list[str] = []
        self.evidence_counts: list[int] = []

    async def stream(
        self,
        *,
        question: str,
        evidence: tuple[RetrievalCandidate, ...],
    ) -> AsyncIterator[GenerationEvent]:
        self.called = True
        assert question
        self.questions.append(question)
        self.evidence_counts.append(len(evidence))
        candidate = evidence[0]
        if self.forge_candidate:
            candidate = RetrievalCandidate(
                chunk=EvidenceChunk(
                    id="80000000-0000-0000-0000-000000000008",
                    document_id=candidate.chunk.document_id,
                    text=candidate.chunk.text,
                ),
                score=candidate.score,
                rank=1,
            )
        yield TokenChunk("Annual review is required [SRC-1].")
        yield CitationHit(source_id="SRC-1", ordinal=1, candidate=candidate)
        yield UsageInfo(input_tokens=20, output_tokens=8)


class P6GeneratorStub:
    def __init__(self) -> None:
        self.contexts: list[GenerationContext] = []

    async def stream(
        self,
        *,
        question: str,
        evidence: tuple[RetrievalCandidate, ...],
        generation_context: GenerationContext,
    ) -> AsyncIterator[GenerationEvent]:
        assert question
        assert generation_context.candidates == evidence
        self.contexts.append(generation_context)
        candidate = generation_context.evidence_by_id["SRC-1"].candidate
        yield TokenChunk("Giá là 48 triệu đồng năm 2025 [SRC-1].")
        yield CitationHit(source_id="SRC-1", ordinal=1, candidate=candidate)
        yield UsageInfo(input_tokens=24, output_tokens=10)


class P6RepositoryStub(RepositoryStub):
    def __init__(
        self,
        hits: list[SearchHit],
        *,
        history: tuple[EnterpriseMessage, ...],
    ) -> None:
        super().__init__(hits, history=history)
        self.enrichment_calls = 0

    async def enrich_relations(
        self,
        candidates: tuple[RetrievalCandidate, ...],
        filters: object,
    ) -> tuple[RetrievalCandidate, ...]:
        assert filters is not None
        self.enrichment_calls += 1
        return candidates


class MissingThenGroundedGenerator:
    def __init__(self, *, always_missing: bool = False) -> None:
        self.always_missing = always_missing
        self.questions: list[str] = []

    async def stream(
        self,
        *,
        question: str,
        evidence: tuple[RetrievalCandidate, ...],
    ) -> AsyncIterator[GenerationEvent]:
        self.questions.append(question)
        if len(self.questions) == 1 or self.always_missing:
            yield TokenChunk("Annual review is required.")
            yield UsageInfo(input_tokens=10, output_tokens=4)
            return
        yield TokenChunk("Annual review is required [SRC-1].")
        yield CitationHit(source_id="SRC-1", ordinal=1, candidate=evidence[0])
        yield UsageInfo(input_tokens=12, output_tokens=5)


class UncitedMaterialThenGroundedGenerator:
    def __init__(self) -> None:
        self.questions: list[str] = []

    async def stream(
        self,
        *,
        question: str,
        evidence: tuple[RetrievalCandidate, ...],
        generation_context: GenerationContext,
    ) -> AsyncIterator[GenerationEvent]:
        self.questions.append(question)
        candidate = generation_context.evidence_by_id["SRC-1"].candidate
        if len(self.questions) == 1:
            yield TokenChunk("Giá là 48 triệu đồng [SRC-1]. Nguồn áp dụng cho năm 2025.")
        else:
            yield TokenChunk("Giá năm 2025 là 48 triệu đồng [SRC-1].")
        yield CitationHit(source_id="SRC-1", ordinal=1, candidate=candidate)
        yield UsageInfo(input_tokens=12, output_tokens=5)


class AlwaysInsufficientChecker:
    def check(
        self,
        original_question: str,
        evidence: tuple[RetrievalCandidate, ...],
    ) -> SufficiencyCheck:
        assert original_question
        assert evidence
        return SufficiencyCheck(
            sufficient=False,
            missing="hưng yên",
            reasoning="lexical shadow verdict",
        )


class EmbeddingStub:
    model_name = "test-embedding"

    def embed(self, texts: list[str]) -> list[list[float]]:
        assert len(texts) == 1
        return [[0.01] * 1536]


class RecordingObservation:
    def __init__(self) -> None:
        self.updates: list[dict[str, object]] = []

    def update(self, **values: object) -> None:
        self.updates.append(values)


class RecordingTelemetry:
    def __init__(self) -> None:
        self.records: list[dict[str, object]] = []

    def create_trace_id(self, *, seed: str | None = None) -> str:
        assert seed == "enterprise-question:request-123"
        return "a" * 32

    def content(self, value: object) -> object:
        return value

    @contextmanager
    def observe(self, name: str, **values: object) -> Iterator[RecordingObservation]:
        observation = RecordingObservation()
        self.records.append({"name": name, "observation": observation, **values})
        yield observation


@pytest.mark.anyio
async def test_question_trace_captures_actor_filters_and_cited_sources() -> None:
    repository = RepositoryStub([_hit()])
    telemetry = RecordingTelemetry()
    service = EnterpriseQuestionService(
        repository,  # type: ignore[arg-type]
        GeneratorStub(),
        model_name="test-model",
        telemetry=telemetry,  # type: ignore[arg-type]
    )

    result = await service.ask_question(
        CONVERSATION_ID,
        "What does the security policy require?",
        filters={"project_code": "p16"},
        trace_id="request-123",
        user_id=USER_MESSAGE_ID,
    )

    assert result.citations
    assert repository.search_filters == [{"project_code": "P16"}]
    assert len(telemetry.records) == 2
    trace = telemetry.records[0]
    assert trace["name"] == "enterprise.answer_question"
    assert trace["trace_id"] == "a" * 32
    assert trace["trace_name"] == "enterprise-rag-chat"
    assert trace["user_id"] == str(USER_MESSAGE_ID)
    assert trace["session_id"] == str(CONVERSATION_ID)
    assert trace["tags"] == ("rag", "enterprise", "chat")

    observation = trace["observation"]
    assert isinstance(observation, RecordingObservation)
    metadata_updates = [
        update["metadata"]
        for update in observation.updates
        if isinstance(update.get("metadata"), dict)
    ]
    assert metadata_updates[0]["filter_project_code"] == "P16"
    assert metadata_updates[-1]["evidence_count"] == 1
    assert metadata_updates[-1]["citation_count"] == 1
    assert metadata_updates[-1]["cited_document_ids"] == str(DOCUMENT_ID)
    assert metadata_updates[-1]["cited_document_version_ids"] == str(VERSION_ID)

    retrieval = telemetry.records[1]
    assert retrieval["name"] == "retrieve-enterprise-context"
    assert retrieval["as_type"] == "retriever"
    assert retrieval["metadata"]["metadata_stage"] == "before_retrieval"
    assert retrieval["metadata"]["filter_project_code"] == "P16"
    retrieval_input = retrieval["input"]
    assert retrieval_input["metadata_before_retrieval"]["effective_filters"] == {
        "project_code": "P16"
    }
    retrieval_observation = retrieval["observation"]
    assert isinstance(retrieval_observation, RecordingObservation)
    assert retrieval_observation.updates[-1]["output"] == {
        "retrieval_strategy": "secure_keyword_mmr",
        "candidate_count": 1,
        "candidate_document_count": 1,
        "candidate_chunk_ids": [str(CHUNK_ID)],
    }


@pytest.mark.anyio
async def test_no_evidence_is_persisted_as_controlled_no_answer_without_generation() -> None:
    repository = RepositoryStub([])
    generator = GeneratorStub()
    service = EnterpriseQuestionService(
        repository,  # type: ignore[arg-type]
        generator,
        model_name="test-model",
    )

    result = await service.ask_question(
        CONVERSATION_ID,
        "What does the security policy require?",
        filters={},
        trace_id="trace-1",
    )

    assert generator.called is False
    assert result.assistant_message.answer_status == "CONTROLLED_NO_ANSWER"
    assert result.citations == ()
    assert repository.completions[0]["model"] is None
    assert repository.completions[0]["error_code"] == "NO_EVIDENCE"
    assert result.candidate_count == 0
    assert result.gate_reason == "no_evidence"
    assert result.error_code == "NO_EVIDENCE"


@pytest.mark.anyio
async def test_keyword_sufficiency_is_diagnostic_and_does_not_discard_evidence() -> None:
    repository = RepositoryStub([_hit()])
    generator = GeneratorStub()
    service = EnterpriseQuestionService(
        repository,  # type: ignore[arg-type]
        generator,
        model_name="test-model",
        sufficiency_checker=AlwaysInsufficientChecker(),  # type: ignore[arg-type]
    )

    result = await service.ask_question(
        CONVERSATION_ID,
        "Các dự án được triển khai tại Hưng Yên?",
        filters={},
    )

    assert generator.called is True
    assert result.assistant_message.answer_status == "COMPLETED"
    assert result.evidence_count == 1
    assert result.candidate_count == 1
    assert result.gate_reason is None


@pytest.mark.anyio
async def test_one_document_can_fill_the_complete_context_budget() -> None:
    hits = [
        replace(
            _hit(),
            chunk_id=UUID(f"60000000-0000-0000-0000-{index:012d}"),
            content=f"Annual access review policy section {index}.",
            score=1.0 - index / 100,
        )
        for index in range(1, 7)
    ]
    repository = RepositoryStub(hits)
    generator = GeneratorStub()
    service = EnterpriseQuestionService(
        repository,  # type: ignore[arg-type]
        generator,
        model_name="test-model",
        retrieval_top_k=6,
        max_chunks_per_document=2,
    )

    result = await service.ask_question(
        CONVERSATION_ID,
        "Summarize every annual access review policy section.",
        filters={},
    )

    assert result.assistant_message.answer_status == "COMPLETED"
    assert result.candidate_count == 6
    assert result.evidence_count == 6
    assert generator.evidence_counts == [6]


@pytest.mark.anyio
async def test_missing_citation_is_retried_and_recovered_with_same_evidence() -> None:
    repository = RepositoryStub([_hit()])
    generator = MissingThenGroundedGenerator()
    service = EnterpriseQuestionService(
        repository,  # type: ignore[arg-type]
        generator,
        model_name="test-model",
    )

    result = await service.ask_question(
        CONVERSATION_ID,
        "What security policy requires annual access review?",
        filters={},
    )

    assert result.assistant_message.answer_status == "COMPLETED"
    assert len(result.citations) == 1
    assert len(generator.questions) == 2
    assert "YÊU CẦU SỬA TRÍCH DẪN" in generator.questions[1]
    assert "Các marker nguồn hợp lệ duy nhất cho lượt này: [SRC-1]." in (generator.questions[1])
    assert repository.completions[0]["input_tokens"] == 22
    assert repository.completions[0]["output_tokens"] == 9
    assert repository.completions[0]["error_code"] == "CITATION_RETRY_RECOVERED"
    assert result.error_code == "CITATION_RETRY_RECOVERED"


@pytest.mark.anyio
async def test_repeated_missing_citation_returns_concise_cited_no_answer() -> None:
    repository = RepositoryStub([_hit()])
    generator = MissingThenGroundedGenerator(always_missing=True)
    service = EnterpriseQuestionService(
        repository,  # type: ignore[arg-type]
        generator,
        model_name="test-model",
    )

    result = await service.ask_question(
        CONVERSATION_ID,
        "What security policy requires annual access review?",
        filters={},
    )

    assert result.assistant_message.answer_status == "COMPLETED"
    assert len(generator.questions) == 2
    assert len(result.citations) == 1
    assert "Chưa tìm thấy đủ bằng chứng trực tiếp" in result.assistant_message.content
    assert "The security policy requires annual access review." not in (
        result.assistant_message.content
    )
    assert result.assistant_message.content.endswith("[SRC-1].")
    assert repository.completions[0]["error_code"] == "CITATION_FALLBACK_USED"
    assert result.error_code == "CITATION_FALLBACK_USED"


@pytest.mark.anyio
async def test_uncited_material_statement_is_retried_and_recovered() -> None:
    hit = replace(
        _hit(),
        content="Giá năm 2025 là 48 triệu đồng.",
        metadata={
            "year": 2025,
            "reference_year": 2025,
            "structured_predicate": "price",
            "structured_value": {"amount": 48, "unit": "triệu đồng"},
            "structured_temporal": {"reference_year": 2025},
        },
    )
    repository = P6RepositoryStub([hit], history=())
    generator = UncitedMaterialThenGroundedGenerator()
    service = EnterpriseQuestionService(
        repository,  # type: ignore[arg-type]
        generator,  # type: ignore[arg-type]
        model_name="test-model",
        rag_mode="on",
    )

    result = await service.ask_question(
        CONVERSATION_ID,
        "Giá năm 2025 là bao nhiêu?",
        filters={},
        user_id=USER_MESSAGE_ID,
    )

    assert len(generator.questions) == 2
    assert result.assistant_message.content == "Giá năm 2025 là 48 triệu đồng [SRC-1]."
    assert result.error_code == "CITATION_RETRY_RECOVERED"
    assert repository.completions[0]["error_code"] == "CITATION_RETRY_RECOVERED"


@pytest.mark.anyio
async def test_grounded_answer_persists_exact_version_bound_citation() -> None:
    repository = RepositoryStub([_hit()])
    generator = GeneratorStub()
    service = EnterpriseQuestionService(
        repository,  # type: ignore[arg-type]
        generator,
        model_name="test-model",
    )

    result = await service.ask_question(
        CONVERSATION_ID,
        "What security policy requires annual access review?",
        filters={},
        trace_id="trace-2",
    )

    assert result.assistant_message.answer_status == "COMPLETED"
    assert result.citations[0].document_id == DOCUMENT_ID
    assert result.citations[0].document_version_id == VERSION_ID
    assert result.citations[0].chunk_id == CHUNK_ID
    assert result.citations[0].document_title == "Security policy"
    assert result.citations[0].section_path == "Access review"
    completion = repository.completions[0]
    assert completion["model"] == "test-model"
    assert completion["input_tokens"] == 20
    assert completion["output_tokens"] == 8


@pytest.mark.anyio
async def test_forged_citation_candidate_fails_closed_without_persisting_citations() -> None:
    repository = RepositoryStub([_hit()])
    generator = GeneratorStub(forge_candidate=True)
    service = EnterpriseQuestionService(
        repository,  # type: ignore[arg-type]
        generator,
        model_name="test-model",
    )

    result = await service.ask_question(
        CONVERSATION_ID,
        "What security policy requires annual access review?",
        filters={},
    )

    assert result.assistant_message.answer_status == "FAILED"
    assert result.citations == ()
    assert repository.completions[0]["error_code"] == "CITATION_VALIDATION_FAILED"
    assert repository.completions[0]["citations"] == ()


@pytest.mark.anyio
async def test_unknown_filter_is_rejected_before_user_message_is_persisted() -> None:
    repository = RepositoryStub([_hit()])
    service = EnterpriseQuestionService(
        repository,  # type: ignore[arg-type]
        GeneratorStub(),
        model_name="test-model",
    )

    with pytest.raises(GovernanceValidationError) as captured:
        await service.ask_question(
            CONVERSATION_ID,
            "question",
            filters={"owner_id": "forbidden"},
        )

    assert captured.value.code == "UNSUPPORTED_SEARCH_FILTER"
    assert repository.appended == []


@pytest.mark.anyio
async def test_follow_up_uses_history_and_acl_gated_hybrid_retrieval() -> None:
    prior_question = _message(
        UUID("80000000-0000-0000-0000-000000000008"),
        "USER",
        "What does the security policy require for annual access review?",
        "COMPLETED",
    )
    repository = RepositoryStub(
        [_hit()],
        dense_hits=[_hit()],
        history=(prior_question,),
    )
    generator = GeneratorStub()
    service = EnterpriseQuestionService(
        repository,  # type: ignore[arg-type]
        generator,
        model_name="test-model",
        embedding_provider=EmbeddingStub(),
    )

    result = await service.ask_question(
        CONVERSATION_ID,
        "What about that requirement?",
        filters={},
    )

    assert result.assistant_message.answer_status == "COMPLETED"
    assert result.retrieval_strategy == "secure_hybrid_rrf_mmr"
    assert "security policy" in repository.search_queries[0]
    assert " OR " in repository.search_queries[0]
    assert len(repository.dense_queries[0]) == 1536
    assert "Ngữ cảnh các câu hỏi trước" in generator.questions[0]
    assert "What about that requirement?" in generator.questions[0]


@pytest.mark.anyio
async def test_document_number_in_query_routes_to_one_canonical_document() -> None:
    repository = RepositoryStub(
        [_hit()],
        document_routes={"QĐ-116/2025": [DOCUMENT_ID]},
    )
    service = EnterpriseQuestionService(
        repository,  # type: ignore[arg-type]
        GeneratorStub(),
        model_name="test-model",
    )

    result = await service.ask_question(
        CONVERSATION_ID,
        "QĐ-116/2025 requires what annual access review?",
        filters={},
    )

    assert result.assistant_message.answer_status == "COMPLETED"
    assert repository.resolver_calls == ["QĐ-116/2025"]
    assert repository.search_filters == [{"document_id": str(DOCUMENT_ID)}]


@pytest.mark.anyio
async def test_broad_process_query_expands_to_bounded_sibling_context() -> None:
    parent_id = "90000000-0000-0000-0000-000000000009"
    primary = replace(_hit(), metadata={"parent_id": parent_id})
    sibling = SearchHit(
        chunk_id=UUID("60000000-0000-0000-0000-000000000016"),
        document_id=DOCUMENT_ID,
        document_version_id=VERSION_ID,
        title="Security policy",
        content="The process owner records the completed annual access review.",
        score=0.5,
        page_start=4,
        section_path="Access review > Record",
        metadata={"parent_id": parent_id, "expansion_kind": "sibling"},
    )
    expanded_primary = replace(
        primary,
        metadata={
            "parent_id": parent_id,
            "parent_heading": "Annual access review process",
            "expansion_kind": "matched",
        },
    )
    repository = RepositoryStub(
        [primary],
        expanded_hits=[expanded_primary, sibling],
    )
    generator = GeneratorStub()
    service = EnterpriseQuestionService(
        repository,  # type: ignore[arg-type]
        generator,
        model_name="test-model",
    )

    result = await service.ask_question(
        CONVERSATION_ID,
        "What are all process steps for annual access review?",
        filters={},
    )

    assert result.assistant_message.answer_status == "COMPLETED"
    assert repository.expansion_calls == [(CHUNK_ID,)]
    assert generator.evidence_counts == [2]


@pytest.mark.anyio
async def test_p6_on_uses_resolved_query_relations_and_generation_contract() -> None:
    prior_question = _message(
        UUID("80000000-0000-0000-0000-000000000018"),
        "USER",
        "So sánh giá căn hộ Vinhomes qua các năm",
        "COMPLETED",
    )
    current = SearchHit(
        chunk_id=CHUNK_ID,
        document_id=DOCUMENT_ID,
        document_version_id=VERSION_ID,
        title="Bảng giá Vinhomes",
        content="Giá căn hộ Vinhomes năm 2025 là 48 triệu đồng mỗi m2.",
        score=0.82,
        page_start=3,
        section_path="Giá 2025",
        metadata={
            "reference_year": 2025,
            "year": 2025,
            "content_kind": "table_row",
            "structured_predicate": "price",
            "structured_value": {"amount": 48, "unit": "triệu đồng/m2"},
            "structured_temporal": {"reference_year": 2025},
            "p4_relation_type": "DISTINCT",
        },
    )
    other_year = replace(
        current,
        chunk_id=UUID("60000000-0000-0000-0000-000000000019"),
        document_id=UUID("40000000-0000-0000-0000-000000000019"),
        document_version_id=UUID("50000000-0000-0000-0000-000000000019"),
        content="Giá căn hộ Vinhomes năm 2026 là 55 triệu đồng mỗi m2.",
        metadata={**current.metadata, "reference_year": 2026, "year": 2026},
    )
    repository = P6RepositoryStub([other_year, current], history=(prior_question,))
    generator = P6GeneratorStub()
    service = EnterpriseQuestionService(
        repository,  # type: ignore[arg-type]
        generator,  # type: ignore[arg-type]
        model_name="test-model",
        rag_mode="on",
    )

    result = await service.ask_question(
        CONVERSATION_ID,
        "2025 thì sao?",
        filters={},
        user_id=USER_MESSAGE_ID,
    )

    assert result.assistant_message.answer_status == "COMPLETED"
    assert result.retrieval_strategy.endswith("_p6_relation_context")
    assert result.evidence_count == 1
    assert result.citations[0].document_id == DOCUMENT_ID
    assert repository.enrichment_calls == 1
    assert repository.search_queries == ["căn hộ Vinhomes price 2025"]
    assert " OR " not in repository.search_queries[0]
    assert repository.search_filters == [{"year": 2025}]
    assert generator.contexts[0].query.reference_years == (2025,)
    assert generator.contexts[0].diagnostics.temporal_completeness == 1.0
