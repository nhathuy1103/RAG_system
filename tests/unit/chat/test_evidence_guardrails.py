"""Security-focused tests for chat evidence and citation gates."""

from __future__ import annotations

from collections.abc import AsyncIterator
from dataclasses import replace
from uuid import UUID

import pytest

from app.chat.application.services import (
    CITATION_VALIDATION_FAILURE,
    CONTROLLED_NO_ANSWER,
    ChatContext,
    ChatService,
)
from app.chat.domain.models import (
    AnswerCitation,
    AnswerDone,
    AnswerFailed,
    AnswerToken,
    ChatEvent,
    NewCitation,
)
from app.generation.domain import CitationHit, GenerationEvent, TokenChunk
from app.generation.domain.evidence import GenerationContext
from app.retrieval.application.handle_retrieval_request import (
    ClarificationNeeded,
    FixedAnswer,
)
from app.retrieval.domain.models import (
    AgenticRetrievalResult,
    AgenticRetrievalRound,
    EvidenceChunk,
    RetrievalCandidate,
    SufficiencyCheck,
)

OWNER_ID = UUID("20000000-0000-0000-0000-000000000002")
NOTEBOOK_ID = UUID("10000000-0000-0000-0000-000000000001")
CONVERSATION_ID = UUID("50000000-0000-0000-0000-000000000005")
MESSAGE_ID = UUID("60000000-0000-0000-0000-000000000006")
ALLOWED_DOCUMENT_ID = UUID("30000000-0000-0000-0000-000000000003")
OTHER_DOCUMENT_ID = UUID("40000000-0000-0000-0000-000000000004")
CHUNK_ID = UUID("70000000-0000-0000-0000-000000000007")
OTHER_CHUNK_ID = UUID("80000000-0000-0000-0000-000000000008")


def _candidate(
    *,
    document_id: UUID = ALLOWED_DOCUMENT_ID,
    chunk_id: UUID = CHUNK_ID,
) -> RetrievalCandidate:
    return RetrievalCandidate(
        chunk=EvidenceChunk(
            id=str(chunk_id),
            document_id=str(document_id),
            text="Nhân viên được nghỉ 12 ngày phép mỗi năm.",
            metadata={"document_version": 2},
        ),
        score=0.91,
        rank=1,
    )


def _result(
    evidence: tuple[RetrievalCandidate, ...],
    *,
    sufficient: bool,
    gave_up: bool,
) -> AgenticRetrievalResult:
    return AgenticRetrievalResult(
        evidence=evidence,
        rounds_used=1,
        gave_up=gave_up,
        trace=(
            AgenticRetrievalRound(
                round_index=1,
                query_used="Nghỉ phép bao nhiêu ngày?",
                new_evidence_count=len(evidence),
                sufficiency=SufficiencyCheck(sufficient=sufficient),
            ),
        ),
    )


class _RetrievalHandler:
    def __init__(self, result: object) -> None:
        self.result = result
        self.calls = 0

    def handle(self, **_: object) -> object:
        self.calls += 1
        return self.result


class _AnswerGenerator:
    def __init__(self, events: tuple[GenerationEvent, ...] = ()) -> None:
        self.events = events
        self.calls: list[
            tuple[str, tuple[RetrievalCandidate, ...], GenerationContext | None]
        ] = []

    async def stream(
        self,
        *,
        question: str,
        evidence: tuple[RetrievalCandidate, ...],
        generation_context: GenerationContext | None = None,
    ) -> AsyncIterator[GenerationEvent]:
        self.calls.append((question, evidence, generation_context))
        for event in self.events:
            yield event


class _ChatRepository:
    def __init__(self) -> None:
        self.completed: list[dict[str, object]] = []
        self.failed: list[dict[str, object]] = []
        self.citations: list[tuple[NewCitation, ...]] = []

    async def complete_assistant_message(
        self,
        message_id: UUID,
        notebook_id: UUID,
        **kwargs: object,
    ) -> None:
        self.completed.append({"message_id": message_id, "notebook_id": notebook_id, **kwargs})

    async def insert_citations(
        self,
        *,
        citations: tuple[NewCitation, ...],
        **_: object,
    ) -> None:
        self.citations.append(citations)

    async def fail_assistant_message(
        self,
        message_id: UUID,
        notebook_id: UUID,
        **kwargs: object,
    ) -> None:
        self.failed.append({"message_id": message_id, "notebook_id": notebook_id, **kwargs})


def _context() -> ChatContext:
    return ChatContext(
        owner_id=OWNER_ID,
        notebook_id=NOTEBOOK_ID,
        conversation_id=CONVERSATION_ID,
        assistant_message_id=MESSAGE_ID,
        question="Nghỉ phép bao nhiêu ngày?",
        history=(),
        allowed_document_ids=(ALLOWED_DOCUMENT_ID,),
        document_titles={ALLOWED_DOCUMENT_ID: "so-tay-nhan-vien.pdf"},
    )


