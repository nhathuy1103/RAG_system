"""Linear row/claim diff for deterministic structured-table analyses."""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation

from app.structured_facts.application.scope import (
    compare_business_scopes,
    compare_qualifiers,
    compare_temporal_intervals,
)
from app.structured_facts.application.table_analyzer import (
    MIN_TRUSTED_CLAIM_CONFIDENCE,
    TableAnalysis,
)
from app.structured_facts.domain.models import (
    ClaimRelation,
    ClaimRelationType,
    NormalizedValue,
    QualifierCompatibility,
    ScopeRelation,
    StructuredClaim,
    TemporalRelation,
)


@dataclass(frozen=True, slots=True)
class TableDiff:
    """Claim-level relations and deterministic document-pair summary."""

    relations: tuple[ClaimRelation, ...]
    summary_counts: dict[str, int]
    source_document_id: str
    target_document_id: str

    @property
    def summary(self) -> dict[str, int]:
        return dict(self.summary_counts)

    def to_payload(self) -> dict[str, object]:
        return {
            "source_document_id": self.source_document_id,
            "target_document_id": self.target_document_id,
            "summary_counts": dict(sorted(self.summary_counts.items())),
            "relations": [relation.to_payload() for relation in self.relations],
        }


def diff_table_analyses(left: TableAnalysis, right: TableAnalysis) -> TableDiff:
    """Diff every claim in two analyses in expected ``O(n + m)`` time.

    Matching first uses row identity plus predicate, then exact stable
    qualifiers.  No cross-product or vector search is performed.  Ambiguous
    duplicate keys are surfaced as ``uncertain`` instead of being paired by
    row position.
    """

    left_groups = _group_by_subject_predicate(left.claims)
    right_groups = _group_by_subject_predicate(right.claims)
    relations: list[ClaimRelation] = []

    ordered_keys = list(left_groups)
    ordered_keys.extend(key for key in right_groups if key not in left_groups)
    for base_key in ordered_keys:
        left_claims = left_groups.get(base_key, ())
        right_claims = right_groups.get(base_key, ())
        if not left_claims:
            relations.extend(_one_sided_relation(None, claim) for claim in right_claims)
            continue
        if not right_claims:
            relations.extend(_one_sided_relation(claim, None) for claim in left_claims)
            continue
        relations.extend(_diff_claim_group(left_claims, right_claims))

    summary = {relation_type.value: 0 for relation_type in ClaimRelationType}
    for relation in relations:
        summary[relation.relation_type.value] += 1
    return TableDiff(
        relations=tuple(relations),
        summary_counts=summary,
        source_document_id=left.document_id,
        target_document_id=right.document_id,
    )


def _group_by_subject_predicate(
    claims: tuple[StructuredClaim, ...],
) -> dict[tuple[str, str], tuple[StructuredClaim, ...]]:
    groups: dict[tuple[str, str], list[StructuredClaim]] = defaultdict(list)
    for claim in claims:
        groups[(claim.subject_key, claim.predicate)].append(claim)
    return {key: tuple(values) for key, values in groups.items()}


def _diff_claim_group(
    left_claims: tuple[StructuredClaim, ...],
    right_claims: tuple[StructuredClaim, ...],
) -> list[ClaimRelation]:
    left_by_qualifier = _group_by_stable_qualifier(left_claims)
    right_by_qualifier = _group_by_stable_qualifier(right_claims)
    relations: list[ClaimRelation] = []
    unmatched_left: list[StructuredClaim] = []
    unmatched_right: list[StructuredClaim] = []

    qualifier_keys = list(left_by_qualifier)
    qualifier_keys.extend(key for key in right_by_qualifier if key not in left_by_qualifier)
    for qualifier_key in qualifier_keys:
        left_matches = left_by_qualifier.get(qualifier_key, ())
        right_matches = right_by_qualifier.get(qualifier_key, ())
        if len(left_matches) == 1 and len(right_matches) == 1:
            relations.append(_compare_claim_pair(left_matches[0], right_matches[0]))
            continue
        if left_matches and right_matches:
            # Duplicate business keys are never safe to zip by physical row.
            relations.extend(_ambiguous_duplicate_relations(left_matches, right_matches))
            continue
        unmatched_left.extend(left_matches)
        unmatched_right.extend(right_matches)

    # One remaining claim on each side is an intentional qualifier variant.
    # Larger sets are not paired heuristically because that would reintroduce
    # an O(n*m) join and could invent conflicts.
    if len(unmatched_left) == 1 and len(unmatched_right) == 1:
        relations.append(_compare_claim_pair(unmatched_left[0], unmatched_right[0]))
    else:
        relations.extend(_one_sided_relation(claim, None) for claim in unmatched_left)
        relations.extend(_one_sided_relation(None, claim) for claim in unmatched_right)
    return relations


