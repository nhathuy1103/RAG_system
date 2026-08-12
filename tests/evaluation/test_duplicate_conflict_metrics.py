from __future__ import annotations

import pytest

from evaluation.duplicate_conflict.metrics import (
    classification_metrics,
    distribution,
    recall_at_k,
)


def test_classification_metrics_known_confusion() -> None:
    metrics = classification_metrics(
        ["A", "A", "B", "B"],
        ["A", "B", "B", "B"],
        labels=("A", "B"),
    )

    assert metrics["accuracy"] == 0.75
    assert metrics["macro_f1"] == pytest.approx(0.733334)
    assert metrics["per_class"]["A"] == {
        "precision": 1.0,
        "recall": 0.5,
        "f1": 0.666667,
        "support": 2,
    }
    assert metrics["confusion_matrix"]["A"] == {"A": 1, "B": 1}


def test_candidate_recall_and_distribution() -> None:
    assert recall_at_k((1, 5, 6, None), (1, 5, 10)) == {
        "recall@1": 0.25,
        "recall@5": 0.5,
        "recall@10": 0.75,
    }
    assert distribution((1, 2, 3, 100)) == {
        "count": 4,
        "mean": 26.5,
        "p50": 2,
        "p95": 100,
        "max": 100,
    }


def test_metrics_reject_mismatched_inputs() -> None:
    with pytest.raises(ValueError, match="equal length"):
        classification_metrics(["A"], [], labels=("A",))
