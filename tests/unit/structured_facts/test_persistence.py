"""Migration-16 persistence mapping tests for structured table facts."""

from __future__ import annotations

import json
from dataclasses import replace
from uuid import NAMESPACE_URL, uuid5

import pytest

from app.pipeline.documents.domain.parsed import ParsedTable
from app.pipeline.indexing.domain.embedded_chunk import EmbeddedChunk
from app.structured_facts.application.persistence import (
    build_structured_fact_persistence_batch,
)
from app.structured_facts.application.table_analyzer import TableAnalysis, analyze_table


def _price_table(*, second_price: str = "4.8") -> ParsedTable:
    header = ["Project", "Building", "Unit", "List price", "Effective date"]
    return ParsedTable(
        table_id="price-table-1",
        location="sheet:Prices:page:3:table:1",
        rows=[
            header,
            ["Ocean Park", "S1", "A101", "4.5", "01/03/2026"],
            ["Ocean Park", "S1", "A102", second_price, "01/03/2026"],
        ],
        columns=len(header),
        header=header,
        warnings=["source_table_warning"],
        confidence=0.96,
        metadata={
            "owner_id": "owner-1",
            "notebook_id": "notebook-1",
            "source_block_id": "logical-table-block-1",
            "source_type": "official_price_list",
            "publisher": "Developer A",
            "approval_status": "approved",
            "officiality": True,
            "authority_level": 90,
            "authority_metadata": {"signed": True},
            "page_number": 3,
            "ingested_at": "2026-03-02T12:30:00+00:00",
        },
        cells=[
            {
                "cell_id": f"r{row_index}c{column_index}",
                "row_index": row_index,
                "column_index": column_index,
                "page_number": 3,
                "confidence": 0.95,
            }
            for row_index in (1, 2)
            for column_index in range(len(header))
        ],
    )


def _embedded_chunk(
    *,
    chunk_id: str,
    row_start: int | None,
    row_end: int | None,
    source_block_id: str = "logical-table-block-1",
    table_atomic: bool = False,
) -> EmbeddedChunk:
    metadata: dict[str, object] = {
        "source_block_ids": [source_block_id],
        "table_atomic": table_atomic,
    }
    if row_start is not None:
        metadata["table_data_row_start_ordinal"] = row_start
    if row_end is not None:
        metadata["table_data_row_end_ordinal"] = row_end
    return EmbeddedChunk(
        id=chunk_id,
        document_id="document-1",
        document_version=1,
        owner_id="owner-1",
        tenant_id="notebook-1",
        chunk_index=row_start or 0,
        page_number=3,
        section_title="Prices",
        checksum=f"checksum-{chunk_id}",
        text="one table row",
        canonical_text="one table row",
        token_count=3,
        embedding=(0.1, 0.2),
        embedding_model="test-model",
        metadata=metadata,
    )


def _analysis(table: ParsedTable) -> TableAnalysis:
    return analyze_table(document_id="document-1", table=table)


def test_builds_migration_16_flat_payload_with_deterministic_hashes() -> None:
    table = _price_table()
    analysis = _analysis(table)
    row_zero = _embedded_chunk(chunk_id="chunk-row-0", row_start=0, row_end=0)
    row_one = _embedded_chunk(chunk_id="chunk-row-1", row_start=1, row_end=1)

    first = build_structured_fact_persistence_batch(
        analyses=(analysis,),
        tables=(table,),
        embedded_chunks=(row_one, row_zero),
        template_fingerprint="a" * 64,
    )
    second = build_structured_fact_persistence_batch(
        analyses=(analysis,),
        tables=(table,),
        embedded_chunks=(row_zero, row_one),
        template_fingerprint="a" * 64,
    )

    assert first == second
    snapshot = first.table_snapshots[0]
    assert snapshot["snapshot_key"] == "price-table-1"
    assert snapshot["template_fingerprint"] == "a" * 64
    assert len(str(snapshot["input_content_hash"])) == 64
    assert len(str(snapshot["schema_fingerprint"])) == 64
    assert snapshot["source_chunk_id"] == str(uuid5(NAMESPACE_URL, "chunk:chunk-row-0"))
    assert snapshot["source_type"] == "official_price_list"
    assert snapshot["authority_level"] == 90
    assert snapshot["authority_metadata"] == {
        "approval_status": "approved",
        "officiality": True,
        "signed": True,
    }
    assert snapshot["effective_from"] == "2026-03-01T00:00:00+00:00"
    assert snapshot["ingested_at"] == "2026-03-02T12:30:00+00:00"
    assert "source_table_warning" in snapshot["warnings"]

    claims_by_row = {int(claim["data_row_ordinal"]): claim for claim in first.claims}
    assert set(claims_by_row) == {0, 1}
    assert claims_by_row[0]["source_chunk_id"] == str(uuid5(NAMESPACE_URL, "chunk:chunk-row-0"))
    assert claims_by_row[1]["source_chunk_id"] == str(uuid5(NAMESPACE_URL, "chunk:chunk-row-1"))
    for claim in first.claims:
        assert claim["snapshot_key"] == "price-table-1"
        assert claim["claim_key"] == claim["claim_identity_hash"]
        assert len(str(claim["row_identity_hash"])) == 64
        assert len(str(claim["subject_identity_hash"])) == 64
        assert len(str(claim["candidate_identity_hash"])) == 64
        assert len(str(claim["qualifier_hash"])) == 64
        assert claim["value_type"] == "money"
        assert claim["currency"] == "VND"
        assert claim["numeric_value"] is not None
        assert claim["source_type"] == "official_price_list"
        assert claim["ingested_at"] == "2026-03-02T12:30:00+00:00"
        assert claim["extraction_confidence"] == claim["confidence"]
        provenance = claim["provenance"]
        assert isinstance(provenance, dict)
        assert provenance["chunk_id"] == claim["source_chunk_id"]
        assert claim["data_row_ordinal"] == provenance["data_row_ordinal"]

    # Snapshot storage contains hashes/schema/locator, never the complete table rows.
    snapshot_json = json.dumps(snapshot, ensure_ascii=False)
    assert "A101" not in snapshot_json
    assert "4.5" not in snapshot_json


