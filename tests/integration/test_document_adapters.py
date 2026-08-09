"""Integration tests for document PostgREST and Storage adapters."""

import json
import logging
from dataclasses import replace
from datetime import UTC, datetime
from uuid import UUID

import httpx2 as httpx
import pytest

from app.documents.adapters.postgrest_repository import (
    DOCUMENT_COLUMNS,
    PostgrestDocumentRepository,
)
from app.documents.adapters.supabase_storage import SupabaseDocumentStorage
from app.documents.ports.repositories import (
    DocumentRepositoryError,
    NewDocument,
)
from app.documents.ports.storage import ObjectStorageError
from app.ingestion.adapters.postgrest_repository import (
    PostgrestIngestionRepository,
)
from app.ingestion.domain.models import (
    ClaimedIngestionJob,
    IngestionProfile,
    PersistedChunk,
)
from app.ingestion.ports.repositories import IngestionRepositoryError
from app.knowledge_quality.application.analysis import (
    build_chunk_fingerprint,
    build_document_fingerprint,
)
from app.knowledge_quality.domain.models import ChunkDedupProbe

DOCUMENT_ID = UUID("30000000-0000-0000-0000-000000000003")
NOTEBOOK_ID = UUID("10000000-0000-0000-0000-000000000001")
OWNER_ID = UUID("20000000-0000-0000-0000-000000000002")
JOB_ID = UUID("40000000-0000-0000-0000-000000000004")
CLAIM_TOKEN = UUID("50000000-0000-0000-0000-000000000005")
NOW = datetime(2026, 7, 27, tzinfo=UTC)
OBJECT_PATH = f"{OWNER_ID}/{NOTEBOOK_ID}/{DOCUMENT_ID}/Báo_cáo.pdf"

DOCUMENT_ROW = {
    "id": str(DOCUMENT_ID),
    "owner_id": str(OWNER_ID),
    "notebook_id": str(NOTEBOOK_ID),
    "original_filename": "Báo cáo.pdf",
    "storage_bucket": "documents",
    "storage_object_path": OBJECT_PATH,
    "mime_type": "application/pdf",
    "size_bytes": 16,
    "content_hash": "a" * 64,
    "status": "uploading",
    "error_message": None,
    "is_active": True,
    "created_at": NOW.isoformat(),
    "updated_at": NOW.isoformat(),
}

NEW_DOCUMENT = NewDocument(
    id=DOCUMENT_ID,
    owner_id=OWNER_ID,
    notebook_id=NOTEBOOK_ID,
    original_filename="Báo cáo.pdf",
    storage_bucket="documents",
    storage_object_path=OBJECT_PATH,
    mime_type="application/pdf",
    size_bytes=16,
    content_hash="a" * 64,
)


def _claimed_job() -> ClaimedIngestionJob:
    return ClaimedIngestionJob(
        id=JOB_ID,
        owner_id=OWNER_ID,
        notebook_id=NOTEBOOK_ID,
        document_id=DOCUMENT_ID,
        attempt_number=1,
        configuration={"knowledge_quality_mode": "on"},
        storage_bucket="documents",
        storage_object_path=OBJECT_PATH,
        original_filename="Báo cáo.pdf",
        mime_type="application/pdf",
        size_bytes=16,
        content_hash="a" * 64,
        claim_token=CLAIM_TOKEN,
    )


@pytest.mark.anyio
async def test_document_repository_wraps_oserror_and_logs_traceback(
    caplog: pytest.LogCaptureFixture,
) -> None:
    def handler(_request: httpx.Request) -> httpx.Response:
        raise OSError("connection reset")

    async with httpx.AsyncClient(
        base_url="https://example.supabase.co/rest/v1",
        transport=httpx.MockTransport(handler),
    ) as client:
        with (
            caplog.at_level(logging.ERROR),
            pytest.raises(DocumentRepositoryError, match="Failed to create document metadata"),
        ):
            await PostgrestDocumentRepository(client).create_uploading(NEW_DOCUMENT)

    assert "PostgREST document metadata creation failed" in caplog.text


