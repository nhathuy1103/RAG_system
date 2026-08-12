"""Real-logic coverage for P2 entity, business-scope, and admission contracts."""

from __future__ import annotations

from datetime import date

import pytest

from app.knowledge_quality.application.analysis import analyze_text_relation
from app.knowledge_quality.application.business_scope import (
    ScopeTextContext,
    load_or_resolve_business_context,
    resolve_business_context,
)
from app.knowledge_quality.application.claims import (
    classify_numeric_mentions,
    normalized_quantities,
)
from app.knowledge_quality.application.conflict_admission import decide_conflict_admission
from app.knowledge_quality.application.entity_resolution import resolve_entities
from app.knowledge_quality.domain.models import NumericRole, RelationType
from app.knowledge_quality.domain.scope_models import (
    ConflictAdmissionDisposition,
    ResolvedBusinessContext,
)
from app.pipeline.documents.domain.parsed import ParsedTable
from app.structured_facts.application.scope import compare_business_scopes
from app.structured_facts.application.table_analyzer import analyze_table
from app.structured_facts.domain.models import (
    BusinessScope,
    EntityEvidenceSource,
    LocationScope,
    ScopeRelation,
)


@pytest.mark.parametrize("alias", ("VF8", "VF 8", "VinFast VF8", "VinFast VF 8"))
def test_vinfast_aliases_resolve_to_one_auditable_entity(alias: str) -> None:
    result = resolve_entities(f"{alias} Eco có tầm 450 km.", domain_hint="vinfast")
    entity = result.primary_entity

    assert entity is not None
    assert entity.canonical_id == "vinfast_vf8"
    assert entity.registry_version == "p2-vinfast-entities-v1"
    assert entity.evidence[0].raw_text
    assert entity.evidence[0].span_start is not None


def test_registry_only_accepts_explicit_vinhomes_aliases() -> None:
    aliases = ("Project Alpha", "Vinhomes Project Alpha", "Alpha")
    resolved = [resolve_entities(alias, domain_hint="vinhomes").primary_entity for alias in aliases]

    assert {item.canonical_id for item in resolved if item is not None} == {
        "vinhomes_project_alpha"
    }
    assert resolve_entities("Ocean Residence", domain_hint="vinhomes").primary_entity is None


def test_ocr_corruption_fails_closed_instead_of_false_entity_assignment() -> None:
    corrupted_vehicle = resolve_business_context(
        "VFB Eco cÃ³ táº§m 450 km theo WLTP nÄƒm 2O26.",
        domain_hint="vinfast",
    )
    corrupted_building = resolve_business_context(
        "Project Alpha tÃ²a SI cÄƒn 2PN nÄƒm 2026 giÃ¡ 6 tá»·/cÄƒn.",
        domain_hint="vinhomes",
    )

    assert corrupted_vehicle.primary_entity is None
    assert corrupted_vehicle.temporal.effective_from is None
    assert corrupted_building.primary_entity is not None
    assert corrupted_building.business_scope.location.building is None


@pytest.mark.parametrize(
    ("left", "right", "reason_fragment"),
    (
        ("Project Alpha giai đoạn 1", "Project Alpha giai đoạn 2", "phase"),
        ("Project Alpha tòa S1", "Project Alpha tòa S2", "building"),
        ("Project Alpha unit 1208", "Project Alpha unit 1508", "unit"),
    ),
)
def test_vinhomes_hierarchy_differences_are_not_admitted(
    left: str, right: str, reason_fragment: str
) -> None:
    suffix = " năm 2026 căn 2PN giá 6 tỷ/căn."
    decision = decide_conflict_admission(
        resolve_business_context(left + suffix),
        resolve_business_context(right + suffix),
    )

    assert decision.allows_conflict_analysis is False
    assert decision.disposition is ConflictAdmissionDisposition.CONDITIONAL_VARIANT
    assert reason_fragment in " ".join(decision.reason_codes)


