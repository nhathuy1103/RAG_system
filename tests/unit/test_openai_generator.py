"""Unit tests for the OpenAI-backed answer generator."""

import pytest

from app.generation.adapters.openai_generator import (
    OpenAIAnswerGenerator,
    _evidence_trace_metadata,
)
from app.generation.application.citation_validation import (
    CitationValidationError,
    build_evidence_aliases,
    validate_answer_citations,
)
from app.generation.domain import CitationHit, TokenChunk, UsageInfo
from app.retrieval.domain.models import EvidenceChunk, RetrievalCandidate

CHUNK_ID_A = "chunk-a"
CHUNK_ID_B = "chunk-b"


def _candidate(
    chunk_id: str,
    text: str,
    *,
    document_id: str = "doc-1",
    metadata: dict[str, object] | None = None,
) -> RetrievalCandidate:
    return RetrievalCandidate(
        chunk=EvidenceChunk(
            id=chunk_id,
            document_id=document_id,
            text=text,
            metadata=metadata or {},
        ),
        score=0.9,
        rank=1,
        source="hybrid",
    )


def test_evidence_trace_metadata_contains_source_identity_and_canonical_fields() -> None:
    evidence = (
        _candidate(
            CHUNK_ID_A,
            "Policy content",
            document_id="doc-a",
            metadata={
                "document_version_id": "version-a",
                "retrieval_metadata": {
                    "project_code": "P16",
                    "year": 2026,
                    "content_kind": "table",
                },
            },
        ),
        _candidate(
            CHUNK_ID_B,
            "More policy content",
            document_id="doc-b",
            metadata={
                "document_version_id": "version-b",
                "retrieval_metadata": {
                    "project_code": "P16",
                    "language": "vi",
                },
            },
        ),
    )

    metadata = _evidence_trace_metadata(evidence)

    assert metadata["evidence_document_ids"] == "doc-a,doc-b"
    assert metadata["evidence_document_version_ids"] == "version-a,version-b"
    assert metadata["evidence_chunk_ids"] == "chunk-a,chunk-b"
    assert metadata["evidence_project_code"] == "P16"
    assert metadata["evidence_year"] == "2026"
    assert metadata["evidence_content_kind"] == "table"
    assert metadata["evidence_language"] == "vi"


def test_missing_citation_has_retriable_validation_code() -> None:
    evidence = (_candidate(CHUNK_ID_A, "Grounded policy content"),)

    with pytest.raises(CitationValidationError) as captured:
        validate_answer_citations(
            "A grounded answer without a marker.",
            evidence_by_alias=build_evidence_aliases(evidence),
            accepted_source_ids=(),
        )

    assert captured.value.code == "MISSING_CITATION_MARKER"


def test_unknown_citation_remains_an_integrity_failure() -> None:
    evidence = (_candidate(CHUNK_ID_A, "Grounded policy content"),)

    with pytest.raises(CitationValidationError) as captured:
        validate_answer_citations(
            "Fabricated source [SRC-999].",
            evidence_by_alias=build_evidence_aliases(evidence),
            accepted_source_ids=(),
        )

    assert captured.value.code == "UNKNOWN_CITATION_SOURCE"


class _Delta:
    def __init__(self, content: str | None) -> None:
        self.content = content


class _Choice:
    def __init__(self, content: str | None) -> None:
        self.delta = _Delta(content)


class _Usage:
    def __init__(self, prompt_tokens: int, completion_tokens: int) -> None:
        self.prompt_tokens = prompt_tokens
        self.completion_tokens = completion_tokens


class _Chunk:
    def __init__(self, choices: list[_Choice], usage: _Usage | None = None) -> None:
        self.choices = choices
        self.usage = usage


class _FakeStream:
    def __init__(self, chunks: list[_Chunk]) -> None:
        self._chunks = chunks

    def __aiter__(self) -> "_FakeStream":
        self._iterator = iter(self._chunks)
        return self

    async def __anext__(self) -> _Chunk:
        try:
            return next(self._iterator)
        except StopIteration as exc:
            raise StopAsyncIteration from exc


class _FakeCompletions:
    def __init__(self, chunks: list[_Chunk]) -> None:
        self._chunks = chunks
        self.last_call: dict[str, object] | None = None

    async def create(self, **kwargs: object) -> _FakeStream:
        self.last_call = kwargs
        return _FakeStream(self._chunks)


class _FakeChat:
    def __init__(self, chunks: list[_Chunk]) -> None:
        self.completions = _FakeCompletions(chunks)


class _FakeClient:
    def __init__(self, chunks: list[_Chunk]) -> None:
        self.chat = _FakeChat(chunks)


