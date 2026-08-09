"""End-to-end contract tests for nested document uploads."""

from datetime import UTC, datetime
from uuid import UUID

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api.dependencies.auth import get_current_user
from app.api.dependencies.services import get_document_service
from app.api.main import create_app
from app.api.routers.documents import upload_documents
from app.api.schemas.auth import CurrentUser
from app.bootstrap.settings import Settings
from app.documents.application.services import (
    DocumentPreview,
    DocumentPreviewNotFoundError,
    DocumentPreviewUnsupportedError,
    DocumentUploadError,
    UploadOutcome,
)
from app.documents.domain.models import Document

OWNER_ID = UUID("20000000-0000-0000-0000-000000000002")
NOTEBOOK_ID = UUID("10000000-0000-0000-0000-000000000001")
DOCUMENT_ID = UUID("30000000-0000-0000-0000-000000000003")
NOW = datetime(2026, 7, 27, tzinfo=UTC)


class FakeDocumentService:
    def __init__(
        self,
        notebook_exists: bool = True,
        list_empty: bool = False,
        document_exists: bool = True,
        preview_supported: bool = True,
        upload_is_duplicate: bool = False,
    ) -> None:
        self._notebook_exists = notebook_exists
        self._list_empty = list_empty
        self._document_exists = document_exists
        self._preview_supported = preview_supported
        self._upload_is_duplicate = upload_is_duplicate
        self.list_call: tuple[UUID, str | None, int, int] | None = None
        self.delete_call: tuple[UUID, UUID] | None = None
        self.preview_call: tuple[UUID, UUID] | None = None

    async def notebook_exists(self, notebook_id: UUID) -> bool:
        return self._notebook_exists and notebook_id == NOTEBOOK_ID

    async def list_documents(
        self,
        notebook_id: UUID,
        *,
        status: str | None,
        limit: int,
        offset: int,
    ) -> tuple[list[Document], int]:
        self.list_call = (notebook_id, status, limit, offset)
        if self._list_empty:
            return [], 0
        return [
            Document(
                id=DOCUMENT_ID,
                owner_id=OWNER_ID,
                notebook_id=notebook_id,
                original_filename="report.pdf",
                storage_bucket="documents",
                storage_object_path=(f"{OWNER_ID}/{notebook_id}/{DOCUMENT_ID}/report.pdf"),
                mime_type="application/pdf",
                size_bytes=16,
                content_hash="a" * 64,
                status="uploaded",
                error_message=None,
                is_active=True,
                created_at=NOW,
                updated_at=NOW,
            )
        ], 12

    async def upload_file(
        self,
        owner_id: UUID,
        notebook_id: UUID,
        filename: str,
        content: bytes,
    ) -> UploadOutcome:
        if filename.endswith(".exe"):
            raise DocumentUploadError(
                "UNSUPPORTED_FILE_TYPE",
                "Unsupported file type",
            )
        return UploadOutcome(
            document=Document(
                id=DOCUMENT_ID,
                owner_id=owner_id,
                notebook_id=notebook_id,
                original_filename=filename,
                storage_bucket="documents",
                storage_object_path=f"{owner_id}/{notebook_id}/{DOCUMENT_ID}/{filename}",
                mime_type="application/pdf",
                size_bytes=len(content),
                content_hash="a" * 64,
                status="processing",
                error_message=None,
                is_active=True,
                created_at=NOW,
                updated_at=NOW,
            ),
            is_duplicate=self._upload_is_duplicate,
        )

    async def get_document_preview(
        self,
        notebook_id: UUID,
        document_id: UUID,
    ) -> DocumentPreview:
        self.preview_call = (notebook_id, document_id)
        if not self._document_exists or document_id != DOCUMENT_ID:
            raise DocumentPreviewNotFoundError("Document not found")
        if not self._preview_supported:
            raise DocumentPreviewUnsupportedError("Document preview is not supported")
        return DocumentPreview(
            content=b"%PDF-1.7\npreview",
            mime_type="application/pdf",
            filename="Báo cáo attention.pdf",
        )

    async def delete_document(
        self,
        notebook_id: UUID,
        document_id: UUID,
    ) -> bool:
        self.delete_call = (notebook_id, document_id)
        return self._document_exists and document_id == DOCUMENT_ID


def make_settings() -> Settings:
    return Settings.model_validate(
        {
            "app_env": "test",
            "supabase_url": "https://example.supabase.co",
            "ingestion_worker_enabled": False,
        }
    )


def make_app(service: FakeDocumentService | None = None) -> FastAPI:
    app = create_app(make_settings())
    app.dependency_overrides[get_current_user] = lambda: CurrentUser(
        id=str(OWNER_ID),
        email="user@example.com",
        role="authenticated",
    )
    app.dependency_overrides[get_document_service] = lambda: service or FakeDocumentService()
    return app


