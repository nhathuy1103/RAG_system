"""Compare retrieval experiment modes such as A/B/C/D.

This script consumes the same JSONL result file as score_retrieval_results.py,
then writes:

- retrieval_metric_summary.csv
- retrieval_metric_by_query_type.csv
- retrieval_metric_comparison.csv
- retrieval_metric_details.csv
- retrieval_metric_by_scenario.csv
- retrieval_metric_by_evidence_fact.csv
- retrieval_metric_macro_summary.csv

Example:

    python evaluation/retrieval_metadata_testset/score_experiment_comparison.py \
      --results evaluation/retrieval_metadata_testset/retrieval_results.jsonl \
      --output-dir evaluation/retrieval_metadata_testset/results/abcd
"""

from __future__ import annotations

import argparse
import csv
import json
import math
import random
import statistics
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

from score_retrieval_results import load_jsonl, score

DEFAULT_TESTSET = Path(__file__).resolve().parent / "testset.jsonl"
DEFAULT_COMPARISONS = (
    ("no_metadata", "current_metadata", "B_minus_A"),
    ("current_metadata", "gold_metadata", "D_minus_B"),
    ("shuffled_metadata", "current_metadata", "B_minus_C"),
)


def _float(value: object, default: float = 0.0) -> float:
    if value in ("", None):
        return default
    return float(value)


def _int(value: object, default: int = 0) -> int:
    if value in ("", None):
        return default
    return int(value)


def _metric_value(row: dict[str, Any], metric: str, primary_k: int, max_k: int) -> float:
    if metric == f"recall_at_{primary_k}":
        return float(_int(row.get(f"hit_at_{primary_k}")))
    if metric.startswith("recall_at_"):
        k = int(metric.rsplit("_", 1)[1])
        return float(_int(row.get(f"hit_at_{k}")))
    if metric == f"mrr_at_{max_k}" or metric == "mrr_at_max_k":
        return _float(row.get("mrr_at_max_k"))
    if metric == f"term_hit_rate_at_{primary_k}":
        return _float(row.get(f"term_hit_rate_at_{primary_k}"))
    if metric.startswith("term_hit_rate_at_"):
        k = int(metric.rsplit("_", 1)[1])
        return _float(row.get(f"term_hit_rate_at_{k}"))
    if metric.startswith("ndcg_at_"):
        k = int(metric.rsplit("_", 1)[1])
        rank = row.get("first_hit_rank")
        if rank in ("", None):
            return 0.0
        rank_int = int(rank)
        if rank_int > k:
            return 0.0
        return 1.0 / math.log2(rank_int + 1)
    if metric.startswith("success_at_"):
        k = int(metric.rsplit("_", 1)[1])
        return float(_int(row.get(f"success_at_{k}")))
    if metric.startswith("multi_hop_group_coverage_at_"):
        k = int(metric.rsplit("_", 1)[1])
        return _float(row.get(f"evidence_group_coverage_at_{k}"))
    if metric.startswith("multi_hop_all_groups_at_"):
        k = int(metric.rsplit("_", 1)[1])
        return float(_int(row.get(f"all_evidence_groups_at_{k}")))
    if metric.startswith("null_rejection_at_"):
        k = int(metric.rsplit("_", 1)[1])
        return float(_int(row.get(f"null_rejection_at_{k}")))
    if metric.startswith("permission_safe_at_"):
        k = int(metric.rsplit("_", 1)[1])
        return float(_int(row.get(f"permission_safe_at_{k}")))
    if metric.startswith("permission_leak_at_"):
        k = int(metric.rsplit("_", 1)[1])
        return float(_int(row.get(f"permission_leak_at_{k}")))
    if metric.startswith("permission_allowed_recall_at_"):
        k = int(metric.rsplit("_", 1)[1])
        return float(_int(row.get(f"permission_allowed_hit_at_{k}")))
    if metric.startswith("protected_hit_count_at_"):
        k = int(metric.rsplit("_", 1)[1])
        return float(_int(row.get(f"protected_hit_count_at_{k}")))
    if metric.startswith("sensitive_term_leak_at_"):
        k = int(metric.rsplit("_", 1)[1])
        return float(_int(row.get(f"sensitive_term_leak_at_{k}")))
    if metric.startswith("all_required_documents_at_"):
        k = int(metric.rsplit("_", 1)[1])
        return float(_int(row.get(f"all_required_documents_at_{k}")))
    if metric.startswith("table_structured_success_at_"):
        k = int(metric.rsplit("_", 1)[1])
        return float(_int(row.get(f"table_structured_hit_at_{k}")))
    if metric == "filter_preflight_pass_rate":
        return float(_int(row.get("filter_preflight_pass"), 1))
    if metric == "empty_result_rate":
        return float(_int(row.get("empty_result")))
    if metric == "forbidden_top1_rate":
        return float(_int(row.get("top1_forbidden")))
    if metric == "top1_mojibake_rate":
        return float(_int(row.get("top1_mojibake")))
    raise ValueError(f"unsupported metric: {metric}")


