"""Enterprise API v1 logical-document, version, ACL and processing routes."""

from __future__ import annotations

import json
from datetime import UTC, date, datetime, timedelta
from typing import Annotated, Literal
from uuid import UUID

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, UploadFile, status

from app.api.dependencies.auth import get_current_user
from app.api.dependencies.enterprise import (
    get_enterprise_document_service,
    get_enterprise_source_file_service,
    get_source_url_signer,
    require_archive_document,
    require_manage_access_policy,
    require_manage_document,
    require_publish_document,
    require_review_document,
    require_review_workspace,
    require_upload_document,
)
from app.api.schemas.auth import CurrentUser
from app.api.schemas.enterprise import (
    AccessTestRequest,
    AccessTestResponse,
    ArchiveDocumentRequest,
    DocumentPermissionLiteral,
    DocumentVersionCreateRequest,
    DocumentVersionResponse,
    DocumentVersionReviewContextResponse,
    InitialDocumentUploadResponse,
    KnowledgeDocumentCreateRequest,
    KnowledgeDocumentListResponse,
    KnowledgeDocumentResponse,
    KnowledgeDocumentUpdateRequest,
    OperationResponse,
    PermissionGrantRequest,
    PermissionResponse,
    ProcessingErrorResponse,
    ProcessingJobDetailResponse,
    ProcessingJobListResponse,
    ProcessingJobResponse,
    ProcessingStageHistoryResponse,
    ReviewChunkResponse,
    ReviewSourceFileResponse,
    SourceFileResponse,
    VersionReviewRequest,
    VersionSourceResponse,
)
from app.documents.application.enterprise_services import (
    EnterpriseDocumentService,
    EnterpriseDocumentValidationError,
    EnterpriseSourceFileService,
)
from app.documents.ports.enterprise_repositories import (
    NewDocumentVersion,
    NewKnowledgeDocument,
)
from app.documents.ports.source_signing import SourceUrlSigner
from app.identity.domain.models import PrincipalContext

router = APIRouter(prefix="/api/v1", tags=["enterprise-documents"])
SOURCE_URL_TTL_SECONDS = 300


@router.post(
    "/source-files",
    response_model=SourceFileResponse,
    status_code=status.HTTP_201_CREATED,
)
async def upload_source_file(
    file: Annotated[UploadFile, File(...)],
    principal: Annotated[PrincipalContext, Depends(require_upload_document)],
    service: Annotated[
        EnterpriseSourceFileService,
        Depends(get_enterprise_source_file_service),
    ],
) -> SourceFileResponse:
    filename = file.filename or "source.bin"
    content = await file.read()
    source = await service.upload(principal.user_id, filename, content)
    return SourceFileResponse.model_validate(source)


@router.post(
    "/documents/upload",
    response_model=InitialDocumentUploadResponse,
    status_code=status.HTTP_201_CREATED,
)
async def upload_initial_document(
    file: Annotated[UploadFile, File(...)],
    title: Annotated[str, Form(min_length=1, max_length=500)],
    principal: Annotated[PrincipalContext, Depends(require_upload_document)],
    service: Annotated[
        EnterpriseSourceFileService,
        Depends(get_enterprise_source_file_service),
    ],
    description: Annotated[str | None, Form(max_length=5000)] = None,
    document_type: Annotated[str | None, Form(max_length=100)] = None,
    category: Annotated[str | None, Form(max_length=100)] = None,
    metadata_json: Annotated[str, Form(max_length=50000)] = "{}",
    change_summary: Annotated[str | None, Form(max_length=5000)] = None,
    effective_date: Annotated[date | None, Form()] = None,
) -> InitialDocumentUploadResponse:
    try:
        raw_metadata = json.loads(metadata_json)
    except json.JSONDecodeError as exc:
        raise EnterpriseDocumentValidationError(
            "INVALID_METADATA", "Metadata must be a JSON object"
        ) from exc
    if not isinstance(raw_metadata, dict):
        raise EnterpriseDocumentValidationError(
            "INVALID_METADATA", "Metadata must be a JSON object"
        )
    metadata: dict[str, object] = {str(key): value for key, value in raw_metadata.items()}
    filename = file.filename or "source.bin"
    result = await service.upload_initial_document(
        principal.user_id,
        filename,
        await file.read(),
        document=NewKnowledgeDocument(
            title=title,
            description=description,
            document_type=document_type,
            category=category,
            metadata=metadata,
        ),
        change_summary=change_summary,
        effective_date=effective_date,
    )
    return InitialDocumentUploadResponse(
        document=KnowledgeDocumentResponse.model_validate(result.document),
        version=DocumentVersionResponse.model_validate(result.version),
        processing_job=ProcessingJobResponse.model_validate(result.processing_job),
        source_file=SourceFileResponse.model_validate(result.source_file),
    )


