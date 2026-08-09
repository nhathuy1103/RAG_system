"""Enterprise API v1 search, conversation, feedback and governance routes."""

from __future__ import annotations

from typing import Annotated, Literal
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status

from app.api.dependencies.enterprise import (
    get_enterprise_question_service,
    get_governance_service,
    require_ask_knowledge,
    require_governance_access,
    require_manage_report,
    require_view_analytics,
)
from app.api.enterprise_errors import request_trace_id
from app.api.schemas.enterprise import (
    AnalyticsSummaryResponse,
    AnswerReportCreateRequest,
    AnswerReportListResponse,
    AnswerReportResolutionRequest,
    AnswerReportResponse,
    AnswerRetrievalResponse,
    AskQuestionResponse,
    AuditLogListResponse,
    AuditLogResponse,
    ConversationCreateRequest,
    ConversationDetailResponse,
    ConversationResponse,
    EnterpriseCitationResponse,
    FeedbackCreateRequest,
    FeedbackResponse,
    MessageCreateRequest,
    MessageResponse,
    SearchHitResponse,
    SearchRequest,
    SearchResponse,
)
from app.governance.application.services import EnterpriseQuestionService, GovernanceService
from app.governance.domain.models import EnterpriseMessage
from app.identity.domain.models import PrincipalContext

router = APIRouter(prefix="/api/v1", tags=["enterprise-knowledge"])


@router.post("/search", response_model=SearchResponse)
async def search_enterprise_knowledge(
    payload: SearchRequest,
    _principal: Annotated[PrincipalContext, Depends(require_ask_knowledge)],
    service: Annotated[GovernanceService, Depends(get_governance_service)],
) -> SearchResponse:
    hits = await service.search(payload.query, limit=payload.limit, filters=payload.filters)
    return SearchResponse(items=[SearchHitResponse.model_validate(hit) for hit in hits])


