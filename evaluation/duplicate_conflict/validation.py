"""Fail-closed validation for the frozen duplicate/conflict gold dataset."""

from __future__ import annotations

import argparse
import hashlib
import json
from collections import Counter
from dataclasses import dataclass
from pathlib import Path

from jsonschema import Draft202012Validator  # type: ignore[import-untyped]

from app.knowledge_quality.application.analysis import strict_normalize_text
from evaluation.duplicate_conflict.build_dataset import deterministic_split
from evaluation.duplicate_conflict.constants import (
    FULL_DATASET_PATH,
    SCHEMA_PATH,
    SCHEMA_VERSION,
    TAXONOMY_PATH,
)
from evaluation.duplicate_conflict.models import Domain, GoldPair, GoldRelation, SourceForm


@dataclass(frozen=True, slots=True)
class ValidationResult:
    pair_count: int
    errors: tuple[str, ...]
    warnings: tuple[str, ...]
    relation_counts: dict[str, int]
    domain_counts: dict[str, int]
    split_counts: dict[str, int]

    @property
    def valid(self) -> bool:
        return not self.errors

    def to_payload(self) -> dict[str, object]:
        return {
            "valid": self.valid,
            "pair_count": self.pair_count,
            "errors": list(self.errors),
            "warnings": list(self.warnings),
            "relation_counts": self.relation_counts,
            "domain_counts": self.domain_counts,
            "split_counts": self.split_counts,
        }


def load_pairs(path: Path = FULL_DATASET_PATH) -> tuple[GoldPair, ...]:
    pairs: list[GoldPair] = []
    with path.open("r", encoding="utf-8") as handle:
        for line_number, line in enumerate(handle, 1):
            if not line.strip():
                continue
            try:
                pairs.append(GoldPair.model_validate_json(line))
            except Exception as exc:  # Pydantic supplies the field-level diagnostics.
                raise ValueError(f"{path}:{line_number}: {exc}") from exc
    return tuple(pairs)


def _pair_text_key(pair: GoldPair) -> str:
    left = strict_normalize_text("\n".join((*pair.context_a, pair.text_a)))
    right = strict_normalize_text("\n".join((*pair.context_b, pair.text_b)))
    ordered = sorted((left, right))
    return hashlib.sha256("\u241f".join(ordered).encode()).hexdigest()


def _table_errors(pair: GoldPair, side: str) -> list[str]:
    source_form = pair.source_form_a if side == "a" else pair.source_form_b
    table = pair.table_a if side == "a" else pair.table_b
    errors: list[str] = []
    if source_form is SourceForm.TABLE and table is None:
        errors.append(f"{pair.pair_id}: table_{side} is required for table source")
    if source_form is SourceForm.PROSE and table is not None:
        errors.append(f"{pair.pair_id}: table_{side} must be null for prose source")
    if table is not None:
        for index, row in enumerate(table.rows):
            if len(row) != len(table.headers):
                errors.append(
                    f"{pair.pair_id}: table_{side} row {index} width "
                    f"{len(row)} != {len(table.headers)}"
                )
    return errors


