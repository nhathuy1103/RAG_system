from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID

import httpx2 as httpx
import pytest
from fastapi import FastAPI

from app.api.dependencies.auth import get_current_user
from app.api.dependencies.enterprise import get_enterprise_document_service
from app.api.routers import enterprise_documents
from app.api.schemas.auth import CurrentUser
from app.documents.application.enterprise_services import EnterpriseDocumentService
from app.documents.domain.enterprise_models import DocumentSearchability

USER_ID = UUID("10000000-0000-0000-0000-000000000001")
DOCUMENT_ID = UUID("20000000-0000-0000-0000-000000000002")
VERSION_ID = UUID("30000000-0000-0000-0000-000000000003")
PROCESSED_AT = datetime(2026, 8, 11, 7, 30, tzinfo=UTC)


def _diagnostic() -> DocumentSearchability:
    return DocumentSearchability(
        document_id=DOCUMENT_ID,
        title="Quy dinh nhan su",
        document_status="PUBLISHED",
        visibility="INTERNAL",
        current_version_id=VERSION_ID,
        version_status="ACTIVE",
        metadata_revision=2,
        chunk_count=12,
        ready_projection_count=12,
        lexical_ready_projection_count=11,
        lexical_stale_count=1,
        embedding_stale_count=3,
        refresh_requested_revision=2,
        refresh_processed_at=PROCESSED_AT,
        refresh_error=None,
        searchable_for_actor=True,
        fully_indexed=False,
        blocking_reasons=("LEXICAL_PROJECTION_STALE",),
        warnings=("EMBEDDING_METADATA_STALE",),
    )


class RepositoryStub:
    def __init__(self) -> None:
        self.document_id: UUID | None | object = object()

    async def list_searchability(self, *, document_id: UUID | None) -> list[DocumentSearchability]:
        self.document_id = document_id
        return [_diagnostic()]


class ServiceStub:
    async def list_searchability(self, *, document_id: UUID | None) -> list[DocumentSearchability]:
        assert document_id == DOCUMENT_ID
        return [_diagnostic()]


@pytest.mark.anyio
async def test_searchability_service_forwards_optional_document_scope() -> None:
    repository = RepositoryStub()
    service = EnterpriseDocumentService(repository)  # type: ignore[arg-type]

    result = await service.list_searchability(document_id=DOCUMENT_ID)

    assert repository.document_id == DOCUMENT_ID
    assert result == [_diagnostic()]


def _app(*, authenticated: bool) -> FastAPI:
    app = FastAPI()
    app.include_router(enterprise_documents.router)
    app.dependency_overrides[get_enterprise_document_service] = ServiceStub
    if authenticated:
        app.dependency_overrides[get_current_user] = lambda: CurrentUser(
            id=str(USER_ID), email="user@example.test"
        )
    return app


@pytest.mark.anyio
async def test_searchability_route_is_static_actor_scoped_and_exposes_no_content() -> None:
    transport = httpx.ASGITransport(app=_app(authenticated=True))
    async with httpx.AsyncClient(transport=transport, base_url="https://api.test") as client:
        response = await client.get(f"/api/v1/documents/searchability?document_id={DOCUMENT_ID}")

    assert response.status_code == 200
    assert isinstance(response.json(), list)
    payload = response.json()[0]
    assert payload["document_id"] == str(DOCUMENT_ID)
    assert payload["current_version_id"] == str(VERSION_ID)
    assert payload["searchable_for_actor"] is True
    assert payload["fully_indexed"] is False
    assert payload["lexical_ready_projection_count"] == 11
    assert payload["blocking_reasons"] == ["LEXICAL_PROJECTION_STALE"]
    assert payload["warnings"] == ["EMBEDDING_METADATA_STALE"]
    assert "content" not in payload


@pytest.mark.anyio
async def test_searchability_route_requires_bearer_authentication() -> None:
    transport = httpx.ASGITransport(app=_app(authenticated=False))
    async with httpx.AsyncClient(transport=transport, base_url="https://api.test") as client:
        response = await client.get("/api/v1/documents/searchability")

    assert response.status_code == 401
    assert response.json()["detail"] == "Missing Bearer token"
