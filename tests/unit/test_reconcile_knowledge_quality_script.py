"""Safety tests for the operator-facing reconciliation command."""

import json
from dataclasses import replace
from pathlib import Path
from tempfile import TemporaryDirectory
from threading import Event
from typing import Any, cast
from uuid import NAMESPACE_URL, uuid5

import pytest

from app.knowledge_quality.application.reconciliation import (
    DatabaseChunkState,
    ReconciliationMismatch,
    ReconciliationReport,
    VectorChunkState,
    reconcile_chunk_inventories,
)
from scripts import reconcile_knowledge_quality as reconciliation_script
from scripts.reconcile_knowledge_quality import (
    _begin_ingestion_maintenance,
    _build_repair_plan,
    _classify_cleanup_batch,
    _delete_orphans,
    _end_ingestion_maintenance,
    _execute_repair_plan,
    _load_existing_chunk_ids,
    _manifest_sha256,
    _renew_ingestion_maintenance,
    _repair_candidates,
    _scan_manifest,
    _write_audit_output,
)


class _Response:
    def __init__(self, payload: object) -> None:
        self._payload = payload

    def raise_for_status(self) -> None:
        return None

    def json(self) -> object:
        return self._payload


class _Client:
    def __init__(self, responses: list[object]) -> None:
        self._responses = iter(responses)
        self.requests: list[tuple[str, dict[str, object]]] = []

    def get(
        self,
        path: str,
        *,
        params: dict[str, object],
    ) -> _Response:
        self.requests.append((path, params))
        return _Response(next(self._responses))

    def post(
        self,
        path: str,
        *,
        json: dict[str, object],
    ) -> _Response:
        self.requests.append((path, json))
        return _Response(next(self._responses))


class _QdrantClient:
    def __init__(self) -> None:
        self.deletes: list[dict[str, object]] = []

    def delete(self, **kwargs: object) -> None:
        self.deletes.append(kwargs)


def _vector(
    point_id: str,
    *,
    generation: str = "generation-a",
) -> VectorChunkState:
    return VectorChunkState(
        id=point_id,
        document_id="document-a",
        owner_id="owner-a",
        notebook_id="notebook-a",
        checksum="checksum-a",
        normalized_content_hash="a" * 64,
        exact_duplicate_group_id="group-a",
        ingestion_generation=generation,
    )


def _database(point_id: str) -> DatabaseChunkState:
    return DatabaseChunkState(
        id=point_id,
        document_id="document-a",
        owner_id="owner-a",
        notebook_id="notebook-a",
        checksum="checksum-a",
        normalized_content_hash="a" * 64,
        exact_duplicate_group_id="group-a",
        ingestion_generation="generation-a",
        embedding_present=True,
    )


def test_maintenance_rpc_contract_acquires_renews_and_releases() -> None:
    client = _Client(["lease-token", True, True])

    token = _begin_ingestion_maintenance(
        cast(Any, client),
        lease_seconds=300,
        reason="verified orphan cleanup",
    )
    _renew_ingestion_maintenance(
        cast(Any, client),
        token=token,
        lease_seconds=300,
    )
    _end_ingestion_maintenance(cast(Any, client), token=token)

    assert token == "lease-token"
    assert [request[0] for request in client.requests] == [
        "/rpc/begin_ingestion_maintenance",
        "/rpc/renew_ingestion_maintenance",
        "/rpc/end_ingestion_maintenance",
    ]
    assert client.requests[0][1]["p_maintenance_owner"]
    assert client.requests[1][1]["p_maintenance_token"] == token
    assert client.requests[2][1]["p_maintenance_token"] == token


