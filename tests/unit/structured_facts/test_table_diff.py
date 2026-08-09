from __future__ import annotations

from typing import cast

from app.pipeline.documents.domain.parsed import ParsedTable
from app.structured_facts.application.table_analyzer import TableAnalysis, analyze_table
from app.structured_facts.application.table_diff import diff_table_analyses
from app.structured_facts.domain.models import ClaimRelationType


def _price_table(
    *,
    table_id: str,
    document_id: str,
    rows: list[list[str]],
    price_header: str = "Giá NY (VND)",
    date_header: str = "Ngày hiệu lực",
    confidence: float | None = None,
    cells: list[dict[str, object]] | None = None,
) -> TableAnalysis:
    header = ["Dự án", "Tòa", "Mã căn", price_header, date_header]
    table = ParsedTable(
        table_id=table_id,
        location="sheet:Bang gia:page:1",
        rows=[header, *rows],
        columns=len(header),
        header=header,
        confidence=confidence,
        cells=cells or [],
    )
    return analyze_table(document_id=document_id, table=table)


def test_table_diff_joins_every_row_by_identity_not_position() -> None:
    old_rows = [
        ["Ocean Park", "S1", f"A{index:04d}", str(4_500_000_000 + index), "01/03/2026"]
        for index in range(1_000)
    ]
    new_rows = [list(row) for row in reversed(old_rows[1:])]
    by_unit = {row[2]: row for row in new_rows}
    by_unit["A0500"][3] = "4700000000"
    by_unit["A0750"][3] = "4800000000"
    new_rows.append(["Ocean Park", "S1", "A1000", "4900000000", "01/03/2026"])
    left = _price_table(table_id="prices-old", document_id="old-document", rows=old_rows)
    right = _price_table(table_id="prices-new", document_id="new-document", rows=new_rows)

    result = diff_table_analyses(left, right)

    assert result.summary_counts[ClaimRelationType.UNCHANGED.value] == 997
    assert result.summary_counts[ClaimRelationType.CONFLICT_CANDIDATE.value] == 2
    assert result.summary_counts[ClaimRelationType.ADDED.value] == 1
    assert result.summary_counts[ClaimRelationType.REMOVED.value] == 1
    assert len(result.relations) == 1_001


def test_table_diff_classifies_non_overlapping_prices_as_updates() -> None:
    left = _price_table(
        table_id="february",
        document_id="old-document",
        rows=[["Ocean Park", "S1", "A101", "4500000000", "02/2026"]],
    )
    right = _price_table(
        table_id="march",
        document_id="new-document",
        rows=[["Ocean Park", "S1", "A101", "4800000000", "03/2026"]],
    )

    result = diff_table_analyses(left, right)

    assert result.summary_counts[ClaimRelationType.UPDATED.value] == 1
    assert result.relations[0].reason_codes == ("non_overlapping_effective_intervals",)


def test_table_diff_requires_overlapping_time_for_conflict() -> None:
    left = _price_table(
        table_id="source-a",
        document_id="source-a",
        rows=[["Ocean Park", "S1", "A101", "4500000000", "01/03/2026"]],
    )
    right = _price_table(
        table_id="source-b",
        document_id="source-b",
        rows=[["Ocean Park", "S1", "A101", "4800000000", "01/03/2026"]],
    )

    result = diff_table_analyses(left, right)

    assert result.summary_counts[ClaimRelationType.CONFLICT_CANDIDATE.value] == 1
    assert result.relations[0].reason_codes == ("overlapping_effective_value_mismatch",)


def test_table_diff_treats_price_type_change_as_conditional_variant() -> None:
    left = _price_table(
        table_id="list-price",
        document_id="source-a",
        price_header="Giá NY (VND)",
        rows=[["Ocean Park", "S1", "A101", "4500000000", "01/03/2026"]],
    )
    right = _price_table(
        table_id="discount-price",
        document_id="source-b",
        price_header="Giá sau chiết khấu (VND)",
        rows=[["Ocean Park", "S1", "A101", "4200000000", "01/03/2026"]],
    )

    result = diff_table_analyses(left, right)

    assert result.summary_counts[ClaimRelationType.CONDITIONAL_VARIANT.value] == 1
    assert result.relations[0].reason_codes == ("disjoint_claim_qualifiers",)


def test_table_diff_missing_vat_qualifier_is_uncertain_not_conflict() -> None:
    left = _price_table(
        table_id="vat-explicit",
        document_id="source-a",
        price_header="Giá NY (đã VAT)",
        rows=[["Ocean Park", "S1", "A101", "4500000000", "01/03/2026"]],
    )
    right = _price_table(
        table_id="vat-unknown",
        document_id="source-b",
        price_header="Giá NY",
        rows=[["Ocean Park", "S1", "A101", "4400000000", "01/03/2026"]],
    )

    result = diff_table_analyses(left, right)

    assert result.summary_counts[ClaimRelationType.UNCERTAIN.value] == 1
    assert result.relations[0].reason_codes == ("unknown_claim_qualifiers",)


def test_table_diff_unknown_time_blocks_value_conflict() -> None:
    left = _price_table(
        table_id="no-date-a",
        document_id="source-a",
        rows=[["Ocean Park", "S1", "A101", "4500000000", ""]],
    )
    right = _price_table(
        table_id="no-date-b",
        document_id="source-b",
        rows=[["Ocean Park", "S1", "A101", "4800000000", ""]],
    )

    result = diff_table_analyses(left, right)

    assert result.summary_counts[ClaimRelationType.UNCERTAIN.value] == 1
    assert result.relations[0].reason_codes == ("unknown_effective_interval",)


