"""Regression coverage for legal-template false conflict detection."""

import pytest

from app.knowledge_quality.application.analysis import analyze_text_relation
from app.knowledge_quality.application.claims import (
    classify_numeric_mentions,
    extract_claims,
    normalize_claim_comparison_text,
)
from app.knowledge_quality.application.scope import compare_claim_scopes, extract_claim_scope
from app.knowledge_quality.domain.models import (
    ClaimScope,
    NumericRole,
    RelationType,
    ScopeComparison,
)


@pytest.mark.parametrize(
    ("left", "right"),
    (
        (
            "Điều 5.2 quy định nghĩa vụ thanh toán.",
            "Điều 9.2 quy định nghĩa vụ thanh toán.",
        ),
        (
            "Xem Điều 9 và Phụ lục 2.",
            "Xem Điều 10 và Phụ lục 4.",
        ),
        (
            "Trang 47 trên 51.",
            "Trang 43 trên 47.",
        ),
        ("Mục 4.1.", "Mục 7.3."),
    ),
)
def test_structural_reference_changes_are_not_conflicts(left: str, right: str) -> None:
    analysis = analyze_text_relation(left, right)

    assert analysis.relation_type != RelationType.CONFLICT_CANDIDATE
    assert "number_mismatch" not in analysis.reason_codes


def test_different_projects_with_different_values_are_not_conflicts() -> None:
    analysis = analyze_text_relation(
        "Dự án Tây Mỗ có thời hạn thanh toán 30 ngày.",
        "Dự án Hải Vân có thời hạn thanh toán 45 ngày.",
    )

    assert analysis.relation_type != RelationType.CONFLICT_CANDIDATE
    assert "different_claim_scope" in analysis.reason_codes


def test_same_claim_quantity_change_remains_a_conflict() -> None:
    analysis = analyze_text_relation(
        "Bên mua phải thanh toán trong 30 ngày.",
        "Bên mua phải thanh toán trong 45 ngày.",
    )

    assert analysis.relation_type == RelationType.CONFLICT_CANDIDATE


def test_same_scope_quantity_conflict_is_validated() -> None:
    scope = ClaimScope(project_id="project-a", contract_id="contract-1")

    analysis = analyze_text_relation(
        "Bên mua phải thanh toán trong 30 ngày.",
        "Bên mua phải thanh toán trong 45 ngày.",
        left_scope=scope,
        right_scope=scope,
    )

    assert analysis.relation_type == RelationType.CONFLICT_CANDIDATE
    assert analysis.scope_comparison is ScopeComparison.SAME_SCOPE
    assert analysis.validated_conflict_count == 1
    assert "semantic_quantity_mismatch" in analysis.reason_codes
    assert "validated_same_scope_conflict" in analysis.reason_codes


def test_different_explicit_scopes_become_template_variant() -> None:
    analysis = analyze_text_relation(
        "Bên mua phải thanh toán trong 30 ngày.",
        "Bên mua phải thanh toán trong 45 ngày.",
        left_scope=ClaimScope(project_id="project-a"),
        right_scope=ClaimScope(project_id="project-b"),
    )

    assert analysis.relation_type == RelationType.TEMPLATE_VARIANT
    assert analysis.validated_conflict_count == 0
    assert analysis.scope_comparison is ScopeComparison.DIFFERENT_SCOPE
    assert "different_project_entity" in analysis.reason_codes
    assert "shared_legal_template" in analysis.reason_codes


def test_scope_comparison_does_not_treat_upload_ids_as_logical_scope() -> None:
    assert (
        compare_claim_scopes(
            ClaimScope(document_id="upload-a"),
            ClaimScope(document_id="upload-b"),
        )
        is ScopeComparison.UNKNOWN_SCOPE
    )


