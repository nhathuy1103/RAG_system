"""Deterministically generate the frozen synthetic Vinhomes/VinFast gold dataset."""

from __future__ import annotations

import hashlib
import json
import unicodedata
from collections.abc import Callable, Mapping
from pathlib import Path
from typing import Literal

from evaluation.duplicate_conflict.constants import (
    DATASET_DIR,
    DEV_DATASET_PATH,
    FULL_DATASET_PATH,
    SCHEMA_VERSION,
    SMOKE_DATASET_PATH,
    SPLIT_SEED,
    STRESS_CASES_PATH,
    TEST_DATASET_PATH,
    TEST_PERCENT,
)
from evaluation.duplicate_conflict.models import (
    Difficulty,
    Domain,
    ExpectedClaimRelation,
    ExtractionReliability,
    FailureCategory,
    GoldPair,
    GoldRelation,
    NoiseLevel,
    SourceForm,
    TablePayload,
)

LABEL_COUNTS_PER_DOMAIN: dict[GoldRelation, int] = {
    GoldRelation.EXACT_DUPLICATE: 30,
    GoldRelation.NEAR_DUPLICATE: 45,
    GoldRelation.VERSION_UPDATE: 36,
    GoldRelation.TEMPORAL_VARIANT: 36,
    GoldRelation.CONDITIONAL_VARIANT: 36,
    GoldRelation.TEMPLATE_VARIANT: 21,
    GoldRelation.CONFLICT: 54,
    GoldRelation.DISTINCT: 27,
    GoldRelation.UNCERTAIN: 15,
}

VINHOMES_SOURCES = (
    "01_Tong_quan_thuong_hieu_Vinhomes.docx",
    "01_Vinhomes_Ocean_Park_1.docx",
    "02_Mo_hinh_dai_do_thi_all_in_one.docx",
    "02_Vinhomes_Ocean_Park_2.docx",
)
VINFAST_SOURCES = (
    "01_vinfast_tong_quan_dong_thoi_gian_2022_2026.docx",
    "02_vinfast_o_to_dien_ca_nhan_2022_2026.docx",
)


def deterministic_split(pair_id: str) -> Literal["dev", "test"]:
    """Assign a stable 70/30 development/frozen-test split."""
    digest = hashlib.sha256(f"{SPLIT_SEED}:{pair_id}".encode()).digest()
    return "test" if int.from_bytes(digest[:4], "big") % 100 < TEST_PERCENT else "dev"


def _claim(
    name: str,
    *,
    entity: str,
    value: object,
    unit: str | None,
    qualifiers: Mapping[str, object],
) -> dict[str, object]:
    return {
        "claim": name,
        "entity": entity,
        "value": value,
        "unit": unit,
        "qualifiers": dict(qualifiers),
    }


def _relation(
    claim: str,
    expected: str,
    *,
    scope: Mapping[str, object],
    conflict_field: str | None = None,
) -> ExpectedClaimRelation:
    return ExpectedClaimRelation(
        claim=claim,
        scope=dict(scope),
        expected_relation=expected,
        conflict_field=conflict_field,
    )


def _table(headers: tuple[str, ...], *rows: tuple[str, ...]) -> TablePayload:
    return TablePayload(headers=headers, rows=rows)


def _render_table(table: TablePayload) -> str:
    lines = [" | ".join(table.headers)]
    lines.extend(" | ".join(row) for row in table.rows)
    return "\n".join(lines)


def _pair(
    *,
    pair_id: str,
    domain: Domain,
    category: str,
    text_a: str,
    text_b: str,
    expected_relation: GoldRelation,
    variation_type: str,
    same_entity: bool,
    same_business_scope: bool,
    same_temporal_scope: bool,
    same_claim: bool,
    same_value: bool,
    entity_a: Mapping[str, object],
    entity_b: Mapping[str, object],
    scope_a: Mapping[str, object],
    scope_b: Mapping[str, object],
    expected_claims_a: tuple[dict[str, object], ...],
    expected_claims_b: tuple[dict[str, object], ...],
    expected_claim_relations: tuple[ExpectedClaimRelation, ...],
    conflict_fields: tuple[str, ...] = (),
    source_form_a: SourceForm = SourceForm.PROSE,
    source_form_b: SourceForm = SourceForm.PROSE,
    table_a: TablePayload | None = None,
    table_b: TablePayload | None = None,
    context_a: tuple[str, ...] = (),
    context_b: tuple[str, ...] = (),
    noise_a: NoiseLevel = NoiseLevel.NONE,
    noise_b: NoiseLevel = NoiseLevel.NONE,
    reliability_a: ExtractionReliability = ExtractionReliability.HIGH,
    reliability_b: ExtractionReliability = ExtractionReliability.HIGH,
    difficulty: Difficulty = Difficulty.MEDIUM,
    annotation_reason: str,
    diagnostic_hints: tuple[FailureCategory, ...] = (),
    source_documents: tuple[str, ...],
    candidate_retrieval_required: bool = True,
    expected_auto_reuse: bool = False,
    seed_index: int,
    distinct_justification: str | None = None,
) -> GoldPair:
    return GoldPair(
        schema_version=SCHEMA_VERSION,
        pair_id=pair_id,
        split=deterministic_split(pair_id),
        domain=domain,
        category=category,
        text_a=text_a,
        text_b=text_b,
        expected_relation=expected_relation,
        variation_type=variation_type,
        same_entity=same_entity,
        same_business_scope=same_business_scope,
        same_temporal_scope=same_temporal_scope,
        same_claim=same_claim,
        same_value=same_value,
        critical_conflict=expected_relation is GoldRelation.CONFLICT,
        entity_a=dict(entity_a),
        entity_b=dict(entity_b),
        scope_a=dict(scope_a),
        scope_b=dict(scope_b),
        expected_claims_a=expected_claims_a,
        expected_claims_b=expected_claims_b,
        expected_claim_relations=expected_claim_relations,
        conflict_fields=conflict_fields,
        source_form_a=source_form_a,
        source_form_b=source_form_b,
        table_a=table_a,
        table_b=table_b,
        context_a=context_a,
        context_b=context_b,
        ocr_noise_level_a=noise_a,
        ocr_noise_level_b=noise_b,
        extraction_reliability_a=reliability_a,
        extraction_reliability_b=reliability_b,
        difficulty=difficulty,
        is_synthetic=True,
        annotation_reason=annotation_reason,
        review_status="gold",
        diagnostic_hints=diagnostic_hints,
        source_documents=source_documents,
        candidate_retrieval_required=candidate_retrieval_required,
        expected_auto_reuse=expected_auto_reuse,
        seed_index=seed_index,
        distinct_justification=distinct_justification,
        temporal_overlap_justification=None,
    )


