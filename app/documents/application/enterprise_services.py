"""Application services for logical documents, versions, ACL and processing."""

from __future__ import annotations

import logging
from datetime import date
from uuid import UUID, uuid4

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
    ReviewDecision,
    SourceFile,
    VersionSource,
)
from app.documents.domain.models import DocumentFileValidationError, validate_document_file
from app.documents.ports.enterprise_repositories import (
    EnterpriseDocumentRepository,
    EnterpriseDocumentRepositoryError,
    NewDocumentVersion,
    NewInitialDocumentUpload,
    NewKnowledgeDocument,
    NewSourceFile,
)
from app.documents.ports.storage import DocumentObjectStorage, ObjectStorageError

LOGGER = logging.getLogger(__name__)
ENTERPRISE_SOURCE_BUCKET = "knowledge-source-files"


class EnterpriseDocumentValidationError(ValueError):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


class EnterpriseDocumentService:
    def __init__(self, repository: EnterpriseDocumentRepository) -> None:
        self._repository = repository

    async def list_documents(
        self, *, document_status: str | None, limit: int, offset: int
    ) -> tuple[list[KnowledgeDocument], int]:
        return await self._repository.list_documents(
            document_status=document_status, limit=limit, offset=offset
        )

    async def get_document(self, document_id: UUID) -> KnowledgeDocument | None:
        return await self._repository.get_document(document_id)

    async def list_searchability(self, *, document_id: UUID | None) -> list[DocumentSearchability]:
        return await self._repository.list_searchability(document_id=document_id)

    async def create_document(self, value: NewKnowledgeDocument) -> KnowledgeDocument:
        title = value.title.strip()
        if not title:
            raise EnterpriseDocumentValidationError("INVALID_TITLE", "Document title is required")
        return await self._repository.create_document(
            NewKnowledgeDocument(
                title=title,
                description=value.description,
                document_type=value.document_type,
                category=value.category,
                metadata=value.metadata,
            )
        )

    async def update_document(
        self, document_id: UUID, changes: dict[str, object]
    ) -> KnowledgeDocument | None:
        document = await self._repository.get_document(document_id)
        if document is None:
            return None
        document.ensure_mutable()
        title = changes.get("title")
        if isinstance(title, str):
            title = title.strip()
            if not title:
                raise EnterpriseDocumentValidationError(
                    "INVALID_TITLE", "Document title is required"
                )
            changes = {**changes, "title": title}
        return await self._repository.update_document(document_id, changes)

    async def list_versions(self, document_id: UUID) -> list[DocumentVersion]:
        return await self._repository.list_versions(document_id)

    async def get_version_review_context(
        self, version_id: UUID
    ) -> DocumentVersionReviewContext | None:
        return await self._repository.get_version_review_context(version_id)

    async def create_version(self, value: NewDocumentVersion) -> DocumentVersion:
        document = await self._repository.get_document(value.document_id)
        if document is None:
            raise EnterpriseDocumentValidationError("DOCUMENT_NOT_FOUND", "Document not found")
        document.ensure_mutable()
        return await self._repository.create_version(value)

    async def review_version(
        self,
        version_id: UUID,
        *,
        decision: str,
        note: str | None,
        rejection_reason: str | None,
    ) -> DocumentVersion:
        if decision == ReviewDecision.REJECT and not rejection_reason:
            raise EnterpriseDocumentValidationError(
                "REJECTION_REASON_REQUIRED", "A rejection reason is required"
            )
        return await self._repository.review_version(
            version_id,
            decision=decision,
            note=note,
            rejection_reason=rejection_reason,
        )

    async def list_metadata_assertions(
        self,
        version_id: UUID,
        *,
        verification_status: str | None,
    ) -> list[DocumentMetadataAssertion]:
        normalized = verification_status.upper() if verification_status else None
        if normalized not in {None, "UNVERIFIED", "VERIFIED", "REJECTED"}:
            raise EnterpriseDocumentValidationError(
                "INVALID_METADATA_ASSERTION_STATUS",
                "Metadata assertion status is invalid",
            )
        return await self._repository.list_metadata_assertions(
            version_id,
            verification_status=normalized,
        )

    async def review_metadata_assertion(
        self,
        assertion_id: UUID,
        *,
        decision: str,
        rejection_reason: str | None,
    ) -> DocumentMetadataAssertion:
        normalized = decision.upper().strip()
        reason = rejection_reason.strip() if rejection_reason else None
        if normalized not in {"VERIFIED", "REJECTED"}:
            raise EnterpriseDocumentValidationError(
                "INVALID_METADATA_ASSERTION_DECISION",
                "Decision must be VERIFIED or REJECTED",
            )
        if normalized == "REJECTED" and not reason:
            raise EnterpriseDocumentValidationError(
                "REJECTION_REASON_REQUIRED",
                "A rejection reason is required",
            )
        return await self._repository.review_metadata_assertion(
            assertion_id,
            decision=normalized,
            rejection_reason=reason,
        )

    async def publish_version(self, version_id: UUID) -> DocumentVersion:
        return await self._repository.publish_version(version_id)

    async def archive_document(self, document_id: UUID, *, reason: str) -> KnowledgeDocument:
        normalized_reason = reason.strip()
        if not normalized_reason:
            raise EnterpriseDocumentValidationError(
                "ARCHIVE_REASON_REQUIRED", "An archive reason is required"
            )
        return await self._repository.archive_document(document_id, reason=normalized_reason)

    async def list_permissions(self, document_id: UUID) -> list[PermissionAssignment]:
        return await self._repository.list_permissions(document_id)

    async def grant_permission(
        self, document_id: UUID, subject_id: UUID, permission: str
    ) -> PermissionAssignment:
        return await self._repository.grant_permission(document_id, subject_id, permission)

    async def revoke_permission(self, document_id: UUID, subject_id: UUID, permission: str) -> None:
        await self._repository.revoke_permission(document_id, subject_id, permission)

    async def test_access(self, user_id: UUID, document_id: UUID, permission: str) -> bool:
        return await self._repository.test_access(user_id, document_id, permission)

    async def explain_access(
        self, user_id: UUID, document_id: UUID, permission: str
    ) -> AccessDecision:
        return await self._repository.explain_access(user_id, document_id, permission)

    async def list_processing_jobs(
        self,
        *,
        document_id: UUID | None,
        document_version_id: UUID | None,
        job_status: str | None,
        limit: int,
        offset: int,
    ) -> tuple[list[ProcessingJob], int]:
        return await self._repository.list_processing_jobs(
            document_id=document_id,
            document_version_id=document_version_id,
            job_status=job_status,
            limit=limit,
            offset=offset,
        )

    async def get_processing_job(self, job_id: UUID) -> ProcessingJob | None:
        return await self._repository.get_processing_job(job_id)

    async def get_processing_job_detail(self, job_id: UUID) -> ProcessingJobDetail | None:
        return await self._repository.get_processing_job_detail(job_id)

    async def retry_processing_job(self, job_id: UUID) -> ProcessingJob:
        return await self._repository.retry_processing_job(job_id)

    async def get_version_source(self, document_id: UUID, version_id: UUID) -> VersionSource | None:
        return await self._repository.get_version_source(document_id, version_id)


