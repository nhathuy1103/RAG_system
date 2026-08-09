"""Maximal Marginal Relevance reranker — SPEC step ⑦, duplicate/conflict Layer 3.

Diversity term is lexical (word-shingle Jaccard) rather than embedding cosine:
``RetrievalCandidate``/``EvidenceChunk`` don't carry the embedding vector back
from the vector store today (see duplicate_conflict_SPEC.html), and plumbing
it through would touch several adapters plus the RRF fusion merge logic for
zero-cost reuse of vectors already computed at ingest time. Lexical
similarity on ``chunk.text`` is a much smaller, self-contained change and is
enough to catch the near-duplicate-chunk case this layer exists for.
"""

from __future__ import annotations

from app.retrieval.domain.models import RetrievalCandidate

DEFAULT_SHINGLE_SIZE = 3


class MaximalMarginalRelevanceReranker:
    """Greedy MMR: argmax[ λ·relevance(d) − (1−λ)·max_sim(d, selected) ]."""

    def __init__(
        self,
        *,
        lambda_param: float = 0.7,
        shingle_size: int = DEFAULT_SHINGLE_SIZE,
        collapse_exact_duplicates: bool = True,
    ) -> None:
        if not 0.0 <= lambda_param <= 1.0:
            raise ValueError("lambda_param must be between 0.0 and 1.0")
        if shingle_size <= 0:
            raise ValueError("shingle_size must be > 0")
        self.lambda_param = lambda_param
        self.shingle_size = shingle_size
        self.collapse_exact_duplicates = collapse_exact_duplicates

    def rerank(
        self,
        query: str,
        candidates: tuple[RetrievalCandidate, ...],
        *,
        top_k: int,
    ) -> tuple[RetrievalCandidate, ...]:
        del query  # relevance is taken from the already-computed candidate.score
        if top_k <= 0 or not candidates:
            return ()

        if self.collapse_exact_duplicates:
            candidates = _collapse_exact_chunks(candidates)
        relevance = _normalized_scores(candidates)
        shingles = [_shingles(candidate.chunk.text, self.shingle_size) for candidate in candidates]

        remaining = list(range(len(candidates)))
        selected: list[int] = []
        limit = min(top_k, len(candidates))

        while remaining and len(selected) < limit:
            best_index = remaining[0]
            best_value = float("-inf")
            for index in remaining:
                diversity_penalty = (
                    max(_jaccard(shingles[index], shingles[chosen]) for chosen in selected)
                    if selected
                    else 0.0
                )
                mmr_value = (
                    self.lambda_param * relevance[index]
                    - (1.0 - self.lambda_param) * diversity_penalty
                )
                if mmr_value > best_value:
                    best_value = mmr_value
                    best_index = index
            selected.append(best_index)
            remaining.remove(best_index)

        return tuple(candidates[index] for index in selected)


def _collapse_exact_chunks(
    candidates: tuple[RetrievalCandidate, ...],
) -> tuple[RetrievalCandidate, ...]:
    """Keep the strongest result per explicit exact group or checksum."""
    best_by_key: dict[str, tuple[int, RetrievalCandidate]] = {}
    for position, candidate in enumerate(candidates):
        metadata = candidate.chunk.typed_metadata
        exact_group_id = metadata.text("exact_duplicate_group_id") or ""
        checksum = metadata.text("checksum") or ""
        if exact_group_id:
            key = f"exact-group:{exact_group_id}"
        elif checksum:
            key = f"checksum:{checksum}"
        else:
            key = f"id:{candidate.chunk.id}"
        previous = best_by_key.get(key)
        if previous is None or candidate.score > previous[1].score:
            best_by_key[key] = (position, candidate)
    return tuple(
        candidate
        for _, candidate in sorted(
            best_by_key.values(),
            key=lambda item: item[0],
        )
    )


def _normalized_scores(candidates: tuple[RetrievalCandidate, ...]) -> list[float]:
    scores = [candidate.score for candidate in candidates]
    lo, hi = min(scores), max(scores)
    if hi == lo:
        return [1.0 for _ in scores]
    return [(score - lo) / (hi - lo) for score in scores]


def _shingles(text: str, size: int) -> frozenset[tuple[str, ...]]:
    words = text.lower().split()
    if not words:
        return frozenset()
    if len(words) <= size:
        return frozenset({tuple(words)})
    return frozenset(tuple(words[i : i + size]) for i in range(len(words) - size + 1))


def _jaccard(a: frozenset[tuple[str, ...]], b: frozenset[tuple[str, ...]]) -> float:
    if not a and not b:
        return 0.0
    union = a | b
    if not union:
        return 0.0
    return len(a & b) / len(union)


__all__ = ["MaximalMarginalRelevanceReranker"]
