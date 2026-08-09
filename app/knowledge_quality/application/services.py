"""Use cases for reviewing detected document relations."""

import logging
from dataclasses import replace
from datetime import datetime
from uuid import UUID

from app.documents.ports.storage import DocumentObjectStorage, ObjectStorageError
from app.knowledge_quality.application.original_preview import (
    ReviewSide,
    build_original_review_blocks,
)
from app.knowledge_quality.domain.models import (
    DocumentRelation,
    DocumentRelationEvidence,
    KnowledgeQualityAudit,
    RelationEvidenceBlock,
    RelationEvidenceChunkPair,
    RelationEvidenceDocument,
    RelationStatus,
    RelationType,
    ResolutionAction,
)
from app.knowledge_quality.ports.repositories import KnowledgeQualityRepository
from app.notebooks.ports.repositories import NotebookRepository

LOGGER = logging.getLogger(__name__)


class KnowledgeQualityService:
    """Coordinate notebook ownership and audited relation decisions."""

    def __init__(
        self,
        notebook_repository: NotebookRepository,
        quality_repository: KnowledgeQualityRepository,
        object_storage: DocumentObjectStorage | None = None,
    ) -> None:
        self._notebook_repository = notebook_repository
        self._quality_repository = quality_repository
        self._object_storage = object_storage

    async def notebook_exists(self, notebook_id: UUID) -> bool:
        return await self._notebook_repository.exists_owned(notebook_id)

    async def list_relations(
        self,
        notebook_id: UUID,
        *,
        relation_status: RelationStatus | None,
        relation_type: RelationType | None,
        limit: int,
        offset: int,
    ) -> tuple[list[DocumentRelation], int]:
        return await self._quality_repository.list_relations(
            notebook_id,
            relation_status=relation_status,
            relation_type=relation_type,
            limit=limit,
            offset=offset,
        )

    async def resolve_relation(
        self,
        notebook_id: UUID,
        relation_id: UUID,
        action: ResolutionAction,
        expected_updated_at: datetime,
        reason: str | None,
    ) -> DocumentRelation | None:
        normalized_reason = reason.strip() if reason is not None else None
        return await self._quality_repository.resolve_relation(
            notebook_id,
            relation_id,
            action,
            expected_updated_at,
            normalized_reason or None,
        )

    async def revert_relation(
        self,
        notebook_id: UUID,
        relation_id: UUID,
        expected_updated_at: datetime,
        reason: str,
    ) -> DocumentRelation | None:
        normalized_reason = reason.strip()
        if not normalized_reason:
            raise ValueError("A reason is required to revert a quality decision")
        return await self._quality_repository.revert_relation(
            notebook_id,
            relation_id,
            expected_updated_at,
            normalized_reason,
        )

    async def list_audit_events(
        self,
        notebook_id: UUID,
        *,
        relation_id: UUID | None,
        limit: int,
        offset: int,
    ) -> tuple[list[KnowledgeQualityAudit], int]:
        return await self._quality_repository.list_audit_events(
            notebook_id,
            relation_id=relation_id,
            limit=limit,
            offset=offset,
        )

    async def get_relation_evidence(
        self,
        notebook_id: UUID,
        relation_id: UUID,
    ) -> DocumentRelationEvidence | None:
        evidence = await self._quality_repository.get_relation_evidence(
            notebook_id,
            relation_id,
        )
        if evidence is None or self._object_storage is None:
            return evidence

        source_blocks = await self._load_original_blocks(
            evidence.source_document,
            evidence.chunk_pairs,
            side="source",
        )
        target_blocks = await self._load_original_blocks(
            evidence.target_document,
            evidence.chunk_pairs,
            side="target",
        )
        return replace(
            evidence,
            source_original_blocks=source_blocks,
            target_original_blocks=target_blocks,
        )

    async def _load_original_blocks(
        self,
        document: RelationEvidenceDocument | None,
        pairs: tuple[RelationEvidenceChunkPair, ...],
        *,
        side: ReviewSide,
    ) -> tuple[RelationEvidenceBlock, ...]:
        if (
            document is None
            or self._object_storage is None
            or not document.storage_bucket
            or not document.storage_object_path
        ):
            return ()
        try:
            content = await self._object_storage.download(
                document.storage_bucket,
                document.storage_object_path,
            )
            return build_original_review_blocks(
                document,
                content,
                pairs,
                side=side,
            )
        except (ObjectStorageError, OSError, ValueError):
            LOGGER.warning(
                "Could not build original relation evidence preview",
                extra={
                    "document_id": str(document.id),
                    "side": side,
                    "mime_type": document.mime_type,
                },
                exc_info=True,
            )
            return ()


__all__ = ["KnowledgeQualityService"]
