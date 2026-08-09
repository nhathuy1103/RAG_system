"""Unit tests for notebook domain and application behavior."""

from datetime import UTC, datetime
from uuid import UUID

import pytest

from app.notebooks.application.services import NotebookService
from app.notebooks.domain.models import Notebook

NOTEBOOK_ID = UUID("10000000-0000-0000-0000-000000000001")
OWNER_ID = UUID("20000000-0000-0000-0000-000000000002")
NOW = datetime(2026, 7, 24, tzinfo=UTC)


class FakeNotebookRepository:
    def __init__(self) -> None:
        self.created_title: str | None = None
        self.created_description: str | None = None
        self.updated_id: UUID | None = None
        self.updated_changes: dict[str, str] | None = None
        self.soft_deleted_id: UUID | None = None
        self.notebook = Notebook(
            id=NOTEBOOK_ID,
            owner_id=OWNER_ID,
            title="Notebook",
            description="Mô tả",
            created_at=NOW,
            updated_at=NOW,
        )

    async def exists_owned(self, notebook_id: UUID) -> bool:
        return notebook_id == self.notebook.id

    async def list_owned(self) -> list[Notebook]:
        return [self.notebook]

    async def create(self, title: str, description: str = "") -> Notebook:
        self.created_title = title
        self.created_description = description
        return Notebook(
            id=self.notebook.id,
            owner_id=self.notebook.owner_id,
            title=title,
            description=description,
            created_at=self.notebook.created_at,
            updated_at=self.notebook.updated_at,
        )

    async def update(
        self,
        notebook_id: UUID,
        changes: dict[str, str],
    ) -> Notebook | None:
        self.updated_id = notebook_id
        self.updated_changes = changes
        return Notebook(
            id=self.notebook.id,
            owner_id=self.notebook.owner_id,
            title=changes.get("title", self.notebook.title),
            description=changes.get("description", self.notebook.description),
            created_at=self.notebook.created_at,
            updated_at=self.notebook.updated_at,
        )

    async def soft_delete(self, notebook_id: UUID) -> Notebook | None:
        self.soft_deleted_id = notebook_id
        if notebook_id != self.notebook.id:
            return None
        return Notebook(
            id=self.notebook.id,
            owner_id=self.notebook.owner_id,
            title=self.notebook.title,
            description=self.notebook.description,
            created_at=self.notebook.created_at,
            updated_at=self.notebook.updated_at,
            is_active=False,
        )


def test_notebook_normalizes_title() -> None:
    notebook = Notebook(
        id=NOTEBOOK_ID,
        owner_id=OWNER_ID,
        title="  Báo cáo quý  ",
        description="  Tổng hợp kết quả  ",
        created_at=NOW,
        updated_at=NOW,
    )

    assert notebook.title == "Báo cáo quý"
    assert notebook.description == "Tổng hợp kết quả"


def test_notebook_rejects_blank_title() -> None:
    with pytest.raises(ValueError, match="1 to 200"):
        Notebook(
            id=NOTEBOOK_ID,
            owner_id=OWNER_ID,
            title="   ",
            description="",
            created_at=NOW,
            updated_at=NOW,
        )


@pytest.mark.anyio
async def test_service_delegates_to_repository() -> None:
    repository = FakeNotebookRepository()
    service = NotebookService(repository)

    created = await service.create_notebook("  Notebook mới  ", "  Mô tả mới  ")
    listed = await service.list_notebooks()

    assert repository.created_title == "Notebook mới"
    assert repository.created_description == "Mô tả mới"
    assert created.title == "Notebook mới"
    assert created.description == "Mô tả mới"
    assert listed == [repository.notebook]


@pytest.mark.anyio
async def test_service_updates_only_provided_fields() -> None:
    repository = FakeNotebookRepository()
    service = NotebookService(repository)

    updated = await service.update_notebook(
        NOTEBOOK_ID,
        description="  Mô tả đã sửa  ",
    )

    assert repository.updated_id == NOTEBOOK_ID
    assert repository.updated_changes == {"description": "Mô tả đã sửa"}
    assert updated is not None
    assert updated.title == "Notebook"
    assert updated.description == "Mô tả đã sửa"


@pytest.mark.anyio
async def test_service_soft_deletes_notebook() -> None:
    repository = FakeNotebookRepository()
    service = NotebookService(repository)

    deleted = await service.delete_notebook(NOTEBOOK_ID)

    assert deleted is True
    assert repository.soft_deleted_id == NOTEBOOK_ID


@pytest.mark.anyio
async def test_service_returns_false_when_notebook_is_not_owned() -> None:
    repository = FakeNotebookRepository()
    service = NotebookService(repository)

    deleted = await service.delete_notebook(UUID("40000000-0000-0000-0000-000000000004"))

    assert deleted is False
