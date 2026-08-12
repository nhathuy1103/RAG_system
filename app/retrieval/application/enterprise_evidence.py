"""Shared P6 query-time evidence selection for Enterprise search and Q&A."""

from __future__ import annotations

import json
import math
import re
import unicodedata
from collections import defaultdict
from collections.abc import Mapping
from dataclasses import dataclass, replace

from app.retrieval.adapters.mmr_reranker import MaximalMarginalRelevanceReranker
from app.retrieval.application.query_context import QueryContext, QueryIntent
from app.retrieval.application.relation_policy import (
    RelationPolicyDiagnostics,
    RetrievalPolicyConfig,
    apply_relation_aware_policy,
)
from app.retrieval.domain.metadata import EvidenceMetadata
from app.retrieval.domain.models import RetrievalCandidate, RetrievalFilters

ENTERPRISE_EVIDENCE_POLICY_VERSION = "p6-enterprise-evidence-v1"

_NUMBER = re.compile(
    r"(?<!\w)(?:\d{1,3}(?:[.,\s]\d{3})+|\d+(?:[.,]\d+)?)"
    r"(?:\s*(?:%|km|kwh|kw|m2|mÂ²|vnd|usd|eur|ty|trieu|billion|million))?",
    re.IGNORECASE,
)
_WORD = re.compile(r"[A-Za-z0-9\u00c0-\u024f\u1e00-\u1eff]+", re.UNICODE)
_METHODOLOGY_TERMS = (
    "method",
    "methodology",
    "definition",
    "introduction",
    "overview",
    "instruction",
    "note",
    "rule",
    "phuong phap",
    "quy tac",
    "dinh nghia",
    "gioi thieu",
    "tong quan",
    "huong dan",
    "luu y",
    "don vi tien te",
)


@dataclass(frozen=True, slots=True)
class EnterpriseEvidenceDiagnostics:
    input_ids: tuple[str, ...]
    relation_retained_ids: tuple[str, ...]
    duplicate_suppressed_ids: tuple[str, ...]
    temporal_reserved_ids: tuple[str, ...]
    conflict_reserved_ids: tuple[str, ...]
    final_ids: tuple[str, ...]
    final_document_ids: tuple[str, ...]
    final_years: tuple[int, ...]
    value_bearing_ids: tuple[str, ...]
    reason_codes: tuple[str, ...]
    relation: RelationPolicyDiagnostics
    policy_version: str = ENTERPRISE_EVIDENCE_POLICY_VERSION


@dataclass(frozen=True, slots=True)
class EnterpriseEvidenceSelection:
    evidence: tuple[RetrievalCandidate, ...]
    diagnostics: EnterpriseEvidenceDiagnostics


