"""PostgREST contracts for owner-scoped structured relation review."""

import json
from datetime import UTC, datetime
from uuid import UUID

import httpx2 as httpx
import pytest

from app.structured_facts.adapters.postgrest_repository import (
    PostgrestStructuredFactReviewRepository,
)
from app.structured_facts.domain.review import StructuredClaimResolutionAction
from app.structured_facts.ports.repositories import (
    StructuredFactReviewConflictError,
    StructuredFactReviewRepositoryError,
)

OWNER_ID = UUID("10000000-0000-0000-0000-000000000001")
NOTEBOOK_ID = UUID("20000000-0000-0000-0000-000000000002")
RELATION_ID = UUID("30000000-0000-0000-0000-000000000003")
SOURCE_SNAPSHOT_ID = UUID("40000000-0000-0000-0000-000000000004")
TARGET_SNAPSHOT_ID = UUID("50000000-0000-0000-0000-000000000005")
SOURCE_CLAIM_ID = UUID("60000000-0000-0000-0000-000000000006")
TARGET_CLAIM_ID = UUID("70000000-0000-0000-0000-000000000007")
SOURCE_DOCUMENT_ID = UUID("80000000-0000-0000-0000-000000000008")
TARGET_DOCUMENT_ID = UUID("90000000-0000-0000-0000-000000000009")
NOW = datetime(2026, 8, 5, 10, tzinfo=UTC)


def relation_row(
    *,
    relation_type: str = "conflict_candidate",
    review_status: str = "pending",
) -> dict[str, object]:
    resolved = review_status in {"confirmed", "dismissed"}
    return {
        "id": str(RELATION_ID),
        "owner_id": str(OWNER_ID),
        "notebook_id": str(NOTEBOOK_ID),
        "source_snapshot_id": str(SOURCE_SNAPSHOT_ID),
        "target_snapshot_id": str(TARGET_SNAPSHOT_ID),
        "source_claim_id": str(SOURCE_CLAIM_ID),
        "target_claim_id": str(TARGET_CLAIM_ID),
        "relation_type": relation_type,
        "scope_relation": "same",
        "qualifier_compatibility": "equal",
        "temporal_compatibility": "same_interval",
        "confidence": 0.96,
        "evidence": {"reason_codes": ["normalized_value_mismatch"]},
        "reason": "reviewed" if resolved else None,
        "detector_name": "structured-fact-analyzer",
        "detector_version": "structured-table-v1",
        "review_status": review_status,
        "resolved_by": str(OWNER_ID) if resolved else None,
        "resolved_at": NOW.isoformat() if resolved else None,
        "created_at": NOW.isoformat(),
        "updated_at": NOW.isoformat(),
    }


def snapshot_row(snapshot_id: UUID, document_id: UUID) -> dict[str, object]:
    return {
        "id": str(snapshot_id),
        "document_id": str(document_id),
        "source_chunk_id": None,
        "snapshot_key": f"table:{snapshot_id}",
        "schema_fingerprint": "a" * 64,
        "template_fingerprint": "b" * 64,
        "table_index": 0,
        "page_from": 2,
        "page_to": 2,
        "source_locator": {"table_index": 0, "page_number": 2},
        "normalized_schema": {"columns": ["unit", "sale_price"]},
        "row_count": 1,
        "column_count": 2,
        "extractor_name": "structured-fact-analyzer",
        "extractor_version": "structured-table-v1",
        "publication_time": NOW.isoformat(),
        "effective_from": NOW.isoformat(),
        "effective_to": None,
        "observed_at": NOW.isoformat(),
        "ingested_at": NOW.isoformat(),
        "source_publisher": "Sales",
        "source_type": "price_list",
        "authority_level": 80,
        "authority_metadata": {"channel": "official"},
        "warnings": [],
        "extraction_confidence": 0.98,
        "created_at": NOW.isoformat(),
        "updated_at": NOW.isoformat(),
    }


