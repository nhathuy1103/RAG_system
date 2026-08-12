from __future__ import annotations

from dataclasses import replace
from datetime import date
from decimal import Decimal

import pytest

from app.knowledge_quality.application.relation_aggregation import (
    aggregate_claim_evidence,
    to_quality_relation_candidate,
)
from app.knowledge_quality.application.relation_clusters import (
    RelationClusterType,
    build_relation_clusters,
)
from app.knowledge_quality.application.version_lineage import (
    VersionLineageEdge,
    build_version_lineage,
    determine_version_direction,
    lineage_has_cycle,
)
from app.knowledge_quality.domain.relation_models import (
    DocumentRelationContext,
    FinalRelationType,
    VersionDirection,
)
from app.knowledge_quality.domain.scope_models import (
    ConflictAdmissionDecision,
    ConflictAdmissionDisposition,
)
from app.structured_facts.application.claim_alignment import align_claims
from app.structured_facts.application.claim_extraction import extract_structured_claims
from app.structured_facts.domain.models import (
    ClaimProvenance,
    NormalizedValue,
    QualifierCompatibility,
    ScopeRelation,
    SourceAuthority,
    StructuredClaim,
    TemporalContext,
    TemporalRelation,
)


def _claims(text: str, document_id: str):  # type: ignore[no-untyped-def]
    return extract_structured_claims(text, document_id=document_id).claims


def _claim(
    document_id: str,
    claim_id: str,
    predicate: str,
    value: str,
) -> StructuredClaim:
    return StructuredClaim(
        id=claim_id,
        document_id=document_id,
        subject_key="business-entity",
        predicate=predicate,
        value=NormalizedValue(value=Decimal(value), unit="unit"),
        provenance=ClaimProvenance(document_id=document_id),
        temporal=TemporalContext(
            effective_from=date(2026, 1, 1),
            effective_to=date(2026, 12, 31),
            reference_period="2026",
        ),
        extractor_version="test-v1",
    )


def _context(
    document_id: str,
    *,
    content_hash: str | None = None,
    owner_id: str = "owner",
    notebook_id: str = "notebook",
    family: str | None = "family",
    version: int | None = None,
    effective: date | None = None,
    authority: int | None = None,
    normalization_version: str = "strict-v1",
) -> DocumentRelationContext:
    return DocumentRelationContext(
        document_id=document_id,
        owner_id=owner_id,
        notebook_id=notebook_id,
        strict_content_hash=content_hash,
        normalization_version=normalization_version if content_hash else None,
        document_family_id=family,
        version_number=version,
        temporal=TemporalContext(effective_from=effective),
        authority=SourceAuthority(authority_level=authority),
    )


def _decision(disposition: ConflictAdmissionDisposition) -> ConflictAdmissionDecision:
    return ConflictAdmissionDecision(
        disposition=disposition,
        allows_conflict_analysis=disposition is ConflictAdmissionDisposition.ADMIT,
        entity_compatible=disposition is not ConflictAdmissionDisposition.DISTINCT_ENTITY,
        scope_relation=(
            ScopeRelation.DISJOINT
            if disposition
            in {
                ConflictAdmissionDisposition.DISTINCT_ENTITY,
                ConflictAdmissionDisposition.CONDITIONAL_VARIANT,
            }
            else ScopeRelation.SAME
        ),
        qualifier_compatibility=(
            QualifierCompatibility.DISJOINT
            if disposition is ConflictAdmissionDisposition.CONDITIONAL_VARIANT
            else QualifierCompatibility.EQUAL
        ),
        temporal_relation=(
            TemporalRelation.BEFORE
            if disposition is ConflictAdmissionDisposition.TEMPORAL_VARIANT
            else TemporalRelation.SAME
        ),
        reason_codes=(disposition.value,),
    )


