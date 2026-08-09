from __future__ import annotations

import pytest

from app.retrieval.adapters.mmr_reranker import MaximalMarginalRelevanceReranker
from app.retrieval.domain.models import EvidenceChunk, RetrievalCandidate


def _candidate(chunk_id: str, *, text: str, score: float) -> RetrievalCandidate:
    return RetrievalCandidate(
        chunk=EvidenceChunk(id=chunk_id, document_id="doc-1", text=text),
        score=score,
        rank=1,
    )


def test_pulls_a_distinct_result_ahead_of_a_near_duplicate() -> None:
    # "dup" outscores "near_dup" on relevance, but they're the exact same
    # chunk text (e.g. retrieved via two different query rewrites); "distinct"
    # is the only genuinely different result and should be pulled up ahead of
    # the near-duplicate once diversity is weighed in.
    same_text = "doanh thu quý 3 tăng 12 phần trăm so với cùng kỳ"
    dup = _candidate("dup", text=same_text, score=0.95)
    near_dup = _candidate("near_dup", text=same_text, score=0.90)
    distinct = _candidate(
        "distinct", text="chính sách bảo hành sản phẩm kéo dài 24 tháng", score=0.70
    )
    reranker = MaximalMarginalRelevanceReranker(lambda_param=0.5)

    result = reranker.rerank("q", (dup, near_dup, distinct), top_k=2)

    assert [c.chunk.id for c in result] == ["dup", "distinct"]


def test_lambda_one_behaves_like_pure_relevance_order() -> None:
    low = _candidate("low", text="văn bản A", score=0.4)
    high = _candidate("high", text="văn bản B", score=0.9)
    reranker = MaximalMarginalRelevanceReranker(lambda_param=1.0)

    result = reranker.rerank("q", (low, high), top_k=2)

    assert [c.chunk.id for c in result] == ["high", "low"]


def test_does_not_mutate_candidate_score_or_rank() -> None:
    candidate = _candidate("c1", text="văn bản", score=0.42)
    reranker = MaximalMarginalRelevanceReranker()

    result = reranker.rerank("q", (candidate,), top_k=1)

    assert result[0] is candidate


def test_collapses_exact_checksum_duplicates_before_mmr_selection() -> None:
    first = RetrievalCandidate(
        chunk=EvidenceChunk(
            id="first",
            document_id="doc-1",
            text="identical source content",
            metadata={"checksum": "same-checksum"},
        ),
        score=0.8,
        rank=2,
    )
    stronger_copy = RetrievalCandidate(
        chunk=EvidenceChunk(
            id="copy",
            document_id="doc-2",
            text="identical source content",
            metadata={"checksum": "same-checksum"},
        ),
        score=0.9,
        rank=1,
    )
    distinct = _candidate("distinct", text="different evidence", score=0.7)

    result = MaximalMarginalRelevanceReranker().rerank(
        "q",
        (first, stronger_copy, distinct),
        top_k=3,
    )

    assert [candidate.chunk.id for candidate in result] == ["copy", "distinct"]


def test_exact_group_id_takes_priority_over_checksum() -> None:
    first = RetrievalCandidate(
        chunk=EvidenceChunk(
            id="first",
            document_id="doc-1",
            text="first",
            metadata={
                "exact_duplicate_group_id": "group-one",
                "checksum": "shared-checksum",
            },
        ),
        score=0.9,
        rank=1,
    )
    second = RetrievalCandidate(
        chunk=EvidenceChunk(
            id="second",
            document_id="doc-2",
            text="second",
            metadata={
                "exact_duplicate_group_id": "group-two",
                "checksum": "shared-checksum",
            },
        ),
        score=0.8,
        rank=2,
    )

    result = MaximalMarginalRelevanceReranker().rerank(
        "q",
        (first, second),
        top_k=2,
    )

    assert {candidate.chunk.id for candidate in result} == {
        "first",
        "second",
    }


@pytest.mark.parametrize(
    ("candidates", "top_k"),
    [((), 5), ((_candidate("c1", text="x", score=1.0),), 0)],
)
def test_returns_empty_for_no_candidates_or_non_positive_top_k(candidates, top_k) -> None:
    reranker = MaximalMarginalRelevanceReranker()

    assert reranker.rerank("q", candidates, top_k=top_k) == ()


def test_top_k_larger_than_candidate_count_returns_all_candidates() -> None:
    candidates = (
        _candidate("c1", text="văn bản một", score=0.5),
        _candidate("c2", text="văn bản hai", score=0.6),
    )
    reranker = MaximalMarginalRelevanceReranker()

    result = reranker.rerank("q", candidates, top_k=10)

    assert {c.chunk.id for c in result} == {"c1", "c2"}


def test_rejects_invalid_lambda_and_shingle_size() -> None:
    with pytest.raises(ValueError):
        MaximalMarginalRelevanceReranker(lambda_param=1.5)
    with pytest.raises(ValueError):
        MaximalMarginalRelevanceReranker(shingle_size=0)
