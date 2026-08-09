from __future__ import annotations

import json
from datetime import UTC, datetime
from uuid import UUID

import httpx2 as httpx
import pytest

from app.documents.adapters.enterprise_postgrest_repository import (
    PostgrestEnterpriseDocumentRepository,
)
from app.documents.ports.enterprise_repositories import (
    NewInitialDocumentUpload,
    NewKnowledgeDocument,
    NewSourceFile,
)
from app.governance.adapters.postgrest_repository import PostgrestGovernanceRepository
from app.identity.adapters.postgrest_repository import PostgrestIdentityRepository

USER_ID = UUID("10000000-0000-0000-0000-000000000001")
DOCUMENT_ID = UUID("20000000-0000-0000-0000-000000000002")
VERSION_ID = UUID("30000000-0000-0000-0000-000000000003")
SOURCE_ID = UUID("40000000-0000-0000-0000-000000000004")
CHUNK_ID = UUID("50000000-0000-0000-0000-000000000005")
ROLE_ID = UUID("60000000-0000-0000-0000-000000000006")
PERMISSION_ID = UUID("70000000-0000-0000-0000-000000000007")
GROUP_ID = UUID("80000000-0000-0000-0000-000000000008")
DEPARTMENT_ID = UUID("90000000-0000-0000-0000-000000000009")
MEMBERSHIP_ID = UUID("a0000000-0000-0000-0000-000000000010")
NOW = datetime(2026, 8, 8, tzinfo=UTC)

VERSION_ROW = {
    "id": str(VERSION_ID),
    "document_id": str(DOCUMENT_ID),
    "version_number": 2,
    "source_file_id": str(SOURCE_ID),
    "status": "ACTIVE",
    "previous_version_id": None,
    "change_summary": "Approved",
    "effective_date": None,
    "created_by": str(USER_ID),
    "created_at": NOW.isoformat(),
    "updated_at": NOW.isoformat(),
    "legacy_document_id": None,
}

DOCUMENT_ROW = {
    "id": str(DOCUMENT_ID),
    "title": "Policy",
    "description": "",
    "document_type": "POLICY",
    "category": "HR",
    "document_number": None,
    "issued_date": None,
    "effective_date": None,
    "expiration_date": None,
    "source": None,
    "owner_department_id": None,
    "status": "DRAFT",
    "current_version_id": None,
    "metadata": {},
    "created_by": str(USER_ID),
    "created_at": NOW.isoformat(),
    "updated_at": NOW.isoformat(),
    "archived_by": None,
    "archived_at": None,
    "archive_reason": None,
}

JOB_ID = UUID("60000000-0000-0000-0000-000000000006")
JOB_ROW = {
    "id": str(JOB_ID),
    "document_version_id": str(VERSION_ID),
    "job_type": "INITIAL_PROCESS",
    "status": "PENDING",
    "current_stage": None,
    "attempt_no": 1,
    "previous_job_id": None,
    "requested_by": str(USER_ID),
    "requested_at": NOW.isoformat(),
    "started_at": None,
    "completed_at": None,
    "heartbeat_at": None,
    "lease_owner": None,
    "lease_expires_at": None,
    "error_code": None,
    "error_message": None,
}


@pytest.mark.anyio
async def test_publish_calls_atomic_rpc_and_parses_version() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path.endswith("/rpc/publish_document_version")
        assert json.loads(request.content) == {"p_version_id": str(VERSION_ID)}
        return httpx.Response(200, json=VERSION_ROW)

    async with httpx.AsyncClient(
        base_url="https://example.test/rest/v1", transport=httpx.MockTransport(handler)
    ) as client:
        version = await PostgrestEnterpriseDocumentRepository(client).publish_version(VERSION_ID)

    assert version.id == VERSION_ID
    assert version.status == "ACTIVE"


