"""Deterministic P5 evidence selection and context-budget construction."""

from __future__ import annotations

import hashlib
import json
import math
import re
import unicodedata
from collections import defaultdict
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, replace

from app.generation.domain.evidence import (
    EvidenceAuthority,
    EvidenceBundle,
    EvidenceBundleType,
    EvidenceProvenance,
    EvidenceStatus,
    GenerationContext,
    GenerationContextDiagnostics,
    GenerationEvidence,
    NoAnswerReason,
)
from app.retrieval.application.query_context import QueryContext, QueryIntent
from app.retrieval.domain.metadata import EvidenceMetadata, MetadataValue
from app.retrieval.domain.models import RetrievalCandidate

CONTEXT_POLICY_VERSION = "p5-context-builder-v1"


@dataclass(frozen=True, slots=True)
class EvidenceContextPolicy:
    max_evidence_items: int = 10
    max_characters: int = 12_000
    characters_per_token: float = 4.0
    max_near_duplicate_representatives: int = 1
    version: str = CONTEXT_POLICY_VERSION

    def __post_init__(self) -> None:
        if self.max_evidence_items <= 0:
            raise ValueError("max_evidence_items must be positive")
        if self.max_characters <= 0:
            raise ValueError("max_characters must be positive")
        if self.characters_per_token <= 0:
            raise ValueError("characters_per_token must be positive")
        if self.max_near_duplicate_representatives <= 0:
            raise ValueError("max_near_duplicate_representatives must be positive")


@dataclass(frozen=True, slots=True)
class _SelectionUnit:
    key: str
    candidates: tuple[RetrievalCandidate, ...]
    bundle_type: EvidenceBundleType
    priority: int
    mandatory: bool
    reason: str


def build_generation_context(
    query: QueryContext,
    candidates: tuple[RetrievalCandidate, ...],
    *,
    authorized_document_ids: frozenset[str],
    policy: EvidenceContextPolicy | None = None,
) -> GenerationContext:
    active = policy or EvidenceContextPolicy()
    visible: list[RetrievalCandidate] = []
    unauthorized: list[str] = []
    for candidate in candidates:
        if candidate.chunk.document_id not in authorized_document_ids:
            unauthorized.append(candidate.chunk.id)
        else:
            visible.append(candidate)

    safe_visible = _strip_orphan_relation_metadata(tuple(visible))
    filtered, qualifier_missing = _select_qualifiers(safe_visible, query)
    deduplicated, duplicate_suppressed = _collapse_duplicates(filtered, active)
    versioned, version_reason = _select_versions(deduplicated, query)
    units = _selection_units(versioned, query)
    selected_candidates, budget_suppressed, budget_overrun = _apply_budget(units, active)
    selected_candidates = tuple(
        sorted(selected_candidates, key=lambda item: (item.rank, -item.score, item.chunk.id))
    )
    evidence = tuple(
        _to_generation_evidence(candidate, ordinal=index, query=query)
        for index, candidate in enumerate(selected_candidates, start=1)
    )
    bundles = _final_bundles(evidence, query)
    no_answer, follow_up = _no_answer_reason(
        query,
        evidence,
        qualifier_missing=qualifier_missing,
        version_reason=version_reason,
        unauthorized=bool(unauthorized),
    )
    conflict_bundles = tuple(
        bundle for bundle in bundles if bundle.bundle_type is EvidenceBundleType.CONFLICT_SET
    )
    conflict_complete = (
        sum(len(bundle.evidence_ids) >= 2 for bundle in conflict_bundles) / len(conflict_bundles)
        if conflict_bundles
        else 1.0
    )
    temporal_complete = _temporal_completeness(query, evidence)
    input_characters = sum(len(item.chunk.text) for item in visible)
    selected_characters = sum(len(item.text) for item in evidence)
    duplicate_occurrences = sum(item.provenance.occurrence_count for item in evidence)
    diagnostics = GenerationContextDiagnostics(
        input_count=len(visible),
        selected_count=len(evidence),
        suppressed_ids=tuple(sorted({*duplicate_suppressed, *budget_suppressed})),
        unauthorized_ids=tuple(sorted(unauthorized)),
        input_characters=input_characters,
        selected_characters=selected_characters,
        estimated_input_tokens=_estimate_tokens(input_characters, active),
        estimated_selected_tokens=_estimate_tokens(selected_characters, active),
        duplicate_occurrence_count=duplicate_occurrences,
        independent_evidence_count=len({item.evidence_group_id for item in evidence}),
        conflict_pair_count=len(conflict_bundles),
        conflict_pair_completeness=conflict_complete,
        temporal_completeness=temporal_complete,
        budget_overrun_for_mandatory_evidence=budget_overrun,
        policy_version=active.version,
    )
    return GenerationContext(
        query=query,
        evidence=evidence,
        bundles=bundles,
        no_answer_reason=no_answer,
        follow_up=follow_up,
        diagnostics=diagnostics,
    )


