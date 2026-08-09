"""Use cases for owner-scoped review of structured claim relations."""

from datetime import datetime
from uuid import UUID

from app.notebooks.ports.repositories import NotebookRepository
from app.structured_facts.domain.review import (
    StructuredClaimRelation,
    StructuredClaimRelationEvidence,
    StructuredClaimResolutionAction,
)
from app.structured_facts.ports.repositories import StructuredFactReviewRepository


class StructuredFactReviewService:
    """Coordinate notebook ownership checks and structured relation decisions."""

    def __init__(
        self,
        notebook_repository: NotebookRepository,
        review_repository: StructuredFactReviewRepository,
    ) -> None:
        self._notebook_repository = notebook_repository
        self._review_repository = review_repository

    async def notebook_exists(self, notebook_id: UUID) -> bool:
        return await self._notebook_repository.exists_owned(notebook_id)

    async def list_pending_relations(
        self,
        notebook_id: UUID,
        *,
        limit: int,
        offset: int,
    ) -> tuple[list[StructuredClaimRelation], int]:
        return await self._review_repository.list_pending_relations(
            notebook_id,
            limit=limit,
            offset=offset,
        )

    async def get_relation_evidence(
        self,
        notebook_id: UUID,
        relation_id: UUID,
    ) -> StructuredClaimRelationEvidence | None:
        return await self._review_repository.get_relation_evidence(
            notebook_id,
            relation_id,
        )

    async def resolve_relation(
        self,
        notebook_id: UUID,
        relation_id: UUID,
        action: StructuredClaimResolutionAction,
        expected_updated_at: datetime,
        reason: str,
    ) -> StructuredClaimRelation | None:
        normalized_reason = reason.strip()
        if not normalized_reason:
            raise ValueError("A reason is required to resolve a structured relation")
        return await self._review_repository.resolve_relation(
            notebook_id,
            relation_id,
            action,
            expected_updated_at,
            normalized_reason,
        )


__all__ = ["StructuredFactReviewService"]