def test_document_type_is_not_business_scope_evidence() -> None:
    assert (
        compare_claim_scopes(
            ClaimScope(document_type="price_list"),
            ClaimScope(document_type="policy"),
        )
        is ScopeComparison.UNKNOWN_SCOPE
    )
    assert (
        compare_claim_scopes(
            ClaimScope(project_id="ocean-park", document_type="price_list"),
            ClaimScope(project_id="ocean-park", document_type="policy"),
        )
        is ScopeComparison.SAME_SCOPE
    )
    assert (
        compare_claim_scopes(
            ClaimScope(project_id="project-a"),
            ClaimScope(project_id="project-b"),
        )
        is ScopeComparison.DIFFERENT_SCOPE
    )


def test_scope_extraction_ignores_unlabelled_financial_numbers() -> None:
    scope = extract_claim_scope("Tài khoản thanh toán số: 4200456848. Số hợp đồng: HD-2026-001.")

    assert scope.contract_id == "hd 2026 001"
    assert scope.reference_year is None


def test_scope_extraction_does_not_promote_account_number_to_contract_id() -> None:
    scope = extract_claim_scope("Tài khoản thanh toán số: 4200456848.")

    assert scope.contract_id is None


def test_scope_extraction_abstains_for_generic_filename_and_incidental_contract_text() -> None:
    scope = extract_claim_scope(
        """
        VINHOMES - CHUYÊN ĐỀ GIÁ NHÀ
        Giá nhà Vinhomes 2025
        Năm 2025 đánh dấu chu kỳ ra mắt dự án mới gồm Wonder City, Golden City.
        Chỉ hợp đồng mua bán và xác nhận chính thức có giá trị cam kết.
        """,
        filename="Vinhomes_Gia_Nha_2025.docx",
    )

    assert scope.project_id is None
    assert scope.document_type is None
    assert scope.contract_type is None
    assert scope.subject_entities == ()


def test_scope_extraction_does_not_turn_policy_filename_into_project() -> None:
    scope = extract_claim_scope(
        "CHÍNH SÁCH ĐỔI TRẢ HÀNG - BỘ PHẬN CSKH",
        filename="demo_kb_chinh_sach_doi_tra_cskh.docx",
    )

    assert scope.project_id is None
    assert scope.document_type is None
    assert scope.subject_entities == ()


def test_scope_extraction_does_not_turn_open_sale_phrase_into_project() -> None:
    scope = extract_claim_scope(
        "Danh sách dự án mở bán tại Hà Nội trong năm 2024.",
        filename="Vinhomes_Gia_Nha_2024.docx",
    )

    assert scope.project_id is None
    assert scope.subject_entities == ()


def test_scope_extraction_keeps_explicit_project_and_contract_title() -> None:
    project_scope = extract_claim_scope("Dự án Tây Mỗ có thời hạn thanh toán 30 ngày.")
    labelled_scope = extract_claim_scope("Dự án: ocean park")
    contract_scope = extract_claim_scope("HỢP ĐỒNG MUA BÁN NHÀ Ở\nSố: HD-2026-001")

    assert project_scope.project_id == "tay mo"
    assert labelled_scope.project_id == "ocean park"
    assert contract_scope.document_type == "housing_sale_contract"
    assert contract_scope.contract_type == "housing_sale_contract"


def test_numeric_roles_keep_semantic_values_and_drop_structure() -> None:
    text = "Điều 5.2 yêu cầu thanh toán 10% trong 30 ngày; xem Phụ lục 2."

    mentions = classify_numeric_mentions(text)

    structural_types = {
        mention.reference_type
        for mention in mentions
        if mention.role is NumericRole.STRUCTURAL_REFERENCE
    }
    assert structural_types == {
        "article_number",
        "appendix_number",
    }
    semantic = [mention for mention in mentions if mention.role is NumericRole.SEMANTIC_QUANTITY]
    assert [(mention.normalized_value, mention.unit) for mention in semantic] == [
        ("10", "percent"),
        ("30", "day"),
    ]
    assert normalize_claim_comparison_text(text).startswith("yêu cầu thanh toán 10% trong 30 ngày")