def validate_pairs(pairs: tuple[GoldPair, ...], *, require_full: bool = True) -> ValidationResult:
    errors: list[str] = []
    warnings: list[str] = []
    ids: set[str] = set()
    text_keys: dict[str, str] = {}

    try:
        taxonomy = json.loads(TAXONOMY_PATH.read_text(encoding="utf-8"))
        schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        errors.append(f"Dataset contract is unreadable: {exc}")
        taxonomy, schema = {}, {}

    taxonomy_labels = set(taxonomy.get("labels", {}))
    model_labels = {label.value for label in GoldRelation}
    if taxonomy.get("version") != SCHEMA_VERSION:
        errors.append("Taxonomy version differs from the frozen schema version")
    if taxonomy_labels != model_labels:
        errors.append(f"Taxonomy labels differ from model labels: {taxonomy_labels ^ model_labels}")
    if schema.get("$id") != f"urn:rag-notebook:{SCHEMA_VERSION}":
        errors.append("JSON Schema $id differs from the frozen schema version")
    try:
        Draft202012Validator.check_schema(schema)
        schema_validator = Draft202012Validator(schema)
    except Exception as exc:
        errors.append(f"JSON Schema is invalid: {exc}")
        schema_validator = None

    for pair in pairs:
        if schema_validator is not None:
            for schema_error in schema_validator.iter_errors(pair.model_dump(mode="json")):
                location = ".".join(str(part) for part in schema_error.absolute_path) or "$"
                errors.append(
                    f"{pair.pair_id}: JSON Schema error at {location}: {schema_error.message}"
                )
        if pair.pair_id in ids:
            errors.append(f"Duplicate pair_id: {pair.pair_id}")
        ids.add(pair.pair_id)
        expected_split = deterministic_split(pair.pair_id)
        if pair.split != expected_split:
            errors.append(
                f"{pair.pair_id}: split={pair.split!r}, expected deterministic {expected_split!r}"
            )
        text_key = _pair_text_key(pair)
        if text_key in text_keys:
            errors.append(f"Repeated unordered text pair: {text_keys[text_key]} and {pair.pair_id}")
        text_keys[text_key] = pair.pair_id
        errors.extend(_table_errors(pair, "a"))
        errors.extend(_table_errors(pair, "b"))

        relation = pair.expected_relation
        exact_equal = strict_normalize_text(pair.text_a) == strict_normalize_text(pair.text_b)
        if relation is GoldRelation.EXACT_DUPLICATE:
            if not exact_equal:
                errors.append(f"{pair.pair_id}: exact duplicate differs after strict normalization")
            if not pair.expected_auto_reuse:
                errors.append(f"{pair.pair_id}: exact duplicate must permit expected_auto_reuse")
            if not all(
                (
                    pair.same_entity,
                    pair.same_business_scope,
                    pair.same_temporal_scope,
                    pair.same_claim,
                    pair.same_value,
                )
            ):
                errors.append(f"{pair.pair_id}: exact duplicate invariants are contradictory")
        else:
            if exact_equal:
                errors.append(f"{pair.pair_id}: non-exact label has strict-identical text")
            if pair.expected_auto_reuse:
                errors.append(f"{pair.pair_id}: non-exact label may not auto-reuse")

        if relation is GoldRelation.CONFLICT:
            if not pair.critical_conflict or not pair.conflict_fields:
                errors.append(
                    f"{pair.pair_id}: conflict requires critical flag and conflict_fields"
                )
            if (
                not all(
                    (
                        pair.same_entity,
                        pair.same_business_scope,
                        pair.same_temporal_scope,
                        pair.same_claim,
                    )
                )
                or pair.same_value
            ):
                errors.append(f"{pair.pair_id}: conflict scope/value invariants are contradictory")
        elif pair.critical_conflict or pair.conflict_fields:
            errors.append(f"{pair.pair_id}: only CONFLICT may carry critical conflict fields")

        if (
            relation is GoldRelation.TEMPORAL_VARIANT
            and pair.same_temporal_scope
            and not pair.temporal_overlap_justification
        ):
            errors.append(f"{pair.pair_id}: temporal variant lacks temporal divergence")
        if (
            relation is GoldRelation.DISTINCT
            and pair.same_entity
            and pair.same_business_scope
            and pair.same_claim
            and not pair.distinct_justification
        ):
            errors.append(f"{pair.pair_id}: ambiguous DISTINCT lacks justification")
        if (
            pair.extraction_reliability_a.value == "low"
            or pair.extraction_reliability_b.value == "low"
        ) and relation is not GoldRelation.UNCERTAIN:
            warnings.append(f"{pair.pair_id}: low-reliability extraction has assertive label")

    relation_counts = Counter(pair.expected_relation.value for pair in pairs)
    domain_counts = Counter(pair.domain.value for pair in pairs)
    split_counts = Counter(pair.split for pair in pairs)
    if require_full:
        if len(pairs) < 500:
            errors.append(f"Full gold dataset requires >=500 pairs; found {len(pairs)}")
        for domain in Domain:
            if domain_counts[domain.value] < 200:
                errors.append(f"Domain {domain.value} is underrepresented")
        for label in GoldRelation:
            if relation_counts[label.value] < 20:
                errors.append(f"Relation {label.value} has fewer than 20 examples")
        test_ratio = split_counts["test"] / max(1, len(pairs))
        if not 0.25 <= test_ratio <= 0.35:
            errors.append(f"Frozen test split ratio {test_ratio:.3f} is outside [0.25, 0.35]")

    return ValidationResult(
        pair_count=len(pairs),
        errors=tuple(errors),
        warnings=tuple(warnings),
        relation_counts=dict(sorted(relation_counts.items())),
        domain_counts=dict(sorted(domain_counts.items())),
        split_counts=dict(sorted(split_counts.items())),
    )


def validate_dataset(
    path: Path = FULL_DATASET_PATH, *, require_full: bool = True
) -> ValidationResult:
    return validate_pairs(load_pairs(path), require_full=require_full)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("path", nargs="?", type=Path, default=FULL_DATASET_PATH)
    parser.add_argument("--allow-subset", action="store_true")
    args = parser.parse_args(argv)
    result = validate_dataset(args.path, require_full=not args.allow_subset)
    print(json.dumps(result.to_payload(), ensure_ascii=False, indent=2))
    return 0 if result.valid else 1


if __name__ == "__main__":
    raise SystemExit(main())


__all__ = ["ValidationResult", "load_pairs", "validate_dataset", "validate_pairs"]
