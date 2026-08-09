"""Framework-agnostic value objects for the retrieval bounded context."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field

from app.retrieval.domain.metadata import EvidenceMetadata, MetadataValue


@dataclass(frozen=True)
class StructuredMetadataFilters:
    """Measured, exact-match metadata filters used before ranking.

    Values are canonical identifiers or normalized enums. A populated field is
    fail-closed: chunks that do not carry that field cannot match it.
    """

    document_type: str | None = None
    content_kind: str | None = None
    project_id: str | None = None
    project_code: str | None = None
    year: int | None = None
    data_period: str | None = None
    effective_status: str | None = None

    def __post_init__(self) -> None:
        for name in (
            "document_type",
            "content_kind",
            "project_id",
            "project_code",
            "data_period",
            "effective_status",
        ):
            value = getattr(self, name)
            if value is not None and not str(value).strip():
                raise ValueError(f"{name} must not be blank")
            if value is not None:
                normalized = str(value).strip()
                if name in {"document_type", "content_kind", "effective_status"}:
                    normalized = normalized.casefold()
                elif name in {"project_code", "data_period"}:
                    normalized = normalized.upper()
                object.__setattr__(self, name, normalized)
        if self.year is not None and not 1900 <= self.year <= 2100:
            raise ValueError("year must be between 1900 and 2100")

    def active_items(self) -> tuple[tuple[str, str | int], ...]:
        return tuple(
            (name, value)
            for name, value in (
                ("document_type", self.document_type),
                ("content_kind", self.content_kind),
                ("project_id", self.project_id),
                ("project_code", self.project_code),
                ("year", self.year),
                ("data_period", self.data_period),
                ("effective_status", self.effective_status),
            )
            if value is not None
        )

    def as_dict(self) -> dict[str, str | int]:
        return dict(self.active_items())


@dataclass(frozen=True)
class RetrievalFilters:
    """Security and document scope applied by every retrieval adapter.

    ``document_ids=None`` means no explicit document-list restriction.
    ``document_ids=()`` means the caller has no allowed documents and MUST
    produce no results. Adapters must not treat an empty tuple as if the
    document filter were absent.
    """

    owner_id: str
    notebook_id: str | None = None
    document_ids: tuple[str, ...] | None = None
    metadata: StructuredMetadataFilters = field(default_factory=StructuredMetadataFilters)


@dataclass(frozen=True)
class EvidenceChunk:
    """A retrievable unit of the user's own uploaded document content."""

    id: str
    document_id: str
    text: str
    metadata: Mapping[str, MetadataValue] = field(default_factory=EvidenceMetadata)
    search_text: str | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.metadata, EvidenceMetadata):
            object.__setattr__(
                self,
                "metadata",
                EvidenceMetadata.from_mapping(self.metadata),
            )

    @property
    def typed_metadata(self) -> EvidenceMetadata:
        metadata = self.metadata
        if not isinstance(metadata, EvidenceMetadata):  # pragma: no cover - post-init invariant
            raise TypeError("EvidenceChunk metadata was not normalized")
        return metadata


@dataclass(frozen=True)
class RetrievalCandidate:
    """One scored/ranked result returned by a retrieval adapter."""

    chunk: EvidenceChunk
    score: float
    rank: int
    source: str = "hybrid"


@dataclass(frozen=True)
class SufficiencyCheck:
    """Verdict on whether accumulated evidence answers the question in full."""

    sufficient: bool
    missing: str | None = None
    reasoning: str | None = None


@dataclass(frozen=True)
class AgenticRetrievalRound:
    """One iteration of the retrieve -> accumulate -> self-correction loop."""

    round_index: int
    query_used: str
    new_evidence_count: int
    sufficiency: SufficiencyCheck


@dataclass(frozen=True)
class AgenticRetrievalResult:
    """Final outcome of the loop: accumulated evidence plus a trace for debugging."""

    evidence: tuple[RetrievalCandidate, ...]
    rounds_used: int
    gave_up: bool
    trace: tuple[AgenticRetrievalRound, ...]


@dataclass(frozen=True)
class ContextualizedQuestion:
    """Outcome of SPEC step ① (Contextualize) feeding step ② (Ambiguity check)."""

    resolved_question: str
    is_ambiguous: bool
    clarifying_question: str | None = None
    reasoning: str | None = None


@dataclass(frozen=True)
class AdaptiveDecision:
    """Outcome of SPEC step ④ (Adaptive)."""

    needs_retrieval: bool
    fixed_answer: str | None = None
    reasoning: str | None = None


__all__ = [
    "AdaptiveDecision",
    "AgenticRetrievalResult",
    "AgenticRetrievalRound",
    "ContextualizedQuestion",
    "EvidenceChunk",
    "RetrievalCandidate",
    "RetrievalFilters",
    "StructuredMetadataFilters",
    "SufficiencyCheck",
]
