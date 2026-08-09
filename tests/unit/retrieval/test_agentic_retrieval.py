from __future__ import annotations

import json

import pytest

from app.retrieval.application.agentic_retrieval import AgenticRetrievalUseCase
from app.retrieval.domain.models import (
    EvidenceChunk,
    RetrievalCandidate,
    RetrievalFilters,
    SufficiencyCheck,
)

FILTERS = RetrievalFilters(owner_id="user-1")


def _chunk(
    chunk_id: str,
    *,
    text: str = "evidence text",
    document_id: str = "doc-1",
    metadata: dict[str, str] | None = None,
) -> EvidenceChunk:
    return EvidenceChunk(
        id=chunk_id,
        document_id=document_id,
        text=text,
        metadata=dict(metadata or {}),
    )


def _candidate(
    chunk_id: str,
    *,
    text: str = "evidence text",
    rank: int = 1,
    score: float = 1.0,
    document_id: str = "doc-1",
    metadata: dict[str, str] | None = None,
) -> RetrievalCandidate:
    return RetrievalCandidate(
        chunk=_chunk(
            chunk_id,
            text=text,
            document_id=document_id,
            metadata=metadata,
        ),
        score=score,
        rank=rank,
    )


class FakeRetrievalPort:
    """Records every query it is asked to search and returns a scripted result."""

    def __init__(self, results_by_call: list[tuple[RetrievalCandidate, ...]]) -> None:
        self._results = list(results_by_call)
        self.queries: list[str] = []
        self.top_ks: list[int] = []

    def search(self, query, filters, *, top_k):
        self.queries.append(query)
        self.top_ks.append(top_k)
        return self._results.pop(0)


class ScriptedChecker:
    """Returns sufficiency verdicts in a fixed order, one per call."""

    def __init__(self, verdicts: list[SufficiencyCheck]) -> None:
        self._verdicts = list(verdicts)
        self.calls: list[tuple[str, int]] = []

    def check(self, original_question, evidence):
        self.calls.append((original_question, len(evidence)))
        return self._verdicts.pop(0)


class FixedReformulator:
    def __init__(self, next_query: str) -> None:
        self.next_query = next_query
        self.calls: list[tuple[str, int, str | None]] = []

    def reformulate(self, *, original_question, evidence, missing):
        self.calls.append((original_question, len(evidence), missing))
        return self.next_query


def test_stops_on_first_round_when_sufficient() -> None:
    retrieval_port = FakeRetrievalPort([(_candidate("c1"),)])
    checker = ScriptedChecker([SufficiencyCheck(sufficient=True, reasoning="ok")])
    reformulator = FixedReformulator("should not be used")
    use_case = AgenticRetrievalUseCase(
        retrieval_port=retrieval_port,
        sufficiency_checker=checker,
        reformulator=reformulator,
    )

    result = use_case.run(
        original_question="doanh thu quý 3 là bao nhiêu?",
        filters=FILTERS,
        top_k=5,
    )

    assert result.gave_up is False
    assert result.rounds_used == 1
    assert [c.chunk.id for c in result.evidence] == ["c1"]
    assert retrieval_port.queries == ["doanh thu quý 3 là bao nhiêu?"]
    assert reformulator.calls == []


