"""Knowledge-quality API schemas."""

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.knowledge_quality.domain.models import (
    RelationStatus,
    RelationType,
    ResolutionAction,
)


class DocumentRelationResponse(BaseModel):
    """One detected or resolved relationship between two documents."""

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    owner_id: UUID
    notebook_id: UUID
    source_document_id: UUID
    target_document_id: UUID
    relation_type: RelationType
    status: RelationStatus
    confidence: float
    signals: dict[str, object]
    reason: str | None
    detector_version: str
    preferred_document_id: UUID | None
    resolved_by: UUID | None
    resolved_at: datetime | None
    created_at: datetime
    updated_at: datetime


class DocumentRelationListResponse(BaseModel):
    """Paginated relation review queue."""

    items: list[DocumentRelationResponse]
    total_count: int
    limit: int
    offset: int


class RelationEvidenceDocumentResponse(BaseModel):
    """Small document summary displayed in relation evidence review."""

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    original_filename: str
    quality_status: str
    version_number: int
    is_current: bool
    canonical_document_id: UUID | None


class RelationEvidenceChunkResponse(BaseModel):
    """Chunk text and provenance used by the review diff."""

    model_config = ConfigDict(from_attributes=True)

    id: str
    document_id: UUID
    chunk_index: int
    content: str
    page_number: int | None
    section_title: str | None
    normalized_content_hash: str | None
    exact_duplicate_group_id: str | None


class RelationEvidenceChunkPairResponse(BaseModel):
    """Aligned source/target chunk evidence for highlighting."""

    model_config = ConfigDict(from_attributes=True)

    source_chunk: RelationEvidenceChunkResponse | None
    target_chunk: RelationEvidenceChunkResponse | None
    evidence_type: str
    confidence: float
    signals: dict[str, object]
    reason: str | None


class RelationEvidenceBlockResponse(BaseModel):
    """Rendered original-file block used by the two-file review modal."""

    model_config = ConfigDict(from_attributes=True)

    id: str
    document_id: UUID
    block_index: int
    block_type: str
    text: str
    page_number: int | None
    cells: list[str]
    highlight_type: str | None
    matched_pair_index: int | None
    confidence: float | None
    reason: str | None


class DocumentRelationEvidenceResponse(BaseModel):
    """Reviewer-facing evidence bundle for one relation."""

    model_config = ConfigDict(from_attributes=True)

    relation: DocumentRelationResponse
    source_document: RelationEvidenceDocumentResponse | None
    target_document: RelationEvidenceDocumentResponse | None
    chunk_pairs: list[RelationEvidenceChunkPairResponse]
    source_original_blocks: list[RelationEvidenceBlockResponse]
    target_original_blocks: list[RelationEvidenceBlockResponse]


class ResolveDocumentRelationRequest(BaseModel):
    """Human decision applied atomically to a relation and its documents."""

    action: ResolutionAction
    expected_updated_at: datetime
    reason: str = Field(min_length=1, max_length=2000)

    @field_validator("reason")
    @classmethod
    def validate_reason(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("reason must not be blank")
        return normalized


class RevertDocumentRelationRequest(BaseModel):
    """Optimistic reversal of the latest still-effective quality decision."""

    expected_updated_at: datetime
    reason: str = Field(min_length=1, max_length=2000)

    @field_validator("reason")
    @classmethod
    def validate_reason(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("reason must not be blank")
        return normalized


class KnowledgeQualityAuditResponse(BaseModel):
    """One immutable quality decision or reversal event."""

    id: int
    owner_id: UUID
    notebook_id: UUID
    relation_id: UUID | None
    actor_id: UUID | None
    action: str
    reason: str | None
    before_state: dict[str, object]
    after_state: dict[str, object]
    created_at: datetime


class KnowledgeQualityAuditListResponse(BaseModel):
    """Paginated notebook-scoped quality audit trail."""

    items: list[KnowledgeQualityAuditResponse]
    total_count: int
    limit: int
    offset: int


__all__ = [
    "DocumentRelationListResponse",
    "DocumentRelationResponse",
    "DocumentRelationEvidenceResponse",
    "KnowledgeQualityAuditListResponse",
    "KnowledgeQualityAuditResponse",
    "RelationEvidenceBlockResponse",
    "RelationEvidenceChunkPairResponse",
    "RelationEvidenceChunkResponse",
    "RelationEvidenceDocumentResponse",
    "RevertDocumentRelationRequest",
    "ResolveDocumentRelationRequest",
]