@pytest.mark.anyio
async def test_principal_context_is_resolved_by_database_rpc() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path.endswith("/rpc/get_principal_context")
        return httpx.Response(
            200,
            json={
                "user_id": str(USER_ID),
                "status": "ACTIVE",
                "roles": [
                    {
                        "id": str(ROLE_ID),
                        "code": "EMPLOYEE",
                        "name": "Employee",
                        "status": "ACTIVE",
                    }
                ],
                "permissions": ["ASK_KNOWLEDGE"],
                "group_ids": [],
                "department_ids": [],
            },
        )

    async with httpx.AsyncClient(
        base_url="https://example.test/rest/v1", transport=httpx.MockTransport(handler)
    ) as client:
        principal = await PostgrestIdentityRepository(client).get_principal_context(
            USER_ID, email="user@example.test"
        )

    assert principal.email == "user@example.test"
    assert principal.has_permission("ASK_KNOWLEDGE")
    assert principal.roles[0].code == "EMPLOYEE"


@pytest.mark.anyio
async def test_role_permission_projection_uses_role_scoped_assignment_rows() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path.endswith("/role_permissions")
        assert request.url.params["role_id"] == f"eq.{ROLE_ID}"
        assert request.url.params["select"] == "permission:functional_permissions(*)"
        return httpx.Response(
            200,
            json=[
                {
                    "permission": {
                        "id": str(PERMISSION_ID),
                        "code": "MANAGE_USER",
                        "name": "Manage users",
                        "description": "Manage enterprise users",
                        "created_at": NOW.isoformat(),
                    }
                }
            ],
        )

    async with httpx.AsyncClient(
        base_url="https://example.test/rest/v1", transport=httpx.MockTransport(handler)
    ) as client:
        permissions = await PostgrestIdentityRepository(client).list_role_permissions(ROLE_ID)

    assert [(item.id, item.code) for item in permissions] == [(PERMISSION_ID, "MANAGE_USER")]


@pytest.mark.anyio
async def test_user_membership_projections_include_related_organizations() -> None:
    def organization(
        object_id: UUID, code: str, name: str, *, department: bool = False
    ) -> dict[str, object]:
        value: dict[str, object] = {
            "id": str(object_id),
            "code": code,
            "name": name,
            "description": "",
            "status": "ACTIVE",
            "created_at": NOW.isoformat(),
            "updated_at": NOW.isoformat(),
        }
        if department:
            value["parent_department_id"] = None
        return value

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.params["user_id"] == f"eq.{USER_ID}"
        if request.url.path.endswith("/user_roles"):
            return httpx.Response(
                200,
                json=[
                    {
                        "id": str(MEMBERSHIP_ID),
                        "user_id": str(USER_ID),
                        "role_id": str(ROLE_ID),
                        "assigned_by": str(USER_ID),
                        "assigned_at": NOW.isoformat(),
                        "role": organization(ROLE_ID, "ADMIN", "Administrator"),
                    }
                ],
            )
        if request.url.path.endswith("/user_groups"):
            return httpx.Response(
                200,
                json=[
                    {
                        "id": str(MEMBERSHIP_ID),
                        "user_id": str(USER_ID),
                        "group_id": str(GROUP_ID),
                        "added_by": None,
                        "joined_at": NOW.isoformat(),
                        "group": organization(GROUP_ID, "HR", "Human Resources"),
                    }
                ],
            )
        assert request.url.path.endswith("/user_departments")
        assert request.url.params["end_at"] == "is.null"
        return httpx.Response(
            200,
            json=[
                {
                    "id": str(MEMBERSHIP_ID),
                    "user_id": str(USER_ID),
                    "department_id": str(DEPARTMENT_ID),
                    "is_primary": True,
                    "start_at": NOW.isoformat(),
                    "end_at": None,
                    "assigned_by": None,
                    "department": organization(
                        DEPARTMENT_ID, "ENGINEERING", "Engineering", department=True
                    ),
                }
            ],
        )

    async with httpx.AsyncClient(
        base_url="https://example.test/rest/v1", transport=httpx.MockTransport(handler)
    ) as client:
        repository = PostgrestIdentityRepository(client)
        roles = await repository.list_user_roles(USER_ID)
        groups = await repository.list_user_groups(USER_ID)
        departments = await repository.list_user_departments(USER_ID, include_inactive=False)

    assert roles[0].role.id == ROLE_ID
    assert groups[0].group.id == GROUP_ID
    assert departments[0].department.id == DEPARTMENT_ID
    assert departments[0].is_primary is True


