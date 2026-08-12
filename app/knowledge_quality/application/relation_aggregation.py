"""P4 claim-evidence aggregation into final document/chunk relations."""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from typing import cast
from uuid import UUID

from app.knowledge_quality.application.authority_policy import (
    AuthorityPolicy,
    select_preferred_evidence,
)
from app.knowledge_quality.application.version_lineage import determine_version_direction
from app.knowledge_quality.domain.models import (
    QualityRelationCandidate,
    RelationStatus,
    RelationType,
)
from app.knowledge_quality.domain.relation_models import (
    AGGREGATION_POLICY_VERSION,
    ClaimConflictEvidence,
    DocumentRelationContext,
    FinalRelationType,
    RelationEvidenceSummary,
    RelationFacets,
    VersionDirection,
)
from app.knowledge_quality.domain.scope_models import (
    ConflictAdmissionDecision,
    ConflictAdmissionDisposition,
)
from app.structured_facts.application.claim_alignment import ClaimAlignmentResult
from app.structured_facts.domain.models import (
    ClaimRelation,
    ClaimRelationType,
    StructuredClaim,
    TemporalRelation,
)


@dataclass(frozen=True, slots=True)
class AggregationPolicy:
    """Small DEV-tunable surface frozen before P4 TEST."""

    near_duplicate_min_source_coverage: float = 0.8
    near_duplicate_min_target_coverage: float = 0.8
    template_similarity_threshold: float = 0.94
    minimum_claim_confidence: float = 0.75
    version: str = AGGREGATION_POLICY_VERSION

    def __post_init__(self) -> None:
        for name in (
            "near_duplicate_min_source_coverage",
            "near_duplicate_min_target_coverage",
            "template_similarity_threshold",
            "minimum_claim_confidence",
        ):
            value = getattr(self, name)
            if not 0 <= value <= 1:
                raise ValueError(f"{name} must be between 0 and 1")


_PRODUCTION_RELATION_MAPPING = {
    FinalRelationType.EXACT_DUPLICATE: RelationType.EXACT_CONTENT,
    FinalRelationType.NEAR_DUPLICATE: RelationType.NEAR_DUPLICATE,
    FinalRelationType.VERSION_UPDATE: RelationType.VERSION,
    FinalRelationType.TEMPORAL_VARIANT: RelationType.TEMPORAL_SERIES,
    FinalRelationType.CONDITIONAL_VARIANT: RelationType.RELATED,
    FinalRelationType.TEMPLATE_VARIANT: RelationType.TEMPLATE_VARIANT,
    FinalRelationType.CONFLICT: RelationType.CONFLICT,
    FinalRelationType.DISTINCT: RelationType.DISTINCT,
    FinalRelationType.UNCERTAIN: RelationType.RELATED,
}