class EnterpriseSourceFileService:
    """Validate and store immutable source bytes before a version references them."""

    def __init__(
        self,
        repository: EnterpriseDocumentRepository,
        object_storage: DocumentObjectStorage,
    ) -> None:
        self._repository = repository
        self._object_storage = object_storage

    async def upload(self, owner_id: UUID, filename: str, content: bytes) -> SourceFile:
        source, object_path = await self._store_source(owner_id, filename, content)
        try:
            return await self._repository.create_source_file(source)
        except Exception:
            await self._cleanup_object(object_path)
            raise

    async def upload_initial_document(
        self,
        owner_id: UUID,
        filename: str,
        content: bytes,
        *,
        document: NewKnowledgeDocument,
        change_summary: str | None = None,
        effective_date: date | None = None,
    ) -> InitialDocumentUpload:
        title = document.title.strip()
        if not title:
            raise EnterpriseDocumentValidationError("INVALID_TITLE", "Document title is required")
        source, object_path = await self._store_source(owner_id, filename, content)
        try:
            return await self._repository.create_initial_document_upload(
                NewInitialDocumentUpload(
                    document=NewKnowledgeDocument(
                        title=title,
                        description=document.description,
                        document_type=document.document_type,
                        category=document.category,
                        metadata=document.metadata,
                    ),
                    source_file=source,
                    change_summary=change_summary,
                    effective_date=effective_date,
                )
            )
        except Exception:
            await self._cleanup_object(object_path)
            raise

    async def _store_source(
        self, owner_id: UUID, filename: str, content: bytes
    ) -> tuple[NewSourceFile, str]:
        try:
            validated = validate_document_file(filename, content)
        except DocumentFileValidationError as exc:
            raise EnterpriseDocumentValidationError(exc.code, exc.message) from exc

        source_file_id = uuid4()
        object_path = f"{owner_id}/{source_file_id}/{validated.storage_filename}"
        try:
            await self._object_storage.upload(
                ENTERPRISE_SOURCE_BUCKET,
                object_path,
                validated.content,
                validated.mime_type,
            )
        except ObjectStorageError as exc:
            raise EnterpriseDocumentRepositoryError("Source file storage is unavailable") from exc

        return (
            NewSourceFile(
                id=source_file_id,
                bucket_name=ENTERPRISE_SOURCE_BUCKET,
                object_path=object_path,
                original_file_name=validated.original_filename,
                mime_type=validated.mime_type,
                size_bytes=validated.size_bytes,
                sha256=validated.content_hash,
                created_by=owner_id,
            ),
            object_path,
        )

    async def _cleanup_object(self, object_path: str) -> None:
        try:
            await self._object_storage.delete(ENTERPRISE_SOURCE_BUCKET, object_path)
        except ObjectStorageError:
            LOGGER.warning(
                "Could not clean up orphaned Enterprise source object %s",
                object_path,
                exc_info=True,
            )
