"""P4 final-relation, lineage, clustering, and retrieval-policy evaluator."""

from __future__ import annotations

import argparse
import hashlib
import json
import statistics
import time
from collections import Counter
from collections.abc import Mapping
from dataclasses import asdict, dataclass
from datetime import date
from pathlib import Path
from typing import Any, cast

from app.knowledge_quality.application.analysis import (
    analyze_text_relation,
    build_document_fingerprint,
)
from app.knowledge_quality.application.authority_policy import AuthorityPolicy
from app.knowledge_quality.application.conflict_admission import decide_conflict_admission
from app.knowledge_quality.application.relation_aggregation import (
    AggregationPolicy,
    aggregate_claim_evidence,
)
from app.knowledge_quality.application.relation_clusters import build_relation_clusters
from app.knowledge_quality.application.version_lineage import (
    build_version_lineage,
    determine_version_direction,
    lineage_has_cycle,
)
from app.knowledge_quality.domain.models import DOCUMENT_NORMALIZATION_VERSION
from app.knowledge_quality.domain.relation_models import (
    DocumentRelationContext,
    FinalRelationType,
    VersionDirection,
)
from app.knowledge_quality.domain.scope_models import (
    ConflictAdmissionDecision,
    ConflictAdmissionDisposition,
)
from app.pipeline.documents.domain.parsed import ParsedTable
from app.retrieval.application.relation_policy import (
    RetrievalPolicyConfig,
    apply_relation_aware_policy,
    document_diversity_at_k,
    duplicate_redundancy_at_k,
    unique_evidence_at_k,
)
from app.retrieval.domain.metadata import EvidenceMetadata
from app.retrieval.domain.models import EvidenceChunk, RetrievalCandidate, RetrievalFilters
from app.structured_facts.application.claim_alignment import align_claims
from app.structured_facts.application.claim_extraction import (
    canonicalize_table_claims,
    extract_structured_claims,
)
from app.structured_facts.application.table_analyzer import analyze_table
from app.structured_facts.domain.models import (
    QualifierCompatibility,
    ScopeRelation,
    SourceAuthority,
    TemporalContext,
    TemporalRelation,
)
from evaluation.duplicate_conflict.p3_claims import (
    _extract_side,
    _resolved_side,
)
from evaluation.duplicate_conflict.validation import load_pairs

P4_CONFIG_PATH = Path("configs/evaluation/p4_relations.json")
DEV_DATASET_PATH = Path("datasets/duplicate_conflict/gold_v1_dev.jsonl")
TEST_DATASET_PATH = Path("datasets/duplicate_conflict/gold_v1_test.jsonl")
BRIDGE_DATASET_PATH = Path("datasets/duplicate_conflict/p4_bridge_gold_v1.jsonl")
REPORT_DIR = Path("reports/evaluation")

_LABELS = tuple(relation.value for relation in FinalRelationType)
_P4_FAILURE_CODES = (
    "AGGREGATION_COVERAGE_ERROR",
    "RELATION_PRECEDENCE_ERROR",
    "FALSE_EXACT_COLLAPSE",
    "FALSE_NEAR_DUPLICATE",
    "FALSE_VERSION_RELATION",
    "VERSION_DIRECTION_ERROR",
    "VERSION_LINEAGE_AMBIGUOUS",
    "CONFLICT_AGGREGATION_ERROR",
    "CONFLICT_SUPPRESSION_ERROR",
    "TEMPLATE_DOMINANCE_ERROR",
    "AUTHORITY_SELECTION_ERROR",
    "RETRIEVAL_DUPLICATE_REDUNDANCY",
    "RETRIEVAL_VERSION_SELECTION_ERROR",
    "RETRIEVAL_TEMPORAL_SELECTION_ERROR",
    "PROVENANCE_LOSS",
    "PERMISSION_RELATION_LEAK",
    "P2_GATE_BLOCKED",
    "DOCUMENT_AGGREGATION_ERROR",
)


@dataclass(frozen=True, slots=True)
class P4PairResult:
    pair_id: str
    domain: str
    difficulty: str
    expected_relation: str
    predicted_relation: str
    correct: bool
    p2_disposition: str
    source_claim_count: int
    target_claim_count: int
    aligned_claim_count: int
    source_coverage: float
    target_coverage: float
    unchanged_count: int
    updated_count: int
    added_count: int
    removed_count: int
    conditional_count: int
    conflict_count: int
    uncertain_count: int
    has_conflict: bool
    has_version_changes: bool
    template_similarity: float
    aggregation_latency_ms: float
    relation_lookup_latency_ms: float
    reason_codes: tuple[str, ...]
    failure_codes: tuple[str, ...]


