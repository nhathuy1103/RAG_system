"""Logical-document lifecycle models used by the enterprise API."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime
from enum import StrEnum
from typing import Self
from uuid import UUID


class KnowledgeDocumentStatus(StrEnum):
    DRAFT = "DRAFT"
    PUBLISHED = "PUBLISHED"
    ARCHIVED = "ARCHIVED"


class DocumentVersionStatus(StrEnum):
    DRAFT = "DRAFT"
    READY_FOR_REVIEW = "READY_FOR_REVIEW"
    ACTIVE = "ACTIVE"
    REJECTED = "REJECTED"
    SUPERSEDED = "SUPERSEDED"


class ReviewDecision(StrEnum):
    APPROVE = "APPROVE"
    REJECT = "REJECT"
    REPROCESS = "REPROCESS"


class DocumentPermission(StrEnum):
    READ = "READ"
    DOWNLOAD = "DOWNLOAD"
    MANAGE = "MANAGE"
    REVIEW = "REVIEW"
    PUBLISH = "PUBLISH"
    ARCHIVE = "ARCHIVE"
    MANAGE_PERMISSION = "MANAGE_PERMISSION"


class ProcessingJobStatus(StrEnum):
    PENDING = "PENDING"
    RUNNING = "RUNNING"
    SUCCEEDED = "SUCCEEDED"
    FAILED = "FAILED"
    CANCELLED = "CANCELLED"


@dataclass(frozen=True, slots=True)
class KnowledgeDocument:
    id: UUID
    title: str
    description: str | None
    document_type: str | None
    category: str | None
    document_number: str | None
    issued_date: date | None
    effective_date: date | None
    expiration_date: date | None
    source: str | None
    owner_department_id: UUID | None
    status: str
    current_version_id: UUID | None
    metadata: dict[str, object] = field(default_factory=dict)
    created_by: UUID | None = None
    created_at: datetime | None = None
    updated_at: datetime | None = None
    archived_by: UUID | None = None
    archived_at: datetime | None = None
    archive_reason: str | None = None

    def ensure_mutable(self) -> Self:
        if self.status == KnowledgeDocumentStatus.ARCHIVED:
            raise EnterpriseDocumentStateError(
                "DOCUMENT_ARCHIVED", "Archived documents cannot be modified"
            )
        return self


@dataclass(frozen=True, slots=True)
class DocumentVersion:
    id: UUID
    document_id: UUID
    version_number: int
    source_file_id: UUID
    status: str
    previous_version_id: UUID | None
    change_summary: str | None
    effective_date: date | None
    created_by: UUID | None
    created_at: datetime | None
    updated_at: datetime | None
    legacy_document_id: UUID | None = None

    def ensure_reviewable(self) -> Self:
        if self.status != DocumentVersionStatus.READY_FOR_REVIEW:
            raise EnterpriseDocumentStateError(
                "VERSION_NOT_REVIEWABLE",
                "Only a version ready for review may be reviewed",
            )
        return self


@dataclass(frozen=True, slots=True)
class PermissionAssignment:
    id: UUID
    document_id: UUID
    subject_id: UUID
    permission: str
    status: str
    granted_by: UUID | None
    granted_at: datetime | None
    revoked_by: UUID | None = None
    revoked_at: datetime | None = None


@dataclass(frozen=True, slots=True)
class ProcessingJob:
    id: UUID
    document_version_id: UUID
    job_type: str
    status: str
    current_stage: str | None
    attempt_no: int
    previous_job_id: UUID | None
    requested_by: UUID | None
    requested_at: datetime | None
    started_at: datetime | None
    completed_at: datetime | None
    heartbeat_at: datetime | None
    lease_owner: str | None
    lease_expires_at: datetime | None
    error_code: str | None = None
    error_message: str | None = None


@dataclass(frozen=True, slots=True)
class ProcessingStageHistory:
    id: int
    processing_job_id: UUID
    stage: str
    status: str
    started_at: datetime
    completed_at: datetime | None
    message: str | None = None


@dataclass(frozen=True, slots=True)
class ProcessingError:
    id: UUID
    processing_job_id: UUID
    stage: str | None
    error_type: str
    error_code: str
    safe_message: str
    retryable: bool
    created_at: datetime


@dataclass(frozen=True, slots=True)
class ProcessingJobDetail:
    job: ProcessingJob
    stage_history: tuple[ProcessingStageHistory, ...] = ()
    errors: tuple[ProcessingError, ...] = ()


@dataclass(frozen=True, slots=True)
class VersionSource:
    bucket_name: str
    object_path: str
    original_file_name: str
    mime_type: str


@dataclass(frozen=True, slots=True)
class SourceFile:
    id: UUID
    bucket_name: str
    object_path: str
    original_file_name: str
    mime_type: str
    size_bytes: int
    sha256: str | None
    created_by: UUID
    created_at: datetime | None = None


@dataclass(frozen=True, slots=True)
class InitialDocumentUpload:
    document: KnowledgeDocument
    version: DocumentVersion
    processing_job: ProcessingJob
    source_file: SourceFile


@dataclass(frozen=True, slots=True)
class ReviewSourceFile:
    id: UUID
    original_file_name: str
    mime_type: str
    size_bytes: int
    sha256: str | None
    created_by: UUID
    created_at: datetime | None = None


@dataclass(frozen=True, slots=True)
class ReviewChunk:
    chunk_id: UUID
    chunk_index: int
    content: str
    page_start: int | None
    page_end: int | None
    section_path: str | None
    metadata: dict[str, object] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class DocumentVersionReviewContext:
    document: KnowledgeDocument
    version: DocumentVersion
    source_file: ReviewSourceFile
    latest_processing_job: ProcessingJob | None = None
    stage_history: tuple[ProcessingStageHistory, ...] = ()
    errors: tuple[ProcessingError, ...] = ()
    extracted_chunks: tuple[ReviewChunk, ...] = ()


@dataclass(frozen=True, slots=True)
class AccessDecision:
    allowed: bool
    sources: tuple[str, ...] = ()


class EnterpriseDocumentStateError(ValueError):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
