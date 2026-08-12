"""P4 value objects for claim-grounded document relations.

The legacy :mod:`app.knowledge_quality.domain.models` relation enum remains the
database wire contract.  These objects retain the richer evaluation taxonomy
and its secondary evidence facets without changing old rows.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime
from enum import StrEnum

from app.knowledge_quality.domain.models import RelationStatus
from app.structured_facts.domain.models import ClaimRelation, SourceAuthority, TemporalContext

AGGREGATION_POLICY_VERSION = "p4-relation-aggregation-v1"
AUTHORITY_POLICY_VERSION = "p4-source-authority-v1"
RETRIEVAL_POLICY_VERSION = "p4-relation-retrieval-v1"


class FinalRelationType(StrEnum):
    """Frozen P4 relation taxonomy, including the preserved P0 template label."""

    EXACT_DUPLICATE = "EXACT_DUPLICATE"
    NEAR_DUPLICATE = "NEAR_DUPLICATE"
    VERSION_UPDATE = "VERSION_UPDATE"
    TEMPORAL_VARIANT = "TEMPORAL_VARIANT"
    CONDITIONAL_VARIANT = "CONDITIONAL_VARIANT"
    TEMPLATE_VARIANT = "TEMPLATE_VARIANT"
    CONFLICT = "CONFLICT"
    DISTINCT = "DISTINCT"
    UNCERTAIN = "UNCERTAIN"


class VersionDirection(StrEnum):
    """Direction is expressed as which pair member is the successor."""

    SOURCE_SUPERSEDES_TARGET = "source_supersedes_target"
    TARGET_SUPERSEDES_SOURCE = "target_supersedes_source"
    UNKNOWN = "unknown"
    NOT_APPLICABLE = "not_applicable"


@dataclass(frozen=True, slots=True)
class DocumentRelationContext:
    """Document metadata permitted to influence P4 after P2/P3 comparison."""

    document_id: str
    owner_id: str
    notebook_id: str
    strict_content_hash: str | None = None
    normalization_version: str | None = None
    document_family_id: str | None = None
    version_number: int | None = None
    temporal: TemporalContext = field(default_factory=TemporalContext)
    authority: SourceAuthority = field(default_factory=SourceAuthority)
    status: str = "active"
    is_current: bool | None = None

    def __post_init__(self) -> None:
        for name in ("document_id", "owner_id", "notebook_id"):
            if not str(getattr(self, name)).strip():
                raise ValueError(f"{name} cannot be blank")
        if self.version_number is not None and self.version_number < 0:
            raise ValueError("version_number cannot be negative")


@dataclass(frozen=True, slots=True)
class ClaimConflictEvidence:
    """The exact aligned claims that made a document conflict visible."""

    predicate: str
    source_claim_id: str | None
    target_claim_id: str | None
    source_value: dict[str, object] | None
    target_value: dict[str, object] | None
    confidence: float
    reason_codes: tuple[str, ...]

    def to_payload(self) -> dict[str, object]:
        return {
            "predicate": self.predicate,
            "source_claim_id": self.source_claim_id,
            "target_claim_id": self.target_claim_id,
            "source_value": self.source_value,
            "target_value": self.target_value,
            "confidence": self.confidence,
            "reason_codes": list(self.reason_codes),
        }


@dataclass(frozen=True, slots=True)
class RelationFacets:
    """Secondary semantics retained even when precedence selects one label."""

    has_conflict: bool = False
    has_version_changes: bool = False
    has_added_claims: bool = False
    has_removed_claims: bool = False
    has_updated_claims: bool = False
    has_conditional_variants: bool = False
    has_temporal_variants: bool = False
    has_uncertain_evidence: bool = False
    is_technical_duplicate: bool = False

    def to_payload(self) -> dict[str, bool]:
        return {
            "has_conflict": self.has_conflict,
            "has_version_changes": self.has_version_changes,
            "has_added_claims": self.has_added_claims,
            "has_removed_claims": self.has_removed_claims,
            "has_updated_claims": self.has_updated_claims,
            "has_conditional_variants": self.has_conditional_variants,
            "has_temporal_variants": self.has_temporal_variants,
            "has_uncertain_evidence": self.has_uncertain_evidence,
            "is_technical_duplicate": self.is_technical_duplicate,
        }


@dataclass(frozen=True, slots=True)
class RelationEvidenceSummary:
    """Canonical O(number-of-claim-relations) P4 aggregation output."""

    source_document_id: str
    target_document_id: str
    owner_id: str
    notebook_id: str
    primary_relation: FinalRelationType
    claim_relations: tuple[ClaimRelation, ...]
    source_claim_count: int
    target_claim_count: int
    aligned_claim_count: int
    unchanged_count: int
    updated_count: int
    added_count: int
    removed_count: int
    conditional_count: int
    conflict_count: int
    uncertain_count: int
    source_coverage: float
    target_coverage: float
    facets: RelationFacets
    confidence: float
    reason_codes: tuple[str, ...]
    conflict_claims: tuple[ClaimConflictEvidence, ...] = ()
    unchanged_predicates: tuple[str, ...] = ()
    updated_predicates: tuple[str, ...] = ()
    added_predicates: tuple[str, ...] = ()
    removed_predicates: tuple[str, ...] = ()
    conflicting_predicates: tuple[str, ...] = ()
    same_periods: tuple[str, ...] = ()
    conflicting_periods: tuple[str, ...] = ()
    version_direction: VersionDirection = VersionDirection.NOT_APPLICABLE
    preferred_document_id: str | None = None
    preference_reason: str | None = None
    review_status: RelationStatus = RelationStatus.PENDING
    aggregation_version: str = AGGREGATION_POLICY_VERSION
    authority_policy_version: str = AUTHORITY_POLICY_VERSION
    retrieval_policy_version: str = RETRIEVAL_POLICY_VERSION
    claim_extractor_versions: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        for name in ("source_coverage", "target_coverage", "confidence"):
            value = getattr(self, name)
            if not 0.0 <= value <= 1.0:
                raise ValueError(f"{name} must be between 0 and 1")

    def to_signals(self) -> dict[str, object]:
        """Serialize into the existing ``document_relations.signals`` JSONB."""
        return {
            "p4_primary_relation": self.primary_relation.value,
            "p4_facets": self.facets.to_payload(),
            "p4_claim_summary": {
                "source_claim_count": self.source_claim_count,
                "target_claim_count": self.target_claim_count,
                "aligned_claim_count": self.aligned_claim_count,
                "unchanged_count": self.unchanged_count,
                "updated_count": self.updated_count,
                "added_count": self.added_count,
                "removed_count": self.removed_count,
                "conditional_count": self.conditional_count,
                "conflict_count": self.conflict_count,
                "uncertain_count": self.uncertain_count,
                "source_coverage": self.source_coverage,
                "target_coverage": self.target_coverage,
            },
            "p4_claim_relations": [relation.to_payload() for relation in self.claim_relations],
            "p4_conflict_claims": [claim.to_payload() for claim in self.conflict_claims],
            "p4_predicates": {
                "unchanged": list(self.unchanged_predicates),
                "updated": list(self.updated_predicates),
                "added": list(self.added_predicates),
                "removed": list(self.removed_predicates),
                "conflicting": list(self.conflicting_predicates),
            },
            "p4_temporal": {
                "same_periods": list(self.same_periods),
                "conflicting_periods": list(self.conflicting_periods),
            },
            "p4_version_direction": self.version_direction.value,
            "p4_reason_codes": list(self.reason_codes),
            "p4_versions": {
                "aggregation": self.aggregation_version,
                "authority": self.authority_policy_version,
                "retrieval": self.retrieval_policy_version,
                "claim_extractors": list(self.claim_extractor_versions),
            },
            "p4_preference": {
                "document_id": self.preferred_document_id,
                "reason": self.preference_reason,
            },
            "p4_review_status": self.review_status.value,
        }


def temporal_business_key(value: date | datetime | None) -> tuple[int, int, int, int, int, int]:
    """Comparable key that never falls back to ingestion time."""
    if value is None:
        return (0, 0, 0, 0, 0, 0)
    if isinstance(value, datetime):
        return (value.year, value.month, value.day, value.hour, value.minute, value.second)
    return (value.year, value.month, value.day, 0, 0, 0)


__all__ = [
    "AGGREGATION_POLICY_VERSION",
    "AUTHORITY_POLICY_VERSION",
    "RETRIEVAL_POLICY_VERSION",
    "ClaimConflictEvidence",
    "DocumentRelationContext",
    "FinalRelationType",
    "RelationEvidenceSummary",
    "RelationFacets",
    "VersionDirection",
    "temporal_business_key",
]