def _select_qualifiers(
    candidates: tuple[RetrievalCandidate, ...], query: QueryContext
) -> tuple[tuple[RetrievalCandidate, ...], bool]:
    if not query.qualifier_terms:
        return candidates, False
    requested = {_fold(value) for value in query.qualifier_terms}
    conditional = [item for item in candidates if _relation(item) == "CONDITIONAL_VARIANT"]
    if not conditional:
        return candidates, False
    matching_documents = {
        item.chunk.document_id
        for item in conditional
        if requested & _candidate_qualifier_terms(item)
    }
    if not matching_documents:
        return candidates, True
    selected = tuple(
        item
        for item in candidates
        if _relation(item) != "CONDITIONAL_VARIANT" or item.chunk.document_id in matching_documents
    )
    return selected, False


def _strip_orphan_relation_metadata(
    candidates: tuple[RetrievalCandidate, ...],
) -> tuple[RetrievalCandidate, ...]:
    """Remove relation hints whose counterpart is not in the visible candidate set."""

    group_keys = (
        "p4_exact_duplicate_group_id",
        "near_duplicate_group_id",
        "version_family_id",
        "conflict_group_id",
        "conditional_variant_group_id",
        "temporal_series_group_id",
    )
    visible_documents: dict[tuple[str, str], set[str]] = defaultdict(set)
    for item in candidates:
        for key in group_keys:
            if value := _text(item, key):
                visible_documents[(key, value)].add(item.chunk.document_id)
    output: list[RetrievalCandidate] = []
    sensitive_keys = {
        "p4_preferred_evidence",
        "p4_reason_codes",
        "p4_claim_relations",
        "p4_conflict_claims",
        "p4_claim_ids",
        "p4_review_status",
        "authority_reason",
        "p4_provenance_chunk_ids",
        "p4_provenance_document_ids",
        "p4_provenance_count",
    }
    for item in candidates:
        metadata = dict(item.chunk.metadata)
        removed = False
        for key in group_keys:
            value = _text(item, key)
            if value and len(visible_documents[(key, value)]) < 2:
                metadata.pop(key, None)
                removed = True
        if removed and not any(metadata.get(key) for key in group_keys):
            if str(metadata.get("p4_relation_type") or "").upper() != "UNCERTAIN":
                metadata.pop("p4_relation_type", None)
            for key in sensitive_keys:
                metadata.pop(key, None)
        output.append(
            replace(
                item,
                chunk=replace(
                    item.chunk,
                    metadata=EvidenceMetadata.from_mapping(metadata),
                ),
            )
        )
    return tuple(output)