def claim_row(
    claim_id: UUID,
    snapshot_id: UUID,
    document_id: UUID,
    value: str,
) -> dict[str, object]:
    return {
        "id": str(claim_id),
        "document_id": str(document_id),
        "snapshot_id": str(snapshot_id),
        "source_chunk_id": None,
        "claim_key": f"claim:{claim_id}",
        "row_identity": "unit=A101",
        "row_identity_hash": "c" * 64,
        "row_index": 1,
        "data_row_ordinal": 0,
        "page_number": 2,
        "source_text": f"A101 | {value}",
        "source_cells": [{"column": "sale_price", "raw_value": value}],
        "provenance": {"page_number": 2, "row_index": 1},
        "subject_identity": {"unit": "A101"},
        "subject_identity_hash": "d" * 64,
        "candidate_identity_hash": "e" * 64,
        "predicate": "sale_price",
        "value_type": "money",
        "normalized_value": {"value": value, "currency": "VND"},
        "numeric_value": value,
        "unit": None,
        "currency": "VND",
        "qualifiers": {"stable": {"price_type": "list_price"}},
        "qualifier_hash": "f" * 64,
        "publication_time": NOW.isoformat(),
        "effective_from": NOW.isoformat(),
        "effective_to": None,
        "observed_at": NOW.isoformat(),
        "ingested_at": NOW.isoformat(),
        "source_publisher": "Sales",
        "source_type": "price_list",
        "authority_level": 80,
        "authority_metadata": {"channel": "official"},
        "confidence": 0.98,
        "is_derived": False,
        "derivation": {},
        "extractor_version": "structured-table-v1",
        "created_at": NOW.isoformat(),
        "updated_at": NOW.isoformat(),
    }


@pytest.mark.anyio
async def test_lists_only_pending_relations_with_exact_pagination_count() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path.endswith("/claim_relations")
        assert request.url.params["notebook_id"] == f"eq.{NOTEBOOK_ID}"
        assert request.url.params["review_status"] == "eq.pending"
        assert request.url.params["limit"] == "7"
        assert request.url.params["offset"] == "3"
        assert request.headers["prefer"] == "count=exact"
        return httpx.Response(
            200,
            headers={"Content-Range": "3-3/11"},
            json=[relation_row()],
        )

    async with httpx.AsyncClient(
        transport=httpx.MockTransport(handler),
        base_url="https://supabase.test/rest/v1",
    ) as client:
        relations, total = await PostgrestStructuredFactReviewRepository(
            client
        ).list_pending_relations(NOTEBOOK_ID, limit=7, offset=3)

    assert total == 11
    assert relations[0].relation_type.value == "conflict_candidate"
    assert relations[0].review_status.value == "pending"


@pytest.mark.anyio
async def test_loads_both_snapshot_and_claim_evidence_endpoints() -> None:
    requested_paths: list[str] = []

    async def handler(request: httpx.Request) -> httpx.Response:
        requested_paths.append(request.url.path)
        assert request.url.params["notebook_id"] == f"eq.{NOTEBOOK_ID}"
        if request.url.path.endswith("/claim_relations"):
            return httpx.Response(200, json=[relation_row()])
        if request.url.path.endswith("/table_snapshots"):
            return httpx.Response(
                200,
                json=[
                    snapshot_row(SOURCE_SNAPSHOT_ID, SOURCE_DOCUMENT_ID),
                    snapshot_row(TARGET_SNAPSHOT_ID, TARGET_DOCUMENT_ID),
                ],
            )
        if request.url.path.endswith("/structured_claims"):
            return httpx.Response(
                200,
                json=[
                    claim_row(
                        SOURCE_CLAIM_ID,
                        SOURCE_SNAPSHOT_ID,
                        SOURCE_DOCUMENT_ID,
                        "4500000000",
                    ),
                    claim_row(
                        TARGET_CLAIM_ID,
                        TARGET_SNAPSHOT_ID,
                        TARGET_DOCUMENT_ID,
                        "4300000000",
                    ),
                ],
            )
        raise AssertionError(f"Unexpected path: {request.url.path}")

    async with httpx.AsyncClient(
        transport=httpx.MockTransport(handler),
        base_url="https://supabase.test/rest/v1",
    ) as client:
        evidence = await PostgrestStructuredFactReviewRepository(client).get_relation_evidence(
            NOTEBOOK_ID, RELATION_ID
        )

    assert evidence is not None
    assert evidence.source_snapshot.id == SOURCE_SNAPSHOT_ID
    assert evidence.target_snapshot.id == TARGET_SNAPSHOT_ID
    assert evidence.source_claim is not None
    assert evidence.target_claim is not None
    assert evidence.source_claim.numeric_value == "4500000000"
    assert evidence.target_claim.numeric_value == "4300000000"
    assert len(requested_paths) == 3


