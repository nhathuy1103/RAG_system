"""Relation-aware, permission-safe P4 post-processing for retrieved evidence."""

from __future__ import annotations

import json
import math
import re
import time
import unicodedata
from dataclasses import dataclass, replace
from typing import Literal

from app.knowledge_quality.domain.relation_models import RETRIEVAL_POLICY_VERSION
from app.retrieval.domain.models import RetrievalCandidate, RetrievalFilters

RelationPolicyMode = Literal["off", "shadow", "on"]

_INACTIVE_STATUSES = {"deleted", "failed", "inactive", "archived"}
_CURRENT_WORDS = {"current", "latest", "hien tai", "moi nhat"}
_COMPARISON_WORDS = {"compare", "comparison", "changed", "change", "so sanh", "thay doi"}
_YEAR = re.compile(r"(?<!\d)(20\d{2})(?!\d)")


@dataclass(frozen=True, slots=True)
class RetrievalPolicyConfig:
    max_near_duplicate_representatives: int = 1
    version: str = RETRIEVAL_POLICY_VERSION

    def __post_init__(self) -> None:
        if self.max_near_duplicate_representatives < 1:
            raise ValueError("max_near_duplicate_representatives must be positive")


@dataclass(frozen=True, slots=True)
class RelationPolicyDiagnostics:
    legacy_chunk_ids: tuple[str, ...]
    proposed_retained_ids: tuple[str, ...]
    suppressed_duplicate_ids: tuple[str, ...]
    selected_version_ids: tuple[str, ...]
    preserved_conflict_ids: tuple[str, ...]
    reason_codes: tuple[str, ...]
    latency_ms: float
    before_count: int
    after_count: int
    before_characters: int
    after_characters: int
    policy_version: str


@dataclass(frozen=True, slots=True)
class RelationPolicyResult:
    evidence: tuple[RetrievalCandidate, ...]
    proposed_evidence: tuple[RetrievalCandidate, ...]
    diagnostics: RelationPolicyDiagnostics


def apply_relation_aware_policy(
    candidates: tuple[RetrievalCandidate, ...],
    *,
    query: str,
    filters: RetrievalFilters,
    mode: RelationPolicyMode = "on",
    top_k: int | None = None,
    config: RetrievalPolicyConfig | None = None,
) -> RelationPolicyResult:
    """Suppress redundant evidence while preserving conflicts and provenance.

    Only candidates already visible inside ``filters`` can enter groups or
    diagnostics.  This prevents a persisted cross-tenant cluster identifier
    from leaking the existence of a hidden counterpart.
    """
    if mode not in {"off", "shadow", "on"}:
        raise ValueError("mode must be off, shadow, or on")
    if top_k is not None and top_k <= 0:
        raise ValueError("top_k must be positive")
    active_config = config or RetrievalPolicyConfig()
    started = time.perf_counter_ns()
    visible = tuple(candidate for candidate in candidates if _visible(candidate, filters))
    visible = tuple(candidate for candidate in visible if _lifecycle_visible(candidate, query))
    legacy = visible[:top_k] if top_k is not None else visible
    if mode == "off":
        proposed = legacy
        reasons: tuple[str, ...] = ("relation_policy_off",)
        suppressed: tuple[str, ...] = ()
        selected_versions: tuple[str, ...] = ()
        preserved_conflicts = _conflict_member_ids(proposed)
    else:
        p4_exact_collapsed, p4_exact_suppressed = _collapse_groups(
            visible,
            group_keys=("p4_exact_duplicate_group_id",),
            maximum=1,
            annotate_provenance=True,
            select_by_document=True,
        )
        exact_collapsed, legacy_exact_suppressed = _collapse_groups(
            p4_exact_collapsed,
            group_keys=("exact_duplicate_group_id",),
            maximum=1,
            annotate_provenance=True,
            select_by_document=False,
        )
        exact_suppressed = tuple(
            sorted({*p4_exact_suppressed, *legacy_exact_suppressed})
        )
        conflict_protected = _conflict_member_ids(exact_collapsed)
        conflict_protected_documents = frozenset(
            candidate.chunk.document_id
            for candidate in exact_collapsed
            if candidate.chunk.id in conflict_protected
        )
        near_collapsed, near_suppressed = _collapse_near_duplicates(
            exact_collapsed,
            protected_documents=conflict_protected_documents,
            maximum=active_config.max_near_duplicate_representatives,
        )
        conditional = _filter_conditional_variants(near_collapsed, query)
        versioned, selected_versions = _select_versions(
            conditional,
            query,
            protected_documents=conflict_protected_documents,
        )
        proposed = versioned[:top_k] if top_k is not None else versioned
        suppressed = tuple(sorted({*exact_suppressed, *near_suppressed}))
        preserved_conflicts = _conflict_member_ids(proposed)
        reasons_list = []
        if suppressed:
            reasons_list.append("duplicate_redundancy_reduced")
        if selected_versions:
            reasons_list.append("business_version_selected")
        if preserved_conflicts:
            reasons_list.append("conflict_evidence_preserved")
        reasons = tuple(reasons_list or ("no_relation_policy_change",))

    latency_ms = (time.perf_counter_ns() - started) / 1_000_000
    output = proposed if mode == "on" else legacy
    diagnostics = RelationPolicyDiagnostics(
        legacy_chunk_ids=tuple(candidate.chunk.id for candidate in legacy),
        proposed_retained_ids=tuple(candidate.chunk.id for candidate in proposed),
        suppressed_duplicate_ids=suppressed,
        selected_version_ids=selected_versions,
        preserved_conflict_ids=preserved_conflicts,
        reason_codes=reasons,
        latency_ms=latency_ms,
        before_count=len(legacy),
        after_count=len(proposed),
        before_characters=sum(len(candidate.chunk.text) for candidate in legacy),
        after_characters=sum(len(candidate.chunk.text) for candidate in proposed),
        policy_version=active_config.version,
    )
    return RelationPolicyResult(output, proposed, diagnostics)