def _metric_applicable(row: dict[str, Any], metric: str) -> bool:
    target_type = str(row.get("target_type") or "single")
    answerable = _int(row.get("answerable"), 1) == 1
    if metric.startswith(("recall_at_", "mrr_at_", "ndcg_at_", "term_hit_rate_at_")):
        return answerable
    if metric in {"empty_result_rate", "forbidden_top1_rate"}:
        return answerable
    if metric.startswith("multi_hop_"):
        return target_type == "multi_hop"
    if metric.startswith("null_rejection_at_"):
        return target_type == "null"
    if metric.startswith(
        (
            "permission_safe_at_",
            "permission_leak_at_",
            "protected_hit_count_at_",
            "sensitive_term_leak_at_",
        )
    ):
        return target_type in {"permission", "permission_denied"}
    if metric.startswith("permission_allowed_recall_at_"):
        return target_type == "permission_allowed"
    if metric.startswith("table_structured_success_at_"):
        return _int(row.get("is_table_structured")) == 1
    return True


def _mean(values: list[float]) -> float:
    return statistics.mean(values) if values else 0.0


def _percentile(values: list[float], pct: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    index = min(len(ordered) - 1, max(0, round((len(ordered) - 1) * pct)))
    return ordered[index]


def bootstrap_ci(values: list[float], *, seed: int, samples: int = 5000) -> tuple[float, float]:
    if not values:
        return 0.0, 0.0
    if len(values) == 1:
        return values[0], values[0]
    rng = random.Random(seed)
    means = []
    n = len(values)
    for _ in range(samples):
        sample = [values[rng.randrange(n)] for _ in range(n)]
        means.append(_mean(sample))
    return _percentile(means, 0.025), _percentile(means, 0.975)


def permutation_p_value(values: list[float], *, seed: int, samples: int = 5000) -> float:
    if not values:
        return 1.0
    observed = abs(_mean(values))
    if observed == 0:
        return 1.0
    rng = random.Random(seed)
    extreme = 0
    for _ in range(samples):
        flipped = [value if rng.random() < 0.5 else -value for value in values]
        if abs(_mean(flipped)) >= observed:
            extreme += 1
    return (extreme + 1) / (samples + 1)


def clustered_bootstrap_ci(
    values: list[float],
    clusters: list[str],
    *,
    seed: int,
    samples: int = 5000,
) -> tuple[float, float]:
    if not values or len(values) != len(clusters):
        return 0.0, 0.0
    grouped: dict[str, list[float]] = defaultdict(list)
    for cluster, value in zip(clusters, values, strict=True):
        grouped[cluster].append(value)
    cluster_ids = sorted(grouped)
    if len(cluster_ids) == 1:
        mean = _mean(values)
        return mean, mean
    rng = random.Random(seed)
    means: list[float] = []
    for _ in range(samples):
        sample: list[float] = []
        for _ in cluster_ids:
            sample.extend(grouped[cluster_ids[rng.randrange(len(cluster_ids))]])
        means.append(_mean(sample))
    return _percentile(means, 0.025), _percentile(means, 0.975)


def clustered_permutation_p_value(
    values: list[float],
    clusters: list[str],
    *,
    seed: int,
    samples: int = 5000,
) -> float:
    if not values or len(values) != len(clusters):
        return 1.0
    observed = abs(_mean(values))
    if observed == 0:
        return 1.0
    grouped: dict[str, list[float]] = defaultdict(list)
    for cluster, value in zip(clusters, values, strict=True):
        grouped[cluster].append(value)
    rng = random.Random(seed)
    extreme = 0
    for _ in range(samples):
        flipped: list[float] = []
        for cluster in sorted(grouped):
            sign = 1 if rng.random() < 0.5 else -1
            flipped.extend(sign * value for value in grouped[cluster])
        if abs(_mean(flipped)) >= observed:
            extreme += 1
    return (extreme + 1) / (samples + 1)


def summarize_rows(
    rows: list[dict[str, Any]], k_values: list[int], primary_k: int
) -> dict[str, Any]:
    max_k = max(k_values)
    answerable_rows = [row for row in rows if _metric_applicable(row, "recall_at_1")]
    multi_hop_rows = [row for row in rows if row.get("target_type") == "multi_hop"]
    null_rows = [row for row in rows if row.get("target_type") == "null"]
    permission_denied_rows = [
        row
        for row in rows
        if row.get("target_type") in {"permission", "permission_denied"}
    ]
    permission_allowed_rows = [
        row for row in rows if row.get("target_type") == "permission_allowed"
    ]
    permission_rows = [*permission_allowed_rows, *permission_denied_rows]
    table_rows = [row for row in rows if _int(row.get("is_table_structured")) == 1]
    latencies = [
        _float(row["latency_ms"]) for row in rows if row.get("latency_ms") not in ("", None)
    ]
    summary: dict[str, Any] = {
        "count": len(rows),
        "answerable_count": len(answerable_rows),
        "multi_hop_count": len(multi_hop_rows),
        "null_count": len(null_rows),
        "permission_count": len(permission_rows),
        "permission_allowed_count": len(permission_allowed_rows),
        "permission_denied_count": len(permission_denied_rows),
        "table_structured_count": len(table_rows),
        "filter_preflight_pass_rate": _mean(
            [_float(row.get("filter_preflight_pass"), 1.0) for row in rows]
        ),
        "mrr_at_10": _mean(
            [_metric_value(row, f"mrr_at_{max_k}", primary_k, max_k) for row in answerable_rows]
        ),
        "ndcg_at_10": _mean(
            [_metric_value(row, "ndcg_at_10", primary_k, max_k) for row in answerable_rows]
        ),
        "forbidden_top1_rate": _mean(
            [_metric_value(row, "forbidden_top1_rate", primary_k, max_k) for row in answerable_rows]
        ),
        "empty_result_rate": _mean(
            [_metric_value(row, "empty_result_rate", primary_k, max_k) for row in answerable_rows]
        ),
        "top1_mojibake_rate": _mean(
            [_metric_value(row, "top1_mojibake_rate", primary_k, max_k) for row in rows]
        ),
        "latency_p50_ms": _percentile(latencies, 0.50) if latencies else "",
        "latency_p95_ms": _percentile(latencies, 0.95) if latencies else "",
    }
    for k in k_values:
        summary[f"recall_at_{k}"] = _mean(
            [_metric_value(row, f"recall_at_{k}", primary_k, max_k) for row in answerable_rows]
        )
        summary[f"term_hit_rate_at_{k}"] = _mean(
            [
                _metric_value(row, f"term_hit_rate_at_{k}", primary_k, max_k)
                for row in answerable_rows
            ]
        )
        summary[f"success_at_{k}"] = _mean(
            [_metric_value(row, f"success_at_{k}", primary_k, max_k) for row in rows]
        )
        summary[f"multi_hop_group_coverage_at_{k}"] = _mean(
            [
                _metric_value(row, f"multi_hop_group_coverage_at_{k}", primary_k, max_k)
                for row in multi_hop_rows
            ]
        )
        summary[f"multi_hop_all_groups_at_{k}"] = _mean(
            [
                _metric_value(row, f"multi_hop_all_groups_at_{k}", primary_k, max_k)
                for row in multi_hop_rows
            ]
        )
        summary[f"null_rejection_at_{k}"] = _mean(
            [_metric_value(row, f"null_rejection_at_{k}", primary_k, max_k) for row in null_rows]
        )
        summary[f"permission_safe_at_{k}"] = _mean(
            [
                _metric_value(row, f"permission_safe_at_{k}", primary_k, max_k)
                for row in permission_denied_rows
            ]
        )
        summary[f"permission_leak_at_{k}"] = _mean(
            [
                _metric_value(row, f"permission_leak_at_{k}", primary_k, max_k)
                for row in permission_denied_rows
            ]
        )
        summary[f"permission_allowed_recall_at_{k}"] = _mean(
            [
                _metric_value(row, f"permission_allowed_recall_at_{k}", primary_k, max_k)
                for row in permission_allowed_rows
            ]
        )
        summary[f"protected_hit_count_at_{k}"] = sum(
            _metric_value(row, f"protected_hit_count_at_{k}", primary_k, max_k)
            for row in permission_denied_rows
        )
        summary[f"sensitive_term_leak_at_{k}"] = _mean(
            [
                _metric_value(row, f"sensitive_term_leak_at_{k}", primary_k, max_k)
                for row in permission_denied_rows
            ]
        )
        summary[f"all_required_documents_at_{k}"] = _mean(
            [
                _metric_value(row, f"all_required_documents_at_{k}", primary_k, max_k)
                for row in rows
            ]
        )
        summary[f"table_structured_success_at_{k}"] = _mean(
            [
                _metric_value(row, f"table_structured_success_at_{k}", primary_k, max_k)
                for row in table_rows
            ]
        )
    return summary


def write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    if not rows:
        path.write_text("", encoding="utf-8")
        return
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0].keys()))
        writer.writeheader()
        writer.writerows(rows)


