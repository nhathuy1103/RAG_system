from __future__ import annotations

from app.pipeline.documents.domain.parsed import ParsedTable
from app.structured_facts.application.claim_alignment import align_claims
from app.structured_facts.application.claim_extraction import (
    canonicalize_table_claims,
    extract_structured_claims,
)
from app.structured_facts.application.table_analyzer import analyze_table
from app.structured_facts.domain.models import ClaimRelationType


def _table_claims(headers: list[str], row: list[str], table_id: str):  # type: ignore[no-untyped-def]
    table = ParsedTable(
        table_id=table_id,
        location=f"sheet:{table_id}",
        rows=[headers, row],
        columns=len(headers),
        header=headers,
    )
    return canonicalize_table_claims(analyze_table(document_id=f"doc-{table_id}", table=table))


def test_vinhomes_table_and_prose_share_claim_identity() -> None:
    table = _table_claims(
        ["Dự án", "Loại căn", "Ngày hiệu lực", "Giá bán"],
        ["Vinhomes Project Alpha", "2PN", "2023-01-01", "8,2 tỷ VND"],
        "vh",
    )
    prose = extract_structured_claims(
        "Giá căn 2PN tại Vinhomes Project Alpha năm 2023 là 8200 triệu VND/căn.",
        document_id="doc-vh-prose",
    ).claims

    relation = align_claims(table, prose).relations[0]
    assert table[0].predicate == prose[0].predicate == "property_price"
    assert relation.relation_type is ClaimRelationType.UNCHANGED


def test_vinfast_table_and_prose_share_claim_identity() -> None:
    table = _table_claims(
        ["Mẫu xe", "Phiên bản", "Model year", "Thị trường", "Chu trình", "Tầm hoạt động"],
        ["VF 8", "Eco", "2025", "Việt Nam", "WLTP", "450 km"],
        "vf",
    )
    prose = extract_structured_claims(
        "VF 8 Eco đời 2025 tại Việt Nam có tầm hoạt động 450000 m theo WLTP.",
        document_id="doc-vf-prose",
    ).claims

    relation = align_claims(table, prose).relations[0]
    assert table[0].predicate == prose[0].predicate == "driving_range"
    assert relation.relation_type is ClaimRelationType.UNCHANGED


def test_prose_to_table_uses_the_same_format_independent_identity() -> None:
    table = _table_claims(
        ["Mẫu xe", "Phiên bản", "Model year", "Thị trường", "Chu trình", "Tầm hoạt động"],
        ["VF 8", "Eco", "2025", "Việt Nam", "WLTP", "450 km"],
        "vf-reverse",
    )
    prose = extract_structured_claims(
        "VF 8 Eco đời 2025 tại Việt Nam có phạm vi hoạt động 450000 m theo WLTP.",
        document_id="doc-vf-reverse-prose",
    ).claims

    forward = align_claims(table, prose).relations[0]
    reverse = align_claims(prose, table).relations[0]
    assert forward.relation_type is ClaimRelationType.UNCHANGED
    assert reverse.relation_type is ClaimRelationType.UNCHANGED
    assert table[0].candidate_identity_hash == prose[0].candidate_identity_hash