def _vh_context(index: int) -> tuple[str, str, str, str, int, str, str]:
    projects = (
        "Vinhomes Project Alpha",
        "Vinhomes Project Beta",
        "Vinhomes Project Gamma",
        "Vinhomes Project Delta",
        "Vinhomes Project Epsilon",
    )
    property_types = (
        "studio",
        "1PN",
        "2PN",
        "3PN",
        "shophouse",
        "biệt thự",
        "townhouse",
    )
    # Use independent facets instead of aligned modulo cycles.  This keeps the
    # corpus synthetic while preventing accidental repeated text pairs.
    project = projects[index % len(projects)]
    building = f"S{index % 7 + 1}.{(index // 3) % 9 + 1:02d}"
    unit = f"{10 + (index // 5) % 20:02d}{1 + (index * 7) % 28:02d}"
    property_type = property_types[(index // 2) % len(property_types)]
    year = 2023 + (index // 7) % 4
    value = f"{4 + index % 7},{(index * 3 + index // 7) % 10}"
    changed = f"{5 + index % 7},{(index * 7 + index // 5 + 1) % 10}"
    return project, building, unit, property_type, year, value, changed


def _vh_pair(label: GoldRelation, index: int) -> GoldPair:
    project, building, unit, property_type, year, value, changed = _vh_context(index)
    alternate_project = _vh_context(index + 1)[0]
    entity = {"project": project, "building": building, "unit": unit}
    scope = {
        "project": project,
        "building": building,
        "unit": unit,
        "property_type": property_type,
        "year": year,
    }
    pair_id = f"VH_{label.value}_{index + 1:04d}"
    price_claim = _claim(
        "price",
        entity=project,
        value=value,
        unit="billion_vnd_per_unit",
        qualifiers=scope,
    )

    if label is GoldRelation.EXACT_DUPLICATE:
        base = (
            f"Giá tham chiếu căn {property_type} mã {unit} tại dự án {project} "
            f"năm {year} là {value} tỷ đồng mỗi căn."
        )
        transformations: tuple[tuple[str, Callable[[str], str]], ...] = (
            ("same_text", lambda text: text),
            ("whitespace_change", lambda text: text.replace(" tại ", "  tại\n")),
            ("unicode_nfc_nfd", lambda text: unicodedata.normalize("NFD", text)),
            ("line_break_change", lambda text: text.replace(" năm ", "\n năm ")),
            ("nbsp_change", lambda text: text.replace(" ", "\u00a0", 1)),
            ("zero_width_change", lambda text: text.replace("tham chiếu", "tham\u200b chiếu")),
        )
        variation, transform = transformations[index % len(transformations)]
        return _pair(
            pair_id=pair_id,
            domain=Domain.VINHOMES,
            category="price",
            text_a=base,
            text_b=transform(base),
            expected_relation=label,
            variation_type=variation,
            same_entity=True,
            same_business_scope=True,
            same_temporal_scope=True,
            same_claim=True,
            same_value=True,
            entity_a=entity,
            entity_b=entity,
            scope_a=scope,
            scope_b=scope,
            expected_claims_a=(price_claim,),
            expected_claims_b=(price_claim,),
            expected_claim_relations=(_relation("price", "UNCHANGED", scope=scope),),
            noise_b=(NoiseLevel.LIGHT if index % len(transformations) >= 2 else NoiseLevel.NONE),
            difficulty=Difficulty.EASY,
            annotation_reason=(
                "Only representation-level differences allowed by strict normalization exist."
            ),
            source_documents=VINHOMES_SOURCES,
            expected_auto_reuse=True,
            seed_index=index,
        )

    if label is GoldRelation.NEAR_DUPLICATE:
        text_a = (
            f"Giá tham khảo căn {property_type} tại {project}, tòa {building}, "
            f"năm {year} là khoảng {value} tỷ đồng/căn."
        )
        text_b = (
            f"Trong kỳ {year}, một sản phẩm {property_type} ở tòa {building} thuộc {project} "
            f"được tham chiếu ở mức xấp xỉ {value} tỷ cho mỗi căn."
        )
        return _pair(
            pair_id=pair_id,
            domain=Domain.VINHOMES,
            category="price",
            text_a=text_a,
            text_b=text_b,
            expected_relation=label,
            variation_type=(
                "same_scope_price_paraphrase" if index % 3 else "word_order_paraphrase"
            ),
            same_entity=True,
            same_business_scope=True,
            same_temporal_scope=True,
            same_claim=True,
            same_value=True,
            entity_a=entity,
            entity_b=entity,
            scope_a=scope,
            scope_b=scope,
            expected_claims_a=(price_claim,),
            expected_claims_b=(price_claim,),
            expected_claim_relations=(_relation("price", "UNCHANGED", scope=scope),),
            difficulty=Difficulty.MEDIUM,
            annotation_reason=(
                "Wording changes while entity, qualifiers, period, and normalized value "
                "remain equal."
            ),
            diagnostic_hints=(FailureCategory.CLASSIFIER_THRESHOLD_ERROR,),
            source_documents=VINHOMES_SOURCES,
            seed_index=index,
        )

    if label is GoldRelation.VERSION_UPDATE:
        base = (
            f"Giá tham chiếu căn {property_type} tại {project} năm {year} là {value} tỷ đồng/căn."
        )
        added = (
            f" Phí quản lý thử nghiệm là {12 + index % 5}.000 đồng/m²/tháng; "
            "khu sinh hoạt cộng đồng dự kiến mở theo tiến độ vận hành."
        )
        extra_claim = _claim(
            "management_fee",
            entity=project,
            value=12000 + index % 5 * 1000,
            unit="vnd_per_m2_month",
            qualifiers=scope,
        )
        return _pair(
            pair_id=pair_id,
            domain=Domain.VINHOMES,
            category="version_extension",
            text_a=base,
            text_b=base + added,
            expected_relation=label,
            variation_type="added_information",
            same_entity=True,
            same_business_scope=True,
            same_temporal_scope=True,
            same_claim=True,
            same_value=True,
            entity_a=entity,
            entity_b=entity,
            scope_a=scope,
            scope_b=scope,
            expected_claims_a=(price_claim,),
            expected_claims_b=(price_claim, extra_claim),
            expected_claim_relations=(
                _relation("price", "UNCHANGED", scope=scope),
                _relation("management_fee", "ADDED", scope=scope),
            ),
            difficulty=Difficulty.MEDIUM,
            annotation_reason=(
                "The second chunk preserves the original price claim and adds "
                "non-conflicting facts."
            ),
            source_documents=VINHOMES_SOURCES,
            seed_index=index,
        )

    if label is GoldRelation.TEMPORAL_VARIANT:
        year_b = year + 1
        scope_b = {**scope, "year": year_b}
        text_a = f"Năm {year}, giá căn {property_type} tại {project} là {value} tỷ đồng/căn."
        text_b = f"Năm {year_b}, giá căn {property_type} tại {project} là {changed} tỷ đồng/căn."
        claim_b = _claim(
            "price",
            entity=project,
            value=changed,
            unit="billion_vnd_per_unit",
            qualifiers=scope_b,
        )
        return _pair(
            pair_id=pair_id,
            domain=Domain.VINHOMES,
            category="price",
            text_a=text_a,
            text_b=text_b,
            expected_relation=label,
            variation_type="different_non_overlapping_year",
            same_entity=True,
            same_business_scope=True,
            same_temporal_scope=False,
            same_claim=True,
            same_value=False,
            entity_a=entity,
            entity_b=entity,
            scope_a=scope,
            scope_b=scope_b,
            expected_claims_a=(price_claim,),
            expected_claims_b=(claim_b,),
            expected_claim_relations=(_relation("price", "UPDATED", scope=scope_b),),
            difficulty=Difficulty.MEDIUM,
            annotation_reason=(
                "Different explicit years are non-overlapping temporal scopes, "
                "not a same-period conflict."
            ),
            diagnostic_hints=(FailureCategory.TEMPORAL_SCOPE_ERROR,),
            source_documents=VINHOMES_SOURCES,
            seed_index=index,
        )

    if label is GoldRelation.CONDITIONAL_VARIANT:
        variant = index % 13
        variations = (
            (
                "price_type_official_secondary",
                "giá chính thức",
                "giá chào thứ cấp",
                "price_type",
            ),
            (
                "price_type_primary_transaction",
                "giá thị trường sơ cấp",
                "giá giao dịch",
                "price_type",
            ),
            (
                "price_type_reference_average",
                "giá tham chiếu",
                "giá trung bình",
                "price_type",
            ),
            (
                "price_type_from_official",
                "giá từ mức",
                "giá chính thức",
                "price_type",
            ),
            (
                "price_basis_per_unit_per_sqm",
                "6,2 tỷ đồng/căn",
                "100 triệu đồng/m²",
                "price_basis",
            ),
            ("property_type", "căn 2PN", "căn 3PN", "property_type"),
            ("building", f"tòa {building}", f"tòa S{index % 4 + 5}", "building"),
            ("unit", f"căn {unit}", f"căn {15 + index % 3:02d}08", "unit"),
            ("subdivision", "phân khu A", "phân khu B", "subdivision"),
            (
                "operator_range_approx",
                "trong khoảng 5,8–6,4 tỷ",
                "xấp xỉ 6,2 tỷ",
                "range_operator",
            ),
            (
                "operator_from_at_most",
                "từ 5,8 tỷ",
                "không quá 6,5 tỷ",
                "range_operator",
            ),
            (
                "operator_at_least_range",
                "ít nhất 5,5 tỷ",
                "trong khoảng 5,8–6,4 tỷ",
                "range_operator",
            ),
            (
                "price_basis_vnd_million",
                "6.200.000.000 VND/căn",
                "100 triệu VND/m²",
                "price_basis",
            ),
        )
        variation, left_term, right_term, field = variations[variant]
        text_a = f"Tại {project} năm {year}, {left_term} được ghi nhận là {value} tỷ đồng."
        text_b = f"Tại {project} năm {year}, {right_term} được ghi nhận là {changed} tỷ đồng."
        if variation.startswith("operator_"):
            text_a = f"Giá căn {property_type} tại {project} năm {year} là {left_term}."
            text_b = f"Giá căn {property_type} tại {project} năm {year} là {right_term}."
        scope_b = {**scope, field: right_term}
        return _pair(
            pair_id=pair_id,
            domain=Domain.VINHOMES,
            category="price_qualifier",
            text_a=text_a,
            text_b=text_b,
            expected_relation=label,
            variation_type=variation,
            same_entity=True,
            same_business_scope=False,
            same_temporal_scope=True,
            same_claim=True,
            same_value=variation == "operator_range_approx",
            entity_a=entity,
            entity_b=entity,
            scope_a={**scope, field: left_term},
            scope_b=scope_b,
            expected_claims_a=(price_claim,),
            expected_claims_b=(price_claim,),
            expected_claim_relations=(_relation("price", "CONDITIONAL_VARIANT", scope=scope_b),),
            difficulty=Difficulty.HARD,
            annotation_reason=(
                "A material price/entity qualifier differs, so raw values are not directly "
                "comparable."
            ),
            diagnostic_hints=(
                FailureCategory.OPERATOR_RANGE_ERROR
                if variation.startswith("operator_")
                else FailureCategory.SCOPE_ERROR,
            ),
            source_documents=VINHOMES_SOURCES,
            seed_index=index,
        )

    if label is GoldRelation.TEMPLATE_VARIANT:
        text_a = (
            f"Dự án: {project}. Mốc {year}. Loại sản phẩm: {property_type}. "
            f"Giá tham chiếu: {value} tỷ đồng/căn. Cần kiểm tra nguồn và hiện trạng."
        )
        text_b = (
            f"Dự án: {alternate_project}. Mốc {year}. Loại sản phẩm: {property_type}. "
            f"Giá tham chiếu: {value} tỷ đồng/căn. Cần kiểm tra nguồn và hiện trạng."
        )
        entity_b = {"project": alternate_project, "building": building, "unit": unit}
        scope_b = {**scope, "project": alternate_project}
        return _pair(
            pair_id=pair_id,
            domain=Domain.VINHOMES,
            category="market_profile_template",
            text_a=text_a,
            text_b=text_b,
            expected_relation=label,
            variation_type="same_market_profile_template_different_project",
            same_entity=False,
            same_business_scope=False,
            same_temporal_scope=True,
            same_claim=True,
            same_value=True,
            entity_a=entity,
            entity_b=entity_b,
            scope_a=scope,
            scope_b=scope_b,
            expected_claims_a=(price_claim,),
            expected_claims_b=(price_claim,),
            expected_claim_relations=(_relation("price", "TEMPLATE_VARIANT", scope=scope_b),),
            difficulty=Difficulty.MEDIUM,
            annotation_reason=(
                "The repeated profile structure is intentional but project identity differs."
            ),
            diagnostic_hints=(FailureCategory.ENTITY_RESOLUTION_ERROR,),
            source_documents=VINHOMES_SOURCES,
            seed_index=index,
        )

    if label is GoldRelation.CONFLICT:
        scenario = index % 6
        source_form_a = SourceForm.PROSE
        source_form_b = SourceForm.PROSE
        table_a = None
        table_b = None
        hints: tuple[FailureCategory, ...] = (FailureCategory.CLAIM_ALIGNMENT_ERROR,)
        conflict_field = "price"
        variation = "same_scope_price_change"
        text_a = f"Giá căn {property_type} tại {project} năm {year} là {value} tỷ đồng/căn."
        text_b = f"Giá căn {property_type} tại {project} năm {year} là {changed} tỷ đồng/căn."
        claim_b = _claim(
            "price",
            entity=project,
            value=changed,
            unit="billion_vnd_per_unit",
            qualifiers=scope,
        )
        relations: tuple[ExpectedClaimRelation, ...] = (
            _relation("price", "CONFLICT", scope=scope, conflict_field="price"),
        )
        if scenario == 1:
            variation = "feature_negation"
            conflict_field = "payment_support"
            text_a = f"Dự án {project} năm {year} có hỗ trợ thanh toán trả góp cho căn {unit}."
            text_b = f"Dự án {project} năm {year} không hỗ trợ thanh toán trả góp cho căn {unit}."
            claim_b = _claim(
                "payment_support", entity=project, value=False, unit=None, qualifiers=scope
            )
            price_claim = _claim(
                "payment_support", entity=project, value=True, unit=None, qualifiers=scope
            )
            relations = (
                _relation("payment_support", "CONFLICT", scope=scope, conflict_field="polarity"),
            )
            hints = (FailureCategory.NEGATION_ERROR,)
        elif scenario == 2:
            variation = "table_to_prose_conflict"
            conflict_field = "price"
            table_a = _table(
                ("Dự án", "Mã căn", "Loại căn", "Ngày hiệu lực", "Giá bán"),
                (project, unit, property_type, f"{year}-01-01", f"{value} tỷ VND"),
            )
            text_a = _render_table(table_a)
            source_form_a = SourceForm.TABLE
            hints = (FailureCategory.TABLE_PROSE_GAP,)
        elif scenario == 3:
            variation = "multi_period_partial_conflict"
            conflict_field = "price_2026"
            text_a = f"{project} – {property_type}:\n2024: 5 tỷ/căn\n2025: 6 tỷ/căn\n2026: 7 tỷ/căn"
            text_b = f"{project} – {property_type}:\n2024: 5 tỷ/căn\n2025: 6 tỷ/căn\n2026: 8 tỷ/căn"
            relations = (
                _relation("price", "UNCHANGED", scope={**scope, "year": 2024}),
                _relation("price", "UNCHANGED", scope={**scope, "year": 2025}),
                _relation(
                    "price",
                    "CONFLICT",
                    scope={**scope, "year": 2026},
                    conflict_field="price",
                ),
            )
            hints = (FailureCategory.CLAIM_ALIGNMENT_ERROR,)
        elif scenario == 4:
            variation = "table_to_table_price_conflict"
            table_a = _table(
                ("Dự án", "Mã căn", "Loại căn", "Ngày hiệu lực", "Giá bán"),
                (project, unit, property_type, f"{year}-01-01", f"{value} tỷ VND"),
            )
            table_b = _table(
                ("Dự án", "Mã căn", "Loại căn", "Ngày hiệu lực", "Giá bán"),
                (project, unit, property_type, f"{year}-01-01", f"{changed} tỷ VND"),
            )
            text_a, text_b = _render_table(table_a), _render_table(table_b)
            source_form_a = source_form_b = SourceForm.TABLE
            hints = (FailureCategory.VALUE_NORMALIZATION_ERROR,)
        elif scenario == 5:
            variation = "high_similarity_value_conflict"
            hints = (FailureCategory.CLASSIFIER_THRESHOLD_ERROR,)
        return _pair(
            pair_id=pair_id,
            domain=Domain.VINHOMES,
            category=conflict_field,
            text_a=text_a,
            text_b=text_b,
            expected_relation=label,
            variation_type=variation,
            same_entity=True,
            same_business_scope=True,
            same_temporal_scope=True,
            same_claim=True,
            same_value=False,
            entity_a=entity,
            entity_b=entity,
            scope_a=scope,
            scope_b=scope,
            expected_claims_a=(price_claim,),
            expected_claims_b=(claim_b,),
            expected_claim_relations=relations,
            conflict_fields=(conflict_field,),
            source_form_a=source_form_a,
            source_form_b=source_form_b,
            table_a=table_a,
            table_b=table_b,
            difficulty=Difficulty.HARD,
            annotation_reason=(
                "Entity, business qualifiers, claim, and period align while the value or "
                "polarity differs."
            ),
            diagnostic_hints=hints,
            source_documents=VINHOMES_SOURCES,
            seed_index=index,
        )

    if label is GoldRelation.DISTINCT:
        entity_b = {"project": alternate_project, "building": f"S{index % 4 + 5}", "unit": unit}
        scope_b = {**scope, "project": alternate_project, "building": entity_b["building"]}
        text_a = f"Giá căn {property_type} tại {project} năm {year} là {value} tỷ đồng/căn."
        text_b = (
            f"Giá căn {property_type} tại {alternate_project}, tòa {entity_b['building']}, "
            f"năm {year} cũng là {value} tỷ đồng/căn."
        )
        return _pair(
            pair_id=pair_id,
            domain=Domain.VINHOMES,
            category="different_project",
            text_a=text_a,
            text_b=text_b,
            expected_relation=label,
            variation_type=(
                "same_value_different_entity" if index % 2 else "structural_identifier"
            ),
            same_entity=False,
            same_business_scope=False,
            same_temporal_scope=True,
            same_claim=True,
            same_value=True,
            entity_a=entity,
            entity_b=entity_b,
            scope_a=scope,
            scope_b=scope_b,
            expected_claims_a=(price_claim,),
            expected_claims_b=(price_claim,),
            expected_claim_relations=(_relation("price", "DISTINCT", scope=scope_b),),
            difficulty=Difficulty.MEDIUM,
            annotation_reason=(
                "Equal values do not make different projects/buildings the same business entity."
            ),
            diagnostic_hints=(FailureCategory.ENTITY_RESOLUTION_ERROR,),
            source_documents=VINHOMES_SOURCES,
            candidate_retrieval_required=False,
            seed_index=index,
            distinct_justification="Project or structural unit identity differs explicitly.",
        )

    scenario = index % 3
    context_a: tuple[str, ...]
    context_b: tuple[str, ...]
    if scenario == 0:
        text_a = f"Giá căn {property_type} tại {project} năm {year} là {value} tỷ đồng."
        text_b = f"Giá căn {property_type} tại {project} năm {year} là 62 tỷ đồng."
        variation = "ocr_semantic_value_corruption"
        context_a = context_b = ()
        hints = (FailureCategory.OCR_EXTRACTION_ERROR,)
    elif scenario == 1:
        text_a = "Đối với dự án này, giá căn 2PN là 6,2 tỷ đồng."
        text_b = "Đối với dự án này, giá căn 2PN là 7,1 tỷ đồng."
        variation = "cross_chunk_reference"
        context_a = (f"Tiêu đề: {project}",)
        context_b = (f"Tiêu đề: {project}",)
        hints = (FailureCategory.CROSS_CHUNK_CONTEXT_MISSING,)
    else:
        text_a = f"Giá căn {property_type} tại {project}: khoảng 5,8–6,4 tỷ đồng."
        text_b = f"Giá căn {property_type} tại {project}: 58–64 tỷ đồng."
        variation = "ocr_range_ambiguity"
        context_a = context_b = ()
        hints = (FailureCategory.OCR_EXTRACTION_ERROR, FailureCategory.OPERATOR_RANGE_ERROR)
    return _pair(
        pair_id=pair_id,
        domain=Domain.VINHOMES,
        category="extraction_reliability",
        text_a=text_a,
        text_b=text_b,
        expected_relation=label,
        variation_type=variation,
        same_entity=True,
        same_business_scope=True,
        same_temporal_scope=True,
        same_claim=True,
        same_value=False,
        entity_a=entity,
        entity_b=entity,
        scope_a=scope,
        scope_b=scope,
        expected_claims_a=(price_claim,),
        expected_claims_b=(),
        expected_claim_relations=(_relation("price", "UNCERTAIN", scope=scope),),
        context_a=context_a,
        context_b=context_b,
        noise_b=NoiseLevel.SEVERE if scenario != 1 else NoiseLevel.MEDIUM,
        reliability_b=ExtractionReliability.LOW,
        difficulty=Difficulty.HARD,
        annotation_reason=(
            "Extraction reliability or missing parent context is insufficient for a safe relation."
        ),
        diagnostic_hints=hints,
        source_documents=VINHOMES_SOURCES,
        candidate_retrieval_required=False,
        seed_index=index,
    )


def _vf_context(index: int) -> tuple[str, str, int, str, str, str, str]:
    models = ("VF 6", "VF 7", "VF 8", "VF 9")
    trims = ("Eco", "Plus", "Base", "Premium")
    markets = ("Việt Nam", "Mỹ", "Châu Âu", "Canada")
    model = models[index % len(models)]
    trim = trims[(index // 4) % len(trims)]
    year = 2023 + (index // 7) % 4
    market = markets[(index // 3) % len(markets)]
    protocol = ("WLTP", "EPA", "NEDC")[(index // 5) % 3]
    value = str(360 + (index * 13 + index // 4) % 190)
    changed = str(int(value) + 30)
    return model, trim, year, market, protocol, value, changed


def _vf_pair(label: GoldRelation, index: int) -> GoldPair:
    model, trim, year, market, protocol, value, changed = _vf_context(index)
    alternate_model = _vf_context(index + 1)[0]
    entity = {"brand": "VinFast", "model": model, "trim": trim}
    scope = {
        "model": model,
        "trim": trim,
        "model_year": year,
        "market": market,
        "protocol": protocol,
    }
    pair_id = f"VF_{label.value}_{index + 1:04d}"
    range_claim = _claim(
        "range",
        entity=model,
        value=int(value),
        unit="km",
        qualifiers=scope,
    )

    if label is GoldRelation.EXACT_DUPLICATE:
        base = (
            f"VinFast {model} {trim} đời {year} tại thị trường {market} có tầm hoạt động "
            f"tham chiếu {value} km theo chu trình {protocol}."
        )
        transformations: tuple[tuple[str, Callable[[str], str]], ...] = (
            ("same_text", lambda text: text),
            ("whitespace_change", lambda text: text.replace(" tại ", "  tại\n")),
            ("unicode_nfc_nfd", lambda text: unicodedata.normalize("NFD", text)),
            ("line_break_change", lambda text: text.replace(" có ", "\n có ")),
            ("nbsp_change", lambda text: text.replace(" ", "\u00a0", 1)),
            ("zero_width_change", lambda text: text.replace("VinFast", "Vin\u200bFast")),
        )
        variation, transform = transformations[index % len(transformations)]
        return _pair(
            pair_id=pair_id,
            domain=Domain.VINFAST,
            category="range",
            text_a=base,
            text_b=transform(base),
            expected_relation=label,
            variation_type=variation,
            same_entity=True,
            same_business_scope=True,
            same_temporal_scope=True,
            same_claim=True,
            same_value=True,
            entity_a=entity,
            entity_b=entity,
            scope_a=scope,
            scope_b=scope,
            expected_claims_a=(range_claim,),
            expected_claims_b=(range_claim,),
            expected_claim_relations=(_relation("range", "UNCHANGED", scope=scope),),
            noise_b=(NoiseLevel.LIGHT if index % len(transformations) >= 2 else NoiseLevel.NONE),
            difficulty=Difficulty.EASY,
            annotation_reason=(
                "Only representation-level differences allowed by strict normalization exist."
            ),
            source_documents=VINFAST_SOURCES,
            expected_auto_reuse=True,
            seed_index=index,
        )

    if label is GoldRelation.NEAR_DUPLICATE:
        compact_model = model.replace(" ", "")
        text_a = (
            f"VinFast {model} bản {trim}, đời {year}, thị trường {market}, đạt khoảng "
            f"{value} km theo {protocol}."
        )
        text_b = (
            f"Phạm vi di chuyển tham chiếu của {compact_model} {trim} model year {year} "
            f"ở {market} là xấp xỉ {value} kilomet theo phép thử {protocol}."
        )
        return _pair(
            pair_id=pair_id,
            domain=Domain.VINFAST,
            category="range",
            text_a=text_a,
            text_b=text_b,
            expected_relation=label,
            variation_type="model_alias_and_paraphrase",
            same_entity=True,
            same_business_scope=True,
            same_temporal_scope=True,
            same_claim=True,
            same_value=True,
            entity_a=entity,
            entity_b=entity,
            scope_a=scope,
            scope_b=scope,
            expected_claims_a=(range_claim,),
            expected_claims_b=(range_claim,),
            expected_claim_relations=(_relation("range", "UNCHANGED", scope=scope),),
            noise_b=NoiseLevel.LIGHT if index % 5 == 0 else NoiseLevel.NONE,
            difficulty=Difficulty.MEDIUM,
            annotation_reason=(
                "VF8/VF 8 aliasing and wording differ while all business qualifiers and "
                "value match."
            ),
            diagnostic_hints=(FailureCategory.ENTITY_RESOLUTION_ERROR,),
            source_documents=VINFAST_SOURCES,
            seed_index=index,
        )

    if label is GoldRelation.VERSION_UPDATE:
        base = (
            f"{model} {trim} đời {year} tại {market} có tầm tham chiếu {value} km theo {protocol}."
        )
        added = (
            f" Bản cập nhật bổ sung mô tả cổng sạc thử nghiệm và gói hỗ trợ dịch vụ số {index + 1}."
        )
        feature_claim = _claim(
            "service_feature",
            entity=model,
            value=f"package-{index + 1}",
            unit=None,
            qualifiers=scope,
        )
        return _pair(
            pair_id=pair_id,
            domain=Domain.VINFAST,
            category="version_extension",
            text_a=base,
            text_b=base + added,
            expected_relation=label,
            variation_type="added_information",
            same_entity=True,
            same_business_scope=True,
            same_temporal_scope=True,
            same_claim=True,
            same_value=True,
            entity_a=entity,
            entity_b=entity,
            scope_a=scope,
            scope_b=scope,
            expected_claims_a=(range_claim,),
            expected_claims_b=(range_claim, feature_claim),
            expected_claim_relations=(
                _relation("range", "UNCHANGED", scope=scope),
                _relation("service_feature", "ADDED", scope=scope),
            ),
            difficulty=Difficulty.MEDIUM,
            annotation_reason=(
                "The second chunk extends the first without replacing its range claim."
            ),
            source_documents=VINFAST_SOURCES,
            seed_index=index,
        )

    if label is GoldRelation.TEMPORAL_VARIANT:
        scope_b = {**scope, "model_year": year + 1}
        text_a = f"{model} {trim} model year {year} tại {market} có tầm {value} km theo {protocol}."
        text_b = (
            f"{model} {trim} model year {year + 1} tại {market} có tầm "
            f"{changed} km theo {protocol}."
        )
        claim_b = _claim("range", entity=model, value=int(changed), unit="km", qualifiers=scope_b)
        return _pair(
            pair_id=pair_id,
            domain=Domain.VINFAST,
            category="model_year",
            text_a=text_a,
            text_b=text_b,
            expected_relation=label,
            variation_type="different_model_year",
            same_entity=True,
            same_business_scope=True,
            same_temporal_scope=False,
            same_claim=True,
            same_value=False,
            entity_a=entity,
            entity_b=entity,
            scope_a=scope,
            scope_b=scope_b,
            expected_claims_a=(range_claim,),
            expected_claims_b=(claim_b,),
            expected_claim_relations=(_relation("range", "UPDATED", scope=scope_b),),
            difficulty=Difficulty.MEDIUM,
            annotation_reason="Different model years are non-overlapping temporal variants.",
            diagnostic_hints=(FailureCategory.TEMPORAL_SCOPE_ERROR,),
            source_documents=VINFAST_SOURCES,
            seed_index=index,
        )

    if label is GoldRelation.CONDITIONAL_VARIANT:
        scenario = index % 6
        variations = (
            ("trim_variant", {**scope, "trim": "Eco"}, {**scope, "trim": "Plus"}),
            ("market_variant", {**scope, "market": "Việt Nam"}, {**scope, "market": "Mỹ"}),
            ("test_protocol", {**scope, "protocol": "WLTP"}, {**scope, "protocol": "EPA"}),
            (
                "charging_condition",
                {**scope, "charge_from": 10, "charge_to": 70},
                {**scope, "charge_from": 10, "charge_to": 80},
            ),
            (
                "battery_variant",
                {**scope, "battery_variant": "standard"},
                {**scope, "battery_variant": "extended"},
            ),
            ("price_type", {**scope, "price_type": "list"}, {**scope, "price_type": "promo"}),
        )
        variation, scope_a, scope_b = variations[scenario]
        if variation == "charging_condition":
            text_a = f"{model} {trim} sạc từ 10% lên 70% trong khoảng 25 phút."
            text_b = f"{model} {trim} sạc từ 10% lên 80% trong khoảng 25 phút."
            category = "charging"
        elif variation == "test_protocol":
            text_a = f"{model} {trim} có tầm 450 km theo WLTP."
            text_b = f"{model} {trim} có tầm 420 km theo EPA."
            category = "range_protocol"
        else:
            text_a = f"{model} với điều kiện {variation} A có giá trị tham chiếu {value}."
            text_b = f"{model} với điều kiện {variation} B có giá trị tham chiếu {changed}."
            category = variation
        return _pair(
            pair_id=pair_id,
            domain=Domain.VINFAST,
            category=category,
            text_a=text_a,
            text_b=text_b,
            expected_relation=label,
            variation_type=variation,
            same_entity=True,
            same_business_scope=False,
            same_temporal_scope=True,
            same_claim=True,
            same_value=False,
            entity_a=entity,
            entity_b=entity,
            scope_a=scope_a,
            scope_b=scope_b,
            expected_claims_a=(range_claim,),
            expected_claims_b=(range_claim,),
            expected_claim_relations=(_relation(category, "CONDITIONAL_VARIANT", scope=scope_b),),
            difficulty=Difficulty.HARD,
            annotation_reason=(
                "Trim, market, protocol, charging window, battery, or price qualifier differs."
            ),
            diagnostic_hints=(FailureCategory.SCOPE_ERROR,),
            source_documents=VINFAST_SOURCES,
            seed_index=index,
        )

    if label is GoldRelation.TEMPLATE_VARIANT:
        text_a = (
            f"Mẫu xe: {model}. Phiên bản: {trim}. Năm: {year}. Thị trường: {market}. "
            f"Tầm tham chiếu: {value} km."
        )
        text_b = (
            f"Mẫu xe: {alternate_model}. Phiên bản: {trim}. Năm: {year}. Thị trường: {market}. "
            f"Tầm tham chiếu: {value} km."
        )
        entity_b = {**entity, "model": alternate_model}
        scope_b = {**scope, "model": alternate_model}
        return _pair(
            pair_id=pair_id,
            domain=Domain.VINFAST,
            category="spec_template",
            text_a=text_a,
            text_b=text_b,
            expected_relation=label,
            variation_type="same_spec_template_different_model",
            same_entity=False,
            same_business_scope=False,
            same_temporal_scope=True,
            same_claim=True,
            same_value=True,
            entity_a=entity,
            entity_b=entity_b,
            scope_a=scope,
            scope_b=scope_b,
            expected_claims_a=(range_claim,),
            expected_claims_b=(range_claim,),
            expected_claim_relations=(_relation("range", "TEMPLATE_VARIANT", scope=scope_b),),
            difficulty=Difficulty.MEDIUM,
            annotation_reason="Specification layout is reused but model identity differs.",
            diagnostic_hints=(FailureCategory.ENTITY_RESOLUTION_ERROR,),
            source_documents=VINFAST_SOURCES,
            seed_index=index,
        )

    if label is GoldRelation.CONFLICT:
        scenario = index % 6
        text_a = f"{model} {trim} đời {year} tại {market} có tầm {value} km theo {protocol}."
        text_b = f"{model} {trim} đời {year} tại {market} có tầm {changed} km theo {protocol}."
        claim_name = "range"
        conflict_field = "range"
        variation = "same_scope_range_change"
        claim_a = range_claim
        claim_b = _claim("range", entity=model, value=int(changed), unit="km", qualifiers=scope)
        source_form_a = SourceForm.PROSE
        source_form_b = SourceForm.PROSE
        table_a = None
        table_b = None
        hints: tuple[FailureCategory, ...] = (FailureCategory.CLAIM_ALIGNMENT_ERROR,)
        if scenario == 1:
            variation = "same_scope_battery_capacity_change"
            claim_name = conflict_field = "battery_capacity"
            text_a = f"{model} {trim} đời {year} tại {market} dùng pin 87,7 kWh."
            text_b = f"{model} {trim} đời {year} tại {market} dùng pin 90 kWh."
            claim_a = _claim(claim_name, entity=model, value=87.7, unit="kWh", qualifiers=scope)
            claim_b = _claim(claim_name, entity=model, value=90, unit="kWh", qualifiers=scope)
            hints = (FailureCategory.UNIT_NORMALIZATION_ERROR,)
        elif scenario == 2:
            variation = "feature_negation"
            claim_name = conflict_field = "feature"
            text_a = f"{model} {trim} đời {year} có tính năng hỗ trợ giữ làn thử nghiệm."
            text_b = f"{model} {trim} đời {year} không được trang bị hỗ trợ giữ làn thử nghiệm."
            claim_a = _claim(claim_name, entity=model, value=True, unit=None, qualifiers=scope)
            claim_b = _claim(claim_name, entity=model, value=False, unit=None, qualifiers=scope)
            hints = (FailureCategory.NEGATION_ERROR,)
        elif scenario == 3:
            variation = "table_to_prose_conflict"
            table_a = _table(
                ("Mã", "Biến thể", "Ngày hiệu lực", "Tầm hoạt động"),
                (model, trim, f"{year}-01-01", f"{value} km {protocol}"),
            )
            text_a = _render_table(table_a)
            source_form_a = SourceForm.TABLE
            hints = (FailureCategory.TABLE_PROSE_GAP,)
        elif scenario == 4:
            variation = "table_to_table_range_conflict"
            table_a = _table(
                ("Mã", "Biến thể", "Ngày hiệu lực", "Tầm hoạt động"),
                (model, trim, f"{year}-01-01", f"{value} km {protocol}"),
            )
            table_b = _table(
                ("Mã", "Biến thể", "Ngày hiệu lực", "Tầm hoạt động"),
                (model, trim, f"{year}-01-01", f"{changed} km {protocol}"),
            )
            text_a, text_b = _render_table(table_a), _render_table(table_b)
            source_form_a = source_form_b = SourceForm.TABLE
            hints = (FailureCategory.VALUE_NORMALIZATION_ERROR,)
        elif scenario == 5:
            variation = "high_similarity_value_conflict"
            hints = (FailureCategory.CLASSIFIER_THRESHOLD_ERROR,)
        return _pair(
            pair_id=pair_id,
            domain=Domain.VINFAST,
            category=claim_name,
            text_a=text_a,
            text_b=text_b,
            expected_relation=label,
            variation_type=variation,
            same_entity=True,
            same_business_scope=True,
            same_temporal_scope=True,
            same_claim=True,
            same_value=False,
            entity_a=entity,
            entity_b=entity,
            scope_a=scope,
            scope_b=scope,
            expected_claims_a=(claim_a,),
            expected_claims_b=(claim_b,),
            expected_claim_relations=(
                _relation(claim_name, "CONFLICT", scope=scope, conflict_field=conflict_field),
            ),
            conflict_fields=(conflict_field,),
            source_form_a=source_form_a,
            source_form_b=source_form_b,
            table_a=table_a,
            table_b=table_b,
            difficulty=Difficulty.HARD,
            annotation_reason=(
                "Model, trim, model year, market, protocol, and claim align but "
                "value/polarity differs."
            ),
            diagnostic_hints=hints,
            source_documents=VINFAST_SOURCES,
            seed_index=index,
        )

    if label is GoldRelation.DISTINCT:
        entity_b = {**entity, "model": alternate_model}
        scope_b = {**scope, "model": alternate_model}
        text_a = f"{model} {trim} có tầm tham chiếu {value} km theo {protocol}."
        text_b = f"{alternate_model} {trim} có tầm tham chiếu {value} km theo {protocol}."
        return _pair(
            pair_id=pair_id,
            domain=Domain.VINFAST,
            category="different_model",
            text_a=text_a,
            text_b=text_b,
            expected_relation=label,
            variation_type="same_value_different_model",
            same_entity=False,
            same_business_scope=False,
            same_temporal_scope=True,
            same_claim=True,
            same_value=True,
            entity_a=entity,
            entity_b=entity_b,
            scope_a=scope,
            scope_b=scope_b,
            expected_claims_a=(range_claim,),
            expected_claims_b=(range_claim,),
            expected_claim_relations=(_relation("range", "DISTINCT", scope=scope_b),),
            difficulty=Difficulty.MEDIUM,
            annotation_reason="Equal numeric values do not make VF 8 and VF 9 the same model.",
            diagnostic_hints=(FailureCategory.ENTITY_RESOLUTION_ERROR,),
            source_documents=VINFAST_SOURCES,
            candidate_retrieval_required=False,
            seed_index=index,
            distinct_justification="The explicit vehicle model identifier differs.",
        )

    scenario = index % 3
    context_a: tuple[str, ...]
    context_b: tuple[str, ...]
    if scenario == 0:
        text_a = f"{model} {trim} đời {year} có tầm {value} km theo {protocol}."
        text_b = f"{model} {trim} đời 2O26 có tầm {value[:-1]}O km theo {protocol}."
        variation = "ocr_year_and_value_corruption"
        context_a = context_b = ()
        hints = (FailureCategory.OCR_EXTRACTION_ERROR,)
    elif scenario == 1:
        text_a = f"Đối với phiên bản {trim} của mẫu xe này, tầm hoạt động là {value} km."
        text_b = f"Đối với phiên bản {trim} của mẫu xe này, tầm hoạt động là {changed} km."
        variation = "cross_chunk_reference"
        context_a = (f"Tiêu đề cha: VinFast {model}",)
        context_b = (f"Tiêu đề cha: VinFast {model}",)
        hints = (FailureCategory.CROSS_CHUNK_CONTEXT_MISSING,)
    else:
        text_a = f"{model} {trim} có dung lượng pin 87,7 kWh."
        text_b = f"{model} {trim} có dung lượng pin 877 kWh do OCR không chắc chắn."
        variation = "ocr_decimal_loss"
        context_a = context_b = ()
        hints = (FailureCategory.OCR_EXTRACTION_ERROR, FailureCategory.VALUE_NORMALIZATION_ERROR)
    return _pair(
        pair_id=pair_id,
        domain=Domain.VINFAST,
        category="extraction_reliability",
        text_a=text_a,
        text_b=text_b,
        expected_relation=label,
        variation_type=variation,
        same_entity=True,
        same_business_scope=True,
        same_temporal_scope=True,
        same_claim=True,
        same_value=False,
        entity_a=entity,
        entity_b=entity,
        scope_a=scope,
        scope_b=scope,
        expected_claims_a=(range_claim,),
        expected_claims_b=(),
        expected_claim_relations=(_relation("range", "UNCERTAIN", scope=scope),),
        context_a=context_a,
        context_b=context_b,
        noise_b=NoiseLevel.SEVERE if scenario != 1 else NoiseLevel.MEDIUM,
        reliability_b=ExtractionReliability.LOW,
        difficulty=Difficulty.HARD,
        annotation_reason=(
            "OCR damage or omitted parent model identity prevents a safe deterministic comparison."
        ),
        diagnostic_hints=hints,
        source_documents=VINFAST_SOURCES,
        candidate_retrieval_required=False,
        seed_index=index,
    )


def build_pairs() -> tuple[GoldPair, ...]:
    pairs: list[GoldPair] = []
    for label, count in LABEL_COUNTS_PER_DOMAIN.items():
        pairs.extend(_vh_pair(label, index) for index in range(count))
        pairs.extend(_vf_pair(label, index) for index in range(count))
    return tuple(sorted(pairs, key=lambda pair: pair.pair_id))


def _json_line(pair: GoldPair) -> str:
    return json.dumps(pair.model_dump(mode="json"), ensure_ascii=False, sort_keys=True)


def _write_jsonl(path: Path, pairs: tuple[GoldPair, ...]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("".join(f"{_json_line(pair)}\n" for pair in pairs), encoding="utf-8")


def _write_stress_cases(path: Path) -> None:
    payload = {
        "version": SCHEMA_VERSION,
        "long_document": {
            "chunk_count": 100,
            "max_fuzzy_probes": 8,
            "meaningful_positions_1_based": [1, 17, 50, 83, 99],
            "relation": "CONFLICT",
            "description": (
                "Only the listed chunk carries a same-scope changed-value claim; "
                "all other chunks are unrelated distractors."
            ),
        },
        "simhash_lsh": {
            "text_a": (
                "Giá tham chiếu căn hộ hai phòng ngủ tại dự án Vinhomes Project Alpha "
                "năm 2026 là khoảng 6,2 tỷ đồng mỗi căn và đã gồm phí quản lý."
            ),
            "text_b": (
                "Giá tham chiếu căn hộ hai phòng ngủ thuộc dự án Project Alpha của "
                "Vinhomes cho kỳ 2026 xấp xỉ 6,2 tỷ đồng mỗi căn và đã gồm phí quản lý."
            ),
            "expected_relation": "NEAR_DUPLICATE",
            "expected_hamming_distance": 21,
            "expected_lsh_band_overlap": 0,
            "expected_candidate_result": "CANDIDATE_MISS",
        },
        "candidate_corpus_policy": {
            "distractors_per_pair": 60,
            "selection": "stable SHA-256 order; same category, then same domain, then cross-domain",
            "runtime_candidate_limit": 5,
            "curve_limit": 50,
        },
    }
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def write_dataset() -> tuple[GoldPair, ...]:
    pairs = build_pairs()
    dev = tuple(pair for pair in pairs if pair.split == "dev")
    test = tuple(pair for pair in pairs if pair.split == "test")
    smoke = tuple(
        next(pair for pair in pairs if pair.domain is domain and pair.expected_relation is label)
        for domain in Domain
        for label in GoldRelation
    )
    DATASET_DIR.mkdir(parents=True, exist_ok=True)
    _write_jsonl(FULL_DATASET_PATH, pairs)
    _write_jsonl(DEV_DATASET_PATH, dev)
    _write_jsonl(TEST_DATASET_PATH, test)
    _write_jsonl(SMOKE_DATASET_PATH, smoke)
    _write_stress_cases(STRESS_CASES_PATH)
    return pairs


def main() -> int:
    pairs = write_dataset()
    print(
        json.dumps(
            {
                "dataset": str(FULL_DATASET_PATH),
                "pairs": len(pairs),
                "dev": sum(pair.split == "dev" for pair in pairs),
                "test": sum(pair.split == "test" for pair in pairs),
            },
            ensure_ascii=False,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())


__all__ = ["LABEL_COUNTS_PER_DOMAIN", "build_pairs", "deterministic_split", "write_dataset"]