def _group_by_stable_qualifier(
    claims: tuple[StructuredClaim, ...],
) -> dict[object, tuple[StructuredClaim, ...]]:
    groups: dict[object, list[StructuredClaim]] = defaultdict(list)
    for claim in claims:
        groups[claim.qualifiers.stable_identity()].append(claim)
    return {key: tuple(values) for key, values in groups.items()}


def _compare_claim_pair(left: StructuredClaim, right: StructuredClaim) -> ClaimRelation:
    scope_relation = compare_business_scopes(left.scope, right.scope)
    qualifier_compatibility = compare_qualifiers(left.qualifiers, right.qualifiers)
    temporal_relation = compare_temporal_intervals(left.temporal, right.temporal)
    confidence = min(left.extraction_confidence, right.extraction_confidence)
    values_equal = _values_equivalent(left, right)

    if confidence < MIN_TRUSTED_CLAIM_CONFIDENCE:
        return _relation(
            ClaimRelationType.UNCERTAIN,
            left,
            right,
            confidence=confidence,
            reason_codes=("low_extraction_confidence",),
            scope_relation=scope_relation,
            qualifier_compatibility=qualifier_compatibility,
            temporal_relation=temporal_relation,
        )
    if scope_relation is ScopeRelation.DISJOINT:
        return _relation(
            ClaimRelationType.CONDITIONAL_VARIANT,
            left,
            right,
            confidence=confidence,
            reason_codes=("disjoint_business_scope",),
            scope_relation=scope_relation,
            qualifier_compatibility=qualifier_compatibility,
            temporal_relation=temporal_relation,
        )
    if scope_relation is ScopeRelation.UNKNOWN:
        return _relation(
            ClaimRelationType.UNCERTAIN,
            left,
            right,
            confidence=confidence,
            reason_codes=("unknown_business_scope",),
            scope_relation=scope_relation,
            qualifier_compatibility=qualifier_compatibility,
            temporal_relation=temporal_relation,
        )
    if qualifier_compatibility is QualifierCompatibility.DISJOINT:
        return _relation(
            ClaimRelationType.CONDITIONAL_VARIANT,
            left,
            right,
            confidence=confidence,
            reason_codes=("disjoint_claim_qualifiers",),
            scope_relation=scope_relation,
            qualifier_compatibility=qualifier_compatibility,
            temporal_relation=temporal_relation,
        )
    if qualifier_compatibility is QualifierCompatibility.UNKNOWN:
        return _relation(
            ClaimRelationType.UNCERTAIN,
            left,
            right,
            confidence=confidence,
            reason_codes=("unknown_claim_qualifiers",),
            scope_relation=scope_relation,
            qualifier_compatibility=qualifier_compatibility,
            temporal_relation=temporal_relation,
        )

    dimension_reason = _incompatible_value_dimension(left.value, right.value)
    if dimension_reason is not None:
        return _relation(
            (
                ClaimRelationType.UNCERTAIN
                if dimension_reason.startswith("unknown_")
                else ClaimRelationType.CONDITIONAL_VARIANT
            ),
            left,
            right,
            confidence=confidence,
            reason_codes=(dimension_reason,),
            scope_relation=scope_relation,
            qualifier_compatibility=qualifier_compatibility,
            temporal_relation=temporal_relation,
        )
    if values_equal:
        return _relation(
            ClaimRelationType.UNCHANGED,
            left,
            right,
            confidence=confidence,
            reason_codes=("equivalent_normalized_value",),
            scope_relation=scope_relation,
            qualifier_compatibility=qualifier_compatibility,
            temporal_relation=temporal_relation,
        )
    if temporal_relation in {TemporalRelation.BEFORE, TemporalRelation.AFTER}:
        return _relation(
            ClaimRelationType.UPDATED,
            left,
            right,
            confidence=confidence,
            reason_codes=("non_overlapping_effective_intervals",),
            scope_relation=scope_relation,
            qualifier_compatibility=qualifier_compatibility,
            temporal_relation=temporal_relation,
        )
    if temporal_relation is TemporalRelation.UNKNOWN:
        return _relation(
            ClaimRelationType.UNCERTAIN,
            left,
            right,
            confidence=confidence,
            reason_codes=("unknown_effective_interval",),
            scope_relation=scope_relation,
            qualifier_compatibility=qualifier_compatibility,
            temporal_relation=temporal_relation,
        )
    return _relation(
        ClaimRelationType.CONFLICT_CANDIDATE,
        left,
        right,
        confidence=confidence,
        reason_codes=("overlapping_effective_value_mismatch",),
        scope_relation=scope_relation,
        qualifier_compatibility=qualifier_compatibility,
        temporal_relation=temporal_relation,
    )


