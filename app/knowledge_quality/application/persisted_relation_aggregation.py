"""Bridge persisted P3 claim edges into P4 document relation candidates.

The ingestion worker already computes P3 relations while comparing the new
document with prior snapshots.  This module aggregates those exact relations;
it deliberately does not run claim alignment a second time.
"""

from __future__ import annotations

import hashlib
from collections import defaultdict
from collections.abc import Mapping, Sequence
from dataclasses import replace
from enum import StrEnum
from uuid import UUID

from app.knowledge_quality.application.relation_aggregation import (
    AggregationPolicy,
    aggregate_claim_evidence,
    to_quality_relation_candidate,
)
from app.knowledge_quality.domain.models import QualityRelationCandidate
from app.knowledge_quality.domain.relation_models import DocumentRelationContext
from app.knowledge_quality.domain.scope_models import (
    ConflictAdmissionDecision,
    ConflictAdmissionDisposition,
)
from app.structured_facts.application.claim_alignment import ClaimAlignmentResult
from app.structured_facts.domain.models import (
    ClaimRelation,
    ClaimRelationType,
    QualifierCompatibility,
    ScopeRelation,
    SourceAuthority,
    StructuredClaim,
    TemporalContext,
    TemporalRelation,
)
from app.structured_facts.ports.repositories import StructuredClaimCandidate

_PERSISTED_RELATION_TYPES = {
    "source_only": ClaimRelationType.REMOVED,
    "target_only": ClaimRelationType.ADDED,
    **{item.value: item for item in ClaimRelationType},
}
def aggregate_persisted_claim_relations(
    *,
    owner_id: UUID,
    notebook_id: UUID,
    source_document_id: UUID,
    current_claims: Sequence[Mapping[str, object]],
    candidates: Sequence[StructuredClaimCandidate],
    relation_payloads: Sequence[Mapping[str, object]],
    strict_content_hash: str | None = None,
    normalization_version: str | None = None,
    policy: AggregationPolicy | None = None,
) -> tuple[QualityRelationCandidate, ...]:
    """Aggregate one P3 persistence batch into tenant-safe document relations."""
    source_by_key = _current_claims_by_key(current_claims)
    target_by_document, target_document_by_snapshot = _candidate_claims(candidates)
    relations_by_document: dict[str, list[ClaimRelation]] = defaultdict(list)

    for payload in relation_payloads:
        target_document_id = _target_document_id(payload, target_document_by_snapshot)
        if target_document_id is None or target_document_id == str(source_document_id):
            continue
        relation = _claim_relation(payload)
        if relation is None:
            continue
        source_claim = source_by_key.get(relation.source_claim_id or "")
        target_claim = target_by_document.get(target_document_id, {}).get(
            relation.target_claim_id or ""
        )
        if relation.source_claim_id is not None and source_claim is None:
            continue
        if relation.target_claim_id is not None and target_claim is None:
            continue
        relations_by_document[target_document_id].append(relation)

    output: list[QualityRelationCandidate] = []
    for target_document_id, raw_relations in sorted(relations_by_document.items()):
        relations = tuple(raw_relations)
        source_keys = {
            relation.source_claim_id
            for relation in relations
            if relation.source_claim_id is not None
        }
        target_keys = {
            relation.target_claim_id
            for relation in relations
            if relation.target_claim_id is not None
        }
        source_claims = tuple(
            source_by_key[key] for key in sorted(source_keys) if key in source_by_key
        )
        target_index = target_by_document.get(target_document_id, {})
        target_claims = tuple(
            target_index[key] for key in sorted(target_keys) if key in target_index
        )
        alignment = ClaimAlignmentResult(
            relations=relations,
            claims_left=len(source_claims),
            claims_right=len(target_claims),
            aligned_claim_count=sum(
                relation.source_claim_id is not None and relation.target_claim_id is not None
                for relation in relations
            ),
        )
        family_id = _shared_claim_family(source_claims, target_claims)
        source = DocumentRelationContext(
            document_id=str(source_document_id),
            owner_id=str(owner_id),
            notebook_id=str(notebook_id),
            strict_content_hash=strict_content_hash,
            normalization_version=normalization_version,
            document_family_id=family_id,
            temporal=_uniform_temporal(source_claims),
            authority=_uniform_authority(source_claims),
        )
        target = DocumentRelationContext(
            document_id=target_document_id,
            owner_id=str(owner_id),
            notebook_id=str(notebook_id),
            document_family_id=family_id,
            temporal=_uniform_temporal(target_claims),
            authority=_uniform_authority(target_claims),
        )
        summary = aggregate_claim_evidence(
            source=source,
            target=target,
            source_claims=source_claims,
            target_claims=target_claims,
            alignment=alignment,
            scope_decision=_scope_decision(relations),
            policy=policy,
        )
        output.append(to_quality_relation_candidate(summary))
    return tuple(output)


def _current_claims_by_key(
    payloads: Sequence[Mapping[str, object]],
) -> dict[str, StructuredClaim]:
    output: dict[str, StructuredClaim] = {}
    for payload in payloads:
        key = str(payload.get("claim_key") or payload.get("claim_identity_hash") or "").strip()
        if not key:
            continue
        output[key] = replace(StructuredClaim.from_payload(payload), id=key)
    return output