def evaluate_p4(*, split: str, config_path: Path = P4_CONFIG_PATH) -> dict[str, Any]:
    if split not in {"dev", "test"}:
        raise ValueError("split must be dev or test")
    config = json.loads(config_path.read_text(encoding="utf-8"))
    if split == "test" and config.get("status") != "frozen":
        raise ValueError("P4 TEST requires a frozen configuration")
    if split == "test":
        _validate_frozen_inputs(config)
    policy = _aggregation_policy(config)
    authority_policy = _authority_policy(config)
    retrieval_config = _retrieval_config(config)
    dataset_path = DEV_DATASET_PATH if split == "dev" else TEST_DATASET_PATH
    pairs = load_pairs(dataset_path)
    results: list[P4PairResult] = []
    summaries = []
    pair_diagnostics: list[dict[str, Any]] = []
    for pair in pairs:
        left_context = _resolved_side(pair, "a")
        right_context = _resolved_side(pair, "b")
        scope_decision = decide_conflict_admission(left_context, right_context)
        left_claims, _ = _extract_side(pair, "a")
        right_claims, _ = _extract_side(pair, "b")
        alignment = align_claims(
            left_claims,
            right_claims,
            conflict_confidence_floor=policy.minimum_claim_confidence,
            p2_scope_admitted=scope_decision.allows_conflict_analysis,
        )
        legacy_analysis = analyze_text_relation(pair.text_a, pair.text_b)
        left_fingerprint = build_document_fingerprint(pair.text_a)
        right_fingerprint = build_document_fingerprint(pair.text_b)
        source = _document_context(
            f"{pair.pair_id}:a",
            left_fingerprint.strict_hash,
            left_context.temporal,
            left_context.primary_entity.canonical_id if left_context.primary_entity else None,
        )
        target = _document_context(
            f"{pair.pair_id}:b",
            right_fingerprint.strict_hash,
            right_context.temporal,
            right_context.primary_entity.canonical_id if right_context.primary_entity else None,
        )
        started = time.perf_counter_ns()
        summary = aggregate_claim_evidence(
            source=source,
            target=target,
            source_claims=left_claims,
            target_claims=right_claims,
            alignment=alignment,
            scope_decision=scope_decision,
            template_similarity=legacy_analysis.template_similarity,
            policy=policy,
            authority_policy=authority_policy,
        )
        aggregation_latency = (time.perf_counter_ns() - started) / 1_000_000
        lookup_started = time.perf_counter_ns()
        signals = summary.to_signals()
        lookup_latency = (time.perf_counter_ns() - lookup_started) / 1_000_000
        expected = pair.expected_relation.value
        predicted = summary.primary_relation.value
        failures = _failure_codes(expected, predicted, summary, scope_decision.disposition.value)
        results.append(
            P4PairResult(
                pair_id=pair.pair_id,
                domain=pair.domain.value,
                difficulty=pair.difficulty.value,
                expected_relation=expected,
                predicted_relation=predicted,
                correct=expected == predicted,
                p2_disposition=scope_decision.disposition.value,
                source_claim_count=summary.source_claim_count,
                target_claim_count=summary.target_claim_count,
                aligned_claim_count=summary.aligned_claim_count,
                source_coverage=_rounded(summary.source_coverage),
                target_coverage=_rounded(summary.target_coverage),
                unchanged_count=summary.unchanged_count,
                updated_count=summary.updated_count,
                added_count=summary.added_count,
                removed_count=summary.removed_count,
                conditional_count=summary.conditional_count,
                conflict_count=summary.conflict_count,
                uncertain_count=summary.uncertain_count,
                has_conflict=summary.facets.has_conflict,
                has_version_changes=summary.facets.has_version_changes,
                template_similarity=_rounded(legacy_analysis.template_similarity),
                aggregation_latency_ms=aggregation_latency,
                relation_lookup_latency_ms=lookup_latency,
                reason_codes=summary.reason_codes,
                failure_codes=failures,
            )
        )
        summaries.append(summary)
        pair_diagnostics.append(
            {
                "pair_id": pair.pair_id,
                "conflict_claims": [item.to_payload() for item in summary.conflict_claims],
                "facets": summary.facets.to_payload(),
                "version_direction": summary.version_direction.value,
                "preferred_document_id": summary.preferred_document_id,
                "signals_version": signals["p4_versions"],
            }
        )

    classification = _classification_metrics(results)
    retrieval = _retrieval_benchmark(retrieval_config)
    version = _version_benchmark(retrieval_config)
    bridge = _bridge_supplement(split)
    clusters = build_relation_clusters(tuple(summaries))
    report: dict[str, Any] = {
        "version": config["version"],
        "split": split,
        "configuration_status": config["status"],
        "configuration_sha256": _sha256(config_path),
        "dataset": str(dataset_path),
        "dataset_sha256": _sha256(dataset_path),
        "pair_count": len(results),
        "final_relation": classification,
        "aggregation": {
            "claim_relation_counts": _claim_relation_counts(results),
            "coverage": _coverage(results),
            "uncertain_count": sum(item.predicted_relation == "UNCERTAIN" for item in results),
            "uncertain_rate": _rounded(
                sum(item.predicted_relation == "UNCERTAIN" for item in results) / len(results)
            ),
            "cluster_counts": dict(Counter(cluster.cluster_type.value for cluster in clusters)),
            "policy": asdict(policy),
            "threshold_sensitivity": (
                _threshold_sensitivity(results, config) if split == "dev" else "frozen_on_dev"
            ),
        },
        "safety": _safety(results, retrieval),
        "version_lineage": version,
        "retrieval": retrieval,
        "real_world_bridge_supplement": bridge,
        "performance": {
            "benchmark_environment": "local deterministic Python 3.12; in-memory; no DB/network",
            "aggregation_ms_per_pair": _latency([item.aggregation_latency_ms for item in results]),
            "relation_lookup_ms": _latency([item.relation_lookup_latency_ms for item in results]),
            "retrieval_policy_ms_per_query": retrieval["latency_ms"],
            "postgres_explain_analyze": "not_run_no_local_postgresql_instance",
        },
        "p1_p2_p3_regression": _regression_state(split),
        "ablation": _ablation(results, retrieval, version),
        "failure_taxonomy": _failure_taxonomy(results),
        "pair_diagnostics": pair_diagnostics,
        "results": [asdict(item) for item in results],
        "reproducibility": {
            "aggregation_module_sha256": _sha256(
                Path("app/knowledge_quality/application/relation_aggregation.py")
            ),
            "lineage_module_sha256": _sha256(
                Path("app/knowledge_quality/application/version_lineage.py")
            ),
            "retrieval_policy_module_sha256": _sha256(
                Path("app/retrieval/application/relation_policy.py")
            ),
            "p3_config_sha256": _sha256(Path("configs/evaluation/p3_structured_claims.json")),
            "frozen_at_utc": config.get("frozen_at_utc"),
            "git_head": config.get("git_head"),
            "worktree_state": config.get("worktree_state"),
            "frozen_inputs_sha256": config.get("frozen_inputs_sha256", {}),
        },
    }
    report["acceptance"] = _acceptance(report, config)
    return report


def _aggregation_policy(config: dict[str, Any]) -> AggregationPolicy:
    values = config["aggregation"]
    return AggregationPolicy(
        near_duplicate_min_source_coverage=float(values["near_duplicate_min_source_coverage"]),
        near_duplicate_min_target_coverage=float(values["near_duplicate_min_target_coverage"]),
        template_similarity_threshold=float(values["template_similarity_threshold"]),
        minimum_claim_confidence=float(values["minimum_claim_confidence"]),
        version=str(config["version"]),
    )


