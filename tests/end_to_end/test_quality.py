"""End-to-end API contracts for quality review, audit, and reversal."""

from datetime import UTC, datetime, timedelta
from uuid import UUID

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api.dependencies.auth import get_current_user
from app.api.dependencies.services import get_knowledge_quality_service
from app.api.main import create_app
from app.api.schemas.auth import CurrentUser
from app.bootstrap.settings import Settings
from app.knowledge_quality.domain.models import (
    DocumentRelation,
    DocumentRelationEvidence,
    KnowledgeQualityAudit,
    RelationEvidenceChunk,
    RelationEvidenceChunkPair,
    RelationEvidenceDocument,
    RelationStatus,
    RelationType,
)
from app.knowledge_quality.ports.repositories import (
    KnowledgeQualityConflictError,
)

OWNER_ID = UUID("20000000-0000-0000-0000-000000000002")
NOTEBOOK_ID = UUID("10000000-0000-0000-0000-000000000001")
RELATION_ID = UUID("50000000-0000-0000-0000-000000000005")
SOURCE_ID = UUID("30000000-0000-0000-0000-000000000003")
TARGET_ID = UUID("40000000-0000-0000-0000-000000000004")
NOW = datetime(2026, 7, 30, tzinfo=UTC)


def make_relation(
    *,
    status: RelationStatus = RelationStatus.PENDING,
    updated_at: datetime = NOW,
) -> DocumentRelation:
    resolved = status != RelationStatus.PENDING
    return DocumentRelation(
        id=RELATION_ID,
        owner_id=OWNER_ID,
        notebook_id=NOTEBOOK_ID,
        source_document_id=SOURCE_ID,
        target_document_id=TARGET_ID,
        relation_type=(RelationType.VERSION if resolved else RelationType.VERSION_CANDIDATE),
        status=status,
        confidence=0.91,
        signals={"reason_codes": ["high_content_containment"]},
        reason="same policy family",
        detector_version="knowledge-quality-v2",
        preferred_document_id=SOURCE_ID if resolved else None,
        resolved_by=OWNER_ID if resolved else None,
        resolved_at=NOW if resolved else None,
        created_at=NOW - timedelta(hours=1),
        updated_at=updated_at,
    )