def test_retries_with_reformulated_query_and_accumulates_evidence() -> None:
    retrieval_port = FakeRetrievalPort(
        [
            (_candidate("c1"),),
            (_candidate("c1"), _candidate("c2")),
        ]
    )
    checker = ScriptedChecker(
        [
            SufficiencyCheck(sufficient=False, missing="ai đứng đầu phòng đó?"),
            SufficiencyCheck(sufficient=True),
        ]
    )
    reformulator = FixedReformulator("ai đứng đầu phòng kinh doanh?")
    use_case = AgenticRetrievalUseCase(
        retrieval_port=retrieval_port,
        sufficiency_checker=checker,
        reformulator=reformulator,
    )

    result = use_case.run(
        original_question="phòng nào doanh thu cao nhất và ai đứng đầu phòng đó?",
        filters=FILTERS,
        top_k=5,
    )

    assert result.gave_up is False
    assert result.rounds_used == 2
    # c1 must not be duplicated even though it appeared in both rounds.
    assert sorted(c.chunk.id for c in result.evidence) == ["c1", "c2"]
    assert retrieval_port.queries == [
        "phòng nào doanh thu cao nhất và ai đứng đầu phòng đó?",
        "ai đứng đầu phòng kinh doanh?",
    ]
    assert reformulator.calls == [
        (
            "phòng nào doanh thu cao nhất và ai đứng đầu phòng đó?",
            1,
            "ai đứng đầu phòng đó?",
        )
    ]
    assert len(result.trace) == 2
    assert result.trace[0].new_evidence_count == 1
    assert result.trace[1].new_evidence_count == 1


def test_accumulation_collapses_same_checksum_across_rounds() -> None:
    first = RetrievalCandidate(
        chunk=EvidenceChunk(
            id="c1",
            document_id="doc-1",
            text="same evidence",
            metadata={"checksum": "stable-checksum"},
        ),
        score=0.7,
        rank=1,
    )
    stronger_copy = RetrievalCandidate(
        chunk=EvidenceChunk(
            id="c2",
            document_id="doc-2",
            text="same evidence",
            metadata={"checksum": "stable-checksum"},
        ),
        score=0.9,
        rank=1,
    )
    retrieval_port = FakeRetrievalPort([(first,), (stronger_copy,)])
    checker = ScriptedChecker(
        [
            SufficiencyCheck(sufficient=False, missing="more"),
            SufficiencyCheck(sufficient=True),
        ]
    )
    use_case = AgenticRetrievalUseCase(
        retrieval_port=retrieval_port,
        sufficiency_checker=checker,
        reformulator=FixedReformulator("rephrased"),
        knowledge_quality_mode="on",
    )

    result = use_case.run(
        original_question="q",
        filters=FILTERS,
        top_k=2,
    )

    assert [candidate.chunk.id for candidate in result.evidence] == ["c2"]
    assert result.trace[1].new_evidence_count == 0
    assert json.loads(result.evidence[0].chunk.metadata["duplicate_source_chunk_ids"]) == [
        "c1",
        "c2",
    ]
    assert json.loads(result.evidence[0].chunk.metadata["duplicate_source_document_ids"]) == [
        "doc-1",
        "doc-2",
    ]
    assert result.evidence[0].chunk.metadata["duplicate_source_count"] == "2"


def test_gives_up_after_max_rounds_without_using_general_knowledge() -> None:
    retrieval_port = FakeRetrievalPort([(), ()])
    checker = ScriptedChecker(
        [
            SufficiencyCheck(sufficient=False, missing="phần A"),
            SufficiencyCheck(sufficient=False, missing="phần A"),
        ]
    )
    reformulator = FixedReformulator("phần A")
    use_case = AgenticRetrievalUseCase(
        retrieval_port=retrieval_port,
        sufficiency_checker=checker,
        reformulator=reformulator,
        max_rounds=2,
    )

    result = use_case.run(original_question="câu hỏi khó", filters=FILTERS, top_k=5)

    assert result.gave_up is True
    assert result.rounds_used == 2
    assert result.evidence == ()


def test_reranker_is_applied_when_provided() -> None:
    low_then_high = (_candidate("low", rank=2), _candidate("high", rank=1))
    retrieval_port = FakeRetrievalPort([low_then_high])
    checker = ScriptedChecker([SufficiencyCheck(sufficient=True)])
    reformulator = FixedReformulator("unused")

    class ReverseReranker:
        def rerank(self, query, candidates, *, top_k):
            return tuple(reversed(candidates))

    use_case = AgenticRetrievalUseCase(
        retrieval_port=retrieval_port,
        sufficiency_checker=checker,
        reformulator=reformulator,
        reranker=ReverseReranker(),
    )

    result = use_case.run(original_question="q", filters=FILTERS, top_k=5)

    assert [c.chunk.id for c in result.evidence] == ["high", "low"]


