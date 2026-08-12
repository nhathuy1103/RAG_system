from __future__ import annotations

import json
from uuid import UUID

import httpx2 as httpx
import pytest

from app.ingestion.adapters.postgrest_repository import PostgrestIngestionRepository
from app.ingestion.domain.models import (
    PersistedChunk,
    ProcessingJobType,
    ProcessingStage,
    ProcessingStageStatus,
)
from app.knowledge_quality.domain.models import (
    ChunkDedupProbe,
    DocumentFingerprint,
    QualityRelationCandidate,
    RelationType,
)

JOB_ID = UUID("10000000-0000-0000-0000-000000000001")
OWNER_ID = UUID("20000000-0000-0000-0000-000000000002")
DOCUMENT_ID = UUID("30000000-0000-0000-0000-000000000003")
VERSION_ID = UUID("40000000-0000-0000-0000-000000000004")
SOURCE_ID = UUID("50000000-0000-0000-0000-000000000005")
CLAIM_TOKEN = UUID("60000000-0000-0000-0000-000000000006")
CHUNK_ID = UUID("70000000-0000-0000-0000-000000000007")
TARGET_DOCUMENT_ID = UUID("80000000-0000-0000-0000-000000000008")


def _claim_row() -> dict[str, object]:
    return {
        "id": str(JOB_ID),
        "owner_id": str(OWNER_ID),
        "notebook_id": str(DOCUMENT_ID),
        "document_id": str(DOCUMENT_ID),
        "attempt_number": 1,
        "configuration": {},
        "storage_bucket": "enterprise-documents",
        "storage_object_path": f"{DOCUMENT_ID}/{VERSION_ID}/policy.pdf",
        "original_filename": "policy.pdf",
        "mime_type": "application/pdf",
        "size_bytes": 128,
        "content_hash": "a" * 64,
        "claim_token": str(CLAIM_TOKEN),
        "document_version": 2,
        "document_version_id": str(VERSION_ID),
        "knowledge_document_id": str(DOCUMENT_ID),
        "source_file_id": str(SOURCE_ID),
        "job_type": "NEW_VERSION",
    }


@pytest.mark.anyio
async def test_enterprise_queue_claim_and_completion_use_version_scoped_rpcs() -> None:
    requests: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request.url.path)
        if request.url.path.endswith("/claim_enterprise_ingestion_job"):
            body = json.loads(request.content)
            assert body == {"p_worker_id": "worker-a", "p_lease_seconds": 120}
            return httpx.Response(200, json=[_claim_row()])
        if request.url.path.endswith("/record_processing_stage"):
            body = json.loads(request.content)
            assert body["p_stage"] == "EXTRACTION"
            assert body["p_status"] == "STARTED"
            return httpx.Response(200, json={"id": 1})
        if request.url.path.endswith("/complete_processing_job_v4"):
            body = json.loads(request.content)
            assert body["p_job_id"] == str(JOB_ID)
            assert body["p_chunks"][0]["id"] == str(CHUNK_ID)
            assert body["p_chunks"][0]["page_start"] == 4
            assert body["p_chunks"][0]["page_end"] == 4
            assert body["p_chunks"][0]["section_path"] == "Access > Review"
            assert len(body["p_chunks"][0]["content_hash"]) == 64
            assert body["p_normalized_content_hash"] == "b" * 64
            assert body["p_normalization_version"] == "knowledge-document-identity-v2"
            assert body["p_loose_content_signature"] == "c" * 16
            assert body["p_quality_mode"] == "on"
            assert body["p_relations"][0]["target_document_id"] == str(
                TARGET_DOCUMENT_ID
            )
            return httpx.Response(200, json={"id": str(JOB_ID), "status": "SUCCEEDED"})
        raise AssertionError(f"Unexpected request: {request.url.path}")

    async with httpx.AsyncClient(
        base_url="https://example.supabase.co/rest/v1",
        transport=httpx.MockTransport(handler),
    ) as client:
        repository = PostgrestIngestionRepository(client, enterprise_queue_enabled=True)
        job = await repository.claim("worker-a", 120)
        assert job is not None
        assert job.is_enterprise
        assert job.document_id == DOCUMENT_ID
        assert job.document_version_id == VERSION_ID
        assert job.job_type == ProcessingJobType.NEW_VERSION

        recorded = await repository.record_stage(
            job,
            "worker-a",
            ProcessingStage.EXTRACTION,
            ProcessingStageStatus.STARTED,
        )
        disposition = await repository.complete(
            job,
            "worker-a",
            (
                PersistedChunk(
                    id=CHUNK_ID,
                    chunk_index=0,
                    content="Annual access review is required.",
                    token_count=5,
                    metadata={
                        "page_number": 4,
                        "section_title": ["Access", "Review"],
                    },
                    embedding=(0.1, 0.2),
                ),
            ),
            "embed-model",
            2,
            fingerprint=DocumentFingerprint(
                strict_hash="b" * 64,
                loose_signature="c" * 16,
                normalization_version="knowledge-document-identity-v2",
                character_count=36,
                token_count=5,
            ),
            relations=(
                QualityRelationCandidate(
                    target_document_id=TARGET_DOCUMENT_ID,
                    relation_type=RelationType.CONFLICT_CANDIDATE,
                    confidence=0.94,
                    reason="validated_claim_conflict",
                ),
            ),
            effective_quality_mode="on",
        )

    assert recorded is True
    assert disposition == "completed"
    assert requests == [
        "/rest/v1/rpc/claim_enterprise_ingestion_job",
        "/rest/v1/rpc/record_processing_stage",
        "/rest/v1/rpc/complete_processing_job_v4",
    ]