@pytest.mark.parametrize(
    ("left", "right"),
    (
        ("căn 2PN", "căn 3PN"),
        ("căn hộ", "biệt thự"),
        ("giá chính thức", "giá chào thứ cấp"),
        ("giá chào", "giá giao dịch"),
        ("6 tỷ/căn", "100 triệu/m2"),
    ),
)
def test_vinhomes_product_and_commercial_dimensions_are_disjoint(left: str, right: str) -> None:
    prefix = "Project Alpha năm 2026 "
    decision = decide_conflict_admission(
        resolve_business_context(prefix + left),
        resolve_business_context(prefix + right),
    )

    assert decision.allows_conflict_analysis is False
    assert decision.scope_relation is ScopeRelation.DISJOINT


@pytest.mark.parametrize(
    ("left", "right"),
    (
        (
            "VF8 Eco đời 2025 tại Việt Nam tầm 450 km WLTP.",
            "VF9 Eco đời 2025 tại Việt Nam tầm 450 km WLTP.",
        ),
        (
            "VF8 Eco đời 2025 tại Việt Nam tầm 450 km WLTP.",
            "VF8 Plus đời 2025 tại Việt Nam tầm 470 km WLTP.",
        ),
        (
            "VF8 Eco đời 2025 tại Việt Nam tầm 450 km WLTP.",
            "VF8 Eco đời 2026 tại Việt Nam tầm 470 km WLTP.",
        ),
        (
            "VF8 Eco đời 2025 tại Việt Nam tầm 450 km WLTP.",
            "VF8 Eco đời 2025 tại Mỹ tầm 470 km WLTP.",
        ),
        (
            "VF8 Eco đời 2025 tại Việt Nam tầm 450 km WLTP.",
            "VF8 Eco đời 2025 tại Việt Nam tầm 420 km EPA.",
        ),
        (
            "VF8 Eco đời 2025 pin standard tại Việt Nam tầm 450 km WLTP.",
            "VF8 Eco đời 2025 pin extended tại Việt Nam tầm 470 km WLTP.",
        ),
    ),
)
def test_vinfast_scope_variants_never_reach_value_conflict(left: str, right: str) -> None:
    decision = decide_conflict_admission(
        resolve_business_context(left), resolve_business_context(right)
    )

    assert decision.allows_conflict_analysis is False
    assert decision.disposition in {
        ConflictAdmissionDisposition.DISTINCT_ENTITY,
        ConflictAdmissionDisposition.CONDITIONAL_VARIANT,
        ConflictAdmissionDisposition.TEMPORAL_VARIANT,
    }


def test_same_vinhomes_and_vinfast_scope_admit_different_values() -> None:
    pairs = (
        (
            "Project Alpha căn 2PN năm 2026 giá thị trường sơ cấp 6,2 tỷ/căn.",
            "Vinhomes Project Alpha căn 2PN năm 2026 giá thị trường sơ cấp 7,1 tỷ/căn.",
        ),
        (
            "VF8 Eco đời 2025 tại Việt Nam tầm 450 km WLTP.",
            "VinFast VF 8 Eco đời 2025 tại Việt Nam tầm 480 km WLTP.",
        ),
    )

    for left, right in pairs:
        decision = decide_conflict_admission(
            resolve_business_context(left), resolve_business_context(right)
        )
        assert decision.allows_conflict_analysis is True
        assert decision.disposition is ConflictAdmissionDisposition.ADMIT


@pytest.mark.parametrize(
    ("text", "reference_type"),
    (
        ("VF 8 có tầm 450 km", "vehicle_model_code"),
        ("Tòa S1 có 20 căn", "building_code"),
        ("Unit 1208 có giá 6 tỷ", "unit_code"),
        ("Căn 2PN có giá 6 tỷ", "bedroom_variant"),
    ),
)
def test_domain_numbers_are_identifiers_not_semantic_quantities(
    text: str, reference_type: str
) -> None:
    mentions = classify_numeric_mentions(text)

    assert any(
        item.role is NumericRole.IDENTIFIER and item.reference_type == reference_type
        for item in mentions
    )
    assert all(
        not (
            item.role is NumericRole.SEMANTIC_QUANTITY
            and item.raw_text.strip() in {"8", "1", "1208", "2"}
        )
        for item in mentions
    )