def test_widens_search_pool_when_reranker_and_pool_size_are_set() -> None:
    retrieval_port = FakeRetrievalPort([(_candidate("c1"),)])
    checker = ScriptedChecker([SufficiencyCheck(sufficient=True)])
    reformulator = FixedReformulator("unused")

    class PassthroughReranker:
        def rerank(self, query, candidates, *, top_k):
            return candidates[:top_k]

    use_case = AgenticRetrievalUseCase(
        retrieval_port=retrieval_port,
        sufficiency_checker=checker,
        reformulator=reformulator,
        reranker=PassthroughReranker(),
        rerank_pool_size=20,
    )

    use_case.run(original_question="q", filters=FILTERS, top_k=5)

    assert retrieval_port.top_ks == [20]


def test_does_not_widen_pool_without_a_reranker() -> None:
    retrieval_port = FakeRetrievalPort([(_candidate("c1"),)])
    checker = ScriptedChecker([SufficiencyCheck(sufficient=True)])
    reformulator = FixedReformulator("unused")
    use_case = AgenticRetrievalUseCase(
        retrieval_port=retrieval_port,
        sufficiency_checker=checker,
        reformulator=reformulator,
        rerank_pool_size=20,
    )

    use_case.run(original_question="q", filters=FILTERS, top_k=5)

    assert retrieval_port.top_ks == [5]


def test_does_not_widen_pool_when_pool_size_is_unset() -> None:
    low_then_high = (_candidate("low", rank=2), _candidate("high", rank=1))
    retrieval_port = FakeRetrievalPort([low_then_high])
    checker = ScriptedChecker([SufficiencyCheck(sufficient=True)])
    reformulator = FixedReformulator("unused")

    class ReverseReranker:
        def rerank(self, query, candidates, *, top_k):
            return tuple(reversed(candidates))

    use_case = AgenticRetrievalUseCase(
        retrieval_port=retrieval_port,
        sufficiency_checker=checker,
        reformulator=reformulator,
        reranker=ReverseReranker(),
    )

    use_case.run(original_question="q", filters=FILTERS, top_k=5)

    assert retrieval_port.top_ks == [5]


def test_document_cap_refills_final_context_from_other_sources() -> None:
    candidates = (
        _candidate("a1", document_id="doc-a", score=1.0),
        _candidate("a2", document_id="doc-a", score=0.9),
        _candidate("a3", document_id="doc-a", score=0.8),
        _candidate("a4", document_id="doc-a", score=0.7),
        _candidate("b1", document_id="doc-b", score=0.6),
        _candidate("b2", document_id="doc-b", score=0.5),
    )
    retrieval_port = FakeRetrievalPort([candidates])
    checker = ScriptedChecker([SufficiencyCheck(sufficient=True)])

    class PassthroughReranker:
        def rerank(self, query, candidates, *, top_k):
            return candidates[:top_k]

    use_case = AgenticRetrievalUseCase(
        retrieval_port=retrieval_port,
        sufficiency_checker=checker,
        reformulator=FixedReformulator("unused"),
        reranker=PassthroughReranker(),
        rerank_pool_size=6,
        max_chunks_per_document=2,
    )

    result = use_case.run(
        original_question="q",
        filters=FILTERS,
        top_k=4,
    )

    assert [item.chunk.id for item in result.evidence] == [
        "a1",
        "a2",
        "b1",
        "b2",
    ]


