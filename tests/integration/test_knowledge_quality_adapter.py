"""Integration-style HTTP contract tests for the quality PostgREST adapter."""

from datetime import UTC, datetime
from uuid import UUID

import httpx2 as httpx
import pytest

from app.knowledge_quality.adapters.postgrest_repository import (
    AUDIT_COLUMNS,
    RELATION_COLUMNS,
    PostgrestKnowledgeQualityRepository,
)
from app.knowledge_quality.domain.models import (
    RelationStatus,
    RelationType,
    ResolutionAction,
)
from app.knowledge_quality.ports.repositories import (
    KnowledgeQualityConflictError,
)

RELATION_ID = UUID("50000000-0000-0000-0000-000000000005")
OWNER_ID = UUID("20000000-0000-0000-0000-000000000002")
NOTEBOOK_ID = UUID("10000000-0000-0000-0000-000000000001")
SOURCE_ID = UUID("30000000-0000-0000-0000-000000000003")
TARGET_ID = UUID("40000000-0000-0000-0000-000000000004")
NOW = datetime(2026, 7, 30, tzinfo=UTC)

RELATION_ROW = {
    "id": str(RELATION_ID),
    "owner_id": str(OWNER_ID),
    "notebook_id": str(NOTEBOOK_ID),
    "source_document_id": str(SOURCE_ID),
    "target_document_id": str(TARGET_ID),
    "relation_type": "version_candidate",
    "status": "pending",
    "confidence": 0.91,
    "signals": {"document_probe_coverage": 0.75},
    "reason": "high_content_containment",
    "detector_version": "knowledge-quality-v1",
    "preferred_document_id": None,
    "resolved_by": None,
    "resolved_at": None,
    "created_at": NOW.isoformat(),
    "updated_at": NOW.isoformat(),
}
AUDIT_ROW = {
    "id": 17,
    "owner_id": str(OWNER_ID),
    "notebook_id": str(NOTEBOOK_ID),
    "relation_id": str(RELATION_ID),
    "actor_id": str(OWNER_ID),
    "action": "mark_version",
    "reason": "Approved after comparison",
    "before_state": {"relation": RELATION_ROW},
    "after_state": {
        "relation": {
            **RELATION_ROW,
            "relation_type": "version",
            "status": "confirmed",
        }
    },
    "created_at": NOW.isoformat(),
}


@pytest.mark.anyio
async def test_lists_filtered_relation_queue_with_exact_count() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.method == "GET"
        assert request.url.path == "/rest/v1/document_relations"
        assert request.url.params["notebook_id"] == f"eq.{NOTEBOOK_ID}"
        assert request.url.params["status"] == "eq.pending"
        assert request.url.params["relation_type"] == "eq.version_candidate"
        assert request.url.params["select"] == RELATION_COLUMNS
        assert request.headers["prefer"] == "count=exact"
        return httpx.Response(
            200,
            json=[RELATION_ROW],
            headers={"Content-Range": "0-0/1"},
        )

    async with httpx.AsyncClient(
        base_url="https://example.supabase.co/rest/v1",
        transport=httpx.MockTransport(handler),
    ) as client:
        relations, total = await PostgrestKnowledgeQualityRepository(client).list_relations(
            NOTEBOOK_ID,
            relation_status=RelationStatus.PENDING,
            relation_type=RelationType.VERSION_CANDIDATE,
            limit=50,
            offset=0,
        )

    assert total == 1
    assert relations[0].id == RELATION_ID
    assert relations[0].signals["document_probe_coverage"] == 0.75