def _collapse_duplicates(
    candidates: tuple[RetrievalCandidate, ...], policy: EvidenceContextPolicy
) -> tuple[tuple[RetrievalCandidate, ...], tuple[str, ...]]:
    protected_documents = {
        item.chunk.document_id
        for item in candidates
        if _text(item, "conflict_group_id") or _relation(item) == "UNCERTAIN"
    }
    retained: list[RetrievalCandidate] = []
    grouped: dict[str, list[RetrievalCandidate]] = defaultdict(list)
    for item in candidates:
        group = _duplicate_group(item)
        if not group or item.chunk.document_id in protected_documents:
            retained.append(item)
        else:
            grouped[group].append(item)
    suppressed: list[str] = []
    for key, members in grouped.items():
        maximum = policy.max_near_duplicate_representatives if key.startswith("near:") else 1
        documents: dict[str, list[RetrievalCandidate]] = defaultdict(list)
        for member in members:
            documents[member.chunk.document_id].append(member)
        ranked_documents = sorted(
            documents,
            key=lambda document_id: _representative_key(
                min(documents[document_id], key=_representative_key)
            ),
        )
        chosen = set(ranked_documents[:maximum])
        retained.extend(item for item in members if item.chunk.document_id in chosen)
        suppressed.extend(item.chunk.id for item in members if item.chunk.document_id not in chosen)
    retained.sort(key=lambda item: (item.rank, -item.score, item.chunk.id))
    return tuple(retained), tuple(sorted(suppressed))


def _select_versions(
    candidates: tuple[RetrievalCandidate, ...], query: QueryContext
) -> tuple[tuple[RetrievalCandidate, ...], NoAnswerReason | None]:
    protected = {
        item.chunk.document_id
        for item in candidates
        if _text(item, "conflict_group_id") or _relation(item) == "UNCERTAIN"
    }
    groups: dict[str, list[RetrievalCandidate]] = defaultdict(list)
    retained: list[RetrievalCandidate] = []
    for item in candidates:
        family = _text(item, "version_family_id") or _text(item, "temporal_series_group_id")
        if not family or item.chunk.document_id in protected:
            retained.append(item)
        else:
            groups[family].append(item)
    reason: NoAnswerReason | None = None
    for members in groups.values():
        documents: dict[str, list[RetrievalCandidate]] = defaultdict(list)
        for member in members:
            documents[member.chunk.document_id].append(member)
        reps = [min(values, key=_representative_key) for values in documents.values()]
        chosen_documents = set(documents)
        if query.intent is QueryIntent.HISTORICAL_FACT and query.reference_years:
            matches = {
                item.chunk.document_id
                for item in reps
                if _candidate_year(item) in query.reference_years
            }
            if matches:
                chosen_documents = matches
            else:
                reason = NoAnswerReason.TEMPORAL_EVIDENCE_MISSING
        elif query.intent is QueryIntent.TEMPORAL_COMPARISON and query.reference_years:
            matches = {
                item.chunk.document_id
                for item in reps
                if _candidate_year(item) in query.reference_years
            }
            matched_years = {
                year
                for item in reps
                if item.chunk.document_id in matches and (year := _candidate_year(item)) is not None
            }
            if matched_years >= set(query.reference_years):
                chosen_documents = matches
            else:
                reason = NoAnswerReason.TEMPORAL_EVIDENCE_MISSING
        elif query.intent is QueryIntent.VERSION_COMPARISON:
            chosen_documents = set(documents)
        else:
            current = [item for item in reps if _bool(item, "is_current") is True]
            if len(current) == 1:
                chosen_documents = {current[0].chunk.document_id}
            elif query.intent is QueryIntent.CURRENT_FACT and len(documents) > 1:
                reason = NoAnswerReason.CURRENT_VERSION_UNKNOWN
        retained.extend(item for item in members if item.chunk.document_id in chosen_documents)
    if (
        query.intent is QueryIntent.CURRENT_FACT
        and reason is None
        and any(_bool(item, "is_current") is False for item in candidates)
        and not any(_bool(item, "is_current") is True for item in candidates)
    ):
        reason = NoAnswerReason.CURRENT_VERSION_UNKNOWN
    retained.sort(key=lambda item: (item.rank, -item.score, item.chunk.id))
    return tuple(retained), reason


