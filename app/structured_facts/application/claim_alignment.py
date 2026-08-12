"""Precision-first O(n+m) alignment and relation decisions for P3 claims."""

from __future__ import annotations

from collections import Counter, defaultdict
from dataclasses import dataclass

from app.structured_facts.application.scope import (
    compare_business_scopes,
    compare_qualifiers,
    compare_temporal_intervals,
)
from app.structured_facts.application.value_normalization import compare_value_expressions
from app.structured_facts.domain.models import (
    ClaimRelation,
    ClaimRelationType,
    QualifierCompatibility,
    ScopeRelation,
    StructuredClaim,
    TemporalRelation,
    ValueExpressionRelation,
)

CLAIM_ALIGNMENT_VERSION = "p3-claim-alignment-v1"
DEFAULT_CONFLICT_CONFIDENCE_FLOOR = 0.75
MAX_AMBIGUOUS_GROUP_SIZE = 8

type CoarseKey = tuple[str, str]


@dataclass(frozen=True, slots=True)
class ClaimAlignmentResult:
    relations: tuple[ClaimRelation, ...]
    claims_left: int
    claims_right: int
    aligned_claim_count: int
    version: str = CLAIM_ALIGNMENT_VERSION

    @property
    def relation_counts(self) -> dict[str, int]:
        counts = Counter(relation.relation_type.value for relation in self.relations)
        return {relation.value: counts[relation.value] for relation in ClaimRelationType}

    def to_payload(self) -> dict[str, object]:
        return {
            "version": self.version,
            "claims_left": self.claims_left,
            "claims_right": self.claims_right,
            "aligned_claim_count": self.aligned_claim_count,
            **{f"{key}_claim_count": value for key, value in self.relation_counts.items()},
            "relations": [relation.to_payload() for relation in self.relations],
        }


def align_claims(
    left_claims: tuple[StructuredClaim, ...],
    right_claims: tuple[StructuredClaim, ...],
    *,
    conflict_confidence_floor: float = DEFAULT_CONFLICT_CONFIDENCE_FLOOR,
    max_ambiguous_group_size: int = MAX_AMBIGUOUS_GROUP_SIZE,
    p2_scope_admitted: bool = False,
) -> ClaimAlignmentResult:
    """Hash/group by value-free identity and bound ambiguous local work."""
    if not 0 <= conflict_confidence_floor <= 1:
        raise ValueError("conflict_confidence_floor must be between 0 and 1")
    if max_ambiguous_group_size < 1:
        raise ValueError("max_ambiguous_group_size must be positive")
    left_groups = _coarse_groups(left_claims)
    right_groups = _coarse_groups(right_claims)
    relations: list[ClaimRelation] = []
    aligned = 0

    for key in sorted(left_groups.keys() | right_groups.keys()):
        left_group = list(left_groups.get(key, ()))
        right_group = list(right_groups.get(key, ()))
        if not left_group:
            relations.extend(_unmatched_relation(claim, added=True) for claim in right_group)
            continue
        if not right_group:
            relations.extend(_unmatched_relation(claim, added=False) for claim in left_group)
            continue

        exact_left = _identity_groups(left_group)
        exact_right = _identity_groups(right_group)
        consumed_left: set[int] = set()
        consumed_right: set[int] = set()
        for identity in exact_left.keys() & exact_right.keys():
            left_indexes = exact_left[identity]
            right_indexes = exact_right[identity]
            if len(left_indexes) == len(right_indexes) == 1:
                left_index, right_index = left_indexes[0], right_indexes[0]
                relations.append(
                    compare_aligned_claims(
                        left_group[left_index],
                        right_group[right_index],
                        conflict_confidence_floor=conflict_confidence_floor,
                        p2_scope_admitted=p2_scope_admitted,
                    )
                )
                consumed_left.add(left_index)
                consumed_right.add(right_index)
                aligned += 1

        remaining_left = [
            claim for index, claim in enumerate(left_group) if index not in consumed_left
        ]
        remaining_right = [
            claim for index, claim in enumerate(right_group) if index not in consumed_right
        ]
        if len(remaining_left) == len(remaining_right) == 1:
            relations.append(
                compare_aligned_claims(
                    remaining_left[0],
                    remaining_right[0],
                    conflict_confidence_floor=conflict_confidence_floor,
                    p2_scope_admitted=p2_scope_admitted,
                )
            )
            aligned += 1
        elif remaining_left or remaining_right:
            total = len(remaining_left) + len(remaining_right)
            reason = (
                "ambiguous_duplicate_comparable_key"
                if total <= max_ambiguous_group_size
                else "ambiguous_group_cap_exceeded"
            )
            relations.extend(
                _uncertain_unpaired(claim, source=True, reason=reason) for claim in remaining_left
            )
            relations.extend(
                _uncertain_unpaired(claim, source=False, reason=reason) for claim in remaining_right
            )

    return ClaimAlignmentResult(
        relations=tuple(relations),
        claims_left=len(left_claims),
        claims_right=len(right_claims),
        aligned_claim_count=aligned,
    )


