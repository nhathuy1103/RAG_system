"""HTTP contracts for reviewing structured claim relations."""

from datetime import UTC, datetime
from uuid import UUID

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api.dependencies.auth import get_current_user
from app.api.dependencies.services import get_structured_fact_review_service
from app.api.main import create_app
from app.api.schemas.auth import CurrentUser
from app.bootstrap.settings import Settings
from app.structured_facts.ports.repositories import StructuredFactReviewConflictError

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


def relation_payload(*, confirmed: bool = False) -> dict[str, object]:
    return {
        "id": RELATION_ID,
        "owner_id": OWNER_ID,
        "notebook_id": NOTEBOOK_ID,
        "source_snapshot_id": SOURCE_SNAPSHOT_ID,
        "target_snapshot_id": TARGET_SNAPSHOT_ID,
        "source_claim_id": SOURCE_CLAIM_ID,
        "target_claim_id": TARGET_CLAIM_ID,
        "relation_type": "conflict" if confirmed else "conflict_candidate",
        "scope_relation": "same",
        "qualifier_compatibility": "equal",
        "temporal_compatibility": "same_interval",
        "confidence": 0.96,
        "evidence": {"reason_codes": ["normalized_value_mismatch"]},
        "reason": "Verified row evidence" if confirmed else None,
        "detector_name": "structured-fact-analyzer",
        "detector_version": "structured-table-v1",
        "review_status": "confirmed" if confirmed else "pending",
        "resolved_by": OWNER_ID if confirmed else None,
        "resolved_at": NOW if confirmed else None,
        "created_at": NOW,
        "updated_at": NOW,
    }


def snapshot_payload(snapshot_id: UUID, document_id: UUID) -> dict[str, object]:
    return {
        "id": snapshot_id,
        "document_id": document_id,
        "source_chunk_id": None,
        "snapshot_key": f"table:{snapshot_id}",
        "schema_fingerprint": "a" * 64,
        "template_fingerprint": "b" * 64,
        "table_index": 0,
        "page_from": 2,
        "page_to": 2,
        "source_locator": {"page_number": 2},
        "normalized_schema": {"columns": ["unit", "sale_price"]},
        "row_count": 1,
        "column_count": 2,
        "extractor_name": "structured-fact-analyzer",
        "extractor_version": "structured-table-v1",
        "publication_time": NOW,
        "effective_from": NOW,
        "effective_to": None,
        "observed_at": NOW,
        "ingested_at": NOW,
        "source_publisher": "Sales",
        "source_type": "price_list",
        "authority_level": 80,
        "authority_metadata": {"channel": "official"},
        "warnings": [],
        "extraction_confidence": 0.98,
        "created_at": NOW,
        "updated_at": NOW,
    }


def claim_payload(
    claim_id: UUID,
    snapshot_id: UUID,
    document_id: UUID,
    value: str,
) -> dict[str, object]:
    return {
        "id": claim_id,
        "document_id": document_id,
        "snapshot_id": snapshot_id,
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
        "publication_time": NOW,
        "effective_from": NOW,
        "effective_to": None,
        "observed_at": NOW,
        "ingested_at": NOW,
        "source_publisher": "Sales",
        "source_type": "price_list",
        "authority_level": 80,
        "authority_metadata": {"channel": "official"},
        "confidence": 0.98,
        "is_derived": False,
        "derivation": {},
        "extractor_version": "structured-table-v1",
        "created_at": NOW,
        "updated_at": NOW,
    }


class FakeStructuredFactReviewService:
    def __init__(
        self,
        *,
        notebook_exists: bool = True,
        stale: bool = False,
        missing: bool = False,
    ) -> None:
        self._notebook_exists = notebook_exists
        self._stale = stale
        self._missing = missing
        self.list_call: tuple[object, ...] | None = None
        self.evidence_call: tuple[object, ...] | None = None
        self.resolve_call: tuple[object, ...] | None = None

    async def notebook_exists(self, notebook_id: UUID) -> bool:
        return self._notebook_exists and notebook_id == NOTEBOOK_ID

    async def list_pending_relations(
        self,
        notebook_id: UUID,
        *,
        limit: int,
        offset: int,
    ) -> tuple[list[dict[str, object]], int]:
        self.list_call = (notebook_id, limit, offset)
        return [relation_payload()], 4

    async def get_relation_evidence(
        self,
        notebook_id: UUID,
        relation_id: UUID,
    ) -> dict[str, object] | None:
        self.evidence_call = (notebook_id, relation_id)
        if self._missing:
            return None
        return {
            "relation": relation_payload(),
            "source_snapshot": snapshot_payload(
                SOURCE_SNAPSHOT_ID,
                SOURCE_DOCUMENT_ID,
            ),
            "target_snapshot": snapshot_payload(
                TARGET_SNAPSHOT_ID,
                TARGET_DOCUMENT_ID,
            ),
            "source_claim": claim_payload(
                SOURCE_CLAIM_ID,
                SOURCE_SNAPSHOT_ID,
                SOURCE_DOCUMENT_ID,
                "4500000000",
            ),
            "target_claim": claim_payload(
                TARGET_CLAIM_ID,
                TARGET_SNAPSHOT_ID,
                TARGET_DOCUMENT_ID,
                "4300000000",
            ),
        }

    async def resolve_relation(
        self,
        notebook_id: UUID,
        relation_id: UUID,
        action: object,
        expected_updated_at: datetime,
        reason: str,
    ) -> dict[str, object] | None:
        self.resolve_call = (
            notebook_id,
            relation_id,
            action,
            expected_updated_at,
            reason,
        )
        if self._stale:
            raise StructuredFactReviewConflictError("stale")
        if self._missing:
            return None
        return relation_payload(confirmed=True)


