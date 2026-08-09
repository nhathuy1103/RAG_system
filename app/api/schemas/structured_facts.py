"""API contracts for reviewing structured claim relations."""

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.structured_facts.domain.review import (
    StructuredClaimRelationType,
    StructuredClaimResolutionAction,
    StructuredClaimReviewStatus,
)


class StructuredClaimRelationResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

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
    evidence: dict[str, object]
    reason: str | None
    detector_name: str
    detector_version: str
    review_status: StructuredClaimReviewStatus
    resolved_by: UUID | None
    resolved_at: datetime | None
    created_at: datetime
    updated_at: datetime


class StructuredClaimRelationListResponse(BaseModel):
    items: list[StructuredClaimRelationResponse]
    total_count: int
    limit: int
    offset: int


class StructuredFactSnapshotEvidenceResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    document_id: UUID
    source_chunk_id: UUID | None
    snapshot_key: str
    schema_fingerprint: str
    template_fingerprint: str | None
    table_index: int
    page_from: int | None
    page_to: int | None
    source_locator: dict[str, object]
    normalized_schema: dict[str, object] | list[object]
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
    authority_metadata: dict[str, object]
    warnings: list[object]
    extraction_confidence: float
    created_at: datetime
    updated_at: datetime


class StructuredFactClaimEvidenceResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

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
    source_cells: list[object]
    provenance: dict[str, object]
    subject_identity: dict[str, object]
    subject_identity_hash: str
    candidate_identity_hash: str
    predicate: str
    value_type: str
    normalized_value: dict[str, object]
    numeric_value: str | None
    unit: str | None
    currency: str | None
    qualifiers: dict[str, object]
    qualifier_hash: str
    publication_time: datetime | None
    effective_from: datetime | None
    effective_to: datetime | None
    observed_at: datetime | None
    ingested_at: datetime
    source_publisher: str | None
    source_type: str
    authority_level: int | None
    authority_metadata: dict[str, object]
    confidence: float
    is_derived: bool
    derivation: dict[str, object]
    extractor_version: str
    created_at: datetime
    updated_at: datetime


class StructuredClaimRelationEvidenceResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    relation: StructuredClaimRelationResponse
    source_snapshot: StructuredFactSnapshotEvidenceResponse
    target_snapshot: StructuredFactSnapshotEvidenceResponse
    source_claim: StructuredFactClaimEvidenceResponse | None
    target_claim: StructuredFactClaimEvidenceResponse | None


class ResolveStructuredClaimRelationRequest(BaseModel):
    action: StructuredClaimResolutionAction
    expected_updated_at: datetime
    reason: str = Field(min_length=1, max_length=2000)

    @field_validator("expected_updated_at")
    @classmethod
    def require_timezone(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("expected_updated_at must include a timezone offset")
        return value

    @field_validator("reason")
    @classmethod
    def normalize_reason(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("reason must not be blank")
        return normalized


__all__ = [
    "ResolveStructuredClaimRelationRequest",
    "StructuredClaimRelationEvidenceResponse",
    "StructuredClaimRelationListResponse",
    "StructuredClaimRelationResponse",
    "StructuredFactClaimEvidenceResponse",
    "StructuredFactSnapshotEvidenceResponse",
]