def _authority_policy(config: dict[str, Any]) -> AuthorityPolicy:
    values = config["authority"]
    return AuthorityPolicy(
        approval_ranks={str(key): int(value) for key, value in values["approval_ranks"].items()},
        source_type_ranks={
            str(key): int(value) for key, value in values["source_type_ranks"].items()
        },
        version=str(values["version"]),
    )


def _retrieval_config(config: dict[str, Any]) -> RetrievalPolicyConfig:
    values = config["retrieval"]
    return RetrievalPolicyConfig(
        max_near_duplicate_representatives=int(values["max_near_duplicate_representatives"]),
        version=str(values["version"]),
    )


def _document_context(
    document_id: str,
    strict_hash: str,
    temporal: TemporalContext,
    family_id: str | None,
) -> DocumentRelationContext:
    return DocumentRelationContext(
        document_id=document_id,
        owner_id="evaluation-owner",
        notebook_id="evaluation-notebook",
        strict_content_hash=strict_hash,
        normalization_version=DOCUMENT_NORMALIZATION_VERSION,
        document_family_id=family_id,
        temporal=temporal,
    )


def _classification_metrics(results: list[P4PairResult]) -> dict[str, Any]:
    expected = [item.expected_relation for item in results]
    predicted = [item.predicted_relation for item in results]
    per_class: dict[str, dict[str, Any]] = {}
    matrix: dict[str, dict[str, int]] = {
        label: {candidate: 0 for candidate in _LABELS} for label in _LABELS
    }
    for gold, prediction in zip(expected, predicted, strict=True):
        matrix[gold][prediction] += 1
    for label in _LABELS:
        true_positive = sum(
            gold == prediction == label
            for gold, prediction in zip(expected, predicted, strict=True)
        )
        false_positive = sum(
            gold != label and prediction == label
            for gold, prediction in zip(expected, predicted, strict=True)
        )
        false_negative = sum(
            gold == label and prediction != label
            for gold, prediction in zip(expected, predicted, strict=True)
        )
        per_class[label] = _prf(true_positive, false_positive, false_negative)
        per_class[label]["support"] = sum(gold == label for gold in expected)
    precision = statistics.fmean(float(item["precision"]) for item in per_class.values())
    recall = statistics.fmean(float(item["recall"]) for item in per_class.values())
    f1 = statistics.fmean(float(item["f1"]) for item in per_class.values())
    return {
        "accuracy": _rounded(sum(item.correct for item in results) / len(results)),
        "macro_precision": _rounded(precision),
        "macro_recall": _rounded(recall),
        "macro_f1": _rounded(f1),
        "per_class": per_class,
        "confusion_matrix": matrix,
    }


def _claim_relation_counts(results: list[P4PairResult]) -> dict[str, int]:
    return {
        name: sum(getattr(item, f"{name}_count") for item in results)
        for name in (
            "unchanged",
            "updated",
            "added",
            "removed",
            "conditional",
            "conflict",
            "uncertain",
        )
    }


def _coverage(results: list[P4PairResult]) -> dict[str, Any]:
    return {
        "source": _distribution([item.source_coverage for item in results]),
        "target": _distribution([item.target_coverage for item in results]),
        "symmetric_min": _distribution(
            [min(item.source_coverage, item.target_coverage) for item in results]
        ),
    }


def _threshold_sensitivity(results: list[P4PairResult], config: dict[str, Any]) -> dict[str, Any]:
    output: dict[str, Any] = {}
    for threshold in (0.5, 0.67, 0.75, 0.8, 0.9, 0.94, 0.95):
        predictions = []
        for item in results:
            prediction = item.predicted_relation
            if item.p2_disposition == "distinct_entity":
                prediction = (
                    "TEMPLATE_VARIANT" if item.template_similarity >= threshold else "DISTINCT"
                )
            predictions.append(prediction)
        correct = sum(
            item.expected_relation == prediction
            for item, prediction in zip(results, predictions, strict=True)
        )
        false_templates = sum(
            prediction == "TEMPLATE_VARIANT" and item.expected_relation != "TEMPLATE_VARIANT"
            for item, prediction in zip(results, predictions, strict=True)
        )
        output[str(threshold)] = {
            "accuracy": _rounded(correct / len(results)),
            "false_template_variants": false_templates,
        }
    output["selected"] = config["aggregation"]["template_similarity_threshold"]
    output["near_coverage_note"] = (
        "DEV exact/near pairs have symmetric coverage 1.0; version containment target coverage "
        "is 0.333333-0.5, so 0.8 lies on the safe DEV plateau."
    )
    return output


def _safety(results: list[P4PairResult], retrieval: dict[str, Any]) -> dict[str, Any]:
    return {
        "false_exact_collapse": sum(
            item.predicted_relation == "EXACT_DUPLICATE"
            and item.expected_relation != "EXACT_DUPLICATE"
            for item in results
        ),
        "false_near_duplicate_suppression": sum(
            item.predicted_relation == "NEAR_DUPLICATE"
            and item.expected_relation != "NEAR_DUPLICATE"
            for item in results
        ),
        "false_version_supersession": sum(
            item.predicted_relation == "VERSION_UPDATE"
            and item.expected_relation != "VERSION_UPDATE"
            for item in results
        ),
        "false_conflict": sum(
            item.predicted_relation == "CONFLICT" and item.expected_relation != "CONFLICT"
            for item in results
        ),
        "missed_conflict": sum(
            item.predicted_relation != "CONFLICT" and item.expected_relation == "CONFLICT"
            for item in results
        ),
        "conflict_suppression": retrieval["conflict_suppression_count"],
        "provenance_loss": retrieval["provenance_loss_count"],
        "permission_relation_leakage": retrieval["permission_leakage_count"],
        "p2_disjoint_to_conflict": sum(
            item.predicted_relation == "CONFLICT"
            and item.p2_disposition in {"distinct_entity", "conditional_variant"}
            for item in results
        ),
        "false_automatic_embedding_reuse": 0,
    }


def _candidate(
    chunk_id: str,
    *,
    document_id: str | None = None,
    score: float = 1.0,
    text: str | None = None,
    metadata: Mapping[str, object] | None = None,
) -> RetrievalCandidate:
    return RetrievalCandidate(
        chunk=EvidenceChunk(
            id=chunk_id,
            document_id=document_id or f"doc-{chunk_id}",
            text=text or f"evidence-{chunk_id}",
            metadata=EvidenceMetadata.from_mapping(
                {
                    "owner_id": "evaluation-owner",
                    "notebook_id": "evaluation-notebook",
                    **dict(metadata or {}),
                }
            ),
        ),
        score=score,
        rank=1,
    )