def select_enterprise_evidence(
    query: QueryContext,
    candidates: tuple[RetrievalCandidate, ...],
    *,
    filters: RetrievalFilters,
    top_k: int,
    max_chunks_per_document: int,
    mmr_lambda: float = 0.7,
    max_near_duplicate_representatives: int = 1,
) -> EnterpriseEvidenceSelection:
    """Construct a compact, relation-safe, value-bearing evidence set."""

    if top_k <= 0:
        raise ValueError("top_k must be positive")
    if max_chunks_per_document <= 0:
        raise ValueError("max_chunks_per_document must be positive")
    normalized = tuple(_wire_canonical_identity(item) for item in candidates)
    relation = apply_relation_aware_policy(
        normalized,
        query=query.retrieval_query,
        filters=filters,
        mode="on",
        top_k=None,
        config=RetrievalPolicyConfig(
            max_near_duplicate_representatives=max_near_duplicate_representatives
        ),
    )
    scoped = _filter_explicit_temporal_scope(relation.evidence, query)
    utility_ranked = _rank_by_evidence_utility(scoped, query)
    conflict_reserved = _reserve_conflicts(utility_ranked)
    conflict_ids = {item.chunk.id for item in conflict_reserved}
    temporal_reserved = _reserve_temporal(
        tuple(item for item in utility_ranked if item.chunk.id not in conflict_ids),
        query,
    )
    mandatory = _unique_candidates((*conflict_reserved, *temporal_reserved))
    mandatory_ids = {item.chunk.id for item in mandatory}
    remainder = tuple(item for item in utility_ranked if item.chunk.id not in mandatory_ids)
    reranker = MaximalMarginalRelevanceReranker(
        lambda_param=mmr_lambda,
        collapse_exact_duplicates=False,
    )
    remaining_budget = max(top_k - len(mandatory), 0)
    diversified = reranker.rerank(
        query.retrieval_query,
        remainder,
        top_k=len(remainder),
    )
    diversified = _bounded_document_fill(
        diversified,
        limit=remaining_budget,
        max_chunks_per_document=max_chunks_per_document,
        existing=mandatory,
    )
    selected = _unique_candidates((*mandatory, *diversified))
    # Mandatory conflict/temporal evidence is never discarded merely because
    # it exceeds the ordinary final Top-K.
    selected = tuple(replace(item, rank=index) for index, item in enumerate(selected, start=1))
    years = tuple(sorted({year for item in selected if (year := candidate_reference_year(item))}))
    reasons: list[str] = []
    if relation.diagnostics.suppressed_duplicate_ids:
        reasons.append("DUPLICATE_SLOT_DILUTION_REDUCED")
    if temporal_reserved:
        reasons.append("TEMPORAL_EVIDENCE_RESERVED")
    if conflict_reserved:
        reasons.append("CONFLICT_EVIDENCE_RESERVED")
    if any(_truthy(item, "p6_value_bearing") for item in selected):
        reasons.append("VALUE_BEARING_EVIDENCE_SELECTED")
    diagnostics = EnterpriseEvidenceDiagnostics(
        input_ids=tuple(item.chunk.id for item in candidates),
        relation_retained_ids=tuple(item.chunk.id for item in relation.evidence),
        duplicate_suppressed_ids=relation.diagnostics.suppressed_duplicate_ids,
        temporal_reserved_ids=tuple(item.chunk.id for item in temporal_reserved),
        conflict_reserved_ids=tuple(item.chunk.id for item in conflict_reserved),
        final_ids=tuple(item.chunk.id for item in selected),
        final_document_ids=tuple(dict.fromkeys(item.chunk.document_id for item in selected)),
        final_years=years,
        value_bearing_ids=tuple(
            item.chunk.id for item in selected if _truthy(item, "p6_value_bearing")
        ),
        reason_codes=tuple(reasons or ("NO_P6_SELECTION_CHANGE",)),
        relation=relation.diagnostics,
    )
    return EnterpriseEvidenceSelection(selected, diagnostics)


def candidate_reference_year(candidate: RetrievalCandidate) -> int | None:
    metadata = candidate.chunk.typed_metadata
    for key in ("reference_year", "year", "canonical_reference_year"):
        value = metadata.integer(key)
        if value is not None and 1900 <= value <= 2100:
            return value
    for key in ("structured_temporal", "claim_scope"):
        nested = _mapping(metadata.get(key))
        for nested_key in ("reference_year", "year"):
            value = _integer(nested.get(nested_key))
            if value is not None and 1900 <= value <= 2100:
                return value
    # Effective time is deliberately not a universal reference-year fallback.
    if _truthy(candidate, "effective_reference_equivalent"):
        match = re.match(r"((?:19|20)\d{2})", _text(candidate, "effective_from"))
        if match:
            return int(match.group(1))
    return None


def _wire_canonical_identity(candidate: RetrievalCandidate) -> RetrievalCandidate:
    metadata = dict(candidate.chunk.metadata)
    if str(metadata.get("conflict_group_id") or "").strip():
        # A persisted conflict edge is a mandatory two-sided unit. Even a bad
        # upstream duplicate annotation must not erase one side.
        metadata.pop("p4_exact_duplicate_group_id", None)
        metadata.pop("exact_duplicate_group_id", None)
        metadata.pop("near_duplicate_group_id", None)
        return replace(
            candidate,
            chunk=replace(
                candidate.chunk,
                metadata=EvidenceMetadata.from_mapping(metadata),
            ),
        )
    if not str(metadata.get("exact_duplicate_group_id") or "").strip():
        normalized_hash = str(metadata.get("normalized_content_hash") or "").strip()
        normalization_version = str(metadata.get("normalization_version") or "").strip()
        if re.fullmatch(r"[0-9a-f]{64}", normalized_hash) and normalization_version:
            metadata["exact_duplicate_group_id"] = (
                f"normalized:{normalization_version}:{normalized_hash}"
            )
    return replace(
        candidate,
        chunk=replace(
            candidate.chunk,
            metadata=EvidenceMetadata.from_mapping(metadata),
        ),
    )