@pytest.mark.anyio
async def test_enterprise_search_uses_security_rpc_and_preserves_version_id() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path.endswith("/rpc/search_enterprise_knowledge")
        assert json.loads(request.content)["p_query"] == "leave policy"
        return httpx.Response(
            200,
            json=[
                {
                    "chunk_id": str(CHUNK_ID),
                    "document_id": str(DOCUMENT_ID),
                    "document_version_id": str(VERSION_ID),
                    "title": "Leave policy",
                    "content": "Employees receive annual leave.",
                    "score": 0.91,
                    "metadata": {},
                }
            ],
        )

    async with httpx.AsyncClient(
        base_url="https://example.test/rest/v1", transport=httpx.MockTransport(handler)
    ) as client:
        hits = await PostgrestGovernanceRepository(client).search(
            "leave policy", limit=5, filters={}
        )

    assert hits[0].document_version_id == VERSION_ID
    assert hits[0].score == pytest.approx(0.91)


@pytest.mark.anyio
async def test_enterprise_dense_search_uses_acl_gated_pgvector_rpc() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path.endswith("/rpc/match_enterprise_document_chunks")
        body = json.loads(request.content)
        assert len(body["p_query_embedding"]) == 1536
        assert body["p_filters"] == {"category": "HR"}
        return httpx.Response(
            200,
            json=[
                {
                    "chunk_id": str(CHUNK_ID),
                    "document_id": str(DOCUMENT_ID),
                    "document_version_id": str(VERSION_ID),
                    "title": "Leave policy",
                    "content": "Employees receive annual leave.",
                    "score": 0.87,
                    "metadata": {},
                }
            ],
        )

    async with httpx.AsyncClient(
        base_url="https://example.test/rest/v1",
        transport=httpx.MockTransport(handler),
    ) as client:
        hits = await PostgrestGovernanceRepository(client).search_dense(
            [0.01] * 1536,
            limit=5,
            filters={"category": "HR"},
        )

    assert hits[0].chunk_id == CHUNK_ID
    assert hits[0].document_version_id == VERSION_ID


@pytest.mark.anyio
async def test_source_file_metadata_is_inserted_with_caller_identity() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path.endswith("/source_files")
        body = json.loads(request.content)
        assert body["created_by"] == str(USER_ID)
        assert body["bucket_name"] == "knowledge-source-files"
        return httpx.Response(
            201,
            json=[{**body, "created_at": NOW.isoformat()}],
        )

    value = NewSourceFile(
        id=SOURCE_ID,
        bucket_name="knowledge-source-files",
        object_path=f"{USER_ID}/{SOURCE_ID}/policy.pdf",
        original_file_name="policy.pdf",
        mime_type="application/pdf",
        size_bytes=16,
        sha256="a" * 64,
        created_by=USER_ID,
    )
    async with httpx.AsyncClient(
        base_url="https://example.test/rest/v1",
        transport=httpx.MockTransport(handler),
    ) as client:
        source = await PostgrestEnterpriseDocumentRepository(client).create_source_file(value)

    assert source.id == SOURCE_ID
    assert source.created_by == USER_ID


@pytest.mark.anyio
async def test_initial_upload_calls_atomic_rpc_and_returns_complete_bundle() -> None:
    source_value = NewSourceFile(
        id=SOURCE_ID,
        bucket_name="knowledge-source-files",
        object_path=f"{USER_ID}/{SOURCE_ID}/policy.pdf",
        original_file_name="policy.pdf",
        mime_type="application/pdf",
        size_bytes=16,
        sha256="a" * 64,
        created_by=USER_ID,
    )
    source_row = {
        "id": str(SOURCE_ID),
        "bucket_name": source_value.bucket_name,
        "object_path": source_value.object_path,
        "original_file_name": source_value.original_file_name,
        "mime_type": source_value.mime_type,
        "size_bytes": source_value.size_bytes,
        "sha256": source_value.sha256,
        "created_by": str(USER_ID),
        "created_at": NOW.isoformat(),
    }

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path.endswith("/rpc/create_enterprise_document_upload")
        body = json.loads(request.content)
        assert body["p_sha256"] == "a" * 64
        assert body["p_title"] == "Policy"
        return httpx.Response(
            200,
            json={
                "document": DOCUMENT_ROW,
                "version": {**VERSION_ROW, "version_number": 1, "status": "DRAFT"},
                "processing_job": JOB_ROW,
                "source_file": source_row,
            },
        )

    async with httpx.AsyncClient(
        base_url="https://example.test/rest/v1",
        transport=httpx.MockTransport(handler),
    ) as client:
        result = await PostgrestEnterpriseDocumentRepository(client).create_initial_document_upload(
            NewInitialDocumentUpload(
                document=NewKnowledgeDocument(title="Policy", category="HR"),
                source_file=source_value,
            )
        )

    assert result.document.id == DOCUMENT_ID
    assert result.version.version_number == 1
    assert result.processing_job.id == JOB_ID
    assert result.source_file.id == SOURCE_ID