def _aggregate(  # type: ignore[no-untyped-def]
    left,
    right,
    *,
    decision: ConflictAdmissionDisposition = ConflictAdmissionDisposition.ADMIT,
    source: DocumentRelationContext | None = None,
    target: DocumentRelationContext | None = None,
    template_similarity: float = 0.0,
):
    p2 = _decision(decision)
    alignment = align_claims(left, right, p2_scope_admitted=p2.allows_conflict_analysis)
    return aggregate_claim_evidence(
        source=source or _context("source"),
        target=target or _context("target"),
        source_claims=left,
        target_claims=right,
        alignment=alignment,
        scope_decision=p2,
        template_similarity=template_similarity,
    )


def test_strict_exact_identity_is_not_inferred_from_claim_equivalence() -> None:
    left = (_claim("source", "left-range", "driving_range", "450"),)
    right = (_claim("target", "right-range", "driving_range", "450"),)

    near = _aggregate(left, right)
    exact = _aggregate(
        left,
        right,
        source=_context("source", content_hash="same"),
        target=_context("target", content_hash="same"),
    )

    assert near.primary_relation is FinalRelationType.NEAR_DUPLICATE
    assert exact.primary_relation is FinalRelationType.EXACT_DUPLICATE
    assert exact.facets.is_technical_duplicate


def test_exact_identity_requires_the_same_normalization_contract() -> None:
    left = (_claim("source", "left-range", "driving_range", "450"),)
    right = (_claim("target", "right-range", "driving_range", "450"),)

    summary = _aggregate(
        left,
        right,
        source=_context("source", content_hash="same", normalization_version="strict-v1"),
        target=_context("target", content_hash="same", normalization_version="strict-v2"),
    )

    assert summary.primary_relation is FinalRelationType.NEAR_DUPLICATE


def test_containment_is_version_and_preserves_added_claims() -> None:
    left = (_claim("source", "left-price", "property_price", "6.2"),)
    right = (
        _claim("target", "right-price", "property_price", "6.2"),
        _claim("target", "right-fee", "management_fee", "20000"),
    )

    summary = _aggregate(left, right)

    assert summary.primary_relation is FinalRelationType.VERSION_UPDATE
    assert summary.unchanged_count == 1
    assert summary.added_count == 1
    assert summary.facets.has_version_changes
    assert summary.source_coverage == 1.0
    assert summary.target_coverage == 0.5


@pytest.mark.parametrize(  # type: ignore[untyped-decorator]
    ("left", "right"),
    [
        (
            (_claim("source", "left-price", "property_price", "6.2"),),
            (),
        ),
        (
            (),
            (_claim("target", "right-price", "property_price", "6.2"),),
        ),
    ],
)
def test_one_sided_claims_require_deterministic_version_continuity(
    left: tuple[StructuredClaim, ...],
    right: tuple[StructuredClaim, ...],
) -> None:
    deterministic = _aggregate(
        left,
        right,
        source=_context("source", version=2, effective=date(2026, 1, 1)),
        target=_context("target", version=1, effective=date(2025, 1, 1)),
    )
    ambiguous = _aggregate(
        left,
        right,
        source=_context("source", family=None),
        target=_context("target", family=None),
    )

    assert deterministic.primary_relation is FinalRelationType.VERSION_UPDATE
    assert deterministic.facets.has_version_changes
    assert ambiguous.primary_relation is FinalRelationType.UNCERTAIN
    assert not ambiguous.facets.has_version_changes


def test_updated_only_claims_are_a_version_when_temporal_evidence_is_explicit() -> None:
    left = (
        replace(
            _claim("source", "left-price", "property_price", "7.1"),
            temporal=TemporalContext(
                effective_from=date(2026, 1, 1),
                effective_to=date(2026, 12, 31),
                reference_period="2026",
            ),
        ),
    )
    right = (
        replace(
            _claim("target", "right-price", "property_price", "6.2"),
            temporal=TemporalContext(
                effective_from=date(2025, 1, 1),
                effective_to=date(2025, 12, 31),
                reference_period="2025",
            ),
        ),
    )

    summary = _aggregate(
        left,
        right,
        source=_context("source", effective=date(2026, 1, 1)),
        target=_context("target", effective=date(2025, 1, 1)),
    )

    assert summary.primary_relation is FinalRelationType.VERSION_UPDATE
    assert summary.updated_count == 1
    assert summary.version_direction is VersionDirection.SOURCE_SUPERSEDES_TARGET