def test_account_context_does_not_hide_semantic_storage_quantity() -> None:
    mentions = classify_numeric_mentions(
        "Gói cơ bản cung cấp cho mỗi tài khoản 500 MB dung lượng lưu trữ."
    )

    assert [
        (mention.normalized_value, mention.unit)
        for mention in mentions
        if mention.role is NumericRole.SEMANTIC_QUANTITY
    ] == [("500", "byte")]


@pytest.mark.parametrize(
    ("left", "right", "reason"),
    (
        (
            "Bên mua được phép chuyển nhượng.",
            "Bên mua không được phép chuyển nhượng.",
            "negation_mismatch",
        ),
        (
            "Bên mua có thể cung cấp tài liệu.",
            "Bên mua phải cung cấp tài liệu.",
            "policy_modality_mismatch",
        ),
        ("Giới hạn là 10 MB.", "Giới hạn là 10 GB.", "semantic_quantity_mismatch"),
        ("Diện tích là 100 m².", "Diện tích là 120 m².", "semantic_quantity_mismatch"),
    ),
)
def test_same_scope_critical_differences_remain_conflicts(
    left: str,
    right: str,
    reason: str,
) -> None:
    scope = ClaimScope(project_id="project-a")

    analysis = analyze_text_relation(
        left,
        right,
        left_scope=scope,
        right_scope=scope,
    )

    assert analysis.relation_type == RelationType.CONFLICT_CANDIDATE
    assert reason in analysis.reason_codes


def test_different_scope_blocks_negation_and_modality_conflicts() -> None:
    left_scope = ClaimScope(project_id="project-a")
    right_scope = ClaimScope(project_id="project-b")
    pairs = (
        ("Bên mua được phép chuyển nhượng.", "Bên mua không được phép chuyển nhượng."),
        ("Bên mua có thể cung cấp tài liệu.", "Bên mua phải cung cấp tài liệu."),
    )

    for left, right in pairs:
        analysis = analyze_text_relation(
            left,
            right,
            left_scope=left_scope,
            right_scope=right_scope,
        )
        assert analysis.relation_type != RelationType.CONFLICT_CANDIDATE
        assert analysis.validated_conflict_count == 0


def test_legal_relation_classification_is_symmetric() -> None:
    left = "Dự án Tây Mỗ áp dụng cho Khu TM tại Điều 5.2."
    right = "Dự án Hải Vân áp dụng cho Khu Nhà Ở tại Điều 9.2."

    analysis_ab = analyze_text_relation(left, right)
    analysis_ba = analyze_text_relation(right, left)

    assert analysis_ab.relation_type == analysis_ba.relation_type
    assert set(analysis_ab.reason_codes) == set(analysis_ba.reason_codes)
    assert analysis_ab.confidence == pytest.approx(analysis_ba.confidence, abs=1e-6)


def test_temporal_scope_extraction_and_metadata_round_trip() -> None:
    scope = extract_claim_scope(
        "Dự án: Vinhomes Ocean Park\nBảng giá áp dụng quý 1/2024.",
        filename="Bang_gia_Vinhomes_2024.docx",
    )

    assert scope.project_id == "vinhomes ocean park"
    assert scope.reference_year == "2024"
    assert scope.reference_quarter == "Q1"
    assert scope.reference_period_label == "quarter:2024-Q1"
    assert ClaimScope.from_metadata(scope.to_metadata()) == scope


def test_bare_title_year_and_filename_year_are_temporal_fallbacks() -> None:
    title_scope = extract_claim_scope("GIÁ NHÀ VINHOMES 2025\nBáo cáo thị trường.")
    filename_scope = extract_claim_scope(
        "Bảng giá tham khảo.",
        filename="Vinhomes_Gia_Nha_2026.docx",
    )

    assert title_scope.reference_year == "2025"
    assert filename_scope.reference_year == "2026"


def test_bare_financial_quantity_is_not_promoted_to_reference_year() -> None:
    scope = extract_claim_scope("Revenue was 2024 USD.")

    assert scope.reference_year is None


