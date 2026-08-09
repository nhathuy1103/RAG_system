"""Contract tests for business scope, qualifiers, and effective time."""

from datetime import date, datetime

import pytest

from app.structured_facts.application.scope import (
    compare_business_scopes,
    compare_qualifiers,
    compare_temporal_intervals,
    explain_business_scope_relation,
)
from app.structured_facts.domain.models import (
    BusinessScope,
    ClaimQualifiers,
    CommercialScope,
    LocationScope,
    ProductScope,
    QualifierCompatibility,
    ScopeRelation,
    TemporalContext,
    TemporalRelation,
)


def test_different_buildings_in_same_project_are_disjoint() -> None:
    left = BusinessScope(location=LocationScope(project="Ocean Park", building="S1"))
    right = BusinessScope(location=LocationScope(project="Ocean Park", building="S2"))

    result = explain_business_scope_relation(left, right)

    assert result.relation is ScopeRelation.DISJOINT
    assert result.conflicting_dimensions == ("location.building",)


def test_scope_relation_is_directional_for_broad_and_narrow_scope() -> None:
    project = BusinessScope(location=LocationScope(project="Ocean Park"))
    building = BusinessScope(location=LocationScope(project="ocean park", building="S1"))

    assert compare_business_scopes(project, building) is ScopeRelation.LEFT_CONTAINS_RIGHT
    assert compare_business_scopes(building, project) is ScopeRelation.RIGHT_CONTAINS_LEFT


def test_orthogonal_constraints_with_shared_anchor_overlap() -> None:
    left = BusinessScope(
        location=LocationScope(project="Ocean Park", building="S1"),
    )
    right = BusinessScope(
        location=LocationScope(project="Ocean Park"),
        product=ProductScope(bedrooms=2),
    )

    assert compare_business_scopes(left, right) is ScopeRelation.OVERLAPS


def test_partially_overlapping_allowed_values_are_scope_overlap() -> None:
    left = BusinessScope(location=LocationScope(project="Ocean Park", building=("S1", "S2")))
    right = BusinessScope(location=LocationScope(project="Ocean Park", building=("S2", "S3")))

    assert compare_business_scopes(left, right) is ScopeRelation.OVERLAPS


def test_unanchored_or_empty_scopes_are_unknown() -> None:
    assert (
        compare_business_scopes(
            BusinessScope(location=LocationScope(project="Ocean Park")),
            BusinessScope(product=ProductScope(bedrooms=2)),
        )
        is ScopeRelation.UNKNOWN
    )
    assert compare_business_scopes(BusinessScope(), BusinessScope()) is ScopeRelation.UNKNOWN


def test_document_type_neither_defines_nor_splits_business_scope() -> None:
    only_type_left = BusinessScope(document_type="price_list")
    only_type_right = BusinessScope(document_type="policy")
    assert compare_business_scopes(only_type_left, only_type_right) is ScopeRelation.UNKNOWN

    same_project_left = BusinessScope(
        location=LocationScope(project="Ocean Park"),
        document_type="price_list",
    )
    same_project_right = BusinessScope(
        location=LocationScope(project="Ocean Park"),
        document_type="policy",
    )
    assert compare_business_scopes(same_project_left, same_project_right) is ScopeRelation.SAME
    assert same_project_left.scope_identity_hash == same_project_right.scope_identity_hash


def test_optional_qualifiers_do_not_change_stable_candidate_identity() -> None:
    left = ClaimQualifiers.from_mappings(
        stable={"price_type": "list_price"},
        optional={"vat_included": True},
    )
    right = ClaimQualifiers.from_mappings(
        stable={"price_type": "list_price"},
        optional={"vat_included": False},
    )

    assert left.stable_identity_hash == right.stable_identity_hash
    assert compare_qualifiers(left, right) is QualifierCompatibility.DISJOINT


def test_missing_optional_qualifier_is_unknown_not_equal() -> None:
    known_vat = ClaimQualifiers.from_mappings(
        stable={"price_type": "list_price"},
        optional={"vat_included": True},
    )
    unspecified_vat = ClaimQualifiers.from_mappings(stable={"price_type": "list_price"})

    assert compare_qualifiers(known_vat, unspecified_vat) is QualifierCompatibility.UNKNOWN


