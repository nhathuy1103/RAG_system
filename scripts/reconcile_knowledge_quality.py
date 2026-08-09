"""Audit Postgres chunk identity against the configured vector backend.

Dry-run is the default. Destructive orphan cleanup acquires a database-backed
maintenance lease, continuously renews it on an independent thread, rechecks
every candidate against Postgres, and uses Qdrant payload CAS before deletion.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import socket
import tempfile
import threading
from collections.abc import Callable, Mapping, Sequence
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from uuid import NAMESPACE_URL, uuid4, uuid5

import httpx2 as httpx

from app.bootstrap.settings import Settings as ApiSettings
from app.knowledge_quality.application.reconciliation import (
    DatabaseChunkState,
    ReconciliationReport,
    VectorChunkState,
    reconcile_chunk_inventories,
)
from app.pipeline.bootstrap.settings import (
    Settings as PipelineSettings,
)
from app.pipeline.bootstrap.settings import (
    get_settings as get_pipeline_settings,
)

CHUNK_SELECT = (
    "id,document_id,owner_id,notebook_id,metadata,"
    "normalized_content_hash,exact_duplicate_group_id"
)


def _arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Reconcile authoritative Postgres chunks and vector points.",
    )
    parser.add_argument(
        "--delete-orphans",
        action="store_true",
        help="Delete only Qdrant point IDs that have no Postgres chunk row.",
    )
    parser.add_argument(
        "--requeue-repairs",
        action="store_true",
        help=(
            "Idempotently enqueue fenced repair attempts for missing or "
            "mismatched vectors from this scan."
        ),
    )
    parser.add_argument(
        "--reason",
        help="Required operator reason for every mutating action.",
    )
    parser.add_argument(
        "--maintenance-lease-seconds",
        type=int,
        default=300,
        help="Database-enforced ingestion pause for cleanup (default: 300).",
    )
    parser.add_argument(
        "--output",
        type=Path,
        help=(
            "Write an atomic JSON audit artifact. Required for every "
            "mutating action."
        ),
    )
    parser.add_argument(
        "--overwrite-output",
        action="store_true",
        help="Explicitly replace an existing audit artifact at --output.",
    )
    parser.add_argument(
        "--page-size",
        type=int,
        default=500,
        help="PostgREST/Qdrant page size (default: 500).",
    )
    return parser.parse_args()


def _load_database_chunks(
    client: httpx.Client,
    *,
    page_size: int,
    heartbeat: Callable[[], None] | None = None,
) -> list[DatabaseChunkState]:
    chunks: list[DatabaseChunkState] = []
    missing_embedding_ids = _load_missing_embedding_ids(
        client,
        page_size=page_size,
        heartbeat=heartbeat,
    )
    offset = 0
    while True:
        if heartbeat is not None:
            heartbeat()
        response = client.get(
            "/document_chunks",
            params={
                "select": CHUNK_SELECT,
                "order": "id.asc",
                "limit": str(page_size),
                "offset": str(offset),
            },
        )
        response.raise_for_status()
        rows = response.json()
        if not isinstance(rows, list):
            raise TypeError("PostgREST document_chunks response must be an array")
        for row in rows:
            chunks.append(
                _parse_database_chunk(
                    row,
                    missing_embedding_ids=missing_embedding_ids,
                )
            )
        if len(rows) < page_size:
            break
        offset += len(rows)
    return chunks


def _load_missing_embedding_ids(
    client: httpx.Client,
    *,
    page_size: int,
    heartbeat: Callable[[], None] | None = None,
) -> set[str]:
    missing: set[str] = set()
    offset = 0
    while True:
        if heartbeat is not None:
            heartbeat()
        response = client.get(
            "/document_chunks",
            params={
                "select": "id",
                "embedding": "is.null",
                "order": "id.asc",
                "limit": str(page_size),
                "offset": str(offset),
            },
        )
        response.raise_for_status()
        rows = response.json()
        if not isinstance(rows, list):
            raise TypeError("PostgREST missing-embedding response must be an array")
        missing.update(str(row["id"]) for row in rows if isinstance(row, Mapping))
        if len(rows) < page_size:
            break
        offset += len(rows)
    return missing


def _parse_database_chunk(
    row: object,
    *,
    missing_embedding_ids: set[str],
) -> DatabaseChunkState:
    if not isinstance(row, Mapping):
        raise TypeError("Postgres chunk row must be an object")
    metadata = row.get("metadata")
    if not isinstance(metadata, Mapping):
        metadata = {}
    return DatabaseChunkState(
        id=str(row["id"]),
        document_id=str(row["document_id"]),
        owner_id=str(row["owner_id"]),
        notebook_id=str(row["notebook_id"]),
        checksum=str(metadata.get("checksum") or ""),
        normalized_content_hash=str(row.get("normalized_content_hash") or ""),
        exact_duplicate_group_id=str(row.get("exact_duplicate_group_id") or ""),
        ingestion_generation=str(metadata.get("ingestion_generation") or ""),
        embedding_present=str(row["id"]) not in missing_embedding_ids,
    )


def _qdrant_client(settings: PipelineSettings) -> Any:
    from qdrant_client import QdrantClient

    kwargs: dict[str, Any] = {"timeout": settings.qdrant_timeout_seconds}
    if settings.qdrant_location:
        kwargs["location"] = settings.qdrant_location
    else:
        kwargs["url"] = settings.qdrant_url or "http://localhost"
        kwargs["port"] = settings.qdrant_port
        if settings.qdrant_api_key:
            kwargs["api_key"] = settings.qdrant_api_key
    return QdrantClient(**kwargs)


def _load_qdrant_chunks(
    client: Any,
    collection_name: str,
    *,
    page_size: int,
    heartbeat: Callable[[], None] | None = None,
) -> list[VectorChunkState]:
    if not client.collection_exists(collection_name):
        return []
    chunks: list[VectorChunkState] = []
    offset: object | None = None
    while True:
        if heartbeat is not None:
            heartbeat()
        points, next_offset = client.scroll(
            collection_name=collection_name,
            limit=page_size,
            offset=offset,
            with_payload=True,
            with_vectors=False,
        )
        chunks.extend(_parse_vector_chunk(point) for point in points)
        if next_offset is None:
            break
        offset = next_offset
    return chunks


def _parse_vector_chunk(point: Any) -> VectorChunkState:
    payload = getattr(point, "payload", None)
    if not isinstance(payload, Mapping):
        payload = {}
    return VectorChunkState(
        id=str(point.id),
        document_id=str(payload.get("document_id") or ""),
        owner_id=str(payload.get("owner_id") or ""),
        notebook_id=str(payload.get("tenant_id") or ""),
        checksum=str(payload.get("checksum") or ""),
        normalized_content_hash=str(
            payload.get("normalized_content_hash") or ""
        ),
        exact_duplicate_group_id=str(
            payload.get("exact_duplicate_group_id") or ""
        ),
        ingestion_generation=str(payload.get("ingestion_generation") or ""),
    )


def _as_pgvector_inventory(
    database_chunks: Sequence[DatabaseChunkState],
) -> list[VectorChunkState]:
    return [
        VectorChunkState(
            id=chunk.id,
            document_id=chunk.document_id,
            owner_id=chunk.owner_id,
            notebook_id=chunk.notebook_id,
            checksum=chunk.checksum,
            normalized_content_hash=chunk.normalized_content_hash,
            exact_duplicate_group_id=chunk.exact_duplicate_group_id,
            ingestion_generation=chunk.ingestion_generation,
        )
        for chunk in database_chunks
    ]


def _delete_orphans(
    client: Any,
    collection_name: str,
    points: Sequence[VectorChunkState],
) -> tuple[str, ...]:
    """Delete only points whose identity payload still matches the scan.

    The maintenance lease prevents new workers from starting, while this
    Qdrant-side compare-and-delete closes the remaining race if the lease is
    lost during a blocking network call. Legacy points without enough identity
    evidence are deliberately left for manual review.
    """
    if not points:
        return ()
    from qdrant_client.http import models

    eligible = tuple(
        point
        for point in points
        if point.id
        and point.document_id
        and point.owner_id
        and point.notebook_id
        and point.checksum
        and point.ingestion_generation
    )
    if not eligible:
        return ()
    point_filters: list[models.Condition] = [
        models.Filter(
            must=[
                models.HasIdCondition(has_id=[point.id]),
                models.FieldCondition(
                    key="document_id",
                    match=models.MatchValue(value=point.document_id),
                ),
                models.FieldCondition(
                    key="owner_id",
                    match=models.MatchValue(value=point.owner_id),
                ),
                models.FieldCondition(
                    key="tenant_id",
                    match=models.MatchValue(value=point.notebook_id),
                ),
                models.FieldCondition(
                    key="checksum",
                    match=models.MatchValue(value=point.checksum),
                ),
                models.FieldCondition(
                    key="ingestion_generation",
                    match=models.MatchValue(
                        value=point.ingestion_generation,
                    ),
                ),
            ]
        )
        for point in eligible
    ]
    client.delete(
        collection_name=collection_name,
        points_selector=models.FilterSelector(
            filter=models.Filter(should=point_filters),
        ),
        wait=True,
    )
    return tuple(point.id for point in eligible)


def _begin_ingestion_maintenance(
    client: httpx.Client,
    *,
    lease_seconds: int,
    reason: str,
) -> str:
    response = client.post(
        "/rpc/begin_ingestion_maintenance",
        json={
            "p_maintenance_owner": f"{socket.gethostname()}:{os.getpid()}",
            "p_lease_seconds": lease_seconds,
            "p_reason": reason,
        },
    )
    response.raise_for_status()
    token = response.json()
    if not isinstance(token, str) or not token.strip():
        raise TypeError("Maintenance RPC did not return a lease token")
    return token


def _renew_ingestion_maintenance(
    client: httpx.Client,
    *,
    token: str,
    lease_seconds: int,
) -> None:
    response = client.post(
        "/rpc/renew_ingestion_maintenance",
        json={
            "p_maintenance_token": token,
            "p_lease_seconds": lease_seconds,
        },
    )
    response.raise_for_status()
    if response.json() is not True:
        raise RuntimeError("Ingestion maintenance lease was lost")


def _end_ingestion_maintenance(
    client: httpx.Client,
    *,
    token: str,
) -> None:
    response = client.post(
        "/rpc/end_ingestion_maintenance",
        json={"p_maintenance_token": token},
    )
    response.raise_for_status()
    if response.json() is not True:
        raise RuntimeError("Ingestion maintenance lease could not be released")


class _MaintenanceHeartbeat:
    """Renew a DB maintenance lease independently from blocking I/O."""

    def __init__(
        self,
        *,
        base_url: str,
        headers: Mapping[str, str],
        token: str,
        lease_seconds: int,
        renewal_interval_seconds: float | None = None,
    ) -> None:
        self._base_url = base_url
        self._headers = dict(headers)
        self._token = token
        self._lease_seconds = lease_seconds
        self._renewal_interval_seconds = (
            renewal_interval_seconds
            if renewal_interval_seconds is not None
            else max(10.0, lease_seconds / 4)
        )
        if self._renewal_interval_seconds <= 0:
            raise ValueError("Maintenance renewal interval must be positive")
        self._stop = threading.Event()
        self._started = threading.Event()
        self._failure: BaseException | None = None
        self._thread = threading.Thread(
            target=self._run,
            name="ingestion-maintenance-heartbeat",
            daemon=True,
        )

    def start(self) -> None:
        self._thread.start()
        startup_timeout = min(30.0, self._lease_seconds / 4) + 1.0
        if not self._started.wait(timeout=startup_timeout):
            self._failure = TimeoutError(
                "Maintenance heartbeat did not complete its initial renewal"
            )
        self.check()

    def check(self) -> None:
        if self._failure is not None:
            raise RuntimeError(
                f"Ingestion maintenance heartbeat failed: {self._failure}"
            ) from self._failure

    def close(self) -> None:
        self._stop.set()
        self._thread.join(timeout=30.0)
        if self._thread.is_alive():
            raise RuntimeError("Maintenance heartbeat did not stop")
        self.check()

    def _run(self) -> None:
        try:
            with httpx.Client(
                base_url=self._base_url,
                headers=self._headers,
                timeout=min(30.0, self._lease_seconds / 4),
            ) as client:
                # Prove the independent renewal channel is healthy before the
                # caller is allowed to begin any blocking vector operation.
                _renew_ingestion_maintenance(
                    client,
                    token=self._token,
                    lease_seconds=self._lease_seconds,
                )
                self._started.set()
                while not self._stop.wait(self._renewal_interval_seconds):
                    _renew_ingestion_maintenance(
                        client,
                        token=self._token,
                        lease_seconds=self._lease_seconds,
                    )
        except BaseException as exc:
            self._failure = exc
            self._started.set()


def _maintenance_heartbeat(
    *,
    base_url: str,
    headers: Mapping[str, str],
    token: str,
    lease_seconds: int,
) -> _MaintenanceHeartbeat:
    heartbeat = _MaintenanceHeartbeat(
        base_url=base_url,
        headers=headers,
        token=token,
        lease_seconds=lease_seconds,
    )
    heartbeat.start()
    return heartbeat


def _load_qdrant_chunks_by_id(
    client: Any,
    collection_name: str,
    point_ids: Sequence[str],
) -> dict[str, VectorChunkState]:
    if not point_ids:
        return {}
    points = client.retrieve(
        collection_name=collection_name,
        ids=list(point_ids),
        with_payload=True,
        with_vectors=False,
    )
    return {
        chunk.id: chunk
        for chunk in (_parse_vector_chunk(point) for point in points)
    }


def _load_existing_chunk_ids(
    client: httpx.Client,
    candidate_ids: Sequence[str],
    *,
    batch_size: int = 100,
    heartbeat: Callable[[], None] | None = None,
) -> set[str]:
    existing: set[str] = set()
    for offset in range(0, len(candidate_ids), batch_size):
        if heartbeat is not None:
            heartbeat()
        batch = candidate_ids[offset : offset + batch_size]
        response = client.get(
            "/document_chunks",
            params={
                "select": "id",
                "id": f"in.({','.join(batch)})",
            },
        )
        response.raise_for_status()
        rows = response.json()
        if not isinstance(rows, list):
            raise TypeError("PostgREST chunk recheck response must be an array")
        for row in rows:
            if not isinstance(row, Mapping) or "id" not in row:
                raise TypeError("PostgREST chunk recheck row must contain id")
            existing.add(str(row["id"]))
    return existing


def _classify_cleanup_batch(
    point_ids: Sequence[str],
    *,
    snapshot_by_id: Mapping[str, VectorChunkState],
    current_by_id: Mapping[str, VectorChunkState],
    existing_database_ids: set[str],
) -> tuple[tuple[str, ...], tuple[str, ...], tuple[str, ...], tuple[str, ...]]:
    """Apply DB-presence and Qdrant payload CAS checks to one manifest batch."""
    deletable: list[str] = []
    protected: list[str] = []
    changed: list[str] = []
    already_absent: list[str] = []
    for point_id in point_ids:
        if point_id in existing_database_ids:
            protected.append(point_id)
            continue
        current = current_by_id.get(point_id)
        if current is None:
            already_absent.append(point_id)
            continue
        if current != snapshot_by_id[point_id]:
            changed.append(point_id)
            continue
        deletable.append(point_id)
    return (
        tuple(deletable),
        tuple(protected),
        tuple(changed),
        tuple(already_absent),
    )


def _scan_manifest(
    report: ReconciliationReport,
    *,
    backend: str,
    collection: str | None,
) -> dict[str, object]:
    return {
        "schema_version": "knowledge-quality-reconciliation-v1",
        "backend": backend,
        "collection": collection,
        "report": report.to_dict(),
    }


def _manifest_sha256(manifest: Mapping[str, object]) -> str:
    canonical = json.dumps(
        manifest,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    return hashlib.sha256(canonical).hexdigest()


def _write_audit_output(path: Path, payload: Mapping[str, object]) -> None:
    """Atomically persist a planned or completed operator action."""
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary_path: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            "w",
            encoding="utf-8",
            dir=path.parent,
            prefix=f".{path.name}.",
            suffix=".tmp",
            delete=False,
        ) as handle:
            temporary_path = Path(handle.name)
            json.dump(
                payload,
                handle,
                ensure_ascii=False,
                indent=2,
                sort_keys=True,
            )
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary_path, path)
        temporary_path = None
    finally:
        if temporary_path is not None:
            temporary_path.unlink(missing_ok=True)


def _repair_candidates(
    report: ReconciliationReport,
    database_chunks: Sequence[DatabaseChunkState],
) -> dict[str, tuple[DatabaseChunkState, str]]:
    chunks_by_id = {chunk.id: chunk for chunk in database_chunks}
    priority = {
        "missing_embedding": 1,
        "missing_vector": 2,
        "mismatch": 3,
    }
    candidates: dict[str, tuple[DatabaseChunkState, str]] = {}

    def add(chunk_id: str, issue_kind: str) -> None:
        chunk = chunks_by_id.get(chunk_id)
        if chunk is None:
            return
        current = candidates.get(chunk.document_id)
        if current is None or priority[issue_kind] > priority[current[1]]:
            candidates[chunk.document_id] = (chunk, issue_kind)

    for chunk_id in report.missing_vector_ids:
        add(chunk_id, "missing_vector")
    for mismatch in report.mismatches:
        add(mismatch.chunk_id, "mismatch")
    for chunk_id in report.database_chunks_without_embedding:
        add(chunk_id, "missing_embedding")
    return candidates


def _load_repair_documents(
    client: httpx.Client,
    document_ids: Sequence[str],
    *,
    batch_size: int = 100,
) -> dict[str, Mapping[str, object]]:
    documents: dict[str, Mapping[str, object]] = {}
    for offset in range(0, len(document_ids), batch_size):
        batch = document_ids[offset : offset + batch_size]
        response = client.get(
            "/documents",
            params={
                "select": (
                    "id,owner_id,notebook_id,status,is_active,"
                    "canonical_document_id,updated_at"
                ),
                "id": f"in.({','.join(batch)})",
            },
        )
        response.raise_for_status()
        rows = response.json()
        if not isinstance(rows, list):
            raise TypeError("PostgREST repair documents response must be an array")
        for row in rows:
            if not isinstance(row, Mapping) or "id" not in row:
                raise TypeError("PostgREST repair document row is invalid")
            documents[str(row["id"])] = row
    return documents


def _build_repair_plan(
    client: httpx.Client,
    *,
    report: ReconciliationReport,
    database_chunks: Sequence[DatabaseChunkState],
    report_sha256: str,
    run_id: str,
    reason: str,
) -> list[dict[str, str]]:
    candidates = _repair_candidates(report, database_chunks)
    document_ids = tuple(sorted(candidates))
    documents = _load_repair_documents(client, document_ids)
    if set(documents) != set(document_ids):
        missing = sorted(set(document_ids) - set(documents))
        raise RuntimeError(f"Repair documents disappeared: {missing}")

    plan: list[dict[str, str]] = []
    for document_id in document_ids:
        chunk, issue_kind = candidates[document_id]
        row = documents[document_id]
        if (
            row.get("status") not in {"ready", "failed", "processing"}
            or row.get("is_active") is not True
            or row.get("canonical_document_id") is not None
        ):
            raise RuntimeError(
                f"Document {document_id} is not an active repairable canonical"
            )
        if (
            str(row.get("owner_id")) != chunk.owner_id
            or str(row.get("notebook_id")) != chunk.notebook_id
        ):
            raise RuntimeError(
                f"Document {document_id} changed permission scope"
            )
        request_key = uuid5(
            NAMESPACE_URL,
            f"rag-reconciliation-repair:{run_id}:{document_id}",
        )
        plan.append(
            {
                "document_id": document_id,
                "owner_id": chunk.owner_id,
                "notebook_id": chunk.notebook_id,
                "request_key": str(request_key),
                "expected_updated_at": str(row["updated_at"]),
                "report_sha256": report_sha256,
                "issue_kind": issue_kind,
                "reason": reason,
            }
        )
    return plan


def _execute_repair_plan(
    client: httpx.Client,
    plan: Sequence[Mapping[str, str]],
) -> tuple[list[dict[str, str]], list[dict[str, str]]]:
    queued: list[dict[str, str]] = []
    failed: list[dict[str, str]] = []
    for item in plan:
        body = {
            "p_document_id": item["document_id"],
            "p_owner_id": item["owner_id"],
            "p_notebook_id": item["notebook_id"],
            "p_request_key": item["request_key"],
            "p_expected_updated_at": item["expected_updated_at"],
            "p_report_sha256": item["report_sha256"],
            "p_issue_kind": item["issue_kind"],
            "p_reason": item["reason"],
        }
        last_error: BaseException | None = None
        for _attempt in range(2):
            try:
                response = client.post(
                    "/rpc/requeue_document_ingestion_repair",
                    json=body,
                )
                response.raise_for_status()
                rows = response.json()
                if (
                    not isinstance(rows, list)
                    or len(rows) != 1
                    or not isinstance(rows[0], Mapping)
                ):
                    raise TypeError(
                        "Repair RPC must return exactly one ingestion job"
                    )
                status = str(rows[0]["status"])
                if status not in {"pending", "running", "succeeded"}:
                    raise TypeError(
                        f"Repair RPC returned unusable job status {status!r}"
                    )
                queued.append(
                    {
                        "document_id": item["document_id"],
                        "request_key": item["request_key"],
                        "job_id": str(rows[0]["id"]),
                        "status": status,
                    }
                )
                last_error = None
                break
            except (httpx.HTTPError, OSError, KeyError, TypeError) as exc:
                last_error = exc
        if last_error is not None:
            failed.append(
                {
                    "document_id": item["document_id"],
                    "request_key": item["request_key"],
                    "error": str(last_error),
                }
            )
    return queued, failed


def main() -> int:
    args = _arguments()
    if args.page_size <= 0 or args.page_size > 10_000:
        raise SystemExit("--page-size must be between 1 and 10000")
    if not 120 <= args.maintenance_lease_seconds <= 3600:
        raise SystemExit(
            "--maintenance-lease-seconds must be between 120 and 3600"
        )
    if args.delete_orphans and args.requeue_repairs:
        raise SystemExit(
            "--delete-orphans and --requeue-repairs must run separately"
        )
    mutating = args.delete_orphans or args.requeue_repairs
    if mutating and (
        args.reason is None or not args.reason.strip()
    ):
        raise SystemExit("Mutating actions require a non-blank --reason")
    if mutating and args.output is None:
        raise SystemExit("Mutating actions require --output for an audit artifact")
    if (
        args.output is not None
        and args.output.exists()
        and not args.overwrite_output
    ):
        raise SystemExit(
            "--output already exists; use a new path or --overwrite-output"
        )

    api_settings = ApiSettings()
    pipeline_settings = get_pipeline_settings()
    if api_settings.supabase_rest_url is None:
        raise SystemExit("SUPABASE_URL is required")
    if api_settings.supabase_service_role_key is None:
        raise SystemExit("SUPABASE_SERVICE_ROLE_KEY is required")
    service_key = (
        api_settings.supabase_service_role_key.get_secret_value().strip()
    )
    if not service_key:
        raise SystemExit("SUPABASE_SERVICE_ROLE_KEY is empty")

    headers = {
        "apikey": service_key,
        "Authorization": f"Bearer {service_key}",
    }
    with httpx.Client(
        base_url=api_settings.supabase_rest_url,
        headers=headers,
        timeout=30.0,
    ) as database_client:
        database_chunks = _load_database_chunks(
            database_client,
            page_size=args.page_size,
        )

    qdrant_client = None
    if pipeline_settings.vector_store_backend == "qdrant":
        qdrant_client = _qdrant_client(pipeline_settings)
        vector_chunks = _load_qdrant_chunks(
            qdrant_client,
            pipeline_settings.qdrant_collection,
            page_size=args.page_size,
        )
    elif pipeline_settings.vector_store_backend == "pgvector":
        vector_chunks = _as_pgvector_inventory(database_chunks)
    else:
        raise SystemExit(
            "Reconciliation supports VECTOR_STORE_BACKEND=qdrant or pgvector"
        )

    report = reconcile_chunk_inventories(database_chunks, vector_chunks)
    collection_name = (
        pipeline_settings.qdrant_collection
        if pipeline_settings.vector_store_backend == "qdrant"
        else None
    )
    scan_manifest = _scan_manifest(
        report,
        backend=pipeline_settings.vector_store_backend,
        collection=collection_name,
    )
    scan_manifest_sha256 = _manifest_sha256(scan_manifest)
    run_id = str(uuid4())
    audit_started_at = datetime.now(UTC).isoformat()
    audit_artifact: dict[str, object] = {
        "schema_version": "knowledge-quality-reconciliation-run-v1",
        "state": "dry_run",
        "started_at": audit_started_at,
        "run_id": run_id,
        "action": "scan",
        "reason": args.reason.strip() if args.reason else None,
        "scan_manifest_sha256": scan_manifest_sha256,
        "scan_manifest": scan_manifest,
    }
    deleted_orphan_ids: tuple[str, ...] = ()
    protected_orphan_ids: tuple[str, ...] = ()
    changed_orphan_ids: tuple[str, ...] = ()
    already_absent_orphan_ids: tuple[str, ...] = ()
    queued_repairs: list[dict[str, str]] = []
    failed_repairs: list[dict[str, str]] = []

    if args.requeue_repairs:
        with httpx.Client(
            base_url=api_settings.supabase_rest_url,
            headers=headers,
            timeout=30.0,
        ) as database_client:
            try:
                repair_plan = _build_repair_plan(
                    database_client,
                    report=report,
                    database_chunks=database_chunks,
                    report_sha256=scan_manifest_sha256,
                    run_id=run_id,
                    reason=args.reason.strip(),
                )
                audit_artifact.update(
                    {
                        "state": "planned",
                        "action": "requeue_repairs",
                        "plan": repair_plan,
                    }
                )
                _write_audit_output(args.output, audit_artifact)
                queued_repairs, failed_repairs = _execute_repair_plan(
                    database_client,
                    repair_plan,
                )
            except (httpx.HTTPError, RuntimeError, TypeError) as exc:
                raise SystemExit(f"Repair requeue failed safely: {exc}") from exc

    if args.delete_orphans:
        if qdrant_client is None:
            raise SystemExit("--delete-orphans is only valid for Qdrant")
        with httpx.Client(
            base_url=api_settings.supabase_rest_url,
            headers=headers,
            timeout=30.0,
        ) as database_client:
            maintenance_token: str | None = None
            lease_heartbeat: _MaintenanceHeartbeat | None = None
            try:
                maintenance_token = _begin_ingestion_maintenance(
                    database_client,
                    lease_seconds=args.maintenance_lease_seconds,
                    reason=args.reason.strip(),
                )
                lease_heartbeat = _maintenance_heartbeat(
                    base_url=str(api_settings.supabase_rest_url),
                    headers=headers,
                    token=maintenance_token,
                    lease_seconds=args.maintenance_lease_seconds,
                )

                # The pre-maintenance snapshot is informational only. Build
                # the immutable deletion manifest after the DB gate is held.
                database_chunks = _load_database_chunks(
                    database_client,
                    page_size=args.page_size,
                    heartbeat=lease_heartbeat.check,
                )
                vector_chunks = _load_qdrant_chunks(
                    qdrant_client,
                    pipeline_settings.qdrant_collection,
                    page_size=args.page_size,
                    heartbeat=lease_heartbeat.check,
                )
                report = reconcile_chunk_inventories(
                    database_chunks,
                    vector_chunks,
                )
                scan_manifest = _scan_manifest(
                    report,
                    backend=pipeline_settings.vector_store_backend,
                    collection=collection_name,
                )
                scan_manifest_sha256 = _manifest_sha256(scan_manifest)
                vector_by_id = {chunk.id: chunk for chunk in vector_chunks}
                manifest_ids = report.orphan_vector_ids
                audit_artifact.update(
                    {
                        "state": "planned",
                        "action": "delete_orphans",
                        "scan_manifest_sha256": scan_manifest_sha256,
                        "scan_manifest": scan_manifest,
                        "plan": {
                            "orphan_point_ids": list(manifest_ids),
                        },
                    }
                )
                _write_audit_output(args.output, audit_artifact)
                deleted: list[str] = []
                protected: list[str] = []
                changed: list[str] = []
                already_absent: list[str] = []

                for offset in range(0, len(manifest_ids), args.page_size):
                    lease_heartbeat.check()
                    batch_ids = manifest_ids[
                        offset : offset + args.page_size
                    ]
                    existing_ids = _load_existing_chunk_ids(
                        database_client,
                        batch_ids,
                        heartbeat=lease_heartbeat.check,
                    )
                    current_by_id = _load_qdrant_chunks_by_id(
                        qdrant_client,
                        pipeline_settings.qdrant_collection,
                        batch_ids,
                    )
                    (
                        deletable,
                        protected_batch,
                        changed_batch,
                        absent_batch,
                    ) = _classify_cleanup_batch(
                        batch_ids,
                        snapshot_by_id=vector_by_id,
                        current_by_id=current_by_id,
                        existing_database_ids=existing_ids,
                    )
                    lease_heartbeat.check()
                    submitted_ids = _delete_orphans(
                        qdrant_client,
                        pipeline_settings.qdrant_collection,
                        tuple(vector_by_id[point_id] for point_id in deletable),
                    )
                    lease_heartbeat.check()
                    after_delete_by_id = _load_qdrant_chunks_by_id(
                        qdrant_client,
                        pipeline_settings.qdrant_collection,
                        submitted_ids,
                    )
                    for point_id in submitted_ids:
                        current = after_delete_by_id.get(point_id)
                        if current is None:
                            deleted.append(point_id)
                        elif current != vector_by_id[point_id]:
                            changed.append(point_id)
                        else:
                            raise RuntimeError(
                                "Qdrant compare-and-delete left an unchanged "
                                f"orphan point: {point_id}"
                            )
                    submitted = set(submitted_ids)
                    changed.extend(
                        point_id
                        for point_id in deletable
                        if point_id not in submitted
                    )
                    protected.extend(protected_batch)
                    changed.extend(changed_batch)
                    already_absent.extend(absent_batch)

                deleted_orphan_ids = tuple(deleted)
                protected_orphan_ids = tuple(protected)
                changed_orphan_ids = tuple(changed)
                already_absent_orphan_ids = tuple(already_absent)

                lease_heartbeat.check()
                database_chunks = _load_database_chunks(
                    database_client,
                    page_size=args.page_size,
                    heartbeat=lease_heartbeat.check,
                )
                vector_chunks = _load_qdrant_chunks(
                    qdrant_client,
                    pipeline_settings.qdrant_collection,
                    page_size=args.page_size,
                    heartbeat=lease_heartbeat.check,
                )
                report = reconcile_chunk_inventories(
                    database_chunks,
                    vector_chunks,
                )
            except (httpx.HTTPError, RuntimeError, TypeError) as exc:
                raise SystemExit(
                    f"Orphan deletion safety check failed: {exc}"
                ) from exc
            finally:
                if maintenance_token is not None:
                    try:
                        if lease_heartbeat is not None:
                            lease_heartbeat.close()
                    except (httpx.HTTPError, RuntimeError, TypeError) as exc:
                        raise SystemExit(
                            f"Could not stop maintenance heartbeat: {exc}"
                        ) from exc
                    finally:
                        try:
                            _end_ingestion_maintenance(
                                database_client,
                                token=maintenance_token,
                            )
                        except (
                            httpx.HTTPError,
                            RuntimeError,
                            TypeError,
                        ) as exc:
                            raise SystemExit(
                                "Could not release ingestion maintenance: "
                                f"{exc}"
                            ) from exc

    output = report.to_dict()
    output["backend"] = pipeline_settings.vector_store_backend
    output["collection"] = collection_name
    output["scan_manifest_sha256"] = scan_manifest_sha256
    output["deleted_orphan_ids"] = list(deleted_orphan_ids)
    output["protected_orphan_ids"] = list(protected_orphan_ids)
    output["changed_orphan_ids"] = list(changed_orphan_ids)
    output["already_absent_orphan_ids"] = list(
        already_absent_orphan_ids
    )
    output["queued_repairs"] = queued_repairs
    output["failed_repairs"] = failed_repairs
    if args.output is not None:
        audit_artifact.update(
            {
                "state": (
                    "partial_failure"
                    if failed_repairs
                    else "completed"
                    if mutating
                    else "dry_run"
                ),
                "completed_at": datetime.now(UTC).isoformat(),
                "result": output,
            }
        )
        _write_audit_output(args.output, audit_artifact)
    print(json.dumps(output, ensure_ascii=False, indent=2, sort_keys=True))
    if args.requeue_repairs:
        return 1 if failed_repairs else 0
    return 0 if report.healthy else 1


if __name__ == "__main__":
    raise SystemExit(main())
