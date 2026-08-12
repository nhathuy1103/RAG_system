from __future__ import annotations

import json
from pathlib import Path

import pytest

from evaluation.rag_p5.evaluate import (
    CONFIG_PATH,
    DATASET_PATHS,
    _load_jsonl,
    _sha256_path,
    evaluate,
)


def test_p5_dataset_cardinality_and_frozen_test_hash() -> None:
    assert len(_load_jsonl(DATASET_PATHS["dev"])) == 240
    assert len(_load_jsonl(DATASET_PATHS["test"])) == 120
    assert len(_load_jsonl(DATASET_PATHS["real_world"])) == 100
    assert _sha256_path(DATASET_PATHS["test"]) == (
        "7C9CC734621C3818D2C5A2CF6F885F5CE964CE17D5FD0F4994EBFB60549E0230"
    )


def test_p5_dev_evaluation_passes_without_writing_reports() -> None:
    report = evaluate("dev", write_reports=False)

    assert report["query_count"] == 240
    assert report["acceptance"]["status"] == "PASS"
    assert report["retrieval_metrics"]["evidence_recall_at_10"] == 1.0
    assert report["answer_metrics"]["fact_f1"] == 1.0
    assert report["citation_metrics"]["citation_support_accuracy"] == 1.0


def test_test_split_is_blocked_until_configuration_is_frozen(
    tmp_path: Path,
) -> None:
    config = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
    config["status"] = "development"
    config_path = tmp_path / "p5-development.json"
    config_path.write_text(json.dumps(config), encoding="utf-8")

    with pytest.raises(ValueError, match="requires a frozen configuration"):
        evaluate("test", config_path=config_path, write_reports=False)