def test_overlapping_allowed_qualifier_values_are_compatible() -> None:
    left = ClaimQualifiers.from_mappings(
        stable={"price_type": "list_price"},
        optional={"payment_plan": ("standard", "early")},
    )
    right = ClaimQualifiers.from_mappings(
        stable={"price_type": "list_price"},
        optional={"payment_plan": ("early", "balloon")},
    )

    assert compare_qualifiers(left, right) is QualifierCompatibility.COMPATIBLE


def test_equal_qualifiers_are_order_and_case_insensitive() -> None:
    left = ClaimQualifiers.from_mappings(
        stable={"Price Type": "LIST_PRICE"},
        optional={"payment_plan": ("EARLY", "standard")},
    )
    right = ClaimQualifiers.from_mappings(
        stable={"price_type": "list_price"},
        optional={"payment_plan": ("standard", "early")},
    )

    assert compare_qualifiers(left, right) is QualifierCompatibility.EQUAL


def test_temporal_context_keeps_distinct_timestamps_and_serializes_iso() -> None:
    context = TemporalContext(
        publication_time=datetime(2026, 2, 25, 9, 30),
        effective_from=date(2026, 3, 1),
        effective_to=date(2026, 3, 31),
        observed_at=datetime(2026, 3, 2, 8, 0),
        ingested_at=datetime(2026, 3, 2, 8, 5),
    )

    assert context.to_payload() == {
        "publication_time": "2026-02-25T09:30:00",
        "effective_from": "2026-03-01",
        "effective_to": "2026-03-31",
        "observed_at": "2026-03-02T08:00:00",
        "ingested_at": "2026-03-02T08:05:00",
    }


@pytest.mark.parametrize(
    ("left", "right", "expected"),
    (
        (
            TemporalContext(effective_from=date(2026, 3, 1), effective_to=date(2026, 3, 31)),
            TemporalContext(effective_from=date(2026, 3, 1), effective_to=date(2026, 3, 31)),
            TemporalRelation.SAME,
        ),
        (
            TemporalContext(effective_from=date(2026, 3, 1), effective_to=date(2026, 3, 31)),
            TemporalContext(effective_from=date(2026, 3, 10), effective_to=date(2026, 3, 20)),
            TemporalRelation.LEFT_CONTAINS_RIGHT,
        ),
        (
            TemporalContext(effective_from=date(2026, 2, 1), effective_to=date(2026, 2, 28)),
            TemporalContext(effective_from=date(2026, 3, 1), effective_to=date(2026, 3, 31)),
            TemporalRelation.BEFORE,
        ),
        (
            TemporalContext(effective_from=date(2026, 3, 1), effective_to=date(2026, 3, 20)),
            TemporalContext(effective_from=date(2026, 3, 10), effective_to=date(2026, 3, 31)),
            TemporalRelation.OVERLAPS,
        ),
        (TemporalContext(), TemporalContext(), TemporalRelation.UNKNOWN),
    ),
)
def test_effective_interval_relations(
    left: TemporalContext,
    right: TemporalContext,
    expected: TemporalRelation,
) -> None:
    assert compare_temporal_intervals(left, right) is expected


def test_publication_time_does_not_imply_effective_time() -> None:
    left = TemporalContext(publication_time=date(2026, 2, 1))
    right = TemporalContext(publication_time=date(2026, 3, 1))

    assert compare_temporal_intervals(left, right) is TemporalRelation.UNKNOWN


def test_invalid_effective_interval_is_rejected() -> None:
    with pytest.raises(ValueError, match="effective_from"):
        TemporalContext(effective_from=date(2026, 4, 1), effective_to=date(2026, 3, 1))


def test_commercial_facets_are_real_scope_constraints() -> None:
    left = BusinessScope(
        location=LocationScope(project="Ocean Park", unit="A101"),
        commercial=CommercialScope(price_type="list_price"),
    )
    right = BusinessScope(
        location=LocationScope(project="Ocean Park", unit="A101"),
        commercial=CommercialScope(price_type="discounted_price"),
    )

    assert compare_business_scopes(left, right) is ScopeRelation.DISJOINT
