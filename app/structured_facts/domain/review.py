"""Reviewer-facing value objects for structured claim relations."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from uuid import UUID


class StructuredClaimRelationType(StrEnum):
    """Persisted directional relationship between two structured claims."""

    UNCHANGED = "unchanged"
    UPDATED = "updated"
    ADDED = "added"
    REMOVED = "removed"
    EQUIVALENT = "equivalent"
    SOURCE_UPDATES_TARGET = "source_updates_target"
    TARGET_UPDATES_SOURCE = "target_updates_source"
    SOURCE_SUPERSEDES_TARGET = "source_supersedes_target"
    TARGET_SUPERSEDES_SOURCE = "target_supersedes_source"
    SOURCE_CONTAINS_TARGET = "source_contains_target"
    TARGET_CONTAINS_SOURCE = "target_contains_source"
    SOURCE_ONLY = "source_only"
    TARGET_ONLY = "target_only"
    CONFLICT_CANDIDATE = "conflict_candidate"
    CONFLICT = "conflict"
    CONDITIONAL_VARIANT = "conditional_variant"
    DISTINCT = "distinct"
    UNCERTAIN = "uncertain"


class StructuredClaimReviewStatus(StrEnum):
    PENDING = "pending"
    AUTO_CONFIRMED = "auto_confirmed"
    CONFIRMED = "confirmed"
    DISMISSED = "dismissed"


class StructuredClaimResolutionAction(StrEnum):
    """Human actions accepted by ``resolve_structured_claim_relation``."""

    CONFIRM = "confirm"
    CONFIRM_EQUIVALENT = "confirm_equivalent"
    CONFIRM_UPDATE = "confirm_update"
    CONFIRM_CONFLICT = "confirm_conflict"
    CONFIRM_CONDITIONAL_VARIANT = "confirm_conditional_variant"
    DISMISS = "dismiss"


@dataclass(frozen=True, slots=True)
class StructuredClaimRelation:
    id: UUID
    owner_id: UUID
    notebook_id: UUID
    source_snapshot_id: UUID
    target_snapshot_id: UUID
    source_claim_id: UUID | None
    target_claim_id: UUID | None
    relation_type: StructuredClaimRelationType
    scope_relation: str
    qualifier_compatibility: str
    temporal_compatibility: str
    confidence: float
    evidence: Mapping[str, object]
    reason: str | None
    detector_name: str
    detector_version: str
    review_status: StructuredClaimReviewStatus
    resolved_by: UUID | None
    resolved_at: datetime | None
    created_at: datetime
    updated_at: datetime


@dataclass(frozen=True, slots=True)
class StructuredFactSnapshotEvidence:
    id: UUID
    document_id: UUID
    source_chunk_id: UUID | None
    snapshot_key: str
    schema_fingerprint: str
    template_fingerprint: str | None
    table_index: int
    page_from: int | None
    page_to: int | None
    source_locator: Mapping[str, object]
    normalized_schema: Mapping[str, object] | tuple[object, ...]
    row_count: int
    column_count: int
    extractor_name: str
    extractor_version: str
    publication_time: datetime | None
    effective_from: datetime | None
    effective_to: datetime | None
    observed_at: datetime | None
    ingested_at: datetime
    source_publisher: str | None
    source_type: str
    authority_level: int | None
    authority_metadata: Mapping[str, object]
    warnings: tuple[object, ...]
    extraction_confidence: float
    created_at: datetime
    updated_at: datetime


@dataclass(frozen=True, slots=True)
class StructuredFactClaimEvidence:
    id: UUID
    document_id: UUID
    snapshot_id: UUID
    source_chunk_id: UUID | None
    claim_key: str
    row_identity: str
    row_identity_hash: str
    row_index: int
    data_row_ordinal: int | None
    page_number: int | None
    source_text: str | None
    source_cells: tuple[object, ...]
    provenance: Mapping[str, object]
    subject_identity: Mapping[str, object]
    subject_identity_hash: str
    candidate_identity_hash: str
    predicate: str
    value_type: str
    normalized_value: Mapping[str, object]
    numeric_value: str | None
    unit: str | None
    currency: str | None
    qualifiers: Mapping[str, object]
    qualifier_hash: str
    publication_time: datetime | None
    effective_from: datetime | None
    effective_to: datetime | None
    observed_at: datetime | None
    ingested_at: datetime
    source_publisher: str | None
    source_type: str
    authority_level: int | None
    authority_metadata: Mapping[str, object]
    confidence: float
    is_derived: bool
    derivation: Mapping[str, object]
    extractor_version: str
    created_at: datetime
    updated_at: datetime


@dataclass(frozen=True, slots=True)
class StructuredClaimRelationEvidence:
    relation: StructuredClaimRelation
    source_snapshot: StructuredFactSnapshotEvidence
    target_snapshot: StructuredFactSnapshotEvidence
    source_claim: StructuredFactClaimEvidence | None
    target_claim: StructuredFactClaimEvidence | None


__all__ = [
    "StructuredClaimRelation",
    "StructuredClaimRelationEvidence",
    "StructuredClaimRelationType",
    "StructuredClaimResolutionAction",
    "StructuredClaimReviewStatus",
    "StructuredFactClaimEvidence",
    "StructuredFactSnapshotEvidence",
]
