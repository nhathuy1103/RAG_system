"""Stable paths and version identifiers for the frozen P0 benchmark."""

from __future__ import annotations

from pathlib import Path
from typing import Final

SCHEMA_VERSION: Final = "duplicate-conflict-gold-v1"
TAXONOMY_VERSION: Final = "duplicate-conflict-gold-v1"
SPLIT_SEED: Final = "duplicate-conflict-gold-v1:20260812"
TEST_PERCENT = 30
CANDIDATE_DISTRACTOR_COUNT = 60
CANDIDATE_EVALUATION_LIMIT = 50
RUNTIME_CANDIDATES_PER_PROBE = 5
RUNTIME_MAX_PROBE_CHUNKS = 8

REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
DATASET_DIR = REPOSITORY_ROOT / "datasets" / "duplicate_conflict"
CONFIG_DIR = REPOSITORY_ROOT / "configs" / "evaluation"
REPORT_DIR = REPOSITORY_ROOT / "reports" / "evaluation"
FULL_DATASET_PATH = DATASET_DIR / "gold_v1.jsonl"
DEV_DATASET_PATH = DATASET_DIR / "gold_v1_dev.jsonl"
TEST_DATASET_PATH = DATASET_DIR / "gold_v1_test.jsonl"
SMOKE_DATASET_PATH = REPOSITORY_ROOT / "tests" / "fixtures" / "duplicate_conflict_smoke.jsonl"
STRESS_CASES_PATH = DATASET_DIR / "stress_cases.json"
TAXONOMY_PATH = CONFIG_DIR / "duplicate_conflict_taxonomy.json"
SCHEMA_PATH = DATASET_DIR / "schema.json"
JSON_REPORT_PATH = REPORT_DIR / "duplicate_conflict_baseline.json"
MARKDOWN_REPORT_PATH = REPORT_DIR / "duplicate_conflict_baseline.md"

__all__ = [
    "CANDIDATE_DISTRACTOR_COUNT",
    "CANDIDATE_EVALUATION_LIMIT",
    "CONFIG_DIR",
    "DATASET_DIR",
    "DEV_DATASET_PATH",
    "FULL_DATASET_PATH",
    "JSON_REPORT_PATH",
    "MARKDOWN_REPORT_PATH",
    "REPORT_DIR",
    "REPOSITORY_ROOT",
    "RUNTIME_CANDIDATES_PER_PROBE",
    "RUNTIME_MAX_PROBE_CHUNKS",
    "SCHEMA_PATH",
    "SCHEMA_VERSION",
    "SMOKE_DATASET_PATH",
    "SPLIT_SEED",
    "STRESS_CASES_PATH",
    "TAXONOMY_PATH",
    "TAXONOMY_VERSION",
    "TEST_DATASET_PATH",
    "TEST_PERCENT",
]