def _filter_explicit_temporal_scope(
    candidates: tuple[RetrievalCandidate, ...], query: QueryContext
) -> tuple[RetrievalCandidate, ...]:
    if query.intent is QueryIntent.CURRENT_FACT or query.current_requested:
        versioned = tuple(
            item
            for item in candidates
            if _text(item, "version_family_id")
            or _text(item, "temporal_series_group_id")
            or _text(item, "p4_relation_type") == "VERSION_UPDATE"
        )
        current = tuple(item for item in versioned if _truthy(item, "is_current"))
        if versioned:
            # A current query must never backfill an older or unknown member of
            # a known version family merely because its lexical score is high.
            return current
    if query.intent is not QueryIntent.HISTORICAL_FACT or not query.reference_years:
        return candidates
    requested = set(query.reference_years)
    matches = tuple(item for item in candidates if candidate_reference_year(item) in requested)
    # Unknown or different periods must not be guessed as the requested year.
    return matches


def _rank_by_evidence_utility(
    candidates: tuple[RetrievalCandidate, ...], query: QueryContext
) -> tuple[RetrievalCandidate, ...]:
    if not candidates:
        return ()
    scores = [item.score if math.isfinite(item.score) else 0.0 for item in candidates]
    low, high = min(scores), max(scores)
    query_tokens = _tokens(query.retrieval_query)
    query_asks_method = any(term in _fold(query.retrieval_query) for term in _METHODOLOGY_TERMS)
    output: list[RetrievalCandidate] = []
    for item, original in zip(candidates, scores, strict=True):
        normalized_relevance = 1.0 if high == low else (original - low) / (high - low)
        metadata = item.chunk.typed_metadata
        searchable = " ".join(
            (
                item.chunk.text,
                metadata.text("section_title") or "",
                " ".join(metadata.strings("table_header")),
                metadata.text("structured_predicate") or "",
            )
        )
        candidate_tokens = _tokens(searchable)
        lexical = len(query_tokens & candidate_tokens) / max(len(query_tokens), 1)
        structured_value = _mapping(metadata.get("structured_value"))
        structured_predicate = _fold(metadata.text("structured_predicate") or "")
        predicate_match = bool(
            structured_predicate
            and any(_fold(value) in structured_predicate for value in query.predicate_terms)
        )
        numbers = _NUMBER.findall(item.chunk.text)
        answer_numbers = tuple(value for value in numbers if not _is_bare_year(value))
        value_bearing = bool(structured_value) or predicate_match or bool(answer_numbers)
        requested_years = set(query.reference_years)
        year = candidate_reference_year(item)
        temporal_score = 0.0
        if requested_years:
            temporal_score = 0.35 if year in requested_years else -0.35
        method_like = any(term in _fold(searchable) for term in _METHODOLOGY_TERMS)
        method_adjustment = 0.50 if query_asks_method and method_like else 0.0
        if query_asks_method and not method_like:
            method_adjustment = -0.18
        if not query_asks_method and method_like and not value_bearing:
            method_adjustment = -0.25
        content_kind = _fold(metadata.text("content_kind") or "")
        table_secondary = 0.06 if value_bearing and content_kind in {"table", "table_row"} else 0.0
        if content_kind in {"table", "table_row"} and not value_bearing:
            table_secondary = -0.18
        value_bonus = 0.06 if query_asks_method else 0.36
        utility = (
            0.32 * normalized_relevance
            + 0.20 * lexical
            + (value_bonus if value_bearing else 0.0)
            + (0.14 if predicate_match else 0.0)
            + temporal_score
            + method_adjustment
            + table_secondary
        )
        reasons = []
        if value_bearing:
            reasons.append("value_bearing")
        if predicate_match:
            reasons.append("predicate_aligned")
        if temporal_score > 0:
            reasons.append("requested_period")
        if method_adjustment < 0:
            reasons.append("supporting_methodology")
        updated = dict(metadata)
        updated.update(
            {
                "p6_original_retrieval_score": original,
                "p6_evidence_utility_score": utility,
                "p6_value_bearing": value_bearing,
                "p6_utility_reason_codes": reasons,
                "rerank_score": utility,
            }
        )
        output.append(
            replace(
                item,
                score=utility,
                chunk=replace(
                    item.chunk,
                    metadata=EvidenceMetadata.from_mapping(updated),
                ),
            )
        )
    ordered = sorted(output, key=lambda item: (-item.score, item.rank, item.chunk.id))
    return tuple(replace(item, rank=index) for index, item in enumerate(ordered, start=1))


def _reserve_conflicts(
    candidates: tuple[RetrievalCandidate, ...],
) -> tuple[RetrievalCandidate, ...]:
    groups: dict[str, list[RetrievalCandidate]] = defaultdict(list)
    for item in candidates:
        if group := _text(item, "conflict_group_id"):
            groups[group].append(item)
    selected: list[RetrievalCandidate] = []
    for group in sorted(groups):
        by_document: dict[str, list[RetrievalCandidate]] = defaultdict(list)
        for item in groups[group]:
            by_document[item.chunk.document_id].append(item)
        if len(by_document) < 2:
            continue
        selected.extend(
            max(values, key=lambda item: (item.score, -item.rank, item.chunk.id))
            for _, values in sorted(by_document.items())
        )
    return _unique_candidates(tuple(selected))