def grouped_summary_rows(
    details: list[dict[str, Any]],
    *,
    source_field: str,
    output_field: str,
    k_values: list[int],
    primary_k: int,
    fallback_field: str | None = None,
) -> list[dict[str, Any]]:
    grouped: dict[tuple[str, str], list[dict[str, Any]]] = defaultdict(list)
    for row in details:
        raw = str(row.get(source_field) or "")
        if not raw and fallback_field:
            raw = str(row.get(fallback_field) or "")
        values = [value.strip() for value in raw.split("|") if value.strip()]
        for value in dict.fromkeys(values):
            grouped[(str(row["mode"]), value)].append(row)
    return [
        {
            "mode": mode,
            output_field: value,
            **summarize_rows(rows, k_values, primary_k),
        }
        for (mode, value), rows in sorted(grouped.items())
    ]


def macro_summary_rows(
    grouped_rows: list[dict[str, Any]], *, grouping_unit: str, k_values: list[int]
) -> list[dict[str, Any]]:
    """Average group-level scores so repeated templates cannot dominate the result."""
    by_mode: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in grouped_rows:
        by_mode[str(row["mode"])].append(row)

    metric_denominators = {
        "mrr_at_10": "answerable_count",
        "ndcg_at_10": "answerable_count",
        "forbidden_top1_rate": "answerable_count",
        "empty_result_rate": "answerable_count",
        "filter_preflight_pass_rate": "count",
    }
    for k in k_values:
        metric_denominators.update(
            {
                f"recall_at_{k}": "answerable_count",
                f"term_hit_rate_at_{k}": "answerable_count",
                f"success_at_{k}": "count",
                f"multi_hop_group_coverage_at_{k}": "multi_hop_count",
                f"multi_hop_all_groups_at_{k}": "multi_hop_count",
                f"null_rejection_at_{k}": "null_count",
                f"permission_safe_at_{k}": "permission_denied_count",
                f"permission_leak_at_{k}": "permission_denied_count",
                f"permission_allowed_recall_at_{k}": "permission_allowed_count",
                f"sensitive_term_leak_at_{k}": "permission_denied_count",
                f"all_required_documents_at_{k}": "count",
                f"table_structured_success_at_{k}": "table_structured_count",
            }
        )

    output = []
    for mode, rows in sorted(by_mode.items()):
        result: dict[str, Any] = {
            "mode": mode,
            "grouping_unit": grouping_unit,
            "group_count": len(rows),
        }
        for metric, denominator in metric_denominators.items():
            applicable = [row for row in rows if _int(row.get(denominator)) > 0]
            result[metric] = _mean([_float(row.get(metric)) for row in applicable])
        output.append(result)
    return output