@pytest.mark.anyio
async def test_stream_yields_tokens_and_citation_for_referenced_source() -> None:
    chunks = [
        _Chunk([_Choice("Theo [SRC-1] ")]),
        _Chunk([_Choice("nhân viên được nghỉ 12 ngày.")]),
        _Chunk([], usage=_Usage(prompt_tokens=50, completion_tokens=10)),
    ]
    client = _FakeClient(chunks)
    generator = OpenAIAnswerGenerator(client=client, model="gpt-4o-mini")
    evidence = (_candidate(CHUNK_ID_A, "Chính sách nghỉ phép"),)

    events = [
        event
        async for event in generator.stream(question="Nghỉ phép bao nhiêu ngày?", evidence=evidence)
    ]

    tokens = [event for event in events if isinstance(event, TokenChunk)]
    citations = [event for event in events if isinstance(event, CitationHit)]
    usages = [event for event in events if isinstance(event, UsageInfo)]

    assert "".join(token.text for token in tokens) == ("Theo [SRC-1] nhân viên được nghỉ 12 ngày.")
    assert len(citations) == 1
    assert citations[0].source_id == "SRC-1"
    assert citations[0].ordinal == 1
    assert usages == [UsageInfo(input_tokens=50, output_tokens=10)]
    assert client.chat.completions.last_call is not None
    assert client.chat.completions.last_call["model"] == "gpt-4o-mini"
    messages = client.chat.completions.last_call["messages"]
    assert isinstance(messages, list)
    assert f"[SRC-1]\n{evidence[0].chunk.text}" in messages[1]["content"]
    assert CHUNK_ID_A not in messages[1]["content"]
    assert "$...$" in messages[0]["content"]
    assert "$$...$$" in messages[0]["content"]
    assert "mâu thuẫn" in messages[0]["content"]


@pytest.mark.anyio
async def test_open_book_system_prompt_also_instructs_to_surface_conflicts() -> None:
    client = _FakeClient([_Chunk([])])
    generator = OpenAIAnswerGenerator(
        client=client,
        model="gpt-4o-mini",
        allow_outside_knowledge=True,
    )

    async for _ in generator.stream(question="Câu hỏi", evidence=()):
        pass

    assert client.chat.completions.last_call is not None
    messages = client.chat.completions.last_call["messages"]
    assert isinstance(messages, list)
    assert "mâu thuẫn" in messages[0]["content"]


@pytest.mark.anyio
async def test_user_prompt_marks_detected_numeric_conflict_with_both_aliases() -> None:
    client = _FakeClient([_Chunk([])])
    generator = OpenAIAnswerGenerator(client=client, model="gpt-4o-mini")
    evidence = (
        _candidate(CHUNK_ID_A, "Revenue in Q3 was 120 million."),
        _candidate(CHUNK_ID_B, "Revenue in Q3 was 121 million."),
    )

    async for _ in generator.stream(question="What was Q3 revenue?", evidence=evidence):
        pass

    assert client.chat.completions.last_call is not None
    messages = client.chat.completions.last_call["messages"]
    prompt = messages[1]["content"]
    assert "SYSTEM CONFLICT SIGNALS" in prompt
    assert "[SRC-1] <-> [SRC-2]" in prompt
    assert "semantic_quantity_mismatch" in prompt


@pytest.mark.anyio
async def test_conflict_annotation_can_be_disabled_by_configuration() -> None:
    client = _FakeClient([_Chunk([])])
    generator = OpenAIAnswerGenerator(
        client=client,
        model="gpt-4o-mini",
        conflict_annotations_enabled=False,
    )
    evidence = (
        _candidate(CHUNK_ID_A, "Revenue in Q3 was 120 million."),
        _candidate(CHUNK_ID_B, "Revenue in Q3 was 121 million."),
    )

    async for _ in generator.stream(question="What was Q3 revenue?", evidence=evidence):
        pass

    messages = client.chat.completions.last_call["messages"]
    assert "SYSTEM CONFLICT SIGNALS" not in messages[1]["content"]
    assert "mâu thuẫn" not in messages[0]["content"]


@pytest.mark.anyio
async def test_conflict_fallback_enforces_citations_from_both_sides() -> None:
    client = _FakeClient([_Chunk([_Choice("Nguồn thứ nhất nói 120 [SRC-1].")])])
    generator = OpenAIAnswerGenerator(client=client, model="gpt-4o-mini")
    evidence = (
        _candidate(CHUNK_ID_A, "Revenue in Q3 was 120 million."),
        _candidate(CHUNK_ID_B, "Revenue in Q3 was 121 million."),
    )

    events = [
        event
        async for event in generator.stream(
            question="What was Q3 revenue?",
            evidence=evidence,
        )
    ]

    text = "".join(event.text for event in events if isinstance(event, TokenChunk))
    citations = [event.source_id for event in events if isinstance(event, CitationHit)]
    assert "Nguồn mâu thuẫn" in text
    assert "[SRC-1] ↔ [SRC-2]" in text
    assert citations == ["SRC-1", "SRC-2"]


