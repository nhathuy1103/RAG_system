"""No-op reranker — a seam for a future cross-encoder / LLM reranker."""

from __future__ import annotations

from app.retrieval.domain.models import RetrievalCandidate


class IdentityReranker:
    """Keeps candidate order unchanged."""

    def rerank(
        self,
        query: str,
        candidates: tuple[RetrievalCandidate, ...],
        *,
        top_k: int,
    ) -> tuple[RetrievalCandidate, ...]:
        return candidates[:top_k]


__all__ = ["IdentityReranker"]
