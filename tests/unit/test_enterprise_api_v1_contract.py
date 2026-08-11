from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID

import httpx2 as httpx
import pytest
from fastapi import FastAPI

from app.api.dependencies.auth import get_current_user
from app.api.dependencies.enterprise import (
    get_enterprise_document_service,
    get_enterprise_question_service,
    get_enterprise_source_file_service,
    get_governance_service,
    get_identity_service,
    require_manage_document,
    require_review_workspace,
    require_upload_document,
)
from app.api.enterprise_errors import install_enterprise_error_contract, request_id_middleware
from app.api.routers import enterprise_documents, enterprise_governance, enterprise_identity
from app.api.schemas.auth import CurrentUser
from app.documents.domain.enterprise_models import (
    DocumentVersion,
    DocumentVersionReviewContext,
    InitialDocumentUpload,
    KnowledgeDocument,
    ProcessingError,
    ProcessingJob,
    ProcessingJobDetail,
    ProcessingStageHistory,
    ReviewChunk,
    ReviewSourceFile,
    SourceFile,
)
from app.governance.domain.models import (
    AskQuestionResult,
    ConversationDetail,
    EnterpriseCitation,
    EnterpriseConversation,
    EnterpriseMessage,
    SearchHit,
)
from app.identity.domain.models import PrincipalContext

USER_ID = UUID("10000000-0000-0000-0000-000000000001")
DOCUMENT_ID = UUID("20000000-0000-0000-0000-000000000002")
VERSION_ID = UUID("30000000-0000-0000-0000-000000000003")
CHUNK_ID = UUID("40000000-0000-0000-0000-000000000004")
CONVERSATION_ID = UUID("50000000-0000-0000-0000-000000000005")
USER_MESSAGE_ID = UUID("60000000-0000-0000-0000-000000000006")
ANSWER_MESSAGE_ID = UUID("70000000-0000-0000-0000-000000000007")
CITATION_ID = UUID("80000000-0000-0000-0000-000000000008")
NOW = datetime(2026, 8, 8, tzinfo=UTC)


class IdentityServiceStub:
    async def current_principal(
        self, user_id: UUID, *, email: str | None = None
    ) -> PrincipalContext:
        return PrincipalContext(
            user_id=user_id,
            email=email,
            status="ACTIVE",
            permissions=frozenset({"ASK_KNOWLEDGE"}),
        )


class DocumentServiceStub:
    def __init__(self, document: KnowledgeDocument | None) -> None:
        self.document = document

    async def get_document(self, _document_id: UUID) -> KnowledgeDocument | None:
        return self.document

    async def list_documents(
        self, *, document_status: str | None, limit: int, offset: int
    ) -> tuple[list[KnowledgeDocument], int]:
        assert document_status is None
        assert limit == 200
        assert offset == 0
        documents = [self.document] if self.document is not None else []
        return documents, len(documents)

    async def list_processing_jobs(
        self,
        *,
        document_id: UUID | None,
        document_version_id: UUID | None,
        job_status: str | None,
        limit: int,
        offset: int,
    ) -> tuple[list[ProcessingJob], int]:
        assert document_id == DOCUMENT_ID
        assert document_version_id is None
        assert job_status == "FAILED"
        assert limit == 50
        assert offset == 0
        return [_processing_job()], 1

    async def get_processing_job_detail(self, job_id: UUID) -> ProcessingJobDetail | None:
        assert job_id == CHUNK_ID
        return ProcessingJobDetail(
            job=_processing_job(),
            stage_history=(
                ProcessingStageHistory(
                    id=1,
                    processing_job_id=CHUNK_ID,
                    stage="EXTRACTION",
                    status="FAILED",
                    started_at=NOW,
                    completed_at=NOW,
                    message="Extraction failed",
                ),
            ),
            errors=(
                ProcessingError(
                    id=CITATION_ID,
                    processing_job_id=CHUNK_ID,
                    stage="EXTRACTION",
                    error_type="ParserError",
                    error_code="PARSER_FAILED",
                    safe_message="The source could not be parsed",
                    retryable=True,
                    created_at=NOW,
                ),
            ),
        )

    async def get_version_review_context(
        self, version_id: UUID
    ) -> DocumentVersionReviewContext | None:
        assert version_id == VERSION_ID
        return DocumentVersionReviewContext(
            document=_document(status="DRAFT"),
            version=DocumentVersion(
                id=VERSION_ID,
                document_id=DOCUMENT_ID,
                version_number=1,
                source_file_id=CITATION_ID,
                status="READY_FOR_REVIEW",
                previous_version_id=None,
                change_summary=None,
                effective_date=None,
                created_by=USER_ID,
                created_at=NOW,
                updated_at=NOW,
            ),
            source_file=ReviewSourceFile(
                id=CITATION_ID,
                original_file_name="policy.pdf",
                mime_type="application/pdf",
                size_bytes=16,
                sha256="a" * 64,
                created_by=USER_ID,
                created_at=NOW,
            ),
            latest_processing_job=_processing_job(status="SUCCEEDED"),
            extracted_chunks=(
                ReviewChunk(
                    chunk_id=CHUNK_ID,
                    chunk_index=0,
                    content="Employees receive annual leave.",
                    page_start=2,
                    page_end=2,
                    section_path="Leave",
                    metadata={},
                ),
            ),
        )