def _service(
    result: object,
    generator: _AnswerGenerator,
    *,
    p5_mode: str = "shadow",
) -> tuple[ChatService, _ChatRepository]:
    repository = _ChatRepository()
    service = ChatService(
        notebook_repository=object(),  # type: ignore[arg-type]
        document_repository=object(),  # type: ignore[arg-type]
        chat_repository=repository,  # type: ignore[arg-type]
        retrieval_handler=_RetrievalHandler(result),  # type: ignore[arg-type]
        answer_generator=generator,
        chat_model_name="test-model",
        p5_mode=p5_mode,  # type: ignore[arg-type]
    )
    return service, repository


async def _events(
    service: ChatService, *, context: ChatContext | None = None
) -> list[ChatEvent]:
    return [event async for event in service.respond(context or _context())]


@pytest.mark.anyio
@pytest.mark.parametrize(
    "result",
    [
        _result((_candidate(),), sufficient=False, gave_up=True),
        _result((), sufficient=True, gave_up=False),
        _result((_candidate(),), sufficient=False, gave_up=False),
    ],
    ids=("gave-up", "no-evidence", "insufficient-verdict"),
)
async def test_evidence_gate_returns_controlled_no_answer_without_calling_generator(
    result: AgenticRetrievalResult,
) -> None:
    generator = _AnswerGenerator()
    service, repository = _service(result, generator)

    events = await _events(service)

    assert generator.calls == []
    assert [event.text for event in events if isinstance(event, AnswerToken)] == [
        CONTROLLED_NO_ANSWER
    ]
    assert isinstance(events[-1], AnswerDone)
    assert repository.completed[0]["content"] == CONTROLLED_NO_ANSWER
    assert repository.completed[0]["model"] is None
    assert repository.citations == [()]
    assert repository.failed == []


@pytest.mark.anyio
async def test_retrieval_candidate_outside_authorized_scope_never_reaches_generator() -> None:
    leaked = _candidate(document_id=OTHER_DOCUMENT_ID)
    generator = _AnswerGenerator()
    service, repository = _service(
        _result((leaked,), sufficient=True, gave_up=False),
        generator,
    )

    events = await _events(service)

    assert generator.calls == []
    assert any(
        isinstance(event, AnswerToken) and event.text == CONTROLLED_NO_ANSWER for event in events
    )
    assert repository.completed[0]["model"] is None


@pytest.mark.anyio
@pytest.mark.parametrize(
    ("decision", "expected"),
    [
        (ClarificationNeeded("Bạn muốn hỏi chính sách nào?"), "Bạn muốn hỏi chính sách nào?"),
        (FixedAnswer("Xin chào!"), "Xin chào!"),
    ],
)
async def test_non_retrieval_decisions_still_bypass_evidence_and_generation_gates(
    decision: ClarificationNeeded | FixedAnswer,
    expected: str,
) -> None:
    generator = _AnswerGenerator()
    service, repository = _service(decision, generator)

    events = await _events(service)

    assert generator.calls == []
    assert [event.text for event in events if isinstance(event, AnswerToken)] == [expected]
    assert repository.completed[0]["content"] == expected
    assert isinstance(events[-1], AnswerDone)


@pytest.mark.anyio
async def test_valid_answer_uses_only_trusted_alias_candidate_and_persists_citation() -> None:
    candidate = _candidate()
    generator = _AnswerGenerator(
        (
            TokenChunk("Nhân viên được nghỉ 12 ngày [SRC-1]."),
            CitationHit(source_id="SRC-1", ordinal=1, candidate=candidate),
        )
    )
    service, repository = _service(
        _result((candidate,), sufficient=True, gave_up=False),
        generator,
    )

    events = await _events(service)

    assert len(generator.calls) == 1
    citations = [event for event in events if isinstance(event, AnswerCitation)]
    assert len(citations) == 1
    assert citations[0].document_id == ALLOWED_DOCUMENT_ID
    assert citations[0].document_version == 2
    assert repository.citations[0][0].chunk_id == CHUNK_ID
    assert repository.failed == []
    assert isinstance(events[-1], AnswerDone)


@pytest.mark.anyio
async def test_unknown_marker_rejects_answer_without_persisting_partial_content() -> None:
    candidate = _candidate()
    generator = _AnswerGenerator((TokenChunk("Thông tin sai [SRC-999]."),))
    service, repository = _service(
        _result((candidate,), sufficient=True, gave_up=False),
        generator,
    )

    events = await _events(service)

    assert repository.completed == []
    assert repository.citations == []
    assert repository.failed[0]["error_message"] == CITATION_VALIDATION_FAILURE
    assert repository.failed[0].get("content") is None
    assert isinstance(events[-1], AnswerFailed)
    assert events[-1].message == CITATION_VALIDATION_FAILURE