def test_list_returns_filtered_paginated_documents() -> None:
    service = FakeDocumentService()
    with TestClient(make_app(service)) as client:
        response = client.get(
            f"/notebooks/{NOTEBOOK_ID}/documents",
            params={"status": "uploaded", "limit": 10, "offset": 5},
        )

    assert response.status_code == 200
    assert response.json()["total_count"] == 12
    assert response.json()["limit"] == 10
    assert response.json()["offset"] == 5
    assert response.json()["items"][0]["id"] == str(DOCUMENT_ID)
    assert response.json()["items"][0]["status"] == "uploaded"
    assert service.list_call == (NOTEBOOK_ID, "uploaded", 10, 5)


def test_list_returns_not_found_for_unowned_notebook() -> None:
    service = FakeDocumentService(notebook_exists=False)
    with TestClient(make_app(service)) as client:
        response = client.get(f"/notebooks/{NOTEBOOK_ID}/documents")

    assert response.status_code == 404
    assert response.json() == {"detail": "Notebook not found"}
    assert service.list_call is None


def test_list_returns_empty_page_for_notebook_without_documents() -> None:
    with TestClient(make_app(FakeDocumentService(list_empty=True))) as client:
        response = client.get(f"/notebooks/{NOTEBOOK_ID}/documents")

    assert response.status_code == 200
    assert response.json() == {
        "items": [],
        "total_count": 0,
        "limit": 50,
        "offset": 0,
    }


def test_list_rejects_invalid_pagination_and_status() -> None:
    with TestClient(make_app()) as client:
        response = client.get(
            f"/notebooks/{NOTEBOOK_ID}/documents",
            params={"status": "unknown", "limit": 0, "offset": -1},
        )

    assert response.status_code == 422


def test_upload_accepts_one_or_more_files_with_partial_success() -> None:
    with TestClient(make_app()) as client:
        response = client.post(
            f"/notebooks/{NOTEBOOK_ID}/documents",
            files=[
                ("files", ("report.pdf", b"%PDF-1.7\ncontent", "application/pdf")),
                ("files", ("malware.exe", b"MZ", "application/octet-stream")),
            ],
        )

    assert response.status_code == 200
    assert response.json()["total_count"] == 2
    assert response.json()["succeeded_count"] == 1
    assert response.json()["failed_count"] == 1
    assert response.json()["items"][0]["document"]["status"] == "processing"
    assert response.json()["items"][0]["duplicate"] is False
    assert response.json()["items"][1] == {
        "filename": "malware.exe",
        "document": None,
        "error_code": "UNSUPPORTED_FILE_TYPE",
        "error_message": "Unsupported file type",
        "duplicate": False,
    }


def test_upload_flags_a_deduplicated_item_without_marking_it_failed() -> None:
    with TestClient(make_app(FakeDocumentService(upload_is_duplicate=True))) as client:
        response = client.post(
            f"/notebooks/{NOTEBOOK_ID}/documents",
            files=[("files", ("report.pdf", b"%PDF-1.7\ncontent", "application/pdf"))],
        )

    assert response.status_code == 200
    assert response.json()["succeeded_count"] == 1
    assert response.json()["failed_count"] == 0
    assert response.json()["items"][0]["duplicate"] is True
    assert response.json()["items"][0]["error_code"] is None


def test_upload_does_not_misclassify_service_oserror_as_file_read_failure() -> None:
    class OSErrorDocumentService(FakeDocumentService):
        async def upload_file(
            self,
            owner_id: UUID,
            notebook_id: UUID,
            filename: str,
            content: bytes,
        ) -> Document:
            del owner_id, notebook_id, filename, content
            raise OSError("post-read transport failure")

    with TestClient(
        make_app(OSErrorDocumentService()),
        raise_server_exceptions=False,
    ) as client:
        response = client.post(
            f"/notebooks/{NOTEBOOK_ID}/documents",
            files=[("files", ("report.pdf", b"%PDF-1.7\ncontent", "application/pdf"))],
        )

    assert response.status_code == 500
    assert "Could not read uploaded file" not in response.text


@pytest.mark.anyio
async def test_upload_reports_file_read_failure_only_when_uploadfile_read_raises() -> None:
    class OSErrorUpload:
        filename = "report.pdf"

        def __init__(self) -> None:
            self.closed = False

        async def read(self, size: int) -> bytes:
            del size
            raise OSError("temporary upload file unavailable")

        async def close(self) -> None:
            self.closed = True

    upload = OSErrorUpload()
    response = await upload_documents(
        NOTEBOOK_ID,
        [upload],  # type: ignore[list-item]
        CurrentUser(
            id=str(OWNER_ID),
            email="user@example.com",
            role="authenticated",
        ),
        FakeDocumentService(),
    )

    assert response.failed_count == 1
    assert response.items[0].error_code == "FILE_READ_FAILED"
    assert response.items[0].error_message == "Could not read uploaded file"
    assert upload.closed is True


