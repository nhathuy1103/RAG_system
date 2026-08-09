"""Unit tests for document validation and upload coordination."""

from dataclasses import replace
from datetime import UTC, datetime
from io import BytesIO
from uuid import UUID
from zipfile import ZipFile

import pytest

from app.documents.application.services import (
    DocumentPreviewNotFoundError,
    DocumentPreviewStorageError,
    DocumentPreviewUnsupportedError,
    DocumentService,
    DocumentUploadError,
)
from app.documents.domain.models import (
    DOCUMENT_STORAGE_BUCKET,
    MAX_DOCUMENT_SIZE_BYTES,
    Document,
    DocumentFileValidationError,
    sanitize_storage_filename,
    validate_document_file,
)
from app.documents.ports.repositories import (
    DocumentDuplicateError,
    NewDocument,
)
from app.documents.ports.storage import ObjectStorageError
from app.ingestion.domain.models import IngestionProfile
from app.ingestion.ports.repositories import IngestionRepositoryError
from app.notebooks.domain.models import Notebook

OWNER_ID = UUID("20000000-0000-0000-0000-000000000002")
NOTEBOOK_ID = UUID("10000000-0000-0000-0000-000000000001")
DOCUMENT_ID = UUID("30000000-0000-0000-0000-000000000003")
NOW = datetime(2026, 7, 27, tzinfo=UTC)
INGESTION_PROFILE = IngestionProfile(
    embedding_model="local-hash-embedding-v1",
    embedding_dimensions=32,
)


def office_file(folder: str) -> bytes:
    buffer = BytesIO()
    with ZipFile(buffer, "w") as archive:
        archive.writestr("[Content_Types].xml", "<Types />")
        archive.writestr(f"{folder}/document.xml", "<document />")
    return buffer.getvalue()


class FakeNotebookRepository:
    async def exists_owned(self, notebook_id: UUID) -> bool:
        return notebook_id == NOTEBOOK_ID

    async def list_owned(self) -> list[Notebook]:
        return []

    async def create(self, title: str, description: str = "") -> Notebook:
        raise NotImplementedError

    async def update(
        self,
        notebook_id: UUID,
        changes: dict[str, str],
    ) -> Notebook | None:
        raise NotImplementedError


class FakeDocumentRepository:
    def __init__(self) -> None:
        self.created: NewDocument | None = None
        self.status_updates: list[tuple[str, str | None]] = []
        self.is_active = True
        self.current_status = "ready"
        self.current_error: str | None = None

    async def get_by_id(
        self,
        document_id: UUID,
        notebook_id: UUID,
    ) -> Document | None:
        if (
            self.created is None
            or self.created.id != document_id
            or self.created.notebook_id != notebook_id
        ):
            return None
        return self._to_document(
            self.created,
            self.current_status,
            self.current_error,
        )

    async def find_by_content_hash(
        self,
        owner_id: UUID,
        notebook_id: UUID,
        content_hash: str,
    ) -> Document | None:
        if (
            self.created is None
            or not self.is_active
            or self.created.owner_id != owner_id
            or self.created.notebook_id != notebook_id
            or self.created.content_hash != content_hash
        ):
            return None
        return self._to_document(self.created, "ready", None)

    async def soft_delete(
        self,
        document_id: UUID,
        notebook_id: UUID,
    ) -> Document | None:
        if (
            self.created is None
            or self.created.id != document_id
            or self.created.notebook_id != notebook_id
            or not self.is_active
        ):
            return None
        self.is_active = False
        return self._to_document(self.created, "ready", None)

    async def list_by_notebook(
        self,
        notebook_id: UUID,
        *,
        status: str | None,
        limit: int,
        offset: int,
    ) -> tuple[list[Document], int]:
        del notebook_id, status, limit, offset
        return [], 0

    async def create_uploading(self, document: NewDocument) -> Document:
        self.created = document
        self.current_status = "uploading"
        self.current_error = None
        return self._to_document(document, "uploading", None)

    async def update_status(
        self,
        document_id: UUID,
        notebook_id: UUID,
        status: str,
        error_message: str | None,
    ) -> Document | None:
        assert self.created is not None
        assert document_id == self.created.id
        assert notebook_id == self.created.notebook_id
        self.status_updates.append((status, error_message))
        self.current_status = status
        self.current_error = error_message
        return self._to_document(self.created, status, error_message)

    def _to_document(
        self,
        document: NewDocument,
        status: str,
        error_message: str | None,
    ) -> Document:
        return Document(
            id=document.id,
            owner_id=document.owner_id,
            notebook_id=document.notebook_id,
            original_filename=document.original_filename,
            storage_bucket=document.storage_bucket,
            storage_object_path=document.storage_object_path,
            mime_type=document.mime_type,
            size_bytes=document.size_bytes,
            content_hash=document.content_hash,
            status=status,
            error_message=error_message,
            is_active=self.is_active,
            created_at=NOW,
            updated_at=NOW,
        )


