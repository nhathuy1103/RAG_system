from __future__ import annotations

from dataclasses import replace

from app.structured_facts.application.claim_alignment import align_claims
from app.structured_facts.application.claim_extraction import extract_structured_claims
from app.structured_facts.domain.models import ClaimRelationType


def _claims(text: str, document_id: str):  # type: ignore[no-untyped-def]
    return extract_structured_claims(text, document_id=document_id).claims


def test_same_claim_same_value_and_changed_value_align() -> None:
    left = _claims("VF 8 Eco đời 2025 tại Việt Nam có tầm hoạt động 450 km theo WLTP.", "left")
    same = _claims(
        "Tầm hoạt động của VF 8 Eco đời 2025 tại Việt Nam là 450000 m theo WLTP.", "same"
    )
    changed = _claims(
        "VF 8 Eco đời 2025 tại Việt Nam có tầm hoạt động 480 km theo WLTP.", "changed"
    )

    assert align_claims(left, same).relations[0].relation_type is ClaimRelationType.UNCHANGED
    assert (
        align_claims(left, changed).relations[0].relation_type
        is ClaimRelationType.CONFLICT_CANDIDATE
    )


def test_same_value_different_predicate_or_entity_never_aligns() -> None:
    range_claim = _claims(
        "VF 8 Eco đời 2025 tại Việt Nam có tầm hoạt động 450 km theo WLTP.", "range"
    )
    other_entity = _claims(
        "VF 9 Eco đời 2025 tại Việt Nam có tầm hoạt động 450 km theo WLTP.", "entity"
    )
    different_predicate = tuple(
        replace(claim, predicate="vehicle_dimensions") for claim in range_claim
    )

    entity_result = align_claims(range_claim, other_entity)
    predicate_result = align_claims(range_claim, different_predicate)
    assert entity_result.aligned_claim_count == 0
    assert predicate_result.aligned_claim_count == 0
    assert {item.relation_type for item in entity_result.relations} == {
        ClaimRelationType.ADDED,
        ClaimRelationType.REMOVED,
    }


def test_reordered_claims_and_added_removed_claims() -> None:
    base = _claims(
        "Giá căn 2PN tại Vinhomes Project Alpha năm 2026 là 6,2 tỷ đồng/căn; diện tích là 70 m².",
        "base",
    )
    extended = _claims(
        "Diện tích căn 2PN tại Vinhomes Project Alpha năm 2026 là 70 m²; "
        "phí quản lý 20.000 đồng/m²/tháng; giá căn là 6,2 tỷ đồng/căn.",
        "extended",
    )

    result = align_claims(base, extended)
    assert result.aligned_claim_count == 2
    assert result.relation_counts["unchanged"] == 2
    assert result.relation_counts["added"] == 1
    reverse = align_claims(extended, base)
    assert reverse.relation_counts["removed"] == 1


def test_p2_disjoint_protocol_is_conditional_not_conflict() -> None:
    wltp = _claims("VF 8 Eco đời 2025 tại Việt Nam có tầm hoạt động 450 km theo WLTP.", "wltp")
    epa = _claims("VF 8 Eco đời 2025 tại Việt Nam có tầm hoạt động 420 km theo EPA.", "epa")

    relation = align_claims(wltp, epa).relations[0]
    assert relation.relation_type is ClaimRelationType.CONDITIONAL_VARIANT


def test_duplicate_comparable_key_is_uncertain_not_zipped() -> None:
    one = _claims("Giá căn studio tại Vinhomes Project Alpha năm 2026 là 6,2 tỷ đồng/căn.", "one")[
        0
    ]
    duplicate = replace(one, id="duplicate", provenance=replace(one.provenance, source_span=(1, 2)))

    result = align_claims((one, duplicate), (one,))

    assert result.aligned_claim_count == 0
    assert all(item.relation_type is ClaimRelationType.UNCERTAIN for item in result.relations)


def test_low_confidence_ocr_value_cannot_trigger_conflict() -> None:
    clean = _claims("VF 8 Eco đời 2025 tại Việt Nam có tầm hoạt động 450 km theo WLTP.", "clean")
    corrupted = _claims("VF 8 Eco đời 2025 tại Việt Nam có tầm hoạt động 45O km theo WLTP.", "ocr")

    assert align_claims(clean, corrupted).relations[0].relation_type is ClaimRelationType.UNCERTAIN


def test_multi_period_partial_conflict_stays_claim_local() -> None:
    left = _claims(
        "Vinhomes Project Alpha – studio:\n2024: 5 tỷ/căn\n2025: 6 tỷ/căn\n2026: 7 tỷ/căn",
        "period-left",
    )
    right = _claims(
        "Vinhomes Project Alpha – studio:\n2024: 5 tỷ/căn\n2025: 6 tỷ/căn\n2026: 8 tỷ/căn",
        "period-right",
    )

    result = align_claims(left, right)

    assert result.aligned_claim_count == 3
    assert result.relation_counts["unchanged"] == 2
    assert result.relation_counts["conflict_candidate"] == 1
    relation_by_period = {
        left_claim.temporal.reference_period: next(
            relation for relation in result.relations if relation.source_claim_id == left_claim.id
        )
        for left_claim in left
    }
    assert relation_by_period["2024"].relation_type is ClaimRelationType.UNCHANGED
    assert relation_by_period["2025"].relation_type is ClaimRelationType.UNCHANGED
    assert relation_by_period["2026"].relation_type is ClaimRelationType.CONFLICT_CANDIDATE


def test_changed_one_of_many_claims_does_not_conflict_the_whole_chunk() -> None:
    left = _claims(
        "VF 8 Eco đời 2025 tại Việt Nam có tầm hoạt động 450 km theo WLTP; "
        "dung lượng pin 87,7 kWh; thời gian sạc 31 phút.",
        "many-left",
    )
    right = _claims(
        "VF 8 Eco đời 2025 tại Việt Nam có tầm hoạt động 480 km theo WLTP; "
        "dung lượng pin 87,7 kWh; thời gian sạc 31 phút.",
        "many-right",
    )

    result = align_claims(left, right)

    assert result.aligned_claim_count == 3
    assert result.relation_counts["conflict_candidate"] == 1
    assert result.relation_counts["unchanged"] == 2