def test_identifier_difference_does_not_become_quantity_conflict() -> None:
    assert "8" not in normalized_quantities("VF 8 Eco có tầm 450 km.")
    analysis = analyze_text_relation(
        "VF 8 Eco đời 2025 tại Việt Nam có tầm 450 km WLTP.",
        "VF 9 Eco đời 2025 tại Việt Nam có tầm 450 km WLTP.",
        domain_scope_mode="on",
    )

    assert analysis.relation_type is not RelationType.CONFLICT_CANDIDATE
    assert "semantic_quantity_mismatch" not in analysis.reason_codes


def test_temporal_context_supports_same_different_and_multi_period_claims() -> None:
    same = resolve_business_context("Project Alpha năm 2026 giá căn 2PN là 6 tỷ/căn.")
    other = resolve_business_context("Project Alpha năm 2025 giá căn 2PN là 6 tỷ/căn.")
    multi = resolve_business_context(
        "Project Alpha studio: 2024: 5 tỷ/căn; 2025: 6 tỷ/căn; 2026: 7 tỷ/căn."
    )

    assert same.temporal.effective_from == date(2026, 1, 1)
    assert decide_conflict_admission(same, same).allows_conflict_analysis is True
    assert decide_conflict_admission(same, other).disposition is (
        ConflictAdmissionDisposition.TEMPORAL_VARIANT
    )
    assert multi.temporal.claim_periods == ("year:2024", "year:2025", "year:2026")


@pytest.mark.parametrize(
    ("left", "right"),
    (
        ("VF8 có tầm 450 km WLTP năm 2025.", "VF8 Eco có tầm 480 km WLTP năm 2025."),
        ("VF8 Eco có tầm 450 km năm 2025.", "VF8 Eco có tầm 480 km WLTP năm 2025."),
        ("Căn 2PN năm 2026 giá 6 tỷ/căn.", "Project Alpha căn 2PN năm 2026 giá 7 tỷ/căn."),
    ),
)
def test_missing_required_entity_or_scope_fails_closed(left: str, right: str) -> None:
    decision = decide_conflict_admission(
        resolve_business_context(left), resolve_business_context(right)
    )

    assert decision.allows_conflict_analysis is False
    assert decision.disposition is ConflictAdmissionDisposition.UNCERTAIN


def test_explicit_breadth_is_distinct_from_missing_scope() -> None:
    missing = BusinessScope(location=LocationScope(project="alpha"))
    specific = BusinessScope(location=LocationScope(project="alpha", building="s1"))
    broad = BusinessScope(
        location=LocationScope(project="alpha"),
        explicit_breadth=("location.building",),
    )

    assert compare_business_scopes(missing, specific) is ScopeRelation.UNKNOWN
    assert compare_business_scopes(broad, specific) is ScopeRelation.LEFT_CONTAINS_RIGHT


def test_heading_context_is_inherited_with_provenance_but_does_not_override_text() -> None:
    inherited = resolve_business_context(
        "Phạm vi hoạt động đạt 450 km theo WLTP năm 2025.",
        contexts=(
            ScopeTextContext(
                "VINFAST VF 8 ECO",
                EntityEvidenceSource.SECTION_HEADING,
                "section-1",
            ),
        ),
    )
    explicit = resolve_business_context(
        "VF9 Plus có phạm vi 450 km theo WLTP năm 2025.",
        contexts=(
            ScopeTextContext(
                "VINFAST VF 8 ECO",
                EntityEvidenceSource.SECTION_HEADING,
                "section-1",
            ),
        ),
    )

    assert inherited.primary_entity is not None
    assert inherited.primary_entity.canonical_id == "vinfast_vf8"
    assert inherited.primary_entity.evidence[0].source is EntityEvidenceSource.SECTION_HEADING
    assert explicit.primary_entity is not None
    assert explicit.primary_entity.canonical_id == "vinfast_vf9"
    assert explicit.business_scope.vehicle.trim == "plus"


