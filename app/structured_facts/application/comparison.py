"""Build persistence-ready claim relations from current and prior table facts."""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from uuid import UUID

from app.structured_facts.application.table_analyzer import TableAnalysis
from app.structured_facts.application.table_diff import diff_table_analyses
from app.structured_facts.domain.models import (
    ClaimRelation,
    ClaimRelationType,
    StructuredClaim,
)
from app.structured_facts.ports.repositories import StructuredClaimCandidate

_PENDING_REVIEW_TYPES = {
    ClaimRelationType.CONFLICT_CANDIDATE.value,
    ClaimRelationType.UNCERTAIN.value,
}


@dataclass(frozen=True, slots=True)
class _CurrentTable:
    analysis: TableAnalysis
    snapshot_key: str
    schema_fingerprint: str
    normalized_schema: tuple[str, ...]
    candidate_hashes: frozenset[str]
    claim_key_by_domain_id: Mapping[str, str]


@dataclass(frozen=True, slots=True)
class _PriorTable:
    analysis: TableAnalysis
    snapshot_id: UUID
    snapshot_key: str
    schema_fingerprint: str
    template_fingerprint: str | None
    normalized_schema: tuple[str, ...]
    candidate_hashes: frozenset[str]
    claim_key_by_domain_id: Mapping[str, str]


@dataclass(frozen=True, slots=True)
class _TableMatch:
    current: _CurrentTable
    prior: _PriorTable
    score: tuple[int, int, int]


def build_structured_relation_payloads(
    *,
    analyses: Sequence[TableAnalysis],
    table_snapshots: Sequence[Mapping[str, object]],
    candidates: Sequence[StructuredClaimCandidate],
) -> tuple[dict[str, object], ...]:
    """Diff current tables against prior snapshots and map results to RPC payloads.

    The source side is always the newly ingested document.  ``diff_table_analyses``
    uses left/right terminology, so one-sided outcomes are remapped to the
    migration's directional ``source_only`` / ``target_only`` names.
    """

    current_tables = _current_tables(analyses, table_snapshots)
    prior_tables = _prior_tables(candidates)
    if not current_tables or not prior_tables:
        return ()

    payloads: list[dict[str, object]] = []
    for match in _unique_table_matches(current_tables, prior_tables):
        diff = diff_table_analyses(match.current.analysis, match.prior.analysis)
        for relation in diff.relations:
            payload = _relation_payload(match, relation)
            if payload is not None:
                payloads.append(payload)
    return tuple(payloads)


def _current_tables(
    analyses: Sequence[TableAnalysis],
    snapshots: Sequence[Mapping[str, object]],
) -> tuple[_CurrentTable, ...]:
    snapshot_by_key = {
        str(snapshot.get("snapshot_key") or snapshot.get("table_id") or ""): snapshot
        for snapshot in snapshots
        if str(snapshot.get("snapshot_key") or snapshot.get("table_id") or "").strip()
    }
    result: list[_CurrentTable] = []
    for analysis in analyses:
        snapshot = snapshot_by_key.get(analysis.table_id, {})
        schema_fingerprint = str(snapshot.get("schema_fingerprint") or "").strip()
        normalized_schema = _schema_columns(snapshot.get("normalized_schema"))
        if not normalized_schema:
            normalized_schema = tuple(analysis.normalized_schema)
        result.append(
            _CurrentTable(
                analysis=analysis,
                snapshot_key=analysis.table_id,
                schema_fingerprint=schema_fingerprint,
                normalized_schema=normalized_schema,
                candidate_hashes=frozenset(
                    claim.candidate_identity_hash for claim in analysis.claims
                ),
                claim_key_by_domain_id={
                    claim.id: claim.claim_identity_hash
                    for claim in analysis.claims
                    if claim.id is not None
                },
            )
        )
    return tuple(result)


def _prior_tables(
    candidates: Sequence[StructuredClaimCandidate],
) -> tuple[_PriorTable, ...]:
    grouped: dict[UUID, list[StructuredClaimCandidate]] = defaultdict(list)
    for candidate in candidates:
        grouped[candidate.snapshot_id].append(candidate)

    result: list[_PriorTable] = []
    for snapshot_id, rows in grouped.items():
        claims: list[StructuredClaim] = []
        claim_key_by_domain_id: dict[str, str] = {}
        for row in rows:
            claim = StructuredClaim.from_payload(row.claim)
            claims.append(claim)
            claim_key = str(
                row.claim.get("claim_identity_hash")
                or row.claim.get("id")
                or claim.claim_identity_hash
            )
            if claim.id is not None:
                claim_key_by_domain_id[claim.id] = claim_key

        first = rows[0]
        normalized_schema = _schema_columns(first.normalized_schema)
        confidence = (
            sum(claim.extraction_confidence for claim in claims) / len(claims) if claims else 0.0
        )
        result.append(
            _PriorTable(
                analysis=TableAnalysis(
                    document_id=str(first.document_id),
                    table_id=first.snapshot_key,
                    claims=tuple(claims),
                    row_count=_row_count(claims),
                    normalized_schema=normalized_schema,
                    header_mapping=_header_mapping(first.normalized_schema),
                    confidence=confidence,
                    warnings=(),
                    extractor_version=claims[0].extractor_version if claims else "",
                ),
                snapshot_id=snapshot_id,
                snapshot_key=first.snapshot_key,
                schema_fingerprint=first.schema_fingerprint,
                template_fingerprint=first.template_fingerprint,
                normalized_schema=normalized_schema,
                candidate_hashes=frozenset(candidate.candidate_identity_hash for candidate in rows),
                claim_key_by_domain_id=claim_key_by_domain_id,
            )
        )
    return tuple(result)