def test_explicit_single_document_scope_disables_document_cap() -> None:
    candidates = tuple(
        _candidate(f"a{index}", document_id="doc-a", score=1 - index / 10) for index in range(4)
    )
    retrieval_port = FakeRetrievalPort([candidates])
    checker = ScriptedChecker([SufficiencyCheck(sufficient=True)])
    use_case = AgenticRetrievalUseCase(
        retrieval_port=retrieval_port,
        sufficiency_checker=checker,
        reformulator=FixedReformulator("unused"),
        max_chunks_per_document=2,
    )

    result = use_case.run(
        original_question="q",
        filters=RetrievalFilters(
            owner_id="user-1",
            document_ids=("doc-a",),
        ),
        top_k=4,
    )

    assert len(result.evidence) == 4


def test_score_threshold_drops_weak_candidates_and_can_yield_empty_evidence() -> None:
    weak_and_strong = (_candidate("weak", score=0.2), _candidate("strong", score=0.9))
    retrieval_port = FakeRetrievalPort([weak_and_strong])
    checker = ScriptedChecker([SufficiencyCheck(sufficient=True)])
    reformulator = FixedReformulator("unused")
    use_case = AgenticRetrievalUseCase(
        retrieval_port=retrieval_port,
        sufficiency_checker=checker,
        reformulator=reformulator,
        score_threshold=0.5,
    )

    result = use_case.run(original_question="q", filters=FILTERS, top_k=5)

    assert [c.chunk.id for c in result.evidence] == ["strong"]


def test_score_threshold_can_leave_no_evidence_at_all() -> None:
    only_weak = (_candidate("weak", score=0.1),)
    retrieval_port = FakeRetrievalPort([only_weak])
    checker = ScriptedChecker([SufficiencyCheck(sufficient=False, missing="q")])
    reformulator = FixedReformulator("unused")
    use_case = AgenticRetrievalUseCase(
        retrieval_port=retrieval_port,
        sufficiency_checker=checker,
        reformulator=reformulator,
        score_threshold=0.5,
        max_rounds=1,
    )

    result = use_case.run(original_question="q", filters=FILTERS, top_k=5)

    assert result.evidence == ()
    assert result.gave_up is True


def test_rejects_non_positive_budgets() -> None:
    retrieval_port = FakeRetrievalPort([])
    checker = ScriptedChecker([])
    reformulator = FixedReformulator("unused")

    with pytest.raises(ValueError):
        AgenticRetrievalUseCase(
            retrieval_port=retrieval_port,
            sufficiency_checker=checker,
            reformulator=reformulator,
            max_rounds=0,
        ).run(original_question="q", filters=FILTERS, top_k=5)

    with pytest.raises(ValueError):
        AgenticRetrievalUseCase(
            retrieval_port=retrieval_port,
            sufficiency_checker=checker,
            reformulator=reformulator,
        ).run(original_question="q", filters=FILTERS, top_k=0)


def test_on_mode_collapses_neighbors_without_joining_citation_text() -> None:
    candidates = (
        _candidate(
            "c10",
            text="citation text ten",
            score=0.9,
            metadata={"chunk_index": "10", "coverage": "0.2"},
        ),
        _candidate(
            "c11",
            text="citation text eleven",
            score=0.9,
            metadata={"chunk_index": "11", "coverage": "0.8"},
        ),
        _candidate(
            "c20",
            text="separate citation",
            score=0.7,
            metadata={"chunk_index": "20"},
        ),
    )
    use_case = AgenticRetrievalUseCase(
        retrieval_port=FakeRetrievalPort([candidates]),
        sufficiency_checker=ScriptedChecker([SufficiencyCheck(sufficient=True)]),
        reformulator=FixedReformulator("unused"),
        knowledge_quality_mode="on",
    )

    result = use_case.run(
        original_question="q",
        filters=FILTERS,
        top_k=2,
    )

    assert [candidate.chunk.id for candidate in result.evidence] == [
        "c11",
        "c20",
    ]
    representative = result.evidence[0]
    assert representative.chunk.text == "citation text eleven"
    assert "citation text ten" not in representative.chunk.text
    assert json.loads(representative.chunk.metadata["duplicate_source_chunk_ids"]) == ["c10", "c11"]
    assert json.loads(representative.chunk.metadata["duplicate_source_document_ids"]) == ["doc-1"]
    assert representative.chunk.metadata["duplicate_source_count"] == "2"