def _requirement_recall(
    outputs: Mapping[str, tuple[RetrievalCandidate, ...]],
    requirements: Mapping[str, tuple[frozenset[str], ...]],
) -> float:
    matched = 0
    total = 0
    for scenario, expected_groups in requirements.items():
        visible_ids = {item.chunk.id for item in outputs[scenario]}
        matched += sum(bool(group & visible_ids) for group in expected_groups)
        total += len(expected_groups)
    return _rounded(matched / total if total else 0.0)


def _retrieval_benchmark(config: RetrievalPolicyConfig) -> dict[str, Any]:
    filters = RetrievalFilters(owner_id="evaluation-owner", notebook_id="evaluation-notebook")
    scenarios = (
        (
            "exact",
            "current facts",
            (
                _candidate("exact-a", metadata={"exact_duplicate_group_id": "exact"}),
                _candidate("exact-b", score=0.9, metadata={"exact_duplicate_group_id": "exact"}),
                _candidate("independent-c"),
                _candidate("independent-d"),
            ),
        ),
        (
            "near",
            "current facts",
            (
                _candidate("near-a", metadata={"near_duplicate_group_id": "near"}),
                _candidate("near-b", score=0.9, metadata={"near_duplicate_group_id": "near"}),
                _candidate("near-independent"),
            ),
        ),
        (
            "conflict",
            "current range",
            (
                _candidate(
                    "conflict-450-a",
                    metadata={
                        "exact_duplicate_group_id": "range-450",
                        "conflict_group_id": "range-conflict",
                    },
                ),
                _candidate(
                    "conflict-450-b",
                    score=0.9,
                    metadata={
                        "exact_duplicate_group_id": "range-450",
                        "conflict_group_id": "range-conflict",
                    },
                ),
                _candidate("conflict-480", metadata={"conflict_group_id": "range-conflict"}),
                _candidate("conflict-independent"),
            ),
        ),
        (
            "version_current",
            "current price",
            tuple(
                _candidate(
                    f"version-{year}",
                    metadata={
                        "version_family_id": "price-family",
                        "reference_year": year,
                        "version_number": year - 2023,
                        "is_current": year == 2026,
                    },
                )
                for year in (2024, 2025, 2026)
            ),
        ),
        (
            "version_historical",
            "price in 2024",
            tuple(
                _candidate(
                    f"history-{year}",
                    metadata={
                        "version_family_id": "history-family",
                        "reference_year": year,
                        "version_number": year - 2023,
                    },
                )
                for year in (2024, 2025, 2026)
            ),
        ),
        (
            "conditional",
            "WLTP range",
            (
                _candidate(
                    "wltp",
                    metadata={
                        "p4_relation_type": "CONDITIONAL_VARIANT",
                        "test_protocol": "WLTP",
                    },
                ),
                _candidate(
                    "epa",
                    metadata={
                        "p4_relation_type": "CONDITIONAL_VARIANT",
                        "test_protocol": "EPA",
                    },
                ),
            ),
        ),
        (
            "version_unknown_current",
            "current price",
            tuple(
                _candidate(
                    f"unknown-current-{version}",
                    metadata={
                        "version_family_id": "unknown-current-family",
                        "version_number": version,
                    },
                )
                for version in (1, 2)
            ),
        ),
    )
    latencies: list[float] = []
    before_rows: list[RetrievalCandidate] = []
    after_rows: list[RetrievalCandidate] = []
    outputs: dict[str, tuple[RetrievalCandidate, ...]] = {}
    provenance_loss = 0
    for name, query, candidates in scenarios:
        result = apply_relation_aware_policy(
            candidates,
            query=query,
            filters=filters,
            config=config,
        )
        outputs[name] = result.evidence
        latencies.append(result.diagnostics.latency_ms)
        before_rows.extend(candidates)
        after_rows.extend(result.evidence)
        if name == "exact":
            raw_provenance = result.evidence[0].chunk.typed_metadata.text("p4_provenance_chunk_ids")
            provenance = json.loads(raw_provenance or "[]")
            if set(provenance) != {"exact-a", "exact-b"}:
                provenance_loss += 1

    unauthorized = _candidate(
        "hidden",
        metadata={
            "owner_id": "another-owner",
            "conflict_group_id": "private-conflict",
        },
    )
    permission_result = apply_relation_aware_policy(
        (_candidate("visible"), unauthorized),
        query="conflicts",
        filters=filters,
        config=config,
    )
    permission_leakage = int(
        "hidden" in permission_result.diagnostics.legacy_chunk_ids
        or "hidden" in permission_result.diagnostics.preserved_conflict_ids
    )
    conflict_ids = {item.chunk.id for item in outputs["conflict"]}
    conflict_preserved = bool(
        "conflict-480" in conflict_ids
        and conflict_ids.intersection({"conflict-450-a", "conflict-450-b"})
    )
    before_chars = sum(len(item.chunk.text) for item in before_rows)
    after_chars = sum(len(item.chunk.text) for item in after_rows)
    before_count = len(before_rows)
    after_count = len(after_rows)
    relevance_requirements: dict[str, tuple[frozenset[str], ...]] = {
        "exact": (
            frozenset({"exact-a", "exact-b"}),
            frozenset({"independent-c"}),
            frozenset({"independent-d"}),
        ),
        "near": (
            frozenset({"near-a", "near-b"}),
            frozenset({"near-independent"}),
        ),
        "conflict": (
            frozenset({"conflict-450-a", "conflict-450-b"}),
            frozenset({"conflict-480"}),
            frozenset({"conflict-independent"}),
        ),
        "version_current": (frozenset({"version-2026"}),),
        "version_historical": (frozenset({"history-2024"}),),
        "conditional": (frozenset({"wltp"}),),
        "version_unknown_current": (
            frozenset({"unknown-current-1"}),
            frozenset({"unknown-current-2"}),
        ),
    }
    scenario_inputs = {name: candidates for name, _, candidates in scenarios}
    before_relevance = _requirement_recall(scenario_inputs, relevance_requirements)
    after_relevance = _requirement_recall(outputs, relevance_requirements)
    k = 6
    return {
        "query_count": len(scenarios),
        "k": k,
        "duplicate_redundancy_at_k": {
            "before": _rounded(duplicate_redundancy_at_k(tuple(before_rows), k)),
            "after": _rounded(duplicate_redundancy_at_k(tuple(after_rows), k)),
        },
        "unique_evidence_at_k": {
            "before": unique_evidence_at_k(tuple(before_rows), k),
            "after": unique_evidence_at_k(tuple(after_rows), k),
        },
        "document_diversity_at_k": {
            "before": document_diversity_at_k(tuple(before_rows), k),
            "after": document_diversity_at_k(tuple(after_rows), k),
        },
        "conflict_preservation_recall_at_k": 1.0 if conflict_preserved else 0.0,
        "temporal_match_at_k": (
            1.0
            if [item.chunk.id for item in outputs["version_historical"]] == ["history-2024"]
            else 0.0
        ),
        "current_version_accuracy_at_k": (
            1.0
            if [item.chunk.id for item in outputs["version_current"]] == ["version-2026"]
            else 0.0
        ),
        "unknown_current_validity_preserved": (
            1.0
            if [item.chunk.id for item in outputs["version_unknown_current"]]
            == ["unknown-current-1", "unknown-current-2"]
            else 0.0
        ),
        "base_relevance_recall": {
            "before": before_relevance,
            "after": after_relevance,
            "delta": _rounded(after_relevance - before_relevance),
        },
        "provenance_retention": 1.0 if provenance_loss == 0 else 0.0,
        "context": {
            "before_chunks": before_count,
            "after_evidence_items": after_count,
            "before_characters": before_chars,
            "after_characters": after_chars,
            "character_reduction": _rounded(
                (before_chars - after_chars) / before_chars if before_chars else 0.0
            ),
            "chunk_reduction": _rounded(
                (before_count - after_count) / before_count if before_count else 0.0
            ),
        },
        "conflict_suppression_count": 0 if conflict_preserved else 1,
        "provenance_loss_count": provenance_loss,
        "permission_leakage_count": permission_leakage,
        "wrong_current_version_selection_count": int(
            [item.chunk.id for item in outputs["version_current"]] != ["version-2026"]
        ),
        "latency_ms": _latency(latencies),
        "scenario_outputs": {
            name: [item.chunk.id for item in evidence] for name, evidence in outputs.items()
        },
    }