def compare_aligned_claims(
    left: StructuredClaim,
    right: StructuredClaim,
    *,
    conflict_confidence_floor: float = DEFAULT_CONFLICT_CONFIDENCE_FLOOR,
    p2_scope_admitted: bool = False,
) -> ClaimRelation:
    """Classify one subject/predicate-aligned pair without document aggregation."""
    confidence = min(left.extraction_confidence, right.extraction_confidence)
    if left.subject_key != right.subject_key or left.predicate != right.predicate:
        return _relation(
            ClaimRelationType.UNCERTAIN,
            left,
            right,
            confidence,
            ("non_comparable_subject_or_predicate",),
        )
    scope_relation = compare_business_scopes(left.scope, right.scope)
    qualifier_relation = compare_qualifiers(left.qualifiers, right.qualifiers)
    temporal_relation = compare_temporal_intervals(left.temporal, right.temporal)

    if (
        scope_relation is ScopeRelation.DISJOINT
        or qualifier_relation is QualifierCompatibility.DISJOINT
    ):
        return _relation(
            ClaimRelationType.CONDITIONAL_VARIANT,
            left,
            right,
            confidence,
            ("p2_scope_or_qualifier_disjoint",),
            scope_relation,
            qualifier_relation,
            temporal_relation,
        )
    if (
        scope_relation is ScopeRelation.UNKNOWN
        or qualifier_relation is QualifierCompatibility.UNKNOWN
    ) and not p2_scope_admitted:
        return _relation(
            ClaimRelationType.UNCERTAIN,
            left,
            right,
            confidence,
            ("unknown_required_scope_or_qualifier",),
            scope_relation,
            qualifier_relation,
            temporal_relation,
        )
    if temporal_relation in {TemporalRelation.BEFORE, TemporalRelation.AFTER}:
        return _relation(
            ClaimRelationType.UPDATED,
            left,
            right,
            confidence,
            ("non_overlapping_effective_progression",),
            scope_relation,
            qualifier_relation,
            temporal_relation,
        )
    if temporal_relation is TemporalRelation.UNKNOWN:
        return _relation(
            ClaimRelationType.UNCERTAIN,
            left,
            right,
            confidence,
            ("unknown_temporal_applicability",),
            scope_relation,
            qualifier_relation,
            temporal_relation,
        )
    left_expression = left.value_expression
    right_expression = right.value_expression
    if left_expression is None or right_expression is None:  # pragma: no cover - model invariant
        raise RuntimeError("StructuredClaim value expression invariant was violated")
    value_relation = compare_value_expressions(
        left_expression,
        right_expression,
        predicate=left.predicate,
    )
    reasons: tuple[str, ...]
    if value_relation is ValueExpressionRelation.EQUIVALENT:
        relation_type = ClaimRelationType.UNCHANGED
        reasons = ("equivalent_value_expression",)
    elif value_relation is ValueExpressionRelation.COMPATIBLE:
        relation_type = ClaimRelationType.CONDITIONAL_VARIANT
        reasons = ("overlapping_value_expressions",)
    elif value_relation is ValueExpressionRelation.INCOMPATIBLE_DIMENSION:
        relation_type = ClaimRelationType.CONDITIONAL_VARIANT
        reasons = ("incompatible_value_dimension",)
    elif (
        value_relation is ValueExpressionRelation.UNKNOWN or confidence < conflict_confidence_floor
    ):
        relation_type = ClaimRelationType.UNCERTAIN
        reasons = (
            "unknown_value_relation"
            if value_relation is ValueExpressionRelation.UNKNOWN
            else "low_extraction_confidence",
        )
    else:
        relation_type = ClaimRelationType.CONFLICT_CANDIDATE
        reasons = ("disjoint_value_expressions",)
    if p2_scope_admitted and (
        scope_relation is ScopeRelation.UNKNOWN
        or qualifier_relation is QualifierCompatibility.UNKNOWN
    ):
        reasons = (*reasons, "authoritative_p2_admission")
    return _relation(
        relation_type,
        left,
        right,
        confidence,
        reasons,
        scope_relation,
        qualifier_relation,
        temporal_relation,
    )