class FakeKnowledgeQualityService:
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
        self.resolve_call: tuple[object, ...] | None = None
        self.revert_call: tuple[object, ...] | None = None
        self.audit_call: tuple[object, ...] | None = None
        self.evidence_call: tuple[object, ...] | None = None

    async def notebook_exists(self, notebook_id: UUID) -> bool:
        return self._notebook_exists and notebook_id == NOTEBOOK_ID

    async def list_relations(
        self,
        notebook_id: UUID,
        *,
        relation_status: RelationStatus | None,
        relation_type: RelationType | None,
        limit: int,
        offset: int,
    ) -> tuple[list[DocumentRelation], int]:
        self.list_call = (
            notebook_id,
            relation_status,
            relation_type,
            limit,
            offset,
        )
        return [make_relation()], 8

    async def resolve_relation(
        self,
        notebook_id: UUID,
        relation_id: UUID,
        action: object,
        expected_updated_at: datetime,
        reason: str | None,
    ) -> DocumentRelation | None:
        self.resolve_call = (
            notebook_id,
            relation_id,
            action,
            expected_updated_at,
            reason,
        )
        if self._stale:
            raise KnowledgeQualityConflictError("stale")
        if self._missing:
            return None
        return make_relation(
            status=RelationStatus.CONFIRMED,
            updated_at=NOW + timedelta(seconds=1),
        )

    async def revert_relation(
        self,
        notebook_id: UUID,
        relation_id: UUID,
        expected_updated_at: datetime,
        reason: str,
    ) -> DocumentRelation | None:
        self.revert_call = (
            notebook_id,
            relation_id,
            expected_updated_at,
            reason,
        )
        if self._stale:
            raise KnowledgeQualityConflictError("stale")
        if self._missing:
            return None
        return make_relation(updated_at=NOW + timedelta(seconds=2))

    async def list_audit_events(
        self,
        notebook_id: UUID,
        *,
        relation_id: UUID | None,
        limit: int,
        offset: int,
    ) -> tuple[list[KnowledgeQualityAudit], int]:
        self.audit_call = (notebook_id, relation_id, limit, offset)
        return [
            KnowledgeQualityAudit(
                id=7,
                owner_id=OWNER_ID,
                notebook_id=NOTEBOOK_ID,
                relation_id=RELATION_ID,
                actor_id=OWNER_ID,
                action="mark_version",
                reason="Checked effective date",
                before_state={"relation": {"status": "pending"}},
                after_state={"relation": {"status": "confirmed"}},
                created_at=NOW,
            )
        ], 1

    async def get_relation_evidence(
        self,
        notebook_id: UUID,
        relation_id: UUID,
    ) -> DocumentRelationEvidence | None:
        self.evidence_call = (notebook_id, relation_id)
        if self._missing:
            return None
        source_chunk = RelationEvidenceChunk(
            id="source-chunk",
            document_id=SOURCE_ID,
            chunk_index=0,
            content="Policy date is 15/03/2027.",
            page_number=1,
            section_title="Policy",
            normalized_content_hash="a" * 64,
            exact_duplicate_group_id="group-1",
        )
        target_chunk = RelationEvidenceChunk(
            id="target-chunk",
            document_id=TARGET_ID,
            chunk_index=0,
            content="Policy date is 15/03/2026.",
            page_number=1,
            section_title="Policy",
            normalized_content_hash="b" * 64,
            exact_duplicate_group_id="group-2",
        )
        return DocumentRelationEvidence(
            relation=make_relation(),
            source_document=RelationEvidenceDocument(
                id=SOURCE_ID,
                original_filename="new.docx",
                quality_status="review_required",
                version_number=1,
                is_current=True,
                canonical_document_id=None,
            ),
            target_document=RelationEvidenceDocument(
                id=TARGET_ID,
                original_filename="old.docx",
                quality_status="clean",
                version_number=1,
                is_current=True,
                canonical_document_id=None,
            ),
            chunk_pairs=(
                RelationEvidenceChunkPair(
                    source_chunk=source_chunk,
                    target_chunk=target_chunk,
                    evidence_type="conflict_candidate",
                    confidence=0.93,
                    signals={"reason_codes": ["date_mismatch"]},
                    reason="date_mismatch",
                ),
            ),
        )


def make_settings() -> Settings:
    return Settings.model_validate(
        {
            "app_env": "test",
            "supabase_url": "https://example.supabase.co",
            "ingestion_worker_enabled": False,
        }
    )


def make_app(service: FakeKnowledgeQualityService) -> FastAPI:
    app = create_app(make_settings())
    app.dependency_overrides[get_current_user] = lambda: CurrentUser(
        id=str(OWNER_ID),
        email="user@example.com",
        role="authenticated",
    )
    app.dependency_overrides[get_knowledge_quality_service] = lambda: service
    return app


def test_lists_filtered_paginated_quality_relations() -> None:
    service = FakeKnowledgeQualityService()
    with TestClient(make_app(service)) as client:
        response = client.get(
            f"/notebooks/{NOTEBOOK_ID}/quality/relations",
            params={
                "status": "pending",
                "relation_type": "version_candidate",
                "limit": 5,
                "offset": 2,
            },
        )

    assert response.status_code == 200
    assert response.json()["total_count"] == 8
    assert response.json()["items"][0]["detector_version"] == "knowledge-quality-v2"
    assert service.list_call == (
        NOTEBOOK_ID,
        RelationStatus.PENDING,
        RelationType.VERSION_CANDIDATE,
        5,
        2,
    )


def test_lists_relation_audit_history() -> None:
    service = FakeKnowledgeQualityService()
    with TestClient(make_app(service)) as client:
        response = client.get(
            f"/notebooks/{NOTEBOOK_ID}/quality/relations/audit",
            params={"relation_id": str(RELATION_ID), "limit": 10},
        )

    assert response.status_code == 200
    assert response.json()["items"][0]["action"] == "mark_version"
    assert response.json()["items"][0]["before_state"]["relation"]["status"] == "pending"
    assert service.audit_call == (NOTEBOOK_ID, RELATION_ID, 10, 0)