@pytest.mark.anyio
async def test_supabase_storage_wraps_oserror_and_logs_traceback(
    caplog: pytest.LogCaptureFixture,
) -> None:
    def handler(_request: httpx.Request) -> httpx.Response:
        raise OSError("connection reset")

    async with httpx.AsyncClient(
        base_url="https://example.supabase.co/storage/v1",
        transport=httpx.MockTransport(handler),
    ) as client:
        with (
            caplog.at_level(logging.ERROR),
            pytest.raises(ObjectStorageError, match="Failed to upload document object"),
        ):
            await SupabaseDocumentStorage(client).upload(
                "documents",
                OBJECT_PATH,
                b"%PDF-1.7\ncontent",
                "application/pdf",
            )

    assert "Supabase Storage document upload failed" in caplog.text


@pytest.mark.anyio
async def test_ingestion_repository_wraps_oserror_and_logs_traceback(
    caplog: pytest.LogCaptureFixture,
) -> None:
    def handler(_request: httpx.Request) -> httpx.Response:
        raise OSError("connection reset")

    profile = IngestionProfile(
        embedding_model="local-hash-embedding-v1",
        embedding_dimensions=32,
    )
    async with httpx.AsyncClient(
        base_url="https://example.supabase.co/rest/v1",
        transport=httpx.MockTransport(handler),
    ) as client:
        with (
            caplog.at_level(logging.ERROR),
            pytest.raises(IngestionRepositoryError, match="Ingestion RPC .* failed"),
        ):
            await PostgrestIngestionRepository(client).enqueue(
                DOCUMENT_ID,
                NOTEBOOK_ID,
                profile,
            )

    assert "PostgREST ingestion RPC enqueue_document_ingestion failed" in caplog.text


@pytest.mark.anyio
async def test_ingestion_completion_returns_duplicate_suppression_disposition() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.method == "POST"
        assert request.url.path == "/rest/v1/rpc/complete_ingestion_job"
        body = json.loads(request.content)
        assert body["p_quality_metadata"]["knowledge_quality_mode"] == "on"
        return httpx.Response(200, json="duplicate_suppressed")

    fingerprint = build_document_fingerprint(
        "Chính sách này áp dụng thống nhất cho toàn bộ nhân viên chính thức."
    )
    chunk = PersistedChunk(
        id=UUID("60000000-0000-0000-0000-000000000006"),
        chunk_index=0,
        content="Nội dung kiểm thử.",
        token_count=4,
        metadata={},
        embedding=(0.1,),
    )
    async with httpx.AsyncClient(
        base_url="https://example.supabase.co/rest/v1",
        transport=httpx.MockTransport(handler),
    ) as client:
        disposition = await PostgrestIngestionRepository(client).complete(
            _claimed_job(),
            "worker-a",
            (chunk,),
            "embed-v1",
            1,
            fingerprint,
            effective_quality_mode="on",
        )

    assert disposition == "duplicate_suppressed"


@pytest.mark.anyio
async def test_untrusted_projection_metadata_is_saved_without_authoritative_hash() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        assert body["p_normalized_content_hash"] is None
        assert body["p_normalization_version"] is None
        assert body["p_loose_content_signature"] is None
        assert body["p_quality_metadata"]["identity_trusted"] is False
        assert body["p_quality_metadata"]["unrepresented_visual_count"] == 1
        return httpx.Response(200, json="completed")

    fingerprint = replace(
        build_document_fingerprint(
            "This document has enough semantic text for an identity fingerprint."
        ),
        identity_trusted=False,
        unrepresented_visual_count=1,
    )
    chunk = PersistedChunk(
        id=UUID("60000000-0000-0000-0000-000000000006"),
        chunk_index=0,
        content="Canonical chunk content.",
        token_count=3,
        metadata={},
        embedding=(0.1,),
    )
    async with httpx.AsyncClient(
        base_url="https://example.supabase.co/rest/v1",
        transport=httpx.MockTransport(handler),
    ) as client:
        disposition = await PostgrestIngestionRepository(client).complete(
            _claimed_job(),
            "worker-a",
            (chunk,),
            "embed-v1",
            1,
            fingerprint,
            effective_quality_mode="on",
        )

    assert disposition == "completed"


