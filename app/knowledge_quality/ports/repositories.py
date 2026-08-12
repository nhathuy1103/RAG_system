"""Persistence contracts for document quality decisions."""

from collections.abc import Sequence
from datetime import datetime
from typing import Protocol, runtime_checkable
from uuid import UUID

from app.knowledge_quality.domain.models import (
    DocumentRelation,
    DocumentRelationEvidence,
    KnowledgeQualityAudit,
    QualityRelationCandidate,
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


@runtime_checkable
class KnowledgeRelationWriter(Protocol):
    """Trusted post-ingestion writer for recomputable P4 relations."""

    async def replace_p4_relations(
        self,
        *,
        source_document_id: UUID,
        detector_version: str,
        relations: Sequence[QualityRelationCandidate],
    ) -> int: ...


__all__ = [
    "KnowledgeQualityConflictError",
    "KnowledgeQualityRepository",
    "KnowledgeQualityRepositoryError",
    "KnowledgeRelationWriter",
]