def aggregate_claim_evidence(
    *,
    source: DocumentRelationContext,
    target: DocumentRelationContext,
    source_claims: tuple[StructuredClaim, ...],
    target_claims: tuple[StructuredClaim, ...],
    alignment: ClaimAlignmentResult,
    scope_decision: ConflictAdmissionDecision,
    template_similarity: float = 0.0,
    technical_duplicate: bool = False,
    policy: AggregationPolicy | None = None,
    authority_policy: AuthorityPolicy | None = None,
) -> RelationEvidenceSummary:
    """Aggregate P3 output in one pass without repeating claim alignment."""
    active_policy = policy or AggregationPolicy()
    _validate_pair_scope(source, target)
    if not 0 <= template_similarity <= 1:
        raise ValueError("template_similarity must be between 0 and 1")
    if alignment.claims_left != len(source_claims) or alignment.claims_right != len(target_claims):
        raise ValueError("alignment claim counts do not match aggregation input")

    relations = alignment.relations
    counts = Counter(relation.relation_type for relation in relations)
    aligned_count = sum(
        relation.source_claim_id is not None and relation.target_claim_id is not None
        for relation in relations
    )
    source_coverage = aligned_count / len(source_claims) if source_claims else 0.0
    target_coverage = aligned_count / len(target_claims) if target_claims else 0.0
    exact_identity = bool(
        source.strict_content_hash
        and source.strict_content_hash == target.strict_content_hash
        and source.normalization_version
        and source.normalization_version == target.normalization_version
    )
    change_count = (
        counts[ClaimRelationType.UPDATED]
        + counts[ClaimRelationType.ADDED]
        + counts[ClaimRelationType.REMOVED]
    )
    anchor_count = counts[ClaimRelationType.UNCHANGED]
    direction = VersionDirection.NOT_APPLICABLE
    direction_reasons: tuple[str, ...] = ()
    if change_count:
        direction, direction_reasons = determine_version_direction(source, target)
    version_continuity = bool(
        source.document_family_id
        and source.document_family_id == target.document_family_id
        and direction is not VersionDirection.UNKNOWN
    )
    primary, decision_reasons = _decide_primary_relation(
        exact_identity=exact_identity,
        counts=counts,
        source_coverage=source_coverage,
        target_coverage=target_coverage,
        scope_decision=scope_decision,
        template_similarity=template_similarity,
        policy=active_policy,
        aligned_count=aligned_count,
        version_continuity=version_continuity,
    )
    has_temporal = (
        scope_decision.disposition is ConflictAdmissionDisposition.TEMPORAL_VARIANT
        or any(
            relation.temporal_relation in {TemporalRelation.BEFORE, TemporalRelation.AFTER}
            for relation in relations
        )
    )
    has_version_changes = bool(
        change_count
        and scope_decision.disposition is not ConflictAdmissionDisposition.DISTINCT_ENTITY
        and (anchor_count or aligned_count or version_continuity)
    )
    facets = RelationFacets(
        has_conflict=counts[ClaimRelationType.CONFLICT_CANDIDATE] > 0,
        has_version_changes=has_version_changes,
        has_added_claims=counts[ClaimRelationType.ADDED] > 0,
        has_removed_claims=counts[ClaimRelationType.REMOVED] > 0,
        has_updated_claims=counts[ClaimRelationType.UPDATED] > 0,
        has_conditional_variants=counts[ClaimRelationType.CONDITIONAL_VARIANT] > 0,
        has_temporal_variants=has_temporal,
        has_uncertain_evidence=(
            counts[ClaimRelationType.UNCERTAIN] > 0
            or scope_decision.disposition is ConflictAdmissionDisposition.UNCERTAIN
        ),
        is_technical_duplicate=technical_duplicate or exact_identity,
    )
    if not facets.has_version_changes:
        direction = VersionDirection.NOT_APPLICABLE
        direction_reasons = ()
    preference = select_preferred_evidence(
        source,
        target,
        relation=primary,
        version_direction=direction,
        policy=authority_policy,
    )
    source_by_id = _claims_by_id(source_claims)
    target_by_id = _claims_by_id(target_claims)
    conflicts = tuple(
        _conflict_evidence(relation, source_by_id, target_by_id)
        for relation in relations
        if relation.relation_type is ClaimRelationType.CONFLICT_CANDIDATE
    )
    confidence = _relation_confidence(primary, relations, exact_identity=exact_identity)
    review_status = _review_status(
        primary,
        direction=direction,
        confidence=confidence,
        minimum_confidence=active_policy.minimum_claim_confidence,
    )
    reason_codes = tuple(
        dict.fromkeys(
            (
                *decision_reasons,
                *direction_reasons,
                *scope_decision.reason_codes,
            )
        )
    )
    return RelationEvidenceSummary(
        source_document_id=source.document_id,
        target_document_id=target.document_id,
        owner_id=source.owner_id,
        notebook_id=source.notebook_id,
        primary_relation=primary,
        claim_relations=relations,
        source_claim_count=len(source_claims),
        target_claim_count=len(target_claims),
        aligned_claim_count=aligned_count,
        unchanged_count=counts[ClaimRelationType.UNCHANGED],
        updated_count=counts[ClaimRelationType.UPDATED],
        added_count=counts[ClaimRelationType.ADDED],
        removed_count=counts[ClaimRelationType.REMOVED],
        conditional_count=counts[ClaimRelationType.CONDITIONAL_VARIANT],
        conflict_count=counts[ClaimRelationType.CONFLICT_CANDIDATE],
        uncertain_count=counts[ClaimRelationType.UNCERTAIN],
        source_coverage=source_coverage,
        target_coverage=target_coverage,
        facets=facets,
        confidence=confidence,
        reason_codes=reason_codes,
        conflict_claims=conflicts,
        unchanged_predicates=_predicates(relations, ClaimRelationType.UNCHANGED),
        updated_predicates=_predicates(relations, ClaimRelationType.UPDATED),
        added_predicates=_predicates(relations, ClaimRelationType.ADDED),
        removed_predicates=_predicates(relations, ClaimRelationType.REMOVED),
        conflicting_predicates=_predicates(relations, ClaimRelationType.CONFLICT_CANDIDATE),
        same_periods=_periods(
            relations,
            source_by_id,
            target_by_id,
            relation_type=ClaimRelationType.UNCHANGED,
        ),
        conflicting_periods=_periods(
            relations,
            source_by_id,
            target_by_id,
            relation_type=ClaimRelationType.CONFLICT_CANDIDATE,
        ),
        version_direction=direction,
        preferred_document_id=preference.preferred_document_id,
        preference_reason=preference.reason,
        review_status=review_status,
        aggregation_version=active_policy.version,
        authority_policy_version=preference.policy_version,
        claim_extractor_versions=tuple(
            sorted({claim.extractor_version for claim in (*source_claims, *target_claims)})
        ),
    )