def test_compare_scopes_distinguishes_entity_and_temporal_divergence() -> None:
    assert (
        compare_claim_scopes(
            ClaimScope(project_id="ocean-park", reference_year="2024"),
            ClaimScope(project_id="ocean-park", reference_year="2026"),
        )
        is ScopeComparison.TEMPORAL_DIVERGENCE
    )
    assert (
        compare_claim_scopes(
            ClaimScope(project_id="project-a", reference_year="2024"),
            ClaimScope(project_id="project-b", reference_year="2026"),
        )
        is ScopeComparison.DIFFERENT_SCOPE
    )


def test_temporal_claim_qualifiers_prevent_cross_period_alignment() -> None:
    left_claim = extract_claims("Giá bán năm 2024 là 5 tỷ đồng.")[0]
    right_claim = extract_claims("Giá bán năm 2026 là 8 tỷ đồng.")[0]

    assert left_claim.claim_key is not None
    assert right_claim.claim_key is not None
    assert left_claim.claim_key.scope_qualifiers == ("year:2024",)
    assert right_claim.claim_key.scope_qualifiers == ("year:2026",)


def test_different_year_values_are_temporal_series_not_conflict() -> None:
    analysis = analyze_text_relation(
        "Dự án: Vinhomes Ocean Park\nGiá bán năm 2024 là 5 tỷ đồng.",
        "Dự án: Vinhomes Ocean Park\nGiá bán năm 2026 là 8 tỷ đồng.",
    )

    assert analysis.relation_type is RelationType.TEMPORAL_SERIES
    assert analysis.scope_comparison is ScopeComparison.TEMPORAL_DIVERGENCE
    assert analysis.validated_conflict_count == 0
    assert analysis.confidence < 0.5
    assert "temporal_period_difference" in analysis.reason_codes
    assert "historical_series_not_conflict" in analysis.reason_codes


def test_inline_title_year_before_value_is_temporal_series() -> None:
    analysis = analyze_text_relation(
        "Giá Vinhomes 2024 là 5 tỷ đồng.",
        "Giá Vinhomes 2026 là 8 tỷ đồng.",
    )

    assert analysis.relation_type is RelationType.TEMPORAL_SERIES
    assert analysis.scope_comparison is ScopeComparison.TEMPORAL_DIVERGENCE


def test_different_quarters_are_temporal_series_not_conflict() -> None:
    analysis = analyze_text_relation(
        "Dự án: Vinhomes Ocean Park\nGiá bán quý 1/2024 là 5 tỷ đồng.",
        "Dự án: Vinhomes Ocean Park\nGiá bán quý 2/2024 là 8 tỷ đồng.",
    )

    assert analysis.relation_type is RelationType.TEMPORAL_SERIES
    assert "different_reference_quarter" in analysis.reason_codes


def test_same_year_quantity_difference_remains_conflict() -> None:
    analysis = analyze_text_relation(
        "Dự án: Vinhomes Ocean Park\nGiá bán năm 2024 là 5 tỷ đồng.",
        "Dự án: Vinhomes Ocean Park\nGiá bán năm 2024 là 8 tỷ đồng.",
    )

    assert analysis.relation_type is RelationType.CONFLICT_CANDIDATE
    assert analysis.scope_comparison is ScopeComparison.SAME_SCOPE
    assert analysis.validated_conflict_count == 1


def test_large_effective_date_gap_is_version_candidate() -> None:
    analysis = analyze_text_relation(
        "Giá bán là 5 tỷ đồng.",
        "Giá bán là 8 tỷ đồng.",
        left_scope=ClaimScope(project_id="ocean-park", effective_date="2024-01-01"),
        right_scope=ClaimScope(project_id="ocean-park", effective_date="2026-01-01"),
    )

    assert analysis.relation_type is RelationType.VERSION_CANDIDATE
    assert analysis.scope_comparison is ScopeComparison.TEMPORAL_DIVERGENCE
    assert analysis.validated_conflict_count == 0
    assert "effective_period_version_difference" in analysis.reason_codes
