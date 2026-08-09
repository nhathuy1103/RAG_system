from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from typing import Protocol, runtime_checkable

from app.pipeline.indexing.domain.embedded_chunk import EmbeddedChunk


@dataclass(frozen=True)
class VectorSearchHit:
    """One scored result from a query-time vector search.

    ``chunk_id`` is the canonical persistent ID shared by the Qdrant point and
    ``document_chunks.id``. It is not the chunker's composite source ID.
    """

    chunk_id: str
    document_id: str
    score: float
    text: str
    page_number: int | None
    section_title: str | None
    document_version: int
    checksum: str | None = None
    chunk_index: int | None = None
    normalized_content_hash: str | None = None
    exact_duplicate_group_id: str | None = None
    metadata: dict[str, object] = field(default_factory=dict)


class VectorIndex(Protocol):
    def is_ready(self) -> bool: ...

    def upsert_chunks(self, chunks: Sequence[EmbeddedChunk]) -> None: ...

    def delete_document_vectors(self, document_id: str) -> None: ...

    def delete_document_version_vectors(
        self,
        document_id: str,
        document_version: int,
    ) -> None: ...

    def query(
        self,
        embedding: Sequence[float],
        *,
        owner_id: str,
        document_ids: Sequence[str] | None,
        limit: int,
        tenant_id: str | None = None,
        metadata_filters: Mapping[str, str | int] | None = None,
    ) -> list[VectorSearchHit]: ...


@runtime_checkable
class GenerationAwareVectorIndex(Protocol):
    """Optional capabilities for fencing external vector-store generations."""

    completion_is_transactional: bool

    def delete_document_generation_vectors(
        self,
        document_id: str,
        generation: str,
    ) -> None: ...

    def finalize_document_generation(
        self,
        document_id: str,
        document_version: int,
        generation: str,
    ) -> None: ...


__all__ = ["GenerationAwareVectorIndex", "VectorIndex", "VectorSearchHit"]