def _selection_units(
    candidates: tuple[RetrievalCandidate, ...], query: QueryContext
) -> tuple[_SelectionUnit, ...]:
    assigned: set[str] = set()
    units: list[_SelectionUnit] = []
    conflict_groups = _candidate_groups(candidates, "conflict_group_id")
    for key, members in conflict_groups.items():
        if len({item.chunk.document_id for item in members}) < 2:
            continue
        assigned.update(item.chunk.id for item in members)
        units.append(
            _SelectionUnit(
                key=f"conflict:{key}",
                candidates=members,
                bundle_type=EvidenceBundleType.CONFLICT_SET,
                priority=0,
                mandatory=True,
                reason="confirmed_conflict_both_sides",
            )
        )
    if query.intent in {QueryIntent.TEMPORAL_COMPARISON, QueryIntent.VERSION_COMPARISON}:
        comparison_groups = _candidate_groups(candidates, "version_family_id")
        for key, members in _candidate_groups(candidates, "temporal_series_group_id").items():
            comparison_groups.setdefault(key, members)
        for key, members in comparison_groups.items():
            remaining = tuple(item for item in members if item.chunk.id not in assigned)
            if len({item.chunk.document_id for item in remaining}) < 2:
                continue
            assigned.update(item.chunk.id for item in remaining)
            units.append(
                _SelectionUnit(
                    key=f"series:{key}",
                    candidates=remaining,
                    bundle_type=EvidenceBundleType.TEMPORAL_SERIES,
                    priority=0,
                    mandatory=True,
                    reason="requested_comparison_endpoints",
                )
            )
    conditional_groups: dict[str, list[RetrievalCandidate]] = defaultdict(list)
    for item in candidates:
        if item.chunk.id in assigned or _relation(item) != "CONDITIONAL_VARIANT":
            continue
        key = _text(item, "conditional_variant_group_id") or "|".join(
            (_text(item, "structured_subject"), _text(item, "structured_predicate"))
        )
        conditional_groups[key or item.chunk.id].append(item)
    for key, values in conditional_groups.items():
        members = tuple(values)
        assigned.update(item.chunk.id for item in members)
        units.append(
            _SelectionUnit(
                key=f"conditional:{key}",
                candidates=members,
                bundle_type=EvidenceBundleType.CONDITIONAL_SET,
                priority=1 if not query.qualifier_terms else 0,
                mandatory=not bool(query.qualifier_terms) and len(members) > 1,
                reason="qualifiers_preserved",
            )
        )
    for item in candidates:
        if item.chunk.id in assigned:
            continue
        relation = _relation(item)
        if relation == "UNCERTAIN":
            bundle_type = EvidenceBundleType.UNCERTAIN_SET
            priority = 6
        elif _duplicate_group(item):
            bundle_type = EvidenceBundleType.DUPLICATE_GROUP
            priority = 4
        elif _text(item, "version_family_id") and _bool(item, "is_current") is True:
            bundle_type = EvidenceBundleType.VERSION_CURRENT
            priority = 2
        elif query.intent is QueryIntent.HISTORICAL_FACT:
            bundle_type = EvidenceBundleType.HISTORICAL_FACT
            priority = 1
        else:
            bundle_type = EvidenceBundleType.SINGLE_FACT
            priority = 3
        units.append(
            _SelectionUnit(
                key=f"single:{item.chunk.id}",
                candidates=(item,),
                bundle_type=bundle_type,
                priority=priority,
                mandatory=False,
                reason="query_relevant_evidence",
            )
        )
    return tuple(sorted(units, key=lambda unit: (unit.priority, _unit_rank(unit), unit.key)))


