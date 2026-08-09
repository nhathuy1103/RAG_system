"""Port for the Adaptive decision — SPEC step ④."""

from __future__ import annotations

from typing import Protocol

from app.retrieval.domain.models import AdaptiveDecision


class AdaptiveClassifierPort(Protocol):
    """Classify whether a question requires retrieving from uploaded documents."""

    def classify(self, question: str) -> AdaptiveDecision: ...


__all__ = ["AdaptiveClassifierPort"]