def parse_comparisons(raw: str | None) -> list[tuple[str, str, str]]:
    if not raw:
        return list(DEFAULT_COMPARISONS)
    comparisons = []
    for item in raw.split(","):
        parts = [part.strip() for part in item.split(":")]
        if len(parts) == 2:
            left, right = parts
            name = f"{right}_minus_{left}"
        elif len(parts) == 3:
            left, right, name = parts
        else:
            raise SystemExit("--comparisons format: left:right[:name],left:right[:name]")
        comparisons.append((left, right, name))
    return comparisons


def _metadata_conditions(test: dict[str, Any]) -> list[dict[str, Any]]:
    retrieval_filters = test.get("retrieval_filters")
    if not isinstance(retrieval_filters, dict):
        return []
    conditions = retrieval_filters.get("metadata_conditions")
    if not isinstance(conditions, list):
        return []
    return [condition for condition in conditions if isinstance(condition, dict)]


def select_query_subset(
    testset: list[dict[str, Any]],
    subset: str,
) -> list[dict[str, Any]]:
    if subset == "all":
        return list(testset)
    if subset == "filter_capable":
        return [test for test in testset if _metadata_conditions(test)]
    raise ValueError(f"Unsupported query subset: {subset}")


def select_metadata_field_subset(
    testset: list[dict[str, Any]],
    field: str | None,
) -> list[dict[str, Any]]:
    selected_field = str(field or "").strip()
    if not selected_field:
        return list(testset)
    return [
        test
        for test in testset
        if any(
            str(condition.get("field") or "") == selected_field
            for condition in _metadata_conditions(test)
        )
    ]