def duplicate_redundancy_at_k(candidates: tuple[RetrievalCandidate, ...], k: int) -> float:
    """Fraction of top-k items beyond the first member of a duplicate group."""
    selected = candidates[:k]
    seen: set[str] = set()
    redundant = 0
    for candidate in selected:
        key = _factual_group_key(candidate)
        if key in seen:
            redundant += 1
        seen.add(key)
    return redundant / len(selected) if selected else 0.0


def unique_evidence_at_k(candidates: tuple[RetrievalCandidate, ...], k: int) -> int:
    return len({_factual_group_key(candidate) for candidate in candidates[:k]})


def document_diversity_at_k(candidates: tuple[RetrievalCandidate, ...], k: int) -> int:
    return len({candidate.chunk.document_id for candidate in candidates[:k]})


def _collapse_groups(
    candidates: tuple[RetrievalCandidate, ...],
    *,
    group_keys: tuple[str, ...],
    maximum: int,
    annotate_provenance: bool,
    select_by_document: bool,
) -> tuple[tuple[RetrievalCandidate, ...], tuple[str, ...]]:
    groups: dict[str, list[tuple[int, RetrievalCandidate]]] = {}
    singles: list[tuple[int, RetrievalCandidate]] = []
    for position, candidate in enumerate(candidates):
        group = _first_text(candidate, group_keys)
        if group:
            groups.setdefault(group, []).append((position, candidate))
        else:
            singles.append((position, candidate))
    retained: list[tuple[int, RetrievalCandidate]] = list(singles)
    suppressed: list[str] = []
    for members in groups.values():
        if select_by_document:
            documents = _members_by_document(members)
            ranked_documents = sorted(
                documents.items(),
                key=lambda item: _representative_key(_best(item[1])[1]),
            )
            selected_documents = {
                document_id for document_id, _ in ranked_documents[:maximum]
            }
            selected = [
                item for item in members if item[1].chunk.document_id in selected_documents
            ]
            suppressed.extend(
                candidate.chunk.id
                for _, candidate in members
                if candidate.chunk.document_id not in selected_documents
            )
        else:
            selected = sorted(members, key=lambda item: _representative_key(item[1]))[:maximum]
            selected_ids = {candidate.chunk.id for _, candidate in selected}
            suppressed.extend(
                candidate.chunk.id
                for _, candidate in members
                if candidate.chunk.id not in selected_ids
            )
        for position, candidate in selected:
            if annotate_provenance:
                candidate = _with_visible_provenance(
                    candidate,
                    tuple(item for _, item in members),
                )
            retained.append((position, candidate))
    retained.sort(key=lambda item: item[0])
    return tuple(candidate for _, candidate in retained), tuple(sorted(suppressed))


