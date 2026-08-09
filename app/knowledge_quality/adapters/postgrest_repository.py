"""Supabase PostgREST adapter for document relations."""

import logging
from collections.abc import Mapping
from datetime import datetime
from uuid import UUID

import httpx2 as httpx

from app.knowledge_quality.application.evidence import build_relation_chunk_pairs
from app.knowledge_quality.domain.models import (
    DocumentRelation,
    DocumentRelationEvidence,
    KnowledgeQualityAudit,
    RelationEvidenceChunk,
    RelationEvidenceDocument,
    RelationStatus,
    RelationType,
    ResolutionAction,
)
from app.knowledge_quality.ports.repositories import (
    KnowledgeQualityConflictError,
    KnowledgeQualityRepository,
    KnowledgeQualityRepositoryError,
)

LOGGER = logging.getLogger(__name__)

RELATION_COLUMNS = (
    "id,owner_id,notebook_id,source_document_id,target_document_id,"
    "relation_type,status,confidence,signals,reason,detector_version,"
    "preferred_document_id,resolved_by,resolved_at,created_at,updated_at"
)
AUDIT_COLUMNS = (
    "id,owner_id,notebook_id,relation_id,actor_id,action,reason,before_state,after_state,created_at"
)
DOCUMENT_EVIDENCE_COLUMNS = (
    "id,original_filename,quality_status,version_number,is_current,"
    "canonical_document_id,mime_type,storage_bucket,storage_object_path"
)
CHUNK_EVIDENCE_COLUMNS = (
    "id,document_id,chunk_index,content,metadata,normalized_content_hash,exact_duplicate_group_id"
)


