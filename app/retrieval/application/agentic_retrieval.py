"""Agentic retrieval use case — the single loop described in retrieval_SPEC.html."""

from __future__ import annotations

import json
import logging
import math
from dataclasses import dataclass, field, replace
from typing import Literal

from app.infrastructure.telemetry import Telemetry
from app.retrieval.application.relation_policy import (
    RetrievalPolicyConfig,
    apply_relation_aware_policy,
)
from app.retrieval.domain.models import (
    AgenticRetrievalResult,
    AgenticRetrievalRound,
    RetrievalCandidate,
    RetrievalFilters,
    SufficiencyCheck,
)
from app.retrieval.ports.reformulation_port import QueryReformulatorPort
from app.retrieval.ports.relation_metadata_port import RelationMetadataPort
from app.retrieval.ports.reranker_port import RerankerPort
from app.retrieval.ports.retrieval_port import RetrievalPort
from app.retrieval.ports.sufficiency_port import SufficiencyCheckerPort

DEFAULT_MAX_ROUNDS = 3
LOGGER = logging.getLogger(__name__)
_ALIAS_CHUNK_IDS_KEY = "duplicate_source_chunk_ids"
_ALIAS_DOCUMENT_IDS_KEY = "duplicate_source_document_ids"
_ALIAS_COUNT_KEY = "duplicate_source_count"
_COVERAGE_METADATA_KEYS = (
    "coverage",
    "retrieval_coverage",
    "document_probe_coverage",
)


@dataclass(frozen=True, slots=True)
class _QualityGroup:
    members: tuple[RetrievalCandidate, ...]
    representative: RetrievalCandidate