def make_settings() -> Settings:
    return Settings.model_validate(
        {
            "app_env": "test",
            "supabase_url": "https://example.supabase.co",
            "ingestion_worker_enabled": False,
        }
    )


def make_app(service: FakeStructuredFactReviewService) -> FastAPI:
    app = create_app(make_settings())
    app.dependency_overrides[get_current_user] = lambda: CurrentUser(
        id=str(OWNER_ID),
        email="user@example.com",
        role="authenticated",
    )
    app.dependency_overrides[get_structured_fact_review_service] = lambda: service
    return app


def test_lists_paginated_pending_structured_relations() -> None:
    service = FakeStructuredFactReviewService()
    with TestClient(make_app(service)) as client:
        response = client.get(
            f"/notebooks/{NOTEBOOK_ID}/structured-facts/relations",
            params={"limit": 7, "offset": 2},
        )

    assert response.status_code == 200
    assert response.json()["total_count"] == 4
    assert response.json()["items"][0]["review_status"] == "pending"
    assert service.list_call == (NOTEBOOK_ID, 7, 2)


def test_gets_both_claims_and_snapshots_for_review() -> None:
    service = FakeStructuredFactReviewService()
    with TestClient(make_app(service)) as client:
        response = client.get(
            f"/notebooks/{NOTEBOOK_ID}/structured-facts/relations/{RELATION_ID}/evidence"
        )

    assert response.status_code == 200
    payload = response.json()
    assert payload["source_snapshot"]["document_id"] == str(SOURCE_DOCUMENT_ID)
    assert payload["target_snapshot"]["document_id"] == str(TARGET_DOCUMENT_ID)
    assert payload["source_claim"]["normalized_value"]["value"] == "4500000000"
    assert payload["target_claim"]["normalized_value"]["value"] == "4300000000"
    assert payload["source_claim"]["provenance"]["row_index"] == 1


def test_resolves_with_action_reason_and_optimistic_timestamp() -> None:
    service = FakeStructuredFactReviewService()
    with TestClient(make_app(service)) as client:
        response = client.post(
            f"/notebooks/{NOTEBOOK_ID}/structured-facts/relations/{RELATION_ID}/resolve",
            json={
                "action": "confirm_conflict",
                "expected_updated_at": NOW.isoformat(),
                "reason": "  Verified row evidence  ",
            },
        )

    assert response.status_code == 200
    assert response.json()["relation_type"] == "conflict"
    assert response.json()["review_status"] == "confirmed"
    assert service.resolve_call is not None
    assert str(service.resolve_call[2]) == "confirm_conflict"
    assert service.resolve_call[-1] == "Verified row evidence"


def test_stale_relation_returns_conflict_and_missing_notebook_is_hidden() -> None:
    stale_service = FakeStructuredFactReviewService(stale=True)
    hidden_service = FakeStructuredFactReviewService(notebook_exists=False)
    with TestClient(make_app(stale_service)) as client:
        stale = client.post(
            f"/notebooks/{NOTEBOOK_ID}/structured-facts/relations/{RELATION_ID}/resolve",
            json={
                "action": "dismiss",
                "expected_updated_at": NOW.isoformat(),
                "reason": "False positive",
            },
        )
    with TestClient(make_app(hidden_service)) as client:
        hidden = client.get(f"/notebooks/{NOTEBOOK_ID}/structured-facts/relations")

    assert stale.status_code == 409
    assert hidden.status_code == 404
    assert hidden_service.list_call is None


def test_resolution_rejects_blank_reason_and_naive_timestamp() -> None:
    service = FakeStructuredFactReviewService()
    endpoint = f"/notebooks/{NOTEBOOK_ID}/structured-facts/relations/{RELATION_ID}/resolve"
    with TestClient(make_app(service)) as client:
        blank = client.post(
            endpoint,
            json={
                "action": "dismiss",
                "expected_updated_at": NOW.isoformat(),
                "reason": "   ",
            },
        )
        naive = client.post(
            endpoint,
            json={
                "action": "dismiss",
                "expected_updated_at": "2026-08-05T10:00:00",
                "reason": "False positive",
            },
        )

    assert blank.status_code == 422
    assert naive.status_code == 422
    assert service.resolve_call is None