class PostgrestKnowledgeQualityRepository(KnowledgeQualityRepository):
    """Persist quality review through a user-scoped Data API client."""

    def __init__(self, client: httpx.AsyncClient) -> None:
        self._client = client

    async def list_relations(
        self,
        notebook_id: UUID,
        *,
        relation_status: RelationStatus | None,
        relation_type: RelationType | None,
        limit: int,
        offset: int,
    ) -> tuple[list[DocumentRelation], int]:
        params = {
            "notebook_id": f"eq.{notebook_id}",
            "select": RELATION_COLUMNS,
            "order": "confidence.desc,created_at.desc,id.asc",
            "limit": str(limit),
            "offset": str(offset),
        }
        if relation_status is not None:
            params["status"] = f"eq.{relation_status.value}"
        if relation_type is not None:
            params["relation_type"] = f"eq.{relation_type.value}"

        try:
            response = await self._client.get(
                "/document_relations",
                params=params,
                headers={"Prefer": "count=exact"},
            )
            response.raise_for_status()
            payload = response.json()
            if not isinstance(payload, list):
                raise TypeError("PostgREST relation response must be an array")
            total_count = self._parse_total_count(response.headers.get("content-range"))
            return [self._parse_relation(row) for row in payload], total_count
        except (httpx.HTTPError, OSError, KeyError, TypeError, ValueError) as exc:
            LOGGER.exception("PostgREST relation listing failed")
            raise KnowledgeQualityRepositoryError("Failed to list document relations") from exc

    async def resolve_relation(
        self,
        notebook_id: UUID,
        relation_id: UUID,
        action: ResolutionAction,
        expected_updated_at: datetime,
        reason: str | None,
    ) -> DocumentRelation | None:
        try:
            response = await self._client.post(
                "/rpc/resolve_document_relation",
                json={
                    "p_relation_id": str(relation_id),
                    "p_notebook_id": str(notebook_id),
                    "p_action": action.value,
                    "p_expected_updated_at": expected_updated_at.isoformat(),
                    "p_reason": reason,
                },
            )
            if response.status_code >= 400 and self._is_not_found(response):
                return None
            if response.status_code >= 400 and self._is_conflict(response):
                raise KnowledgeQualityConflictError(
                    "Document relation changed before this decision was saved"
                )
            response.raise_for_status()
            payload = response.json()
            if not isinstance(payload, list):
                raise TypeError("Resolve response must be an array")
            if not payload:
                return None
            if len(payload) != 1:
                raise TypeError("Resolve response must contain one relation")
            return self._parse_relation(payload[0])
        except KnowledgeQualityConflictError:
            raise
        except (httpx.HTTPError, OSError, KeyError, TypeError, ValueError) as exc:
            LOGGER.exception("PostgREST relation resolution failed")
            raise KnowledgeQualityRepositoryError("Failed to resolve document relation") from exc

    async def revert_relation(
        self,
        notebook_id: UUID,
        relation_id: UUID,
        expected_updated_at: datetime,
        reason: str,
    ) -> DocumentRelation | None:
        try:
            response = await self._client.post(
                "/rpc/revert_document_relation_resolution",
                json={
                    "p_relation_id": str(relation_id),
                    "p_notebook_id": str(notebook_id),
                    "p_expected_updated_at": expected_updated_at.isoformat(),
                    "p_reason": reason,
                },
            )
            if response.status_code >= 400 and self._is_not_found(response):
                return None
            if response.status_code >= 400 and self._is_conflict(response):
                raise KnowledgeQualityConflictError(
                    "Document relation changed before this reversal was saved"
                )
            response.raise_for_status()
            payload = response.json()
            if not isinstance(payload, list):
                raise TypeError("Revert response must be an array")
            if not payload:
                return None
            if len(payload) != 1:
                raise TypeError("Revert response must contain one relation")
            return self._parse_relation(payload[0])
        except KnowledgeQualityConflictError:
            raise
        except (httpx.HTTPError, OSError, KeyError, TypeError, ValueError) as exc:
            LOGGER.exception("PostgREST relation reversal failed")
            raise KnowledgeQualityRepositoryError("Failed to revert document relation") from exc

    async def list_audit_events(
        self,
        notebook_id: UUID,
        *,
        relation_id: UUID | None,
        limit: int,
        offset: int,
    ) -> tuple[list[KnowledgeQualityAudit], int]:
        params = {
            "notebook_id": f"eq.{notebook_id}",
            "select": AUDIT_COLUMNS,
            "order": "created_at.desc,id.desc",
            "limit": str(limit),
            "offset": str(offset),
        }
        if relation_id is not None:
            params["relation_id"] = f"eq.{relation_id}"
        try:
            response = await self._client.get(
                "/knowledge_quality_audit",
                params=params,
                headers={"Prefer": "count=exact"},
            )
            response.raise_for_status()
            payload = response.json()
            if not isinstance(payload, list):
                raise TypeError("PostgREST audit response must be an array")
            total_count = self._parse_total_count(response.headers.get("content-range"))
            return [self._parse_audit(row) for row in payload], total_count
        except (httpx.HTTPError, OSError, KeyError, TypeError, ValueError) as exc:
            LOGGER.exception("PostgREST quality audit listing failed")
            raise KnowledgeQualityRepositoryError(
                "Failed to list knowledge-quality audit events"
            ) from exc

    async def get_relation_evidence(
        self,
        notebook_id: UUID,
        relation_id: UUID,
    ) -> DocumentRelationEvidence | None:
        try:
            relation_response = await self._client.get(
                "/document_relations",
                params={
                    "id": f"eq.{relation_id}",
                    "notebook_id": f"eq.{notebook_id}",
                    "select": RELATION_COLUMNS,
                    "limit": "1",
                },
            )
            relation_response.raise_for_status()
            relation_payload = relation_response.json()
            if not isinstance(relation_payload, list):
                raise TypeError("PostgREST relation response must be an array")
            if not relation_payload:
                return None

            relation = self._parse_relation(relation_payload[0])
            document_ids = (
                relation.source_document_id,
                relation.target_document_id,
            )
            in_filter = ",".join(str(document_id) for document_id in document_ids)
            documents_response = await self._client.get(
                "/documents",
                params={
                    "id": f"in.({in_filter})",
                    "notebook_id": f"eq.{notebook_id}",
                    "select": DOCUMENT_EVIDENCE_COLUMNS,
                },
            )
            documents_response.raise_for_status()
            document_payload = documents_response.json()
            if not isinstance(document_payload, list):
                raise TypeError("PostgREST document response must be an array")
            documents = {
                document.id: document
                for document in (self._parse_evidence_document(row) for row in document_payload)
            }

            chunks_response = await self._client.get(
                "/document_chunks",
                params={
                    "document_id": f"in.({in_filter})",
                    "notebook_id": f"eq.{notebook_id}",
                    "select": CHUNK_EVIDENCE_COLUMNS,
                    "order": "document_id.asc,chunk_index.asc",
                },
            )
            chunks_response.raise_for_status()
            chunk_payload = chunks_response.json()
            if not isinstance(chunk_payload, list):
                raise TypeError("PostgREST chunk response must be an array")

            source_chunks: list[RelationEvidenceChunk] = []
            target_chunks: list[RelationEvidenceChunk] = []
            for row in chunk_payload:
                chunk = self._parse_evidence_chunk(row)
                if chunk.document_id == relation.source_document_id:
                    source_chunks.append(chunk)
                elif chunk.document_id == relation.target_document_id:
                    target_chunks.append(chunk)

            return DocumentRelationEvidence(
                relation=relation,
                source_document=documents.get(relation.source_document_id),
                target_document=documents.get(relation.target_document_id),
                chunk_pairs=build_relation_chunk_pairs(
                    relation,
                    tuple(source_chunks),
                    tuple(target_chunks),
                ),
            )
        except (httpx.HTTPError, OSError, KeyError, TypeError, ValueError) as exc:
            LOGGER.exception("PostGREST relation evidence loading failed")
            raise KnowledgeQualityRepositoryError(
                "Failed to load document relation evidence"
            ) from exc

    @staticmethod
    def _is_not_found(response: httpx.Response) -> bool:
        try:
            payload = response.json()
        except ValueError:
            return response.status_code == 404
        return (
            response.status_code == 404
            or isinstance(payload, Mapping)
            and payload.get("code") == "P0002"
        )

    @staticmethod
    def _is_conflict(response: httpx.Response) -> bool:
        try:
            payload = response.json()
        except ValueError:
            return response.status_code == 409
        return (
            response.status_code == 409
            or isinstance(payload, Mapping)
            and payload.get("code") == "40001"
        )

    @staticmethod
    def _parse_total_count(content_range: str | None) -> int:
        if content_range is None or "/" not in content_range:
            raise ValueError("PostgREST count response is missing Content-Range")
        total = content_range.rsplit("/", maxsplit=1)[1]
        if total == "*":
            raise ValueError("PostgREST did not return an exact count")
        return int(total)

    @staticmethod
    def _parse_relation(row: object) -> DocumentRelation:
        if not isinstance(row, Mapping):
            raise TypeError("Document relation row must be an object")
        signals = row["signals"]
        if not isinstance(signals, Mapping):
            raise TypeError("Document relation signals must be an object")
        return DocumentRelation(
            id=UUID(str(row["id"])),
            owner_id=UUID(str(row["owner_id"])),
            notebook_id=UUID(str(row["notebook_id"])),
            source_document_id=UUID(str(row["source_document_id"])),
            target_document_id=UUID(str(row["target_document_id"])),
            relation_type=RelationType(str(row["relation_type"])),
            status=RelationStatus(str(row["status"])),
            confidence=float(row["confidence"]),
            signals=dict(signals),
            reason=str(row["reason"]) if row["reason"] is not None else None,
            detector_version=str(row["detector_version"]),
            preferred_document_id=(
                UUID(str(row["preferred_document_id"]))
                if row["preferred_document_id"] is not None
                else None
            ),
            resolved_by=(UUID(str(row["resolved_by"])) if row["resolved_by"] is not None else None),
            resolved_at=(
                datetime.fromisoformat(str(row["resolved_at"]))
                if row["resolved_at"] is not None
                else None
            ),
            created_at=datetime.fromisoformat(str(row["created_at"])),
            updated_at=datetime.fromisoformat(str(row["updated_at"])),
        )

    @staticmethod
    def _parse_audit(row: object) -> KnowledgeQualityAudit:
        if not isinstance(row, Mapping):
            raise TypeError("Knowledge-quality audit row must be an object")
        before_state = row["before_state"]
        after_state = row["after_state"]
        if not isinstance(before_state, Mapping) or not isinstance(
            after_state,
            Mapping,
        ):
            raise TypeError("Knowledge-quality audit states must be objects")
        return KnowledgeQualityAudit(
            id=int(row["id"]),
            owner_id=UUID(str(row["owner_id"])),
            notebook_id=UUID(str(row["notebook_id"])),
            relation_id=(UUID(str(row["relation_id"])) if row["relation_id"] is not None else None),
            actor_id=(UUID(str(row["actor_id"])) if row["actor_id"] is not None else None),
            action=str(row["action"]),
            reason=str(row["reason"]) if row["reason"] is not None else None,
            before_state=dict(before_state),
            after_state=dict(after_state),
            created_at=datetime.fromisoformat(str(row["created_at"])),
        )

    @staticmethod
    def _parse_evidence_document(row: object) -> RelationEvidenceDocument:
        if not isinstance(row, Mapping):
            raise TypeError("Document evidence row must be an object")
        return RelationEvidenceDocument(
            id=UUID(str(row["id"])),
            original_filename=str(row["original_filename"]),
            quality_status=str(row["quality_status"]),
            version_number=int(row["version_number"]),
            is_current=bool(row["is_current"]),
            canonical_document_id=(
                UUID(str(row["canonical_document_id"]))
                if row["canonical_document_id"] is not None
                else None
            ),
            mime_type=str(row["mime_type"]) if row["mime_type"] is not None else None,
            storage_bucket=(
                str(row["storage_bucket"]) if row["storage_bucket"] is not None else None
            ),
            storage_object_path=(
                str(row["storage_object_path"]) if row["storage_object_path"] is not None else None
            ),
        )

    @staticmethod
    def _parse_evidence_chunk(row: object) -> RelationEvidenceChunk:
        if not isinstance(row, Mapping):
            raise TypeError("Chunk evidence row must be an object")
        metadata = row.get("metadata")
        if not isinstance(metadata, Mapping):
            metadata = {}
        return RelationEvidenceChunk(
            id=str(row["id"]),
            document_id=UUID(str(row["document_id"])),
            chunk_index=int(row["chunk_index"]),
            content=str(row["content"]),
            page_number=_optional_int(metadata.get("page_number")),
            section_title=(
                str(metadata["section_title"])
                if metadata.get("section_title") is not None
                else None
            ),
            normalized_content_hash=(
                str(row["normalized_content_hash"])
                if row["normalized_content_hash"] is not None
                else None
            ),
            exact_duplicate_group_id=(
                str(row["exact_duplicate_group_id"])
                if row["exact_duplicate_group_id"] is not None
                else None
            ),
        )


def _optional_int(value: object) -> int | None:
    if value is None or value == "":
        return None
    if isinstance(value, int):
        return value
    if not isinstance(value, str):
        return None
    try:
        return int(value)
    except ValueError:
        return None


__all__ = [
    "AUDIT_COLUMNS",
    "CHUNK_EVIDENCE_COLUMNS",
    "DOCUMENT_EVIDENCE_COLUMNS",
    "RELATION_COLUMNS",
    "PostgrestKnowledgeQualityRepository",
]