@dataclass(frozen=True)
class AgenticRetrievalUseCase:
    """score_threshold (SPEC step ⑧) drops low-scoring candidates before working memory."""

    retrieval_port: RetrievalPort
    sufficiency_checker: SufficiencyCheckerPort
    reformulator: QueryReformulatorPort
    reranker: RerankerPort | None = None
    max_rounds: int = DEFAULT_MAX_ROUNDS
    score_threshold: float | None = None
    # Candidates to search for before reranking down to top_k — a diversity
    # reranker (Layer 3 MMR) needs a wider pool than the final top_k to have
    # anything to pick diversity from.
    rerank_pool_size: int | None = None
    max_chunks_per_document: int | None = None
    knowledge_quality_mode: Literal["off", "shadow", "on"] = "off"
    relation_metadata_port: RelationMetadataPort | None = field(
        default=None,
        compare=False,
        repr=False,
    )
    relation_policy_config: RetrievalPolicyConfig = field(
        default_factory=RetrievalPolicyConfig,
        compare=False,
        repr=False,
    )
    telemetry: Telemetry = field(default_factory=Telemetry, compare=False, repr=False)

    def run(
        self,
        *,
        original_question: str,
        filters: RetrievalFilters,
        top_k: int,
    ) -> AgenticRetrievalResult:
        """Retrieve evidence, retrying with reformulated queries until sufficient."""
        if self.max_rounds <= 0:
            raise ValueError("max_rounds must be > 0")
        if top_k <= 0:
            raise ValueError("top_k must be > 0")
        if self.max_chunks_per_document is not None and self.max_chunks_per_document <= 0:
            raise ValueError("max_chunks_per_document must be > 0")
        if self.knowledge_quality_mode not in {"off", "shadow", "on"}:
            raise ValueError("knowledge_quality_mode must be off, shadow, or on")

        with self.telemetry.observe(
            "retrieval.agentic_loop",
            as_type="agent",
            input={
                "question": self.telemetry.content(original_question),
                "top_k": top_k,
                "max_rounds": self.max_rounds,
                "score_threshold": self.score_threshold,
                "knowledge_quality_mode": self.knowledge_quality_mode,
            },
        ) as root_observation:
            accumulated: dict[str, RetrievalCandidate] = {}
            quality_members: dict[str, RetrievalCandidate] = {}
            observed_quality_keys: set[str] = set()
            exact_duplicate_observations = 0
            trace: list[AgenticRetrievalRound] = []
            query = original_question

            search_top_k = top_k
            if self.reranker is not None and self.rerank_pool_size is not None:
                search_top_k = max(top_k, self.rerank_pool_size)

            for round_index in range(1, self.max_rounds + 1):
                with self.telemetry.observe(
                    f"retrieval.round.{round_index}",
                    as_type="chain",
                    input={
                        "query": self.telemetry.content(query),
                        "search_top_k": search_top_k,
                    },
                    metadata={"round": round_index},
                ) as round_observation:
                    candidates = self.retrieval_port.search(query, filters, top_k=search_top_k)
                    retrieved_count = len(candidates)
                    relation_metadata_status = "off"
                    shadow_relation_candidates: dict[str, RetrievalCandidate] = {}
                    if (
                        self.knowledge_quality_mode != "off"
                        and self.relation_metadata_port is not None
                    ):
                        try:
                            enriched = self.relation_metadata_port.enrich(candidates, filters)
                            relation_metadata_status = "enriched"
                            if self.knowledge_quality_mode == "on":
                                candidates = enriched
                            else:
                                shadow_relation_candidates = {
                                    item.chunk.id: item for item in enriched
                                }
                        except Exception:
                            relation_metadata_status = "failed_open"
                            LOGGER.exception(
                                "P4 relation metadata enrichment failed; using base retrieval"
                            )
                    round_quality_groups: dict[str, _QualityGroup] = {}
                    if self.knowledge_quality_mode == "on":
                        for candidate in candidates:
                            quality_key = _evidence_key(
                                candidate,
                                collapse_exact_duplicates=True,
                            )
                            identity_key = _evidence_key(
                                candidate,
                                collapse_exact_duplicates=False,
                            )
                            if quality_key != identity_key and quality_key in observed_quality_keys:
                                exact_duplicate_observations += 1
                            observed_quality_keys.add(quality_key)
                        groups = _collapse_quality_groups(candidates)
                        candidates = tuple(group.representative for group in groups)
                        round_quality_groups = {
                            group.representative.chunk.id: group for group in groups
                        }
                    if self.reranker is not None:
                        rerank_top_k = (
                            search_top_k if self.max_chunks_per_document is not None else top_k
                        )
                        with self.telemetry.observe(
                            "retrieval.mmr_rerank",
                            as_type="chain",
                            input={
                                "candidate_count": len(candidates),
                                "top_k": top_k,
                            },
                        ) as observation:
                            candidates = self.reranker.rerank(query, candidates, top_k=rerank_top_k)
                            observation.update(
                                output={
                                    "candidate_count": len(candidates),
                                    "chunk_ids": [candidate.chunk.id for candidate in candidates],
                                }
                            )
                    before_threshold = len(candidates)
                    if self.score_threshold is not None:
                        candidates = tuple(
                            candidate
                            for candidate in candidates
                            if candidate.score >= self.score_threshold
                        )
                    relation_policy_input = (
                        tuple(
                            shadow_relation_candidates.get(item.chunk.id, item)
                            for item in candidates
                        )
                        if self.knowledge_quality_mode == "shadow"
                        else candidates
                    )
                    relation_policy = apply_relation_aware_policy(
                        relation_policy_input,
                        query=original_question,
                        filters=filters,
                        mode=self.knowledge_quality_mode,
                        config=self.relation_policy_config,
                    )
                    if self.knowledge_quality_mode == "on":
                        candidates = relation_policy.evidence
                    document_cap = (
                        None
                        if filters.document_ids is not None and len(filters.document_ids) == 1
                        else self.max_chunks_per_document
                    )
                    candidates = _apply_document_cap(
                        candidates,
                        top_k=top_k,
                        max_per_document=document_cap,
                    )

                    if self.knowledge_quality_mode == "on":
                        previous_evidence = tuple(accumulated.values())
                        for candidate in candidates:
                            group = round_quality_groups.get(candidate.chunk.id)
                            members = group.members if group is not None else (candidate,)
                            for member in members:
                                previous = quality_members.get(member.chunk.id)
                                if previous is None or _candidate_is_better(
                                    member,
                                    previous,
                                ):
                                    quality_members[member.chunk.id] = member

                        collapsed = tuple(
                            group.representative
                            for group in _collapse_quality_groups(tuple(quality_members.values()))
                        )
                        collapsed = apply_relation_aware_policy(
                            collapsed,
                            query=original_question,
                            filters=filters,
                            mode="on",
                            config=self.relation_policy_config,
                        ).evidence
                        evidence = _apply_document_cap(
                            collapsed,
                            top_k=None,
                            max_per_document=document_cap,
                        )
                        accumulated = {
                            f"quality:{position}": candidate
                            for position, candidate in enumerate(evidence)
                        }
                        new_evidence_count = _count_new_quality_evidence(
                            previous_evidence,
                            evidence,
                        )
                    else:
                        new_evidence_count = 0
                        for candidate in candidates:
                            quality_key = _evidence_key(
                                candidate,
                                collapse_exact_duplicates=True,
                            )
                            identity_key = _evidence_key(
                                candidate,
                                collapse_exact_duplicates=False,
                            )
                            if quality_key != identity_key and quality_key in observed_quality_keys:
                                exact_duplicate_observations += 1
                            observed_quality_keys.add(quality_key)
                            previous = accumulated.get(identity_key)
                            if previous is None and _can_add_document_evidence(
                                accumulated,
                                candidate,
                                document_cap,
                            ):
                                accumulated[identity_key] = candidate
                                new_evidence_count += 1
                            elif previous is not None and candidate.score > previous.score:
                                accumulated[identity_key] = candidate

                        evidence = tuple(accumulated.values())
                    with self.telemetry.observe(
                        "retrieval.sufficiency_check",
                        as_type="evaluator",
                        input={
                            "question": self.telemetry.content(original_question),
                            "evidence_count": len(evidence),
                        },
                    ) as observation:
                        check: SufficiencyCheck = self.sufficiency_checker.check(
                            original_question, evidence
                        )
                        observation.update(
                            output={
                                "sufficient": check.sufficient,
                                "missing": self.telemetry.content(check.missing),
                            }
                        )
                    trace.append(
                        AgenticRetrievalRound(
                            round_index=round_index,
                            query_used=query,
                            new_evidence_count=new_evidence_count,
                            sufficiency=check,
                        )
                    )
                    round_observation.update(
                        output={
                            "retrieved_count": retrieved_count,
                            "before_threshold_count": before_threshold,
                            "candidate_count": len(candidates),
                            "new_evidence_count": new_evidence_count,
                            "accumulated_evidence_count": len(evidence),
                            "exact_duplicate_observations": exact_duplicate_observations,
                            "quality_mode": self.knowledge_quality_mode,
                            "p4_relation_policy": {
                                "proposed_retained_ids": list(
                                    relation_policy.diagnostics.proposed_retained_ids
                                ),
                                "suppressed_duplicate_ids": list(
                                    relation_policy.diagnostics.suppressed_duplicate_ids
                                ),
                                "selected_version_ids": list(
                                    relation_policy.diagnostics.selected_version_ids
                                ),
                                "preserved_conflict_ids": list(
                                    relation_policy.diagnostics.preserved_conflict_ids
                                ),
                                "reason_codes": list(relation_policy.diagnostics.reason_codes),
                                "latency_ms": relation_policy.diagnostics.latency_ms,
                                "metadata_enrichment_status": relation_metadata_status,
                            },
                            "sufficient": check.sufficient,
                        }
                    )

                if check.sufficient:
                    result = AgenticRetrievalResult(
                        evidence=evidence,
                        rounds_used=round_index,
                        gave_up=False,
                        trace=tuple(trace),
                    )
                    root_observation.update(
                        output={
                            "rounds_used": round_index,
                            "gave_up": False,
                            "evidence_count": len(evidence),
                            "exact_duplicate_observations": exact_duplicate_observations,
                            "quality_mode": self.knowledge_quality_mode,
                        }
                    )
                    return result

                if round_index == self.max_rounds:
                    result = AgenticRetrievalResult(
                        evidence=evidence,
                        rounds_used=round_index,
                        gave_up=True,
                        trace=tuple(trace),
                    )
                    root_observation.update(
                        output={
                            "rounds_used": round_index,
                            "gave_up": True,
                            "evidence_count": len(evidence),
                            "exact_duplicate_observations": exact_duplicate_observations,
                            "quality_mode": self.knowledge_quality_mode,
                        },
                        level="WARNING",
                        status_message="Maximum retrieval rounds reached",
                    )
                    return result

                with self.telemetry.observe(
                    "retrieval.reformulate",
                    as_type="chain",
                    input={
                        "original_question": self.telemetry.content(original_question),
                        "missing": self.telemetry.content(check.missing),
                    },
                ) as observation:
                    query = self.reformulator.reformulate(
                        original_question=original_question,
                        evidence=evidence,
                        missing=check.missing,
                    )
                    observation.update(output={"reformulated_query": self.telemetry.content(query)})

        raise AssertionError("unreachable: loop always returns within max_rounds")