@router.get("/documents", response_model=KnowledgeDocumentListResponse)
async def list_documents(
    _user: Annotated[CurrentUser, Depends(get_current_user)],
    service: Annotated[EnterpriseDocumentService, Depends(get_enterprise_document_service)],
    document_status: Annotated[
        Literal["DRAFT", "PUBLISHED", "ARCHIVED"] | None, Query(alias="status")
    ] = None,
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> KnowledgeDocumentListResponse:
    documents, total = await service.list_documents(
        document_status=document_status, limit=limit, offset=offset
    )
    return KnowledgeDocumentListResponse(
        items=[KnowledgeDocumentResponse.model_validate(item) for item in documents],
        total_count=total,
        limit=limit,
        offset=offset,
    )


@router.post(
    "/documents",
    response_model=KnowledgeDocumentResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_document(
    payload: KnowledgeDocumentCreateRequest,
    _principal: Annotated[PrincipalContext, Depends(require_manage_document)],
    service: Annotated[EnterpriseDocumentService, Depends(get_enterprise_document_service)],
) -> KnowledgeDocumentResponse:
    document = await service.create_document(NewKnowledgeDocument(**payload.model_dump()))
    return KnowledgeDocumentResponse.model_validate(document)


@router.get("/documents/{document_id}", response_model=KnowledgeDocumentResponse)
async def get_document(
    document_id: UUID,
    _user: Annotated[CurrentUser, Depends(get_current_user)],
    service: Annotated[EnterpriseDocumentService, Depends(get_enterprise_document_service)],
) -> KnowledgeDocumentResponse:
    document = await service.get_document(document_id)
    if document is None:
        raise HTTPException(status_code=404, detail="Document not found")
    return KnowledgeDocumentResponse.model_validate(document)


@router.patch("/documents/{document_id}", response_model=KnowledgeDocumentResponse)
async def update_document(
    document_id: UUID,
    payload: KnowledgeDocumentUpdateRequest,
    _principal: Annotated[PrincipalContext, Depends(require_manage_document)],
    service: Annotated[EnterpriseDocumentService, Depends(get_enterprise_document_service)],
) -> KnowledgeDocumentResponse:
    document = await service.update_document(
        document_id, payload.model_dump(mode="json", exclude_unset=True)
    )
    if document is None:
        raise HTTPException(status_code=404, detail="Document not found")
    return KnowledgeDocumentResponse.model_validate(document)


@router.get("/documents/{document_id}/versions", response_model=list[DocumentVersionResponse])
async def list_document_versions(
    document_id: UUID,
    _user: Annotated[CurrentUser, Depends(get_current_user)],
    service: Annotated[EnterpriseDocumentService, Depends(get_enterprise_document_service)],
) -> list[DocumentVersionResponse]:
    return [
        DocumentVersionResponse.model_validate(item)
        for item in await service.list_versions(document_id)
    ]


@router.get(
    "/document-versions/{version_id}/review-context",
    response_model=DocumentVersionReviewContextResponse,
)
async def get_document_version_review_context(
    version_id: UUID,
    _principal: Annotated[PrincipalContext, Depends(require_review_workspace)],
    service: Annotated[EnterpriseDocumentService, Depends(get_enterprise_document_service)],
) -> DocumentVersionReviewContextResponse:
    context = await service.get_version_review_context(version_id)
    if context is None:
        raise HTTPException(status_code=404, detail="Document version review context not found")
    return DocumentVersionReviewContextResponse(
        document=KnowledgeDocumentResponse.model_validate(context.document),
        version=DocumentVersionResponse.model_validate(context.version),
        source_file=ReviewSourceFileResponse.model_validate(context.source_file),
        latest_processing_job=(
            ProcessingJobResponse.model_validate(context.latest_processing_job)
            if context.latest_processing_job is not None
            else None
        ),
        stage_history=[
            ProcessingStageHistoryResponse.model_validate(item) for item in context.stage_history
        ],
        errors=[ProcessingErrorResponse.model_validate(item) for item in context.errors],
        extracted_chunks=[
            ReviewChunkResponse.model_validate(item) for item in context.extracted_chunks
        ],
    )


@router.post(
    "/documents/{document_id}/versions",
    response_model=DocumentVersionResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_document_version(
    document_id: UUID,
    payload: DocumentVersionCreateRequest,
    _principal: Annotated[PrincipalContext, Depends(require_manage_document)],
    service: Annotated[EnterpriseDocumentService, Depends(get_enterprise_document_service)],
) -> DocumentVersionResponse:
    version = await service.create_version(
        NewDocumentVersion(document_id=document_id, **payload.model_dump())
    )
    return DocumentVersionResponse.model_validate(version)


@router.get(
    "/documents/{document_id}/versions/{version_id}/source",
    response_model=VersionSourceResponse,
)
async def get_version_source(
    document_id: UUID,
    version_id: UUID,
    _user: Annotated[CurrentUser, Depends(get_current_user)],
    service: Annotated[EnterpriseDocumentService, Depends(get_enterprise_document_service)],
    signer: Annotated[SourceUrlSigner, Depends(get_source_url_signer)],
) -> VersionSourceResponse:
    source = await service.get_version_source(document_id, version_id)
    if source is None:
        # The RPC intentionally does not distinguish missing from unauthorized.
        raise HTTPException(status_code=404, detail="Document version source not found")
    url = await signer.sign(
        source.bucket_name, source.object_path, expires_in=SOURCE_URL_TTL_SECONDS
    )
    return VersionSourceResponse(
        signed_url=url,
        expires_at=datetime.now(UTC) + timedelta(seconds=SOURCE_URL_TTL_SECONDS),
        original_file_name=source.original_file_name,
        mime_type=source.mime_type,
    )


@router.post("/document-versions/{version_id}/review", response_model=DocumentVersionResponse)
async def review_document_version(
    version_id: UUID,
    payload: VersionReviewRequest,
    _principal: Annotated[PrincipalContext, Depends(require_review_document)],
    service: Annotated[EnterpriseDocumentService, Depends(get_enterprise_document_service)],
) -> DocumentVersionResponse:
    version = await service.review_version(version_id, **payload.model_dump())
    return DocumentVersionResponse.model_validate(version)


@router.post("/document-versions/{version_id}/publish", response_model=DocumentVersionResponse)
async def publish_document_version(
    version_id: UUID,
    _principal: Annotated[PrincipalContext, Depends(require_publish_document)],
    service: Annotated[EnterpriseDocumentService, Depends(get_enterprise_document_service)],
) -> DocumentVersionResponse:
    version = await service.publish_version(version_id)
    return DocumentVersionResponse.model_validate(version)


@router.post("/documents/{document_id}/archive", response_model=KnowledgeDocumentResponse)
async def archive_document(
    document_id: UUID,
    payload: ArchiveDocumentRequest,
    _principal: Annotated[PrincipalContext, Depends(require_archive_document)],
    service: Annotated[EnterpriseDocumentService, Depends(get_enterprise_document_service)],
) -> KnowledgeDocumentResponse:
    document = await service.archive_document(document_id, reason=payload.reason)
    return KnowledgeDocumentResponse.model_validate(document)


@router.get("/documents/{document_id}/permissions", response_model=list[PermissionResponse])
async def list_document_permissions(
    document_id: UUID,
    _principal: Annotated[PrincipalContext, Depends(require_manage_access_policy)],
    service: Annotated[EnterpriseDocumentService, Depends(get_enterprise_document_service)],
) -> list[PermissionResponse]:
    return [
        PermissionResponse.model_validate(item)
        for item in await service.list_permissions(document_id)
    ]


@router.post(
    "/documents/{document_id}/permissions",
    response_model=PermissionResponse,
    status_code=status.HTTP_201_CREATED,
)
async def grant_document_permission(
    document_id: UUID,
    payload: PermissionGrantRequest,
    _principal: Annotated[PrincipalContext, Depends(require_manage_access_policy)],
    service: Annotated[EnterpriseDocumentService, Depends(get_enterprise_document_service)],
) -> PermissionResponse:
    assignment = await service.grant_permission(document_id, payload.subject_id, payload.permission)
    return PermissionResponse.model_validate(assignment)


@router.delete("/documents/{document_id}/permissions", response_model=OperationResponse)
async def revoke_document_permission(
    document_id: UUID,
    subject_id: Annotated[UUID, Query()],
    permission: Annotated[DocumentPermissionLiteral, Query()],
    _principal: Annotated[PrincipalContext, Depends(require_manage_access_policy)],
    service: Annotated[EnterpriseDocumentService, Depends(get_enterprise_document_service)],
) -> OperationResponse:
    await service.revoke_permission(document_id, subject_id, permission)
    return OperationResponse(message="Permission revoked")


@router.post("/documents/{document_id}/permissions/test", response_model=AccessTestResponse)
async def test_document_access(
    document_id: UUID,
    payload: AccessTestRequest,
    _principal: Annotated[PrincipalContext, Depends(require_manage_access_policy)],
    service: Annotated[EnterpriseDocumentService, Depends(get_enterprise_document_service)],
) -> AccessTestResponse:
    decision = await service.explain_access(payload.user_id, document_id, payload.permission)
    return AccessTestResponse(allowed=decision.allowed, sources=list(decision.sources))


@router.get("/processing-jobs", response_model=ProcessingJobListResponse)
async def list_processing_jobs(
    _principal: Annotated[PrincipalContext, Depends(require_manage_document)],
    service: Annotated[EnterpriseDocumentService, Depends(get_enterprise_document_service)],
    document_id: Annotated[UUID | None, Query()] = None,
    document_version_id: Annotated[UUID | None, Query()] = None,
    job_status: Annotated[
        Literal["PENDING", "RUNNING", "SUCCEEDED", "FAILED", "CANCELLED"] | None,
        Query(alias="status"),
    ] = None,
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> ProcessingJobListResponse:
    jobs, total = await service.list_processing_jobs(
        document_id=document_id,
        document_version_id=document_version_id,
        job_status=job_status,
        limit=limit,
        offset=offset,
    )
    return ProcessingJobListResponse(
        items=[ProcessingJobResponse.model_validate(job) for job in jobs],
        total_count=total,
        limit=limit,
        offset=offset,
    )


@router.get("/processing-jobs/{job_id}", response_model=ProcessingJobDetailResponse)
async def get_processing_job(
    job_id: UUID,
    _principal: Annotated[PrincipalContext, Depends(require_manage_document)],
    service: Annotated[EnterpriseDocumentService, Depends(get_enterprise_document_service)],
) -> ProcessingJobDetailResponse:
    detail = await service.get_processing_job_detail(job_id)
    if detail is None:
        raise HTTPException(status_code=404, detail="Processing job not found")
    job = ProcessingJobResponse.model_validate(detail.job)
    return ProcessingJobDetailResponse(
        **job.model_dump(),
        stage_history=[
            ProcessingStageHistoryResponse.model_validate(item) for item in detail.stage_history
        ],
        errors=[ProcessingErrorResponse.model_validate(item) for item in detail.errors],
    )


@router.post("/processing-jobs/{job_id}/retry", response_model=ProcessingJobResponse)
async def retry_processing_job(
    job_id: UUID,
    _principal: Annotated[PrincipalContext, Depends(require_manage_document)],
    service: Annotated[EnterpriseDocumentService, Depends(get_enterprise_document_service)],
) -> ProcessingJobResponse:
    return ProcessingJobResponse.model_validate(await service.retry_processing_job(job_id))