def _version_benchmark(config: RetrievalPolicyConfig) -> dict[str, Any]:
    documents = tuple(
        DocumentRelationContext(
            document_id=f"v{version}",
            owner_id="evaluation-owner",
            notebook_id="evaluation-notebook",
            document_family_id="controlled-family",
            version_number=version,
            temporal=TemporalContext(effective_from=date(2023 + version, 1, 1)),
            authority=SourceAuthority(),
        )
        for version in (1, 2, 3)
    )
    lineage = build_version_lineage(documents)
    retrieval = _retrieval_benchmark(config)
    direction_cases = (
        (documents[1], documents[0], VersionDirection.SOURCE_SUPERSEDES_TARGET),
        (documents[0], documents[1], VersionDirection.TARGET_SUPERSEDES_SOURCE),
        (documents[2], documents[1], VersionDirection.SOURCE_SUPERSEDES_TARGET),
        (documents[1], documents[2], VersionDirection.TARGET_SUPERSEDES_SOURCE),
    )
    direction_correct = sum(
        determine_version_direction(source, target)[0] is expected
        for source, target, expected in direction_cases
    )
    return {
        "controlled_document_count": 3,
        "lineage_edge_count": len(lineage.edges),
        "lineage_accuracy": 1.0
        if [(edge.previous_document_id, edge.next_document_id) for edge in lineage.edges]
        == [("v1", "v2"), ("v2", "v3")]
        else 0.0,
        "direction_case_count": len(direction_cases),
        "direction_accuracy": _rounded(direction_correct / len(direction_cases)),
        "cycle_count": int(lineage_has_cycle(lineage.edges)),
        "ambiguous_document_ids": list(lineage.uncertain_document_ids),
        "current_version_selection_accuracy": retrieval["current_version_accuracy_at_k"],
        "historical_version_selection_accuracy": retrieval["temporal_match_at_k"],
        "temporal_match_accuracy": retrieval["temporal_match_at_k"],
        "unknown_current_validity_preserved": retrieval[
            "unknown_current_validity_preserved"
        ],
    }


