"""Supabase Storage adapter for document bytes."""

import logging
from collections.abc import Mapping

import httpx2 as httpx

from app.documents.ports.storage import (
    DocumentObjectStorage,
    ObjectStorageError,
)

LOGGER = logging.getLogger(__name__)


class SupabaseDocumentStorage(DocumentObjectStorage):
    """Store immutable document bytes in a private Supabase bucket."""

    def __init__(self, client: httpx.AsyncClient) -> None:
        self._client = client

    async def upload(
        self,
        bucket: str,
        object_path: str,
        content: bytes,
        mime_type: str,
    ) -> None:
        try:
            response = await self._client.post(
                f"/object/{bucket}/{object_path}",
                headers={
                    "Content-Type": mime_type,
                    "x-upsert": "false",
                },
                content=content,
            )
            if response.status_code >= 400:
                LOGGER.error(
                    "Supabase Storage upload rejected (status=%s, path=%s): %s",
                    response.status_code,
                    object_path,
                    response.text,
                )
            response.raise_for_status()
        except (httpx.HTTPError, OSError) as exc:
            LOGGER.exception("Supabase Storage document upload failed")
            raise ObjectStorageError("Failed to upload document object") from exc

    async def delete(self, bucket: str, object_path: str) -> None:
        try:
            response = await self._client.delete(f"/object/{bucket}/{object_path}")
            if self._is_missing_object(response):
                return
            response.raise_for_status()
        except (httpx.HTTPError, OSError) as exc:
            LOGGER.exception("Supabase Storage document deletion failed")
            raise ObjectStorageError("Failed to delete document object") from exc

    async def download(self, bucket: str, object_path: str) -> bytes:
        try:
            response = await self._client.get(f"/object/authenticated/{bucket}/{object_path}")
            response.raise_for_status()
            return response.content
        except (httpx.HTTPError, OSError) as exc:
            LOGGER.exception("Supabase Storage document download failed")
            raise ObjectStorageError("Failed to download document object") from exc

    @staticmethod
    def _is_missing_object(response: httpx.Response) -> bool:
        if response.status_code == 404:
            return True
        if response.status_code != 400:
            return False
        try:
            payload = response.json()
        except ValueError:
            return False
        if not isinstance(payload, Mapping):
            return False
        return payload.get("statusCode") in {404, "404"} and payload.get("error") == "not_found"