def _unique_table_matches(
    current_tables: Sequence[_CurrentTable],
    prior_tables: Sequence[_PriorTable],
) -> tuple[_TableMatch, ...]:
    accepted: list[_TableMatch] = []
    prior_by_document: dict[str, list[_PriorTable]] = defaultdict(list)
    for prior in prior_tables:
        prior_by_document[prior.analysis.document_id].append(prior)

    # A current table may legitimately conflict with the corresponding table
    # in several independent source documents. Ambiguity is therefore judged
    # only among tables inside one prior document, never across documents.
    for document_priors in prior_by_document.values():
        pairs: list[_TableMatch] = []
        for current in current_tables:
            for prior in document_priors:
                score = _match_score(current, prior)
                if score is not None:
                    pairs.append(_TableMatch(current=current, prior=prior, score=score))

        by_current: dict[str, list[_TableMatch]] = defaultdict(list)
        by_prior: dict[UUID, list[_TableMatch]] = defaultdict(list)
        for pair in pairs:
            by_current[pair.current.snapshot_key].append(pair)
            by_prior[pair.prior.snapshot_id].append(pair)

        for current in current_tables:
            top_for_current = _unique_top(by_current.get(current.snapshot_key, ()))
            if top_for_current is None:
                continue
            top_for_prior = _unique_top(by_prior.get(top_for_current.prior.snapshot_id, ()))
            if top_for_prior == top_for_current:
                accepted.append(top_for_current)
    return tuple(accepted)


def _match_score(
    current: _CurrentTable,
    prior: _PriorTable,
) -> tuple[int, int, int] | None:
    schema_matches = bool(
        current.schema_fingerprint
        and prior.schema_fingerprint
        and current.schema_fingerprint == prior.schema_fingerprint
    )
    identity_overlap = len(current.candidate_hashes.intersection(prior.candidate_hashes))
    if not schema_matches and identity_overlap == 0:
        return None
    column_overlap = len(set(current.normalized_schema).intersection(prior.normalized_schema))
    return (1 if schema_matches else 0, identity_overlap, column_overlap)


def _unique_top(matches: Sequence[_TableMatch]) -> _TableMatch | None:
    if not matches:
        return None
    ordered = sorted(matches, key=lambda match: match.score, reverse=True)
    if len(ordered) > 1 and ordered[0].score == ordered[1].score:
        return None
    return ordered[0]


def _relation_payload(
    match: _TableMatch,
    relation: ClaimRelation,
) -> dict[str, object] | None:
    relation_type = _relation_type_for_persistence(relation.relation_type)
    source_claim_key = (
        match.current.claim_key_by_domain_id.get(relation.source_claim_id)
        if relation.source_claim_id is not None
        else None
    )
    target_claim_key = (
        match.prior.claim_key_by_domain_id.get(relation.target_claim_id)
        if relation.target_claim_id is not None
        else None
    )
    if relation.source_claim_id is not None and source_claim_key is None:
        return None
    if relation.target_claim_id is not None and target_claim_key is None:
        return None

    reason_codes = tuple(relation.reason_codes)
    return {
        "source_snapshot_key": match.current.snapshot_key,
        "target_snapshot_id": str(match.prior.snapshot_id),
        "source_claim_key": source_claim_key,
        "target_claim_key": target_claim_key,
        "relation_type": relation_type,
        "scope_relation": (
            relation.scope_relation.value if relation.scope_relation is not None else None
        ),
        "qualifier_compatibility": (
            relation.qualifier_compatibility.value
            if relation.qualifier_compatibility is not None
            else None
        ),
        "temporal_relation": (
            relation.temporal_relation.value if relation.temporal_relation is not None else None
        ),
        "confidence": relation.confidence,
        "reason": ",".join(reason_codes) if reason_codes else None,
        "review_status": (
            "pending" if relation_type in _PENDING_REVIEW_TYPES else "auto_confirmed"
        ),
        "detector_name": "structured-fact-analyzer",
        "detector_version": match.current.analysis.extractor_version,
        "evidence": {
            "reason_codes": list(reason_codes),
            "subject_key": relation.subject_key,
            "predicate": relation.predicate,
            "source_document_id": match.current.analysis.document_id,
            "target_document_id": match.prior.analysis.document_id,
            "source_snapshot_key": match.current.snapshot_key,
            "target_snapshot_key": match.prior.snapshot_key,
            "source_schema_fingerprint": match.current.schema_fingerprint,
            "target_schema_fingerprint": match.prior.schema_fingerprint,
            "target_template_fingerprint": match.prior.template_fingerprint,
            "direction": "current_to_prior",
        },
    }


def _relation_type_for_persistence(relation_type: ClaimRelationType) -> str:
    if relation_type is ClaimRelationType.REMOVED:
        return "source_only"
    if relation_type is ClaimRelationType.ADDED:
        return "target_only"
    return str(relation_type.value)


def _schema_columns(value: object) -> tuple[str, ...]:
    if not isinstance(value, Mapping):
        return ()
    columns = value.get("columns")
    if not isinstance(columns, list | tuple):
        return ()
    return tuple(str(column) for column in columns)


def _header_mapping(value: object) -> dict[str, str]:
    if not isinstance(value, Mapping):
        return {}
    raw_mapping = value.get("header_mapping")
    if not isinstance(raw_mapping, Mapping):
        return {}
    return {str(key): str(item) for key, item in raw_mapping.items()}


def _row_count(claims: Sequence[StructuredClaim]) -> int:
    row_keys = {
        (
            claim.provenance.table_id,
            claim.provenance.data_row_ordinal,
            claim.subject_key,
        )
        for claim in claims
    }
    return len(row_keys)


__all__ = ["build_structured_relation_payloads"]