def _reserve_temporal(
    candidates: tuple[RetrievalCandidate, ...], query: QueryContext
) -> tuple[RetrievalCandidate, ...]:
    if query.intent not in {QueryIntent.TEMPORAL_COMPARISON, QueryIntent.VERSION_COMPARISON}:
        return ()
    by_year: dict[int, list[RetrievalCandidate]] = defaultdict(list)
    for item in candidates:
        if year := candidate_reference_year(item):
            by_year[year].append(item)
    target_years = tuple(dict.fromkeys(query.reference_years)) or tuple(sorted(by_year))
    selected = [
        max(by_year[year], key=lambda item: (item.score, -item.rank, item.chunk.id))
        for year in target_years
        if by_year.get(year)
    ]
    if selected:
        return _unique_candidates(tuple(selected))

    # A version comparison can still reserve relation endpoints when their
    # canonical reference year is genuinely unknown.
    groups: dict[str, dict[str, list[RetrievalCandidate]]] = defaultdict(lambda: defaultdict(list))
    for item in candidates:
        group = _text(item, "temporal_series_group_id") or _text(item, "version_family_id")
        if group:
            groups[group][item.chunk.document_id].append(item)
    for group in sorted(groups):
        documents = groups[group]
        if len(documents) >= 2:
            selected.extend(
                max(values, key=lambda item: (item.score, -item.rank, item.chunk.id))
                for _, values in sorted(documents.items())
            )
    return _unique_candidates(tuple(selected))


def _bounded_document_fill(
    candidates: tuple[RetrievalCandidate, ...],
    *,
    limit: int,
    max_chunks_per_document: int,
    existing: tuple[RetrievalCandidate, ...],
) -> tuple[RetrievalCandidate, ...]:
    if limit <= 0:
        return ()
    counts: dict[str, int] = defaultdict(int)
    for item in existing:
        counts[item.chunk.document_id] += 1
    selected: list[RetrievalCandidate] = []
    deferred: list[RetrievalCandidate] = []
    for item in candidates:
        if counts[item.chunk.document_id] >= max_chunks_per_document:
            deferred.append(item)
            continue
        selected.append(item)
        counts[item.chunk.document_id] += 1
        if len(selected) == limit:
            return tuple(selected)
    for item in deferred:
        if len(selected) == limit:
            break
        selected.append(item)
    return tuple(selected)


def _unique_candidates(
    candidates: tuple[RetrievalCandidate, ...],
) -> tuple[RetrievalCandidate, ...]:
    seen: set[str] = set()
    output: list[RetrievalCandidate] = []
    for item in candidates:
        if item.chunk.id in seen:
            continue
        seen.add(item.chunk.id)
        output.append(item)
    return tuple(output)


def _tokens(value: str) -> set[str]:
    return {token for token in (_fold(item) for item in _WORD.findall(value)) if len(token) > 1}


def _fold(value: str) -> str:
    normalized = unicodedata.normalize("NFKD", value.casefold()).replace("đ", "d")
    return "".join(character for character in normalized if not unicodedata.combining(character))


def _text(candidate: RetrievalCandidate, key: str) -> str:
    return candidate.chunk.typed_metadata.text(key) or ""


def _truthy(candidate: RetrievalCandidate, key: str) -> bool:
    value = candidate.chunk.metadata.get(key)
    return value is True or str(value).casefold() in {"true", "1", "yes"}


def _integer(value: object) -> int | None:
    if isinstance(value, bool) or not isinstance(value, str | int | float):
        return None
    try:
        return int(value)
    except (TypeError, ValueError, OverflowError):
        return None


def _is_bare_year(value: str) -> bool:
    compact = value.strip().replace(" ", "")
    return bool(re.fullmatch(r"(?:19|20)\d{2}", compact))


def _mapping(value: object) -> dict[str, object]:
    if isinstance(value, str):
        try:
            value = json.loads(value)
        except (TypeError, ValueError):
            return {}
    if not isinstance(value, Mapping):
        return {}
    return {str(key): item for key, item in value.items()}


__all__ = [
    "ENTERPRISE_EVIDENCE_POLICY_VERSION",
    "EnterpriseEvidenceDiagnostics",
    "EnterpriseEvidenceSelection",
    "candidate_reference_year",
    "select_enterprise_evidence",
]
