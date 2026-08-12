"""P3 evaluation, freeze, and immutable-report contracts."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

import evaluation.duplicate_conflict.p3_claims as evaluator

CONFIG = Path("configs/evaluation/p3_structured_claims.json")
DEV_DATASET = Path("datasets/duplicate_conflict/gold_v1_dev.jsonl")
DEV_REPORT = Path("reports/evaluation/duplicate_conflict_p3_claims_dev.json")
TEST_DATASET = Path("datasets/duplicate_conflict/gold_v1_test.jsonl")
TEST_REPORT = Path("reports/evaluation/duplicate_conflict_p3_claims_test.json")
BRIDGE_GOLD = Path("datasets/duplicate_conflict/p3_bridge_gold_v1.jsonl")


@pytest.fixture(scope="module")
def dev_report() -> dict[str, object]:
    return evaluator.evaluate_p3(split="dev")


def test_p3_dev_evaluation_runs_real_core_and_meets_acceptance(
    dev_report: dict[str, object],
) -> None:
    assert dev_report["split"] == "dev"
    assert all(dev_report["acceptance"].values())
    assert dev_report["claim_extraction"]["precision"] >= 0.98
    assert dev_report["claim_extraction"]["recall"] >= 0.95
    assert dev_report["alignment"]["precision"] >= 0.99
    assert dev_report["alignment"]["recall"] >= 0.97
    assert dev_report["claim_conflict"]["precision"] >= 0.98
    assert dev_report["claim_conflict"]["recall"] >= 0.9
    assert dev_report["safety"]["false_conflict_admission"] == 0


def test_bridge_gold_covers_both_directions_and_domains() -> None:
    cases = [json.loads(line) for line in BRIDGE_GOLD.read_text(encoding="utf-8").splitlines()]
    dev_cases = [case for case in cases if case["split"] == "dev"]

    assert {case["direction"] for case in dev_cases} == {"table→prose", "prose→table"}
    assert {case["domain"] for case in dev_cases} == {"vinhomes", "vinfast"}
    metrics = evaluator._evaluate_bridge_gold("dev")
    assert metrics["table→prose"]["alignment_accuracy"] == 1.0
    assert metrics["prose→table"]["alignment_accuracy"] == 1.0
    assert metrics["table→prose"]["relation_accuracy"] == 1.0
    assert metrics["prose→table"]["relation_accuracy"] == 1.0


def test_dev_report_writer_allows_explicit_dev_refresh_but_is_immutable_by_default(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    dev_report: dict[str, object],
) -> None:
    monkeypatch.setattr(evaluator, "REPORT_DIR", tmp_path)

    paths = evaluator.write_p3_report(dev_report)
    assert all(path.exists() for path in paths)
    with pytest.raises(FileExistsError, match="refusing to overwrite immutable"):
        evaluator.write_p3_report(dev_report)
    assert evaluator.write_p3_report(dev_report, overwrite_dev=True) == paths


def test_checked_in_dev_report_tracks_frozen_inputs_and_safety() -> None:
    stored = json.loads(DEV_REPORT.read_text(encoding="utf-8"))

    assert stored["configuration_status"] == "frozen"
    assert stored["configuration_sha256"] == _sha256(CONFIG)
    assert stored["dataset_sha256"] == _sha256(DEV_DATASET)
    assert all(stored["acceptance"].values())
    assert stored["safety"]["false_auto_reuse"] == 0
    assert stored["safety"]["false_entity_merge"] == 0
    assert stored["safety"]["false_conflict_admission"] == 0


def test_invalid_split_is_rejected_before_any_test_data_is_loaded() -> None:
    with pytest.raises(ValueError, match="split must be dev or test"):
        evaluator.evaluate_p3(split="holdout")


def test_frozen_test_artifact_matches_frozen_inputs_without_rerunning_test() -> None:
    stored = json.loads(TEST_REPORT.read_text(encoding="utf-8"))

    assert stored["configuration_status"] == "frozen"
    assert stored["configuration_sha256"] == _sha256(CONFIG)
    assert stored["dataset_sha256"] == _sha256(TEST_DATASET)
    assert all(stored["acceptance"].values())
    assert stored["claim_conflict"]["false_positive"] == 0
    assert stored["claim_conflict"]["false_negative"] == 0
    assert stored["safety"]["false_auto_reuse"] == 0
    assert stored["safety"]["false_entity_merge"] == 0
    assert stored["safety"]["false_conflict_admission"] == 0


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest().upper()
