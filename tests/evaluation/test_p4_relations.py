from __future__ import annotations

import json
from pathlib import Path

import pytest

from evaluation.duplicate_conflict.p4_relations import P4_CONFIG_PATH, evaluate_p4


def test_p4_dev_report_is_claim_grounded_and_safety_preserving() -> None:
    report = evaluate_p4(split="dev")

    assert report["pair_count"] == 421
    final = report["final_relation"]
    safety = report["safety"]
    retrieval = report["retrieval"]
    regression = report["p1_p2_p3_regression"]
    assert final["per_class"]["EXACT_DUPLICATE"]["precision"] == 1.0
    assert final["per_class"]["CONFLICT"]["precision"] == 1.0
    assert safety["false_exact_collapse"] == 0
    assert safety["conflict_suppression"] == 0
    assert safety["provenance_loss"] == 0
    assert safety["permission_relation_leakage"] == 0
    assert retrieval["conflict_preservation_recall_at_k"] == 1.0
    assert retrieval["provenance_retention"] == 1.0
    assert retrieval["base_relevance_recall"]["delta"] >= 0.0
    assert report["version_lineage"]["unknown_current_validity_preserved"] == 1.0
    assert regression["p1_candidate_recall_at_50"] == 1.0


def test_p4_dev_known_failures_remain_conservative() -> None:
    report = evaluate_p4(split="dev")

    failures = report["failure_taxonomy"]
    assert failures["counts"]["P2_GATE_BLOCKED"] == 5
    assert report["acceptance"]["status"] == "PARTIAL"
    assert set(report["acceptance"]["failed_checks"]) == {"macro_f1", "conflict_recall"}


def test_unfrozen_configuration_cannot_run_test(tmp_path: Path) -> None:
    config = json.loads(P4_CONFIG_PATH.read_text(encoding="utf-8"))
    config["status"] = "development"
    unfrozen = tmp_path / "p4-unfrozen.json"
    unfrozen.write_text(json.dumps(config), encoding="utf-8")

    with pytest.raises(ValueError, match="requires a frozen configuration"):
        evaluate_p4(split="test", config_path=unfrozen)


def test_frozen_test_rejects_hash_drift_before_reading_gold(tmp_path: Path) -> None:
    config = json.loads(P4_CONFIG_PATH.read_text(encoding="utf-8"))
    config["status"] = "frozen"
    config["frozen_inputs_sha256"] = {"missing-p4-input": "0" * 64}
    drifted = tmp_path / "p4-drifted.json"
    drifted.write_text(json.dumps(config), encoding="utf-8")

    with pytest.raises(ValueError, match="frozen input hash mismatch"):
        evaluate_p4(split="test", config_path=drifted)
