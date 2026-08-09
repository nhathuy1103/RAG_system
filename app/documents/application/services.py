"""Document upload application services."""

import asyncio
import logging
from dataclasses import dataclass
from uuid import UUID, uuid4

from app.documents.domain.models import (
    DOCUMENT_STORAGE_BUCKET,
    Document,
    DocumentFileValidationError,
    validate_document_file,
)
from app.documents.ports.repositories import (
    DocumentDuplicateError,
    DocumentRepository,
    DocumentRepositoryError,
    NewDocument,
)
from app.documents.ports.storage import (
    DocumentObjectStorage,
    ObjectStorageError,
)
from app.ingestion.domain.models import IngestionProfile
from app.ingestion.ports.repositories import (
    IngestionRepository,
)
from app.notebooks.ports.repositories import NotebookRepository

LOGGER = logging.getLogger(__name__)


class DocumentUploadError(RuntimeError):
    """A safe file-level upload failure returned to API clients."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


class DocumentPreviewError(RuntimeError):
    """Base error for safe document preview failures."""


class DocumentPreviewNotFoundError(DocumentPreviewError):
    """Raised when a preview target is outside the owned notebook."""


class DocumentPreviewUnsupportedError(DocumentPreviewError):
    """Raised when the original file has no supported preview renderer."""


class DocumentPreviewStorageError(DocumentPreviewError):
    """Raised when preview bytes cannot be downloaded."""


@dataclass(frozen=True, slots=True)
class DocumentPreview:
    """Authenticated original-file preview returned to the API layer."""

    content: bytes
    mime_type: str
    filename: str


@dataclass(frozen=True, slots=True)
class UploadOutcome:
    """Result of one ``upload_file`` call — the API layer needs ``is_duplicate``
    to tell the caller apart from a genuinely new upload (Layer 1 exact-hash
    dedup, duplicate_conflict_SPEC.html)."""

    document: Document
    is_duplicate: bool = False


class DocumentService:
    """Coordinate document metadata and object storage operations."""

    def __init__(
        self,
        notebook_repository: NotebookRepository,
        document_repository: DocumentRepository,
        object_storage: DocumentObjectStorage,
        ingestion_repository: IngestionRepository,
        ingestion_profile: IngestionProfile,
    ) -> None:
        self._notebook_repository = notebook_repository
        self._document_repository = document_repository
        self._object_storage = object_storage
        self._ingestion_repository = ingestion_repository
        self._ingestion_profile = ingestion_profile

    async def notebook_exists(self, notebook_id: UUID) -> bool:
        return await self._notebook_repository.exists_owned(notebook_id)

    async def list_documents(
        self,
        notebook_id: UUID,
        *,
        status: str | None,
        limit: int,
        offset: int,
    ) -> tuple[list[Document], int]:
        return await self._document_repository.list_by_notebook(
            notebook_id,
            status=status,
            limit=limit,
            offset=offset,
        )

    async def get_document_preview(
        self,
        notebook_id: UUID,
        document_id: UUID,
    ) -> DocumentPreview:
        document = await self._document_repository.get_by_id(
            document_id,
            notebook_id,
        )
        if document is None:
            raise DocumentPreviewNotFoundError("Document not found")
        if document.mime_type != "application/pdf":
            raise DocumentPreviewUnsupportedError("Document preview is not supported")

        try:
            content = await self._object_storage.download(
                document.storage_bucket,
                document.storage_object_path,
            )
        except ObjectStorageError as exc:
            raise DocumentPreviewStorageError("Could not load document preview") from exc

        return DocumentPreview(
            content=content,
            mime_type=document.mime_type,
            filename=document.original_filename,
        )

    async def delete_document(
        self,
        notebook_id: UUID,
        document_id: UUID,
    ) -> bool:
        """Soft-delete: archive the document, keep storage/vectors/row intact."""
        document = await self._document_repository.soft_delete(document_id, notebook_id)
        return document is not None

    async def upload_file(
        self,
        owner_id: UUID,
        notebook_id: UUID,
        filename: str,
        content: bytes,
    ) -> UploadOutcome:
        try:
            validated_file = validate_document_file(filename, content)
        except DocumentFileValidationError as exc:
            raise DocumentUploadError(exc.code, exc.message) from exc

        try:
            duplicate = await self._document_repository.find_by_content_hash(
                owner_id,
                notebook_id,
                validated_file.content_hash,
            )
        except DocumentRepositoryError as exc:
            raise DocumentUploadError(
                "DOCUMENT_METADATA_FAILED",
                "Could not check existing document metadata",
            ) from exc
        if duplicate is not None:
            # Layer 1 (exact-hash dedup): byte-identical re-upload, skip and
            # hand back the existing document instead of re-embedding it.
            return UploadOutcome(document=duplicate, is_duplicate=True)

        document_id = uuid4()
        object_path = f"{owner_id}/{notebook_id}/{document_id}/{validated_file.storage_filename}"
        new_document = NewDocument(
            id=document_id,
            owner_id=owner_id,
            notebook_id=notebook_id,
            original_filename=validated_file.original_filename,
            storage_bucket=DOCUMENT_STORAGE_BUCKET,
            storage_object_path=object_path,
            mime_type=validated_file.mime_type,
            size_bytes=validated_file.size_bytes,
            content_hash=validated_file.content_hash,
        )

        try:
            await self._document_repository.create_uploading(new_document)
        except DocumentDuplicateError as duplicate_exc:
            # The pre-check above is intentionally not trusted for correctness:
            # a concurrent request may have inserted the same content first.
            try:
                duplicate = await self._document_repository.find_by_content_hash(
                    owner_id,
                    notebook_id,
                    validated_file.content_hash,
                )
            except DocumentRepositoryError as lookup_exc:
                raise DocumentUploadError(
                    "DOCUMENT_METADATA_FAILED",
                    "Could not load the concurrently uploaded document",
                ) from lookup_exc
            if duplicate is not None:
                return UploadOutcome(document=duplicate, is_duplicate=True)
            raise DocumentUploadError(
                "DOCUMENT_METADATA_CONFLICT",
                "A concurrent document upload could not be resolved",
            ) from duplicate_exc
        except DocumentRepositoryError as exc:
            raise DocumentUploadError(
                "DOCUMENT_METADATA_FAILED",
                "Could not create document metadata",
            ) from exc

        try:
            await self._object_storage.upload(
                DOCUMENT_STORAGE_BUCKET,
                object_path,
                validated_file.content,
                validated_file.mime_type,
            )
        except asyncio.CancelledError:
            await self._mark_failed(
                document_id,
                notebook_id,
                "Document upload was cancelled",
            )
            await self._delete_uploaded_object(object_path)
            raise
        except Exception as exc:
            LOGGER.exception(
                "Object storage upload failed for document %s",
                document_id,
            )
            await self._mark_failed(
                document_id,
                notebook_id,
                "Object storage upload failed",
            )
            await self._delete_uploaded_object(object_path)
            raise DocumentUploadError(
                "STORAGE_UPLOAD_FAILED",
                "Could not upload file to object storage",
            ) from exc

        try:
            processing_document = await self._ingestion_repository.enqueue(
                document_id,
                notebook_id,
                self._ingestion_profile,
            )
        except asyncio.CancelledError:
            committed_document = await asyncio.shield(
                self._reconcile_enqueued_document(document_id, notebook_id)
            )
            if committed_document is None:
                await self._mark_failed(
                    document_id,
                    notebook_id,
                    "Document ingestion enqueue was cancelled",
                )
                await self._delete_uploaded_object(object_path)
            raise
        except Exception as exc:
            LOGGER.exception(
                "Ingestion enqueue failed for document %s",
                document_id,
            )
            recovered_document: Document | None
            try:
                # The first RPC may have committed even if its response was
                # lost. The database RPC is idempotent for the same profile.
                recovered_document = await self._ingestion_repository.enqueue(
                    document_id,
                    notebook_id,
                    self._ingestion_profile,
                )
            except Exception:
                recovered_document = await self._reconcile_enqueued_document(
                    document_id,
                    notebook_id,
                )
            if recovered_document is not None:
                LOGGER.warning(
                    "Recovered ambiguous enqueue outcome for document %s",
                    document_id,
                )
                return UploadOutcome(document=recovered_document)
            await self._mark_failed(
                document_id,
                notebook_id,
                "Could not enqueue document ingestion",
            )
            await self._delete_uploaded_object(object_path)
            raise DocumentUploadError(
                "INGESTION_ENQUEUE_FAILED",
                "Could not enqueue document for processing",
            ) from exc

        return UploadOutcome(document=processing_document)

    async def _reconcile_enqueued_document(
        self,
        document_id: UUID,
        notebook_id: UUID,
    ) -> Document | None:
        """Resolve a commit/response race before deleting uploaded content."""
        try:
            document = await self._document_repository.get_by_id(
                document_id,
                notebook_id,
            )
        except DocumentRepositoryError:
            LOGGER.exception(
                "Could not reconcile enqueue state for document %s",
                document_id,
            )
            return None
        if document is not None and document.status in {"processing", "ready"}:
            return document
        return None

    async def _mark_failed(
        self,
        document_id: UUID,
        notebook_id: UUID,
        error_message: str,
    ) -> None:
        try:
            document = await self._document_repository.update_status(
                document_id,
                notebook_id,
                "failed",
                error_message,
            )
        except DocumentRepositoryError:
            LOGGER.exception(
                "Could not mark document %s as failed",
                document_id,
            )
            return
        if document is None:
            LOGGER.error(
                "Could not mark document %s as failed because it no longer exists",
                document_id,
            )

    async def _delete_uploaded_object(self, object_path: str) -> None:
        try:
            await self._object_storage.delete(DOCUMENT_STORAGE_BUCKET, object_path)
        except ObjectStorageError:
            LOGGER.exception("Could not clean up uploaded document object")
