"""Conservative scope, qualifier, and temporal comparison policies."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum

from app.structured_facts.domain.models import (
    BusinessScope,
    ClaimQualifiers,
    ConstraintValue,
    QualifierCompatibility,
    ScopeRelation,
    TemporalContext,
    TemporalPoint,
    TemporalRelation,
    _business_scope_items,
    _constraint_atoms,
    _temporal_sort_key,
)


class _ConstraintRelation(StrEnum):
    SAME = "same"
    LEFT_CONTAINS_RIGHT = "left_contains_right"
    RIGHT_CONTAINS_LEFT = "right_contains_left"
    OVERLAPS = "overlaps"
    DISJOINT = "disjoint"
    LEFT_ONLY = "left_only"
    RIGHT_ONLY = "right_only"
    EMPTY = "empty"


@dataclass(frozen=True, slots=True)
class ScopeComparisonResult:
    relation: ScopeRelation
    matching_dimensions: tuple[str, ...] = ()
    left_broader_dimensions: tuple[str, ...] = ()
    right_broader_dimensions: tuple[str, ...] = ()
    overlapping_dimensions: tuple[str, ...] = ()
    conflicting_dimensions: tuple[str, ...] = ()

    def to_payload(self) -> dict[str, object]:
        return {
            "relation": self.relation.value,
            "matching_dimensions": list(self.matching_dimensions),
            "left_broader_dimensions": list(self.left_broader_dimensions),
            "right_broader_dimensions": list(self.right_broader_dimensions),
            "overlapping_dimensions": list(self.overlapping_dimensions),
            "conflicting_dimensions": list(self.conflicting_dimensions),
        }


@dataclass(frozen=True, slots=True)
class QualifierComparisonResult:
    compatibility: QualifierCompatibility
    equal_keys: tuple[str, ...] = ()
    compatible_keys: tuple[str, ...] = ()
    conflicting_keys: tuple[str, ...] = ()
    unknown_keys: tuple[str, ...] = ()

    def to_payload(self) -> dict[str, object]:
        return {
            "compatibility": self.compatibility.value,
            "equal_keys": list(self.equal_keys),
            "compatible_keys": list(self.compatible_keys),
            "conflicting_keys": list(self.conflicting_keys),
            "unknown_keys": list(self.unknown_keys),
        }


def compare_business_scopes(left: BusinessScope, right: BusinessScope) -> ScopeRelation:
    """Return the directional set relation between two facet-based scopes."""
    return explain_business_scope_relation(left, right).relation


def explain_business_scope_relation(
    left: BusinessScope,
    right: BusinessScope,
) -> ScopeComparisonResult:
    """Compare business facets while deliberately ignoring document type."""
    left_values = dict(_business_scope_items(left))
    right_values = dict(_business_scope_items(right))
    matching: list[str] = []
    left_broader: list[str] = []
    right_broader: list[str] = []
    overlapping: list[str] = []
    conflicting: list[str] = []
    explicit_shared_dimension = False

    for name in left_values:
        left_value = left_values[name]
        right_value = right_values[name]
        if left_value is not None and right_value is not None:
            explicit_shared_dimension = True
        dimension_relation = _compare_constraints(left_value, right_value)
        if dimension_relation is _ConstraintRelation.SAME:
            matching.append(name)
        elif dimension_relation in {
            _ConstraintRelation.LEFT_CONTAINS_RIGHT,
            _ConstraintRelation.RIGHT_ONLY,
        }:
            left_broader.append(name)
        elif dimension_relation in {
            _ConstraintRelation.RIGHT_CONTAINS_LEFT,
            _ConstraintRelation.LEFT_ONLY,
        }:
            right_broader.append(name)
        elif dimension_relation is _ConstraintRelation.OVERLAPS:
            overlapping.append(name)
        elif dimension_relation is _ConstraintRelation.DISJOINT:
            conflicting.append(name)

    if conflicting:
        overall_relation = ScopeRelation.DISJOINT
    elif not explicit_shared_dimension:
        # Missing constraints are unknown evidence, not proof of a global wildcard.
        overall_relation = ScopeRelation.UNKNOWN
    elif overlapping or (left_broader and right_broader):
        overall_relation = ScopeRelation.OVERLAPS
    elif left_broader:
        overall_relation = ScopeRelation.LEFT_CONTAINS_RIGHT
    elif right_broader:
        overall_relation = ScopeRelation.RIGHT_CONTAINS_LEFT
    else:
        overall_relation = ScopeRelation.SAME

    return ScopeComparisonResult(
        relation=overall_relation,
        matching_dimensions=tuple(matching),
        left_broader_dimensions=tuple(left_broader),
        right_broader_dimensions=tuple(right_broader),
        overlapping_dimensions=tuple(overlapping),
        conflicting_dimensions=tuple(conflicting),
    )


def compare_qualifiers(
    left: ClaimQualifiers,
    right: ClaimQualifiers,
) -> QualifierCompatibility:
    """Return field-level qualifier compatibility for claim comparison."""
    return explain_qualifier_compatibility(left, right).compatibility


def explain_qualifier_compatibility(
    left: ClaimQualifiers,
    right: ClaimQualifiers,
) -> QualifierComparisonResult:
    """Compare stable and optional qualifiers without folding them into one hash."""
    left_stable = dict(left.stable)
    right_stable = dict(right.stable)
    left_optional = dict(left.optional)
    right_optional = dict(right.optional)
    equal: list[str] = []
    compatible: list[str] = []
    conflicting: list[str] = []
    unknown: list[str] = []

    keys = set(left_stable) | set(right_stable) | set(left_optional) | set(right_optional)
    for key in sorted(keys):
        left_category = (
            "stable" if key in left_stable else "optional" if key in left_optional else None
        )
        right_category = (
            "stable" if key in right_stable else "optional" if key in right_optional else None
        )
        if left_category is None or right_category is None or left_category != right_category:
            unknown.append(key)
            continue
        relation = _compare_constraints(
            (left_stable if left_category == "stable" else left_optional)[key],
            (right_stable if right_category == "stable" else right_optional)[key],
        )
        if relation is _ConstraintRelation.SAME:
            equal.append(key)
        elif relation is _ConstraintRelation.DISJOINT:
            conflicting.append(key)
        elif relation in {
            _ConstraintRelation.LEFT_CONTAINS_RIGHT,
            _ConstraintRelation.RIGHT_CONTAINS_LEFT,
            _ConstraintRelation.OVERLAPS,
        }:
            compatible.append(key)
        else:
            unknown.append(key)

    if conflicting:
        result = QualifierCompatibility.DISJOINT
    elif unknown:
        result = QualifierCompatibility.UNKNOWN
    elif compatible:
        result = QualifierCompatibility.COMPATIBLE
    else:
        result = QualifierCompatibility.EQUAL
    return QualifierComparisonResult(
        compatibility=result,
        equal_keys=tuple(equal),
        compatible_keys=tuple(compatible),
        conflicting_keys=tuple(conflicting),
        unknown_keys=tuple(unknown),
    )


def compare_temporal_intervals(
    left: TemporalContext,
    right: TemporalContext,
) -> TemporalRelation:
    """Compare effective intervals; publication/ingestion never imply validity."""
    if not left.has_effective_interval or not right.has_effective_interval:
        return TemporalRelation.UNKNOWN

    left_start = _bound(left.effective_from, lower=True)
    left_end = _bound(left.effective_to, lower=False)
    right_start = _bound(right.effective_from, lower=True)
    right_end = _bound(right.effective_to, lower=False)

    if left_end < right_start:
        return TemporalRelation.BEFORE
    if left_start > right_end:
        return TemporalRelation.AFTER
    if left_start == right_start and left_end == right_end:
        return TemporalRelation.SAME
    if left_start <= right_start and left_end >= right_end:
        return TemporalRelation.LEFT_CONTAINS_RIGHT
    if right_start <= left_start and right_end >= left_end:
        return TemporalRelation.RIGHT_CONTAINS_LEFT
    return TemporalRelation.OVERLAPS


def _compare_constraints(
    left: ConstraintValue | None,
    right: ConstraintValue | None,
) -> _ConstraintRelation:
    if left is None and right is None:
        return _ConstraintRelation.EMPTY
    if left is None:
        return _ConstraintRelation.RIGHT_ONLY
    if right is None:
        return _ConstraintRelation.LEFT_ONLY
    left_values = frozenset(_constraint_atoms(left))
    right_values = frozenset(_constraint_atoms(right))
    if left_values == right_values:
        return _ConstraintRelation.SAME
    intersection = left_values & right_values
    if not intersection:
        return _ConstraintRelation.DISJOINT
    if left_values > right_values:
        return _ConstraintRelation.LEFT_CONTAINS_RIGHT
    if right_values > left_values:
        return _ConstraintRelation.RIGHT_CONTAINS_LEFT
    return _ConstraintRelation.OVERLAPS


def _bound(value: TemporalPoint | None, *, lower: bool) -> datetime:
    if value is None:
        return datetime.min if lower else datetime.max
    return _temporal_sort_key(value)


__all__ = [
    "QualifierComparisonResult",
    "ScopeComparisonResult",
    "compare_business_scopes",
    "compare_qualifiers",
    "compare_temporal_intervals",
    "explain_business_scope_relation",
    "explain_qualifier_compatibility",
]
