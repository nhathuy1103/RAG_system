"""Document request and response schemas."""

from datetime import date, datetime
from uuid import UUID

from pydantic import BaseModel


class DocumentResponse(BaseModel):
    """Document metadata returned after a successful upload."""

    id: UUID
    owner_id: UUID
    notebook_id: UUID
    original_filename: str
    storage_bucket: str
    storage_object_path: str
    mime_type: str
    size_bytes: int
    content_hash: str | None
    status: str
    error_message: str | None
    is_active: bool
    created_at: datetime
    updated_at: datetime
    normalized_content_hash: str | None = None
    normalization_version: str | None = None
    loose_content_signature: str | None = None
    canonical_document_id: UUID | None = None
    version_group_id: UUID | None = None
    version_number: int = 1
    effective_from: date | None = None
    effective_to: date | None = None
    supersedes_document_id: UUID | None = None
    is_current: bool = True
    quality_status: str = "unreviewed"


class DocumentListResponse(BaseModel):
    """Paginated documents belonging to one notebook."""

    items: list[DocumentResponse]
    total_count: int
    limit: int
    offset: int


class DocumentDeleteResponse(BaseModel):
    """Confirmation returned after a document has been archived (soft-deleted)."""

    message: str
    document_id: UUID


class DocumentUploadItemResponse(BaseModel):
    """Per-file result in a batch upload response."""

    filename: str
    document: DocumentResponse | None = None
    error_code: str | None = None
    error_message: str | None = None
    # True when `document` is a pre-existing document reused because this
    # file's content is byte-identical to one already in the notebook (Layer 1
    # exact-hash dedup) — no new upload/ingestion happened for this item.
    duplicate: bool = False


class DocumentUploadBatchResponse(BaseModel):
    """Aggregate result for one or more independently processed files."""

    total_count: int
    succeeded_count: int
    failed_count: int
    items: list[DocumentUploadItemResponse]
