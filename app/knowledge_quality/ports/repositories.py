"""Persistence contracts for document quality decisions."""

from datetime import datetime
from typing import Protocol
from uuid import UUID

from app.knowledge_quality.domain.models import (
    DocumentRelation,
    DocumentRelationEvidence,
    KnowledgeQualityAudit,
    RelationStatus,
    RelationType,
    ResolutionAction,
)


class KnowledgeQualityRepositoryError(RuntimeError):
    """Raised when document-quality persistence is unavailable."""


class KnowledgeQualityConflictError(KnowledgeQualityRepositoryError):
    """Raised when a reviewer acts on a stale relation snapshot."""


class KnowledgeQualityRepository(Protocol):
    """Read and resolve document relations within a user-owned notebook."""

    async def list_relations(
        self,
        notebook_id: UUID,
        *,
        relation_status: RelationStatus | None,
        relation_type: RelationType | None,
        limit: int,
        offset: int,
    ) -> tuple[list[DocumentRelation], int]: ...

    async def resolve_relation(
        self,
        notebook_id: UUID,
        relation_id: UUID,
        action: ResolutionAction,
        expected_updated_at: datetime,
        reason: str | None,
    ) -> DocumentRelation | None: ...

    async def revert_relation(
        self,
        notebook_id: UUID,
        relation_id: UUID,
        expected_updated_at: datetime,
        reason: str,
    ) -> DocumentRelation | None: ...

    async def list_audit_events(
        self,
        notebook_id: UUID,
        *,
        relation_id: UUID | None,
        limit: int,
        offset: int,
    ) -> tuple[list[KnowledgeQualityAudit], int]: ...

    async def get_relation_evidence(
        self,
        notebook_id: UUID,
        relation_id: UUID,
    ) -> DocumentRelationEvidence | None: ...


__all__ = [
    "KnowledgeQualityConflictError",
    "KnowledgeQualityRepository",
    "KnowledgeQualityRepositoryError",
]
