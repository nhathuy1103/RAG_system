"""Fail-closed validation for model-produced citation markers.

The answer generator is an untrusted boundary: even when its prompt contains
only authorised evidence, a provider (or another adapter implementing the
port) can emit a fabricated alias or attach the wrong candidate to a citation
event.  These helpers validate the completed answer and every citation event
against the exact, turn-local evidence mapping used for generation.
"""

from __future__ import annotations

import re
from collections.abc import Mapping, Sequence

from app.generation.domain import CitationHit
from app.retrieval.domain.models import RetrievalCandidate

_SOURCE_MARKER_PATTERN = re.compile(r"\[(SRC-[^\[\]]+)\]")


class CitationValidationError(RuntimeError):
    """Raised when an answer's citations cannot be traced to supplied evidence."""


def build_evidence_aliases(
    evidence: tuple[RetrievalCandidate, ...],
) -> dict[str, RetrievalCandidate]:
    """Return the canonical alias mapping shared with answer generators."""

    return {f"SRC-{ordinal}": candidate for ordinal, candidate in enumerate(evidence, start=1)}


def validate_citation_hit(
    hit: CitationHit,
    *,
    evidence_by_alias: Mapping[str, RetrievalCandidate],
    accepted_source_ids: Sequence[str],
) -> RetrievalCandidate:
    """Validate one streamed citation event and return its trusted candidate.

    The caller must use the returned candidate instead of ``hit.candidate`` so
    an adapter cannot smuggle a different document through a valid alias.
    """

    expected = evidence_by_alias.get(hit.source_id)
    if expected is None:
        raise CitationValidationError(f"Unknown citation source: {hit.source_id}")
    if hit.source_id in accepted_source_ids:
        raise CitationValidationError(f"Duplicate citation event: {hit.source_id}")
    expected_ordinal = len(accepted_source_ids) + 1
    if hit.ordinal != expected_ordinal:
        raise CitationValidationError(
            f"Citation {hit.source_id} has ordinal {hit.ordinal}; expected {expected_ordinal}"
        )
    if (
        hit.candidate.chunk.id != expected.chunk.id
        or hit.candidate.chunk.document_id != expected.chunk.document_id
    ):
        raise CitationValidationError(
            f"Citation {hit.source_id} is attached to evidence outside its alias"
        )
    return expected


def validate_answer_citations(
    answer: str,
    *,
    evidence_by_alias: Mapping[str, RetrievalCandidate],
    accepted_source_ids: Sequence[str],
    require_citation: bool = True,
) -> tuple[str, ...]:
    """Validate final marker/event consistency in first-appearance order."""

    referenced = tuple(
        dict.fromkeys(match.group(1) for match in _SOURCE_MARKER_PATTERN.finditer(answer))
    )
    unknown = tuple(source_id for source_id in referenced if source_id not in evidence_by_alias)
    if unknown:
        raise CitationValidationError(
            "Answer contains unknown citation source(s): " + ", ".join(unknown)
        )
    accepted = tuple(accepted_source_ids)
    if accepted != referenced:
        raise CitationValidationError(
            "Citation events do not match the markers present in the answer"
        )
    if require_citation and answer.strip() and not referenced:
        raise CitationValidationError("Grounded answer contains no citation marker")
    return referenced


__all__ = [
    "CitationValidationError",
    "build_evidence_aliases",
    "validate_answer_citations",
    "validate_citation_hit",
]
