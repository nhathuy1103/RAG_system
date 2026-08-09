"""Port for self-correction — SPEC step ⑧, the most important decision in the loop."""

from __future__ import annotations

from typing import Protocol

from app.retrieval.domain.models import RetrievalCandidate, SufficiencyCheck


class SufficiencyCheckerPort(Protocol):
    """Judge whether accumulated evidence answers the FULL original question."""

    def check(
        self,
        original_question: str,
        evidence: tuple[RetrievalCandidate, ...],
    ) -> SufficiencyCheck: ...


__all__ = ["SufficiencyCheckerPort"]