def _evidence_key(
    candidate: RetrievalCandidate,
    *,
    collapse_exact_duplicates: bool,
) -> str:
    if collapse_exact_duplicates:
        group_id = _metadata_text(
            candidate,
            "exact_duplicate_group_id",
        )
        if group_id:
            return f"exact-group:{group_id}"
        checksum = _metadata_text(candidate, "checksum")
        if checksum:
            return f"checksum:{checksum}"
    return f"id:{candidate.chunk.id}"


def _collapse_quality_groups(
    candidates: tuple[RetrievalCandidate, ...],
) -> tuple[_QualityGroup, ...]:
    """Collapse exact aliases, then adjacent chunks, without joining their text."""
    if not candidates:
        return ()

    unique: dict[str, tuple[int, RetrievalCandidate]] = {}
    for position, candidate in enumerate(candidates):
        previous = unique.get(candidate.chunk.id)
        if previous is None:
            unique[candidate.chunk.id] = (position, candidate)
        elif _candidate_is_better(candidate, previous[1]):
            unique[candidate.chunk.id] = (previous[0], candidate)

    ordered = sorted(unique.values(), key=lambda item: item[0])
    first_position = {candidate.chunk.id: position for position, candidate in ordered}
    exact_groups_by_key: dict[str, list[RetrievalCandidate]] = {}
    for _, candidate in ordered:
        exact_groups_by_key.setdefault(
            _evidence_key(candidate, collapse_exact_duplicates=True),
            [],
        ).append(candidate)
    exact_groups = tuple(tuple(members) for members in exact_groups_by_key.values())

    parent = list(range(len(exact_groups)))

    def find(group_index: int) -> int:
        while parent[group_index] != group_index:
            parent[group_index] = parent[parent[group_index]]
            group_index = parent[group_index]
        return group_index

    def union(left: int, right: int) -> None:
        left_root, right_root = find(left), find(right)
        if left_root != right_root:
            parent[right_root] = left_root

    positions_by_document: dict[str, dict[int, set[int]]] = {}
    for group_index, members in enumerate(exact_groups):
        # A multi-member exact group can represent several independent
        # neighbourhoods, even inside one document (for example repeated
        # headers). Let exact collapse win instead of using that group as a
        # bridge between unrelated adjacent chunks.
        if len(members) != 1:
            continue
        for candidate in members:
            chunk_index = _chunk_index(candidate)
            if chunk_index is None:
                continue
            positions_by_document.setdefault(
                candidate.chunk.document_id,
                {},
            ).setdefault(chunk_index, set()).add(group_index)

    for indexes in positions_by_document.values():
        for chunk_index, left_groups in indexes.items():
            right_groups = indexes.get(chunk_index + 1, set())
            for left_group in left_groups:
                for right_group in right_groups:
                    union(left_group, right_group)

    components: dict[int, list[RetrievalCandidate]] = {}
    for group_index, members in enumerate(exact_groups):
        components.setdefault(find(group_index), []).extend(members)

    grouped: list[tuple[int, _QualityGroup]] = []
    for component_members in components.values():
        component_members.sort(key=lambda item: first_position[item.chunk.id])
        representative = min(
            component_members,
            key=_candidate_selection_key,
        )
        enriched = _with_alias_provenance(
            representative,
            tuple(component_members),
        )
        grouped.append(
            (
                min(first_position[item.chunk.id] for item in component_members),
                _QualityGroup(
                    members=tuple(component_members),
                    representative=enriched,
                ),
            )
        )
    grouped.sort(key=lambda item: item[0])
    return tuple(group for _, group in grouped)