def test_input_hash_changes_with_table_content_but_schema_hash_does_not() -> None:
    old_table = _price_table(second_price="4.8")
    new_table = _price_table(second_price="5.1")

    old = build_structured_fact_persistence_batch(
        analyses=(_analysis(old_table),),
        tables=(old_table,),
        embedded_chunks=(),
    ).table_snapshots[0]
    new = build_structured_fact_persistence_batch(
        analyses=(_analysis(new_table),),
        tables=(new_table,),
        embedded_chunks=(),
    ).table_snapshots[0]

    assert old["input_content_hash"] != new["input_content_hash"]
    assert old["schema_fingerprint"] == new["schema_fingerprint"]


def test_schema_fingerprint_uses_canonical_columns_not_raw_header_aliases() -> None:
    first_table = ParsedTable(
        table_id="price-table-1",
        location="sheet:prices",
        rows=[
            ["Project", "Building", "Unit", "List price", "Effective date"],
            ["Ocean Park", "S1", "A101", "4500000000", "2026-03-01"],
        ],
        columns=5,
        header=["Project", "Building", "Unit", "List price", "Effective date"],
    )
    second_table = ParsedTable(
        table_id="price-table-1",
        location="sheet:prices",
        rows=[
            ["Dự án", "Tòa", "Mã căn", "Giá niêm yết", "Ngày hiệu lực"],
            ["Ocean Park", "S2", "B202", "5100000000", "2026-04-01"],
        ],
        columns=5,
        header=["Dự án", "Tòa", "Mã căn", "Giá niêm yết", "Ngày hiệu lực"],
    )

    first = build_structured_fact_persistence_batch(
        analyses=(_analysis(first_table),),
        tables=(first_table,),
        embedded_chunks=(),
    ).table_snapshots[0]
    second = build_structured_fact_persistence_batch(
        analyses=(_analysis(second_table),),
        tables=(second_table,),
        embedded_chunks=(),
    ).table_snapshots[0]

    assert first["normalized_schema"] != second["normalized_schema"]
    assert first["schema_fingerprint"] == second["schema_fingerprint"]


def test_unmapped_or_unproven_row_citation_stays_null() -> None:
    table = _price_table()
    analysis = _analysis(table)
    wrong_block = _embedded_chunk(
        chunk_id="wrong-block",
        row_start=0,
        row_end=1,
        source_block_id="another-table",
    )
    incomplete_range = _embedded_chunk(
        chunk_id="incomplete-range",
        row_start=0,
        row_end=None,
    )

    payload = build_structured_fact_persistence_batch(
        analyses=(analysis,),
        tables=(table,),
        embedded_chunks=(wrong_block, incomplete_range),
    )

    assert all(claim["source_chunk_id"] is None for claim in payload.claims)
    for claim in payload.claims:
        provenance = claim["provenance"]
        assert isinstance(provenance, dict)
        assert provenance["chunk_id"] is None
        assert provenance["embedded_chunk_id"] is None


def test_atomic_table_chunk_can_cite_every_row_without_row_range() -> None:
    table = _price_table()
    analysis = _analysis(table)
    atomic = _embedded_chunk(
        chunk_id="atomic-table",
        row_start=None,
        row_end=None,
        table_atomic=True,
    )

    payload = build_structured_fact_persistence_batch(
        analyses=(analysis,),
        tables=(table,),
        embedded_chunks=(atomic,),
    )

    expected = str(uuid5(NAMESPACE_URL, "chunk:atomic-table"))
    assert all(claim["source_chunk_id"] == expected for claim in payload.claims)


def test_mapper_rejects_unknown_table_and_invalid_template_fingerprint() -> None:
    table = _price_table()
    analysis = _analysis(table)
    other_table = replace(table, table_id="other-table")

    with pytest.raises(ValueError, match="unknown parsed table"):
        build_structured_fact_persistence_batch(
            analyses=(analysis,),
            tables=(other_table,),
            embedded_chunks=(),
        )
    with pytest.raises(ValueError, match="template_fingerprint"):
        build_structured_fact_persistence_batch(
            analyses=(analysis,),
            tables=(table,),
            embedded_chunks=(),
            template_fingerprint="not-a-hash",
        )
    with pytest.raises(ValueError, match="unknown table"):
        build_structured_fact_persistence_batch(
            analyses=(analysis,),
            tables=(table,),
            embedded_chunks=(),
            template_fingerprint={"other-table": "a" * 64},
        )


def test_mapper_rejects_claim_with_mismatched_provenance_table() -> None:
    table = _price_table()
    analysis = _analysis(table)
    first = analysis.claims[0]
    wrong_provenance = replace(first.provenance, table_id="another-table")
    wrong_claim = replace(first, provenance=wrong_provenance)
    invalid_analysis = replace(analysis, claims=(wrong_claim,))

    with pytest.raises(ValueError, match="provenance table_id"):
        build_structured_fact_persistence_batch(
            analyses=(invalid_analysis,),
            tables=(table,),
            embedded_chunks=(),
        )