def _candidate_claims(
    candidates: Sequence[StructuredClaimCandidate],
) -> tuple[dict[str, dict[str, StructuredClaim]], dict[str, str]]:
    by_document: dict[str, dict[str, StructuredClaim]] = defaultdict(dict)
    document_by_snapshot: dict[str, str] = {}
    for candidate in candidates:
        document_id = str(candidate.document_id)
        snapshot_id = str(candidate.snapshot_id)
        document_by_snapshot[snapshot_id] = document_id
        claim = StructuredClaim.from_payload(candidate.claim)
        aliases = {
            str(candidate.claim_id),
            str(candidate.claim.get("id") or ""),
            str(candidate.claim.get("claim_identity_hash") or ""),
            claim.claim_identity_hash,
        }
        for key in sorted(alias for alias in aliases if alias):
            by_document[document_id][key] = replace(claim, id=key)
    return dict(by_document), document_by_snapshot


def _target_document_id(
    payload: Mapping[str, object],
    document_by_snapshot: Mapping[str, str],
) -> str | None:
    evidence = payload.get("evidence")
    if isinstance(evidence, Mapping) and evidence.get("target_document_id"):
        return str(evidence["target_document_id"])
    snapshot_id = str(payload.get("target_snapshot_id") or "")
    return document_by_snapshot.get(snapshot_id)


def _claim_relation(payload: Mapping[str, object]) -> ClaimRelation | None:
    relation_type = _PERSISTED_RELATION_TYPES.get(str(payload.get("relation_type") or ""))
    evidence = payload.get("evidence")
    evidence_map = evidence if isinstance(evidence, Mapping) else {}
    if relation_type is None:
        return None
    source_claim_id = _optional_text(payload.get("source_claim_key"))
    target_claim_id = _optional_text(payload.get("target_claim_key"))
    raw_reasons = evidence_map.get("reason_codes")
    reason_codes = (
        tuple(str(item) for item in raw_reasons)
        if isinstance(raw_reasons, list | tuple)
        else tuple(
            item.strip()
            for item in str(payload.get("reason") or "").split(",")
            if item.strip()
        )
    )
    return ClaimRelation(
        relation_type=relation_type,
        source_claim_id=source_claim_id,
        target_claim_id=target_claim_id,
        subject_key=str(evidence_map.get("subject_key") or "unknown"),
        predicate=str(evidence_map.get("predicate") or "unknown"),
        confidence=_confidence(payload.get("confidence")),
        reason_codes=reason_codes,
        scope_relation=_optional_enum(ScopeRelation, payload.get("scope_relation")),
        qualifier_compatibility=_optional_enum(
            QualifierCompatibility,
            payload.get("qualifier_compatibility"),
        ),
        temporal_relation=_optional_enum(TemporalRelation, payload.get("temporal_relation")),
    )


def _scope_decision(relations: tuple[ClaimRelation, ...]) -> ConflictAdmissionDecision:
    types = {relation.relation_type for relation in relations}
    if ClaimRelationType.CONFLICT_CANDIDATE in types:
        disposition = ConflictAdmissionDisposition.ADMIT
        scope_relation = ScopeRelation.SAME
        qualifier = QualifierCompatibility.EQUAL
    elif ClaimRelationType.CONDITIONAL_VARIANT in types:
        disposition = ConflictAdmissionDisposition.CONDITIONAL_VARIANT
        scope_relation = ScopeRelation.OVERLAPS
        qualifier = QualifierCompatibility.DISJOINT
    elif types == {ClaimRelationType.UNCERTAIN}:
        disposition = ConflictAdmissionDisposition.UNCERTAIN
        scope_relation = ScopeRelation.UNKNOWN
        qualifier = QualifierCompatibility.UNKNOWN
    else:
        disposition = ConflictAdmissionDisposition.ADMIT
        scope_relation = ScopeRelation.SAME
        qualifier = QualifierCompatibility.COMPATIBLE
    return ConflictAdmissionDecision(
        disposition=disposition,
        allows_conflict_analysis=disposition is ConflictAdmissionDisposition.ADMIT,
        entity_compatible=True,
        scope_relation=scope_relation,
        qualifier_compatibility=qualifier,
        temporal_relation=TemporalRelation.SAME,
        reason_codes=("p3_persisted_claim_relation_gate",),
    )


def _shared_claim_family(
    source_claims: tuple[StructuredClaim, ...],
    target_claims: tuple[StructuredClaim, ...],
) -> str | None:
    shared = {claim.subject_key for claim in source_claims} & {
        claim.subject_key for claim in target_claims
    }
    if len(shared) != 1:
        return None
    subject = next(iter(shared))
    return f"p4-claim-family-{hashlib.sha256(subject.encode()).hexdigest()[:24]}"


def _uniform_temporal(claims: tuple[StructuredClaim, ...]) -> TemporalContext:
    if not claims:
        return TemporalContext()
    first = claims[0].temporal
    return first if all(claim.temporal == first for claim in claims) else TemporalContext()


def _uniform_authority(claims: tuple[StructuredClaim, ...]) -> SourceAuthority:
    if not claims:
        return SourceAuthority()
    first = claims[0].authority
    return first if all(claim.authority == first for claim in claims) else SourceAuthority()


def _optional_text(value: object) -> str | None:
    normalized = str(value).strip() if value is not None else ""
    return normalized or None


def _optional_enum[EnumT: StrEnum](
    enum_type: type[EnumT], value: object
) -> EnumT | None:
    normalized = _optional_text(value)
    return enum_type(normalized) if normalized is not None else None


def _confidence(value: object) -> float:
    if isinstance(value, bool) or not isinstance(value, str | int | float):
        return 0.0
    return float(value)


__all__ = ["aggregate_persisted_claim_relations"]
