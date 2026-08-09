"""Supabase Storage implementation of short-lived source URL signing."""

from __future__ import annotations

import logging
from collections.abc import Mapping
from urllib.parse import urljoin

import httpx2 as httpx

from app.documents.ports.source_signing import SourceSigningError, SourceUrlSigner

LOGGER = logging.getLogger(__name__)


class SupabaseSourceUrlSigner(SourceUrlSigner):
    def __init__(self, client: httpx.AsyncClient, storage_base_url: str) -> None:
        self._client = client
        self._storage_base_url = storage_base_url.rstrip("/") + "/"

    async def sign(self, bucket_name: str, object_path: str, *, expires_in: int) -> str:
        try:
            response = await self._client.post(
                f"/object/sign/{bucket_name}/{object_path}", json={"expiresIn": expires_in}
            )
            response.raise_for_status()
            payload = response.json()
            if not isinstance(payload, Mapping):
                raise TypeError("Storage signing response must be an object")
            value = payload.get("signedURL", payload.get("signedUrl"))
            if not isinstance(value, str) or not value:
                raise TypeError("Storage signing response has no signed URL")
            return (
                value
                if value.startswith(("http://", "https://"))
                else urljoin(self._storage_base_url, value.lstrip("/"))
            )
        except (httpx.HTTPError, OSError, TypeError, ValueError) as exc:
            LOGGER.exception("Supabase source URL signing failed")
            raise SourceSigningError("Could not create a source download link") from exc
