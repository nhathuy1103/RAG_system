"""Supabase PostgREST adapter for ingestion enqueueing and worker leases."""

import json
import logging
from collections.abc import Mapping, Sequence
from hashlib import sha256
from typing import Literal, cast
from uuid import UUID

import httpx2 as httpx

from app.documents.adapters.postgrest_repository import (
    PostgrestDocumentRepository,
)
from app.documents.domain.models import Document
from app.ingestion.domain.models import (
    ClaimedIngestionJob,
    IngestionProfile,
    PersistedChunk,
    ProcessingFailure,
    ProcessingJobType,
    ProcessingStage,
    ProcessingStageStatus,
    QueuedProcessingJob,
)
from app.ingestion.ports.repositories import (
    EnterpriseProcessingQueue,
    IngestionCompletionDisposition,
    IngestionRepository,
    IngestionRepositoryError,
    IngestionWorkerRepository,
    ProcessingProgressReporter,
)
from app.knowledge_quality.application.analysis import is_auto_identity_eligible
from app.knowledge_quality.application.scope import extract_claim_scope, merge_claim_scopes
from app.knowledge_quality.domain.models import (
    ChunkDedupCandidate,
    ChunkDedupProbe,
    ClaimScope,
    DocumentFingerprint,
    QualityRelationCandidate,
)

LOGGER = logging.getLogger(__name__)
_CHUNK_CANDIDATE_BATCH_SIZE = 128


