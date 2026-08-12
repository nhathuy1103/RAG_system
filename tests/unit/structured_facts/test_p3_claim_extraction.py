from __future__ import annotations

from decimal import Decimal

from app.structured_facts.application.claim_extraction import extract_structured_claims
from app.structured_facts.domain.models import ValueOperator


def test_extracts_entity_aware_vehicle_range_not_generic_verb() -> None:
    result = extract_structured_claims(
        "VF 8 Eco đời 2025 tại Việt Nam có tầm hoạt động 450 km theo WLTP.",
        document_id="doc-vf8",
    )

    assert len(result.claims) == 1
    claim = result.claims[0]
    assert claim.subject_key == "vinfast_vf8"
    assert claim.predicate == "driving_range"
    assert claim.value_expression.value == Decimal("450")
    assert claim.value_expression.unit == "km"
    assert claim.provenance.source_span is not None


def test_one_sentence_can_emit_multiple_claims_with_late_subject() -> None:
    text = (
        "Giá căn 2PN là 6,2 tỷ đồng/căn; diện tích 70 m²; "
        "phí quản lý 20.000 đồng/m²/tháng tại Vinhomes Project Alpha năm 2026."
    )
    result = extract_structured_claims(text, document_id="doc-many")

    assert [claim.predicate for claim in result.claims] == [
        "property_price",
        "property_area",
        "management_fee",
    ]
    assert {claim.subject_key for claim in result.claims} == {"vinhomes_project_alpha"}
    assert {claim.temporal.reference_period for claim in result.claims} == {"2026"}


def test_multi_period_lines_emit_independent_temporal_claims() -> None:
    text = "Vinhomes Project Alpha – studio:\n2024: 5 tỷ/căn\n2025: 6 tỷ/căn\n2026: 7 tỷ/căn"
    claims = extract_structured_claims(text, document_id="doc-periods").claims

    assert len(claims) == 3
    assert [claim.temporal.reference_period for claim in claims] == ["2024", "2025", "2026"]
    assert [claim.value_expression.value for claim in claims] == [
        Decimal("5000000000"),
        Decimal("6000000000"),
        Decimal("7000000000"),
    ]


def test_negation_and_context_inheritance_are_source_grounded() -> None:
    negative = extract_structured_claims(
        "Đối với bản Base, xe này không được trang bị tính năng hỗ trợ giữ làn.",
        document_id="doc-feature",
        contexts=("Tiêu đề cha: VinFast VF 6 đời 2024",),
    ).claims

    assert len(negative) == 1
    assert negative[0].subject_key == "vinfast_vf6"
    assert negative[0].predicate == "feature_availability"
    assert negative[0].value_expression.operator is ValueOperator.BOOLEAN
    assert negative[0].value_expression.value is False


def test_structural_identifiers_are_not_extracted_as_values() -> None:
    claim = extract_structured_claims(
        "Căn 1208 tại tòa S8, Vinhomes Project Delta có giá 7,9 tỷ đồng/căn.",
        document_id="doc-identifiers",
    ).claims[0]

    assert claim.value_expression.value == Decimal("7900000000")
    assert claim.value_expression.value not in {Decimal("1208"), Decimal("8")}


def test_claim_cap_fails_closed() -> None:
    text = "Vinhomes Project Alpha – studio:\n" + "\n".join(
        f"{2020 + index}: {index + 1} tỷ/căn" for index in range(10)
    )
    result = extract_structured_claims(text, document_id="doc-cap", max_claims=3)

    assert len(result.claims) == 3
    assert result.capped is True
    assert "claim_cap_reached" in result.warnings


def test_new_value_expression_round_trips_with_legacy_adapter() -> None:
    claim = extract_structured_claims(
        "Giá căn studio tại Vinhomes Project Alpha năm 2026 khoảng 6,2 tỷ đồng/căn.",
        document_id="doc-roundtrip",
    ).claims[0]

    restored = type(claim).from_payload(claim.to_payload())

    assert restored.value_expression == claim.value_expression
    assert restored.claim_identity_hash == claim.claim_identity_hash


def test_service_package_is_an_enum_not_an_identifier_number() -> None:
    claim = extract_structured_claims(
        "VF 8 Eco đời 2025 tại Việt Nam có gói hỗ trợ dịch vụ 3.",
        document_id="doc-service-package",
    ).claims[0]

    assert claim.predicate == "service_feature"
    assert claim.value_expression.operator is ValueOperator.ENUM
    assert claim.value_expression.value == "package-3"