@pytest.mark.anyio
async def test_ingestion_repository_parses_preembedding_chunk_candidates() -> None:
    text = "The approved expense policy applies to every employee."
    fingerprint = build_chunk_fingerprint(text)
    probe = ChunkDedupProbe(
        chunk_index=0,
        chunk_id="source-0",
        canonical_text=text,
        embedding_text_checksum="b" * 64,
        fingerprint=fingerprint,
        include_fuzzy_candidates=True,
    )
    target_document_id = UUID("70000000-0000-0000-0000-000000000007")

    def handler(request: httpx.Request) -> httpx.Response:
        if request.method == "GET":
            assert request.url.path == "/rest/v1/documents"
            return httpx.Response(
                200,
                json=[
                    {
                        "id": str(target_document_id),
                        "original_filename": "project-a-contract.pdf",
                        "canonical_document_id": None,
                        "version_group_id": "80000000-0000-0000-0000-000000000008",
                        "quality_metadata": {"claim_scope": {"project_id": "project-a"}},
                    }
                ],
            )
        assert request.method == "POST"
        assert request.url.path == "/rest/v1/rpc/find_chunk_dedup_candidates"
        body = json.loads(request.content)
        assert body["p_owner_id"] == str(OWNER_ID)
        assert body["p_notebook_id"] == str(NOTEBOOK_ID)
        assert body["p_document_id"] == str(DOCUMENT_ID)
        assert body["p_embedding_model"] == "embedding-v1"
        assert body["p_limit_per_probe"] == 6
        assert body["p_probes"] == [probe.to_payload()]
        return httpx.Response(
            200,
            json=[
                {
                    "source_chunk_index": 0,
                    "target_chunk_id": ("60000000-0000-0000-0000-000000000006"),
                    "target_document_id": str(target_document_id),
                    "target_chunk_index": 4,
                    "canonical_text": text,
                    "normalized_content_hash": fingerprint.strict_hash,
                    "normalization_version": fingerprint.normalization_version,
                    "loose_content_signature": fingerprint.loose_signature,
                    "embedding_text_checksum": "b" * 64,
                    "embedding": "[0.1,0.2,0.3]",
                    "embedding_model": "embedding-v1",
                    "lsh_band_matches": 8,
                }
            ],
        )

    async with httpx.AsyncClient(
        base_url="https://example.supabase.co/rest/v1",
        transport=httpx.MockTransport(handler),
    ) as client:
        candidates = await PostgrestIngestionRepository(client).find_chunk_dedup_candidates(
            _claimed_job(),
            (probe,),
            "embedding-v1",
            6,
        )

    assert len(candidates) == 1
    assert candidates[0].target_document_id == target_document_id
    assert candidates[0].embedding == (0.1, 0.2, 0.3)
    assert candidates[0].lsh_band_matches == 8
    assert candidates[0].scope is not None
    assert candidates[0].scope.project_id == "project-a"


@pytest.mark.anyio
async def test_duplicate_completion_rejects_untrusted_projection_before_rpc() -> None:
    fingerprint = replace(
        build_document_fingerprint(
            "This document has enough semantic text for an identity fingerprint."
        ),
        identity_trusted=False,
        unrepresented_visual_count=1,
    )
    async with httpx.AsyncClient(
        base_url="https://example.supabase.co/rest/v1",
    ) as client:
        repository = PostgrestIngestionRepository(client)
        with pytest.raises(ValueError, match="trusted eligible"):
            await repository.complete_duplicate(
                _claimed_job(),
                "worker-a",
                DOCUMENT_ID,
                fingerprint,
                effective_quality_mode="on",
            )


