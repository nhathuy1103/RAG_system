"""Supabase PostgREST adapter for document metadata."""

import logging
from collections.abc import Mapping
from datetime import datetime
from uuid import UUID

import httpx2 as httpx

from app.documents.domain.models import Document
from app.documents.ports.repositories import (
    DocumentDuplicateError,
    DocumentRepository,
    DocumentRepositoryError,
    NewDocument,
)

LOGGER = logging.getLogger(__name__)

DOCUMENT_COLUMNS = (
    "id,owner_id,notebook_id,original_filename,storage_bucket,"
    "storage_object_path,mime_type,size_bytes,content_hash,status,"
    "error_message,is_active,created_at,updated_at,normalized_content_hash,"
    "normalization_version,loose_content_signature,canonical_document_id,"
    "version_group_id,version_number,effective_from,effective_to,"
    "supersedes_document_id,is_current,quality_status"
)


class PostgrestDocumentRepository(DocumentRepository):
    """Persist document metadata through a user-scoped Data API client."""

    def __init__(self, client: httpx.AsyncClient) -> None:
        self._client = client

    async def get_by_id(
        self,
        document_id: UUID,
        notebook_id: UUID,
    ) -> Document | None:
        try:
            response = await self._client.get(
                "/documents",
                params={
                    "id": f"eq.{document_id}",
                    "notebook_id": f"eq.{notebook_id}",
                    "select": DOCUMENT_COLUMNS,
                    "limit": "1",
                },
            )
            response.raise_for_status()
            payload = response.json()
            if not isinstance(payload, list):
                raise TypeError("PostgREST document response must be an array")
            if not payload:
                return None
            if len(payload) != 1:
                raise TypeError("PostgREST document response must contain at most one row")
            return self._parse_document(payload[0])
        except (httpx.HTTPError, OSError, KeyError, TypeError, ValueError) as exc:
            LOGGER.exception("PostgREST document lookup failed")
            raise DocumentRepositoryError("Failed to get document metadata") from exc

    async def find_by_content_hash(
        self,
        owner_id: UUID,
        notebook_id: UUID,
        content_hash: str,
    ) -> Document | None:
        try:
            response = await self._client.get(
                "/documents",
                params={
                    "owner_id": f"eq.{owner_id}",
                    "notebook_id": f"eq.{notebook_id}",
                    "content_hash": f"eq.{content_hash}",
                    "is_active": "eq.true",
                    "status": "neq.failed",
                    "canonical_document_id": "is.null",
                    "select": DOCUMENT_COLUMNS,
                    "order": "created_at.asc,id.asc",
                    "limit": "1",
                },
            )
            response.raise_for_status()
            payload = response.json()
            if not isinstance(payload, list):
                raise TypeError("PostgREST document response must be an array")
            if not payload:
                return None
            if len(payload) != 1:
                raise TypeError("PostgREST document response must contain at most one row")
            return self._parse_document(payload[0])
        except (httpx.HTTPError, OSError, KeyError, TypeError, ValueError) as exc:
            LOGGER.exception("PostgREST content-hash lookup failed")
            raise DocumentRepositoryError("Failed to look up document by content hash") from exc

    async def soft_delete(
        self,
        document_id: UUID,
        notebook_id: UUID,
    ) -> Document | None:
        """Archive a document: is_active=false, storage/vectors untouched."""
        try:
            response = await self._client.post(
                "/rpc/soft_delete_document",
                json={
                    "p_document_id": str(document_id),
                    "p_notebook_id": str(notebook_id),
                },
            )
            response.raise_for_status()
            payload = response.json()
            if not isinstance(payload, list):
                raise TypeError("Soft delete response must be an array")
            if not payload:
                return None
            if len(payload) != 1:
                raise TypeError("Soft delete response must contain at most one document")
            return self._parse_document(payload[0])
        except (httpx.HTTPError, OSError, KeyError, TypeError, ValueError) as exc:
            LOGGER.exception("PostgREST document soft delete failed")
            raise DocumentRepositoryError("Failed to archive document") from exc

    async def list_by_notebook(
        self,
        notebook_id: UUID,
        *,
        status: str | None,
        limit: int,
        offset: int,
    ) -> tuple[list[Document], int]:
        params = {
            "notebook_id": f"eq.{notebook_id}",
            "is_active": "eq.true",
            "select": DOCUMENT_COLUMNS,
            "order": "updated_at.desc,id.asc",
            "limit": str(limit),
            "offset": str(offset),
        }
        if status is not None:
            params["status"] = f"eq.{status}"

        try:
            response = await self._client.get(
                "/documents",
                params=params,
                headers={"Prefer": "count=exact"},
            )
            response.raise_for_status()
            payload = response.json()
            if not isinstance(payload, list):
                raise TypeError("PostgREST list response must be an array")
            total_count = self._parse_total_count(response.headers.get("content-range"))
            return [self._parse_document(row) for row in payload], total_count
        except (httpx.HTTPError, OSError, KeyError, TypeError, ValueError) as exc:
            LOGGER.exception("PostgREST document metadata listing failed")
            raise DocumentRepositoryError("Failed to list document metadata") from exc

    async def create_uploading(self, document: NewDocument) -> Document:
        try:
            response = await self._client.post(
                "/documents",
                params={"select": DOCUMENT_COLUMNS},
                headers={"Prefer": "return=representation"},
                json={
                    "id": str(document.id),
                    "owner_id": str(document.owner_id),
                    "notebook_id": str(document.notebook_id),
                    "original_filename": document.original_filename,
                    "storage_bucket": document.storage_bucket,
                    "storage_object_path": document.storage_object_path,
                    "mime_type": document.mime_type,
                    "size_bytes": document.size_bytes,
                    "content_hash": document.content_hash,
                    "status": "uploading",
                    "error_message": None,
                },
            )
            response.raise_for_status()
            return self._parse_single(response.json(), "create")
        except httpx.HTTPStatusError as exc:
            if exc.response.status_code == 409:
                raise DocumentDuplicateError(
                    "An active document with this content hash already exists"
                ) from exc
            LOGGER.exception("PostgREST document metadata creation failed")
            raise DocumentRepositoryError("Failed to create document metadata") from exc
        except (httpx.HTTPError, OSError, KeyError, TypeError, ValueError) as exc:
            LOGGER.exception("PostgREST document metadata creation failed")
            raise DocumentRepositoryError("Failed to create document metadata") from exc

    async def update_status(
        self,
        document_id: UUID,
        notebook_id: UUID,
        status: str,
        error_message: str | None,
    ) -> Document | None:
        try:
            response = await self._client.patch(
                "/documents",
                params={
                    "id": f"eq.{document_id}",
                    "notebook_id": f"eq.{notebook_id}",
                    "select": DOCUMENT_COLUMNS,
                },
                headers={"Prefer": "return=representation"},
                json={
                    "status": status,
                    "error_message": error_message,
                },
            )
            response.raise_for_status()
            payload = response.json()
            if not isinstance(payload, list):
                raise TypeError("PostgREST update response must be an array")
            if not payload:
                return None
            if len(payload) != 1:
                raise TypeError("PostgREST update response must contain at most one row")
            return self._parse_document(payload[0])
        except (httpx.HTTPError, OSError, KeyError, TypeError, ValueError) as exc:
            LOGGER.exception("PostgREST document status update failed")
            raise DocumentRepositoryError("Failed to update document status") from exc

    def _parse_single(self, payload: object, operation: str) -> Document:
        if not isinstance(payload, list) or len(payload) != 1:
            raise TypeError(f"PostgREST {operation} response must contain exactly one row")
        return self._parse_document(payload[0])

    @staticmethod
    def _parse_total_count(content_range: str | None) -> int:
        if content_range is None or "/" not in content_range:
            raise ValueError("PostgREST count response is missing Content-Range")
        total = content_range.rsplit("/", maxsplit=1)[1]
        if total == "*":
            raise ValueError("PostgREST did not return an exact count")
        return int(total)

    @staticmethod
    def _parse_document(row: object) -> Document:
        if not isinstance(row, Mapping):
            raise TypeError("Document row must be an object")
        return Document(
            id=UUID(str(row["id"])),
            owner_id=UUID(str(row["owner_id"])),
            notebook_id=UUID(str(row["notebook_id"])),
            original_filename=str(row["original_filename"]),
            storage_bucket=str(row["storage_bucket"]),
            storage_object_path=str(row["storage_object_path"]),
            mime_type=str(row["mime_type"]),
            size_bytes=int(row["size_bytes"]),
            content_hash=(str(row["content_hash"]) if row["content_hash"] is not None else None),
            status=str(row["status"]),
            error_message=(str(row["error_message"]) if row["error_message"] is not None else None),
            is_active=bool(row["is_active"]),
            created_at=datetime.fromisoformat(str(row["created_at"])),
            updated_at=datetime.fromisoformat(str(row["updated_at"])),
            normalized_content_hash=(
                str(row["normalized_content_hash"])
                if row.get("normalized_content_hash") is not None
                else None
            ),
            normalization_version=(
                str(row["normalization_version"])
                if row.get("normalization_version") is not None
                else None
            ),
            loose_content_signature=(
                str(row["loose_content_signature"])
                if row.get("loose_content_signature") is not None
                else None
            ),
            canonical_document_id=(
                UUID(str(row["canonical_document_id"]))
                if row.get("canonical_document_id") is not None
                else None
            ),
            version_group_id=(
                UUID(str(row["version_group_id"]))
                if row.get("version_group_id") is not None
                else None
            ),
            version_number=int(row.get("version_number") or 1),
            effective_from=(
                datetime.fromisoformat(str(row["effective_from"])).date()
                if row.get("effective_from") is not None
                else None
            ),
            effective_to=(
                datetime.fromisoformat(str(row["effective_to"])).date()
                if row.get("effective_to") is not None
                else None
            ),
            supersedes_document_id=(
                UUID(str(row["supersedes_document_id"]))
                if row.get("supersedes_document_id") is not None
                else None
            ),
            is_current=bool(row.get("is_current", True)),
            quality_status=str(row.get("quality_status") or "unreviewed"),
        )
