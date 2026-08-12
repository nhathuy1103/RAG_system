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
from dataclasses import dataclass

from app.generation.domain import CitationHit
from app.generation.domain.evidence import EvidenceBundleType, GenerationContext
from app.retrieval.domain.models import RetrievalCandidate

_SOURCE_MARKER_PATTERN = re.compile(r"\[(SRC-[^\[\]]+)\]")
_NUMERIC_FACT_PATTERN = re.compile(r"(?<![\w-])\d+(?:[.,]\d+)*(?![\w-])")
_SENTENCE_BOUNDARY_PATTERN = re.compile(r"(?<!\d)[.!?]+(?!\d)|\n+")


@dataclass(frozen=True, slots=True)
class P5CitationDiagnostics:
    referenced_source_ids: tuple[str, ...]
    material_statement_count: int
    cited_material_statement_count: int
    numeric_statement_count: int
    supported_numeric_statement_count: int
    conflict_bundle_count: int
    complete_conflict_bundle_count: int

    @property
    def citation_coverage(self) -> float:
        if not self.material_statement_count:
            return 1.0
        return self.cited_material_statement_count / self.material_statement_count

    @property
    def numeric_support_accuracy(self) -> float:
        if not self.numeric_statement_count:
            return 1.0
        return self.supported_numeric_statement_count / self.numeric_statement_count


class CitationValidationError(RuntimeError):
    """Raised when an answer's citations cannot be traced to supplied evidence."""

    def __init__(self, message: str, *, code: str = "INVALID_CITATION") -> None:
        super().__init__(message)
        self.code = code


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
        raise CitationValidationError(
            f"Unknown citation source: {hit.source_id}",
            code="UNKNOWN_CITATION_SOURCE",
        )
    if hit.source_id in accepted_source_ids:
        raise CitationValidationError(
            f"Duplicate citation event: {hit.source_id}",
            code="DUPLICATE_CITATION_EVENT",
        )
    expected_ordinal = len(accepted_source_ids) + 1
    if hit.ordinal != expected_ordinal:
        raise CitationValidationError(
            f"Citation {hit.source_id} has ordinal {hit.ordinal}; expected {expected_ordinal}",
            code="INVALID_CITATION_ORDER",
        )
    if (
        hit.candidate.chunk.id != expected.chunk.id
        or hit.candidate.chunk.document_id != expected.chunk.document_id
    ):
        raise CitationValidationError(
            f"Citation {hit.source_id} is attached to evidence outside its alias",
            code="CITATION_EVIDENCE_MISMATCH",
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

    if require_citation and not answer.strip():
        raise CitationValidationError(
            "Grounded answer is empty",
            code="EMPTY_GROUNDED_ANSWER",
        )

    referenced = tuple(
        dict.fromkeys(match.group(1) for match in _SOURCE_MARKER_PATTERN.finditer(answer))
    )
    unknown = tuple(source_id for source_id in referenced if source_id not in evidence_by_alias)
    if unknown:
        raise CitationValidationError(
            "Answer contains unknown citation source(s): " + ", ".join(unknown),
            code="UNKNOWN_CITATION_SOURCE",
        )
    accepted = tuple(accepted_source_ids)
    if accepted != referenced:
        raise CitationValidationError(
            "Citation events do not match the markers present in the answer",
            code="CITATION_MARKER_EVENT_MISMATCH",
        )
    if require_citation and not referenced:
        raise CitationValidationError(
            "Grounded answer contains no citation marker",
            code="MISSING_CITATION_MARKER",
        )
    return referenced


def validate_p5_citation_contract(
    answer: str,
    *,
    context: GenerationContext,
    accepted_source_ids: Sequence[str],
) -> P5CitationDiagnostics:
    """Validate P5 citation coverage, numeric support, and conflict completeness."""

    evidence_by_alias = {item.evidence_id: item.candidate for item in context.evidence}
    referenced = validate_answer_citations(
        answer,
        evidence_by_alias=evidence_by_alias,
        accepted_source_ids=accepted_source_ids,
        require_citation=False,
    )
    query_numbers = set(_numbers(context.query.raw_query))
    material_count = 0
    cited_material_count = 0
    numeric_count = 0
    supported_numeric_count = 0
    for raw_statement in _SENTENCE_BOUNDARY_PATTERN.split(answer):
        statement = raw_statement.strip()
        if not statement:
            continue
        source_ids = tuple(
            dict.fromkeys(value.group(1) for value in _SOURCE_MARKER_PATTERN.finditer(statement))
        )
        statement_numbers = set(_numbers(_SOURCE_MARKER_PATTERN.sub("", statement)))
        material = bool(statement_numbers) or any(
            token in statement.casefold()
            for token in ("reports", "states", "source", "nguồn", "tài liệu", "mâu thuẫn")
        )
        if not material:
            continue
        material_count += 1
        if source_ids:
            cited_material_count += 1
        else:
            raise CitationValidationError(
                "Material factual statement has no inline citation",
                code="UNCITED_MATERIAL_STATEMENT",
            )
        if not statement_numbers:
            continue
        numeric_count += 1
        evidence_numbers = set(query_numbers)
        for source_id in source_ids:
            item = context.evidence_by_id.get(source_id)
            if item is not None:
                evidence_numbers.update(_numbers(item.text))
                evidence_numbers.update(_numbers(str(dict(item.value))))
                evidence_numbers.update(_numbers(str(dict(item.temporal))))
        if statement_numbers <= evidence_numbers:
            supported_numeric_count += 1
        else:
            unsupported = sorted(statement_numbers - evidence_numbers)
            raise CitationValidationError(
                "Answer contains numeric value(s) unsupported by cited evidence: "
                + ", ".join(unsupported),
                code="UNSUPPORTED_NUMERIC_STATEMENT",
            )

    conflict_bundles = tuple(
        bundle
        for bundle in context.bundles
        if bundle.bundle_type is EvidenceBundleType.CONFLICT_SET
    )
    referenced_set = set(referenced)
    complete_conflicts = sum(
        set(bundle.evidence_ids) <= referenced_set for bundle in conflict_bundles
    )
    if complete_conflicts != len(conflict_bundles):
        raise CitationValidationError(
            "Confirmed conflict answer does not cite every visible side",
            code="INCOMPLETE_CONFLICT_CITATION",
        )
    if not referenced:
        raise CitationValidationError(
            "Grounded answer contains no citation marker",
            code="MISSING_CITATION_MARKER",
        )
    return P5CitationDiagnostics(
        referenced_source_ids=referenced,
        material_statement_count=material_count,
        cited_material_statement_count=cited_material_count,
        numeric_statement_count=numeric_count,
        supported_numeric_statement_count=supported_numeric_count,
        conflict_bundle_count=len(conflict_bundles),
        complete_conflict_bundle_count=complete_conflicts,
    )


def _numbers(value: str) -> tuple[str, ...]:
    return tuple(
        match.group(0).replace(",", ".") for match in _NUMERIC_FACT_PATTERN.finditer(value)
    )


__all__ = [
    "CitationValidationError",
    "P5CitationDiagnostics",
    "build_evidence_aliases",
    "validate_answer_citations",
    "validate_citation_hit",
    "validate_p5_citation_contract",
]
