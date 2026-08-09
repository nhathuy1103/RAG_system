"""Port for query reformulation — SPEC step ⑨-⑩ (the retry branch)."""

from __future__ import annotations

from typing import Protocol

from app.retrieval.domain.models import RetrievalCandidate


class QueryReformulatorPort(Protocol):
    """Rewrite the retrieval query to target evidence still missing after a round."""

    def reformulate(
        self,
        *,
        original_question: str,
        evidence: tuple[RetrievalCandidate, ...],
        missing: str | None,
    ) -> str: ...


__all__ = ["QueryReformulatorPort"]
