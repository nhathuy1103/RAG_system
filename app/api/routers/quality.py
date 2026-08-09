"""Document duplicate, version, and conflict review routes."""

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status

from app.api.dependencies.auth import get_current_user
from app.api.dependencies.services import get_knowledge_quality_service
from app.api.schemas.auth import CurrentUser
from app.api.schemas.quality import (
    DocumentRelationEvidenceResponse,
    DocumentRelationListResponse,
    DocumentRelationResponse,
    KnowledgeQualityAuditListResponse,
    KnowledgeQualityAuditResponse,
    ResolveDocumentRelationRequest,
    RevertDocumentRelationRequest,
)
from app.knowledge_quality.application.services import KnowledgeQualityService
from app.knowledge_quality.domain.models import RelationStatus, RelationType
from app.knowledge_quality.ports.repositories import (
    KnowledgeQualityConflictError,
    KnowledgeQualityRepositoryError,
)
from app.notebooks.ports.repositories import NotebookRepositoryError

router = APIRouter(
    prefix="/notebooks/{notebook_id}/quality/relations",
    tags=["knowledge-quality"],
)


def _to_response(relation: object) -> DocumentRelationResponse:
    return DocumentRelationResponse.model_validate(relation, from_attributes=True)


def _to_audit_response(event: object) -> KnowledgeQualityAuditResponse:
    return KnowledgeQualityAuditResponse.model_validate(event, from_attributes=True)


def _to_evidence_response(evidence: object) -> DocumentRelationEvidenceResponse:
    return DocumentRelationEvidenceResponse.model_validate(
        evidence,
        from_attributes=True,
    )


async def _require_notebook(
    notebook_id: UUID,
    service: KnowledgeQualityService,
) -> None:
    try:
        exists = await service.notebook_exists(notebook_id)
    except NotebookRepositoryError as exc:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="Notebook storage is unavailable",
        ) from exc
    if not exists:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Notebook not found",
        )


@router.get("", response_model=DocumentRelationListResponse)
async def list_document_relations(
    notebook_id: UUID,
    _current_user: Annotated[CurrentUser, Depends(get_current_user)],
    service: Annotated[
        KnowledgeQualityService,
        Depends(get_knowledge_quality_service),
    ],
    relation_status: Annotated[
        RelationStatus | None,
        Query(alias="status"),
    ] = None,
    relation_type: RelationType | None = None,
    limit: Annotated[int, Query(ge=1, le=100)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> DocumentRelationListResponse:
    """List the review queue or resolved relation history."""
    await _require_notebook(notebook_id, service)
    try:
        relations, total_count = await service.list_relations(
            notebook_id,
            relation_status=relation_status,
            relation_type=relation_type,
            limit=limit,
            offset=offset,
        )
    except KnowledgeQualityRepositoryError as exc:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="Knowledge-quality storage is unavailable",
        ) from exc
    return DocumentRelationListResponse(
        items=[_to_response(relation) for relation in relations],
        total_count=total_count,
        limit=limit,
        offset=offset,
    )


@router.get("/audit", response_model=KnowledgeQualityAuditListResponse)
async def list_knowledge_quality_audit(
    notebook_id: UUID,
    _current_user: Annotated[CurrentUser, Depends(get_current_user)],
    service: Annotated[
        KnowledgeQualityService,
        Depends(get_knowledge_quality_service),
    ],
    relation_id: UUID | None = None,
    limit: Annotated[int, Query(ge=1, le=100)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> KnowledgeQualityAuditListResponse:
    """List immutable decision history, optionally for one relation."""
    await _require_notebook(notebook_id, service)
    try:
        events, total_count = await service.list_audit_events(
            notebook_id,
            relation_id=relation_id,
            limit=limit,
            offset=offset,
        )
    except KnowledgeQualityRepositoryError as exc:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="Knowledge-quality storage is unavailable",
        ) from exc
    return KnowledgeQualityAuditListResponse(
        items=[_to_audit_response(event) for event in events],
        total_count=total_count,
        limit=limit,
        offset=offset,
    )


@router.get(
    "/{relation_id}/evidence",
    response_model=DocumentRelationEvidenceResponse,
)
async def get_document_relation_evidence(
    notebook_id: UUID,
    relation_id: UUID,
    _current_user: Annotated[CurrentUser, Depends(get_current_user)],
    service: Annotated[
        KnowledgeQualityService,
        Depends(get_knowledge_quality_service),
    ],
) -> DocumentRelationEvidenceResponse:
    """Load reviewer-facing chunk evidence for one detected relation."""
    await _require_notebook(notebook_id, service)
    try:
        evidence = await service.get_relation_evidence(notebook_id, relation_id)
    except KnowledgeQualityRepositoryError as exc:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="Knowledge-quality evidence is unavailable",
        ) from exc
    if evidence is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Document relation not found",
        )
    return _to_evidence_response(evidence)


@router.post(
    "/{relation_id}/resolve",
    response_model=DocumentRelationResponse,
)
async def resolve_document_relation(
    notebook_id: UUID,
    relation_id: UUID,
    request: ResolveDocumentRelationRequest,
    _current_user: Annotated[CurrentUser, Depends(get_current_user)],
    service: Annotated[
        KnowledgeQualityService,
        Depends(get_knowledge_quality_service),
    ],
) -> DocumentRelationResponse:
    """Apply an audited duplicate, version, conflict, or separation decision."""
    await _require_notebook(notebook_id, service)
    try:
        relation = await service.resolve_relation(
            notebook_id,
            relation_id,
            request.action,
            request.expected_updated_at,
            request.reason,
        )
    except KnowledgeQualityConflictError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Document relation changed; refresh before deciding",
        ) from exc
    except KnowledgeQualityRepositoryError as exc:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="Knowledge-quality storage is unavailable",
        ) from exc
    if relation is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Document relation not found",
        )
    return _to_response(relation)


@router.post(
    "/{relation_id}/revert",
    response_model=DocumentRelationResponse,
)
async def revert_document_relation(
    notebook_id: UUID,
    relation_id: UUID,
    request: RevertDocumentRelationRequest,
    _current_user: Annotated[CurrentUser, Depends(get_current_user)],
    service: Annotated[
        KnowledgeQualityService,
        Depends(get_knowledge_quality_service),
    ],
) -> DocumentRelationResponse:
    """Revert the latest still-effective resolution and append an audit event."""
    await _require_notebook(notebook_id, service)
    try:
        relation = await service.revert_relation(
            notebook_id,
            relation_id,
            request.expected_updated_at,
            request.reason,
        )
    except KnowledgeQualityConflictError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Document relation changed; refresh before reverting",
        ) from exc
    except KnowledgeQualityRepositoryError as exc:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="Knowledge-quality storage is unavailable",
        ) from exc
    if relation is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Reversible document relation decision not found",
        )
    return _to_response(relation)


__all__ = ["router"]