def to_quality_relation_candidate(
    summary: RelationEvidenceSummary,
) -> QualityRelationCandidate:
    """Persist P4 through the existing quality-relation JSONB infrastructure."""
    return QualityRelationCandidate(
        target_document_id=UUID(summary.target_document_id),
        relation_type=_PRODUCTION_RELATION_MAPPING[summary.primary_relation],
        confidence=summary.confidence,
        signals=summary.to_signals(),
        reason=";".join(summary.reason_codes) or None,
        detector_version=summary.aggregation_version,
    )


def production_relation_for(relation: FinalRelationType) -> RelationType:
    return _PRODUCTION_RELATION_MAPPING[relation]


def _decide_primary_relation(
    *,
    exact_identity: bool,
    counts: Counter[ClaimRelationType],
    source_coverage: float,
    target_coverage: float,
    scope_decision: ConflictAdmissionDecision,
    template_similarity: float,
    policy: AggregationPolicy,
    aligned_count: int,
    version_continuity: bool,
) -> tuple[FinalRelationType, tuple[str, ...]]:
    if exact_identity:
        return FinalRelationType.EXACT_DUPLICATE, ("strict_exact_content",)
    if scope_decision.disposition is ConflictAdmissionDisposition.DISTINCT_ENTITY:
        if template_similarity >= policy.template_similarity_threshold:
            return FinalRelationType.TEMPLATE_VARIANT, (
                "template_overlap_without_business_identity",
            )
        return FinalRelationType.DISTINCT, ("distinct_business_entity",)
    if counts[ClaimRelationType.CONFLICT_CANDIDATE]:
        return FinalRelationType.CONFLICT, ("overlapping_value_conflict",)
    if scope_decision.disposition is ConflictAdmissionDisposition.TEMPORAL_VARIANT:
        return FinalRelationType.TEMPORAL_VARIANT, ("non_overlapping_reference_periods",)
    if (
        scope_decision.disposition is ConflictAdmissionDisposition.CONDITIONAL_VARIANT
        or counts[ClaimRelationType.CONDITIONAL_VARIANT]
    ):
        return FinalRelationType.CONDITIONAL_VARIANT, ("disjoint_business_conditions",)
    change_count = (
        counts[ClaimRelationType.UPDATED]
        + counts[ClaimRelationType.ADDED]
        + counts[ClaimRelationType.REMOVED]
    )
    anchor_count = counts[ClaimRelationType.UNCHANGED]
    if change_count and (anchor_count or aligned_count or version_continuity):
        return FinalRelationType.VERSION_UPDATE, ("claim_change_with_business_continuity",)
    if (
        scope_decision.disposition is ConflictAdmissionDisposition.UNCERTAIN
        or counts[ClaimRelationType.UNCERTAIN]
    ):
        return FinalRelationType.UNCERTAIN, ("insufficient_safe_aggregation_evidence",)
    if (
        aligned_count
        and counts[ClaimRelationType.UNCHANGED] == aligned_count
        and source_coverage >= policy.near_duplicate_min_source_coverage
        and target_coverage >= policy.near_duplicate_min_target_coverage
    ):
        return FinalRelationType.NEAR_DUPLICATE, ("high_symmetric_claim_coverage",)
    if aligned_count == 0:
        if change_count:
            return FinalRelationType.UNCERTAIN, (
                "one_sided_claims_without_version_continuity",
            )
        return FinalRelationType.DISTINCT, ("no_comparable_business_claims",)
    return FinalRelationType.UNCERTAIN, ("insufficient_claim_coverage",)