def _collapse_near_duplicates(
    candidates: tuple[RetrievalCandidate, ...],
    *,
    protected_documents: frozenset[str],
    maximum: int,
) -> tuple[tuple[RetrievalCandidate, ...], tuple[str, ...]]:
    grouped: dict[str, list[tuple[int, RetrievalCandidate]]] = {}
    retained: list[tuple[int, RetrievalCandidate]] = []
    uncertain_documents = {
        candidate.chunk.document_id for candidate in candidates if _is_uncertain(candidate)
    }
    for position, candidate in enumerate(candidates):
        group = _text(candidate, "near_duplicate_group_id")
        if (
            not group
            or candidate.chunk.document_id in protected_documents
            or candidate.chunk.document_id in uncertain_documents
        ):
            retained.append((position, candidate))
        else:
            grouped.setdefault(group, []).append((position, candidate))
    suppressed: list[str] = []
    for members in grouped.values():
        documents = _members_by_document(members)
        ranked_documents = sorted(
            documents.items(),
            key=lambda item: _representative_key(_best(item[1])[1]),
        )
        selected_documents = {document_id for document_id, _ in ranked_documents[:maximum]}
        retained.extend(
            item for item in members if item[1].chunk.document_id in selected_documents
        )
        suppressed.extend(
            candidate.chunk.id
            for _, candidate in members
            if candidate.chunk.document_id not in selected_documents
        )
    retained.sort(key=lambda item: item[0])
    return tuple(candidate for _, candidate in retained), tuple(sorted(suppressed))


def _select_versions(
    candidates: tuple[RetrievalCandidate, ...],
    query: str,
    *,
    protected_documents: frozenset[str],
) -> tuple[tuple[RetrievalCandidate, ...], tuple[str, ...]]:
    groups: dict[str, list[tuple[int, RetrievalCandidate]]] = {}
    retained: list[tuple[int, RetrievalCandidate]] = []
    uncertain_documents = {
        candidate.chunk.document_id for candidate in candidates if _is_uncertain(candidate)
    }
    for position, candidate in enumerate(candidates):
        family = _text(candidate, "version_family_id")
        if (
            not family
            or candidate.chunk.document_id in protected_documents
            or candidate.chunk.document_id in uncertain_documents
        ):
            retained.append((position, candidate))
        else:
            groups.setdefault(family, []).append((position, candidate))
    requested_years = tuple(dict.fromkeys(int(value) for value in _YEAR.findall(query)))
    folded_query = _fold(query)
    comparison = len(requested_years) > 1 or any(word in folded_query for word in _COMPARISON_WORDS)
    current_requested = any(word in folded_query for word in _CURRENT_WORDS)
    selected_ids: list[str] = []
    for members in groups.values():
        documents = _members_by_document(members)
        document_representatives = [
            _best(document_members) for document_members in documents.values()
        ]
        chosen_documents = set(documents)
        if requested_years:
            matches = [
                item
                for item in document_representatives
                if _candidate_year(item[1]) in requested_years
            ]
            if matches:
                chosen = matches if comparison else [_best(matches)]
                chosen_documents = {item[1].chunk.document_id for item in chosen}
        elif not comparison:
            explicit_current = [
                item for item in document_representatives if _truthy(item[1], "is_current")
            ]
            if len(explicit_current) == 1:
                chosen_documents = {explicit_current[0][1].chunk.document_id}
            elif current_requested or explicit_current:
                # A newest-known revision is not automatically the currently
                # valid business version.  Ambiguous/absent validity metadata
                # therefore keeps the visible family instead of guessing.
                chosen_documents = set(documents)
            else:
                deterministic = _latest_deterministic(document_representatives)
                if deterministic is not None:
                    chosen_documents = {deterministic[1].chunk.document_id}
        chosen = [
            item for item in members if item[1].chunk.document_id in chosen_documents
        ]
        retained.extend(chosen)
        if len(chosen_documents) < len(documents):
            selected_ids.extend(candidate.chunk.id for _, candidate in chosen)
    retained.sort(key=lambda item: item[0])
    return tuple(candidate for _, candidate in retained), tuple(sorted(selected_ids))