@pytest.mark.anyio
async def test_lost_completion_response_recovers_persisted_disposition() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.method == "POST":
            raise httpx.ReadError("response lost", request=request)
        assert request.url.path == "/rest/v1/ingestion_jobs"
        assert request.url.params["id"] == f"eq.{JOB_ID}"
        assert request.url.params["select"] == "status,completion_disposition"
        return httpx.Response(
            200,
            json=[
                {
                    "status": "succeeded",
                    "completion_disposition": "duplicate_suppressed",
                }
            ],
        )

    chunk = PersistedChunk(
        id=UUID("60000000-0000-0000-0000-000000000006"),
        chunk_index=0,
        content="Nội dung kiểm thử.",
        token_count=4,
        metadata={},
        embedding=(0.1,),
    )
    async with httpx.AsyncClient(
        base_url="https://example.supabase.co/rest/v1",
        transport=httpx.MockTransport(handler),
    ) as client:
        disposition = await PostgrestIngestionRepository(client).complete(
            _claimed_job(),
            "worker-a",
            (chunk,),
            "embed-v1",
            1,
        )

    assert disposition == "duplicate_suppressed"


@pytest.mark.anyio
async def test_document_repository_lists_filtered_page_with_exact_count() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.method == "GET"
        assert request.url.path == "/rest/v1/documents"
        assert request.url.params["notebook_id"] == f"eq.{NOTEBOOK_ID}"
        assert request.url.params["is_active"] == "eq.true"
        assert request.url.params["status"] == "eq.uploaded"
        assert request.url.params["select"] == DOCUMENT_COLUMNS
        assert request.url.params["order"] == "updated_at.desc,id.asc"
        assert request.url.params["limit"] == "10"
        assert request.url.params["offset"] == "5"
        assert request.headers["prefer"] == "count=exact"
        return httpx.Response(
            200,
            json=[{**DOCUMENT_ROW, "status": "uploaded"}],
            headers={"Content-Range": "5-5/12"},
        )

    async with httpx.AsyncClient(
        base_url="https://example.supabase.co/rest/v1",
        transport=httpx.MockTransport(handler),
    ) as client:
        documents, total_count = await PostgrestDocumentRepository(client).list_by_notebook(
            NOTEBOOK_ID,
            status="uploaded",
            limit=10,
            offset=5,
        )

    assert [document.id for document in documents] == [DOCUMENT_ID]
    assert total_count == 12


@pytest.mark.anyio
async def test_document_repository_gets_one_document_in_notebook_scope() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.method == "GET"
        assert request.url.path == "/rest/v1/documents"
        assert request.url.params["id"] == f"eq.{DOCUMENT_ID}"
        assert request.url.params["notebook_id"] == f"eq.{NOTEBOOK_ID}"
        assert request.url.params["select"] == DOCUMENT_COLUMNS
        assert request.url.params["limit"] == "1"
        return httpx.Response(200, json=[DOCUMENT_ROW])

    async with httpx.AsyncClient(
        base_url="https://example.supabase.co/rest/v1",
        transport=httpx.MockTransport(handler),
    ) as client:
        document = await PostgrestDocumentRepository(client).get_by_id(
            DOCUMENT_ID,
            NOTEBOOK_ID,
        )

    assert document is not None
    assert document.id == DOCUMENT_ID
    assert document.notebook_id == NOTEBOOK_ID


@pytest.mark.anyio
async def test_document_repository_finds_active_document_by_content_hash() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.method == "GET"
        assert request.url.path == "/rest/v1/documents"
        assert request.url.params["owner_id"] == f"eq.{OWNER_ID}"
        assert request.url.params["notebook_id"] == f"eq.{NOTEBOOK_ID}"
        assert request.url.params["content_hash"] == f"eq.{'a' * 64}"
        assert request.url.params["is_active"] == "eq.true"
        assert request.url.params["status"] == "neq.failed"
        assert request.url.params["select"] == DOCUMENT_COLUMNS
        assert request.url.params["limit"] == "1"
        return httpx.Response(200, json=[DOCUMENT_ROW])

    async with httpx.AsyncClient(
        base_url="https://example.supabase.co/rest/v1",
        transport=httpx.MockTransport(handler),
    ) as client:
        document = await PostgrestDocumentRepository(client).find_by_content_hash(
            OWNER_ID,
            NOTEBOOK_ID,
            "a" * 64,
        )

    assert document is not None
    assert document.id == DOCUMENT_ID


