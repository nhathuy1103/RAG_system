"""Deterministic query reformulator — placeholder for an LLM rewriter."""

from __future__ import annotations

from app.retrieval.domain.models import RetrievalCandidate


class FallbackQueryReformulator:
    """Retries with whatever the sufficiency check reported as missing."""

    def reformulate(
        self,
        *,
        original_question: str,
        evidence: tuple[RetrievalCandidate, ...],
        missing: str | None,
    ) -> str:
        return missing.strip() if missing and missing.strip() else original_question


__all__ = ["FallbackQueryReformulator"]
