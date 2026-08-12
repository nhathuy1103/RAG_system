from __future__ import annotations

from evaluation.duplicate_conflict.constants import SMOKE_DATASET_PATH
from evaluation.duplicate_conflict.models import GoldRelation
from evaluation.duplicate_conflict.runner import build_report, evaluate_pair
from evaluation.duplicate_conflict.validation import load_pairs


def test_smoke_runner_separates_candidate_and_classifier_metrics() -> None:
    pairs = load_pairs(SMOKE_DATASET_PATH)

    report = build_report(pairs, require_full_dataset=False)

    assert report["dataset"]["valid"] is True
    assert report["dataset"]["pair_count"] == 18
    assert set(report["candidate_generation"]) >= {"recall@1", "recall@5", "recall@50"}
    assert report["oracle_pair_classification"]["count"] == 18
    assert report["reached_classifier_classification"]["count"] <= 18
    assert report["safety"]["false_auto_reuse_count"] == 0


def test_current_sampling_and_lsh_counterexample_are_exposed() -> None:
    report = build_report(load_pairs(SMOKE_DATASET_PATH), require_full_dataset=False)
    stress = report["stress_tests"]

    assert stress["long_document_sampling"]["chunk_count"] == 100
    assert stress["long_document_sampling"]["meaningful_position_recall"] == 0.2
    assert stress["simhash_lsh_counterexample"] == {
        "hamming_distance": 21,
        "maximum_hamming_distance": 24,
        "aligned_band_overlap": 0,
        "raw_relation": "near_duplicate",
        "candidate_generated": False,
        "demonstrates_lsh_false_negative": True,
    }


def test_incorrect_prediction_has_failure_attribution() -> None:
    pairs = load_pairs(SMOKE_DATASET_PATH)
    pair = next(pair for pair in pairs if pair.expected_relation is GoldRelation.UNCERTAIN)

    result = evaluate_pair(pair, pairs)

    assert result.oracle_prediction != pair.expected_relation.value
    assert result.failure_category is not None


def test_report_is_deterministic() -> None:
    pairs = load_pairs(SMOKE_DATASET_PATH)

    assert build_report(pairs, require_full_dataset=False) == build_report(
        pairs, require_full_dataset=False
    )
