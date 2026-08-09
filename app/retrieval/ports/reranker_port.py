"""Port for optional candidate reranking — SPEC step ⑥."""

from __future__ import annotations

from typing import Protocol

from app.retrieval.domain.models import RetrievalCandidate


class RerankerPort(Protocol):
    """Re-order candidates by a more precise (and usually more expensive) signal."""

    def rerank(
        self,
        query: str,
        candidates: tuple[RetrievalCandidate, ...],
        *,
        top_k: int,
    ) -> tuple[RetrievalCandidate, ...]: ...


__all__ = ["RerankerPort"]
