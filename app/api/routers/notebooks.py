"""Notebook routes."""

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status

from app.api.dependencies.auth import get_current_user
from app.api.dependencies.services import get_notebook_service
from app.api.schemas.auth import CurrentUser
from app.api.schemas.notebooks import (
    NotebookCreate,
    NotebookDeleteResponse,
    NotebookResponse,
    NotebookUpdate,
)
from app.notebooks.application.services import NotebookService
from app.notebooks.ports.repositories import NotebookRepositoryError

router = APIRouter(prefix="/notebooks", tags=["notebooks"])


def to_response(notebook: object) -> NotebookResponse:
    return NotebookResponse.model_validate(notebook, from_attributes=True)


@router.get("", response_model=list[NotebookResponse])
async def list_notebooks(
    _current_user: Annotated[CurrentUser, Depends(get_current_user)],
    service: Annotated[NotebookService, Depends(get_notebook_service)],
) -> list[NotebookResponse]:
    try:
        notebooks = await service.list_notebooks()
    except NotebookRepositoryError as exc:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="Notebook storage is unavailable",
        ) from exc
    return [to_response(notebook) for notebook in notebooks]


@router.post("", response_model=NotebookResponse, status_code=status.HTTP_201_CREATED)
async def create_notebook(
    payload: NotebookCreate,
    _current_user: Annotated[CurrentUser, Depends(get_current_user)],
    service: Annotated[NotebookService, Depends(get_notebook_service)],
) -> NotebookResponse:
    try:
        notebook = await service.create_notebook(payload.title, payload.description)
    except NotebookRepositoryError as exc:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="Notebook storage is unavailable",
        ) from exc
    return to_response(notebook)


@router.patch("/{notebook_id}", response_model=NotebookResponse)
async def update_notebook(
    notebook_id: UUID,
    payload: NotebookUpdate,
    _current_user: Annotated[CurrentUser, Depends(get_current_user)],
    service: Annotated[NotebookService, Depends(get_notebook_service)],
) -> NotebookResponse:
    try:
        notebook = await service.update_notebook(
            notebook_id,
            title=payload.title,
            description=payload.description,
        )
    except NotebookRepositoryError as exc:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="Notebook storage is unavailable",
        ) from exc
    if notebook is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Notebook not found",
        )
    return to_response(notebook)


@router.delete("/{notebook_id}", response_model=NotebookDeleteResponse)
async def delete_notebook(
    notebook_id: UUID,
    _current_user: Annotated[CurrentUser, Depends(get_current_user)],
    service: Annotated[NotebookService, Depends(get_notebook_service)],
) -> NotebookDeleteResponse:
    """Soft-delete (archive) a user-owned notebook; all child data is kept."""
    try:
        deleted = await service.delete_notebook(notebook_id)
    except NotebookRepositoryError as exc:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="Notebook storage is unavailable",
        ) from exc
    if not deleted:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Notebook not found",
        )
    return NotebookDeleteResponse(
        message="Notebook archived successfully",
        notebook_id=notebook_id,
    )