def _apply_budget(
    units: tuple[_SelectionUnit, ...], policy: EvidenceContextPolicy
) -> tuple[tuple[RetrievalCandidate, ...], tuple[str, ...], bool]:
    selected: list[RetrievalCandidate] = []
    suppressed: list[str] = []
    characters = 0
    overrun = False
    for unit in units:
        selected_ids = {value.chunk.id for value in selected}
        new_items = [item for item in unit.candidates if item.chunk.id not in selected_ids]
        unit_characters = sum(len(item.chunk.text) for item in new_items)
        fits = (
            len(selected) + len(new_items) <= policy.max_evidence_items
            and characters + unit_characters <= policy.max_characters
        )
        if not fits and not unit.mandatory:
            suppressed.extend(item.chunk.id for item in new_items)
            continue
        if not fits:
            overrun = True
        selected.extend(new_items)
        characters += unit_characters
    return tuple(selected), tuple(sorted(suppressed)), overrun


def _to_generation_evidence(
    candidate: RetrievalCandidate,
    *,
    ordinal: int,
    query: QueryContext,
) -> GenerationEvidence:
    metadata = candidate.chunk.typed_metadata
    duplicate_group = _duplicate_group(candidate) or None
    version_family = metadata.text("version_family_id") or metadata.text("temporal_series_group_id")
    conflict_group = metadata.text("conflict_group_id")
    relation = _relation(candidate) or "DISTINCT"
    status = EvidenceStatus.UNCERTAIN if relation == "UNCERTAIN" else EvidenceStatus.CONFIRMED
    provenance_chunks = _string_values(metadata.get("p4_provenance_chunk_ids"))
    provenance_documents = _string_values(metadata.get("p4_provenance_document_ids"))
    chunk_ids = tuple(sorted({candidate.chunk.id, *provenance_chunks}))
    document_ids = tuple(sorted({candidate.chunk.document_id, *provenance_documents}))
    authority_map = _mapping(metadata.get("structured_authority"))
    authority_level = _safe_int(
        authority_map.get("authority_level", metadata.get("authority_level"))
    )
    source_type = _optional_text(authority_map.get("source_type", metadata.get("source_type")))
    approval = _optional_text(authority_map.get("approval_status", metadata.get("approval_status")))
    authority_reason = _optional_text(
        authority_map.get("authority_reason", metadata.get("authority_reason"))
    )
    claim_ids = tuple(
        dict.fromkeys(
            value
            for value in (
                metadata.text("structured_claim_id"),
                *_string_values(metadata.get("p4_claim_ids")),
            )
            if value
        )
    )
    evidence_group = (
        duplicate_group
        or conflict_group
        or metadata.text("independent_evidence_group_id")
        or f"chunk:{candidate.chunk.id}"
    )
    selection_reason = _selection_reason(candidate, query)
    return GenerationEvidence(
        evidence_id=f"SRC-{ordinal}",
        candidate=candidate,
        claim_ids=claim_ids,
        subject=metadata.text("structured_subject"),
        predicate=metadata.text("structured_predicate"),
        value=_mapping(metadata.get("structured_value")),
        qualifiers=_mapping(metadata.get("structured_qualifiers")),
        temporal=_mapping(metadata.get("structured_temporal")),
        provenance=EvidenceProvenance(
            document_ids=document_ids,
            chunk_ids=chunk_ids,
            occurrence_count=max(len(chunk_ids), len(document_ids), 1),
        ),
        authority=EvidenceAuthority(
            authority_level=authority_level,
            source_type=source_type,
            approval_status=approval,
            authority_reason=authority_reason,
        ),
        relation_type=relation,
        duplicate_group=duplicate_group,
        version_family=version_family,
        conflict_group=conflict_group,
        current_status=_bool(candidate, "is_current"),
        status=status,
        uncertainty_reasons=_string_values(metadata.get("p4_reason_codes")),
        retrieval_score=candidate.score,
        rerank_score=_safe_float(metadata.get("rerank_score")),
        selection_reason=selection_reason,
        evidence_group_id=evidence_group,
        independent_source_count=1,
    )