@pytest.mark.anyio
async def test_confirmed_conflict_relation_enforces_both_citations_without_heuristic_match() -> (
    None
):
    client = _FakeClient([_Chunk([_Choice("Nguồn A [SRC-1].")])])
    generator = OpenAIAnswerGenerator(client=client, model="gpt-4o-mini")
    evidence = (
        _candidate(
            CHUNK_ID_A,
            "Quy định áp dụng cho nhân viên.",
            document_id="doc-a",
            metadata={"confirmed_conflict_peer_document_ids": "doc-b"},
        ),
        _candidate(
            CHUNK_ID_B,
            "Hướng dẫn áp dụng cho đối tác.",
            document_id="doc-b",
            metadata={"confirmed_conflict_peer_document_ids": "doc-a"},
        ),
    )

    events = [
        event
        async for event in generator.stream(
            question="Chính sách áp dụng thế nào?",
            evidence=evidence,
        )
    ]

    prompt = client.chat.completions.last_call["messages"][1]["content"]
    citations = [event.source_id for event in events if isinstance(event, CitationHit)]
    assert "confirmed_document_relation" in prompt
    assert citations == ["SRC-1", "SRC-2"]


@pytest.mark.anyio
async def test_structured_claim_conflict_enforces_both_citations_without_heuristic_match() -> None:
    client = _FakeClient([_Chunk([_Choice("Source A [SRC-1].")])])
    generator = OpenAIAnswerGenerator(client=client, model="gpt-4o-mini")
    warning = {
        "relation_id": "relation-1",
        "relation_type": "conflict_candidate",
        "review_status": "pending",
    }
    evidence = (
        _candidate(
            CHUNK_ID_A,
            "Policy applies to employees.",
            document_id="doc-a",
            metadata={"structured_relation_warnings": [warning]},
        ),
        _candidate(
            CHUNK_ID_B,
            "Guidance applies to partners.",
            document_id="doc-b",
            metadata={"structured_relation_warnings": [warning]},
        ),
    )

    events = [
        event
        async for event in generator.stream(
            question="How does the policy apply?",
            evidence=evidence,
        )
    ]

    prompt = client.chat.completions.last_call["messages"][1]["content"]
    citations = [event.source_id for event in events if isinstance(event, CitationHit)]
    assert "structured_claim_relation" in prompt
    assert citations == ["SRC-1", "SRC-2"]


@pytest.mark.anyio
async def test_dismissed_structured_conflict_does_not_force_a_citation_pair() -> None:
    client = _FakeClient([_Chunk([_Choice("Source A [SRC-1].")])])
    generator = OpenAIAnswerGenerator(client=client, model="gpt-4o-mini")
    warning = {
        "relation_id": "relation-1",
        "relation_type": "conflict",
        "review_status": "dismissed",
    }
    evidence = (
        _candidate(
            CHUNK_ID_A,
            "Policy applies to employees.",
            metadata={"structured_relation_warnings": [warning]},
        ),
        _candidate(
            CHUNK_ID_B,
            "Guidance applies to partners.",
            metadata={"structured_relation_warnings": [warning]},
        ),
    )

    events = [event async for event in generator.stream(question="Question", evidence=evidence)]

    prompt = client.chat.completions.last_call["messages"][1]["content"]
    citations = [event.source_id for event in events if isinstance(event, CitationHit)]
    assert "structured_claim_relation" not in prompt
    assert citations == ["SRC-1"]


@pytest.mark.anyio
async def test_stream_ignores_hallucinated_and_duplicate_source_ids() -> None:
    chunks = [
        _Chunk([_Choice("[SRC-1] [SRC-999] [SRC-1]")]),
    ]
    client = _FakeClient(chunks)
    generator = OpenAIAnswerGenerator(client=client, model="gpt-4o-mini")
    evidence = (_candidate(CHUNK_ID_A, "Chính sách nghỉ phép"),)

    events = [event async for event in generator.stream(question="Câu hỏi", evidence=evidence)]

    citations = [event for event in events if isinstance(event, CitationHit)]
    assert len(citations) == 1
    assert citations[0].source_id == "SRC-1"


@pytest.mark.anyio
async def test_stream_detects_source_alias_split_across_token_chunks() -> None:
    chunks = [
        _Chunk([_Choice("Theo [SR")]),
        _Chunk([_Choice("C-2], nội dung nguồn thứ hai.")]),
    ]
    client = _FakeClient(chunks)
    generator = OpenAIAnswerGenerator(client=client, model="gpt-4o-mini")
    evidence = (
        _candidate(CHUNK_ID_A, "Nguồn thứ nhất"),
        _candidate(CHUNK_ID_B, "Nguồn thứ hai"),
    )

    events = [event async for event in generator.stream(question="Câu hỏi", evidence=evidence)]

    citations = [event for event in events if isinstance(event, CitationHit)]
    assert len(citations) == 1
    assert citations[0].source_id == "SRC-2"
    assert citations[0].candidate.chunk.id == CHUNK_ID_B


def test_construction_rejects_empty_model_name() -> None:
    with pytest.raises(ValueError):
        OpenAIAnswerGenerator(client=_FakeClient([]), model="")