def _candidate_is_better(
    candidate: RetrievalCandidate,
    previous: RetrievalCandidate,
) -> bool:
    return _candidate_selection_key(candidate) < _candidate_selection_key(previous)


def _candidate_selection_key(
    candidate: RetrievalCandidate,
) -> tuple[float, float, int, str, str]:
    score = candidate.score if math.isfinite(candidate.score) else float("-inf")
    return (
        -score,
        -_candidate_coverage(candidate),
        candidate.rank,
        candidate.chunk.id,
        candidate.chunk.document_id,
    )


def _candidate_coverage(candidate: RetrievalCandidate) -> float:
    values: list[float] = []
    for key in _COVERAGE_METADATA_KEYS:
        raw = _metadata_text(candidate, key)
        if not raw:
            continue
        try:
            value = float(raw)
        except ValueError:
            continue
        if math.isfinite(value):
            values.append(value)
    return max(values, default=0.0)


def _chunk_index(candidate: RetrievalCandidate) -> int | None:
    value = candidate.chunk.typed_metadata.chunk_index
    if value is None:
        return None
    return value if value >= 0 else None


def _metadata_text(candidate: RetrievalCandidate, key: str) -> str:
    return candidate.chunk.typed_metadata.text(key) or ""


def _with_alias_provenance(
    representative: RetrievalCandidate,
    members: tuple[RetrievalCandidate, ...],
) -> RetrievalCandidate:
    """Rebuild aliases only from candidates already returned inside scope."""
    chunk_ids = sorted({candidate.chunk.id for candidate in members})
    document_ids = sorted({candidate.chunk.document_id for candidate in members})
    metadata = {
        key: value
        for key, value in representative.chunk.metadata.items()
        if not key.startswith("duplicate_source_")
    }
    metadata.update(
        {
            _ALIAS_CHUNK_IDS_KEY: json.dumps(
                chunk_ids,
                ensure_ascii=True,
                separators=(",", ":"),
            ),
            _ALIAS_DOCUMENT_IDS_KEY: json.dumps(
                document_ids,
                ensure_ascii=True,
                separators=(",", ":"),
            ),
            _ALIAS_COUNT_KEY: str(len(chunk_ids)),
        }
    )
    return replace(
        representative,
        chunk=replace(representative.chunk, metadata=metadata),
    )