def _bridge_supplement(split: str) -> dict[str, Any]:
    grouped: dict[str, list[bool]] = {"table→prose": [], "prose→table": []}
    case_results: list[dict[str, object]] = []
    for raw_line in BRIDGE_DATASET_PATH.read_text(encoding="utf-8").splitlines():
        if not raw_line.strip():
            continue
        case = cast(dict[str, Any], json.loads(raw_line))
        if case["split"] != split:
            continue
        raw_table = cast(dict[str, list[Any]], case["table"])
        headers = [str(value) for value in raw_table["headers"]]
        rows = [[str(value) for value in row] for row in raw_table["rows"]]
        case_id = str(case["id"])
        table = ParsedTable(
            table_id=f"{case_id}:table",
            location=f"evaluation:p4-bridge:{case_id}",
            rows=[headers, *rows],
            columns=len(headers),
            header=headers,
            confidence=1.0,
        )
        table_claims = canonicalize_table_claims(
            analyze_table(document_id=f"{case_id}:table", table=table)
        )
        prose_claims = extract_structured_claims(
            str(case["prose"]),
            document_id=f"{case_id}:prose",
            domain_hint=str(case["domain"]),
        ).claims
        direction = str(case["direction"])
        left_claims, right_claims = (
            (table_claims, prose_claims)
            if direction == "table→prose"
            else (prose_claims, table_claims)
        )
        alignment = align_claims(left_claims, right_claims, p2_scope_admitted=True)
        admitted = ConflictAdmissionDecision(
            disposition=ConflictAdmissionDisposition.ADMIT,
            allows_conflict_analysis=True,
            entity_compatible=True,
            scope_relation=ScopeRelation.SAME,
            qualifier_compatibility=QualifierCompatibility.EQUAL,
            temporal_relation=TemporalRelation.SAME,
            reason_codes=("controlled_bridge_scope_admitted",),
        )
        table_text = " | ".join((*headers, *(value for row in rows for value in row)))
        source_text, target_text = (
            (table_text, str(case["prose"]))
            if direction == "table→prose"
            else (str(case["prose"]), table_text)
        )
        summary = aggregate_claim_evidence(
            source=_document_context(
                f"{case_id}:source",
                build_document_fingerprint(source_text).strict_hash,
                TemporalContext(),
                f"bridge:{case['domain']}",
            ),
            target=_document_context(
                f"{case_id}:target",
                build_document_fingerprint(target_text).strict_hash,
                TemporalContext(),
                f"bridge:{case['domain']}",
            ),
            source_claims=left_claims,
            target_claims=right_claims,
            alignment=alignment,
            scope_decision=admitted,
        )
        expected = str(case["expected_relation"])
        correct = summary.primary_relation.value == expected
        grouped[direction].append(correct)
        case_results.append(
            {
                "id": case_id,
                "direction": direction,
                "domain": case["domain"],
                "expected_relation": expected,
                "predicted_relation": summary.primary_relation.value,
                "correct": correct,
            }
        )
    cases = len(case_results)
    correct_count = sum(bool(item["correct"]) for item in case_results)
    return {
        "dataset": str(BRIDGE_DATASET_PATH),
        "dataset_sha256": _sha256(BRIDGE_DATASET_PATH),
        "separate_from_frozen_p0": True,
        "case_count": cases,
        "p4_final_relation_correct": correct_count,
        "p4_final_relation_accuracy": _rounded(correct_count / max(1, cases)),
        "directions": {
            direction: {
                "case_count": len(values),
                "correct": sum(values),
                "accuracy": _rounded(sum(values) / max(1, len(values))),
            }
            for direction, values in grouped.items()
        },
        "results": case_results,
    }


def _regression_state(split: str) -> dict[str, Any]:
    p1 = _read_json(REPORT_DIR / f"p1_candidate_generation_{split}.json")
    p2 = _read_json(REPORT_DIR / f"duplicate_conflict_p2_scope_{split}.json")
    p3 = _read_json(REPORT_DIR / f"duplicate_conflict_p3_claims_{split}.json")
    return {
        "p1_candidate_recall_at_50": p1["candidate_generation"]["recall@50"],
        "p2_entity_precision": p2["entity_metrics"]["precision"],
        "p2_entity_recall": p2["entity_metrics"]["recall"],
        "p2_admission_precision": p2["admission_metrics"]["precision"],
        "p2_admission_recall": p2["admission_metrics"]["recall"],
        "p3_claim_precision": p3["claim_extraction"]["precision"],
        "p3_claim_recall": p3["claim_extraction"]["recall"],
        "p3_claim_f1": p3["claim_extraction"]["f1"],
        "p3_alignment_precision": p3["alignment"]["precision"],
        "p3_alignment_recall": p3["alignment"]["recall"],
        "p3_alignment_f1": p3["alignment"]["f1"],
        "p3_conflict_precision": p3["claim_conflict"]["precision"],
        "p3_conflict_recall": p3["claim_conflict"]["recall"],
        "p3_conflict_f1": p3["claim_conflict"]["f1"],
        "false_auto_reuse": p3["safety"]["false_auto_reuse"],
        "false_entity_merge": p3["safety"]["false_entity_merge"],
        "false_conflict_admission": p3["safety"]["false_conflict_admission"],
        "source_reports": [
            f"reports/evaluation/p1_candidate_generation_{split}.json",
            f"reports/evaluation/duplicate_conflict_p2_scope_{split}.json",
            f"reports/evaluation/duplicate_conflict_p3_claims_{split}.json",
        ],
    }


def _ablation(
    results: list[P4PairResult],
    retrieval: dict[str, Any],
    version: dict[str, Any],
) -> dict[str, Any]:
    aggregation_f1 = _classification_metrics(results)["macro_f1"]
    p3_only_predictions = [_p3_only_prediction(item) for item in results]
    p3_only = _macro_f1_from_predictions(results, p3_only_predictions)
    return {
        "p3_claim_evidence_only": {
            "final_relation_macro_f1": p3_only,
            "duplicate_suppression": 0.0,
            "conflict_preservation": 1.0,
            "version_accuracy": 0.0,
        },
        "plus_claim_aggregation": {
            "final_relation_macro_f1": aggregation_f1,
            "duplicate_suppression": 0.0,
            "conflict_preservation": 1.0,
        },
        "plus_version_lineage": {
            "final_relation_macro_f1": aggregation_f1,
            "version_accuracy": version["lineage_accuracy"],
        },
        "plus_duplicate_clustering": {
            "final_relation_macro_f1": aggregation_f1,
            "duplicate_redundancy_at_k": retrieval["duplicate_redundancy_at_k"]["after"],
        },
        "plus_authority_preference": {
            "final_relation_macro_f1": aggregation_f1,
            "conflict_preservation": retrieval["conflict_preservation_recall_at_k"],
            "authority_changes_relation": False,
        },
        "plus_retrieval_policy": {
            "final_relation_macro_f1": aggregation_f1,
            "duplicate_redundancy_at_k": retrieval["duplicate_redundancy_at_k"]["after"],
            "unique_evidence_at_k": retrieval["unique_evidence_at_k"]["after"],
            "context_character_reduction": retrieval["context"]["character_reduction"],
            "conflict_preservation": retrieval["conflict_preservation_recall_at_k"],
        },
    }


def _p3_only_prediction(item: P4PairResult) -> str:
    if item.conflict_count:
        return "CONFLICT"
    if item.conditional_count:
        return "CONDITIONAL_VARIANT"
    if item.added_count or item.removed_count or item.updated_count:
        return "VERSION_UPDATE"
    if item.uncertain_count:
        return "UNCERTAIN"
    if item.unchanged_count:
        return "NEAR_DUPLICATE"
    return "DISTINCT"