class SourceFileServiceStub:
    async def upload_initial_document(
        self, *args: object, **kwargs: object
    ) -> InitialDocumentUpload:
        return InitialDocumentUpload(
            document=_document(status="DRAFT"),
            version=DocumentVersion(
                id=VERSION_ID,
                document_id=DOCUMENT_ID,
                version_number=1,
                source_file_id=CITATION_ID,
                status="DRAFT",
                previous_version_id=None,
                change_summary=None,
                effective_date=None,
                created_by=USER_ID,
                created_at=NOW,
                updated_at=NOW,
            ),
            processing_job=_processing_job(status="PENDING"),
            source_file=SourceFile(
                id=CITATION_ID,
                bucket_name="knowledge-source-files",
                object_path=f"{USER_ID}/{CITATION_ID}/policy.pdf",
                original_file_name="policy.pdf",
                mime_type="application/pdf",
                size_bytes=16,
                sha256="a" * 64,
                created_by=USER_ID,
                created_at=NOW,
            ),
        )


class GovernanceServiceStub:
    async def search(
        self, query: str, *, limit: int, filters: dict[str, object]
    ) -> list[SearchHit]:
        assert query == "policy"
        assert limit == 3
        assert filters == {}
        return [
            SearchHit(
                chunk_id=CHUNK_ID,
                document_id=DOCUMENT_ID,
                document_version_id=VERSION_ID,
                title="Policy",
                content="Grounded evidence",
                score=0.8,
            )
        ]

    async def get_conversation(self, conversation_id: UUID) -> ConversationDetail:
        conversation = EnterpriseConversation(
            id=conversation_id,
            user_id=USER_ID,
            title="Policy",
            created_at=NOW,
            updated_at=NOW,
        )
        user_message = EnterpriseMessage(
            id=USER_MESSAGE_ID,
            conversation_id=conversation_id,
            role="USER",
            content="What is the policy?",
            created_at=NOW,
            answer_status="COMPLETED",
        )
        answer_message = EnterpriseMessage(
            id=ANSWER_MESSAGE_ID,
            conversation_id=conversation_id,
            role="ASSISTANT",
            content="Grounded answer [SRC-1]",
            created_at=NOW,
            answer_status="COMPLETED",
            error_code="CITATION_RETRY_RECOVERED",
            citations=(
                EnterpriseCitation(
                    id=CITATION_ID,
                    answer_message_id=ANSWER_MESSAGE_ID,
                    document_id=DOCUMENT_ID,
                    document_version_id=VERSION_ID,
                    chunk_id=CHUNK_ID,
                    quote_text="Grounded evidence",
                    citation_order=1,
                    page_number=2,
                    document_title="Policy",
                    section_path="Scope",
                ),
            ),
        )
        return ConversationDetail(
            conversation=conversation,
            messages=(user_message, answer_message),
        )


class QuestionServiceStub:
    async def ask_question(
        self,
        conversation_id: UUID,
        question: str,
        *,
        filters: dict[str, object],
        trace_id: str | None = None,
        user_id: UUID | None = None,
    ) -> AskQuestionResult:
        assert conversation_id == CONVERSATION_ID
        assert question == "What is the policy?"
        assert filters == {}
        assert user_id == USER_ID
        user_message = EnterpriseMessage(
            id=USER_MESSAGE_ID,
            conversation_id=conversation_id,
            role="USER",
            content=question,
            created_at=NOW,
            answer_status="COMPLETED",
        )
        answer_message = EnterpriseMessage(
            id=ANSWER_MESSAGE_ID,
            conversation_id=conversation_id,
            role="ASSISTANT",
            content="Grounded answer [SRC-1]",
            created_at=NOW,
            answer_status="COMPLETED",
        )
        citation = EnterpriseCitation(
            id=CITATION_ID,
            answer_message_id=ANSWER_MESSAGE_ID,
            document_id=DOCUMENT_ID,
            document_version_id=VERSION_ID,
            chunk_id=CHUNK_ID,
            quote_text="Grounded evidence",
            citation_order=1,
            page_number=2,
            document_title="Policy",
            section_path="Scope",
        )
        return AskQuestionResult(
            user_message=user_message,
            assistant_message=answer_message,
            citations=(citation,),
            retrieval_strategy="secure_keyword",
            evidence_count=1,
            candidate_count=3,
            trace_id=trace_id,
        )