@pytest.mark.anyio
async def test_rejects_claim_evidence_attached_to_the_wrong_snapshot() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/claim_relations"):
            return httpx.Response(200, json=[relation_row()])
        if request.url.path.endswith("/table_snapshots"):
            return httpx.Response(
                200,
                json=[
                    snapshot_row(SOURCE_SNAPSHOT_ID, SOURCE_DOCUMENT_ID),
                    snapshot_row(TARGET_SNAPSHOT_ID, TARGET_DOCUMENT_ID),
                ],
            )
        if request.url.path.endswith("/structured_claims"):
            return httpx.Response(
                200,
                json=[
                    claim_row(
                        SOURCE_CLAIM_ID,
                        TARGET_SNAPSHOT_ID,
                        SOURCE_DOCUMENT_ID,
                        "4500000000",
                    ),
                    claim_row(
                        TARGET_CLAIM_ID,
                        TARGET_SNAPSHOT_ID,
                        TARGET_DOCUMENT_ID,
                        "4300000000",
                    ),
                ],
            )
        raise AssertionError(f"Unexpected path: {request.url.path}")

    async with httpx.AsyncClient(
        transport=httpx.MockTransport(handler),
        base_url="https://supabase.test/rest/v1",
    ) as client:
        with pytest.raises(StructuredFactReviewRepositoryError):
            await PostgrestStructuredFactReviewRepository(client).get_relation_evidence(
                NOTEBOOK_ID, RELATION_ID
            )


@pytest.mark.anyio
async def test_resolves_through_owner_scoped_optimistic_rpc() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path.endswith("/rpc/resolve_structured_claim_relation")
        assert json.loads(request.read()) == {
            "p_relation_id": str(RELATION_ID),
            "p_notebook_id": str(NOTEBOOK_ID),
            "p_action": "confirm_conflict",
            "p_expected_updated_at": NOW.isoformat(),
            "p_reason": "Verified both source rows",
        }
        return httpx.Response(
            200,
            json=[relation_row(relation_type="conflict", review_status="confirmed")],
        )

    async with httpx.AsyncClient(
        transport=httpx.MockTransport(handler),
        base_url="https://supabase.test/rest/v1",
    ) as client:
        relation = await PostgrestStructuredFactReviewRepository(client).resolve_relation(
            NOTEBOOK_ID,
            RELATION_ID,
            StructuredClaimResolutionAction.CONFIRM_CONFLICT,
            NOW,
            "Verified both source rows",
        )

    assert relation is not None
    assert relation.relation_type.value == "conflict"
    assert relation.review_status.value == "confirmed"


@pytest.mark.anyio
async def test_maps_stale_rpc_snapshot_to_review_conflict() -> None:
    async def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            409,
            json={"code": "40001", "message": "stale"},
        )

    async with httpx.AsyncClient(
        transport=httpx.MockTransport(handler),
        base_url="https://supabase.test/rest/v1",
    ) as client:
        with pytest.raises(StructuredFactReviewConflictError):
            await PostgrestStructuredFactReviewRepository(client).resolve_relation(
                NOTEBOOK_ID,
                RELATION_ID,
                StructuredClaimResolutionAction.DISMISS,
                NOW,
                "False positive",
            )
