"""Generation domain model and business rules."""

from __future__ import annotations

from dataclasses import dataclass

from app.retrieval.domain.models import RetrievalCandidate


@dataclass(frozen=True)
class TokenChunk:
    """One piece of streamed answer text."""

    text: str


@dataclass(frozen=True)
class CitationHit:
    """A source id the model referenced, in first-appearance order."""

    source_id: str
    ordinal: int
    candidate: RetrievalCandidate


@dataclass(frozen=True)
class UsageInfo:
    """Token accounting reported by the provider for one generation call."""

    input_tokens: int | None
    output_tokens: int | None


GenerationEvent = TokenChunk | CitationHit | UsageInfo


__all__ = ["CitationHit", "GenerationEvent", "TokenChunk", "UsageInfo"]
