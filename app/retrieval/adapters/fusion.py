"""Reciprocal Rank Fusion — SPEC step ⑥. Merges by rank, not raw score."""

from __future__ import annotations

from collections.abc import Mapping, Sequence

from app.retrieval.domain.models import RetrievalCandidate


class ReciprocalRankFusion:
    def __init__(self, *, rank_constant: int = 60) -> None:
        if rank_constant <= 0:
            raise ValueError("rank_constant must be > 0")
        self.rank_constant = rank_constant

    def fuse(
        self,
        rankings: Mapping[str, Sequence[RetrievalCandidate]],
        *,
        top_k: int,
    ) -> tuple[RetrievalCandidate, ...]:
        if top_k <= 0:
            return ()

        scores: dict[str, float] = {}
        first_seen: dict[str, RetrievalCandidate] = {}
        for candidates in rankings.values():
            for position, candidate in enumerate(candidates, start=1):
                chunk_id = candidate.chunk.id
                scores[chunk_id] = scores.get(chunk_id, 0.0) + 1.0 / (self.rank_constant + position)
                first_seen.setdefault(chunk_id, candidate)

        ordered = sorted(scores.items(), key=lambda item: (-item[1], item[0]))
        return tuple(
            RetrievalCandidate(
                chunk=first_seen[chunk_id].chunk,
                score=score,
                rank=rank,
                source="hybrid",
            )
            for rank, (chunk_id, score) in enumerate(ordered[:top_k], start=1)
        )


__all__ = ["ReciprocalRankFusion"]