@pytest.mark.parametrize("mode", ["off", "shadow"])
def test_neighbor_collapse_does_not_change_off_or_shadow_behavior(
    mode: str,
) -> None:
    candidates = (
        _candidate("c10", metadata={"chunk_index": "10"}),
        _candidate("c11", metadata={"chunk_index": "11"}),
        _candidate("c20", metadata={"chunk_index": "20"}),
    )
    use_case = AgenticRetrievalUseCase(
        retrieval_port=FakeRetrievalPort([candidates]),
        sufficiency_checker=ScriptedChecker([SufficiencyCheck(sufficient=True)]),
        reformulator=FixedReformulator("unused"),
        knowledge_quality_mode=mode,
    )

    result = use_case.run(
        original_question="q",
        filters=FILTERS,
        top_k=2,
    )

    assert [candidate.chunk.id for candidate in result.evidence] == [
        "c10",
        "c11",
    ]
    assert all(
        "duplicate_source_chunk_ids" not in candidate.chunk.metadata
        for candidate in result.evidence
    )


def test_exact_group_id_is_authoritative_and_checksum_is_fallback() -> None:
    candidates = (
        _candidate(
            "group-a-weak",
            document_id="doc-a",
            score=0.7,
            metadata={
                "exact_duplicate_group_id": "group-a",
                "checksum": "checksum-one",
            },
        ),
        _candidate(
            "group-a-best",
            document_id="doc-b",
            score=0.95,
            metadata={
                "exact_duplicate_group_id": "group-a",
                "checksum": "checksum-two",
            },
        ),
        _candidate(
            "group-b",
            document_id="doc-c",
            score=0.8,
            metadata={
                "exact_duplicate_group_id": "group-b",
                "checksum": "checksum-two",
            },
        ),
        _candidate(
            "checksum-copy-one",
            document_id="doc-d",
            score=0.6,
            metadata={"checksum": "fallback-checksum"},
        ),
        _candidate(
            "checksum-copy-two",
            document_id="doc-e",
            score=0.9,
            metadata={"checksum": "fallback-checksum"},
        ),
    )
    use_case = AgenticRetrievalUseCase(
        retrieval_port=FakeRetrievalPort([candidates]),
        sufficiency_checker=ScriptedChecker([SufficiencyCheck(sufficient=True)]),
        reformulator=FixedReformulator("unused"),
        knowledge_quality_mode="on",
    )

    result = use_case.run(
        original_question="q",
        filters=FILTERS,
        top_k=5,
    )

    assert [candidate.chunk.id for candidate in result.evidence] == [
        "group-a-best",
        "group-b",
        "checksum-copy-two",
    ]
    assert json.loads(result.evidence[0].chunk.metadata["duplicate_source_chunk_ids"]) == [
        "group-a-best",
        "group-a-weak",
    ]
    assert json.loads(result.evidence[2].chunk.metadata["duplicate_source_chunk_ids"]) == [
        "checksum-copy-one",
        "checksum-copy-two",
    ]