def test_table_diff_low_cell_confidence_is_uncertain() -> None:
    low_confidence_cell = {
        "cell_id": "price-cell",
        "row_index": 1,
        "column_index": 3,
        "confidence": 0.4,
    }
    left = _price_table(
        table_id="same-table",
        document_id="source-a",
        rows=[["Ocean Park", "S1", "A101", "4500000000", "01/03/2026"]],
        cells=[low_confidence_cell],
    )
    right = _price_table(
        table_id="same-table",
        document_id="source-b",
        rows=[["Ocean Park", "S1", "A101", "4800000000", "01/03/2026"]],
    )

    result = diff_table_analyses(left, right)

    assert result.summary_counts[ClaimRelationType.UNCERTAIN.value] == 1
    assert result.relations[0].reason_codes == ("low_extraction_confidence",)


def test_table_diff_different_buildings_never_create_false_conflict() -> None:
    left = _price_table(
        table_id="building-s1",
        document_id="source-a",
        rows=[["Ocean Park", "S1", "A101", "4500000000", "01/03/2026"]],
    )
    right = _price_table(
        table_id="building-s2",
        document_id="source-b",
        rows=[["Ocean Park", "S2", "A101", "4800000000", "01/03/2026"]],
    )

    result = diff_table_analyses(left, right)

    assert result.summary_counts[ClaimRelationType.CONFLICT_CANDIDATE.value] == 0
    assert result.summary_counts[ClaimRelationType.REMOVED.value] == 1
    assert result.summary_counts[ClaimRelationType.ADDED.value] == 1


def test_table_diff_derived_total_matches_published_total_with_tolerance() -> None:
    total_header = ["Dự án", "Tòa", "Mã căn", "Giá bán", "Ngày hiệu lực"]
    component_header = [
        "Dự án",
        "Tòa",
        "Mã căn",
        "Đơn giá (triệu/m²)",
        "DT thông thủy (m²)",
        "Ngày hiệu lực",
    ]
    total = analyze_table(
        document_id="published-total",
        table=ParsedTable(
            table_id="total",
            location="sheet:1",
            rows=[total_header, ["Ocean Park", "S1", "A101", "4,5 tỷ", "01/03/2026"]],
            columns=len(total_header),
            header=total_header,
        ),
    )
    components = analyze_table(
        document_id="components",
        table=ParsedTable(
            table_id="components",
            location="sheet:1",
            rows=[
                component_header,
                ["Ocean Park", "S1", "A101", "64,285", "70", "01/03/2026"],
            ],
            columns=len(component_header),
            header=component_header,
        ),
    )

    result = diff_table_analyses(total, components)

    derived = next(claim for claim in components.claims if claim.derivation is not None)
    assert derived.value.value == "4499950000"
    assert derived.derivation is not None
    assert len(derived.derivation.input_claim_ids) == 2
    assert any(
        relation.relation_type is ClaimRelationType.UNCHANGED
        and relation.target_claim_id == derived.id
        for relation in result.relations
    )


def test_table_diff_duplicate_row_identity_is_uncertain() -> None:
    rows = [
        ["Ocean Park", "S1", "A101", "4500000000", "01/03/2026"],
        ["Ocean Park", "S1", "A101", "4600000000", "01/03/2026"],
    ]
    left = _price_table(table_id="duplicate-a", document_id="a", rows=rows)
    right = _price_table(table_id="duplicate-b", document_id="b", rows=rows)

    result = diff_table_analyses(left, right)

    # Four one-sided relations preserve all four claims without inventing two
    # source/target pairs from their incidental row positions.
    assert result.summary_counts[ClaimRelationType.UNCERTAIN.value] == 4
    assert len(result.relations) == len(left.claims) + len(right.claims)
    assert all(
        relation.reason_codes == ("duplicate_business_key",) for relation in result.relations
    )
    assert all(
        (relation.source_claim_id is None) != (relation.target_claim_id is None)
        for relation in result.relations
    )
    source_ids = {
        relation.source_claim_id for relation in result.relations if relation.source_claim_id
    }
    target_ids = {
        relation.target_claim_id for relation in result.relations if relation.target_claim_id
    }
    assert source_ids == {claim.id for claim in left.claims}
    assert target_ids == {claim.id for claim in right.claims}


def test_table_diff_payload_contains_summary_and_relation_evidence() -> None:
    left = _price_table(
        table_id="payload-a",
        document_id="source-a",
        rows=[["Ocean Park", "S1", "A101", "4500000000", "01/03/2026"]],
    )
    right = _price_table(
        table_id="payload-b",
        document_id="source-b",
        rows=[["Ocean Park", "S1", "A101", "4500000000", "01/03/2026"]],
    )

    payload = diff_table_analyses(left, right).to_payload()
    summary = cast(dict[str, int], payload["summary_counts"])
    relations = cast(list[dict[str, object]], payload["relations"])

    assert payload["source_document_id"] == "source-a"
    assert payload["target_document_id"] == "source-b"
    assert summary[ClaimRelationType.UNCHANGED.value] == 1
    assert relations[0]["relation_type"] == "unchanged"
