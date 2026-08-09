from __future__ import annotations

from decimal import Decimal

import pytest

from app.pipeline.documents.domain.parsed import ParsedTable
from app.structured_facts.application.table_analyzer import (
    analyze_table,
    normalize_area,
    normalize_header,
    normalize_money,
)


@pytest.mark.parametrize(
    ("header", "expected"),
    (
        ("Mã căn hộ", "unit"),
        ("Tòa/Tháp", "building"),
        ("DT thông thủy (m²)", "carpet_area"),
        ("Giá NY (tỷ đồng)", "list_price"),
        ("Giá sau chiết khấu", "discounted_price"),
        ("Đơn giá (triệu/m²)", "price_per_sqm"),
        ("Valid from", "effective_from"),
        ("Maintenance fee", "maintenance_fee_included"),
        ("Customer segment", "field_customer_segment"),
    ),
)
def test_table_header_normalization_covers_generic_and_price_aliases(
    header: str, expected: str
) -> None:
    assert normalize_header(header) == expected


@pytest.mark.parametrize(
    ("raw", "header", "expected", "basis"),
    (
        ("4,5 tỷ", "Giá bán", Decimal("4500000000"), "total_unit"),
        ("4.500.000.000 đ", "Tổng giá", Decimal("4500000000"), "total_unit"),
        ("64,285 triệu/m²", "Đơn giá", Decimal("64285000"), "per_sqm"),
    ),
)
def test_table_money_normalization_is_decimal_and_basis_aware(
    raw: str,
    header: str,
    expected: Decimal,
    basis: str,
) -> None:
    value, confidence = normalize_money(raw, header=header)

    assert Decimal(str(value.value)) == expected
    assert value.currency == "VND"
    assert value.basis == basis
    assert value.raw_value == raw
    assert confidence >= 0.9


def test_table_area_normalization_preserves_raw_value() -> None:
    value, confidence = normalize_area("70,25 m²", header="DT thông thủy")

    assert Decimal(str(value.value)) == Decimal("70.25")
    assert value.unit == "m2"
    assert value.basis == "carpet"
    assert value.raw_value == "70,25 m²"
    assert confidence == 1.0


def test_table_money_magnitude_uses_tokens_not_property_suffixes() -> None:
    value, confidence = normalize_money("500000", header="Property price")

    assert Decimal(str(value.value)) == Decimal("500000")
    assert confidence == 1.0


def test_table_analysis_builds_business_identity_and_exact_cell_provenance() -> None:
    header = [
        "Dự án",
        "Tòa",
        "Mã căn",
        "DT thông thủy (m²)",
        "Giá NY (tỷ đồng)",
        "Ngày hiệu lực",
    ]
    table = ParsedTable(
        table_id="price-table-1",
        location="sheet:Bang gia:page:3:table:1",
        rows=[header, ["Ocean Park", "S1", "A101", "70", "4,5", "01/03/2026"]],
        columns=len(header),
        header=header,
        confidence=0.96,
        metadata={
            "owner_id": "owner-1",
            "notebook_id": "notebook-1",
            "source_type": "official_price_list",
            "publisher": "Developer A",
            "approval_status": "approved",
            "officiality": True,
            "authority_level": 90,
            "authority_metadata": {"signed": True, "channel": "portal"},
        },
        cells=[
            {
                "cell_id": f"cell-1-{column_index}",
                "row_index": 1,
                "column_index": column_index,
                "confidence": 0.94,
                "page_number": 3,
            }
            for column_index in range(len(header))
        ],
    )

    analysis = analyze_table(document_id="document-1", table=table)

    assert analysis.row_count == 1
    assert analysis.normalized_schema == (
        "project",
        "building",
        "unit",
        "carpet_area",
        "list_price",
        "effective_date",
    )
    assert len(analysis.claims) == 2
    assert all(
        claim.subject_key == "project=ocean park|building=s1|unit=a101" for claim in analysis.claims
    )
    price = next(claim for claim in analysis.claims if claim.predicate == "sale_price")
    assert Decimal(str(price.value.value)) == Decimal("4500000000")
    assert price.provenance.table_id == "price-table-1"
    assert price.provenance.row_index == 1
    assert price.provenance.data_row_ordinal == 0
    assert price.provenance.column_name == "Giá NY (tỷ đồng)"
    assert price.provenance.cell_id == "cell-1-4"
    assert price.provenance.page_number == 3
    assert price.owner_id == "owner-1"
    assert price.notebook_id == "notebook-1"
    assert price.authority.publisher == "Developer A"
    assert price.authority.authority_level == 90
    assert price.authority.to_payload()["metadata"] == {"channel": "portal", "signed": True}
    assert price.temporal.effective_from is not None
    assert price.temporal.effective_to == price.temporal.effective_from


def test_table_analysis_marks_positional_identity_as_low_confidence() -> None:
    header = ["Giá bán"]
    table = ParsedTable(
        table_id="identity-missing",
        location="sheet:1",
        rows=[header, ["4,5 tỷ"]],
        columns=1,
        header=header,
    )

    analysis = analyze_table(document_id="document-1", table=table)

    assert len(analysis.claims) == 1
    assert analysis.claims[0].subject_key.startswith("unresolved:")
    assert analysis.claims[0].extraction_confidence < 0.7
    assert "fallback_row_identity:1" in analysis.warnings


def test_table_analysis_uses_row_currency_and_rejects_invalid_time() -> None:
    header = ["Mã căn", "Giá bán", "Tiền tệ", "Hiệu lực từ", "Hiệu lực đến"]
    table = ParsedTable(
        table_id="invalid-time",
        location="sheet:1",
        rows=[header, ["A101", "500000", "USD", "01/03/2026", "invalid"]],
        columns=len(header),
        header=header,
    )

    analysis = analyze_table(document_id="document-1", table=table)

    claim = analysis.claims[0]
    assert claim.value.currency == "USD"
    assert claim.temporal.has_effective_interval is False
    assert claim.extraction_confidence == 0.4
    assert "invalid_effective_interval:1" in analysis.warnings


def test_table_analysis_building_scope_uses_composite_product_identity() -> None:
    header = ["Dự án", "Tòa", "Loại căn", "Số phòng ngủ", "Giá bán"]
    table = ParsedTable(
        table_id="building-products",
        location="sheet:1",
        rows=[
            header,
            ["Ocean Park", "S1", "Apartment", "2", "4500000000"],
            ["Ocean Park", "S1", "Apartment", "3", "5500000000"],
        ],
        columns=len(header),
        header=header,
    )

    analysis = analyze_table(document_id="document-1", table=table)

    assert len({claim.subject_key for claim in analysis.claims}) == 2
    assert all("building=s1" in claim.subject_key for claim in analysis.claims)
    assert all("bedrooms=" in claim.subject_key for claim in analysis.claims)


def test_table_analysis_does_not_sample_large_tables() -> None:
    header = ["Dự án", "Tòa", "Mã căn", "Giá NY (tỷ đồng)"]
    rows = [
        ["Ocean Park", "S1", f"A{index:04d}", f"{4 + index / 1000:.3f} tỷ"]
        for index in range(1_000)
    ]
    table = ParsedTable(
        table_id="large-price-table",
        location="sheet:1",
        rows=[header, *rows],
        columns=len(header),
        header=header,
    )

    analysis = analyze_table(document_id="document-1", table=table)

    assert analysis.row_count == 1_000
    assert len(analysis.claims) == 1_000
    assert analysis.claims[-1].provenance.data_row_ordinal == 999