def test_claim_conflict_wins_without_destroying_version_facets() -> None:
    left = _claims(
        "VF 8 Eco đời 2025 tại Việt Nam có tầm hoạt động 450 km theo WLTP; "
        "dung lượng pin 87,7 kWh.",
        "source",
    )
    right = _claims(
        "VF 8 Eco đời 2025 tại Việt Nam có tầm hoạt động 480 km theo WLTP; "
        "dung lượng pin 87,7 kWh; thời gian sạc 31 phút.",
        "target",
    )

    summary = _aggregate(left, right)

    assert summary.primary_relation is FinalRelationType.CONFLICT
    assert summary.conflict_count == 1
    assert summary.added_count == 1
    assert summary.facets.has_conflict
    assert summary.facets.has_version_changes
    assert summary.conflict_claims[0].source_value is not None
    assert summary.conflict_claims[0].target_value is not None


def test_multiple_conflicts_retain_each_claim_value_and_predicate() -> None:
    left = (
        _claim("source", "left-price", "property_price", "6.2"),
        _claim("source", "left-fee", "management_fee", "20"),
    )
    right = (
        _claim("target", "right-price", "property_price", "7.1"),
        _claim("target", "right-fee", "management_fee", "25"),
    )

    summary = _aggregate(left, right)

    assert summary.primary_relation is FinalRelationType.CONFLICT
    assert summary.conflict_count == 2
    assert summary.conflicting_predicates == ("management_fee", "property_price")
    assert all(item.source_value and item.target_value for item in summary.conflict_claims)


@pytest.mark.parametrize(  # type: ignore[untyped-decorator]
    ("disposition", "expected"),
    [
        (ConflictAdmissionDisposition.TEMPORAL_VARIANT, FinalRelationType.TEMPORAL_VARIANT),
        (
            ConflictAdmissionDisposition.CONDITIONAL_VARIANT,
            FinalRelationType.CONDITIONAL_VARIANT,
        ),
        (ConflictAdmissionDisposition.UNCERTAIN, FinalRelationType.UNCERTAIN),
    ],
)
def test_p2_business_scope_dispositions_remain_authoritative(
    disposition: ConflictAdmissionDisposition,
    expected: FinalRelationType,
) -> None:
    left = _claims("VF 8 Eco có tầm hoạt động 450 km.", "source")
    right = _claims("VF 8 Eco có tầm hoạt động 480 km.", "target")

    assert _aggregate(left, right, decision=disposition).primary_relation is expected


def test_template_threshold_only_applies_after_distinct_entity_gate() -> None:
    no_claims: tuple[StructuredClaim, ...] = ()

    template = _aggregate(
        no_claims,
        no_claims,
        decision=ConflictAdmissionDisposition.DISTINCT_ENTITY,
        template_similarity=0.95,
    )
    distinct = _aggregate(
        no_claims,
        no_claims,
        decision=ConflictAdmissionDisposition.DISTINCT_ENTITY,
        template_similarity=0.93,
    )

    assert template.primary_relation is FinalRelationType.TEMPLATE_VARIANT
    assert distinct.primary_relation is FinalRelationType.DISTINCT


def test_distinct_entities_do_not_create_version_clusters_from_one_sided_claims() -> None:
    left = (_claim("source", "left-price", "property_price", "6.2"),)
    right = (_claim("target", "right-range", "driving_range", "450"),)

    summary = _aggregate(
        left,
        right,
        decision=ConflictAdmissionDisposition.DISTINCT_ENTITY,
    )

    assert summary.primary_relation is FinalRelationType.DISTINCT
    assert not summary.facets.has_version_changes
    assert build_relation_clusters((summary,)) == ()