class PostgrestIngestionRepository(
    IngestionRepository,
    IngestionWorkerRepository,
    ProcessingProgressReporter,
    EnterpriseProcessingQueue,
):
    """Call transactional ingestion RPCs through a user or service-role client."""

    def __init__(
        self,
        client: httpx.AsyncClient,
        *,
        enterprise_queue_enabled: bool = False,
    ) -> None:
        self._client = client
        self._enterprise_queue_enabled = enterprise_queue_enabled
        self._enterprise_claims: set[UUID] = set()
        self._enterprise_stages: dict[UUID, ProcessingStage] = {}

    async def enqueue(
        self,
        document_id: UUID,
        notebook_id: UUID,
        profile: IngestionProfile,
    ) -> Document:
        payload = await self._rpc(
            "enqueue_document_ingestion",
            {
                "p_document_id": str(document_id),
                "p_notebook_id": str(notebook_id),
                "p_embedding_model": profile.embedding_model,
                "p_embedding_dimensions": profile.embedding_dimensions,
                "p_configuration": profile.configuration,
            },
        )
        try:
            if not isinstance(payload, list) or len(payload) != 1:
                raise TypeError("Enqueue response must contain exactly one document")
            return PostgrestDocumentRepository._parse_document(payload[0])
        except (KeyError, TypeError, ValueError) as exc:
            raise IngestionRepositoryError("Failed to parse enqueued document metadata") from exc

    async def claim(
        self,
        worker_id: str,
        lease_seconds: int,
    ) -> ClaimedIngestionJob | None:
        if self._enterprise_queue_enabled:
            enterprise_job = await self._claim_enterprise(worker_id, lease_seconds)
            if enterprise_job is not None:
                self._enterprise_claims.add(enterprise_job.id)
                return enterprise_job
        payload = await self._rpc(
            "claim_ingestion_job",
            {
                "p_worker_id": worker_id,
                "p_lease_seconds": lease_seconds,
            },
        )
        try:
            if not isinstance(payload, list):
                raise TypeError("Claim response must be an array")
            if not payload:
                return None
            if len(payload) != 1 or not isinstance(payload[0], Mapping):
                raise TypeError("Claim response must contain at most one job")
            row = payload[0]
            configuration = row["configuration"]
            if not isinstance(configuration, Mapping):
                raise TypeError("Job configuration must be an object")
            return ClaimedIngestionJob(
                id=UUID(str(row["id"])),
                owner_id=UUID(str(row["owner_id"])),
                notebook_id=UUID(str(row["notebook_id"])),
                document_id=UUID(str(row["document_id"])),
                attempt_number=int(row["attempt_number"]),
                configuration=dict(configuration),
                storage_bucket=str(row["storage_bucket"]),
                storage_object_path=str(row["storage_object_path"]),
                original_filename=str(row["original_filename"]),
                mime_type=str(row["mime_type"]),
                size_bytes=int(row["size_bytes"]),
                content_hash=(
                    str(row["content_hash"]) if row["content_hash"] is not None else None
                ),
                claim_token=UUID(str(row["claim_token"])),
                document_version=int(row.get("document_version") or 1),
            )
        except (KeyError, TypeError, ValueError) as exc:
            raise IngestionRepositoryError("Failed to parse claimed job") from exc

    async def renew_lease(
        self,
        job_id: UUID,
        worker_id: str,
        claim_token: UUID,
        lease_seconds: int,
    ) -> bool:
        if job_id in self._enterprise_claims:
            payload = await self._rpc(
                "renew_processing_job_lease",
                {
                    "p_job_id": str(job_id),
                    "p_worker_id": worker_id,
                    "p_claim_token": str(claim_token),
                    "p_lease_seconds": lease_seconds,
                },
            )
            if not isinstance(payload, bool):
                raise IngestionRepositoryError(
                    "Enterprise lease renewal response must be boolean"
                )
            return payload
        payload = await self._rpc(
            "renew_ingestion_job_lease",
            {
                "p_job_id": str(job_id),
                "p_worker_id": worker_id,
                "p_claim_token": str(claim_token),
                "p_lease_seconds": lease_seconds,
            },
        )
        if not isinstance(payload, bool):
            raise IngestionRepositoryError("Lease renewal response must be boolean")
        return payload

    async def complete(
        self,
        job: ClaimedIngestionJob,
        worker_id: str,
        chunks: Sequence[PersistedChunk],
        embedding_model: str,
        embedding_dimensions: int,
        fingerprint: DocumentFingerprint | None = None,
        relations: Sequence[QualityRelationCandidate] = (),
        effective_quality_mode: Literal["off", "shadow", "on"] = "off",
        claim_scope: ClaimScope | None = None,
    ) -> IngestionCompletionDisposition:
        if job.is_enterprise:
            return await self._complete_enterprise(
                job,
                worker_id,
                chunks,
            )
        if effective_quality_mode not in {"off", "shadow", "on"}:
            raise ValueError("Effective knowledge-quality mode is invalid")
        quality_metadata = fingerprint.to_metadata() if fingerprint is not None else {}
        quality_metadata["knowledge_quality_mode"] = effective_quality_mode
        if claim_scope is not None:
            quality_metadata["claim_scope"] = claim_scope.to_metadata()
        is_repair_job = job.configuration.get("ingestion_kind") == "reconciliation_repair"
        persist_authoritative_identity = fingerprint is not None and (
            is_repair_job or is_auto_identity_eligible(fingerprint)
        )
        body: dict[str, object] = {
            "p_job_id": str(job.id),
            "p_worker_id": worker_id,
            "p_claim_token": str(job.claim_token),
            "p_embedding_model": embedding_model,
            "p_embedding_dimensions": embedding_dimensions,
            "p_chunks": [
                {
                    "id": str(chunk.id),
                    "chunk_index": chunk.chunk_index,
                    "content": chunk.content,
                    "token_count": chunk.token_count,
                    "metadata": chunk.metadata,
                    "embedding": list(chunk.embedding),
                }
                for chunk in chunks
            ],
            "p_normalized_content_hash": (
                fingerprint.strict_hash
                if persist_authoritative_identity and fingerprint is not None
                else None
            ),
            "p_normalization_version": (
                fingerprint.normalization_version
                if persist_authoritative_identity and fingerprint is not None
                else None
            ),
            "p_loose_content_signature": (
                fingerprint.loose_signature
                if persist_authoritative_identity and fingerprint is not None
                else None
            ),
            "p_quality_metadata": quality_metadata,
            "p_relations": [relation.to_payload() for relation in relations],
        }
        try:
            payload = await self._rpc("complete_ingestion_job", body)
        except IngestionRepositoryError:
            disposition = await self._job_completion_disposition(job.id)
            if disposition is not None:
                LOGGER.warning(
                    ("Completion response was lost after job %s committed; reconciled as %s"),
                    job.id,
                    disposition,
                )
                return disposition
            raise
        if payload not in {"completed", "duplicate_suppressed"}:
            raise IngestionRepositoryError("Complete ingestion response has an invalid disposition")
        return cast(IngestionCompletionDisposition, payload)

    async def find_content_duplicate(
        self,
        job: ClaimedIngestionJob,
        fingerprint: DocumentFingerprint,
    ) -> UUID | None:
        if job.is_enterprise:
            return None
        try:
            response = await self._client.get(
                "/documents",
                params={
                    "owner_id": f"eq.{job.owner_id}",
                    "notebook_id": f"eq.{job.notebook_id}",
                    "id": f"neq.{job.document_id}",
                    "normalized_content_hash": f"eq.{fingerprint.strict_hash}",
                    "normalization_version": f"eq.{fingerprint.normalization_version}",
                    "status": "eq.ready",
                    "is_active": "eq.true",
                    "select": "id,canonical_document_id",
                    "order": "created_at.asc,id.asc",
                    "limit": "1",
                },
            )
            response.raise_for_status()
            payload = response.json()
            if not isinstance(payload, list):
                raise TypeError("Content duplicate response must be an array")
            if not payload:
                return None
            row = payload[0]
            if not isinstance(row, dict):
                raise TypeError("Content duplicate row must be an object")
            return UUID(str(row.get("canonical_document_id") or row["id"]))
        except (httpx.HTTPError, OSError, KeyError, TypeError, ValueError) as exc:
            raise IngestionRepositoryError("Failed to look up normalized content") from exc

    async def find_chunk_dedup_candidates(
        self,
        job: ClaimedIngestionJob,
        probes: Sequence[ChunkDedupProbe],
        embedding_model: str,
        candidates_per_probe: int,
    ) -> tuple[ChunkDedupCandidate, ...]:
        if job.is_enterprise:
            return ()
        if candidates_per_probe <= 0:
            raise ValueError("candidates_per_probe must be > 0")
        candidates: list[ChunkDedupCandidate] = []
        try:
            for start in range(0, len(probes), _CHUNK_CANDIDATE_BATCH_SIZE):
                batch = probes[start : start + _CHUNK_CANDIDATE_BATCH_SIZE]
                payload = await self._rpc(
                    "find_chunk_dedup_candidates",
                    {
                        "p_owner_id": str(job.owner_id),
                        "p_notebook_id": str(job.notebook_id),
                        "p_document_id": str(job.document_id),
                        "p_embedding_model": embedding_model,
                        "p_probes": [probe.to_payload() for probe in batch],
                        "p_limit_per_probe": candidates_per_probe,
                    },
                )
                if not isinstance(payload, list):
                    raise TypeError("Chunk candidate response must be an array")
                target_ids = {
                    UUID(str(row["target_document_id"]))
                    for row in payload
                    if isinstance(row, Mapping)
                }
                document_scopes = await self._load_candidate_document_scopes(
                    job,
                    target_ids,
                )
                for row in payload:
                    if not isinstance(row, Mapping):
                        raise TypeError("Chunk candidate row must be an object")
                    target_document_id = UUID(str(row["target_document_id"]))
                    canonical_text = str(row["canonical_text"])
                    persisted_scope = merge_claim_scopes(
                        ClaimScope.from_metadata(row.get("target_claim_scope")),
                        document_scopes.get(target_document_id),
                    )
                    fallback_scope = extract_claim_scope(
                        canonical_text,
                        document_id=str(target_document_id),
                        canonical_document_id=(
                            str(row["target_canonical_document_id"])
                            if row.get("target_canonical_document_id") is not None
                            else None
                        ),
                        filename=(
                            str(row["target_original_filename"])
                            if row.get("target_original_filename") is not None
                            else None
                        ),
                        version_id=(
                            str(row["target_version_group_id"])
                            if row.get("target_version_group_id") is not None
                            else None
                        ),
                    )
                    candidates.append(
                        ChunkDedupCandidate(
                            source_chunk_index=int(row["source_chunk_index"]),
                            target_chunk_id=str(row["target_chunk_id"]),
                            target_document_id=target_document_id,
                            target_chunk_index=int(row["target_chunk_index"]),
                            canonical_text=canonical_text,
                            normalized_content_hash=str(row["normalized_content_hash"]),
                            normalization_version=str(row["normalization_version"]),
                            loose_content_signature=str(row["loose_content_signature"]),
                            embedding_text_checksum=(
                                str(row["embedding_text_checksum"])
                                if row.get("embedding_text_checksum") is not None
                                else None
                            ),
                            embedding=_parse_embedding(row["embedding"]),
                            embedding_model=str(row["embedding_model"]),
                            lsh_band_matches=int(row.get("lsh_band_matches") or 0),
                            scope=merge_claim_scopes(persisted_scope, fallback_scope),
                        )
                    )
        except (KeyError, TypeError, ValueError) as exc:
            raise IngestionRepositoryError("Failed to parse chunk dedup candidates") from exc
        return tuple(candidates)

    async def _load_candidate_document_scopes(
        self,
        job: ClaimedIngestionJob,
        document_ids: set[UUID],
    ) -> dict[UUID, ClaimScope]:
        if not document_ids:
            return {}
        try:
            response = await self._client.get(
                "/documents",
                params={
                    "owner_id": f"eq.{job.owner_id}",
                    "notebook_id": f"eq.{job.notebook_id}",
                    "id": f"in.({','.join(sorted(str(value) for value in document_ids))})",
                    "select": (
                        "id,original_filename,canonical_document_id,version_group_id,quality_metadata"
                    ),
                },
            )
            response.raise_for_status()
            payload = response.json()
            if not isinstance(payload, list):
                raise TypeError("Candidate document response must be an array")
            scopes: dict[UUID, ClaimScope] = {}
            for row in payload:
                if not isinstance(row, Mapping):
                    raise TypeError("Candidate document row must be an object")
                document_id = UUID(str(row["id"]))
                quality_metadata = row.get("quality_metadata")
                persisted = (
                    ClaimScope.from_metadata(quality_metadata.get("claim_scope"))
                    if isinstance(quality_metadata, Mapping)
                    else None
                )
                fallback = extract_claim_scope(
                    "",
                    document_id=str(document_id),
                    canonical_document_id=(
                        str(row["canonical_document_id"])
                        if row.get("canonical_document_id") is not None
                        else None
                    ),
                    filename=str(row.get("original_filename") or ""),
                    version_id=(
                        str(row["version_group_id"])
                        if row.get("version_group_id") is not None
                        else None
                    ),
                )
                scopes[document_id] = merge_claim_scopes(persisted, fallback) or fallback
            return scopes
        except (httpx.HTTPError, OSError, KeyError, TypeError, ValueError):
            LOGGER.warning(
                "Could not load persisted scope for chunk candidates; using chunk evidence",
                extra={"document_count": len(document_ids)},
                exc_info=True,
            )
            return {}

    async def complete_duplicate(
        self,
        job: ClaimedIngestionJob,
        worker_id: str,
        canonical_document_id: UUID,
        fingerprint: DocumentFingerprint,
        effective_quality_mode: Literal["off", "shadow", "on"] = "off",
    ) -> None:
        if job.is_enterprise:
            raise ValueError("Enterprise jobs cannot use legacy duplicate suppression")
        if effective_quality_mode not in {"off", "shadow", "on"}:
            raise ValueError("Effective knowledge-quality mode is invalid")
        if not is_auto_identity_eligible(fingerprint):
            raise ValueError(
                "Automatic duplicate completion requires a trusted eligible fingerprint"
            )
        quality_metadata = fingerprint.to_metadata()
        quality_metadata["knowledge_quality_mode"] = effective_quality_mode
        body: dict[str, object] = {
            "p_job_id": str(job.id),
            "p_worker_id": worker_id,
            "p_claim_token": str(job.claim_token),
            "p_canonical_document_id": str(canonical_document_id),
            "p_normalized_content_hash": fingerprint.strict_hash,
            "p_normalization_version": fingerprint.normalization_version,
            "p_loose_content_signature": fingerprint.loose_signature,
            "p_quality_metadata": quality_metadata,
        }
        try:
            await self._rpc("complete_duplicate_ingestion_job", body)
        except IngestionRepositoryError:
            if await self._job_status(job.id) == "succeeded":
                LOGGER.warning(
                    "Duplicate completion response was lost after job %s committed; reconciled",
                    job.id,
                )
                return
            raise

    async def fail(
        self,
        job: ClaimedIngestionJob,
        worker_id: str,
        error_message: str,
    ) -> bool:
        if job.is_enterprise:
            return await self._fail_enterprise(job, worker_id, error_message)
        try:
            payload = await self._rpc(
                "fail_ingestion_job",
                {
                    "p_job_id": str(job.id),
                    "p_worker_id": worker_id,
                    "p_claim_token": str(job.claim_token),
                    "p_error_message": error_message,
                },
            )
        except IngestionRepositoryError:
            if await self._job_status(job.id) == "failed":
                LOGGER.warning(
                    "Failure response was lost after job %s committed; reconciled",
                    job.id,
                )
                return True
            raise
        if not isinstance(payload, bool):
            raise IngestionRepositoryError("Fail ingestion response must be boolean")
        return payload

    async def record_stage(
        self,
        job: ClaimedIngestionJob,
        worker_id: str,
        stage: ProcessingStage,
        status: ProcessingStageStatus,
        *,
        message: str | None = None,
    ) -> bool:
        if not job.is_enterprise:
            return False
        payload = await self._rpc(
            "record_processing_stage",
            {
                "p_job_id": str(job.id),
                "p_worker_id": worker_id,
                "p_claim_token": str(job.claim_token),
                "p_stage": stage.value,
                "p_status": status.value,
                "p_message": message,
            },
        )
        self._enterprise_stages[job.id] = stage
        return payload is not None

    async def record_error(
        self,
        job: ClaimedIngestionJob,
        worker_id: str,
        failure: ProcessingFailure,
    ) -> bool:
        if not job.is_enterprise:
            return False
        payload = await self._rpc(
            "fail_processing_job",
            {
                "p_job_id": str(job.id),
                "p_worker_id": worker_id,
                "p_claim_token": str(job.claim_token),
                "p_stage": failure.stage.value if failure.stage else None,
                "p_error_type": failure.error_type,
                "p_error_code": failure.error_code,
                "p_safe_message": failure.safe_message,
                "p_internal_reference": failure.internal_reference,
                "p_retryable": failure.retryable,
            },
        )
        self._enterprise_claims.discard(job.id)
        self._enterprise_stages.pop(job.id, None)
        return payload is not None

    async def get_job(self, job_id: UUID) -> QueuedProcessingJob | None:
        try:
            response = await self._client.get(
                "/processing_jobs",
                params={
                    "id": f"eq.{job_id}",
                    "select": "id,document_version_id,job_type,attempt_no,previous_job_id",
                    "limit": "1",
                },
            )
            response.raise_for_status()
            rows = response.json()
            if not isinstance(rows, list) or len(rows) > 1:
                raise TypeError("Processing job response must be an array")
            return self._parse_queued_job(rows[0]) if rows else None
        except (httpx.HTTPError, OSError, TypeError, ValueError, KeyError) as exc:
            raise IngestionRepositoryError("Failed to load processing job") from exc

    async def reprocess(self, job_id: UUID) -> QueuedProcessingJob:
        payload = await self._rpc("retry_processing_job", {"p_job_id": str(job_id)})
        row = self._one_mapping(payload, "processing retry")
        return self._parse_queued_job(row)

    async def _claim_enterprise(
        self,
        worker_id: str,
        lease_seconds: int,
    ) -> ClaimedIngestionJob | None:
        payload = await self._rpc(
            "claim_enterprise_ingestion_job",
            {
                "p_worker_id": worker_id,
                "p_lease_seconds": lease_seconds,
            },
        )
        if payload is None or payload == []:
            return None
        row = self._one_mapping(payload, "Enterprise ingestion claim")
        try:
            configuration = row.get("configuration", {})
            if not isinstance(configuration, Mapping):
                raise TypeError("Enterprise job configuration must be an object")
            logical_document_id = UUID(str(row["knowledge_document_id"]))
            return ClaimedIngestionJob(
                id=UUID(str(row["id"])),
                owner_id=UUID(str(row["owner_id"])),
                notebook_id=UUID(str(row["notebook_id"])),
                document_id=logical_document_id,
                attempt_number=int(row["attempt_number"]),
                configuration=dict(configuration),
                storage_bucket=str(row["storage_bucket"]),
                storage_object_path=str(row["storage_object_path"]),
                original_filename=str(row["original_filename"]),
                mime_type=str(row["mime_type"]),
                size_bytes=int(row["size_bytes"]),
                content_hash=(
                    str(row["content_hash"]) if row.get("content_hash") is not None else None
                ),
                claim_token=UUID(str(row["claim_token"])),
                document_version=int(row["document_version"]),
                queue_kind="enterprise",
                document_version_id=UUID(str(row["document_version_id"])),
                knowledge_document_id=logical_document_id,
                source_file_id=UUID(str(row["source_file_id"])),
                job_type=ProcessingJobType(str(row["job_type"])),
            )
        except (KeyError, TypeError, ValueError) as exc:
            raise IngestionRepositoryError("Failed to parse Enterprise claimed job") from exc

    async def _complete_enterprise(
        self,
        job: ClaimedIngestionJob,
        worker_id: str,
        chunks: Sequence[PersistedChunk],
    ) -> IngestionCompletionDisposition:
        payload = await self._rpc(
            "complete_processing_job",
            {
                "p_job_id": str(job.id),
                "p_worker_id": worker_id,
                "p_claim_token": str(job.claim_token),
                "p_chunks": [_enterprise_chunk_payload(chunk) for chunk in chunks],
            },
        )
        if payload is None:
            raise IngestionRepositoryError("Enterprise completion returned no job")
        self._enterprise_claims.discard(job.id)
        self._enterprise_stages.pop(job.id, None)
        return "completed"

    async def _fail_enterprise(
        self,
        job: ClaimedIngestionJob,
        worker_id: str,
        error_message: str,
    ) -> bool:
        stage = self._enterprise_stages.get(job.id)
        payload = await self._rpc(
            "fail_processing_job",
            {
                "p_job_id": str(job.id),
                "p_worker_id": worker_id,
                "p_claim_token": str(job.claim_token),
                "p_stage": stage.value if stage else None,
                "p_error_type": "INGESTION_PIPELINE_ERROR",
                "p_error_code": "PROCESSING_FAILED",
                "p_safe_message": error_message[:1000],
                "p_internal_reference": f"processing_jobs/{job.id}",
                "p_retryable": True,
            },
        )
        self._enterprise_claims.discard(job.id)
        self._enterprise_stages.pop(job.id, None)
        return payload is not None

    @staticmethod
    def _one_mapping(payload: object, label: str) -> Mapping[str, object]:
        if isinstance(payload, Mapping):
            return payload
        if (
            isinstance(payload, list)
            and len(payload) == 1
            and isinstance(payload[0], Mapping)
        ):
            return payload[0]
        raise IngestionRepositoryError(f"Invalid {label} response")

    @staticmethod
    def _parse_queued_job(row: object) -> QueuedProcessingJob:
        if not isinstance(row, Mapping):
            raise TypeError("Processing job row must be an object")
        return QueuedProcessingJob(
            id=UUID(str(row["id"])),
            document_version_id=UUID(str(row["document_version_id"])),
            job_type=ProcessingJobType(str(row["job_type"])),
            attempt_number=int(row["attempt_no"]),
            previous_job_id=(
                UUID(str(row["previous_job_id"]))
                if row.get("previous_job_id") is not None
                else None
            ),
        )

    async def _job_status(self, job_id: UUID) -> str | None:
        """Reconcile an ambiguous RPC outcome without replaying side effects."""
        try:
            response = await self._client.get(
                "/ingestion_jobs",
                params={
                    "id": f"eq.{job_id}",
                    "select": "status",
                    "limit": "1",
                },
            )
            response.raise_for_status()
            payload = response.json()
            if not isinstance(payload, list) or len(payload) > 1:
                raise TypeError("Job reconciliation response must be an array")
            if not payload:
                return None
            row = payload[0]
            if not isinstance(row, Mapping):
                raise TypeError("Job reconciliation row must be an object")
            return str(row["status"])
        except (httpx.HTTPError, OSError, KeyError, TypeError, ValueError):
            LOGGER.exception("Could not reconcile ingestion job %s", job_id)
            return None

    async def _job_completion_disposition(
        self,
        job_id: UUID,
    ) -> IngestionCompletionDisposition | None:
        """Recover the exact completion outcome after an ambiguous response."""
        try:
            response = await self._client.get(
                "/ingestion_jobs",
                params={
                    "id": f"eq.{job_id}",
                    "select": "status,completion_disposition",
                    "limit": "1",
                },
            )
            response.raise_for_status()
            payload = response.json()
            if not isinstance(payload, list) or len(payload) > 1:
                raise TypeError("Job reconciliation response must be an array")
            if not payload:
                return None
            row = payload[0]
            if not isinstance(row, Mapping):
                raise TypeError("Job reconciliation row must be an object")
            if row.get("status") != "succeeded":
                return None
            disposition = row.get("completion_disposition")
            if disposition not in {"completed", "duplicate_suppressed"}:
                raise TypeError("Succeeded job has no completion disposition")
            return cast(IngestionCompletionDisposition, disposition)
        except (httpx.HTTPError, OSError, KeyError, TypeError, ValueError):
            LOGGER.exception(
                "Could not reconcile ingestion completion %s",
                job_id,
            )
            return None

    async def _rpc(self, function_name: str, body: dict[str, object]) -> object:
        try:
            response = await self._client.post(f"/rpc/{function_name}", json=body)
            response.raise_for_status()
            if not response.content:
                return None
            return response.json()
        except (httpx.HTTPError, OSError, TypeError, ValueError) as exc:
            LOGGER.exception("PostgREST ingestion RPC %s failed", function_name)
            raise IngestionRepositoryError(f"Ingestion RPC {function_name} failed") from exc


