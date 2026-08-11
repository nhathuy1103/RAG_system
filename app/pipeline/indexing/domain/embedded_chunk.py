from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime


@dataclass(frozen=True)
class EmbeddedChunk:
    id: str
    document_id: str
    document_version: int
    owner_id: str
    tenant_id: str
    chunk_index: int
    page_number: int | None
    section_title: str | None
    checksum: str
    text: str
    canonical_text: str
    token_count: int
    embedding: tuple[float, ...]
    embedding_model: str
    metadata: dict[str, object] = field(default_factory=dict)
    retrieval_metadata: dict[str, object] = field(default_factory=dict)
    provenance_metadata: dict[str, object] = field(default_factory=dict)
    authority_metadata: dict[str, object] = field(default_factory=dict)
    embedding_text: str | None = None
    search_text: str | None = None
    retrieval_projection_version: str = "retrieval-projection-v1"
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))

    @property
    def vector_size(self) -> int:
        return len(self.embedding)


__all__ = ["EmbeddedChunk"]