def _filter_conditional_variants(
    candidates: tuple[RetrievalCandidate, ...], query: str
) -> tuple[RetrievalCandidate, ...]:
    folded = _fold(query)
    conditions = {
        _fold(value)
        for candidate in candidates
        for key in ("p4_condition", "test_protocol", "market", "price_type")
        if (value := _text(candidate, key))
    }
    requested = {condition for condition in conditions if condition and condition in folded}
    if not requested:
        return candidates
    output: list[RetrievalCandidate] = []
    for candidate in candidates:
        relation = _text(candidate, "p4_relation_type").upper()
        if relation != "CONDITIONAL_VARIANT":
            output.append(candidate)
            continue
        candidate_conditions = {
            _fold(value)
            for key in ("p4_condition", "test_protocol", "market", "price_type")
            if (value := _text(candidate, key))
        }
        if candidate_conditions & requested:
            output.append(candidate)
    return tuple(output)


def _visible(candidate: RetrievalCandidate, filters: RetrievalFilters) -> bool:
    if filters.document_ids is not None and candidate.chunk.document_id not in filters.document_ids:
        return False
    owner_id = _text(candidate, "owner_id")
    if owner_id and owner_id != filters.owner_id:
        return False
    notebook_id = _text(candidate, "notebook_id")
    return not (
        filters.notebook_id is not None and notebook_id and notebook_id != filters.notebook_id
    )


def _lifecycle_visible(candidate: RetrievalCandidate, query: str) -> bool:
    status = _text(candidate, "document_status").casefold()
    if status not in _INACTIVE_STATUSES:
        return True
    return status == "archived" and bool(_YEAR.search(query))


def _conflict_member_ids(candidates: tuple[RetrievalCandidate, ...]) -> tuple[str, ...]:
    groups: dict[str, list[str]] = {}
    for candidate in candidates:
        group = _text(candidate, "conflict_group_id")
        if group:
            groups.setdefault(group, []).append(candidate.chunk.id)
    return tuple(
        sorted(item for members in groups.values() if len(members) > 1 for item in members)
    )


def _with_visible_provenance(
    representative: RetrievalCandidate,
    members: tuple[RetrievalCandidate, ...],
) -> RetrievalCandidate:
    metadata = dict(representative.chunk.metadata)
    existing_chunk_ids = _json_string_values(metadata.get("p4_provenance_chunk_ids"))
    existing_document_ids = _json_string_values(metadata.get("p4_provenance_document_ids"))
    chunk_ids = sorted({*existing_chunk_ids, *(item.chunk.id for item in members)})
    document_ids = sorted(
        {*existing_document_ids, *(item.chunk.document_id for item in members)}
    )
    metadata.update(
        {
            "p4_provenance_chunk_ids": json.dumps(
                chunk_ids, separators=(",", ":")
            ),
            "p4_provenance_document_ids": json.dumps(
                document_ids, separators=(",", ":")
            ),
            "p4_provenance_count": len(chunk_ids),
            "p4_relation_policy_version": RETRIEVAL_POLICY_VERSION,
        }
    )
    return replace(representative, chunk=replace(representative.chunk, metadata=metadata))