def _coarse_groups(
    claims: tuple[StructuredClaim, ...],
) -> dict[CoarseKey, tuple[StructuredClaim, ...]]:
    grouped: dict[CoarseKey, list[StructuredClaim]] = defaultdict(list)
    for claim in claims:
        grouped[(claim.subject_key, claim.predicate)].append(claim)
    return {key: tuple(value) for key, value in grouped.items()}


def _identity_groups(claims: list[StructuredClaim]) -> dict[str, list[int]]:
    grouped: dict[str, list[int]] = defaultdict(list)
    for index, claim in enumerate(claims):
        grouped[claim.candidate_identity_hash].append(index)
    return grouped


def _unmatched_relation(claim: StructuredClaim, *, added: bool) -> ClaimRelation:
    return ClaimRelation(
        relation_type=ClaimRelationType.ADDED if added else ClaimRelationType.REMOVED,
        source_claim_id=None if added else claim.id,
        target_claim_id=claim.id if added else None,
        subject_key=claim.subject_key,
        predicate=claim.predicate,
        confidence=claim.extraction_confidence,
        reason_codes=("unmatched_comparable_key",),
    )


def _uncertain_unpaired(
    claim: StructuredClaim,
    *,
    source: bool,
    reason: str,
) -> ClaimRelation:
    return ClaimRelation(
        relation_type=ClaimRelationType.UNCERTAIN,
        source_claim_id=claim.id if source else None,
        target_claim_id=None if source else claim.id,
        subject_key=claim.subject_key,
        predicate=claim.predicate,
        confidence=claim.extraction_confidence,
        reason_codes=(reason,),
    )


def _relation(
    relation_type: ClaimRelationType,
    left: StructuredClaim,
    right: StructuredClaim,
    confidence: float,
    reasons: tuple[str, ...],
    scope_relation: ScopeRelation | None = None,
    qualifier_relation: QualifierCompatibility | None = None,
    temporal_relation: TemporalRelation | None = None,
) -> ClaimRelation:
    return ClaimRelation(
        relation_type=relation_type,
        source_claim_id=left.id,
        target_claim_id=right.id,
        subject_key=left.subject_key,
        predicate=left.predicate,
        confidence=confidence,
        reason_codes=reasons,
        scope_relation=scope_relation,
        qualifier_compatibility=qualifier_relation,
        temporal_relation=temporal_relation,
    )


__all__ = [
    "CLAIM_ALIGNMENT_VERSION",
    "DEFAULT_CONFLICT_CONFIDENCE_FLOOR",
    "MAX_AMBIGUOUS_GROUP_SIZE",
    "ClaimAlignmentResult",
    "align_claims",
    "compare_aligned_claims",
]
