"""Integration tests for the PostgREST notebook adapter contract."""

import json
from uuid import UUID

import httpx2 as httpx
import pytest

from app.notebooks.adapters.postgrest_repository import (
    PostgrestNotebookRepository,
)

NOTEBOOK_ROW = {
    "id": "10000000-0000-0000-0000-000000000001",
    "owner_id": "20000000-0000-0000-0000-000000000002",
    "title": "Notebook",
    "description": "Mô tả notebook",
    "is_active": True,
    "created_at": "2026-07-24T09:00:00+00:00",
    "updated_at": "2026-07-24T09:00:00+00:00",
}
NOTEBOOK_COLUMNS = "id,owner_id,title,description,is_active,created_at,updated_at"


@pytest.mark.anyio
async def test_exists_owned_uses_rls_scoped_lookup() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.method == "GET"
        assert request.url.params["select"] == "id"
        assert request.url.params["id"] == f"eq.{NOTEBOOK_ROW['id']}"
        assert request.url.params["is_active"] == "eq.true"
        assert request.url.params["limit"] == "1"
        return httpx.Response(200, json=[{"id": NOTEBOOK_ROW["id"]}])

    async with httpx.AsyncClient(
        base_url="https://example.supabase.co/rest/v1",
        transport=httpx.MockTransport(handler),
    ) as client:
        exists = await PostgrestNotebookRepository(client).exists_owned(UUID(NOTEBOOK_ROW["id"]))

    assert exists is True


@pytest.mark.anyio
async def test_list_owned_parses_postgrest_rows() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.method == "GET"
        assert request.url.path == "/rest/v1/notebooks"
        assert request.url.params["select"] == NOTEBOOK_COLUMNS
        assert request.url.params["is_active"] == "eq.true"
        return httpx.Response(200, json=[NOTEBOOK_ROW])

    async with httpx.AsyncClient(
        base_url="https://example.supabase.co/rest/v1",
        transport=httpx.MockTransport(handler),
    ) as client:
        notebooks = await PostgrestNotebookRepository(client).list_owned()

    assert len(notebooks) == 1
    assert notebooks[0].title == "Notebook"
    assert notebooks[0].description == "Mô tả notebook"
    assert str(notebooks[0].owner_id) == NOTEBOOK_ROW["owner_id"]


@pytest.mark.anyio
async def test_create_relies_on_rls_owner_default() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.method == "POST"
        assert request.headers["prefer"] == "return=representation"
        assert json.loads(request.content) == {
            "title": "Notebook mới",
            "description": "Mô tả mới",
        }
        return httpx.Response(
            201,
            json=[
                {
                    **NOTEBOOK_ROW,
                    "title": "Notebook mới",
                    "description": "Mô tả mới",
                }
            ],
        )

    async with httpx.AsyncClient(
        base_url="https://example.supabase.co/rest/v1",
        transport=httpx.MockTransport(handler),
    ) as client:
        notebook = await PostgrestNotebookRepository(client).create(
            "Notebook mới",
            "Mô tả mới",
        )

    assert notebook.title == "Notebook mới"
    assert notebook.description == "Mô tả mới"


@pytest.mark.anyio
async def test_update_sends_only_changed_fields() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.method == "PATCH"
        assert request.url.path == "/rest/v1/notebooks"
        assert request.url.params["id"] == f"eq.{NOTEBOOK_ROW['id']}"
        assert request.url.params["is_active"] == "eq.true"
        assert request.url.params["select"] == NOTEBOOK_COLUMNS
        assert request.headers["prefer"] == "return=representation"
        assert json.loads(request.content) == {"description": ""}
        return httpx.Response(200, json=[{**NOTEBOOK_ROW, "description": ""}])

    async with httpx.AsyncClient(
        base_url="https://example.supabase.co/rest/v1",
        transport=httpx.MockTransport(handler),
    ) as client:
        notebook = await PostgrestNotebookRepository(client).update(
            UUID(NOTEBOOK_ROW["id"]),
            {"description": ""},
        )

    assert notebook is not None
    assert notebook.description == ""


@pytest.mark.anyio
async def test_update_returns_none_when_rls_hides_notebook() -> None:
    async with httpx.AsyncClient(
        base_url="https://example.supabase.co/rest/v1",
        transport=httpx.MockTransport(lambda _request: httpx.Response(200, json=[])),
    ) as client:
        notebook = await PostgrestNotebookRepository(client).update(
            UUID(NOTEBOOK_ROW["id"]),
            {"title": "Tên mới"},
        )

    assert notebook is None


@pytest.mark.anyio
async def test_soft_delete_flips_is_active_and_keeps_the_row() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.method == "PATCH"
        assert request.url.path == "/rest/v1/notebooks"
        assert request.url.params["id"] == f"eq.{NOTEBOOK_ROW['id']}"
        assert request.url.params["is_active"] == "eq.true"
        assert request.url.params["select"] == NOTEBOOK_COLUMNS
        assert request.headers["prefer"] == "return=representation"
        assert json.loads(request.content) == {"is_active": False}
        return httpx.Response(200, json=[{**NOTEBOOK_ROW, "is_active": False}])

    async with httpx.AsyncClient(
        base_url="https://example.supabase.co/rest/v1",
        transport=httpx.MockTransport(handler),
    ) as client:
        notebook = await PostgrestNotebookRepository(client).soft_delete(UUID(NOTEBOOK_ROW["id"]))

    assert notebook is not None
    assert notebook.is_active is False


@pytest.mark.anyio
async def test_soft_delete_returns_none_when_already_archived() -> None:
    async with httpx.AsyncClient(
        base_url="https://example.supabase.co/rest/v1",
        transport=httpx.MockTransport(lambda _request: httpx.Response(200, json=[])),
    ) as client:
        notebook = await PostgrestNotebookRepository(client).soft_delete(UUID(NOTEBOOK_ROW["id"]))

    assert notebook is None