class FakeObjectStorage:
    def __init__(
        self,
        fail_upload: bool = False,
        fail_delete: bool = False,
        fail_download: bool = False,
        download_content: bytes = b"%PDF-1.7\npreview",
    ) -> None:
        self.fail_upload = fail_upload
        self.fail_delete = fail_delete
        self.fail_download = fail_download
        self.download_content = download_content
        self.uploads: list[tuple[str, str, bytes, str]] = []
        self.deleted: list[tuple[str, str]] = []
        self.downloaded: list[tuple[str, str]] = []

    async def upload(
        self,
        bucket: str,
        object_path: str,
        content: bytes,
        mime_type: str,
    ) -> None:
        if self.fail_upload:
            raise ObjectStorageError("storage unavailable")
        self.uploads.append((bucket, object_path, content, mime_type))

    async def delete(self, bucket: str, object_path: str) -> None:
        if self.fail_delete:
            raise ObjectStorageError("storage unavailable")
        self.deleted.append((bucket, object_path))

    async def download(self, bucket: str, object_path: str) -> bytes:
        if self.fail_download:
            raise ObjectStorageError("storage unavailable")
        self.downloaded.append((bucket, object_path))
        return self.download_content


class FakeIngestionRepository:
    def __init__(
        self,
        documents: FakeDocumentRepository,
        *,
        fail_enqueue: bool = False,
    ) -> None:
        self.documents = documents
        self.fail_enqueue = fail_enqueue
        self.enqueued: list[tuple[UUID, UUID, IngestionProfile]] = []

    async def enqueue(
        self,
        document_id: UUID,
        notebook_id: UUID,
        profile: IngestionProfile,
    ) -> Document:
        if self.fail_enqueue:
            raise IngestionRepositoryError("database unavailable")
        self.enqueued.append((document_id, notebook_id, profile))
        document = await self.documents.update_status(
            document_id,
            notebook_id,
            "processing",
            None,
        )
        assert document is not None
        return document


def existing_document_metadata() -> NewDocument:
    return NewDocument(
        id=DOCUMENT_ID,
        owner_id=OWNER_ID,
        notebook_id=NOTEBOOK_ID,
        original_filename="report.pdf",
        storage_bucket=DOCUMENT_STORAGE_BUCKET,
        storage_object_path=(f"{OWNER_ID}/{NOTEBOOK_ID}/{DOCUMENT_ID}/report.pdf"),
        mime_type="application/pdf",
        size_bytes=16,
        content_hash="a" * 64,
    )