def _final_bundles(
    evidence: tuple[GenerationEvidence, ...], query: QueryContext
) -> tuple[EvidenceBundle, ...]:
    valid_conflicts = {
        group
        for group in {item.conflict_group for item in evidence if item.conflict_group}
        if len({item.document_id for item in evidence if item.conflict_group == group}) >= 2
    }
    grouped: dict[tuple[EvidenceBundleType, str], list[GenerationEvidence]] = defaultdict(list)
    for item in evidence:
        if item.conflict_group in valid_conflicts:
            key = (EvidenceBundleType.CONFLICT_SET, item.conflict_group)
        elif item.version_family and query.intent in {
            QueryIntent.TEMPORAL_COMPARISON,
            QueryIntent.VERSION_COMPARISON,
        }:
            key = (EvidenceBundleType.TEMPORAL_SERIES, item.version_family)
        elif item.relation_type == "CONDITIONAL_VARIANT":
            key = (
                EvidenceBundleType.CONDITIONAL_SET,
                f"{item.subject or ''}|{item.predicate or ''}",
            )
        elif item.status is EvidenceStatus.UNCERTAIN:
            key = (EvidenceBundleType.UNCERTAIN_SET, item.evidence_group_id)
        elif item.duplicate_group:
            key = (EvidenceBundleType.DUPLICATE_GROUP, item.duplicate_group)
        elif item.current_status is True and item.version_family:
            key = (EvidenceBundleType.VERSION_CURRENT, item.version_family)
        elif query.intent is QueryIntent.HISTORICAL_FACT:
            key = (EvidenceBundleType.HISTORICAL_FACT, item.evidence_group_id)
        else:
            key = (EvidenceBundleType.SINGLE_FACT, item.evidence_group_id)
        grouped[key].append(item)
    bundles: list[EvidenceBundle] = []
    for (bundle_type, group_key), members in grouped.items():
        mandatory = bundle_type in {
            EvidenceBundleType.CONFLICT_SET,
            EvidenceBundleType.TEMPORAL_SERIES,
        }
        priority = {
            EvidenceBundleType.CONFLICT_SET: 0,
            EvidenceBundleType.TEMPORAL_SERIES: 0,
            EvidenceBundleType.HISTORICAL_FACT: 1,
            EvidenceBundleType.CONDITIONAL_SET: 1,
            EvidenceBundleType.VERSION_CURRENT: 2,
            EvidenceBundleType.SINGLE_FACT: 3,
            EvidenceBundleType.DUPLICATE_GROUP: 4,
            EvidenceBundleType.UNCERTAIN_SET: 6,
        }[bundle_type]
        digest = hashlib.sha256(f"{bundle_type}:{group_key}".encode()).hexdigest()[:16]
        bundles.append(
            EvidenceBundle(
                bundle_id=f"p5-bundle-{digest}",
                bundle_type=bundle_type,
                evidence_ids=tuple(item.evidence_id for item in members),
                priority=priority,
                mandatory=mandatory,
                reason=_bundle_reason(bundle_type),
            )
        )
    return tuple(sorted(bundles, key=lambda item: (item.priority, item.bundle_id)))


def _no_answer_reason(
    query: QueryContext,
    evidence: tuple[GenerationEvidence, ...],
    *,
    qualifier_missing: bool,
    version_reason: NoAnswerReason | None,
    unauthorized: bool,
) -> tuple[NoAnswerReason | None, str | None]:
    if not evidence:
        reason = (
            NoAnswerReason.PERMISSION_FILTERED
            if unauthorized
            else NoAnswerReason.NO_RELEVANT_EVIDENCE
        )
        return reason, None
    if qualifier_missing:
        return (
            NoAnswerReason.INSUFFICIENT_SCOPE,
            "Bạn muốn hỏi theo tiêu chuẩn hoặc phạm vi nào?",
        )
    if version_reason is not None:
        return version_reason, None
    if all(item.status is EvidenceStatus.UNCERTAIN for item in evidence):
        return NoAnswerReason.LOW_CONFIDENCE_EVIDENCE, None
    return None, None