def _one_sided_relation(
    left: StructuredClaim | None,
    right: StructuredClaim | None,
) -> ClaimRelation:
    claim = left or right
    if claim is None:
        raise ValueError("one-sided relation requires one claim")
    low_confidence = claim.extraction_confidence < MIN_TRUSTED_CLAIM_CONFIDENCE
    relation_type = (
        ClaimRelationType.UNCERTAIN
        if low_confidence
        else ClaimRelationType.REMOVED
        if left is not None
        else ClaimRelationType.ADDED
    )
    reason = (
        "low_extraction_confidence"
        if low_confidence
        else "claim_missing_from_target"
        if left is not None
        else "claim_new_in_target"
    )
    return ClaimRelation(
        relation_type=relation_type,
        source_claim_id=left.id if left is not None else None,
        target_claim_id=right.id if right is not None else None,
        subject_key=claim.subject_key,
        predicate=claim.predicate,
        confidence=claim.extraction_confidence,
        reason_codes=(reason,),
    )


def _ambiguous_duplicate_relations(
    left_claims: tuple[StructuredClaim, ...],
    right_claims: tuple[StructuredClaim, ...],
) -> list[ClaimRelation]:
    # A repeated key gives us no evidence that the first source row represents
    # the first target row (and so on).  Preserve every claim independently;
    # setting only its known side makes the missing identity explicit instead
    # of manufacturing a pair from physical row order.
    return [
        *(_ambiguous_one_sided_relation(claim, source_side=True) for claim in left_claims),
        *(_ambiguous_one_sided_relation(claim, source_side=False) for claim in right_claims),
    ]


def _ambiguous_one_sided_relation(
    claim: StructuredClaim,
    *,
    source_side: bool,
) -> ClaimRelation:
    return ClaimRelation(
        relation_type=ClaimRelationType.UNCERTAIN,
        source_claim_id=claim.id if source_side else None,
        target_claim_id=None if source_side else claim.id,
        subject_key=claim.subject_key,
        predicate=claim.predicate,
        confidence=claim.extraction_confidence,
        reason_codes=("duplicate_business_key",),
    )


def _relation(
    relation_type: ClaimRelationType,
    left: StructuredClaim,
    right: StructuredClaim,
    *,
    confidence: float,
    reason_codes: tuple[str, ...],
    scope_relation: ScopeRelation,
    qualifier_compatibility: QualifierCompatibility,
    temporal_relation: TemporalRelation,
) -> ClaimRelation:
    return ClaimRelation(
        relation_type=relation_type,
        source_claim_id=left.id,
        target_claim_id=right.id,
        subject_key=left.subject_key,
        predicate=left.predicate,
        confidence=confidence,
        reason_codes=reason_codes,
        scope_relation=scope_relation,
        qualifier_compatibility=qualifier_compatibility,
        temporal_relation=temporal_relation,
    )


def _values_equivalent(left: StructuredClaim, right: StructuredClaim) -> bool:
    if _incompatible_value_dimension(left.value, right.value) is not None:
        return False
    if left.value.stable_identity() == right.value.stable_identity():
        return True
    left_number = _decimal(left.value.value)
    right_number = _decimal(right.value.value)
    if left_number is None or right_number is None:
        return False
    absolute_tolerance = max(
        _derivation_decimal(left, "absolute_tolerance"),
        _derivation_decimal(right, "absolute_tolerance"),
    )
    relative_tolerance = max(
        _derivation_decimal(left, "relative_tolerance"),
        _derivation_decimal(right, "relative_tolerance"),
    )
    allowed_difference = max(
        absolute_tolerance,
        max(abs(left_number), abs(right_number)) * relative_tolerance,
    )
    return abs(left_number - right_number) <= allowed_difference


def _incompatible_value_dimension(left: NormalizedValue, right: NormalizedValue) -> str | None:
    for field_name, reason in (
        ("unit", "incompatible_value_unit"),
        ("currency", "incompatible_currency"),
        ("basis", "incompatible_value_basis"),
    ):
        left_value = getattr(left, field_name)
        right_value = getattr(right, field_name)
        if (left_value is None) != (right_value is None):
            return f"unknown_{field_name}"
        if left_value is not None and right_value is not None and left_value != right_value:
            return reason
    return None


def _derivation_decimal(claim: StructuredClaim, field_name: str) -> Decimal:
    if claim.derivation is None:
        return Decimal("0")
    return _decimal(getattr(claim.derivation, field_name)) or Decimal("0")


def _decimal(value: object) -> Decimal | None:
    if value is None:
        return None
    try:
        return Decimal(str(value))
    except InvalidOperation:
        return None


__all__ = ["TableDiff", "diff_table_analyses"]