def _parse_embedding(value: object) -> tuple[float, ...]:
    parsed = value
    if isinstance(value, str):
        parsed = json.loads(value)
    if not isinstance(parsed, list) or not parsed:
        raise TypeError("Chunk candidate embedding must be a non-empty array")
    if any(isinstance(item, bool) or not isinstance(item, int | float) for item in parsed):
        raise TypeError("Chunk candidate embedding contains a non-numeric value")
    return tuple(float(item) for item in parsed)


def _enterprise_chunk_payload(chunk: PersistedChunk) -> dict[str, object]:
    metadata = chunk.metadata
    page_number = _positive_integer(metadata.get("page_number"))
    retrieval_metadata = metadata.get("retrieval_metadata")
    nested = retrieval_metadata if isinstance(retrieval_metadata, Mapping) else {}
    section_value = (
        metadata.get("section_title")
        or nested.get("section_path")
        or nested.get("section_title")
    )
    if isinstance(section_value, Sequence) and not isinstance(section_value, str | bytes):
        section_path = " > ".join(
            str(part).strip() for part in section_value if str(part).strip()
        )
    else:
        section_path = str(section_value).strip() if section_value is not None else ""
    contextual_value = nested.get("contextual_summary") or metadata.get("contextual_summary")
    contextual_content = (
        str(contextual_value).strip() if contextual_value is not None else ""
    )
    checksum = str(metadata.get("checksum") or "").strip().lower()
    if len(checksum) != 64 or any(character not in "0123456789abcdef" for character in checksum):
        checksum = sha256(chunk.content.encode("utf-8")).hexdigest()
    return {
        "id": str(chunk.id),
        "chunk_index": chunk.chunk_index,
        "content": chunk.content,
        "contextual_content": contextual_content or None,
        "token_count": chunk.token_count,
        "content_hash": checksum,
        "page_start": page_number,
        "page_end": page_number,
        "section_path": section_path or None,
        "metadata": metadata,
        "embedding": list(chunk.embedding),
    }


def _positive_integer(value: object) -> int | None:
    if isinstance(value, bool) or value in (None, ""):
        return None
    try:
        parsed = int(str(value))
    except ValueError:
        return None
    return parsed if parsed > 0 else None


__all__ = ["PostgrestIngestionRepository"]