@pytest.mark.anyio
async def test_processing_job_detail_includes_stage_and_safe_error_history() -> None:
    stage_id = 7
    error_id = UUID("70000000-0000-0000-0000-000000000007")

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/processing_jobs"):
            return httpx.Response(200, json=[JOB_ROW])
        if request.url.path.endswith("/processing_stage_history"):
            return httpx.Response(
                200,
                json=[
                    {
                        "id": stage_id,
                        "processing_job_id": str(JOB_ID),
                        "stage": "EXTRACTION",
                        "status": "FAILED",
                        "started_at": NOW.isoformat(),
                        "completed_at": NOW.isoformat(),
                        "message": "Extraction failed",
                    }
                ],
            )
        assert request.url.path.endswith("/processing_errors")
        return httpx.Response(
            200,
            json=[
                {
                    "id": str(error_id),
                    "processing_job_id": str(JOB_ID),
                    "stage": "EXTRACTION",
                    "error_type": "ParserError",
                    "error_code": "PARSER_FAILED",
                    "safe_message": "The source could not be parsed",
                    "retryable": True,
                    "created_at": NOW.isoformat(),
                }
            ],
        )

    async with httpx.AsyncClient(
        base_url="https://example.test/rest/v1",
        transport=httpx.MockTransport(handler),
    ) as client:
        detail = await PostgrestEnterpriseDocumentRepository(client).get_processing_job_detail(
            JOB_ID
        )

    assert detail is not None
    assert detail.stage_history[0].id == stage_id
    assert detail.errors[0].safe_message == "The source could not be parsed"


@pytest.mark.anyio
async def test_review_context_exposes_candidate_chunks_without_raw_table_access() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path.endswith("/rpc/get_document_version_review_context")
        assert json.loads(request.content) == {"p_version_id": str(VERSION_ID)}
        return httpx.Response(
            200,
            json={
                "document": DOCUMENT_ROW,
                "version": {**VERSION_ROW, "status": "READY_FOR_REVIEW"},
                "source_file": {
                    "id": str(SOURCE_ID),
                    "original_file_name": "policy.pdf",
                    "mime_type": "application/pdf",
                    "size_bytes": 16,
                    "sha256": "a" * 64,
                    "created_by": str(USER_ID),
                    "created_at": NOW.isoformat(),
                },
                "latest_processing_job": {**JOB_ROW, "status": "SUCCEEDED"},
                "stage_history": [],
                "errors": [],
                "extracted_chunks": [
                    {
                        "chunk_id": str(CHUNK_ID),
                        "chunk_index": 0,
                        "content": "Employees receive annual leave.",
                        "page_start": 2,
                        "page_end": 2,
                        "section_path": "Leave",
                        "metadata": {"language": "en"},
                    }
                ],
            },
        )

    async with httpx.AsyncClient(
        base_url="https://example.test/rest/v1",
        transport=httpx.MockTransport(handler),
    ) as client:
        context = await PostgrestEnterpriseDocumentRepository(client).get_version_review_context(
            VERSION_ID
        )

    assert context is not None
    assert context.version.status == "READY_FOR_REVIEW"
    assert context.source_file.original_file_name == "policy.pdf"
    assert context.extracted_chunks[0].page_start == 2
    assert context.extracted_chunks[0].content.startswith("Employees")