@pytest.mark.anyio
async def test_resolves_relation_through_transactional_rpc() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.method == "POST"
        assert request.url.path == "/rest/v1/rpc/resolve_document_relation"
        assert request.read()
        payload = request.content.decode("utf-8")
        assert '"p_action":"mark_version"' in payload
        assert f'"p_relation_id":"{RELATION_ID}"' in payload
        assert '"p_expected_updated_at":"' in payload
        return httpx.Response(
            200,
            json=[
                {
                    **RELATION_ROW,
                    "relation_type": "version",
                    "status": "confirmed",
                    "preferred_document_id": str(SOURCE_ID),
                    "resolved_by": str(OWNER_ID),
                    "resolved_at": NOW.isoformat(),
                }
            ],
        )

    async with httpx.AsyncClient(
        base_url="https://example.supabase.co/rest/v1",
        transport=httpx.MockTransport(handler),
    ) as client:
        relation = await PostgrestKnowledgeQualityRepository(client).resolve_relation(
            NOTEBOOK_ID,
            RELATION_ID,
            ResolutionAction.MARK_VERSION,
            NOW,
            "Approved after comparison",
        )

    assert relation is not None
    assert relation.relation_type == RelationType.VERSION
    assert relation.status == RelationStatus.CONFIRMED


@pytest.mark.anyio
async def test_maps_database_not_found_to_none() -> None:
    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            400,
            json={"code": "P0002", "message": "Document relation was not found"},
        )

    async with httpx.AsyncClient(
        base_url="https://example.supabase.co/rest/v1",
        transport=httpx.MockTransport(handler),
    ) as client:
        relation = await PostgrestKnowledgeQualityRepository(client).resolve_relation(
            NOTEBOOK_ID,
            RELATION_ID,
            ResolutionAction.DISMISS,
            NOW,
            None,
        )

    assert relation is None


@pytest.mark.anyio
async def test_maps_stale_resolution_to_conflict_error() -> None:
    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            400,
            json={
                "code": "40001",
                "message": "Document relation changed before resolution",
            },
        )

    async with httpx.AsyncClient(
        base_url="https://example.supabase.co/rest/v1",
        transport=httpx.MockTransport(handler),
    ) as client:
        with pytest.raises(KnowledgeQualityConflictError):
            await PostgrestKnowledgeQualityRepository(client).resolve_relation(
                NOTEBOOK_ID,
                RELATION_ID,
                ResolutionAction.DISMISS,
                NOW,
                None,
            )


@pytest.mark.anyio
async def test_lists_relation_audit_with_exact_count() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.method == "GET"
        assert request.url.path == "/rest/v1/knowledge_quality_audit"
        assert request.url.params["notebook_id"] == f"eq.{NOTEBOOK_ID}"
        assert request.url.params["relation_id"] == f"eq.{RELATION_ID}"
        assert request.url.params["select"] == AUDIT_COLUMNS
        return httpx.Response(
            200,
            json=[AUDIT_ROW],
            headers={"Content-Range": "0-0/1"},
        )

    async with httpx.AsyncClient(
        base_url="https://example.supabase.co/rest/v1",
        transport=httpx.MockTransport(handler),
    ) as client:
        events, total = await PostgrestKnowledgeQualityRepository(client).list_audit_events(
            NOTEBOOK_ID,
            relation_id=RELATION_ID,
            limit=50,
            offset=0,
        )

    assert total == 1
    assert events[0].id == 17
    assert events[0].action == "mark_version"
    assert events[0].before_state["relation"]["status"] == "pending"


@pytest.mark.anyio
async def test_reverts_latest_resolution_through_optimistic_rpc() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.method == "POST"
        assert request.url.path == "/rest/v1/rpc/revert_document_relation_resolution"
        payload = request.content.decode("utf-8")
        assert f'"p_relation_id":"{RELATION_ID}"' in payload
        assert '"p_reason":"Incorrect version lineage"' in payload
        return httpx.Response(200, json=[RELATION_ROW])

    async with httpx.AsyncClient(
        base_url="https://example.supabase.co/rest/v1",
        transport=httpx.MockTransport(handler),
    ) as client:
        relation = await PostgrestKnowledgeQualityRepository(client).revert_relation(
            NOTEBOOK_ID,
            RELATION_ID,
            NOW,
            "Incorrect version lineage",
        )

    assert relation is not None
    assert relation.status == RelationStatus.PENDING
    assert relation.updated_at == NOW