def _temporal_completeness(query: QueryContext, evidence: tuple[GenerationEvidence, ...]) -> float:
    if not query.reference_years:
        return 1.0
    observed = {year for item in evidence if (year := _evidence_year(item)) is not None}
    return len(observed & set(query.reference_years)) / len(set(query.reference_years))


def _candidate_groups(
    candidates: tuple[RetrievalCandidate, ...], key: str
) -> dict[str, tuple[RetrievalCandidate, ...]]:
    groups: dict[str, list[RetrievalCandidate]] = defaultdict(list)
    for item in candidates:
        if value := _text(item, key):
            groups[value].append(item)
    return {name: tuple(values) for name, values in groups.items()}


def _duplicate_group(candidate: RetrievalCandidate) -> str:
    for prefix, key in (
        ("exact", "p4_exact_duplicate_group_id"),
        ("exact", "exact_duplicate_group_id"),
        ("near", "near_duplicate_group_id"),
    ):
        if value := _text(candidate, key):
            return f"{prefix}:{value}"
    return ""


def _candidate_qualifier_terms(candidate: RetrievalCandidate) -> set[str]:
    metadata = candidate.chunk.typed_metadata
    values: list[str] = []
    for key in ("p4_condition", "test_protocol", "market", "price_type"):
        if value := metadata.text(key):
            values.append(value)
    values.extend(_leaf_text(_mapping(metadata.get("structured_qualifiers"))))
    return {_fold(value) for value in values}


def _leaf_text(value: Mapping[str, MetadataValue]) -> tuple[str, ...]:
    output: list[str] = []
    for item in value.values():
        if isinstance(item, dict):
            output.extend(_leaf_text(item))
        elif isinstance(item, list):
            output.extend(str(value) for value in item)
        elif item is not None:
            output.append(str(item))
    return tuple(output)


def _representative_key(candidate: RetrievalCandidate) -> tuple[int, int, float, int, str]:
    inactive = _text(candidate, "document_status").casefold() in {
        "archived",
        "inactive",
        "deleted",
    }
    active = 1 if inactive else 0
    current = 0 if _bool(candidate, "is_current") is True else 1
    score = candidate.score if math.isfinite(candidate.score) else float("-inf")
    authority = _safe_int(candidate.chunk.metadata.get("authority_level")) or 0
    return (active, current, -score, -authority, candidate.chunk.id)


def _selection_reason(candidate: RetrievalCandidate, query: QueryContext) -> str:
    if _text(candidate, "conflict_group_id"):
        return "conflict_counterpart_preserved"
    if query.intent is QueryIntent.HISTORICAL_FACT:
        return "requested_historical_period"
    if query.intent in {QueryIntent.TEMPORAL_COMPARISON, QueryIntent.VERSION_COMPARISON}:
        return "requested_comparison_evidence"
    if _bool(candidate, "is_current") is True:
        return "explicit_current_version"
    if _relation(candidate) == "UNCERTAIN":
        return "query_relevant_uncertain_evidence"
    if _duplicate_group(candidate):
        return "duplicate_group_representative"
    return "ranked_query_relevance"


def _bundle_reason(bundle_type: EvidenceBundleType) -> str:
    return {
        EvidenceBundleType.CONFLICT_SET: "both_conflicting_sides_mandatory",
        EvidenceBundleType.TEMPORAL_SERIES: "comparison_endpoints_mandatory",
        EvidenceBundleType.HISTORICAL_FACT: "requested_historical_evidence",
        EvidenceBundleType.CONDITIONAL_SET: "measurement_business_qualifiers_preserved",
        EvidenceBundleType.VERSION_CURRENT: "explicit_current_version",
        EvidenceBundleType.DUPLICATE_GROUP: "one_fact_with_authorized_occurrences",
        EvidenceBundleType.UNCERTAIN_SET: "uncertainty_preserved",
        EvidenceBundleType.SINGLE_FACT: "independent_query_evidence",
    }[bundle_type]