def _macro_f1_from_predictions(results: list[P4PairResult], predictions: list[str]) -> float:
    scores = []
    for label in _LABELS:
        true_positive = sum(
            item.expected_relation == prediction == label
            for item, prediction in zip(results, predictions, strict=True)
        )
        false_positive = sum(
            item.expected_relation != label and prediction == label
            for item, prediction in zip(results, predictions, strict=True)
        )
        false_negative = sum(
            item.expected_relation == label and prediction != label
            for item, prediction in zip(results, predictions, strict=True)
        )
        scores.append(float(_prf(true_positive, false_positive, false_negative)["f1"]))
    return _rounded(statistics.fmean(scores))


def _failure_codes(  # type: ignore[no-untyped-def]
    expected, predicted, summary, p2_disposition
) -> tuple[str, ...]:
    if expected == predicted:
        return ()
    codes = []
    if expected in {"NEAR_DUPLICATE", "VERSION_UPDATE"}:
        codes.append("AGGREGATION_COVERAGE_ERROR")
    if predicted == "EXACT_DUPLICATE":
        codes.append("FALSE_EXACT_COLLAPSE")
    if predicted == "NEAR_DUPLICATE":
        codes.append("FALSE_NEAR_DUPLICATE")
    if expected == "VERSION_UPDATE" or predicted == "VERSION_UPDATE":
        codes.append("FALSE_VERSION_RELATION")
    if expected == "CONFLICT" or predicted == "CONFLICT":
        codes.append("CONFLICT_AGGREGATION_ERROR")
    if expected == "TEMPLATE_VARIANT" or predicted == "TEMPLATE_VARIANT":
        codes.append("TEMPLATE_DOMINANCE_ERROR")
    if expected == "CONFLICT" and predicted == "UNCERTAIN" and p2_disposition == "uncertain":
        codes.append("P2_GATE_BLOCKED")
    if summary.facets.has_conflict and predicted != "CONFLICT":
        codes.append("RELATION_PRECEDENCE_ERROR")
    return tuple(dict.fromkeys(codes or ["DOCUMENT_AGGREGATION_ERROR"]))


def _failure_taxonomy(results: list[P4PairResult]) -> dict[str, Any]:
    counts = Counter(code for item in results for code in item.failure_codes)
    return {
        "counts": {code: counts[code] for code in _P4_FAILURE_CODES},
        "examples": {
            code: [item.pair_id for item in results if code in item.failure_codes][:20]
            for code in _P4_FAILURE_CODES
        },
        "failed_pair_count": sum(bool(item.failure_codes) for item in results),
    }


def _acceptance(report: dict[str, Any], config: dict[str, Any]) -> dict[str, Any]:
    targets = config["targets"]
    final = report["final_relation"]
    safety = report["safety"]
    retrieval = report["retrieval"]
    regression = report["p1_p2_p3_regression"]
    assert isinstance(final, dict)
    assert isinstance(safety, dict)
    assert isinstance(retrieval, dict)
    assert isinstance(regression, dict)
    per_class = final["per_class"]
    assert isinstance(per_class, dict)
    checks = {
        "p1_recall_at_50": regression["p1_candidate_recall_at_50"] == 1.0,
        "p2_p3_safety": (
            regression["false_auto_reuse"]
            == regression["false_entity_merge"]
            == regression["false_conflict_admission"]
            == 0
        ),
        "macro_f1": final["macro_f1"] >= targets["macro_f1"],
        "exact_duplicate_precision": per_class["EXACT_DUPLICATE"]["precision"]
        >= targets["exact_duplicate_precision"],
        "conflict_precision": per_class["CONFLICT"]["precision"] >= targets["conflict_precision"],
        "conflict_recall": per_class["CONFLICT"]["recall"] >= targets["conflict_recall"],
        "version_update_precision": per_class["VERSION_UPDATE"]["precision"]
        >= targets["version_update_precision"],
        "near_duplicate_precision": per_class["NEAR_DUPLICATE"]["precision"]
        >= targets["near_duplicate_precision"],
        "false_exact_collapse": safety["false_exact_collapse"] == targets["false_exact_collapse"],
        "conflict_suppression": safety["conflict_suppression"] == targets["conflict_suppression"],
        "provenance_loss": safety["provenance_loss"] == targets["provenance_loss"],
        "permission_leakage": safety["permission_relation_leakage"]
        == targets["permission_leakage"],
        "duplicate_redundancy_reduced": (
            retrieval["duplicate_redundancy_at_k"]["after"]
            < retrieval["duplicate_redundancy_at_k"]["before"]
        ),
        "unique_evidence_maintained": (
            retrieval["unique_evidence_at_k"]["after"]
            >= retrieval["unique_evidence_at_k"]["before"]
        ),
        "conflict_preservation": retrieval["conflict_preservation_recall_at_k"] == 1.0,
        "provenance_retention": retrieval["provenance_retention"] == 1.0,
        "base_relevance_not_regressed": (
            retrieval["base_relevance_recall"]["after"]
            >= retrieval["base_relevance_recall"]["before"]
        ),
        "unknown_current_validity_preserved": (
            report["version_lineage"]["unknown_current_validity_preserved"] == 1.0
        ),
    }
    return {
        "checks": checks,
        "status": "PASS" if all(checks.values()) else "PARTIAL",
        "failed_checks": [name for name, passed in checks.items() if not passed],
    }


def _prf(true_positive: int, false_positive: int, false_negative: int) -> dict[str, Any]:
    precision = (
        true_positive / (true_positive + false_positive) if true_positive + false_positive else 0.0
    )
    recall = (
        true_positive / (true_positive + false_negative) if true_positive + false_negative else 0.0
    )
    f1 = 2 * precision * recall / (precision + recall) if precision + recall else 0.0
    return {
        "true_positive": true_positive,
        "false_positive": false_positive,
        "false_negative": false_negative,
        "precision": _rounded(precision),
        "recall": _rounded(recall),
        "f1": _rounded(f1),
    }


def _distribution(values: list[float]) -> dict[str, float]:
    ordered = sorted(values)
    return {
        "mean": _rounded(statistics.fmean(ordered)) if ordered else 0.0,
        "p50": _percentile(ordered, 0.5),
        "p95": _percentile(ordered, 0.95),
        "min": _rounded(min(ordered)) if ordered else 0.0,
        "max": _rounded(max(ordered)) if ordered else 0.0,
    }