@pytest.mark.anyio
async def test_enterprise_duplicate_lookup_uses_canonical_acl_scoped_rpc() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/rpc/claim_enterprise_ingestion_job"):
            return httpx.Response(200, json=[_claim_row()])
        assert request.url.path.endswith("/rpc/find_enterprise_content_duplicate")
        body = json.loads(request.content)
        assert body == {
            "p_actor_id": str(OWNER_ID),
            "p_document_id": str(DOCUMENT_ID),
            "p_normalized_content_hash": "d" * 64,
            "p_normalization_version": "knowledge-document-identity-v2",
        }
        return httpx.Response(200, json=str(TARGET_DOCUMENT_ID))

    async with httpx.AsyncClient(
        base_url="https://example.supabase.co/rest/v1",
        transport=httpx.MockTransport(handler),
    ) as client:
        repository = PostgrestIngestionRepository(client, enterprise_queue_enabled=True)
        job = await repository._claim_enterprise("worker-a", 120)
        assert job is not None
        duplicate_id = await repository.find_content_duplicate(
            job,
            DocumentFingerprint(
                strict_hash="d" * 64,
                loose_signature="e" * 16,
                normalization_version="knowledge-document-identity-v2",
                character_count=100,
                token_count=20,
            ),
        )

    assert duplicate_id == TARGET_DOCUMENT_ID


@pytest.mark.anyio
async def test_enterprise_chunk_candidates_use_acl_scoped_canonical_rpc() -> None:
    fingerprint = DocumentFingerprint(
        strict_hash="f" * 64,
        loose_signature="1" * 16,
        normalization_version="knowledge-chunk-identity-v1",
        character_count=100,
        token_count=20,
    )
    probe = ChunkDedupProbe(
        chunk_index=0,
        chunk_id="source-chunk",
        canonical_text="Annual access review is required.",
        embedding_text_checksum="2" * 64,
        fingerprint=fingerprint,
        include_fuzzy_candidates=True,
        binary_keys=("m1:b0:10",),
        fts_terms=("annual", "access"),
    )

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/rpc/claim_enterprise_ingestion_job"):
            return httpx.Response(200, json=[_claim_row()])
        assert request.url.path.endswith("/rpc/find_enterprise_chunk_candidates_v2")
        body = json.loads(request.content)
        assert body["p_actor_id"] == str(OWNER_ID)
        assert body["p_document_id"] == str(DOCUMENT_ID)
        assert body["p_probes"][0]["binary_keys"] == ["m1:b0:10"]
        return httpx.Response(
            200,
            json=[
                {
                    "source_chunk_index": 0,
                    "target_chunk_id": str(CHUNK_ID),
                    "target_document_id": str(TARGET_DOCUMENT_ID),
                    "target_chunk_index": 3,
                    "canonical_text": "Annual access review is required.",
                    "normalized_content_hash": "f" * 64,
                    "normalization_version": "knowledge-chunk-identity-v1",
                    "loose_content_signature": "1" * 16,
                    "embedding_text_checksum": "2" * 64,
                    "embedding": [0.1, 0.2],
                    "embedding_model": "embed-model",
                    "lsh_band_matches": 1,
                    "exact_rank": 1,
                    "exact_score": 1.0,
                    "binary_rank": 1,
                    "binary_score": 0.5,
                    "binary_key_matches": 1,
                    "fts_rank": 1,
                    "fts_score": 0.4,
                }
            ],
        )

    async with httpx.AsyncClient(
        base_url="https://example.supabase.co/rest/v1",
        transport=httpx.MockTransport(handler),
    ) as client:
        repository = PostgrestIngestionRepository(client, enterprise_queue_enabled=True)
        job = await repository._claim_enterprise("worker-a", 120)
        assert job is not None
        candidates = await repository.find_chunk_dedup_candidates(
            job,
            (probe,),
            "embed-model",
            5,
        )

    assert len(candidates) == 1
    assert candidates[0].target_document_id == TARGET_DOCUMENT_ID
    assert {item.channel.value for item in candidates[0].channel_evidence} == {
        "exact",
        "binary",
        "fts",
    }


@pytest.mark.anyio
async def test_empty_enterprise_queue_falls_back_to_legacy_claim() -> None:
    legacy_document_id = UUID("80000000-0000-0000-0000-000000000008")

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/claim_enterprise_ingestion_job"):
            return httpx.Response(200, json=[])
        if request.url.path.endswith("/claim_ingestion_job"):
            return httpx.Response(
                200,
                json=[
                    {
                        "id": str(JOB_ID),
                        "owner_id": str(OWNER_ID),
                        "notebook_id": str(DOCUMENT_ID),
                        "document_id": str(legacy_document_id),
                        "attempt_number": 1,
                        "configuration": {},
                        "storage_bucket": "documents",
                        "storage_object_path": "legacy/policy.pdf",
                        "original_filename": "policy.pdf",
                        "mime_type": "application/pdf",
                        "size_bytes": 128,
                        "content_hash": None,
                        "claim_token": str(CLAIM_TOKEN),
                        "document_version": 1,
                    }
                ],
            )
        raise AssertionError(f"Unexpected request: {request.url.path}")

    async with httpx.AsyncClient(
        base_url="https://example.supabase.co/rest/v1",
        transport=httpx.MockTransport(handler),
    ) as client:
        job = await PostgrestIngestionRepository(
            client,
            enterprise_queue_enabled=True,
        ).claim("worker-a", 120)

    assert job is not None
    assert job.is_enterprise is False
    assert job.document_id == legacy_document_id