@pytest.mark.anyio
async def test_service_returns_owned_pdf_preview() -> None:
    document_repository = FakeDocumentRepository()
    document_repository.created = existing_document_metadata()
    object_storage = FakeObjectStorage()
    service = DocumentService(
        FakeNotebookRepository(),
        document_repository,
        object_storage,
        FakeIngestionRepository(document_repository),
        INGESTION_PROFILE,
    )

    preview = await service.get_document_preview(NOTEBOOK_ID, DOCUMENT_ID)

    assert preview.content == b"%PDF-1.7\npreview"
    assert preview.mime_type == "application/pdf"
    assert preview.filename == "report.pdf"
    assert object_storage.downloaded == [
        (
            DOCUMENT_STORAGE_BUCKET,
            f"{OWNER_ID}/{NOTEBOOK_ID}/{DOCUMENT_ID}/report.pdf",
        )
    ]


@pytest.mark.anyio
async def test_service_rejects_preview_outside_owned_notebook() -> None:
    document_repository = FakeDocumentRepository()
    service = DocumentService(
        FakeNotebookRepository(),
        document_repository,
        FakeObjectStorage(),
        FakeIngestionRepository(document_repository),
        INGESTION_PROFILE,
    )

    with pytest.raises(DocumentPreviewNotFoundError):
        await service.get_document_preview(NOTEBOOK_ID, DOCUMENT_ID)


@pytest.mark.anyio
async def test_service_rejects_non_pdf_preview() -> None:
    document_repository = FakeDocumentRepository()
    document_repository.created = replace(
        existing_document_metadata(),
        original_filename="notes.txt",
        storage_object_path=f"{OWNER_ID}/{NOTEBOOK_ID}/{DOCUMENT_ID}/notes.txt",
        mime_type="text/plain",
    )
    service = DocumentService(
        FakeNotebookRepository(),
        document_repository,
        FakeObjectStorage(),
        FakeIngestionRepository(document_repository),
        INGESTION_PROFILE,
    )

    with pytest.raises(DocumentPreviewUnsupportedError):
        await service.get_document_preview(NOTEBOOK_ID, DOCUMENT_ID)


@pytest.mark.anyio
async def test_service_wraps_preview_storage_failure() -> None:
    document_repository = FakeDocumentRepository()
    document_repository.created = existing_document_metadata()
    service = DocumentService(
        FakeNotebookRepository(),
        document_repository,
        FakeObjectStorage(fail_download=True),
        FakeIngestionRepository(document_repository),
        INGESTION_PROFILE,
    )

    with pytest.raises(DocumentPreviewStorageError):
        await service.get_document_preview(NOTEBOOK_ID, DOCUMENT_ID)