@pytest.mark.anyio
async def test_valid_alias_cannot_attach_a_candidate_from_another_document() -> None:
    authorized = _candidate()
    leaked = _candidate(document_id=OTHER_DOCUMENT_ID, chunk_id=OTHER_CHUNK_ID)
    generator = _AnswerGenerator(
        (
            TokenChunk("Nội dung [SRC-1]."),
            CitationHit(source_id="SRC-1", ordinal=1, candidate=leaked),
        )
    )
    service, repository = _service(
        _result((authorized,), sufficient=True, gave_up=False),
        generator,
    )

    events = await _events(service)

    assert not any(isinstance(event, AnswerCitation) for event in events)
    assert repository.completed == []
    assert repository.citations == []
    assert repository.failed[0]["error_message"] == CITATION_VALIDATION_FAILURE
    assert isinstance(events[-1], AnswerFailed)


@pytest.mark.anyio
async def test_p5_on_passes_typed_context_and_persists_valid_grounded_answer() -> None:
    candidate = _candidate()
    answer = "The policy grants 12 days [SRC-1]."
    generator = _AnswerGenerator(
        (
            TokenChunk(answer),
            CitationHit(source_id="SRC-1", ordinal=1, candidate=candidate),
        )
    )
    service, repository = _service(
        _result((candidate,), sufficient=True, gave_up=False),
        generator,
        p5_mode="on",
    )

    events = await _events(service)

    assert generator.calls[0][2] is not None
    assert [event.text for event in events if isinstance(event, AnswerToken)] == [answer]
    assert repository.completed[0]["model"] == "test-model"
    assert len(repository.citations[0]) == 1
    assert repository.failed == []
    assert isinstance(events[-1], AnswerDone)


@pytest.mark.anyio
async def test_p5_citation_exposes_structured_table_row_provenance() -> None:
    candidate = RetrievalCandidate(
        chunk=EvidenceChunk(
            id=str(CHUNK_ID),
            document_id=str(ALLOWED_DOCUMENT_ID),
            text="The table reports 12 days.",
            metadata={
                "structured_value": {"value": "12"},
                "structured_provenance": {
                    "table_id": "benefits-table",
                    "data_row_ordinal": 3,
                },
            },
        ),
        score=0.91,
        rank=1,
    )
    generator = _AnswerGenerator(
        (
            TokenChunk("The table reports 12 days [SRC-1]."),
            CitationHit(source_id="SRC-1", ordinal=1, candidate=candidate),
        )
    )
    service, _ = _service(
        _result((candidate,), sufficient=True, gave_up=False),
        generator,
        p5_mode="on",
    )

    events = await _events(service)
    citation = next(event for event in events if isinstance(event, AnswerCitation))

    assert citation.table_id == "benefits-table"
    assert citation.row_ordinal == 3


@pytest.mark.anyio
async def test_p5_on_converts_invalid_citation_to_controlled_uncertainty() -> None:
    candidate = _candidate()
    generator = _AnswerGenerator((TokenChunk("Unsupported [SRC-999]."),))
    service, repository = _service(
        _result((candidate,), sufficient=True, gave_up=False),
        generator,
        p5_mode="on",
    )

    events = await _events(service)

    assert len([event for event in events if isinstance(event, AnswerToken)]) == 1
    assert repository.completed[0]["model"] is None
    assert repository.citations == [()]
    assert repository.failed == []
    assert isinstance(events[-1], AnswerDone)


@pytest.mark.anyio
async def test_p5_on_does_not_guess_current_value_from_historical_evidence() -> None:
    candidate = RetrievalCandidate(
        chunk=EvidenceChunk(
            id=str(CHUNK_ID),
            document_id=str(ALLOWED_DOCUMENT_ID),
            text="The 2024 price was 5 billion VND.",
            metadata={
                "version_family_id": "price-family",
                "year": 2024,
                "is_current": False,
                "structured_value": {"value": "5"},
            },
        ),
        score=0.91,
        rank=1,
    )
    generator = _AnswerGenerator()
    service, repository = _service(
        _result((candidate,), sufficient=True, gave_up=False),
        generator,
        p5_mode="on",
    )

    events = await _events(
        service,
        context=replace(_context(), question="What is the current price?"),
    )

    assert generator.calls == []
    assert repository.completed[0]["model"] is None
    assert repository.citations == [()]
    assert isinstance(events[-1], AnswerDone)
