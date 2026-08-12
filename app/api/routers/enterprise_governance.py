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
    require_review_workspace,
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
    EnterpriseDocumentRelationEvidenceResponse,
    EnterpriseDocumentRelationListResponse,
    EnterpriseDocumentRelationResolutionRequest,
    EnterpriseDocumentRelationResponse,
    EnterpriseRelationStatus,
    FeedbackCreateRequest,
    FeedbackResponse,
    MessageCreateRequest,
    MessageResponse,
    SearchHitResponse,
    SearchRequest,
    SearchResponse,
    TextComparisonRequest,
    TextComparisonResponse,
)
from app.governance.application.services import EnterpriseQuestionService, GovernanceService
from app.governance.domain.models import EnterpriseMessage
from app.identity.domain.models import PrincipalContext
from app.knowledge_quality.application.analysis import analyze_text_relation
from app.knowledge_quality.domain.models import RelationType

router = APIRouter(prefix="/api/v1", tags=["enterprise-knowledge"])


@router.get(
    "/quality/relations",
    response_model=EnterpriseDocumentRelationListResponse,
)
async def list_enterprise_document_relations(
    _principal: Annotated[PrincipalContext, Depends(require_review_workspace)],
    service: Annotated[GovernanceService, Depends(get_governance_service)],
    relation_status: Annotated[
        EnterpriseRelationStatus | None,
        Query(alias="status"),
    ] = None,
    limit: Annotated[int, Query(ge=1, le=200)] = 200,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> EnterpriseDocumentRelationListResponse:
    items, total = await service.list_document_relations(
        relation_status=relation_status,
        limit=limit,
        offset=offset,
    )
    return EnterpriseDocumentRelationListResponse(
        items=[EnterpriseDocumentRelationResponse.model_validate(item) for item in items],
        total_count=total,
        limit=limit,
        offset=offset,
    )


@router.get(
    "/quality/relations/{relation_id}/evidence",
    response_model=EnterpriseDocumentRelationEvidenceResponse,
)
async def get_enterprise_document_relation_evidence(
    relation_id: UUID,
    _principal: Annotated[PrincipalContext, Depends(require_review_workspace)],
    service: Annotated[GovernanceService, Depends(get_governance_service)],
) -> EnterpriseDocumentRelationEvidenceResponse:
    evidence = await service.get_document_relation_evidence(relation_id)
    if evidence is None:
        raise HTTPException(status_code=404, detail="Enterprise relation was not found")
    return EnterpriseDocumentRelationEvidenceResponse.model_validate(evidence)


@router.post(
    "/quality/relations/{relation_id}/resolve",
    response_model=EnterpriseDocumentRelationResponse,
)
async def resolve_enterprise_document_relation(
    relation_id: UUID,
    payload: EnterpriseDocumentRelationResolutionRequest,
    _principal: Annotated[PrincipalContext, Depends(require_review_workspace)],
    service: Annotated[GovernanceService, Depends(get_governance_service)],
) -> EnterpriseDocumentRelationResponse:
    relation = await service.resolve_document_relation(
        relation_id,
        action=payload.action,
        reason=payload.reason,
        expected_updated_at=(
            payload.expected_updated_at.isoformat()
            if payload.expected_updated_at is not None
            else None
        ),
    )
    return EnterpriseDocumentRelationResponse.model_validate(relation)


@router.post("/quality/compare-texts", response_model=TextComparisonResponse)
async def compare_quality_texts(
    payload: TextComparisonRequest,
    _principal: Annotated[PrincipalContext, Depends(require_review_workspace)],
) -> TextComparisonResponse:
    """Preview duplicate/conflict classification without persisting either text."""

    analysis = analyze_text_relation(payload.left_text, payload.right_text)
    signals = analysis.to_signals()
    review_recommended = analysis.relation_type not in {
        RelationType.EXACT_CONTENT,
        RelationType.DISTINCT,
    }
    return TextComparisonResponse(
        relation_type=analysis.relation_type.value,
        confidence=round(analysis.confidence, 6),
        review_recommended=review_recommended,
        lexical_similarity=float(signals["lexical_similarity"]),
        containment=float(signals["containment"]),
        semantic_similarity=signals["semantic_similarity"],
        template_similarity=float(signals["template_similarity"]),
        number_agreement=analysis.number_agreement,
        date_agreement=analysis.date_agreement,
        negation_mismatch=analysis.negation_mismatch,
        unit_agreement=analysis.unit_agreement,
        policy_modality_mismatch=analysis.policy_modality_mismatch,
        scope_comparison=analysis.scope_comparison.value,
        reason_codes=list(analysis.reason_codes),
        claim_conflicts=[conflict.to_signal() for conflict in analysis.claim_conflicts],
        validated_conflict_count=analysis.validated_conflict_count,
        exact_line_overlap_count=analysis.exact_line_overlap_count,
        exact_line_overlap_ratio=analysis.exact_line_overlap_ratio,
        structural_numbers_ignored=analysis.structural_numbers_ignored,
    )


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
    principal: Annotated[PrincipalContext, Depends(require_ask_knowledge)],
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
        user_id=principal.user_id,
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
                citation_order=item.citation_order,
                quote_text=item.quote_text,
                page=item.page_number,
                section=item.section_path,
            )
            for item in result.citations
        ],
        retrieval=AnswerRetrievalResponse(
            strategy=result.retrieval_strategy,
            candidate_count=result.candidate_count,
            evidence_count=result.evidence_count,
            gate_reason=result.gate_reason,
        ),
        error_code=result.error_code,
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
        error_code=item.error_code,
        citations=[
            EnterpriseCitationResponse.model_validate(citation)
            for citation in item.citations
        ],
    )