def _validate_pair_scope(
    source: DocumentRelationContext,
    target: DocumentRelationContext,
) -> None:
    if source.document_id == target.document_id:
        raise ValueError("cannot aggregate a document against itself")
    if source.owner_id != target.owner_id:
        raise PermissionError("cross-owner relation aggregation is forbidden")
    if source.notebook_id != target.notebook_id:
        raise PermissionError("cross-notebook relation aggregation is forbidden")


def _claims_by_id(claims: tuple[StructuredClaim, ...]) -> dict[str, StructuredClaim]:
    return {claim.id or claim.claim_identity_hash: claim for claim in claims}


def _conflict_evidence(
    relation: ClaimRelation,
    source_by_id: dict[str, StructuredClaim],
    target_by_id: dict[str, StructuredClaim],
) -> ClaimConflictEvidence:
    source_claim = source_by_id.get(relation.source_claim_id or "")
    target_claim = target_by_id.get(relation.target_claim_id or "")
    return ClaimConflictEvidence(
        predicate=relation.predicate,
        source_claim_id=relation.source_claim_id,
        target_claim_id=relation.target_claim_id,
        source_value=(
            source_claim.value_expression.to_payload()
            if source_claim is not None and source_claim.value_expression is not None
            else None
        ),
        target_value=(
            target_claim.value_expression.to_payload()
            if target_claim is not None and target_claim.value_expression is not None
            else None
        ),
        confidence=relation.confidence,
        reason_codes=relation.reason_codes,
    )


def _predicates(
    relations: tuple[ClaimRelation, ...], relation_type: ClaimRelationType
) -> tuple[str, ...]:
    return tuple(
        sorted(
            {
                relation.predicate
                for relation in relations
                if relation.relation_type is relation_type
            }
        )
    )


def _periods(
    relations: tuple[ClaimRelation, ...],
    source_by_id: dict[str, StructuredClaim],
    target_by_id: dict[str, StructuredClaim],
    *,
    relation_type: ClaimRelationType,
) -> tuple[str, ...]:
    values: set[str] = set()
    for relation in relations:
        if relation.relation_type is not relation_type:
            continue
        for claim_id, index in (
            (relation.source_claim_id, source_by_id),
            (relation.target_claim_id, target_by_id),
        ):
            claim = index.get(claim_id or "")
            if claim is not None:
                if claim.temporal.reference_period:
                    values.add(claim.temporal.reference_period)
                values.update(claim.temporal.claim_periods)
    return tuple(sorted(values))


def _relation_confidence(
    primary: FinalRelationType,
    relations: tuple[ClaimRelation, ...],
    *,
    exact_identity: bool,
) -> float:
    if exact_identity:
        return 1.0
    relevant = [relation.confidence for relation in relations]
    if not relevant:
        return (
            0.9
            if primary in {FinalRelationType.DISTINCT, FinalRelationType.TEMPLATE_VARIANT}
            else 0.5
        )
    return cast(float, round(min(relevant), 6))


def _review_status(
    relation: FinalRelationType,
    *,
    direction: VersionDirection,
    confidence: float,
    minimum_confidence: float,
) -> RelationStatus:
    """Keep unsafe or ambiguous outcomes in the existing human review queue."""
    if relation in {FinalRelationType.CONFLICT, FinalRelationType.UNCERTAIN}:
        return RelationStatus.PENDING
    if confidence < minimum_confidence:
        return RelationStatus.PENDING
    if relation is FinalRelationType.VERSION_UPDATE and direction is VersionDirection.UNKNOWN:
        return RelationStatus.PENDING
    return RelationStatus.AUTO_CONFIRMED


__all__ = [
    "AggregationPolicy",
    "aggregate_claim_evidence",
    "production_relation_for",
    "to_quality_relation_candidate",
]
