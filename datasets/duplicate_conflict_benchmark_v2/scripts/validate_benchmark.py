#!/usr/bin/env python3
"""Fail-closed validation for duplicate-conflict-benchmark-v2."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import unicodedata
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any


RELATIONS = {
    "EXACT_DUPLICATE",
    "NEAR_DUPLICATE",
    "VERSION_UPDATE",
    "TEMPORAL_VARIANT",
    "CONDITIONAL_VARIANT",
    "TEMPLATE_VARIANT",
    "CONFLICT",
    "DISTINCT",
    "UNCERTAIN",
}


def load_jsonl(path: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    with path.open("r", encoding="utf-8") as handle:
        for line_number, line in enumerate(handle, 1):
            if not line.strip():
                continue
            try:
                rows.append(json.loads(line))
            except json.JSONDecodeError as exc:
                raise ValueError(f"{path}:{line_number}: {exc}") from exc
    return rows


def normalize(text: str) -> str:
    text = unicodedata.normalize("NFKC", text).replace("\u00a0", " ")
    return re.sub(r"\s+", " ", text).strip().casefold()


def full_input(side: dict[str, Any]) -> str:
    return normalize("\n".join([*side["context"], side["text"]]))


def digest(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def validate(root: Path) -> dict[str, Any]:
    errors: list[str] = []
    warnings: list[str] = []
    manifest = json.loads((root / "manifest.json").read_text(encoding="utf-8"))
    schema = json.loads((root / "schema.json").read_text(encoding="utf-8"))
    pairs = load_jsonl(root / "data" / "benchmark_all.jsonl")
    dev_pairs = load_jsonl(root / "data" / "benchmark_dev.jsonl")
    test_pairs = load_jsonl(root / "data" / "benchmark_test.jsonl")
    evidence_rows = load_jsonl(root / "sources" / "evidence_catalog.jsonl")
    evidence = {row["evidence_id"]: row for row in evidence_rows}
    documents = {row["filename"]: row for row in manifest["source_documents"]}

    try:
        from jsonschema import Draft202012Validator  # type: ignore[import-untyped]

        Draft202012Validator.check_schema(schema)
        validator = Draft202012Validator(schema)
        for pair in pairs:
            for issue in validator.iter_errors(pair):
                location = ".".join(str(value) for value in issue.absolute_path) or "$"
                errors.append(f"{pair.get('pair_id', '?')}: schema {location}: {issue.message}")
    except ImportError:
        required = set(schema.get("required", []))
        allowed = set(schema.get("properties", {}))
        side_required = set(schema.get("$defs", {}).get("side", {}).get("required", []))
        side_allowed = set(
            schema.get("$defs", {}).get("side", {}).get("properties", {})
        )
        for pair in pairs:
            pair_id = pair.get("pair_id", "?")
            missing = required - pair.keys()
            extra = pair.keys() - allowed
            if missing:
                errors.append(f"{pair_id}: missing required fields: {sorted(missing)}")
            if extra:
                errors.append(f"{pair_id}: unexpected fields: {sorted(extra)}")
            for side_name in ("side_a", "side_b"):
                side = pair.get(side_name)
                if not isinstance(side, dict):
                    errors.append(f"{pair_id}: {side_name} must be an object")
                    continue
                side_missing = side_required - side.keys()
                side_extra = side.keys() - side_allowed
                if side_missing:
                    errors.append(
                        f"{pair_id}: {side_name} missing fields: {sorted(side_missing)}"
                    )
                if side_extra:
                    errors.append(
                        f"{pair_id}: {side_name} unexpected fields: {sorted(side_extra)}"
                    )
    except Exception as exc:
        errors.append(f"JSON Schema validation failed to initialize: {exc}")

    if len(evidence) != len(evidence_rows):
        errors.append("Duplicate evidence_id detected")
    for row in evidence_rows:
        if digest(row["text"]) != row["text_sha256"]:
            errors.append(f"{row['evidence_id']}: text SHA-256 mismatch")
        document = documents.get(row["filename"])
        if document is None:
            errors.append(f"{row['evidence_id']}: unknown source document")
        elif row["document_sha256"] != document["sha256"]:
            errors.append(f"{row['evidence_id']}: source document SHA-256 mismatch")

    ids: set[str] = set()
    pair_keys: set[str] = set()
    split_families: dict[str, set[str]] = defaultdict(set)
    split_inputs: dict[str, set[str]] = defaultdict(set)
    relation_counts: Counter[str] = Counter()
    split_counts: Counter[str] = Counter()
    provenance_counts: Counter[str] = Counter()
    difficulty_counts: Counter[str] = Counter()

    for pair in pairs:
        pair_id = pair.get("pair_id", "?")
        split = pair.get("split")
        relation = pair.get("expected_relation")
        if pair_id in ids:
            errors.append(f"Duplicate pair_id: {pair_id}")
        ids.add(pair_id)
        if relation not in RELATIONS:
            errors.append(f"{pair_id}: unknown relation {relation!r}")
        if split not in {"dev", "test"}:
            errors.append(f"{pair_id}: invalid split {split!r}")
            continue
        expected_prefix = f"DCV2_{split.upper()}_"
        if not pair_id.startswith(expected_prefix):
            errors.append(f"{pair_id}: pair ID does not match split")

        relation_counts[relation] += 1
        split_counts[split] += 1
        provenance_counts[pair["provenance_kind"]] += 1
        difficulty_counts[pair["difficulty"]] += 1

        full_a = full_input(pair["side_a"])
        full_b = full_input(pair["side_b"])
        unordered_key = digest("\u241f".join(sorted((full_a, full_b))))
        if unordered_key in pair_keys:
            errors.append(f"{pair_id}: repeated unordered full-input pair")
        pair_keys.add(unordered_key)
        split_inputs[split].update((digest(full_a), digest(full_b)))

        for side_name in ("side_a", "side_b"):
            side = pair[side_name]
            item = evidence.get(side["source_evidence_id"])
            if item is None:
                errors.append(f"{pair_id}: missing {side_name} evidence")
                continue
            if side["source_form"] != item["source_form"]:
                errors.append(f"{pair_id}: {side_name} source_form differs from catalog")
            if side["representation"] == "observed" and side["text"] != item["text"]:
                errors.append(f"{pair_id}: observed {side_name} text differs from catalog")
            if side["representation"] == "controlled_mutation" and not pair["is_synthetic"]:
                errors.append(f"{pair_id}: controlled side in non-synthetic pair")

        for filename in pair["source_documents"]:
            document = documents.get(filename)
            if document is None:
                errors.append(f"{pair_id}: source document absent from manifest: {filename}")
                continue
            if document["split"] != split:
                errors.append(f"{pair_id}: source document crosses split: {filename}")
            split_families[split].add(document["document_id"])

        mutation = pair["mutation"]
        if pair["is_synthetic"]:
            if pair["provenance_kind"] != "controlled_mutation" or mutation is None:
                errors.append(f"{pair_id}: synthetic pair lacks controlled mutation provenance")
            elif mutation["parent_evidence_id"] not in evidence:
                errors.append(f"{pair_id}: mutation parent evidence is missing")
        elif pair["provenance_kind"] != "observed" or mutation is not None:
            errors.append(f"{pair_id}: observed pair carries mutation metadata")

        inv = pair["invariants"]
        same_full_input = full_a == full_b
        if relation == "EXACT_DUPLICATE":
            if not same_full_input:
                errors.append(f"{pair_id}: exact duplicate differs after full-input normalization")
            if not all(inv.values()):
                errors.append(f"{pair_id}: exact duplicate invariants are inconsistent")
            if not pair["expected_auto_reuse"]:
                errors.append(f"{pair_id}: exact duplicate must permit auto-reuse")
        else:
            if pair["expected_auto_reuse"]:
                errors.append(f"{pair_id}: non-exact relation permits auto-reuse")
            if same_full_input:
                errors.append(f"{pair_id}: non-exact relation has identical full input")

        if relation == "TEMPLATE_VARIANT":
            if normalize(pair["side_a"]["text"]) != normalize(pair["side_b"]["text"]):
                errors.append(f"{pair_id}: template hard case must share normalized body text")
            if inv["same_entity"]:
                errors.append(f"{pair_id}: template variant incorrectly marks same entity")

        if relation == "CONFLICT":
            if not pair["critical_conflict"] or not pair["conflict_fields"]:
                errors.append(f"{pair_id}: conflict lacks critical flag/fields")
            if not all(
                inv[key]
                for key in ("same_entity", "same_business_scope", "same_temporal_scope", "same_claim")
            ) or inv["same_value"]:
                errors.append(f"{pair_id}: conflict invariants are inconsistent")
        elif pair["critical_conflict"] or pair["conflict_fields"]:
            errors.append(f"{pair_id}: only conflicts may carry conflict fields")

        if relation == "TEMPORAL_VARIANT":
            if inv["same_temporal_scope"] or not pair["temporal_overlap_justification"]:
                errors.append(f"{pair_id}: temporal variant lacks non-overlap evidence")
        if relation == "DISTINCT" and not pair["distinct_justification"]:
            errors.append(f"{pair_id}: DISTINCT lacks explicit justification")

    if split_families["dev"] & split_families["test"]:
        errors.append("Source-family leakage between dev and test")
    overlapping_inputs = split_inputs["dev"] & split_inputs["test"]
    if overlapping_inputs:
        errors.append(f"Exact full-input leakage between splits: {len(overlapping_inputs)} inputs")

    dev_ids = {pair["pair_id"] for pair in dev_pairs}
    test_ids = {pair["pair_id"] for pair in test_pairs}
    if dev_ids & test_ids:
        errors.append("Pair appears in both dev and test files")
    if dev_ids | test_ids != ids:
        errors.append("Split files do not exactly partition benchmark_all.jsonl")
    if any(pair["split"] != "dev" for pair in dev_pairs):
        errors.append("benchmark_dev.jsonl contains non-dev pair")
    if any(pair["split"] != "test" for pair in test_pairs):
        errors.append("benchmark_test.jsonl contains non-test pair")

    if len(pairs) != manifest["pair_count"]:
        errors.append("Manifest pair_count mismatch")
    if len(evidence_rows) != manifest["evidence_count"]:
        errors.append("Manifest evidence_count mismatch")
    for relation in RELATIONS:
        if relation_counts[relation] < 10:
            errors.append(f"Relation {relation} has fewer than 10 cases")
    observed_ratio = provenance_counts["observed"] / max(1, len(pairs))
    test_ratio = split_counts["test"] / max(1, len(pairs))
    if observed_ratio < 0.5:
        errors.append(f"Observed-evidence ratio is too low: {observed_ratio:.3f}")
    if not 0.35 <= test_ratio <= 0.45:
        errors.append(f"Test ratio outside [0.35, 0.45]: {test_ratio:.3f}")

    return {
        "valid": not errors,
        "pair_count": len(pairs),
        "evidence_count": len(evidence_rows),
        "errors": errors,
        "warnings": warnings,
        "relation_counts": dict(sorted(relation_counts.items())),
        "split_counts": dict(sorted(split_counts.items())),
        "provenance_counts": dict(sorted(provenance_counts.items())),
        "difficulty_counts": dict(sorted(difficulty_counts.items())),
        "test_ratio": round(test_ratio, 6),
        "observed_ratio": round(observed_ratio, 6),
        "cross_split_full_input_overlap": len(overlapping_inputs),
        "source_family_overlap": sorted(split_families["dev"] & split_families["test"]),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("root", nargs="?", type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument("--write-report", action="store_true")
    args = parser.parse_args()
    result = validate(args.root)
    output = json.dumps(result, ensure_ascii=False, indent=2) + "\n"
    print(output, end="")
    if args.write_report:
        report = args.root / "reports" / "validation_report.json"
        report.write_text(output, encoding="utf-8")
    return 0 if result["valid"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
