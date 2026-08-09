"""Tests for conservative document identity and relation analysis."""

from app.knowledge_quality.application.analysis import (
    analyze_text_relation,
    build_document_fingerprint,
    detect_conflicts,
    is_auto_identity_eligible,
    strict_normalize_text,
)
from app.knowledge_quality.application.claims import extract_claims
from app.knowledge_quality.domain.models import PolicyModality, RelationType


def test_strict_identity_normalizes_representation_but_preserves_meaning() -> None:
    left = "  Revenue\u00a0increased\u200b in 2026.\n\nCosts stayed controlled. "
    right = "Revenue increased in 2026. Costs stayed controlled."

    assert strict_normalize_text(left) == right
    assert build_document_fingerprint(left).strict_hash == (
        build_document_fingerprint(right).strict_hash
    )
    assert analyze_text_relation(left, right).relation_type == RelationType.EXACT_CONTENT


def test_tiny_or_empty_extraction_is_never_eligible_for_automatic_merge() -> None:
    assert not is_auto_identity_eligible(build_document_fingerprint(""))
    assert not is_auto_identity_eligible(build_document_fingerprint("Terms apply."))
    assert is_auto_identity_eligible(
        build_document_fingerprint(
            "Revenue increased in 2026 while operating costs remained fully controlled."
        )
    )


def test_high_semantic_paraphrase_becomes_reviewable_near_duplicate() -> None:
    analysis = analyze_text_relation(
        "Annual leave is 12 days for each employee.",
        "Each employee receives 12 days of annual paid leave.",
        semantic_similarity=0.94,
    )

    assert analysis.relation_type == RelationType.NEAR_DUPLICATE
    assert analysis.confidence >= 0.80
    assert analysis.number_agreement is True


def test_content_extension_is_a_version_candidate() -> None:
    analysis = analyze_text_relation(
        "The system supports email and password login.",
        (
            "The system supports email and password login. "
            "Administrators can enable two factor authentication."
        ),
    )

    assert analysis.relation_type == RelationType.VERSION_CANDIDATE
    assert analysis.containment == 1.0


def test_number_and_negation_changes_are_conflict_candidates() -> None:
    number_change = analyze_text_relation(
        "Revenue in Q3 was 120 million.",
        "Revenue in Q3 was 121 million.",
    )
    negation_change = analyze_text_relation(
        "Employees may work remotely on Friday.",
        "Employees may not work remotely on Friday.",
    )

    assert number_change.relation_type == RelationType.CONFLICT_CANDIDATE
    assert number_change.reason_codes[0] == "semantic_quantity_mismatch"
    assert negation_change.relation_type == RelationType.CONFLICT_CANDIDATE
    assert negation_change.reason_codes[0] == "negation_mismatch"


def test_conflict_detector_reports_source_indexes_without_reconciling() -> None:
    conflicts = detect_conflicts(
        (
            "Revenue in Q3 was 120 million.",
            "The warranty lasts 24 months.",
            "Revenue in Q3 was 121 million.",
        )
    )

    assert len(conflicts) == 1
    assert (conflicts[0].left_index, conflicts[0].right_index) == (0, 2)
    assert "semantic_quantity_mismatch" in conflicts[0].analysis.reason_codes


def test_magnitude_conflict_has_normalized_values_units_and_source_spans() -> None:
    left = "Revenue was 120 million USD."
    right = "Revenue was 120 billion USD."

    analysis = analyze_text_relation(left, right)

    assert analysis.relation_type == RelationType.CONFLICT_CANDIDATE
    assert analysis.reason_codes[:2] == (
        "semantic_quantity_mismatch",
        "unit_value_mismatch",
    )
    assert analysis.number_agreement is False
    assert analysis.unit_agreement is False
    assert len(analysis.claim_conflicts) == 1
    conflict = analysis.claim_conflicts[0]
    assert conflict.reason_codes == (
        "semantic_quantity_mismatch",
        "unit_value_mismatch",
    )
    left_value = conflict.left_claim.values[0]
    right_value = conflict.right_claim.values[0]
    assert left_value.normalized_value == "120000000"
    assert right_value.normalized_value == "120000000000"
    assert left_value.unit == right_value.unit == "usd"
    assert left[left_value.span_start : left_value.span_end] == left_value.raw_text
    assert right[right_value.span_start : right_value.span_end] == right_value.raw_text


def test_grouped_and_plain_integer_notation_are_equivalent() -> None:
    analysis = analyze_text_relation(
        "The budget is 1,000 VND.",
        "The budget is 1000 VND.",
        semantic_similarity=0.95,
    )

    assert analysis.relation_type == RelationType.NEAR_DUPLICATE
    assert analysis.number_agreement is True
    assert analysis.unit_agreement is True
    assert analysis.claim_conflicts == ()


def test_claim_alignment_detects_values_swapped_between_different_claims() -> None:
    analysis = analyze_text_relation(
        "Policy A allows 10 days and Policy B allows 20 days.",
        "Policy A allows 20 days and Policy B allows 10 days.",
    )

    assert analysis.relation_type == RelationType.CONFLICT_CANDIDATE
    assert analysis.reason_codes[0] == "semantic_quantity_mismatch"
    assert len(analysis.claim_conflicts) == 2
    assert [conflict.left_claim.alignment_key for conflict in analysis.claim_conflicts] == [
        "policy a allows",
        "policy b allows",
    ]
    assert all(
        conflict.reason_codes == ("semantic_quantity_mismatch",)
        for conflict in analysis.claim_conflicts
    )