@router.post(
    "/conversations",
    response_model=ConversationResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_conversation(
    payload: ConversationCreateRequest,
    _principal: Annotated[PrincipalContext, Depends(require_ask_knowledge)],
    service: Annotated[GovernanceService, Depends(get_governance_service)],
) -> ConversationResponse:
    return ConversationResponse.model_validate(await service.create_conversation(payload.title))


@router.get("/conversations/{conversation_id}", response_model=ConversationDetailResponse)
async def get_conversation(
    conversation_id: UUID,
    _principal: Annotated[PrincipalContext, Depends(require_ask_knowledge)],
    service: Annotated[GovernanceService, Depends(get_governance_service)],
) -> ConversationDetailResponse:
    detail = await service.get_conversation(conversation_id)
    if detail is None:
        raise HTTPException(status_code=404, detail="Conversation not found")
    return ConversationDetailResponse(
        conversation=ConversationResponse.model_validate(detail.conversation),
        messages=[_message_response(item) for item in detail.messages],
    )


@router.post(
    "/conversations/{conversation_id}/messages",
    response_model=AskQuestionResponse,
    status_code=status.HTTP_201_CREATED,
)
async def append_conversation_message(
    conversation_id: UUID,
    payload: MessageCreateRequest,
    request: Request,
    _principal: Annotated[PrincipalContext, Depends(require_ask_knowledge)],
    service: Annotated[
        EnterpriseQuestionService,
        Depends(get_enterprise_question_service),
    ],
) -> AskQuestionResponse:
    result = await service.ask_question(
        conversation_id,
        payload.content,
        filters=payload.filters,
        trace_id=request_trace_id(request),
    )
    status_value: Literal["ANSWERED", "INSUFFICIENT_EVIDENCE", "FAILED"]
    if result.assistant_message.answer_status == "COMPLETED":
        status_value = "ANSWERED"
    elif result.assistant_message.answer_status == "CONTROLLED_NO_ANSWER":
        status_value = "INSUFFICIENT_EVIDENCE"
    else:
        status_value = "FAILED"
    return AskQuestionResponse(
        conversation_id=conversation_id,
        message_id=result.assistant_message.id,
        answer=result.assistant_message.content,
        answer_status=status_value,
        citations=[
            EnterpriseCitationResponse(
                document_id=item.document_id,
                document_version_id=item.document_version_id,
                document_title=item.document_title,
                chunk_id=item.chunk_id,
                page=item.page_number,
                section=item.section_path,
            )
            for item in result.citations
        ],
        retrieval=AnswerRetrievalResponse(
            strategy=result.retrieval_strategy,
            evidence_count=result.evidence_count,
        ),
        trace_id=result.trace_id,
    )


@router.post(
    "/answers/{message_id}/feedback",
    response_model=FeedbackResponse,
    status_code=status.HTTP_201_CREATED,
)
async def submit_answer_feedback(
    message_id: UUID,
    payload: FeedbackCreateRequest,
    principal: Annotated[PrincipalContext, Depends(require_ask_knowledge)],
    service: Annotated[GovernanceService, Depends(get_governance_service)],
) -> FeedbackResponse:
    feedback = await service.submit_feedback(
        message_id,
        principal.user_id,
        rating=payload.rating,
        comment=payload.comment,
    )
    return FeedbackResponse.model_validate(feedback)


@router.post(
    "/answers/{message_id}/reports",
    response_model=AnswerReportResponse,
    status_code=status.HTTP_201_CREATED,
)
async def report_answer(
    message_id: UUID,
    payload: AnswerReportCreateRequest,
    principal: Annotated[PrincipalContext, Depends(require_ask_knowledge)],
    service: Annotated[GovernanceService, Depends(get_governance_service)],
) -> AnswerReportResponse:
    report = await service.submit_report(
        message_id,
        principal.user_id,
        reason_code=payload.reason_code,
        details=payload.details,
    )
    return AnswerReportResponse.model_validate(report)


@router.get("/audit-logs", response_model=AuditLogListResponse)
async def list_audit_logs(
    _principal: Annotated[PrincipalContext, Depends(require_governance_access)],
    service: Annotated[GovernanceService, Depends(get_governance_service)],
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> AuditLogListResponse:
    items, total = await service.list_audit_logs(limit=limit, offset=offset)
    return AuditLogListResponse(
        items=[AuditLogResponse.model_validate(item) for item in items],
        total_count=total,
        limit=limit,
        offset=offset,
    )


@router.get("/analytics/summary", response_model=AnalyticsSummaryResponse)
async def get_analytics_summary(
    _principal: Annotated[PrincipalContext, Depends(require_view_analytics)],
    service: Annotated[GovernanceService, Depends(get_governance_service)],
) -> AnalyticsSummaryResponse:
    return AnalyticsSummaryResponse.model_validate(await service.analytics_summary())


@router.get("/answer-reports", response_model=AnswerReportListResponse)
async def list_answer_reports(
    _principal: Annotated[PrincipalContext, Depends(require_governance_access)],
    service: Annotated[GovernanceService, Depends(get_governance_service)],
    report_status: Annotated[
        Literal["OPEN", "INVESTIGATING", "RESOLVED", "DISMISSED"] | None,
        Query(alias="status"),
    ] = None,
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> AnswerReportListResponse:
    items, total = await service.list_answer_reports(
        report_status=report_status, limit=limit, offset=offset
    )
    return AnswerReportListResponse(
        items=[AnswerReportResponse.model_validate(item) for item in items],
        total_count=total,
        limit=limit,
        offset=offset,
    )


@router.patch("/answer-reports/{report_id}", response_model=AnswerReportResponse)
async def resolve_answer_report(
    report_id: UUID,
    payload: AnswerReportResolutionRequest,
    _principal: Annotated[PrincipalContext, Depends(require_manage_report)],
    service: Annotated[GovernanceService, Depends(get_governance_service)],
) -> AnswerReportResponse:
    report = await service.resolve_answer_report(
        report_id,
        status=payload.status,
        resolution_note=payload.resolution_note,
    )
    if report is None:
        raise HTTPException(status_code=404, detail="Answer report not found")
    return AnswerReportResponse.model_validate(report)


def _message_response(item: EnterpriseMessage) -> MessageResponse:
    role = item.role
    internal_status = item.answer_status
    public_status: Literal["ANSWERED", "INSUFFICIENT_EVIDENCE", "FAILED"] | None
    if role != "ASSISTANT":
        public_status = None
    elif internal_status == "COMPLETED":
        public_status = "ANSWERED"
    elif internal_status == "CONTROLLED_NO_ANSWER":
        public_status = "INSUFFICIENT_EVIDENCE"
    else:
        public_status = "FAILED"
    return MessageResponse(
        id=item.id,
        conversation_id=item.conversation_id,
        role=role,
        content=item.content,
        created_at=item.created_at,
        answer_status=public_status,
        citations=[
            EnterpriseCitationResponse.model_validate(citation)
            for citation in item.citations
        ],
    )
