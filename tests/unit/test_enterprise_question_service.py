from __future__ import annotations

from collections.abc import AsyncIterator
from datetime import UTC, datetime
from uuid import UUID

import pytest

from app.generation.domain import CitationHit, GenerationEvent, TokenChunk, UsageInfo
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
from app.retrieval.domain.models import EvidenceChunk, RetrievalCandidate

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
    ) -> None:
        self.hits = hits
        self.dense_hits = dense_hits
        self.history = history
        self.appended: list[str] = []
        self.completions: list[dict[str, object]] = []
        self.search_queries: list[str] = []
        self.dense_queries: list[list[float]] = []

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

    async def append_user_message(
        self, conversation_id: UUID, content: str
    ) -> EnterpriseMessage:
        assert conversation_id == CONVERSATION_ID
        self.appended.append(content)
        return _message(USER_MESSAGE_ID, "USER", content, "COMPLETED")

    async def search(
        self, query: str, *, limit: int, filters: dict[str, object]
    ) -> list[SearchHit]:
        assert query
        assert limit == 6
        assert filters == {}
        self.search_queries.append(query)
        return self.hits

    async def search_dense(
        self,
        query_embedding: list[float],
        *,
        limit: int,
        filters: dict[str, object],
    ) -> list[SearchHit]:
        assert limit == 6
        assert filters == {}
        self.dense_queries.append(query_embedding)
        return list(self.dense_hits or ())

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

    async def stream(
        self,
        *,
        question: str,
        evidence: tuple[RetrievalCandidate, ...],
    ) -> AsyncIterator[GenerationEvent]:
        self.called = True
        assert question
        self.questions.append(question)
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


class EmbeddingStub:
    model_name = "test-embedding"

    def embed(self, texts: list[str]) -> list[list[float]]:
        assert len(texts) == 1
        return [[0.01] * 1536]


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
