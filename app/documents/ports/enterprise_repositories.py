"""Persistence contract for enterprise logical documents and lifecycle operations."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from typing import Protocol
from uuid import UUID

from app.documents.domain.enterprise_models import (
    AccessDecision,
    DocumentMetadataAssertion,
    DocumentSearchability,
    DocumentVersion,
    DocumentVersionReviewContext,
    InitialDocumentUpload,
    KnowledgeDocument,
    PermissionAssignment,
    ProcessingJob,
    ProcessingJobDetail,
    SourceFile,
    VersionSource,
)


class EnterpriseDocumentRepositoryError(RuntimeError):
    pass


class EnterpriseDocumentConflictError(EnterpriseDocumentRepositoryError):
    pass


class EnterpriseDocumentAccessDeniedError(EnterpriseDocumentRepositoryError):
    pass


@dataclass(frozen=True, slots=True)
class NewKnowledgeDocument:
    title: str
    description: str | None = None
    document_type: str | None = None
    category: str | None = None
    metadata: dict[str, object] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class NewDocumentVersion:
    document_id: UUID
    source_file_id: UUID
    change_summary: str | None = None
    effective_date: date | None = None


@dataclass(frozen=True, slots=True)
class NewSourceFile:
    id: UUID
    bucket_name: str
    object_path: str
    original_file_name: str
    mime_type: str
    size_bytes: int
    sha256: str
    created_by: UUID


@dataclass(frozen=True, slots=True)
class NewInitialDocumentUpload:
    document: NewKnowledgeDocument
    source_file: NewSourceFile
    change_summary: str | None = None
    effective_date: date | None = None


class EnterpriseDocumentRepository(Protocol):
    async def create_source_file(self, value: NewSourceFile) -> SourceFile: ...

    async def create_initial_document_upload(
        self, value: NewInitialDocumentUpload
    ) -> InitialDocumentUpload: ...

    async def list_documents(
        self, *, document_status: str | None, limit: int, offset: int
    ) -> tuple[list[KnowledgeDocument], int]: ...

    async def get_document(self, document_id: UUID) -> KnowledgeDocument | None: ...

    async def list_searchability(
        self, *, document_id: UUID | None
    ) -> list[DocumentSearchability]: ...

    async def create_document(self, value: NewKnowledgeDocument) -> KnowledgeDocument: ...

    async def update_document(
        self, document_id: UUID, changes: dict[str, object]
    ) -> KnowledgeDocument | None: ...

    async def list_versions(self, document_id: UUID) -> list[DocumentVersion]: ...

    async def get_version_review_context(
        self, version_id: UUID
    ) -> DocumentVersionReviewContext | None: ...

    async def create_version(self, value: NewDocumentVersion) -> DocumentVersion: ...

    async def review_version(
        self,
        version_id: UUID,
        *,
        decision: str,
        note: str | None,
        rejection_reason: str | None,
    ) -> DocumentVersion: ...

    async def list_metadata_assertions(
        self, version_id: UUID, *, verification_status: str | None
    ) -> list[DocumentMetadataAssertion]: ...

    async def review_metadata_assertion(
        self,
        assertion_id: UUID,
        *,
        decision: str,
        rejection_reason: str | None,
    ) -> DocumentMetadataAssertion: ...

    async def publish_version(self, version_id: UUID) -> DocumentVersion: ...

    async def archive_document(self, document_id: UUID, *, reason: str) -> KnowledgeDocument: ...

    async def list_permissions(self, document_id: UUID) -> list[PermissionAssignment]: ...

    async def grant_permission(
        self, document_id: UUID, subject_id: UUID, permission: str
    ) -> PermissionAssignment: ...

    async def revoke_permission(
        self, document_id: UUID, subject_id: UUID, permission: str
    ) -> None: ...

    async def test_access(self, user_id: UUID, document_id: UUID, permission: str) -> bool: ...

    async def explain_access(
        self, user_id: UUID, document_id: UUID, permission: str
    ) -> AccessDecision: ...

    async def list_processing_jobs(
        self,
        *,
        document_id: UUID | None,
        document_version_id: UUID | None,
        job_status: str | None,
        limit: int,
        offset: int,
    ) -> tuple[list[ProcessingJob], int]: ...

    async def get_processing_job(self, job_id: UUID) -> ProcessingJob | None: ...

    async def get_processing_job_detail(self, job_id: UUID) -> ProcessingJobDetail | None: ...

    async def retry_processing_job(self, job_id: UUID) -> ProcessingJob: ...

    async def get_version_source(
        self, document_id: UUID, version_id: UUID
    ) -> VersionSource | None: ...