def _candidate_year(candidate: RetrievalCandidate) -> int | None:
    for key in ("reference_year", "year", "effective_year"):
        if value := _safe_int(candidate.chunk.metadata.get(key)):
            return value
    for key in ("effective_from", "valid_from"):
        text_value = _text(candidate, key)
        match = re.match(r"((?:19|20)\d{2})", text_value)
        if match:
            return int(match.group(1))
    temporal = _mapping(candidate.chunk.metadata.get("structured_temporal"))
    for key in ("reference_year", "effective_from", "valid_from"):
        temporal_value = temporal.get(key)
        match = re.match(r"((?:19|20)\d{2})", str(temporal_value or ""))
        if match:
            return int(match.group(1))
    return None


def _evidence_year(item: GenerationEvidence) -> int | None:
    for key in ("reference_year", "year", "effective_from", "valid_from"):
        match = re.match(r"((?:19|20)\d{2})", str(item.temporal.get(key) or ""))
        if match:
            return int(match.group(1))
    return _candidate_year(item.candidate)


def _relation(candidate: RetrievalCandidate) -> str:
    return _text(candidate, "p4_relation_type").upper()


def _text(candidate: RetrievalCandidate, key: str) -> str:
    return candidate.chunk.typed_metadata.text(key) or ""


def _bool(candidate: RetrievalCandidate, key: str) -> bool | None:
    value = candidate.chunk.metadata.get(key)
    if isinstance(value, bool):
        return value
    if isinstance(value, str) and value.casefold() in {"true", "1", "yes"}:
        return True
    if isinstance(value, str) and value.casefold() in {"false", "0", "no"}:
        return False
    return None


def _mapping(value: object) -> dict[str, MetadataValue]:
    if isinstance(value, str):
        try:
            value = json.loads(value)
        except (TypeError, ValueError):
            return {}
    if not isinstance(value, Mapping):
        return {}
    return {str(key): _metadata_value(item) for key, item in value.items()}


def _metadata_value(value: object) -> MetadataValue:
    if value is None or isinstance(value, str | int | float | bool):
        return value
    if isinstance(value, Mapping):
        return {str(key): _metadata_value(item) for key, item in value.items()}
    if isinstance(value, Iterable) and not isinstance(value, bytes):
        return [_metadata_value(item) for item in value]
    return str(value)


def _string_values(value: object) -> tuple[str, ...]:
    if isinstance(value, str):
        try:
            decoded = json.loads(value)
        except (TypeError, ValueError):
            return tuple(part.strip() for part in value.split(",") if part.strip())
        value = decoded
    if isinstance(value, Iterable) and not isinstance(value, bytes | Mapping):
        return tuple(str(item).strip() for item in value if str(item).strip())
    return ()


def _safe_int(value: object) -> int | None:
    if isinstance(value, bool) or not isinstance(value, str | int | float):
        return None
    try:
        return int(value)
    except (TypeError, ValueError, OverflowError):
        return None


def _safe_float(value: object) -> float | None:
    if isinstance(value, bool) or not isinstance(value, str | int | float):
        return None
    try:
        parsed = float(value)
    except (TypeError, ValueError, OverflowError):
        return None
    return parsed if math.isfinite(parsed) else None


def _optional_text(value: object) -> str | None:
    if value is None or isinstance(value, dict | list):
        return None
    text = str(value).strip()
    return text or None


def _estimate_tokens(characters: int, policy: EvidenceContextPolicy) -> int:
    return math.ceil(characters / policy.characters_per_token) if characters else 0


def _unit_rank(unit: _SelectionUnit) -> int:
    return min((item.rank for item in unit.candidates), default=0)


def _fold(value: str) -> str:
    normalized = unicodedata.normalize("NFKD", value.casefold()).replace("đ", "d")
    return " ".join(
        "".join(
            character for character in normalized if not unicodedata.combining(character)
        ).split()
    )


__all__ = [
    "CONTEXT_POLICY_VERSION",
    "EvidenceContextPolicy",
    "build_generation_context",
]