def test_upload_requires_at_least_one_file() -> None:
    with TestClient(make_app()) as client:
        response = client.post(f"/notebooks/{NOTEBOOK_ID}/documents")

    assert response.status_code == 422


def test_upload_rejects_more_than_twenty_files() -> None:
    files = [("files", (f"file-{index}.txt", b"content", "text/plain")) for index in range(21)]
    with TestClient(make_app()) as client:
        response = client.post(
            f"/notebooks/{NOTEBOOK_ID}/documents",
            files=files,
        )

    assert response.status_code == 422
    assert response.json()["detail"] == "At most 20 files may be uploaded at once"


def test_upload_returns_not_found_for_unowned_notebook() -> None:
    with TestClient(make_app(FakeDocumentService(notebook_exists=False))) as client:
        response = client.post(
            f"/notebooks/{NOTEBOOK_ID}/documents",
            files=[("files", ("notes.txt", b"notes", "text/plain"))],
        )

    assert response.status_code == 404
    assert response.json() == {"detail": "Notebook not found"}


def test_delete_returns_confirmation_json() -> None:
    service = FakeDocumentService()
    with TestClient(make_app(service)) as client:
        response = client.delete(f"/notebooks/{NOTEBOOK_ID}/documents/{DOCUMENT_ID}")

    assert response.status_code == 200
    assert response.json() == {
        "message": "Document archived successfully",
        "document_id": str(DOCUMENT_ID),
    }
    assert service.delete_call == (NOTEBOOK_ID, DOCUMENT_ID)


def test_preview_returns_authenticated_inline_pdf() -> None:
    service = FakeDocumentService()
    with TestClient(make_app(service)) as client:
        response = client.get(f"/notebooks/{NOTEBOOK_ID}/documents/{DOCUMENT_ID}/preview")

    assert response.status_code == 200
    assert response.content == b"%PDF-1.7\npreview"
    assert response.headers["content-type"] == "application/pdf"
    assert response.headers["cache-control"] == "private, no-store"
    assert response.headers["x-content-type-options"] == "nosniff"
    assert (
        "filename*=UTF-8''B%C3%A1o%20c%C3%A1o%20attention.pdf"
        in response.headers["content-disposition"]
    )
    assert service.preview_call == (NOTEBOOK_ID, DOCUMENT_ID)


def test_preview_returns_not_found_for_document_outside_notebook() -> None:
    service = FakeDocumentService(document_exists=False)
    with TestClient(make_app(service)) as client:
        response = client.get(f"/notebooks/{NOTEBOOK_ID}/documents/{DOCUMENT_ID}/preview")

    assert response.status_code == 404
    assert response.json() == {"detail": "Document not found"}


def test_preview_rejects_non_pdf_documents() -> None:
    service = FakeDocumentService(preview_supported=False)
    with TestClient(make_app(service)) as client:
        response = client.get(f"/notebooks/{NOTEBOOK_ID}/documents/{DOCUMENT_ID}/preview")

    assert response.status_code == 415
    assert response.json() == {"detail": "Preview is currently supported for PDF documents only"}


def test_preview_returns_not_found_for_unowned_notebook() -> None:
    service = FakeDocumentService(notebook_exists=False)
    with TestClient(make_app(service)) as client:
        response = client.get(f"/notebooks/{NOTEBOOK_ID}/documents/{DOCUMENT_ID}/preview")

    assert response.status_code == 404
    assert response.json() == {"detail": "Notebook not found"}
    assert service.preview_call is None


def test_delete_returns_not_found_for_document_outside_notebook() -> None:
    service = FakeDocumentService(document_exists=False)
    with TestClient(make_app(service)) as client:
        response = client.delete(f"/notebooks/{NOTEBOOK_ID}/documents/{DOCUMENT_ID}")

    assert response.status_code == 404
    assert response.json() == {"detail": "Document not found"}


def test_delete_returns_not_found_for_unowned_notebook() -> None:
    service = FakeDocumentService(notebook_exists=False)
    with TestClient(make_app(service)) as client:
        response = client.delete(f"/notebooks/{NOTEBOOK_ID}/documents/{DOCUMENT_ID}")

    assert response.status_code == 404
    assert response.json() == {"detail": "Notebook not found"}
    assert service.delete_call is None
