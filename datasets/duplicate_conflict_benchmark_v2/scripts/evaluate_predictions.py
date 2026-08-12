#!/usr/bin/env python3
"""Evaluate pair predictions with stratified and safety-oriented metrics."""

from __future__ import annotations

import argparse
import json
import math
from collections import Counter
from pathlib import Path
from typing import Any, Callable


LABELS = (
    "EXACT_DUPLICATE",
    "NEAR_DUPLICATE",
    "VERSION_UPDATE",
    "TEMPORAL_VARIANT",
    "CONDITIONAL_VARIANT",
    "TEMPLATE_VARIANT",
    "CONFLICT",
    "DISTINCT",
    "UNCERTAIN",
)


def load_jsonl(path: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    with path.open("r", encoding="utf-8") as handle:
        for line_number, line in enumerate(handle, 1):
            if not line.strip():
                continue
            try:
                rows.append(json.loads(line))
            except json.JSONDecodeError as exc:
                raise ValueError(f"{path}:{line_number}: {exc}") from exc
    return rows


def safe_div(numerator: int, denominator: int) -> float:
    return numerator / denominator if denominator else 0.0


def wilson(successes: int, total: int, z: float = 1.96) -> list[float]:
    if total == 0:
        return [0.0, 0.0]
    rate = successes / total
    denominator = 1 + z * z / total
    center = (rate + z * z / (2 * total)) / denominator
    margin = z * math.sqrt(rate * (1 - rate) / total + z * z / (4 * total * total)) / denominator
    return [round(max(0.0, center - margin), 6), round(min(1.0, center + margin), 6)]


def classification(gold: list[str], predicted: list[str]) -> dict[str, Any]:
    confusion = {label: {other: 0 for other in LABELS} for label in LABELS}
    for expected, actual in zip(gold, predicted, strict=True):
        confusion[expected][actual] += 1
    per_class: dict[str, dict[str, Any]] = {}
    supported: list[str] = []
    for label in LABELS:
        tp = confusion[label][label]
        fp = sum(confusion[other][label] for other in LABELS if other != label)
        fn = sum(confusion[label][other] for other in LABELS if other != label)
        support = tp + fn
        precision = safe_div(tp, tp + fp)
        recall = safe_div(tp, support)
        f1 = safe_div(2 * precision * recall, precision + recall)
        if support:
            supported.append(label)
        per_class[label] = {
            "precision": round(precision, 6),
            "recall": round(recall, 6),
            "f1": round(f1, 6),
            "support": support,
        }
    correct = sum(confusion[label][label] for label in LABELS)
    macro_f1 = safe_div(sum(per_class[label]["f1"] for label in supported), len(supported))
    return {
        "count": len(gold),
        "accuracy": round(safe_div(correct, len(gold)), 6),
        "macro_f1_supported": round(macro_f1, 6),
        "supported_labels": supported,
        "per_class": per_class,
        "confusion_matrix": confusion,
    }


def slice_metrics(
    pairs: list[dict[str, Any]],
    predictions: dict[str, str],
    selector: Callable[[dict[str, Any]], str],
) -> dict[str, Any]:
    buckets: dict[str, list[dict[str, Any]]] = {}
    for pair in pairs:
        buckets.setdefault(selector(pair), []).append(pair)
    return {
        key: classification(
            [pair["expected_relation"] for pair in rows],
            [predictions[pair["pair_id"]] for pair in rows],
        )
        for key, rows in sorted(buckets.items())
    }


def safety_metrics(pairs: list[dict[str, Any]], predictions: dict[str, str]) -> dict[str, Any]:
    predicted_exact = [pair for pair in pairs if predictions[pair["pair_id"]] == "EXACT_DUPLICATE"]
    correct_exact = sum(pair["expected_relation"] == "EXACT_DUPLICATE" for pair in predicted_exact)
    unsafe_reuse = len(predicted_exact) - correct_exact
    actual_conflicts = [pair for pair in pairs if pair["expected_relation"] == "CONFLICT"]
    caught_conflicts = sum(predictions[pair["pair_id"]] == "CONFLICT" for pair in actual_conflicts)
    false_conflicts = sum(
        predictions[pair["pair_id"]] == "CONFLICT" and pair["expected_relation"] != "CONFLICT"
        for pair in pairs
    )
    predicted_conflicts = sum(predictions[pair["pair_id"]] == "CONFLICT" for pair in pairs)
    return {
        "auto_reuse_precision": round(safe_div(correct_exact, len(predicted_exact)), 6),
        "auto_reuse_precision_95ci": wilson(correct_exact, len(predicted_exact)),
        "unsafe_auto_reuse_count": unsafe_reuse,
        "unsafe_auto_reuse_rate_all": round(safe_div(unsafe_reuse, len(pairs)), 6),
        "conflict_recall": round(safe_div(caught_conflicts, len(actual_conflicts)), 6),
        "conflict_recall_95ci": wilson(caught_conflicts, len(actual_conflicts)),
        "missed_conflict_count": len(actual_conflicts) - caught_conflicts,
        "false_conflict_count": false_conflicts,
        "false_conflict_rate_predicted": round(safe_div(false_conflicts, predicted_conflicts), 6),
    }


def main() -> int:
    root = Path(__file__).resolve().parents[1]
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("predictions", type=Path, help="JSONL with pair_id and predicted_relation")
    parser.add_argument("--gold", type=Path, default=root / "data" / "benchmark_test.jsonl")
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()

    pairs = load_jsonl(args.gold)
    prediction_rows = load_jsonl(args.predictions)
    predictions: dict[str, str] = {}
    for row in prediction_rows:
        pair_id = row.get("pair_id")
        label = row.get("predicted_relation")
        if pair_id in predictions:
            raise ValueError(f"Duplicate prediction for {pair_id}")
        if label not in LABELS:
            raise ValueError(f"Unknown prediction label for {pair_id}: {label!r}")
        predictions[pair_id] = label
    gold_ids = {pair["pair_id"] for pair in pairs}
    missing = gold_ids - predictions.keys()
    extra = predictions.keys() - gold_ids
    if missing or extra:
        raise ValueError(f"Prediction coverage mismatch; missing={sorted(missing)}, extra={sorted(extra)}")

    gold = [pair["expected_relation"] for pair in pairs]
    predicted = [predictions[pair["pair_id"]] for pair in pairs]
    report = {
        "gold_file": str(args.gold),
        "overall": classification(gold, predicted),
        "safety": safety_metrics(pairs, predictions),
        "by_provenance": slice_metrics(pairs, predictions, lambda pair: pair["provenance_kind"]),
        "by_difficulty": slice_metrics(pairs, predictions, lambda pair: pair["difficulty"]),
        "by_source_form": slice_metrics(
            pairs,
            predictions,
            lambda pair: f"{pair['side_a']['source_form']}->{pair['side_b']['source_form']}",
        ),
        "prediction_distribution": dict(sorted(Counter(predicted).items())),
    }
    payload = json.dumps(report, ensure_ascii=False, indent=2) + "\n"
    print(payload, end="")
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(payload, encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
