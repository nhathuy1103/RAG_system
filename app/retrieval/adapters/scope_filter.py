"""Shared scope filter for in-memory retrieval adapters."""

from __future__ import annotations

from app.retrieval.domain.filtering import matches_metadata_filters
from app.retrieval.domain.models import EvidenceChunk, RetrievalFilters


def matches_scope(chunk: EvidenceChunk, filters: RetrievalFilters) -> bool:
    metadata = chunk.typed_metadata
    if metadata.text("owner_id") != filters.owner_id:
        return False
    if filters.notebook_id is not None and metadata.text("notebook_id") != filters.notebook_id:
        return False
    if filters.document_ids is not None and chunk.document_id not in filters.document_ids:
        return False
    return matches_metadata_filters(metadata, filters.metadata)


__all__ = ["matches_scope"]
