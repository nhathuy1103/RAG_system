"""Fail-closed P2 gate in front of existing value-conflict analysis."""

from __future__ import annotations

from app.knowledge_quality.domain.scope_models import (
    ConflictAdmissionDecision,
    ConflictAdmissionDisposition,
    ResolvedBusinessContext,
)
from app.structured_facts.application.scope import (
    compare_temporal_intervals,
    explain_business_scope_relation,
    explain_qualifier_compatibility,
)
from app.structured_facts.domain.models import (
    QualifierCompatibility,
    ScopeRelation,
    TemporalRelation,
)

_COMPARABLE_SCOPE_RELATIONS = {
    ScopeRelation.SAME,
    ScopeRelation.LEFT_CONTAINS_RIGHT,
    ScopeRelation.RIGHT_CONTAINS_LEFT,
    ScopeRelation.OVERLAPS,
}
_COMPARABLE_TEMPORAL_RELATIONS = {
    TemporalRelation.SAME,
    TemporalRelation.LEFT_CONTAINS_RIGHT,
    TemporalRelation.RIGHT_CONTAINS_LEFT,
    TemporalRelation.OVERLAPS,
}


def decide_conflict_admission(
    left: ResolvedBusinessContext,
    right: ResolvedBusinessContext,
    *,
    legacy_scope: str | None = None,
) -> ConflictAdmissionDecision:
    """Allow value analysis only after all P2 comparability gates pass."""
    left_entity = left.primary_entity
    right_entity = right.primary_entity
    scope_explanation = explain_business_scope_relation(
        left.business_scope,
        right.business_scope,
    )
    scope_relation = scope_explanation.relation
    qualifier_explanation = explain_qualifier_compatibility(
        left.qualifiers,
        right.qualifiers,
    )
    qualifier_compatibility = qualifier_explanation.compatibility
    temporal_relation = compare_temporal_intervals(left.temporal, right.temporal)

    if left_entity is None or right_entity is None:
        return _decision(
            ConflictAdmissionDisposition.UNCERTAIN,
            False,
            None,
            scope_relation,
            qualifier_compatibility,
            temporal_relation,
            ("unknown_primary_entity",),
            legacy_scope,
        )
    if left_entity.canonical_id != right_entity.canonical_id:
        return _decision(
            ConflictAdmissionDisposition.DISTINCT_ENTITY,
            False,
            False,
            ScopeRelation.DISJOINT,
            qualifier_compatibility,
            temporal_relation,
            (
                "different_canonical_entity",
                f"left_entity:{left_entity.canonical_id}",
                f"right_entity:{right_entity.canonical_id}",
            ),
            legacy_scope,
        )
    if left.predicate == "unknown" or right.predicate == "unknown":
        return _decision(
            ConflictAdmissionDisposition.UNCERTAIN,
            False,
            True,
            scope_relation,
            qualifier_compatibility,
            temporal_relation,
            ("unknown_claim_predicate",),
            legacy_scope,
        )
    if left.predicate != right.predicate:
        return _decision(
            ConflictAdmissionDisposition.UNCERTAIN,
            False,
            True,
            scope_relation,
            qualifier_compatibility,
            temporal_relation,
            ("different_claim_predicate",),
            legacy_scope,
        )
    if temporal_relation in {TemporalRelation.BEFORE, TemporalRelation.AFTER}:
        return _decision(
            ConflictAdmissionDisposition.TEMPORAL_VARIANT,
            False,
            True,
            scope_relation,
            qualifier_compatibility,
            temporal_relation,
            ("non_overlapping_temporal_scope",),
            legacy_scope,
        )
    if scope_relation is ScopeRelation.DISJOINT:
        reasons = tuple(
            ["disjoint_business_scope"]
            + [
                f"different_{item.replace('.', '_')}"
                for item in scope_explanation.conflicting_dimensions
            ]
        )
        return _decision(
            ConflictAdmissionDisposition.CONDITIONAL_VARIANT,
            False,
            True,
            scope_relation,
            qualifier_compatibility,
            temporal_relation,
            reasons,
            legacy_scope,
        )
    if scope_relation is ScopeRelation.UNKNOWN:
        reasons = tuple(
            ["unknown_required_business_scope"]
            + [f"unknown_{item.replace('.', '_')}" for item in scope_explanation.unknown_dimensions]
        )
        return _decision(
            ConflictAdmissionDisposition.UNCERTAIN,
            False,
            True,
            scope_relation,
            qualifier_compatibility,
            temporal_relation,
            reasons,
            legacy_scope,
        )
    if qualifier_compatibility is QualifierCompatibility.DISJOINT:
        return _decision(
            ConflictAdmissionDisposition.CONDITIONAL_VARIANT,
            False,
            True,
            scope_relation,
            qualifier_compatibility,
            temporal_relation,
            tuple(
                ["disjoint_claim_qualifiers"]
                + [f"different_qualifier:{item}" for item in qualifier_explanation.conflicting_keys]
            ),
            legacy_scope,
        )
    if qualifier_compatibility is QualifierCompatibility.UNKNOWN:
        if not _unknown_qualifiers_are_explicit_breadth(
            qualifier_explanation.unknown_keys,
            left,
            right,
        ):
            return _decision(
                ConflictAdmissionDisposition.UNCERTAIN,
                False,
                True,
                scope_relation,
                qualifier_compatibility,
                temporal_relation,
                tuple(
                    ["unknown_required_qualifiers"]
                    + [f"unknown_qualifier:{item}" for item in qualifier_explanation.unknown_keys]
                ),
                legacy_scope,
            )
        qualifier_compatibility = QualifierCompatibility.COMPATIBLE
    if temporal_relation is TemporalRelation.UNKNOWN:
        return _decision(
            ConflictAdmissionDisposition.UNCERTAIN,
            False,
            True,
            scope_relation,
            qualifier_compatibility,
            temporal_relation,
            ("unknown_temporal_applicability",),
            legacy_scope,
        )
    if scope_relation not in _COMPARABLE_SCOPE_RELATIONS or (
        temporal_relation not in _COMPARABLE_TEMPORAL_RELATIONS
    ):
        return _decision(
            ConflictAdmissionDisposition.UNCERTAIN,
            False,
            True,
            scope_relation,
            qualifier_compatibility,
            temporal_relation,
            ("unsupported_scope_relation",),
            legacy_scope,
        )
    return _decision(
        ConflictAdmissionDisposition.ADMIT,
        True,
        True,
        scope_relation,
        qualifier_compatibility,
        temporal_relation,
        ("entity_scope_qualifier_time_comparable",),
        legacy_scope,
    )


def _unknown_qualifiers_are_explicit_breadth(
    keys: tuple[str, ...],
    left: ResolvedBusinessContext,
    right: ResolvedBusinessContext,
) -> bool:
    if not keys:
        return False
    breadth = set(left.business_scope.explicit_breadth) | set(right.business_scope.explicit_breadth)
    return set(keys) <= breadth


def _decision(
    disposition: ConflictAdmissionDisposition,
    allows: bool,
    entity_compatible: bool | None,
    scope_relation: ScopeRelation,
    qualifier_compatibility: QualifierCompatibility,
    temporal_relation: TemporalRelation,
    reason_codes: tuple[str, ...],
    legacy_scope: str | None,
) -> ConflictAdmissionDecision:
    return ConflictAdmissionDecision(
        disposition=disposition,
        allows_conflict_analysis=allows,
        entity_compatible=entity_compatible,
        scope_relation=scope_relation,
        qualifier_compatibility=qualifier_compatibility,
        temporal_relation=temporal_relation,
        reason_codes=reason_codes,
        legacy_scope=legacy_scope,
    )


__all__ = ["decide_conflict_admission"]