def test_negation_is_compared_within_each_aligned_claim() -> None:
    analysis = analyze_text_relation(
        "Employees may not work Friday and may work Monday.",
        "Employees may work Friday and may not work Monday.",
    )

    assert analysis.relation_type == RelationType.CONFLICT_CANDIDATE
    assert analysis.reason_codes[0] == "negation_mismatch"
    assert analysis.negation_mismatch is True
    assert len(analysis.claim_conflicts) == 2
    assert all(
        "negation_mismatch" in conflict.reason_codes for conflict in analysis.claim_conflicts
    )


def test_policy_modality_distinguishes_force_and_prohibition() -> None:
    must_vs_may = analyze_text_relation(
        "Employees must submit reports.",
        "Employees may submit reports.",
    )
    permitted_vs_prohibited = analyze_text_relation(
        "Employees are permitted to enter.",
        "Employees are prohibited from entering.",
    )
    vietnamese = analyze_text_relation(
        "Nhân viên phải nộp báo cáo.",
        "Nhân viên có thể nộp báo cáo.",
    )
    vietnamese_prohibition = analyze_text_relation(
        "Nhân viên được phép vào kho.",
        "Nhân viên bị cấm vào kho.",
    )

    for analysis in (
        must_vs_may,
        permitted_vs_prohibited,
        vietnamese,
        vietnamese_prohibition,
    ):
        assert analysis.relation_type == RelationType.CONFLICT_CANDIDATE
        assert analysis.reason_codes[0] == "policy_modality_mismatch"
        assert analysis.policy_modality_mismatch is True


def test_equivalent_policy_modality_phrases_do_not_create_conflicts() -> None:
    equivalent_pairs = (
        (
            "Employees must submit reports.",
            "Employees are required to submit reports.",
        ),
        (
            "Employees may enter the archive.",
            "Employees are permitted to enter the archive.",
        ),
        (
            "Nhân viên không được vào kho.",
            "Nhân viên bị cấm vào kho.",
        ),
        (
            "Nhân viên bắt buộc nộp báo cáo.",
            "Nhân viên phải nộp báo cáo.",
        ),
        (
            "Nhân viên có thể vào kho.",
            "Nhân viên được phép vào kho.",
        ),
    )

    for left, right in equivalent_pairs:
        analysis = analyze_text_relation(left, right, semantic_similarity=0.95)
        assert analysis.relation_type == RelationType.NEAR_DUPLICATE
        assert analysis.policy_modality_mismatch is False


def test_dates_are_normalized_and_date_evidence_keeps_absolute_spans() -> None:
    equivalent = analyze_text_relation(
        "Policy starts on 30/07/2026.",
        "Policy starts on July 30, 2026.",
        semantic_similarity=0.95,
    )
    changed = analyze_text_relation(
        "Chính sách áp dụng ngày 30 tháng 7 năm 2026.",
        "Chính sách áp dụng ngày 31 tháng 7 năm 2026.",
    )

    assert equivalent.relation_type == RelationType.NEAR_DUPLICATE
    assert equivalent.date_agreement is True
    assert equivalent.number_agreement is True
    assert changed.relation_type == RelationType.CONFLICT_CANDIDATE
    assert changed.reason_codes[0] == "date_value_mismatch"
    date_conflict = changed.claim_conflicts[0]
    assert date_conflict.left_claim.values[0].normalized_value == "2026-07-30"
    assert date_conflict.right_claim.values[0].normalized_value == "2026-07-31"
    for claim in (
        date_conflict.left_claim,
        date_conflict.right_claim,
    ):
        value = claim.values[0]
        source = (
            "Chính sách áp dụng ngày 30 tháng 7 năm 2026."
            if value.normalized_value == "2026-07-30"
            else "Chính sách áp dụng ngày 31 tháng 7 năm 2026."
        )
        assert source[value.span_start : value.span_end] == value.raw_text


def test_claim_extraction_normalizes_vietnamese_policy_and_quantity() -> None:
    text = "Từ ngày 30 tháng 7 năm 2026, nhân viên phải hoàn trả 120 triệu VND."

    claim = extract_claims(text)[0]

    assert claim.modality is PolicyModality.REQUIRED
    assert text[claim.span_start : claim.span_end] == claim.text
    assert [value.kind for value in claim.values] == ["date", "quantity"]
    assert [value.normalized_value for value in claim.values] == [
        "2026-07-30",
        "120000000",
    ]
    assert claim.values[1].unit == "vnd"


def test_decimal_point_does_not_split_a_quantity_claim() -> None:
    analysis = analyze_text_relation(
        "The allowance is 1.5 million USD.",
        "The allowance is 1.6 million USD.",
    )

    assert analysis.relation_type == RelationType.CONFLICT_CANDIDATE
    assert len(analysis.claim_conflicts) == 1
    left_value = analysis.claim_conflicts[0].left_claim.values[0]
    right_value = analysis.claim_conflicts[0].right_claim.values[0]
    assert left_value.normalized_value == "1500000"
    assert right_value.normalized_value == "1600000"
