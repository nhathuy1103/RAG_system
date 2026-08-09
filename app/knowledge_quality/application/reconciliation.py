"""Deterministic Postgres/vector-store inventory reconciliation."""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import asdict, dataclass


@dataclass(frozen=True, slots=True)
class DatabaseChunkState:
    """Authoritative chunk identity read from Postgres."""

    id: str
    document_id: str
    owner_id: str
    notebook_id: str
    checksum: str
    normalized_content_hash: str
    exact_duplicate_group_id: str
    ingestion_generation: str
    embedding_present: bool


@dataclass(frozen=True, slots=True)
class VectorChunkState:
    """External vector point identity and integrity metadata."""

    id: str
    document_id: str
    owner_id: str
    notebook_id: str
    checksum: str
    normalized_content_hash: str
    exact_duplicate_group_id: str
    ingestion_generation: str


@dataclass(frozen=True, slots=True)
class ReconciliationMismatch:
    """One field-level mismatch for a shared chunk ID."""

    chunk_id: str
    field: str
    database_value: str
    vector_value: str


@dataclass(frozen=True, slots=True)
class ReconciliationReport:
    """Machine-readable drift report; no mutation is performed here."""

    database_chunk_count: int
    vector_chunk_count: int
    missing_vector_ids: tuple[str, ...]
    orphan_vector_ids: tuple[str, ...]
    database_chunks_without_embedding: tuple[str, ...]
    mismatches: tuple[ReconciliationMismatch, ...]

    @property
    def healthy(self) -> bool:
        return not (
            self.missing_vector_ids
            or self.orphan_vector_ids
            or self.database_chunks_without_embedding
            or self.mismatches
        )

    def to_dict(self) -> dict[str, object]:
        return {
            "healthy": self.healthy,
            "database_chunk_count": self.database_chunk_count,
            "vector_chunk_count": self.vector_chunk_count,
            "missing_vector_ids": list(self.missing_vector_ids),
            "orphan_vector_ids": list(self.orphan_vector_ids),
            "database_chunks_without_embedding": list(self.database_chunks_without_embedding),
            "mismatches": [asdict(item) for item in self.mismatches],
        }


def reconcile_chunk_inventories(
    database_chunks: Iterable[DatabaseChunkState],
    vector_chunks: Iterable[VectorChunkState],
) -> ReconciliationReport:
    """Compare authoritative rows and external points without changing either."""
    database_by_id = _unique_by_id(database_chunks, source="database")
    vector_by_id = _unique_by_id(vector_chunks, source="vector store")
    database_ids = set(database_by_id)
    vector_ids = set(vector_by_id)
    missing = tuple(sorted(database_ids - vector_ids))
    orphans = tuple(sorted(vector_ids - database_ids))
    without_embedding = tuple(
        sorted(chunk.id for chunk in database_by_id.values() if not chunk.embedding_present)
    )

    mismatches: list[ReconciliationMismatch] = []
    fields = (
        "document_id",
        "owner_id",
        "notebook_id",
        "checksum",
        "normalized_content_hash",
        "exact_duplicate_group_id",
        "ingestion_generation",
    )
    for chunk_id in sorted(database_ids & vector_ids):
        database_chunk = database_by_id[chunk_id]
        vector_chunk = vector_by_id[chunk_id]
        for field_name in fields:
            database_value = str(getattr(database_chunk, field_name) or "")
            vector_value = str(getattr(vector_chunk, field_name) or "")
            if database_value != vector_value:
                mismatches.append(
                    ReconciliationMismatch(
                        chunk_id=chunk_id,
                        field=field_name,
                        database_value=database_value,
                        vector_value=vector_value,
                    )
                )

    return ReconciliationReport(
        database_chunk_count=len(database_by_id),
        vector_chunk_count=len(vector_by_id),
        missing_vector_ids=missing,
        orphan_vector_ids=orphans,
        database_chunks_without_embedding=without_embedding,
        mismatches=tuple(mismatches),
    )


def _unique_by_id[ChunkStateT: (DatabaseChunkState, VectorChunkState)](
    records: Iterable[ChunkStateT],
    *,
    source: str,
) -> dict[str, ChunkStateT]:
    result: dict[str, ChunkStateT] = {}
    for record in records:
        if record.id in result:
            raise ValueError(f"Duplicate chunk ID {record.id!r} in {source}")
        result[record.id] = record
    return result


__all__ = [
    "DatabaseChunkState",
    "ReconciliationMismatch",
    "ReconciliationReport",
    "VectorChunkState",
    "reconcile_chunk_inventories",
]
