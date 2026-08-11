from __future__ import annotations

import json
from datetime import UTC, datetime
from uuid import UUID

import httpx2 as httpx
import pytest

from app.documents.adapters.enterprise_postgrest_repository import (
    PostgrestEnterpriseDocumentRepository,
)
from app.documents.ports.enterprise_repositories import EnterpriseDocumentRepositoryError

DOCUMENT_ID = UUID("20000000-0000-0000-0000-000000000002")
VERSION_ID = UUID("30000000-0000-0000-0000-000000000003")
PROCESSED_AT = datetime(2026, 8, 11, 7, 30, tzinfo=UTC)


def _searchability_row() -> dict[str, object]:
    return {
        "document_id": str(DOCUMENT_ID),
        "title": "Quy dinh nhan su",
        "document_status": "PUBLISHED",
        "visibility": "INTERNAL",
        "current_version_id": str(VERSION_ID),
        "version_status": "ACTIVE",
        "metadata_revision": 2,
        "chunk_count": 12,
        "ready_projection_count": 12,
        "lexical_ready_projection_count": 12,
        "lexical_stale_count": 0,
        "embedding_stale_count": 3,
        "refresh_requested_revision": 2,
        "refresh_processed_at": PROCESSED_AT.isoformat(),
        "refresh_error": None,
        "searchable_for_actor": True,
        "fully_indexed": True,
        "blocking_reasons": [],
        "warnings": ["EMBEDDING_METADATA_STALE"],
    }


@pytest.mark.anyio
async def test_searchability_calls_actor_scoped_rpc_and_parses_all_diagnostics() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path.endswith("/rpc/get_enterprise_document_searchability")
        assert json.loads(request.content) == {"p_document_id": str(DOCUMENT_ID)}
        return httpx.Response(200, json=[_searchability_row()])

    async with httpx.AsyncClient(
        base_url="https://example.test/rest/v1",
        transport=httpx.MockTransport(handler),
    ) as client:
        result = await PostgrestEnterpriseDocumentRepository(client).list_searchability(
            document_id=DOCUMENT_ID
        )

    assert len(result) == 1
    diagnostic = result[0]
    assert diagnostic.document_id == DOCUMENT_ID
    assert diagnostic.current_version_id == VERSION_ID
    assert diagnostic.searchable_for_actor is True
    assert diagnostic.fully_indexed is True
    assert diagnostic.chunk_count == 12
    assert diagnostic.refresh_processed_at == PROCESSED_AT
    assert diagnostic.blocking_reasons == ()
    assert diagnostic.warnings == ("EMBEDDING_METADATA_STALE",)


@pytest.mark.anyio
async def test_searchability_list_sends_null_filter_and_rejects_invalid_boolean() -> None:
    row = _searchability_row()
    row["searchable_for_actor"] = "true"

    def handler(request: httpx.Request) -> httpx.Response:
        assert json.loads(request.content) == {"p_document_id": None}
        return httpx.Response(200, json=[row])

    async with httpx.AsyncClient(
        base_url="https://example.test/rest/v1",
        transport=httpx.MockTransport(handler),
    ) as client:
        with pytest.raises(
            EnterpriseDocumentRepositoryError,
            match="Invalid document searchability response",
        ):
            await PostgrestEnterpriseDocumentRepository(client).list_searchability(document_id=None)
