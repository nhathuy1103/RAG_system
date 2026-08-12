"""Reproducibility contracts for the frozen P2 evaluator and reports."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

from evaluation.duplicate_conflict.p2_scope import evaluate_p2

CONFIG = Path("configs/evaluation/p2_domain_scope.json")
DEV_REPORT = Path("reports/evaluation/duplicate_conflict_p2_scope_dev.json")
DEV_MARKDOWN = Path("reports/evaluation/duplicate_conflict_p2_scope_dev.md")
TEST_DATASET = Path("datasets/duplicate_conflict/gold_v1_test.jsonl")
TEST_REPORT = Path("reports/evaluation/duplicate_conflict_p2_scope_test.json")


def test_p2_dev_report_is_reproducible_from_frozen_configuration() -> None:
    stored = json.loads(DEV_REPORT.read_text(encoding="utf-8"))
    generated = json.loads(json.dumps(evaluate_p2(split="dev")))

    assert generated == stored
    assert stored["configuration_status"] == "frozen"
    assert all(stored["acceptance"].values())


def test_p2_frozen_test_artifact_matches_frozen_inputs_and_safety_contract() -> None:
    stored = json.loads(TEST_REPORT.read_text(encoding="utf-8"))

    assert stored["configuration_status"] == "frozen"
    assert stored["configuration_sha256"] == _sha256(CONFIG)
    assert stored["dataset_sha256"] == _sha256(TEST_DATASET)
    assert stored["entity_metrics"]["precision"] == 1.0
    assert stored["admission_metrics"]["precision"] == 1.0
    assert stored["safety"]["false_auto_reuse"] == 0
    assert stored["safety"]["false_entity_merges"] == 0
    assert stored["safety"]["false_conflict_admissions"] == 0


def test_p2_markdown_contains_required_metric_sections() -> None:
    markdown = DEV_MARKDOWN.read_text(encoding="utf-8")

    for heading in (
        "## Frozen P1 state",
        "## Entity resolution",
        "## Scope and conflict admission",
        "## Temporal and qualifier compatibility",
        "## Domain breakdown",
        "## Difficulty breakdown",
        "## Ocr Level breakdown",
        "## Ablation",
        "## Critical case matrix",
        "## Existing classifier after gate",
        "## Safety",
        "## Remaining P2 errors",
        "## Acceptance",
    ):
        assert heading in markdown


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest().upper()