@pytest.mark.parametrize(
    ("filename", "content", "expected_mime"),
    [
        ("report.pdf", b"%PDF-1.7\ncontent", "application/pdf"),
        (
            "report.docx",
            office_file("word"),
            "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        ),
        (
            "slides.pptx",
            office_file("ppt"),
            "application/vnd.openxmlformats-officedocument.presentationml.presentation",
        ),
        (
            "data.xlsx",
            office_file("xl"),
            "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        ),
        ("data.csv", b"name,value\nA,1", "text/csv"),
        ("notes.md", b"# Notes", "text/markdown"),
        ("page.html", b"<h1>Page</h1>", "text/html"),
        ("notes.txt", b"Hello", "text/plain"),
    ],
)
def test_validate_document_file_types(
    filename: str,
    content: bytes,
    expected_mime: str,
) -> None:
    validated = validate_document_file(filename, content)

    assert validated.mime_type == expected_mime
    assert validated.size_bytes == len(content)
    assert len(validated.content_hash) == 64


def test_sanitize_storage_filename_preserves_unicode_and_extension() -> None:
    assert sanitize_storage_filename("../../Báo cáo Q3 (bản cuối).PDF") == "Báo_cáo_Q3_bản_cuối.pdf"
    assert sanitize_storage_filename("hợp đồng<script>.DOCX") == "hợp_đồng_script.docx"


@pytest.mark.parametrize(
    ("filename", "content", "error_code"),
    [
        ("empty.txt", b"", "EMPTY_FILE"),
        ("malware.exe", b"MZ", "UNSUPPORTED_FILE_TYPE"),
        ("fake.pdf", b"not a PDF", "INVALID_FILE_CONTENT"),
        ("fake.docx", b"not a ZIP", "INVALID_FILE_CONTENT"),
        ("binary.txt", b"\xff\xfe\xfa", "INVALID_FILE_CONTENT"),
    ],
)
def test_validate_document_file_rejects_invalid_content(
    filename: str,
    content: bytes,
    error_code: str,
) -> None:
    with pytest.raises(DocumentFileValidationError) as exc_info:
        validate_document_file(filename, content)

    assert exc_info.value.code == error_code


def test_validate_document_file_rejects_oversized_content() -> None:
    assert MAX_DOCUMENT_SIZE_BYTES == 10_485_760

    with pytest.raises(DocumentFileValidationError) as exc_info:
        validate_document_file(
            "large.txt",
            b"x" * (MAX_DOCUMENT_SIZE_BYTES + 1),
        )

    assert exc_info.value.code == "FILE_TOO_LARGE"


@pytest.mark.anyio
async def test_service_persists_uploads_and_finalizes_metadata() -> None:
    document_repository = FakeDocumentRepository()
    storage = FakeObjectStorage()
    service = DocumentService(
        FakeNotebookRepository(),
        document_repository,
        storage,
        FakeIngestionRepository(document_repository),
        INGESTION_PROFILE,
    )

    outcome = await service.upload_file(
        OWNER_ID,
        NOTEBOOK_ID,
        "  Báo cáo (cuối).PDF  ",
        b"%PDF-1.7\ncontent",
    )

    assert outcome.is_duplicate is False
    assert outcome.document.status == "processing"
    assert outcome.document.error_message is None
    assert document_repository.created is not None
    assert document_repository.created.owner_id == OWNER_ID
    assert document_repository.created.notebook_id == NOTEBOOK_ID
    assert document_repository.created.original_filename == "  Báo cáo (cuối).PDF  "
    assert document_repository.created.storage_bucket == DOCUMENT_STORAGE_BUCKET
    assert document_repository.created.storage_object_path.endswith("/Báo_cáo_cuối.pdf")
    assert document_repository.status_updates == [("processing", None)]
    assert storage.uploads[0][2] == b"%PDF-1.7\ncontent"


@pytest.mark.anyio
async def test_service_skips_upload_when_exact_hash_duplicate_exists() -> None:
    content = b"%PDF-1.7\ncontent"
    existing = replace(
        existing_document_metadata(),
        content_hash=validate_document_file("report.pdf", content).content_hash,
    )
    document_repository = FakeDocumentRepository()
    document_repository.created = existing
    storage = FakeObjectStorage()
    service = DocumentService(
        FakeNotebookRepository(),
        document_repository,
        storage,
        FakeIngestionRepository(document_repository),
        INGESTION_PROFILE,
    )

    outcome = await service.upload_file(
        OWNER_ID,
        NOTEBOOK_ID,
        "report (2).pdf",
        content,
    )

    assert outcome.is_duplicate is True
    assert outcome.document.id == existing.id
    assert storage.uploads == []
    assert document_repository.status_updates == []


@pytest.mark.anyio
async def test_service_resolves_concurrent_exact_upload_from_unique_constraint() -> None:
    content = b"%PDF-1.7\ncontent"

    class RacingDocumentRepository(FakeDocumentRepository):
        def __init__(self) -> None:
            super().__init__()
            self.lookup_count = 0

        async def find_by_content_hash(
            self,
            owner_id: UUID,
            notebook_id: UUID,
            content_hash: str,
        ) -> Document | None:
            self.lookup_count += 1
            if self.lookup_count == 1:
                return None
            return await super().find_by_content_hash(
                owner_id,
                notebook_id,
                content_hash,
            )

        async def create_uploading(self, document: NewDocument) -> Document:
            self.created = replace(
                document,
                id=DOCUMENT_ID,
                storage_object_path=(f"{OWNER_ID}/{NOTEBOOK_ID}/{DOCUMENT_ID}/report.pdf"),
            )
            raise DocumentDuplicateError("concurrent insert won")

    document_repository = RacingDocumentRepository()
    storage = FakeObjectStorage()
    service = DocumentService(
        FakeNotebookRepository(),
        document_repository,
        storage,
        FakeIngestionRepository(document_repository),
        INGESTION_PROFILE,
    )

    outcome = await service.upload_file(
        OWNER_ID,
        NOTEBOOK_ID,
        "report (2).pdf",
        content,
    )

    assert outcome.is_duplicate is True
    assert outcome.document.id == DOCUMENT_ID
    assert document_repository.lookup_count == 2
    assert storage.uploads == []


@pytest.mark.anyio
async def test_service_marks_metadata_failed_when_storage_upload_fails() -> None:
    document_repository = FakeDocumentRepository()
    service = DocumentService(
        FakeNotebookRepository(),
        document_repository,
        FakeObjectStorage(fail_upload=True),
        FakeIngestionRepository(document_repository),
        INGESTION_PROFILE,
    )

    with pytest.raises(DocumentUploadError) as exc_info:
        await service.upload_file(
            OWNER_ID,
            NOTEBOOK_ID,
            "notes.txt",
            b"notes",
        )

    assert exc_info.value.code == "STORAGE_UPLOAD_FAILED"
    assert document_repository.status_updates == [("failed", "Object storage upload failed")]


@pytest.mark.anyio
async def test_service_marks_metadata_failed_when_storage_raises_oserror() -> None:
    class OSErrorStorage(FakeObjectStorage):
        async def upload(
            self,
            bucket: str,
            object_path: str,
            content: bytes,
            mime_type: str,
        ) -> None:
            del bucket, object_path, content, mime_type
            raise OSError("connection reset")

    document_repository = FakeDocumentRepository()
    service = DocumentService(
        FakeNotebookRepository(),
        document_repository,
        OSErrorStorage(),
        FakeIngestionRepository(document_repository),
        INGESTION_PROFILE,
    )

    with pytest.raises(DocumentUploadError) as exc_info:
        await service.upload_file(
            OWNER_ID,
            NOTEBOOK_ID,
            "notes.txt",
            b"notes",
        )

    assert exc_info.value.code == "STORAGE_UPLOAD_FAILED"
    assert document_repository.status_updates == [("failed", "Object storage upload failed")]


@pytest.mark.anyio
async def test_service_deletes_object_when_ingestion_enqueue_fails() -> None:
    document_repository = FakeDocumentRepository()
    storage = FakeObjectStorage()
    service = DocumentService(
        FakeNotebookRepository(),
        document_repository,
        storage,
        FakeIngestionRepository(document_repository, fail_enqueue=True),
        INGESTION_PROFILE,
    )

    with pytest.raises(DocumentUploadError) as exc_info:
        await service.upload_file(
            OWNER_ID,
            NOTEBOOK_ID,
            "notes.txt",
            b"notes",
        )

    assert exc_info.value.code == "INGESTION_ENQUEUE_FAILED"
    assert document_repository.created is not None
    assert storage.deleted == [
        (
            DOCUMENT_STORAGE_BUCKET,
            document_repository.created.storage_object_path,
        )
    ]
    assert document_repository.status_updates == [
        ("failed", "Could not enqueue document ingestion"),
    ]


@pytest.mark.anyio
async def test_service_retries_ambiguous_enqueue_without_deleting_committed_upload() -> None:
    class CommitThenDropIngestionRepository(FakeIngestionRepository):
        def __init__(self, documents: FakeDocumentRepository) -> None:
            super().__init__(documents)
            self.calls = 0

        async def enqueue(
            self,
            document_id: UUID,
            notebook_id: UUID,
            profile: IngestionProfile,
        ) -> Document:
            self.calls += 1
            document = await self.documents.update_status(
                document_id,
                notebook_id,
                "processing",
                None,
            )
            assert document is not None
            if self.calls == 1:
                raise IngestionRepositoryError("response lost after commit")
            return document

    document_repository = FakeDocumentRepository()
    storage = FakeObjectStorage()
    ingestion = CommitThenDropIngestionRepository(document_repository)
    service = DocumentService(
        FakeNotebookRepository(),
        document_repository,
        storage,
        ingestion,
        INGESTION_PROFILE,
    )

    outcome = await service.upload_file(
        OWNER_ID,
        NOTEBOOK_ID,
        "notes.txt",
        b"notes",
    )

    assert ingestion.calls == 2
    assert outcome.document.status == "processing"
    assert storage.deleted == []
    assert ("failed", "Could not enqueue document ingestion") not in (
        document_repository.status_updates
    )


@pytest.mark.anyio
async def test_service_marks_failed_when_ingestion_enqueue_raises_oserror() -> None:
    class OSErrorIngestionRepository(FakeIngestionRepository):
        async def enqueue(
            self,
            document_id: UUID,
            notebook_id: UUID,
            profile: IngestionProfile,
        ) -> Document:
            del document_id, notebook_id, profile
            raise OSError("connection reset")

    document_repository = FakeDocumentRepository()
    storage = FakeObjectStorage()
    service = DocumentService(
        FakeNotebookRepository(),
        document_repository,
        storage,
        OSErrorIngestionRepository(document_repository),
        INGESTION_PROFILE,
    )

    with pytest.raises(DocumentUploadError) as exc_info:
        await service.upload_file(
            OWNER_ID,
            NOTEBOOK_ID,
            "notes.txt",
            b"notes",
        )

    assert exc_info.value.code == "INGESTION_ENQUEUE_FAILED"
    assert document_repository.created is not None
    assert storage.deleted == [
        (
            DOCUMENT_STORAGE_BUCKET,
            document_repository.created.storage_object_path,
        )
    ]
    assert document_repository.status_updates == [
        ("failed", "Could not enqueue document ingestion"),
    ]


@pytest.mark.anyio
async def test_service_soft_deletes_document() -> None:
    document_repository = FakeDocumentRepository()
    document_repository.created = existing_document_metadata()
    storage = FakeObjectStorage()
    service = DocumentService(
        FakeNotebookRepository(),
        document_repository,
        storage,
        FakeIngestionRepository(document_repository),
        INGESTION_PROFILE,
    )

    deleted = await service.delete_document(NOTEBOOK_ID, DOCUMENT_ID)

    assert deleted is True
    assert document_repository.is_active is False
    # True soft delete: storage object is left untouched.
    assert storage.deleted == []


@pytest.mark.anyio
async def test_service_returns_false_when_document_is_not_in_notebook() -> None:
    document_repository = FakeDocumentRepository()
    service = DocumentService(
        FakeNotebookRepository(),
        document_repository,
        FakeObjectStorage(),
        FakeIngestionRepository(document_repository),
        INGESTION_PROFILE,
    )

    deleted = await service.delete_document(NOTEBOOK_ID, DOCUMENT_ID)

    assert deleted is False


@pytest.mark.anyio
async def test_service_returns_false_when_document_already_archived() -> None:
    document_repository = FakeDocumentRepository()
    document_repository.created = existing_document_metadata()
    document_repository.is_active = False
    service = DocumentService(
        FakeNotebookRepository(),
        document_repository,
        FakeObjectStorage(),
        FakeIngestionRepository(document_repository),
        INGESTION_PROFILE,
    )

    deleted = await service.delete_document(NOTEBOOK_ID, DOCUMENT_ID)

    assert deleted is False