def _document(status: str = "PUBLISHED") -> KnowledgeDocument:
    return KnowledgeDocument(
        id=DOCUMENT_ID,
        title="Policy",
        description=None,
        document_type="POLICY",
        category="HR",
        document_number=None,
        issued_date=None,
        effective_date=None,
        expiration_date=None,
        source=None,
        owner_department_id=None,
        status=status,
        current_version_id=VERSION_ID if status == "PUBLISHED" else None,
        created_by=USER_ID,
        created_at=NOW,
        updated_at=NOW,
    )


def _processing_job(status: str = "FAILED") -> ProcessingJob:
    return ProcessingJob(
        id=CHUNK_ID,
        document_version_id=VERSION_ID,
        job_type="INITIAL_PROCESS",
        status=status,
        current_stage="EXTRACTION",
        attempt_no=1,
        previous_job_id=None,
        requested_by=USER_ID,
        requested_at=NOW,
        started_at=NOW,
        completed_at=NOW if status in {"FAILED", "SUCCEEDED", "CANCELLED"} else None,
        heartbeat_at=NOW,
        lease_owner=None,
        lease_expires_at=None,
        error_code="PARSER_FAILED" if status == "FAILED" else None,
        error_message="The source could not be parsed" if status == "FAILED" else None,
    )


def _app(document: KnowledgeDocument | None = None) -> FastAPI:
    app = FastAPI()
    app.middleware("http")(request_id_middleware)
    install_enterprise_error_contract(app)
    app.include_router(enterprise_identity.router)
    app.include_router(enterprise_documents.router)
    app.include_router(enterprise_governance.router)

    async def user() -> CurrentUser:
        return CurrentUser(id=str(USER_ID), email="user@example.test", user_role="user")

    app.dependency_overrides[get_current_user] = user
    app.dependency_overrides[get_identity_service] = lambda: IdentityServiceStub()
    app.dependency_overrides[get_enterprise_document_service] = lambda: DocumentServiceStub(
        document
    )
    app.dependency_overrides[get_governance_service] = lambda: GovernanceServiceStub()
    app.dependency_overrides[get_enterprise_question_service] = lambda: QuestionServiceStub()
    app.dependency_overrides[get_enterprise_source_file_service] = lambda: SourceFileServiceStub()
    app.dependency_overrides[require_manage_document] = lambda: PrincipalContext(
        user_id=USER_ID,
        email="user@example.test",
        status="ACTIVE",
        permissions=frozenset({"MANAGE_DOCUMENT"}),
    )
    app.dependency_overrides[require_upload_document] = lambda: PrincipalContext(
        user_id=USER_ID,
        email="user@example.test",
        status="ACTIVE",
        permissions=frozenset({"UPLOAD_DOCUMENT"}),
    )
    app.dependency_overrides[require_review_workspace] = lambda: PrincipalContext(
        user_id=USER_ID,
        email="user@example.test",
        status="ACTIVE",
        permissions=frozenset({"REVIEW_DOCUMENT"}),
    )
    return app


@pytest.mark.anyio
async def test_me_and_document_detail_use_stable_v1_shapes() -> None:
    transport = httpx.ASGITransport(app=_app(_document()))
    async with httpx.AsyncClient(transport=transport, base_url="https://api.test") as client:
        principal = await client.get("/api/v1/me", headers={"X-Request-ID": "request-123"})
        document = await client.get(f"/api/v1/documents/{DOCUMENT_ID}")

    assert principal.status_code == 200
    assert principal.json()["permissions"] == ["ASK_KNOWLEDGE"]
    assert principal.headers["X-Request-ID"] == "request-123"
    assert document.status_code == 200
    assert document.json()["current_version_id"] == str(VERSION_ID)


@pytest.mark.anyio
async def test_document_list_accepts_admin_portal_page_size() -> None:
    transport = httpx.ASGITransport(app=_app(_document()))
    async with httpx.AsyncClient(transport=transport, base_url="https://api.test") as client:
        response = await client.get("/api/v1/documents?limit=200")

    assert response.status_code == 200
    assert response.json()["limit"] == 200
    assert response.json()["items"][0]["id"] == str(DOCUMENT_ID)


@pytest.mark.anyio
async def test_v1_not_found_uses_standard_error_contract() -> None:
    transport = httpx.ASGITransport(app=_app(None))
    async with httpx.AsyncClient(transport=transport, base_url="https://api.test") as client:
        response = await client.get(f"/api/v1/documents/{DOCUMENT_ID}")

    assert response.status_code == 404
    assert response.json()["error"]["code"] == "HTTP_404"
    assert response.json()["error"]["message"] == "Document not found"
    assert response.json()["error"]["trace_id"] == response.headers["X-Request-ID"]