def test_gets_relation_evidence_for_reviewer_diff() -> None:
    service = FakeKnowledgeQualityService()
    with TestClient(make_app(service)) as client:
        response = client.get(f"/notebooks/{NOTEBOOK_ID}/quality/relations/{RELATION_ID}/evidence")

    assert response.status_code == 200
    payload = response.json()
    assert payload["source_document"]["original_filename"] == "new.docx"
    assert payload["target_document"]["original_filename"] == "old.docx"
    assert payload["chunk_pairs"][0]["evidence_type"] == "conflict_candidate"
    assert payload["chunk_pairs"][0]["source_chunk"]["content"].endswith("2027.")
    assert payload["source_original_blocks"] == []
    assert payload["target_original_blocks"] == []
    assert service.evidence_call == (NOTEBOOK_ID, RELATION_ID)


def test_resolves_relation_with_optimistic_snapshot_and_reason() -> None:
    service = FakeKnowledgeQualityService()
    with TestClient(make_app(service)) as client:
        response = client.post(
            f"/notebooks/{NOTEBOOK_ID}/quality/relations/{RELATION_ID}/resolve",
            json={
                "action": "mark_version",
                "expected_updated_at": NOW.isoformat(),
                "reason": "Effective date is newer",
            },
        )

    assert response.status_code == 200
    assert response.json()["status"] == "confirmed"
    assert service.resolve_call is not None
    assert service.resolve_call[-1] == "Effective date is newer"


def test_reverts_latest_relation_decision_with_reason() -> None:
    service = FakeKnowledgeQualityService()
    with TestClient(make_app(service)) as client:
        response = client.post(
            f"/notebooks/{NOTEBOOK_ID}/quality/relations/{RELATION_ID}/revert",
            json={
                "expected_updated_at": NOW.isoformat(),
                "reason": "  Wrong document family  ",
            },
        )

    assert response.status_code == 200
    assert response.json()["status"] == "pending"
    assert service.revert_call is not None
    assert service.revert_call[-1] == "Wrong document family"


def test_revert_rejects_blank_reason() -> None:
    service = FakeKnowledgeQualityService()
    with TestClient(make_app(service)) as client:
        response = client.post(
            f"/notebooks/{NOTEBOOK_ID}/quality/relations/{RELATION_ID}/revert",
            json={
                "expected_updated_at": NOW.isoformat(),
                "reason": "   ",
            },
        )

    assert response.status_code == 422
    assert service.revert_call is None


def test_resolution_rejects_missing_or_blank_reason() -> None:
    service = FakeKnowledgeQualityService()
    with TestClient(make_app(service)) as client:
        missing = client.post(
            f"/notebooks/{NOTEBOOK_ID}/quality/relations/{RELATION_ID}/resolve",
            json={
                "action": "dismiss",
                "expected_updated_at": NOW.isoformat(),
            },
        )
        blank = client.post(
            f"/notebooks/{NOTEBOOK_ID}/quality/relations/{RELATION_ID}/resolve",
            json={
                "action": "dismiss",
                "expected_updated_at": NOW.isoformat(),
                "reason": "  ",
            },
        )

    assert missing.status_code == 422
    assert blank.status_code == 422
    assert service.resolve_call is None


def test_stale_resolution_and_reversal_return_conflict() -> None:
    service = FakeKnowledgeQualityService(stale=True)
    with TestClient(make_app(service)) as client:
        resolve_response = client.post(
            f"/notebooks/{NOTEBOOK_ID}/quality/relations/{RELATION_ID}/resolve",
            json={
                "action": "dismiss",
                "expected_updated_at": NOW.isoformat(),
                "reason": "False positive",
            },
        )
        revert_response = client.post(
            f"/notebooks/{NOTEBOOK_ID}/quality/relations/{RELATION_ID}/revert",
            json={
                "expected_updated_at": NOW.isoformat(),
                "reason": "Wrong resolution",
            },
        )

    assert resolve_response.status_code == 409
    assert revert_response.status_code == 409


def test_quality_routes_hide_unowned_notebook() -> None:
    service = FakeKnowledgeQualityService(notebook_exists=False)
    with TestClient(make_app(service)) as client:
        response = client.get(f"/notebooks/{NOTEBOOK_ID}/quality/relations/audit")

    assert response.status_code == 404
    assert service.audit_call is None