def _representative_key(candidate: RetrievalCandidate) -> tuple[int, int, float, int, str]:
    status = _text(candidate, "document_status").casefold()
    active_rank = 0 if status not in _INACTIVE_STATUSES else 1
    current_rank = 0 if _truthy(candidate, "is_current") else 1
    score = candidate.score if math.isfinite(candidate.score) else float("-inf")
    authority = _integer(candidate, "authority_level") or 0
    return (active_rank, current_rank, -score, -authority, candidate.chunk.id)


def _latest_deterministic(
    members: list[tuple[int, RetrievalCandidate]],
) -> tuple[int, RetrievalCandidate] | None:
    ranked: list[tuple[tuple[int, int], tuple[int, RetrievalCandidate]]] = []
    for item in members:
        candidate = item[1]
        year = _candidate_year(candidate)
        version = _integer(candidate, "version_number") or _integer(candidate, "document_version")
        if year is None and version is None:
            return None
        ranked.append(((year or -1, version or -1), item))
    ranked.sort(key=lambda item: (item[0], item[1][1].chunk.id))
    if len(ranked) > 1 and ranked[-1][0] == ranked[-2][0]:
        return None
    return ranked[-1][1]


def _best(members: list[tuple[int, RetrievalCandidate]]) -> tuple[int, RetrievalCandidate]:
    return min(members, key=lambda item: _representative_key(item[1]))


def _members_by_document(
    members: list[tuple[int, RetrievalCandidate]],
) -> dict[str, list[tuple[int, RetrievalCandidate]]]:
    output: dict[str, list[tuple[int, RetrievalCandidate]]] = {}
    for item in members:
        output.setdefault(item[1].chunk.document_id, []).append(item)
    return output


def _candidate_year(candidate: RetrievalCandidate) -> int | None:
    for key in ("reference_year", "year", "effective_year"):
        value = _integer(candidate, key)
        if value is not None:
            return value
    effective = _text(candidate, "effective_from")
    match = re.match(r"(20\d{2})", effective)
    return int(match.group(1)) if match else None


def _factual_group_key(candidate: RetrievalCandidate) -> str:
    for key in (
        "p4_exact_duplicate_group_id",
        "exact_duplicate_group_id",
        "near_duplicate_group_id",
        "version_family_id",
        "conflict_group_id",
    ):
        if value := _text(candidate, key):
            return f"{key}:{value}"
    return f"chunk:{candidate.chunk.id}"


def _is_uncertain(candidate: RetrievalCandidate) -> bool:
    return _text(candidate, "p4_relation_type").upper() == "UNCERTAIN"


def _truthy(candidate: RetrievalCandidate, key: str) -> bool:
    value = candidate.chunk.metadata.get(key)
    return value is True or str(value).casefold() in {"true", "1", "yes"}


def _integer(candidate: RetrievalCandidate, key: str) -> int | None:
    value = candidate.chunk.metadata.get(key)
    if isinstance(value, bool) or not isinstance(value, str | int | float):
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _text(candidate: RetrievalCandidate, key: str) -> str:
    return candidate.chunk.typed_metadata.text(key) or ""


def _first_text(candidate: RetrievalCandidate, keys: tuple[str, ...]) -> str:
    return next((value for key in keys if (value := _text(candidate, key))), "")


def _fold(value: str) -> str:
    normalized = unicodedata.normalize("NFKD", value.casefold()).replace("đ", "d")
    return " ".join(
        "".join(
            character for character in normalized if not unicodedata.combining(character)
        ).split()
    )


def _json_string_values(value: object) -> tuple[str, ...]:
    if not isinstance(value, str):
        return ()
    try:
        payload = json.loads(value)
    except (TypeError, ValueError):
        return ()
    if not isinstance(payload, list):
        return ()
    return tuple(item for item in payload if isinstance(item, str))


__all__ = [
    "RelationPolicyDiagnostics",
    "RelationPolicyMode",
    "RelationPolicyResult",
    "RetrievalPolicyConfig",
    "apply_relation_aware_policy",
    "document_diversity_at_k",
    "duplicate_redundancy_at_k",
    "unique_evidence_at_k",
]