def test_entity_scope_metadata_round_trip_and_legacy_fallback() -> None:
    resolved = resolve_business_context("VF8 Eco đời 2025 tại Việt Nam có tầm 450 km theo WLTP.")
    restored = ResolvedBusinessContext.from_metadata(resolved.to_metadata())
    fallback = load_or_resolve_business_context(
        "Project Alpha căn 2PN năm 2026 giá 6 tỷ/căn.",
        persisted_metadata={"legacy": True},
    )

    assert restored == resolved
    assert fallback.primary_entity is not None
    assert fallback.primary_entity.canonical_id == "vinhomes_project_alpha"


def test_claim_comparable_key_excludes_value() -> None:
    left = resolve_business_context(
        "Project Alpha căn 2PN năm 2026 giá thị trường sơ cấp 6,2 tỷ/căn."
    )
    right = resolve_business_context(
        "Project Alpha căn 2PN năm 2026 giá thị trường sơ cấp 7,1 tỷ/căn."
    )

    assert left.comparable_key.identity_hash == right.comparable_key.identity_hash


def test_shadow_records_disagreement_and_on_mode_blocks_false_conflict() -> None:
    left = "VF8 Eco đời 2025 tại Việt Nam có tầm 450 km WLTP."
    right = "VF9 Eco đời 2025 tại Việt Nam có tầm 480 km WLTP."
    shadow = analyze_text_relation(left, right, domain_scope_mode="shadow")
    enforced = analyze_text_relation(left, right, domain_scope_mode="on")

    assert shadow.domain_scope_decision["mode"] == "shadow"
    assert shadow.domain_scope_decision["disposition"] == "distinct_entity"
    assert enforced.relation_type is not RelationType.CONFLICT_CANDIDATE
    assert enforced.domain_scope_decision["allows_conflict_analysis"] is False


def test_vehicle_table_uses_the_same_business_scope_contract() -> None:
    table = ParsedTable(
        table_id="vehicle-table",
        location="page-1",
        rows=[
            ["Mẫu xe", "Biến thể", "Chu trình", "Tầm hoạt động"],
            ["VF 8", "Eco", "WLTP", "450 km"],
        ],
        columns=4,
        header=["Mẫu xe", "Biến thể", "Chu trình", "Tầm hoạt động"],
        confidence=1.0,
    )

    analysis = analyze_table(document_id="doc-vf8", table=table)

    assert len(analysis.claims) == 1
    claim = analysis.claims[0]
    prose = resolve_business_context("VF 8 Eco cÃ³ pháº¡m vi 480 km theo WLTP.")
    assert claim.predicate == "vehicle_range"
    assert claim.scope.vehicle.model == "vinfast_vf8"
    assert claim.scope.vehicle.trim == "eco"
    assert claim.scope.vehicle.test_protocol == "WLTP"
    assert claim.scope.entities[0].canonical_id == "vinfast_vf8"
    assert claim.scope.entities[0].evidence[0].source is EntityEvidenceSource.TABLE_CELL
    assert compare_business_scopes(claim.scope, prose.business_scope) is ScopeRelation.SAME


def test_scope_gate_cannot_enable_embedding_reuse() -> None:
    decision = decide_conflict_admission(
        resolve_business_context("VF8 Eco đời 2025 tại Việt Nam tầm 450 km WLTP."),
        resolve_business_context("VF8 Eco đời 2025 tại Việt Nam tầm 480 km WLTP."),
    )

    assert decision.allows_conflict_analysis is True
    assert "reuse" not in decision.to_payload()