@pytest.mark.anyio
async def test_document_repository_finds_no_duplicate_by_content_hash() -> None:
    async with httpx.AsyncClient(
        base_url="https://example.supabase.co/rest/v1",
        transport=httpx.MockTransport(lambda _request: httpx.Response(200, json=[])),
    ) as client:
        document = await PostgrestDocumentRepository(client).find_by_content_hash(
            OWNER_ID,
            NOTEBOOK_ID,
            "b" * 64,
        )

    assert document is None


@pytest.mark.anyio
async def test_document_repository_creates_all_metadata_fields() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.method == "POST"
        assert request.url.path == "/rest/v1/documents"
        assert request.url.params["select"] == DOCUMENT_COLUMNS
        assert request.headers["prefer"] == "return=representation"
        assert json.loads(request.content) == {
            "id": str(DOCUMENT_ID),
            "owner_id": str(OWNER_ID),
            "notebook_id": str(NOTEBOOK_ID),
            "original_filename": "Báo cáo.pdf",
            "storage_bucket": "documents",
            "storage_object_path": OBJECT_PATH,
            "mime_type": "application/pdf",
            "size_bytes": 16,
            "content_hash": "a" * 64,
            "status": "uploading",
            "error_message": None,
        }
        return httpx.Response(201, json=[DOCUMENT_ROW])

    async with httpx.AsyncClient(
        base_url="https://example.supabase.co/rest/v1",
        transport=httpx.MockTransport(handler),
    ) as client:
        document = await PostgrestDocumentRepository(client).create_uploading(NEW_DOCUMENT)

    assert document.id == DOCUMENT_ID
    assert document.storage_object_path == OBJECT_PATH
    assert document.status == "uploading"


@pytest.mark.anyio
async def test_document_repository_updates_status_in_notebook_scope() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.method == "PATCH"
        assert request.url.params["id"] == f"eq.{DOCUMENT_ID}"
        assert request.url.params["notebook_id"] == f"eq.{NOTEBOOK_ID}"
        assert json.loads(request.content) == {
            "status": "uploaded",
            "error_message": None,
        }
        return httpx.Response(
            200,
            json=[{**DOCUMENT_ROW, "status": "uploaded"}],
        )

    async with httpx.AsyncClient(
        base_url="https://example.supabase.co/rest/v1",
        transport=httpx.MockTransport(handler),
    ) as client:
        document = await PostgrestDocumentRepository(client).update_status(
            DOCUMENT_ID,
            NOTEBOOK_ID,
            "uploaded",
            None,
        )

    assert document is not None
    assert document.status == "uploaded"


@pytest.mark.anyio
async def test_document_repository_soft_deletes_in_notebook_scope() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.method == "POST"
        assert request.url.path == "/rest/v1/rpc/soft_delete_document"
        assert json.loads(request.content) == {
            "p_document_id": str(DOCUMENT_ID),
            "p_notebook_id": str(NOTEBOOK_ID),
        }
        return httpx.Response(200, json=[{**DOCUMENT_ROW, "is_active": False}])

    async with httpx.AsyncClient(
        base_url="https://example.supabase.co/rest/v1",
        transport=httpx.MockTransport(handler),
    ) as client:
        document = await PostgrestDocumentRepository(client).soft_delete(
            DOCUMENT_ID,
            NOTEBOOK_ID,
        )

    assert document is not None
    assert document.is_active is False


@pytest.mark.anyio
async def test_document_repository_soft_delete_returns_none_when_already_archived() -> None:
    async with httpx.AsyncClient(
        base_url="https://example.supabase.co/rest/v1",
        transport=httpx.MockTransport(lambda _request: httpx.Response(200, json=[])),
    ) as client:
        document = await PostgrestDocumentRepository(client).soft_delete(
            DOCUMENT_ID,
            NOTEBOOK_ID,
        )

    assert document is None


