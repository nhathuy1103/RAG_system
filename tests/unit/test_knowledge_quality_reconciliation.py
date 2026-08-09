"""Tests for deterministic Postgres/vector inventory reconciliation."""

import pytest

from app.knowledge_quality.application.reconciliation import (
    DatabaseChunkState,
    VectorChunkState,
    reconcile_chunk_inventories,
)


def _database_chunk(
    chunk_id: str,
    *,
    checksum: str = "checksum-a",
    embedding_present: bool = True,
) -> DatabaseChunkState:
    return DatabaseChunkState(
        id=chunk_id,
        document_id="document-a",
        owner_id="owner-a",
        notebook_id="notebook-a",
        checksum=checksum,
        normalized_content_hash="a" * 64,
        exact_duplicate_group_id="group-a",
        ingestion_generation="generation-a",
        embedding_present=embedding_present,
    )


def _vector_chunk(
    chunk_id: str,
    *,
    checksum: str = "checksum-a",
) -> VectorChunkState:
    return VectorChunkState(
        id=chunk_id,
        document_id="document-a",
        owner_id="owner-a",
        notebook_id="notebook-a",
        checksum=checksum,
        normalized_content_hash="a" * 64,
        exact_duplicate_group_id="group-a",
        ingestion_generation="generation-a",
    )


def test_reconciliation_reports_healthy_identical_inventory() -> None:
    report = reconcile_chunk_inventories(
        [_database_chunk("chunk-a")],
        [_vector_chunk("chunk-a")],
    )

    assert report.healthy is True
    assert report.to_dict()["healthy"] is True


def test_reconciliation_reports_missing_orphan_embedding_and_field_drift() -> None:
    report = reconcile_chunk_inventories(
        [
            _database_chunk("shared", embedding_present=False),
            _database_chunk("missing"),
        ],
        [
            _vector_chunk("shared", checksum="changed"),
            _vector_chunk("orphan"),
        ],
    )

    assert report.healthy is False
    assert report.missing_vector_ids == ("missing",)
    assert report.orphan_vector_ids == ("orphan",)
    assert report.database_chunks_without_embedding == ("shared",)
    assert [(item.chunk_id, item.field) for item in report.mismatches] == [("shared", "checksum")]


def test_reconciliation_rejects_ambiguous_duplicate_inventory_ids() -> None:
    with pytest.raises(ValueError, match="Duplicate chunk ID"):
        reconcile_chunk_inventories(
            [_database_chunk("duplicate"), _database_chunk("duplicate")],
            [],
        )