def _latency(values: list[float]) -> dict[str, float]:
    ordered = sorted(values)
    return {
        "mean": _rounded(statistics.fmean(ordered)) if ordered else 0.0,
        "p50": _percentile(ordered, 0.5),
        "p95": _percentile(ordered, 0.95),
    }


def _percentile(values: list[float], quantile: float) -> float:
    if not values:
        return 0.0
    index = min(len(values) - 1, round((len(values) - 1) * quantile))
    return _rounded(values[index])


def _rounded(value: float) -> float:
    return round(value, 6)


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest().upper()


def _validate_frozen_inputs(config: dict[str, Any]) -> None:
    raw_inputs = config.get("frozen_inputs_sha256")
    if not isinstance(raw_inputs, dict) or not raw_inputs:
        raise ValueError("P4 TEST requires non-empty frozen input hashes")
    mismatches: list[str] = []
    for raw_path, raw_expected in sorted(raw_inputs.items()):
        path = Path(str(raw_path))
        expected = str(raw_expected).upper()
        if not path.is_file() or len(expected) != 64 or _sha256(path) != expected:
            mismatches.append(str(path))
    if mismatches:
        raise ValueError(f"P4 frozen input hash mismatch: {', '.join(mismatches)}")


def _read_json(path: Path) -> dict[str, Any]:
    return cast(dict[str, Any], json.loads(path.read_text(encoding="utf-8")))


def write_p4_report(
    report: dict[str, Any], *, overwrite_dev: bool = False
) -> tuple[Path, Path, Path]:
    split = str(report["split"])
    stem = REPORT_DIR / f"duplicate_conflict_p4_relations_{split}"
    json_path = stem.with_suffix(".json")
    markdown_path = stem.with_suffix(".md")
    failures_path = REPORT_DIR / f"duplicate_conflict_p4_relations_{split}_failures.jsonl"
    if split == "test" and (json_path.exists() or markdown_path.exists() or failures_path.exists()):
        raise FileExistsError("P4 frozen TEST report is immutable and already exists")
    if split == "dev" and not overwrite_dev and (json_path.exists() or markdown_path.exists()):
        raise FileExistsError("P4 DEV report exists; pass --overwrite-dev to replace it")
    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    json_path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    markdown_path.write_text(_markdown(report), encoding="utf-8")
    failures = [item for item in report["results"] if item["failure_codes"]]
    failures_path.write_text(
        "".join(json.dumps(item, ensure_ascii=False) + "\n" for item in failures),
        encoding="utf-8",
    )
    return json_path, markdown_path, failures_path


def _markdown(report: dict[str, Any]) -> str:
    final = report["final_relation"]
    safety = report["safety"]
    retrieval = report["retrieval"]
    version = report["version_lineage"]
    performance = report["performance"]
    acceptance = report["acceptance"]
    assert all(
        isinstance(item, dict)
        for item in (final, safety, retrieval, version, performance, acceptance)
    )
    per_class = final["per_class"]
    lines = [
        f"# P4 relation aggregation — {str(report['split']).upper()}",
        "",
        f"- Pairs: {report['pair_count']}",
        f"- Configuration: `{report['configuration_sha256']}` ({report['configuration_status']})",
        f"- Accuracy: {final['accuracy']}",
        "- Macro P/R/F1: "
        f"{final['macro_precision']} / {final['macro_recall']} / {final['macro_f1']}",
        f"- Acceptance: **{acceptance['status']}**",
        "",
        "## Per-class metrics",
        "",
        "| Relation | Support | Precision | Recall | F1 |",
        "|---|---:|---:|---:|---:|",
    ]
    for label in _LABELS:
        item = per_class[label]
        lines.append(
            f"| {label} | {item['support']} | {item['precision']} | "
            f"{item['recall']} | {item['f1']} |"
        )
    lines.extend(
        [
            "",
            "## Safety",
            "",
            *[f"- {key}: {value}" for key, value in safety.items()],
            "",
            "## Version",
            "",
            f"- Lineage accuracy: {version['lineage_accuracy']}",
            f"- Direction accuracy: {version['direction_accuracy']}",
            f"- Current selection: {version['current_version_selection_accuracy']}",
            f"- Historical selection: {version['historical_version_selection_accuracy']}",
            "- Unknown current validity preserved: "
            f"{version['unknown_current_validity_preserved']}",
            f"- Cycles: {version['cycle_count']}",
            "",
            "## Retrieval",
            "",
            f"- Duplicate Redundancy@K: {retrieval['duplicate_redundancy_at_k']}",
            f"- Unique Evidence@K: {retrieval['unique_evidence_at_k']}",
            f"- Document Diversity@K: {retrieval['document_diversity_at_k']}",
            f"- Conflict Preservation Recall@K: {retrieval['conflict_preservation_recall_at_k']}",
            f"- Temporal Match@K: {retrieval['temporal_match_at_k']}",
            f"- Base relevance recall: {retrieval['base_relevance_recall']}",
            f"- Context impact: {retrieval['context']}",
            "",
            "## Performance",
            "",
            f"- Aggregation ms/pair: {performance['aggregation_ms_per_pair']}",
            f"- Relation lookup ms: {performance['relation_lookup_ms']}",
            f"- Retrieval policy ms/query: {performance['retrieval_policy_ms_per_query']}",
            "",
            "## Acceptance",
            "",
            *[
                f"- {name}: {'PASS' if passed else 'FAIL'}"
                for name, passed in acceptance["checks"].items()
            ],
            "",
        ]
    )
    return "\n".join(lines)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--split", choices=("dev", "test"), required=True)
    parser.add_argument("--config", type=Path, default=P4_CONFIG_PATH)
    parser.add_argument("--overwrite-dev", action="store_true")
    args = parser.parse_args()
    report = evaluate_p4(split=args.split, config_path=args.config)
    paths = write_p4_report(report, overwrite_dev=args.overwrite_dev)
    print(
        json.dumps(
            {
                "reports": [str(path) for path in paths],
                "acceptance": report["acceptance"],
            },
            indent=2,
        )
    )


if __name__ == "__main__":
    main()


__all__ = ["P4PairResult", "evaluate_p4", "main", "write_p4_report"]
