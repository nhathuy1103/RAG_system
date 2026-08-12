from __future__ import annotations

import json

from evaluation.duplicate_conflict.build_dataset import deterministic_split
from evaluation.duplicate_conflict.constants import (
    FULL_DATASET_PATH,
    SCHEMA_PATH,
    TAXONOMY_PATH,
)
from evaluation.duplicate_conflict.models import GoldRelation
from evaluation.duplicate_conflict.validation import load_pairs, validate_pairs


def test_full_gold_dataset_validates() -> None:
    result = validate_pairs(load_pairs(FULL_DATASET_PATH))

    assert result.valid, result.errors
    assert result.pair_count == 600
    assert result.domain_counts == {"vinfast": 300, "vinhomes": 300}
    assert set(result.relation_counts) == {label.value for label in GoldRelation}


def test_taxonomy_and_schema_are_versioned_and_complete() -> None:
    taxonomy = json.loads(TAXONOMY_PATH.read_text(encoding="utf-8"))
    schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))

    assert taxonomy["version"] == "duplicate-conflict-gold-v1"
    assert set(taxonomy["labels"]) == {label.value for label in GoldRelation}
    assert schema["$id"] == "urn:rag-notebook:duplicate-conflict-gold-v1"
    assert schema["additionalProperties"] is False


def test_split_is_deterministic_for_every_pair() -> None:
    first = load_pairs(FULL_DATASET_PATH)
    second = load_pairs(FULL_DATASET_PATH)

    assert [(pair.pair_id, pair.split) for pair in first] == [
        (pair.pair_id, pair.split) for pair in second
    ]
    assert all(pair.split == deterministic_split(pair.pair_id) for pair in first)


def test_validator_rejects_reverse_duplicate_pair() -> None:
    original = load_pairs(FULL_DATASET_PATH)[0]
    duplicate_id = "VF_CONDITIONAL_VARIANT_9999"
    reverse = original.model_copy(
        update={
            "pair_id": duplicate_id,
            "split": deterministic_split(duplicate_id),
            "text_a": original.text_b,
            "text_b": original.text_a,
            "context_a": original.context_b,
            "context_b": original.context_a,
        }
    )

    result = validate_pairs((original, reverse), require_full=False)

    assert not result.valid
    assert any("Repeated unordered text pair" in error for error in result.errors)


def test_validator_rejects_contradictory_conflict_metadata() -> None:
    conflict = next(
        pair
        for pair in load_pairs(FULL_DATASET_PATH)
        if pair.expected_relation is GoldRelation.CONFLICT
    )
    invalid = conflict.model_copy(update={"same_value": True})

    result = validate_pairs((invalid,), require_full=False)

    assert not result.valid
    assert any("conflict scope/value invariants" in error for error in result.errors)
