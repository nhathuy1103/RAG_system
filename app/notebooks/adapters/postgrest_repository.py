"""Supabase PostgREST notebook repository."""

import logging
from collections.abc import Mapping
from datetime import datetime
from uuid import UUID

import httpx2 as httpx

from app.notebooks.domain.models import Notebook
from app.notebooks.ports.repositories import (
    NotebookRepository,
    NotebookRepositoryError,
)

LOGGER = logging.getLogger(__name__)

NOTEBOOK_COLUMNS = "id,owner_id,title,description,is_active,created_at,updated_at"


class PostgrestNotebookRepository(NotebookRepository):
    """Persist notebooks through a user-scoped Supabase Data API client."""

    def __init__(self, client: httpx.AsyncClient) -> None:
        self._client = client

    async def exists_owned(self, notebook_id: UUID) -> bool:
        try:
            response = await self._client.get(
                "/notebooks",
                params={
                    "select": "id",
                    "id": f"eq.{notebook_id}",
                    "is_active": "eq.true",
                    "limit": "1",
                },
            )
            response.raise_for_status()
            payload = response.json()
            if not isinstance(payload, list):
                raise TypeError("PostgREST existence response must be an array")
            return len(payload) == 1
        except (httpx.HTTPError, OSError, TypeError, ValueError) as exc:
            LOGGER.exception("PostgREST notebook lookup failed")
            raise NotebookRepositoryError("Failed to find notebook") from exc

    async def list_owned(self) -> list[Notebook]:
        try:
            response = await self._client.get(
                "/notebooks",
                params={
                    "select": NOTEBOOK_COLUMNS,
                    "is_active": "eq.true",
                    "order": "updated_at.desc,id.asc",
                    "limit": "100",
                },
            )
            response.raise_for_status()
            payload = response.json()
            if not isinstance(payload, list):
                raise TypeError("PostgREST list response must be an array")
            return [self._parse_notebook(row) for row in payload]
        except (httpx.HTTPError, OSError, KeyError, TypeError, ValueError) as exc:
            LOGGER.exception("PostgREST notebook listing failed")
            raise NotebookRepositoryError("Failed to list notebooks") from exc

    async def create(self, title: str, description: str = "") -> Notebook:
        try:
            response = await self._client.post(
                "/notebooks",
                params={"select": NOTEBOOK_COLUMNS},
                headers={"Prefer": "return=representation"},
                json={"title": title, "description": description},
            )
            response.raise_for_status()
            payload = response.json()
            if not isinstance(payload, list) or len(payload) != 1:
                raise TypeError("PostgREST create response must contain one row")
            return self._parse_notebook(payload[0])
        except (httpx.HTTPError, OSError, KeyError, TypeError, ValueError) as exc:
            LOGGER.exception("PostgREST notebook creation failed")
            raise NotebookRepositoryError("Failed to create notebook") from exc

    async def update(
        self,
        notebook_id: UUID,
        changes: dict[str, str],
    ) -> Notebook | None:
        try:
            response = await self._client.patch(
                "/notebooks",
                params={
                    "id": f"eq.{notebook_id}",
                    "is_active": "eq.true",
                    "select": NOTEBOOK_COLUMNS,
                },
                headers={"Prefer": "return=representation"},
                json=changes,
            )
            response.raise_for_status()
            payload = response.json()
            if not isinstance(payload, list):
                raise TypeError("PostgREST update response must be an array")
            if not payload:
                return None
            if len(payload) != 1:
                raise TypeError("PostgREST update response must contain at most one row")
            return self._parse_notebook(payload[0])
        except (httpx.HTTPError, OSError, KeyError, TypeError, ValueError) as exc:
            LOGGER.exception("PostgREST notebook update failed")
            raise NotebookRepositoryError("Failed to update notebook") from exc

    async def soft_delete(self, notebook_id: UUID) -> Notebook | None:
        """Archive a notebook: is_active=false, all child data is kept."""
        try:
            response = await self._client.patch(
                "/notebooks",
                params={
                    "id": f"eq.{notebook_id}",
                    "is_active": "eq.true",
                    "select": NOTEBOOK_COLUMNS,
                },
                headers={"Prefer": "return=representation"},
                json={"is_active": False},
            )
            response.raise_for_status()
            payload = response.json()
            if not isinstance(payload, list):
                raise TypeError("PostgREST soft delete response must be an array")
            if not payload:
                return None
            if len(payload) != 1:
                raise TypeError("PostgREST soft delete response must contain at most one row")
            return self._parse_notebook(payload[0])
        except (httpx.HTTPError, OSError, KeyError, TypeError, ValueError) as exc:
            LOGGER.exception("PostgREST notebook soft delete failed")
            raise NotebookRepositoryError("Failed to archive notebook") from exc

    @staticmethod
    def _parse_notebook(row: object) -> Notebook:
        if not isinstance(row, Mapping):
            raise TypeError("Notebook row must be an object")
        return Notebook(
            id=UUID(str(row["id"])),
            owner_id=UUID(str(row["owner_id"])),
            title=str(row["title"]),
            description=str(row["description"]),
            is_active=bool(row["is_active"]),
            created_at=datetime.fromisoformat(str(row["created_at"])),
            updated_at=datetime.fromisoformat(str(row["updated_at"])),
        )