@pytest.mark.anyio
async def test_supabase_storage_uploads_immutable_object() -> None:
    content = b"%PDF-1.7\ncontent"

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.method == "POST"
        assert request.url.path.endswith(f"/object/documents/{OBJECT_PATH}")
        assert request.headers["content-type"] == "application/pdf"
        assert request.headers["x-upsert"] == "false"
        assert request.content == content
        return httpx.Response(200, json={"Key": OBJECT_PATH})

    async with httpx.AsyncClient(
        base_url="https://example.supabase.co/storage/v1",
        transport=httpx.MockTransport(handler),
    ) as client:
        await SupabaseDocumentStorage(client).upload(
            "documents",
            OBJECT_PATH,
            content,
            "application/pdf",
        )


@pytest.mark.anyio
@pytest.mark.parametrize(
    ("status_code", "payload"),
    [
        (404, {"message": "Not found"}),
        (
            400,
            {
                "statusCode": "404",
                "error": "not_found",
                "message": "Object not found",
            },
        ),
    ],
)
async def test_supabase_storage_delete_is_idempotent_when_object_is_missing(
    status_code: int,
    payload: dict[str, str],
) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.method == "DELETE"
        assert request.url.path.endswith(f"/object/documents/{OBJECT_PATH}")
        return httpx.Response(status_code, json=payload)

    async with httpx.AsyncClient(
        base_url="https://example.supabase.co/storage/v1",
        transport=httpx.MockTransport(handler),
    ) as client:
        await SupabaseDocumentStorage(client).delete(
            "documents",
            OBJECT_PATH,
        )


@pytest.mark.anyio
async def test_supabase_storage_does_not_hide_other_bad_requests() -> None:
    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            400,
            json={
                "statusCode": "400",
                "error": "invalid_request",
                "message": "Invalid object path",
            },
        )

    async with httpx.AsyncClient(
        base_url="https://example.supabase.co/storage/v1",
        transport=httpx.MockTransport(handler),
    ) as client:
        with pytest.raises(
            ObjectStorageError,
            match="Failed to delete document object",
        ):
            await SupabaseDocumentStorage(client).delete(
                "documents",
                OBJECT_PATH,
            )


@pytest.mark.anyio
async def test_supabase_storage_downloads_private_object() -> None:
    content = b"%PDF-1.7\ncontent"

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.method == "GET"
        assert request.url.path.endswith(f"/object/authenticated/documents/{OBJECT_PATH}")
        return httpx.Response(200, content=content)

    async with httpx.AsyncClient(
        base_url="https://example.supabase.co/storage/v1",
        transport=httpx.MockTransport(handler),
    ) as client:
        downloaded = await SupabaseDocumentStorage(client).download(
            "documents",
            OBJECT_PATH,
        )

    assert downloaded == content


@pytest.mark.anyio
async def test_ingestion_repository_enqueues_with_pipeline_profile() -> None:
    profile = IngestionProfile(
        embedding_model="local-hash-embedding-v1",
        embedding_dimensions=32,
        configuration={"advanced_extraction_enabled": True},
    )

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.method == "POST"
        assert request.url.path == "/rest/v1/rpc/enqueue_document_ingestion"
        assert json.loads(request.content) == {
            "p_document_id": str(DOCUMENT_ID),
            "p_notebook_id": str(NOTEBOOK_ID),
            "p_embedding_model": "local-hash-embedding-v1",
            "p_embedding_dimensions": 32,
            "p_configuration": {"advanced_extraction_enabled": True},
        }
        return httpx.Response(
            200,
            json=[{**DOCUMENT_ROW, "status": "processing"}],
        )

    async with httpx.AsyncClient(
        base_url="https://example.supabase.co/rest/v1",
        transport=httpx.MockTransport(handler),
    ) as client:
        document = await PostgrestIngestionRepository(client).enqueue(
            DOCUMENT_ID,
            NOTEBOOK_ID,
            profile,
        )

    assert document.status == "processing"
