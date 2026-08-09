"""Notebook domain entities."""

from dataclasses import dataclass
from datetime import datetime
from uuid import UUID


@dataclass(frozen=True, slots=True)
class Notebook:
    """A user-owned collection of sources and conversations."""

    id: UUID
    owner_id: UUID
    title: str
    description: str
    created_at: datetime
    updated_at: datetime
    is_active: bool = True

    def __post_init__(self) -> None:
        normalized_title = self.title.strip()
        if not 1 <= len(normalized_title) <= 200:
            raise ValueError("Notebook title must contain 1 to 200 characters")
        object.__setattr__(self, "title", normalized_title)
        object.__setattr__(self, "description", self.description.strip())
