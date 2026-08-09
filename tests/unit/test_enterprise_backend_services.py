from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID

import pytest

from app.documents.application.enterprise_services import (
    EnterpriseDocumentService,
    EnterpriseDocumentValidationError,
)
from app.documents.domain.enterprise_models import KnowledgeDocument
from app.documents.ports.enterprise_repositories import NewDocumentVersion
from app.governance.application.services import GovernanceService, GovernanceValidationError
from app.identity.application.services import IdentityService
from app.identity.ports.repositories import OrganizationInput

DOCUMENT_ID = UUID("10000000-0000-0000-0000-000000000001")
SOURCE_ID = UUID("20000000-0000-0000-0000-000000000002")


def _document(status: str = "DRAFT") -> KnowledgeDocument:
    return KnowledgeDocument(
        id=DOCUMENT_ID,
        title="Policy",
        description=None,
        document_type=None,
        category=None,
        document_number=None,
        issued_date=None,
        effective_date=None,
        expiration_date=None,
        source=None,
        owner_department_id=None,
        status=status,
        current_version_id=None,
        created_at=datetime.now(UTC),
    )


class DocumentRepositoryStub:
    def __init__(self, document: KnowledgeDocument | None) -> None:
        self.document = document
        self.created_version: NewDocumentVersion | None = None

    async def get_document(self, _document_id: UUID) -> KnowledgeDocument | None:
        return self.document

    async def create_version(self, value: NewDocumentVersion) -> object:
        self.created_version = value
        return object()


class IdentityRepositoryStub:
    def __init__(self) -> None:
        self.value: OrganizationInput | None = None

    async def create_role(self, value: OrganizationInput) -> object:
        self.value = value
        return object()


class GovernanceRepositoryStub:
    async def search(self, _query: str, *, limit: int, filters: dict[str, object]) -> list[object]:
        return []


@pytest.mark.anyio
async def test_create_version_rejects_archived_document_before_repository_write() -> None:
    repository = DocumentRepositoryStub(_document("ARCHIVED"))
    service = EnterpriseDocumentService(repository)  # type: ignore[arg-type]

    with pytest.raises(ValueError, match="Archived documents"):
        await service.create_version(
            NewDocumentVersion(document_id=DOCUMENT_ID, source_file_id=SOURCE_ID)
        )

    assert repository.created_version is None


@pytest.mark.anyio
async def test_review_rejection_requires_reason() -> None:
    service = EnterpriseDocumentService(DocumentRepositoryStub(_document()))  # type: ignore[arg-type]

    with pytest.raises(EnterpriseDocumentValidationError) as captured:
        await service.review_version(
            SOURCE_ID,
            decision="REJECT",
            note=None,
            rejection_reason=None,
        )

    assert captured.value.code == "REJECTION_REASON_REQUIRED"


@pytest.mark.anyio
async def test_identity_service_normalizes_organization_code_and_name() -> None:
    repository = IdentityRepositoryStub()
    service = IdentityService(repository)  # type: ignore[arg-type]

    await service.create_role(OrganizationInput(code=" hr_admin ", name="  HR Admin  "))

    assert repository.value is not None
    assert repository.value.code == "HR_ADMIN"
    assert repository.value.name == "HR Admin"


@pytest.mark.anyio
async def test_enterprise_search_rejects_blank_query_without_repository_call() -> None:
    service = GovernanceService(GovernanceRepositoryStub())  # type: ignore[arg-type]

    with pytest.raises(GovernanceValidationError) as captured:
        await service.search("   ", limit=10, filters={})

    assert captured.value.code == "EMPTY_QUERY"