def test_cross_owner_and_notebook_relations_are_rejected() -> None:
    left = _claims("VF 8 Eco có tầm hoạt động 450 km.", "source")
    right = _claims("VF 8 Eco có tầm hoạt động 450 km.", "target")

    with pytest.raises(PermissionError, match="cross-owner"):
        _aggregate(
            left,
            right,
            source=_context("source", owner_id="one"),
            target=_context("target", owner_id="two"),
        )
    with pytest.raises(PermissionError, match="cross-notebook"):
        _aggregate(
            left,
            right,
            source=_context("source", notebook_id="one"),
            target=_context("target", notebook_id="two"),
        )


def test_version_direction_uses_business_time_and_lineage_is_acyclic() -> None:
    older = _context("v1", version=1, effective=date(2025, 1, 1))
    newer = _context("v2", version=2, effective=date(2026, 1, 1))
    direction, reasons = determine_version_direction(newer, older)

    assert direction is VersionDirection.SOURCE_SUPERSEDES_TARGET
    assert set(reasons) == {"explicit_version_number", "effective_from_progression"}
    lineage = build_version_lineage((newer, older))
    assert lineage.edges == (
        VersionLineageEdge("v1", "v2", "family", ("adjacent_business_version",)),
    )
    assert not lineage_has_cycle(lineage.edges)
    assert lineage_has_cycle(
        (
            *lineage.edges,
            VersionLineageEdge("v2", "v1", "family", ("invalid",)),
        )
    )


def test_ambiguous_version_direction_stays_unknown_in_both_pair_orders() -> None:
    first = _context("v1", family="family")
    second = _context("v2", family="family")

    forward, forward_reasons = determine_version_direction(first, second)
    reverse, reverse_reasons = determine_version_direction(second, first)

    assert forward is reverse is VersionDirection.UNKNOWN
    assert forward_reasons == reverse_reasons == ("ambiguous_version_direction",)


def test_conflict_summary_can_belong_to_version_and_conflict_clusters() -> None:
    left = _claims(
        "VF 8 Eco đời 2025 tại Việt Nam có tầm hoạt động 450 km theo WLTP.",
        "source",
    )
    right = _claims(
        "VF 8 Eco đời 2025 tại Việt Nam có tầm hoạt động 480 km theo WLTP; thời gian sạc 31 phút.",
        "target",
    )
    summary = _aggregate(left, right)

    clusters = build_relation_clusters((summary,))

    assert {cluster.cluster_type for cluster in clusters} == {
        RelationClusterType.CONFLICT_GROUP,
        RelationClusterType.VERSION_FAMILY,
    }
    assert all(cluster.document_ids == ("source", "target") for cluster in clusters)


def test_authority_preference_does_not_change_conflict_relation() -> None:
    left = _claims(
        "VF 8 Eco đời 2025 tại Việt Nam có tầm hoạt động 450 km theo WLTP.",
        "source",
    )
    right = _claims(
        "VF 8 Eco đời 2025 tại Việt Nam có tầm hoạt động 480 km theo WLTP.",
        "target",
    )
    summary = _aggregate(
        left,
        right,
        source=_context("source", authority=90),
        target=_context("target", authority=10),
    )

    assert summary.primary_relation is FinalRelationType.CONFLICT
    assert summary.preferred_document_id == "source"
    assert summary.conflict_count == 1
    assert len(summary.conflict_claims) == 1


def test_existing_quality_relation_payload_retains_p4_evidence_and_review_state() -> None:
    source_id = "00000000-0000-0000-0000-000000000001"
    target_id = "00000000-0000-0000-0000-000000000002"
    left = (_claim(source_id, "left-range", "driving_range", "450"),)
    right = (_claim(target_id, "right-range", "driving_range", "480"),)
    summary = _aggregate(
        left,
        right,
        source=_context(source_id),
        target=_context(target_id),
    )

    candidate = to_quality_relation_candidate(summary)
    payload = candidate.to_payload()

    assert payload["relation_type"] == "conflict"
    assert payload["detector_version"] == "p4-relation-aggregation-v1"
    assert payload["signals"]["p4_primary_relation"] == "CONFLICT"  # type: ignore[index]
    assert payload["signals"]["p4_conflict_claims"]  # type: ignore[index]
    assert payload["signals"]["p4_review_status"] == "pending"  # type: ignore[index]
