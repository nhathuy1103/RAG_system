from __future__ import annotations

from uuid import UUID

import pytest

from app.documents.application.enterprise_services import (
    ENTERPRISE_SOURCE_BUCKET,
    EnterpriseDocumentValidationError,
    EnterpriseSourceFileService,
)
from app.documents.domain.enterprise_models import SourceFile
from app.documents.ports.enterprise_repositories import (
    EnterpriseDocumentRepositoryError,
    NewInitialDocumentUpload,
    NewKnowledgeDocument,
    NewSourceFile,
)

OWNER_ID = UUID("10000000-0000-0000-0000-000000000001")


class RepositoryStub:
    def __init__(self, *, fail: bool = False, fail_initial: bool = False) -> None:
        self.fail = fail
        self.fail_initial = fail_initial
        self.value: NewSourceFile | None = None
        self.initial_value: NewInitialDocumentUpload | None = None
        self.initial_result = object()

    async def create_source_file(self, value: NewSourceFile) -> SourceFile:
        self.value = value
        if self.fail:
            raise EnterpriseDocumentRepositoryError("metadata failed")
        return SourceFile(
            id=value.id,
            bucket_name=value.bucket_name,
            object_path=value.object_path,
            original_file_name=value.original_file_name,
            mime_type=value.mime_type,
            size_bytes=value.size_bytes,
            sha256=value.sha256,
            created_by=value.created_by,
        )

    async def create_initial_document_upload(self, value: NewInitialDocumentUpload) -> object:
        self.initial_value = value
        if self.fail_initial:
            raise EnterpriseDocumentRepositoryError("atomic registration failed")
        return self.initial_result


class StorageStub:
    def __init__(self) -> None:
        self.uploads: list[tuple[str, str, bytes, str]] = []
        self.deletes: list[tuple[str, str]] = []

    async def upload(self, bucket: str, object_path: str, content: bytes, mime_type: str) -> None:
        self.uploads.append((bucket, object_path, content, mime_type))

    async def delete(self, bucket: str, object_path: str) -> None:
        self.deletes.append((bucket, object_path))

    async def download(self, bucket: str, object_path: str) -> bytes:
        raise AssertionError("download is not used")


@pytest.mark.anyio
async def test_source_upload_validates_bytes_and_persists_immutable_metadata() -> None:
    repository = RepositoryStub()
    storage = StorageStub()
    service = EnterpriseSourceFileService(
        repository,  # type: ignore[arg-type]
        storage,
    )

    source = await service.upload(OWNER_ID, "../Policy 2026.pdf", b"%PDF-1.7\ncontent")

    assert source.bucket_name == ENTERPRISE_SOURCE_BUCKET
    assert source.original_file_name == "Policy 2026.pdf"
    assert source.object_path.startswith(f"{OWNER_ID}/{source.id}/")
    assert source.object_path.endswith("Policy_2026.pdf")
    assert len(source.sha256 or "") == 64
    assert storage.uploads[0][0] == ENTERPRISE_SOURCE_BUCKET
    assert storage.deletes == []


@pytest.mark.anyio
async def test_metadata_failure_compensates_uploaded_object() -> None:
    repository = RepositoryStub(fail=True)
    storage = StorageStub()
    service = EnterpriseSourceFileService(
        repository,  # type: ignore[arg-type]
        storage,
    )

    with pytest.raises(EnterpriseDocumentRepositoryError, match="metadata failed"):
        await service.upload(OWNER_ID, "policy.pdf", b"%PDF-1.7\ncontent")

    assert len(storage.uploads) == 1
    assert storage.deletes == [storage.uploads[0][:2]]


@pytest.mark.anyio
async def test_invalid_source_never_reaches_storage_or_metadata() -> None:
    repository = RepositoryStub()
    storage = StorageStub()
    service = EnterpriseSourceFileService(
        repository,  # type: ignore[arg-type]
        storage,
    )

    with pytest.raises(EnterpriseDocumentValidationError) as captured:
        await service.upload(OWNER_ID, "policy.pdf", b"not-a-pdf")

    assert captured.value.code == "INVALID_FILE_CONTENT"
    assert storage.uploads == []
    assert repository.value is None


@pytest.mark.anyio
async def test_initial_upload_registers_document_source_version_and_job_atomically() -> None:
    repository = RepositoryStub()
    storage = StorageStub()
    service = EnterpriseSourceFileService(
        repository,  # type: ignore[arg-type]
        storage,
    )

    result = await service.upload_initial_document(
        OWNER_ID,
        "policy.pdf",
        b"%PDF-1.7\ncontent",
        document=NewKnowledgeDocument(title="  Policy  ", category="HR"),
        change_summary="Initial publication candidate",
    )

    assert result is repository.initial_result
    assert repository.initial_value is not None
    assert repository.initial_value.document.title == "Policy"
    assert repository.initial_value.source_file.sha256
    assert repository.initial_value.change_summary == "Initial publication candidate"
    assert storage.deletes == []


@pytest.mark.anyio
async def test_initial_upload_rolls_back_storage_object_when_atomic_rpc_fails() -> None:
    repository = RepositoryStub(fail_initial=True)
    storage = StorageStub()
    service = EnterpriseSourceFileService(
        repository,  # type: ignore[arg-type]
        storage,
    )

    with pytest.raises(EnterpriseDocumentRepositoryError, match="atomic registration failed"):
        await service.upload_initial_document(
            OWNER_ID,
            "policy.pdf",
            b"%PDF-1.7\ncontent",
            document=NewKnowledgeDocument(title="Policy"),
        )

    assert len(storage.uploads) == 1
    assert storage.deletes == [storage.uploads[0][:2]]