@pytest.mark.anyio
async def test_search_returns_version_bound_evidence() -> None:
    transport = httpx.ASGITransport(app=_app(_document()))
    async with httpx.AsyncClient(transport=transport, base_url="https://api.test") as client:
        response = await client.post(
            "/api/v1/search", json={"query": "policy", "limit": 3, "filters": {}}
        )

    assert response.status_code == 200
    assert response.json()["items"][0]["document_version_id"] == str(VERSION_ID)


@pytest.mark.anyio
async def test_question_endpoint_returns_frontend_answer_contract() -> None:
    transport = httpx.ASGITransport(app=_app(_document()))
    async with httpx.AsyncClient(transport=transport, base_url="https://api.test") as client:
        response = await client.post(
            f"/api/v1/conversations/{CONVERSATION_ID}/messages",
            json={"content": "What is the policy?", "filters": {}},
            headers={"X-Request-ID": "question-trace"},
        )

    assert response.status_code == 201
    payload = response.json()
    assert payload["message_id"] == str(ANSWER_MESSAGE_ID)
    assert payload["answer_status"] == "ANSWERED"
    assert payload["retrieval"] == {
        "strategy": "secure_keyword",
        "candidate_count": 3,
        "evidence_count": 1,
        "gate_reason": None,
    }
    assert payload["error_code"] is None
    assert payload["citations"][0] == {
        "document_id": str(DOCUMENT_ID),
        "document_version_id": str(VERSION_ID),
        "document_title": "Policy",
        "chunk_id": str(CHUNK_ID),
        "page": 2,
        "section": "Scope",
    }
    assert payload["trace_id"] == "question-trace"


@pytest.mark.anyio
async def test_conversation_history_normalizes_internal_answer_statuses() -> None:
    transport = httpx.ASGITransport(app=_app(_document()))
    async with httpx.AsyncClient(transport=transport, base_url="https://api.test") as client:
        response = await client.get(f"/api/v1/conversations/{CONVERSATION_ID}")

    assert response.status_code == 200
    messages = response.json()["messages"]
    assert messages[0]["answer_status"] is None
    assert messages[1]["answer_status"] == "ANSWERED"
    assert messages[1]["error_code"] == "CITATION_RETRY_RECOVERED"
    assert messages[1]["citations"][0]["document_version_id"] == str(VERSION_ID)


@pytest.mark.anyio
async def test_initial_upload_returns_document_version_job_and_source_atomically() -> None:
    transport = httpx.ASGITransport(app=_app(_document()))
    async with httpx.AsyncClient(transport=transport, base_url="https://api.test") as client:
        response = await client.post(
            "/api/v1/documents/upload",
            data={"title": "Policy", "metadata_json": '{"owner":"HR"}'},
            files={"file": ("policy.pdf", b"%PDF-1.7\ncontent", "application/pdf")},
        )

    assert response.status_code == 201
    payload = response.json()
    assert payload["document"]["id"] == str(DOCUMENT_ID)
    assert payload["version"]["version_number"] == 1
    assert payload["processing_job"]["status"] == "PENDING"
    assert payload["source_file"]["original_file_name"] == "policy.pdf"


@pytest.mark.anyio
async def test_processing_monitor_discovers_jobs_and_safe_history_by_document() -> None:
    transport = httpx.ASGITransport(app=_app(_document()))
    async with httpx.AsyncClient(transport=transport, base_url="https://api.test") as client:
        listing = await client.get(
            f"/api/v1/processing-jobs?document_id={DOCUMENT_ID}&status=FAILED"
        )
        detail = await client.get(f"/api/v1/processing-jobs/{CHUNK_ID}")

    assert listing.status_code == 200
    assert listing.json()["total_count"] == 1
    assert listing.json()["items"][0]["document_version_id"] == str(VERSION_ID)
    assert detail.status_code == 200
    assert detail.json()["stage_history"][0]["stage"] == "EXTRACTION"
    assert detail.json()["errors"][0]["safe_message"] == "The source could not be parsed"


@pytest.mark.anyio
async def test_review_workspace_returns_candidate_content_and_processing_context() -> None:
    transport = httpx.ASGITransport(app=_app(_document()))
    async with httpx.AsyncClient(transport=transport, base_url="https://api.test") as client:
        response = await client.get(f"/api/v1/document-versions/{VERSION_ID}/review-context")

    assert response.status_code == 200
    payload = response.json()
    assert payload["version"]["status"] == "READY_FOR_REVIEW"
    assert payload["source_file"]["original_file_name"] == "policy.pdf"
    assert payload["latest_processing_job"]["status"] == "SUCCEEDED"
    assert payload["extracted_chunks"][0]["page_start"] == 2