def test_cleanup_batch_uses_database_recheck_and_qdrant_payload_cas() -> None:
    snapshot = {
        point_id: _vector(point_id) for point_id in ("stable", "committed", "replaced", "absent")
    }
    current = {
        "stable": snapshot["stable"],
        "committed": snapshot["committed"],
        "replaced": replace(
            snapshot["replaced"],
            ingestion_generation="new-generation",
        ),
    }

    deletable, protected, changed, already_absent = _classify_cleanup_batch(
        tuple(snapshot),
        snapshot_by_id=snapshot,
        current_by_id=current,
        existing_database_ids={"committed"},
    )

    assert deletable == ("stable",)
    assert protected == ("committed",)
    assert changed == ("replaced",)
    assert already_absent == ("absent",)


def test_qdrant_delete_uses_point_and_generation_payload_cas() -> None:
    client = _QdrantClient()

    submitted = _delete_orphans(
        cast(Any, client),
        "chunks",
        (_vector("orphan-a"),),
    )

    assert submitted == ("orphan-a",)
    assert len(client.deletes) == 1
    selector = client.deletes[0]["points_selector"]
    point_filter = selector.filter.should[0]
    conditions = point_filter.must
    assert any(getattr(condition, "has_id", None) == ["orphan-a"] for condition in conditions)
    values = {
        condition.key: condition.match.value
        for condition in conditions
        if getattr(condition, "key", None) is not None
    }
    assert values == {
        "checksum": "checksum-a",
        "document_id": "document-a",
        "ingestion_generation": "generation-a",
        "owner_id": "owner-a",
        "tenant_id": "notebook-a",
    }


def test_qdrant_delete_leaves_point_without_generation_for_manual_review() -> None:
    client = _QdrantClient()

    submitted = _delete_orphans(
        cast(Any, client),
        "chunks",
        (_vector("legacy", generation=""),),
    )

    assert submitted == ()
    assert client.deletes == []