def test_cross_document_exact_group_does_not_bridge_neighbor_groups() -> None:
    candidates = (
        _candidate(
            "doc-a-zero",
            document_id="doc-a",
            metadata={
                "chunk_index": "0",
                "exact_duplicate_group_id": "shared",
            },
        ),
        _candidate(
            "doc-b-zero",
            document_id="doc-b",
            metadata={
                "chunk_index": "0",
                "exact_duplicate_group_id": "shared",
            },
        ),
        _candidate(
            "doc-a-one",
            document_id="doc-a",
            metadata={"chunk_index": "1"},
        ),
        _candidate(
            "doc-b-one",
            document_id="doc-b",
            metadata={"chunk_index": "1"},
        ),
    )
    use_case = AgenticRetrievalUseCase(
        retrieval_port=FakeRetrievalPort([candidates]),
        sufficiency_checker=ScriptedChecker([SufficiencyCheck(sufficient=True)]),
        reformulator=FixedReformulator("unused"),
        knowledge_quality_mode="on",
    )

    result = use_case.run(
        original_question="q",
        filters=FILTERS,
        top_k=4,
    )

    assert len(result.evidence) == 3
    assert json.loads(result.evidence[0].chunk.metadata["duplicate_source_chunk_ids"]) == [
        "doc-a-zero",
        "doc-b-zero",
    ]
    assert {candidate.chunk.id for candidate in result.evidence[1:]} == {"doc-a-one", "doc-b-one"}


def test_neighbor_collapse_is_transitive_across_multiple_rounds() -> None:
    retrieval_port = FakeRetrievalPort(
        [
            (
                _candidate(
                    "c1",
                    text="best original citation",
                    score=0.95,
                    metadata={"chunk_index": "1"},
                ),
            ),
            (
                _candidate(
                    "c2",
                    text="second citation",
                    score=0.8,
                    metadata={"chunk_index": "2"},
                ),
            ),
            (
                _candidate(
                    "c3",
                    text="third citation",
                    score=0.7,
                    metadata={"chunk_index": "3"},
                ),
            ),
        ]
    )
    checker = ScriptedChecker(
        [
            SufficiencyCheck(sufficient=False, missing="more"),
            SufficiencyCheck(sufficient=False, missing="more"),
            SufficiencyCheck(sufficient=True),
        ]
    )
    use_case = AgenticRetrievalUseCase(
        retrieval_port=retrieval_port,
        sufficiency_checker=checker,
        reformulator=FixedReformulator("rephrased"),
        max_rounds=3,
        knowledge_quality_mode="on",
    )

    result = use_case.run(
        original_question="q",
        filters=FILTERS,
        top_k=2,
    )

    assert [candidate.chunk.id for candidate in result.evidence] == ["c1"]
    assert result.evidence[0].chunk.text == "best original citation"
    assert json.loads(result.evidence[0].chunk.metadata["duplicate_source_chunk_ids"]) == [
        "c1",
        "c2",
        "c3",
    ]
    assert result.evidence[0].chunk.metadata["duplicate_source_count"] == "3"
    assert [item.new_evidence_count for item in result.trace] == [1, 0, 0]


def test_alias_provenance_uses_only_retrieval_filtered_candidates() -> None:
    allowed = _candidate(
        "allowed-chunk",
        document_id="allowed-doc",
        metadata={
            "exact_duplicate_group_id": "shared-group",
            "duplicate_source_chunk_ids": ('["allowed-chunk","forbidden-chunk"]'),
            "duplicate_source_document_ids": ('["allowed-doc","forbidden-doc"]'),
            "duplicate_source_count": "2",
        },
    )
    use_case = AgenticRetrievalUseCase(
        retrieval_port=FakeRetrievalPort([(allowed,)]),
        sufficiency_checker=ScriptedChecker([SufficiencyCheck(sufficient=True)]),
        reformulator=FixedReformulator("unused"),
        knowledge_quality_mode="on",
    )

    result = use_case.run(
        original_question="q",
        filters=RetrievalFilters(
            owner_id="user-1",
            document_ids=("allowed-doc",),
        ),
        top_k=2,
    )

    metadata = result.evidence[0].chunk.metadata
    assert json.loads(metadata["duplicate_source_chunk_ids"]) == ["allowed-chunk"]
    assert json.loads(metadata["duplicate_source_document_ids"]) == ["allowed-doc"]
    assert metadata["duplicate_source_count"] == "1"