def _alias_chunk_ids(candidate: RetrievalCandidate) -> frozenset[str]:
    raw = _metadata_text(candidate, _ALIAS_CHUNK_IDS_KEY)
    if raw:
        try:
            parsed = json.loads(raw)
        except json.JSONDecodeError:
            parsed = None
        if isinstance(parsed, list) and all(isinstance(item, str) for item in parsed):
            return frozenset(parsed)
    return frozenset({candidate.chunk.id})


def _count_new_quality_evidence(
    previous: tuple[RetrievalCandidate, ...],
    current: tuple[RetrievalCandidate, ...],
) -> int:
    previous_source_ids = frozenset(
        source_id for candidate in previous for source_id in _alias_chunk_ids(candidate)
    )
    return sum(_alias_chunk_ids(candidate).isdisjoint(previous_source_ids) for candidate in current)


def _apply_document_cap(
    candidates: tuple[RetrievalCandidate, ...],
    *,
    top_k: int | None,
    max_per_document: int | None,
) -> tuple[RetrievalCandidate, ...]:
    selected: list[RetrievalCandidate] = []
    counts: dict[str, int] = {}
    for candidate in candidates:
        document_id = candidate.chunk.document_id
        if max_per_document is not None and counts.get(document_id, 0) >= max_per_document:
            continue
        selected.append(candidate)
        counts[document_id] = counts.get(document_id, 0) + 1
        if top_k is not None and len(selected) >= top_k:
            break
    return tuple(selected)


def _can_add_document_evidence(
    accumulated: dict[str, RetrievalCandidate],
    candidate: RetrievalCandidate,
    max_per_document: int | None,
) -> bool:
    if max_per_document is None:
        return True
    document_id = candidate.chunk.document_id
    return (
        sum(item.chunk.document_id == document_id for item in accumulated.values())
        < max_per_document
    )


__all__ = ["DEFAULT_MAX_ROUNDS", "AgenticRetrievalUseCase"]