def test_maintenance_heartbeat_renews_independently_of_main_thread(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    renewed = Event()

    def renew(*args: object, **kwargs: object) -> None:
        del args, kwargs
        renewed.set()

    monkeypatch.setattr(
        reconciliation_script,
        "_renew_ingestion_maintenance",
        renew,
    )
    heartbeat = reconciliation_script._MaintenanceHeartbeat(
        base_url="http://localhost",
        headers={},
        token="lease-token",
        lease_seconds=120,
        renewal_interval_seconds=0.01,
    )
    heartbeat.start()
    try:
        assert renewed.wait(timeout=1.0)
    finally:
        heartbeat.close()


def test_maintenance_heartbeat_fails_before_work_if_initial_renewal_fails(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fail_renewal(*args: object, **kwargs: object) -> None:
        del args, kwargs
        raise RuntimeError("lease unavailable")

    monkeypatch.setattr(
        reconciliation_script,
        "_renew_ingestion_maintenance",
        fail_renewal,
    )
    heartbeat = reconciliation_script._MaintenanceHeartbeat(
        base_url="http://localhost",
        headers={},
        token="lease-token",
        lease_seconds=120,
        renewal_interval_seconds=0.01,
    )

    with pytest.raises(RuntimeError, match="lease unavailable"):
        heartbeat.start()


def test_repair_issue_precedence_prefers_mismatch() -> None:
    chunks = (
        _database("missing"),
        _database("unembedded"),
        _database("mismatch"),
    )
    report = ReconciliationReport(
        database_chunk_count=3,
        vector_chunk_count=1,
        missing_vector_ids=("missing",),
        orphan_vector_ids=(),
        database_chunks_without_embedding=("unembedded",),
        mismatches=(
            ReconciliationMismatch(
                chunk_id="mismatch",
                field="checksum",
                database_value="old",
                vector_value="new",
            ),
        ),
    )

    candidates = _repair_candidates(report, chunks)

    assert candidates["document-a"][1] == "mismatch"


def test_repair_plan_can_replay_after_response_loss_while_processing() -> None:
    updated_at = "2026-07-30T00:00:00+00:00"
    database_chunk = _database("missing-vector")
    report = reconcile_chunk_inventories([database_chunk], [])
    client = _Client(
        [
            [
                {
                    "id": "document-a",
                    "owner_id": "owner-a",
                    "notebook_id": "notebook-a",
                    "status": "processing",
                    "is_active": True,
                    "canonical_document_id": None,
                    "updated_at": updated_at,
                }
            ]
        ]
    )

    plan = _build_repair_plan(
        cast(Any, client),
        report=report,
        database_chunks=[database_chunk],
        report_sha256="a" * 64,
        run_id="response-loss-run",
        reason="retry lost response",
    )

    assert plan[0]["expected_updated_at"] == updated_at
    assert plan[0]["issue_kind"] == "missing_vector"


def test_repair_plan_is_manifest_bound_and_response_loss_idempotent() -> None:
    database_chunk = _database("missing-vector")
    report = reconcile_chunk_inventories([database_chunk], [])
    manifest = _scan_manifest(
        report,
        backend="qdrant",
        collection="chunks",
    )
    report_sha256 = _manifest_sha256(manifest)
    client = _Client(
        [
            [
                {
                    "id": "document-a",
                    "owner_id": "owner-a",
                    "notebook_id": "notebook-a",
                    "status": "ready",
                    "is_active": True,
                    "canonical_document_id": None,
                    "updated_at": "2026-07-30T00:00:00+00:00",
                }
            ],
            [{"id": "job-a", "status": "pending"}],
        ]
    )

    plan = _build_repair_plan(
        cast(Any, client),
        report=report,
        database_chunks=[database_chunk],
        report_sha256=report_sha256,
        run_id="run-a",
        reason="restore missing vector",
    )
    queued, failed = _execute_repair_plan(cast(Any, client), plan)

    assert len(plan) == 1
    assert plan[0]["request_key"] == str(
        uuid5(
            NAMESPACE_URL,
            "rag-reconciliation-repair:run-a:document-a",
        )
    )
    assert plan[0]["report_sha256"] == report_sha256
    assert plan[0]["issue_kind"] == "missing_vector"
    assert queued == [
        {
            "document_id": "document-a",
            "request_key": plan[0]["request_key"],
            "job_id": "job-a",
            "status": "pending",
        }
    ]
    assert failed == []
    rpc_body = client.requests[1][1]
    assert rpc_body["p_request_key"] == plan[0]["request_key"]
    assert rpc_body["p_report_sha256"] == report_sha256


def test_failed_repair_attempt_is_not_reported_as_queued() -> None:
    client = _Client(
        [
            [{"id": "failed-job", "status": "failed"}],
            [{"id": "failed-job", "status": "failed"}],
        ]
    )
    plan = [
        {
            "document_id": "document-a",
            "owner_id": "owner-a",
            "notebook_id": "notebook-a",
            "request_key": "request-a",
            "expected_updated_at": "2026-07-30T00:00:00+00:00",
            "report_sha256": "a" * 64,
            "issue_kind": "missing_vector",
            "reason": "retry failed repair",
        }
    ]

    queued, failed = _execute_repair_plan(cast(Any, client), plan)

    assert queued == []
    assert failed[0]["document_id"] == "document-a"
    assert "unusable job status" in failed[0]["error"]


def test_audit_output_is_valid_atomic_json() -> None:
    with TemporaryDirectory(dir=Path.cwd()) as temporary_directory:
        output_path = Path(temporary_directory) / "audit" / "reconciliation.json"
        payload = {
            "state": "planned",
            "scan_manifest_sha256": "a" * 64,
        }

        _write_audit_output(output_path, payload)

        assert json.loads(output_path.read_text(encoding="utf-8")) == payload
        assert list(output_path.parent.glob("*.tmp")) == []


def test_database_recheck_fails_closed_on_malformed_row() -> None:
    client = _Client([[{"wrong": "shape"}]])

    with pytest.raises(TypeError, match="must contain id"):
        _load_existing_chunk_ids(cast(Any, client), ("orphan-a",))
