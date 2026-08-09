"""Persistence contracts for document metadata."""

from dataclasses import dataclass
from typing import Protocol
from uuid import UUID

from app.documents.domain.models import Document


class DocumentRepositoryError(RuntimeError):
    """Raised when document metadata persistence fails."""


class DocumentDuplicateError(DocumentRepositoryError):
    """Raised when an atomic database constraint finds an exact duplicate."""


@dataclass(frozen=True, slots=True)
class NewDocument:
    """Metadata required before uploading bytes to object storage."""

    id: UUID
    owner_id: UUID
    notebook_id: UUID
    original_filename: str
    storage_bucket: str
    storage_object_path: str
    mime_type: str
    size_bytes: int
    content_hash: str


class DocumentRepository(Protocol):
    """Document metadata operations required by application services."""

    async def get_by_id(
        self,
        document_id: UUID,
        notebook_id: UUID,
    ) -> Document | None: ...

    async def find_by_content_hash(
        self,
        owner_id: UUID,
        notebook_id: UUID,
        content_hash: str,
    ) -> Document | None:
        """Find a live (active, non-failed) duplicate for exact-hash dedup (Layer 1)."""
        ...

    async def soft_delete(
        self,
        document_id: UUID,
        notebook_id: UUID,
    ) -> Document | None: ...

    async def list_by_notebook(
        self,
        notebook_id: UUID,
        *,
        status: str | None,
        limit: int,
        offset: int,
    ) -> tuple[list[Document], int]: ...

    async def create_uploading(self, document: NewDocument) -> Document: ...

    async def update_status(
        self,
        document_id: UUID,
        notebook_id: UUID,
        status: str,
        error_message: str | None,
    ) -> Document | None: ...
