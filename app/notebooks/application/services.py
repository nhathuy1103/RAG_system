"""Notebook application services."""

from uuid import UUID

from app.notebooks.domain.models import Notebook
from app.notebooks.ports.repositories import NotebookRepository


class NotebookService:
    """Coordinate notebook use cases through a repository port."""

    def __init__(self, repository: NotebookRepository) -> None:
        self._repository = repository

    async def list_notebooks(self) -> list[Notebook]:
        return await self._repository.list_owned()

    async def create_notebook(self, title: str, description: str = "") -> Notebook:
        return await self._repository.create(title.strip(), description.strip())

    async def update_notebook(
        self,
        notebook_id: UUID,
        *,
        title: str | None = None,
        description: str | None = None,
    ) -> Notebook | None:
        changes: dict[str, str] = {}
        if title is not None:
            changes["title"] = title.strip()
        if description is not None:
            changes["description"] = description.strip()
        return await self._repository.update(notebook_id, changes)

    async def delete_notebook(self, notebook_id: UUID) -> bool:
        """Soft-delete: archive the notebook, keep all child data intact."""
        notebook = await self._repository.soft_delete(notebook_id)
        return notebook is not None
