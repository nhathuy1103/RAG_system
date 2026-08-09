"""Port for Contextualize + Ambiguity check — SPEC steps ①-②."""

from __future__ import annotations

from typing import Protocol

from app.retrieval.domain.models import ContextualizedQuestion


class ContextualizerPort(Protocol):
    """Resolve a message into a self-contained question, or flag it unresolvable."""

    def contextualize(
        self,
        message: str,
        history: tuple[str, ...],
    ) -> ContextualizedQuestion: ...


__all__ = ["ContextualizerPort"]
