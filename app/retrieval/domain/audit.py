"""Small, content-free audit projections for retrieval telemetry."""

from __future__ import annotations

from collections.abc import Mapping, Sequence

from app.retrieval.domain.filtering import matches_metadata_filters
from app.retrieval.domain.models import RetrievalCandidate, StructuredMetadataFilters


def candidate_metadata_audit(
    candidates: Sequence[RetrievalCandidate],
    filters: StructuredMetadataFilters,
) -> list[dict[str, object]]:
    """Describe returned candidates without copying their chunk text into telemetry."""

    records: list[dict[str, object]] = []
    for candidate in candidates:
        metadata = candidate.chunk.typed_metadata
        nested = metadata.get("retrieval_metadata")
        retrieval_metadata = dict(nested) if isinstance(nested, Mapping) else {}
        records.append(
            {
                "chunk_id": candidate.chunk.id,
                "document_id": candidate.chunk.document_id,
                "rank": candidate.rank,
                "score": candidate.score,
                "source": candidate.source,
                "retrieval_metadata": retrieval_metadata,
                "matches_metadata_filters": matches_metadata_filters(metadata, filters),
            }
        )
    return records


__all__ = ["candidate_metadata_audit"]
