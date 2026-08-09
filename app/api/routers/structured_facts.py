"""Owner-scoped structured claim relation review routes."""

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status

from app.api.dependencies.auth import get_current_user
from app.api.dependencies.services import get_structured_fact_review_service
from app.api.schemas.auth import CurrentUser
from app.api.schemas.structured_facts import (
    ResolveStructuredClaimRelationRequest,
    StructuredClaimRelationEvidenceResponse,
    StructuredClaimRelationListResponse,
    StructuredClaimRelationResponse,
)
from app.notebooks.ports.repositories import NotebookRepositoryError
from app.structured_facts.application.review import StructuredFactReviewService
from app.structured_facts.ports.repositories import (
    StructuredFactReviewConflictError,
    StructuredFactReviewRepositoryError,
)

router = APIRouter(
    prefix="/notebooks/{notebook_id}/structured-facts/relations",
    tags=["structured-facts"],
)


async def _require_notebook(
    notebook_id: UUID,
    service: StructuredFactReviewService,
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


@router.get("", response_model=StructuredClaimRelationListResponse)
async def list_pending_structured_claim_relations(
    notebook_id: UUID,
    _current_user: Annotated[CurrentUser, Depends(get_current_user)],
    service: Annotated[
        StructuredFactReviewService,
        Depends(get_structured_fact_review_service),
    ],
    limit: Annotated[int, Query(ge=1, le=100)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> StructuredClaimRelationListResponse:
    """List only human-reviewable pending relations in an owned notebook."""
    await _require_notebook(notebook_id, service)
    try:
        relations, total_count = await service.list_pending_relations(
            notebook_id,
            limit=limit,
            offset=offset,
        )
    except StructuredFactReviewRepositoryError as exc:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="Structured relation storage is unavailable",
        ) from exc
    return StructuredClaimRelationListResponse(
        items=[
            StructuredClaimRelationResponse.model_validate(
                relation,
                from_attributes=True,
            )
            for relation in relations
        ],
        total_count=total_count,
        limit=limit,
        offset=offset,
    )


@router.get(
    "/{relation_id}/evidence",
    response_model=StructuredClaimRelationEvidenceResponse,
)
async def get_structured_claim_relation_evidence(
    notebook_id: UUID,
    relation_id: UUID,
    _current_user: Annotated[CurrentUser, Depends(get_current_user)],
    service: Annotated[
        StructuredFactReviewService,
        Depends(get_structured_fact_review_service),
    ],
) -> StructuredClaimRelationEvidenceResponse:
    """Load both table snapshots and their nullable claim endpoints."""
    await _require_notebook(notebook_id, service)
    try:
        evidence = await service.get_relation_evidence(notebook_id, relation_id)
    except StructuredFactReviewRepositoryError as exc:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="Structured relation evidence is unavailable",
        ) from exc
    if evidence is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Structured claim relation not found",
        )
    return StructuredClaimRelationEvidenceResponse.model_validate(
        evidence,
        from_attributes=True,
    )


@router.post(
    "/{relation_id}/resolve",
    response_model=StructuredClaimRelationResponse,
)
async def resolve_structured_claim_relation(
    notebook_id: UUID,
    relation_id: UUID,
    request: ResolveStructuredClaimRelationRequest,
    _current_user: Annotated[CurrentUser, Depends(get_current_user)],
    service: Annotated[
        StructuredFactReviewService,
        Depends(get_structured_fact_review_service),
    ],
) -> StructuredClaimRelationResponse:
    """Resolve atomically through the audited optimistic-concurrency RPC."""
    await _require_notebook(notebook_id, service)
    try:
        relation = await service.resolve_relation(
            notebook_id,
            relation_id,
            request.action,
            request.expected_updated_at,
            request.reason,
        )
    except StructuredFactReviewConflictError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Structured claim relation changed; refresh before deciding",
        ) from exc
    except StructuredFactReviewRepositoryError as exc:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="Structured relation storage is unavailable",
        ) from exc
    if relation is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Structured claim relation not found",
        )
    return StructuredClaimRelationResponse.model_validate(
        relation,
        from_attributes=True,
    )


__all__ = ["router"]
