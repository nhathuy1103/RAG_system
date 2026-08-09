from __future__ import annotations

from types import SimpleNamespace

import pytest

from app.retrieval.adapters.fusion import ReciprocalRankFusion
from app.retrieval.domain.models import RetrievalCandidate


def _candidate(chunk_id: str, *, rank: int) -> RetrievalCandidate:
    return RetrievalCandidate(
        chunk=SimpleNamespace(id=chunk_id),  # type: ignore[arg-type]
        score=1.0,
        rank=rank,
        source="test",
    )


def test_candidate_found_by_both_rankings_outranks_one_found_by_only_one() -> None:
    fusion = ReciprocalRankFusion()

    result = fusion.fuse(
        {
            "bm25": (_candidate("only_bm25", rank=1), _candidate("both", rank=2)),
            "dense": (_candidate("both", rank=1),),
        },
        top_k=5,
    )

    assert [c.chunk.id for c in result][0] == "both"


def test_respects_top_k() -> None:
    fusion = ReciprocalRankFusion()

    result = fusion.fuse(
        {"a": (_candidate("c1", rank=1), _candidate("c2", rank=2), _candidate("c3", rank=3))},
        top_k=2,
    )

    assert len(result) == 2


def test_empty_rankings_returns_empty() -> None:
    fusion = ReciprocalRankFusion()

    assert fusion.fuse({}, top_k=5) == ()


def test_non_positive_top_k_returns_empty_without_erroring() -> None:
    fusion = ReciprocalRankFusion()

    assert fusion.fuse({"a": (_candidate("c1", rank=1),)}, top_k=0) == ()


def test_rejects_non_positive_rank_constant() -> None:
    with pytest.raises(ValueError):
        ReciprocalRankFusion(rank_constant=0)


def test_fused_results_are_reranked_starting_at_one() -> None:
    fusion = ReciprocalRankFusion()

    result = fusion.fuse(
        {"a": (_candidate("c1", rank=5), _candidate("c2", rank=9))},
        top_k=5,
    )

    assert [c.rank for c in result] == [1, 2]
    assert all(c.source == "hybrid" for c in result)