def evaluation_scope(
    source_testset: list[dict[str, Any]],
    selected_testset: list[dict[str, Any]],
    subset: str,
    metadata_field: str | None = None,
) -> dict[str, Any]:
    fields = Counter(
        str(condition.get("field") or "")
        for test in selected_testset
        for condition in _metadata_conditions(test)
        if str(condition.get("field") or "").strip()
    )
    slices = Counter(
        str(test.get("primary_slice") or test.get("category") or "unknown")
        for test in selected_testset
    )
    return {
        "schema_version": "1.0",
        "query_subset": subset,
        "metadata_field": metadata_field,
        "selection_rule": (
            f"metadata_conditions contains field={metadata_field}"
            if metadata_field
            else (
                "retrieval_filters.metadata_conditions contains at least one condition"
                if subset == "filter_capable"
                else "all queries"
            )
        ),
        "source_query_count": len(source_testset),
        "selected_query_count": len(selected_testset),
        "selected_answerable_count": sum(
            bool(test.get("answerable", True)) for test in selected_testset
        ),
        "primary_slice_counts": dict(sorted(slices.items())),
        "metadata_filter_field_counts": dict(sorted(fields.items())),
        "selected_query_ids": [str(test["id"]) for test in selected_testset],
    }


def build_outputs(
    *,
    details: list[dict[str, Any]],
    k_values: list[int],
    primary_k: int,
    comparisons: list[tuple[str, str, str]],
    seed: int,
    bootstrap_samples: int,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]]]:
    max_k = max(k_values)
    by_mode: dict[str, list[dict[str, Any]]] = defaultdict(list)
    by_mode_type: dict[tuple[str, str], list[dict[str, Any]]] = defaultdict(list)
    by_mode_test: dict[tuple[str, str], dict[str, Any]] = {}

    for row in details:
        mode = row["mode"]
        query_type = row.get("query_type") or row.get("category")
        by_mode[mode].append(row)
        by_mode_type[(mode, query_type)].append(row)
        by_mode_test[(mode, row["test_id"])] = row

    summary_rows = []
    for mode, rows in sorted(by_mode.items()):
        summary = summarize_rows(rows, k_values, primary_k)
        summary_rows.append({"mode": mode, **summary})

    by_type_rows = []
    for (mode, query_type), rows in sorted(by_mode_type.items()):
        summary = summarize_rows(rows, k_values, primary_k)
        by_type_rows.append({"mode": mode, "query_type": query_type, **summary})

    metrics = [
        f"recall_at_{primary_k}",
        f"success_at_{primary_k}",
        f"mrr_at_{max_k}",
        f"ndcg_at_{max_k}",
        f"term_hit_rate_at_{primary_k}",
        f"multi_hop_group_coverage_at_{max_k}",
        f"multi_hop_all_groups_at_{max_k}",
        f"null_rejection_at_{max_k}",
        f"permission_safe_at_{max_k}",
        f"permission_leak_at_{max_k}",
        f"permission_allowed_recall_at_{max_k}",
        f"protected_hit_count_at_{max_k}",
        f"sensitive_term_leak_at_{max_k}",
        f"all_required_documents_at_{max_k}",
        f"table_structured_success_at_{max_k}",
        "filter_preflight_pass_rate",
        "empty_result_rate",
        "forbidden_top1_rate",
        "top1_mojibake_rate",
    ]
    comparison_rows = []
    for left_mode, right_mode, comparison_name in comparisons:
        paired_ids = sorted(
            test_id
            for mode, test_id in by_mode_test
            if mode == left_mode and (right_mode, test_id) in by_mode_test
        )
        if not paired_ids:
            comparison_rows.append(
                {
                    "comparison": comparison_name,
                    "left_mode": left_mode,
                    "right_mode": right_mode,
                    "metric": "unavailable",
                    "n_pairs": 0,
                    "note": "No paired rows found for these mode names.",
                }
            )
            continue
        for metric in metrics:
            common_ids = [
                test_id
                for test_id in paired_ids
                if _metric_applicable(by_mode_test[(left_mode, test_id)], metric)
                and _metric_applicable(by_mode_test[(right_mode, test_id)], metric)
            ]
            if not common_ids:
                continue
            left_values = [
                _metric_value(by_mode_test[(left_mode, test_id)], metric, primary_k, max_k)
                for test_id in common_ids
            ]
            right_values = [
                _metric_value(by_mode_test[(right_mode, test_id)], metric, primary_k, max_k)
                for test_id in common_ids
            ]
            deltas = [right - left for left, right in zip(left_values, right_values, strict=True)]
            left_mean = _mean(left_values)
            right_mean = _mean(right_values)
            delta = _mean(deltas)
            ci_low, ci_high = bootstrap_ci(deltas, seed=seed, samples=bootstrap_samples)
            p_value = permutation_p_value(deltas, seed=seed + 17, samples=bootstrap_samples)
            clusters = [
                str(by_mode_test[(right_mode, test_id)].get("scenario_id") or test_id)
                for test_id in common_ids
            ]
            cluster_ci_low, cluster_ci_high = clustered_bootstrap_ci(
                deltas,
                clusters,
                seed=seed + 31,
                samples=bootstrap_samples,
            )
            cluster_p_value = clustered_permutation_p_value(
                deltas,
                clusters,
                seed=seed + 47,
                samples=bootstrap_samples,
            )
            wins = sum(value > 0 for value in deltas)
            ties = sum(value == 0 for value in deltas)
            losses = sum(value < 0 for value in deltas)
            comparison_rows.append(
                {
                    "comparison": comparison_name,
                    "left_mode": left_mode,
                    "right_mode": right_mode,
                    "metric": metric,
                    "left_mean": round(left_mean, 6),
                    "right_mean": round(right_mean, 6),
                    "absolute_delta": round(delta, 6),
                    "relative_delta": "" if left_mean == 0 else round(delta / left_mean, 6),
                    "ci95_low": round(ci_low, 6),
                    "ci95_high": round(ci_high, 6),
                    "win": wins,
                    "tie": ties,
                    "loss": losses,
                    "n_pairs": len(common_ids),
                    "p_value_permutation": round(p_value, 6),
                    "cluster_field": "scenario_id",
                    "cluster_count": len(set(clusters)),
                    "cluster_ci95_low": round(cluster_ci_low, 6),
                    "cluster_ci95_high": round(cluster_ci_high, 6),
                    "cluster_p_value_permutation": round(cluster_p_value, 6),
                    "note": "",
                }
            )
    return summary_rows, by_type_rows, comparison_rows


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--testset", type=Path, default=DEFAULT_TESTSET)
    parser.add_argument("--results", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--k", default="1,3,5,10")
    parser.add_argument("--primary-k", type=int, default=5)
    parser.add_argument("--comparisons", default=None)
    parser.add_argument(
        "--query-subset",
        choices=("all", "filter_capable"),
        default="all",
        help=(
            "Use all queries or only queries with at least one structured "
            "metadata condition."
        ),
    )
    parser.add_argument("--bootstrap-samples", type=int, default=5000)
    parser.add_argument(
        "--metadata-field",
        default=None,
        help="Optionally score only queries whose structured conditions use this field.",
    )
    parser.add_argument("--seed", type=int, default=20260803)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    k_values = sorted({int(value.strip()) for value in args.k.split(",") if value.strip()})
    if args.primary_k not in k_values:
        k_values.append(args.primary_k)
        k_values.sort()
    source_testset = load_jsonl(args.testset)
    testset = select_query_subset(source_testset, args.query_subset)
    testset = select_metadata_field_subset(testset, args.metadata_field)
    if not testset:
        raise SystemExit(f"Query subset {args.query_subset!r} selected no test cases")
    selected_ids = {str(test["id"]) for test in testset}
    result_rows = [
        row
        for row in load_jsonl(args.results)
        if str(row.get("test_id") or row.get("id") or row.get("query_id")) in selected_ids
    ]
    details, _ = score(testset, result_rows, k_values)
    summary_rows, by_type_rows, comparison_rows = build_outputs(
        details=details,
        k_values=k_values,
        primary_k=args.primary_k,
        comparisons=parse_comparisons(args.comparisons),
        seed=args.seed,
        bootstrap_samples=args.bootstrap_samples,
    )

    args.output_dir.mkdir(parents=True, exist_ok=True)
    (args.output_dir / "evaluation_scope.json").write_text(
        json.dumps(
            evaluation_scope(
                source_testset,
                testset,
                args.query_subset,
                metadata_field=args.metadata_field,
            ),
            ensure_ascii=False,
            indent=2,
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )
    write_csv(args.output_dir / "retrieval_metric_details.csv", details)
    write_csv(args.output_dir / "retrieval_metric_summary.csv", summary_rows)
    write_csv(args.output_dir / "retrieval_metric_by_query_type.csv", by_type_rows)
    write_csv(
        args.output_dir / "retrieval_metric_by_slice.csv",
        grouped_summary_rows(
            details,
            source_field="benchmark_slices",
            output_field="slice",
            fallback_field="query_type",
            k_values=k_values,
            primary_k=args.primary_k,
        ),
    )
    write_csv(
        args.output_dir / "retrieval_metric_by_metadata_field.csv",
        grouped_summary_rows(
            details,
            source_field="required_metadata_fields",
            output_field="metadata_field",
            k_values=k_values,
            primary_k=args.primary_k,
        ),
    )
    scenario_rows = grouped_summary_rows(
        details,
        source_field="scenario_id",
        output_field="scenario_id",
        k_values=k_values,
        primary_k=args.primary_k,
    )
    evidence_fact_rows = grouped_summary_rows(
        details,
        source_field="evidence_fact_ids",
        output_field="evidence_fact_id",
        k_values=k_values,
        primary_k=args.primary_k,
    )
    write_csv(args.output_dir / "retrieval_metric_by_scenario.csv", scenario_rows)
    write_csv(
        args.output_dir / "retrieval_metric_by_evidence_fact.csv", evidence_fact_rows
    )
    write_csv(
        args.output_dir / "retrieval_metric_macro_summary.csv",
        [
            *macro_summary_rows(
                scenario_rows, grouping_unit="scenario_id", k_values=k_values
            ),
            *macro_summary_rows(
                evidence_fact_rows,
                grouping_unit="evidence_fact_id",
                k_values=k_values,
            ),
        ],
    )
    write_csv(args.output_dir / "retrieval_metric_comparison.csv", comparison_rows)

    print(
        f"Wrote comparison outputs to {args.output_dir} "
        f"for subset={args.query_subset} ({len(testset)}/{len(source_testset)} queries)"
    )
    primary = [row for row in comparison_rows if row.get("metric") == f"recall_at_{args.primary_k}"]
    for row in primary:
        print(
            f"{row['comparison']}: {row['right_mode']} - {row['left_mode']} "
            f"Recall@{args.primary_k} delta={row['absolute_delta']} "
            f"CI=[{row['ci95_low']}, {row['ci95_high']}] "
            f"W/T/L={row['win']}/{row['tie']}/{row['loss']}"
        )


if __name__ == "__main__":
    main()
