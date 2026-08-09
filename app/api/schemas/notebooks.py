"""Notebook request and response schemas."""

from datetime import datetime
from typing import Annotated
from uuid import UUID

from pydantic import BaseModel, ConfigDict, StringConstraints, model_validator

NotebookTitle = Annotated[
    str,
    StringConstraints(strip_whitespace=True, min_length=1, max_length=200),
]
NotebookDescription = Annotated[
    str,
    StringConstraints(strip_whitespace=True),
]


class NotebookCreate(BaseModel):
    """Create-notebook payload owned by the authenticated user."""

    model_config = ConfigDict(extra="forbid")

    title: NotebookTitle
    description: NotebookDescription = ""


class NotebookUpdate(BaseModel):
    """Fields that may be changed on an existing notebook."""

    model_config = ConfigDict(extra="forbid")

    title: NotebookTitle | None = None
    description: NotebookDescription | None = None

    @model_validator(mode="after")
    def validate_update(self) -> "NotebookUpdate":
        provided_fields = self.model_fields_set & {"title", "description"}
        if not provided_fields:
            raise ValueError("At least one of title or description must be provided")
        for field_name in provided_fields:
            if getattr(self, field_name) is None:
                raise ValueError(f"{field_name} cannot be null")
        return self


class NotebookResponse(BaseModel):
    """Notebook representation returned by the HTTP API."""

    id: UUID
    owner_id: UUID
    title: str
    description: str
    is_active: bool
    created_at: datetime
    updated_at: datetime


class NotebookDeleteResponse(BaseModel):
    """Confirmation returned after a notebook has been archived (soft-deleted)."""

    message: str
    notebook_id: UUID
