"""Small dependency-free metrics used by the P0 baseline runner."""

from __future__ import annotations

import math
from collections import Counter
from collections.abc import Iterable, Sequence


def classification_metrics(
    expected: Sequence[str], predicted: Sequence[str], *, labels: Sequence[str]
) -> dict[str, object]:
    if len(expected) != len(predicted):
        raise ValueError("expected and predicted must have equal length")
    confusion = {label: {other: 0 for other in labels} for label in labels}
    unknown_predictions: Counter[str] = Counter()
    for gold, prediction in zip(expected, predicted, strict=True):
        if gold not in confusion:
            raise ValueError(f"Unknown gold label: {gold}")
        if prediction in confusion[gold]:
            confusion[gold][prediction] += 1
        else:
            unknown_predictions[prediction] += 1

    per_class: dict[str, dict[str, float | int]] = {}
    for label in labels:
        true_positive = confusion[label][label]
        false_positive = sum(confusion[other][label] for other in labels if other != label)
        support = sum(confusion[label].values())
        precision = (
            true_positive / (true_positive + false_positive)
            if true_positive + false_positive
            else 0.0
        )
        recall = true_positive / support if support else 0.0
        f1 = 2 * precision * recall / (precision + recall) if precision + recall else 0.0
        per_class[label] = {
            "precision": round(precision, 6),
            "recall": round(recall, 6),
            "f1": round(f1, 6),
            "support": support,
        }
    count = len(expected)
    correct = sum(confusion[label][label] for label in labels)
    macro_f1 = sum(float(per_class[label]["f1"]) for label in labels) / max(1, len(labels))
    return {
        "count": count,
        "accuracy": round(correct / count, 6) if count else 0.0,
        "macro_f1": round(macro_f1, 6),
        "per_class": per_class,
        "confusion_matrix": confusion,
        "unknown_predictions": dict(sorted(unknown_predictions.items())),
    }


def recall_at_k(ranks: Iterable[int | None], ks: Sequence[int]) -> dict[str, float]:
    values = tuple(ranks)
    denominator = len(values)
    return {
        f"recall@{k}": round(
            sum(rank is not None and rank <= k for rank in values) / denominator, 6
        )
        if denominator
        else 0.0
        for k in ks
    }


def distribution(values: Iterable[int]) -> dict[str, float | int]:
    ordered = sorted(values)
    if not ordered:
        return {"count": 0, "mean": 0.0, "p50": 0, "p95": 0, "max": 0}

    def percentile(fraction: float) -> int:
        index = max(0, math.ceil(fraction * len(ordered)) - 1)
        return ordered[index]

    return {
        "count": len(ordered),
        "mean": round(sum(ordered) / len(ordered), 3),
        "p50": percentile(0.50),
        "p95": percentile(0.95),
        "max": ordered[-1],
    }


__all__ = ["classification_metrics", "distribution", "recall_at_k"]
