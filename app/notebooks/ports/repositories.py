"""Notebook persistence contracts."""

from typing import Protocol
from uuid import UUID

from app.notebooks.domain.models import Notebook


class NotebookRepositoryError(RuntimeError):
    """Raised when notebook persistence cannot complete safely."""


class NotebookRepository(Protocol):
    """Persistence operations required by notebook use cases."""

    async def exists_owned(self, notebook_id: UUID) -> bool: ...

    async def list_owned(self) -> list[Notebook]: ...

    async def create(self, title: str, description: str = "") -> Notebook: ...

    async def update(
        self,
        notebook_id: UUID,
        changes: dict[str, str],
    ) -> Notebook | None: ...

    async def soft_delete(self, notebook_id: UUID) -> Notebook | None: ...
