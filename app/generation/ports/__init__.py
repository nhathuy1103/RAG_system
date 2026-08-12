"""Generation port contracts."""

from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Protocol

from app.generation.domain import GenerationEvent
from app.generation.domain.evidence import GenerationContext
from app.retrieval.domain.models import RetrievalCandidate


class AnswerGeneratorPort(Protocol):
    """Boundary between the chat use case and a concrete LLM provider."""

    def stream(
        self,
        *,
        question: str,
        evidence: tuple[RetrievalCandidate, ...],
        generation_context: GenerationContext | None = None,
    ) -> AsyncIterator[GenerationEvent]: ...


__all__ = ["AnswerGeneratorPort"]
