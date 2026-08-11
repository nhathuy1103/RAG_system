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

JOB_ID = UUID("10000000-0000-0000-0000-000000000001")
OWNER_ID = UUID("20000000-0000-0000-0000-000000000002")
DOCUMENT_ID = UUID("30000000-0000-0000-0000-000000000003")
VERSION_ID = UUID("40000000-0000-0000-0000-000000000004")
SOURCE_ID = UUID("50000000-0000-0000-0000-000000000005")
CLAIM_TOKEN = UUID("60000000-0000-0000-0000-000000000006")
CHUNK_ID = UUID("70000000-0000-0000-0000-000000000007")


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
        if request.url.path.endswith("/complete_processing_job_v3"):
            body = json.loads(request.content)
            assert body["p_job_id"] == str(JOB_ID)
            assert body["p_chunks"][0]["id"] == str(CHUNK_ID)
            assert body["p_chunks"][0]["page_start"] == 4
            assert body["p_chunks"][0]["page_end"] == 4
            assert body["p_chunks"][0]["section_path"] == "Access > Review"
            assert len(body["p_chunks"][0]["content_hash"]) == 64
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
        )

    assert recorded is True
    assert disposition == "completed"
    assert requests == [
        "/rest/v1/rpc/claim_enterprise_ingestion_job",
        "/rest/v1/rpc/record_processing_stage",
        "/rest/v1/rpc/complete_processing_job_v3",
    ]


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
