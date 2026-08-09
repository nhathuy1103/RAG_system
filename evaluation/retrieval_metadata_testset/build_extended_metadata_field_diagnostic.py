"""Build an evidence-traceable diagnostic for pre-retrieval metadata fields.

This does not modify or claim approval of the frozen benchmark. Diagnostic
conditions come only from an existing frozen condition, a deterministic
one-to-one field substitution observed in gold metadata, or a value stated
directly in the query.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import statistics
import unicodedata
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

SCRIPT_DIR = Path(__file__).resolve().parent
DEFAULT_TESTSET = SCRIPT_DIR / "real_benchmark_v3" / "testset.jsonl"
DEFAULT_CORPUS = (
    SCRIPT_DIR
    / "runs"
    / "real-benchmark-v3-context-quality-v4-openai"
    / "corpus.jsonl"
)
DEFAULT_OUTPUT = SCRIPT_DIR / "extended_metadata_field_diagnostic"

SECURITY_FIELDS = {"owner_id", "notebook_id", "document_ids", "visibility", "allowed_groups"}
PROVENANCE_FIELDS = {
    "chunk_index",
    "page_number",
    "source_block_ids",
    "table_id",
    "table_identity",
    "table_location",
    "bbox",
}
RANKING_FIELDS = {
    "title",
    "section_title",
    "section_path",
    "content_kind",
    "table_header",
    "contextual_summary",
    "contextual_search_terms",
    "keyword_aliases",
    "language",
}

SUBSTITUTIONS = {
    "project_name": ("project_code", "canonical_alias_resolution"),
    "year": ("data_period", "annual_period_equivalence"),
    "lifecycle_status": ("effective_status", "current_latest_equivalence"),
    "document_type": ("domain", "document_type_domain_mapping"),
}
EXPLICIT_FIELDS = ("project_code", "region", "section_title")
REDUNDANCY_PAIRS = (
    ("document_type", "domain"),
    ("project_name", "project_code"),
    ("year", "data_period"),
    ("year", "as_of_date"),
    ("lifecycle_status", "effective_status"),
    ("lifecycle_status", "document_version"),
    ("source", "source_code"),
    ("source", "source_kind"),
    ("section_title", "project_code"),
)


def _load_jsonl(path: Path) -> list[dict[str, Any]]:
    with path.open(encoding="utf-8") as handle:
        return [json.loads(line) for line in handle if line.strip()]


def _write_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    with path.open("w", encoding="utf-8", newline="\n") as handle:
        for row in rows:
            handle.write(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n")


def _write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    if not rows:
        return
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)


def _write_json(path: Path, value: Any) -> None:
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    digest.update(path.read_bytes())
    return digest.hexdigest()


def _normalize(value: object) -> str:
    text = unicodedata.normalize("NFD", str(value or "").casefold())
    text = "".join(char for char in text if unicodedata.category(char) != "Mn")
    return " ".join(text.split())


def _serialized(value: object) -> str:
    if isinstance(value, list):
        return " > ".join(_normalize(item) for item in value)
    if isinstance(value, dict):
        return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return _normalize(value)


def _present(value: object) -> bool:
    return value not in (None, "", [], {})


def _percentile(values: list[float], fraction: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    return ordered[round((len(ordered) - 1) * fraction)]


def _metadata_conditions(test: dict[str, Any]) -> list[dict[str, Any]]:
    filters = test.get("retrieval_filters")
    if not isinstance(filters, dict):
        return []
    conditions = filters.get("metadata_conditions")
    if not isinstance(conditions, list):
        return []
    return [dict(item) for item in conditions if isinstance(item, dict)]


def _consistent_relevant_value(
    test: dict[str, Any],
    field: str,
    chunks_by_id: dict[str, dict[str, Any]],
) -> object | None:
    values: list[object] = []
    for chunk_id in test.get("relevant_chunk_ids", []):
        chunk = chunks_by_id.get(str(chunk_id))
        if chunk is None:
            return None
        value = (chunk.get("gold_metadata") or {}).get(field)
        if not _present(value) or isinstance(value, dict | list):
            return None
        values.append(value)
    if not values:
        return None
    normalized = {_serialized(value) for value in values}
    return values[0] if len(normalized) == 1 else None


def _pair_mapping(
    chunks: list[dict[str, Any]], left: str, right: str
) -> dict[str, set[str]]:
    mapping: dict[str, set[str]] = defaultdict(set)
    for chunk in chunks:
        metadata = chunk.get("gold_metadata") or {}
        left_value = metadata.get(left)
        right_value = metadata.get(right)
        if not _present(left_value) or not _present(right_value):
            continue
        if isinstance(left_value, dict | list) or isinstance(right_value, dict | list):
            continue
        mapping[_serialized(left_value)].add(_serialized(right_value))
    return mapping


def _clone_diagnostic(
    test: dict[str, Any],
    *,
    field: str,
    value: object,
    basis: str,
    source_field: str,
) -> dict[str, Any]:
    row = json.loads(json.dumps(test, ensure_ascii=False))
    source_id = str(test["id"])
    row["id"] = f"diag_{field}_{source_id}"
    row["query_id"] = row["id"]
    row["annotation_status"] = "derived_diagnostic_requires_human_review"
    row["human_review"] = {
        "status": "not_reviewed",
        "approval_basis": (
            "Derived from approved frozen evidence; diagnostic condition needs review."
        ),
    }
    row["required_metadata_fields"] = [field]
    row["metadata_focus"] = [field]
    row["retrieval_filters"] = {
        "metadata_conditions": [{"field": field, "op": "eq", "value": value}],
        "unsupported_field_policy": "fail_closed",
    }
    row["expected_metadata"] = {
        "metadata_conditions": row["retrieval_filters"]["metadata_conditions"],
        "required_fields": [field],
    }
    row["diagnostic_provenance"] = {
        "basis": basis,
        "source_test_id": source_id,
        "source_field": source_field,
        "target_field": field,
        "frozen_test_unchanged": True,
    }
    return row


def _field_group(field: str) -> str:
    if field in SECURITY_FIELDS:
        return "security"
    if field in PROVENANCE_FIELDS:
        return "provenance"
    if field in RANKING_FIELDS:
        return "ranking_or_routing"
    if field == "context_enrichment":
        return "operational"
    return "domain_filter_candidate"


def _field_profiles(
    chunks: list[dict[str, Any]],
    tests: list[dict[str, Any]],
    diagnostics: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    fields = sorted(
        {
            key
            for chunk in chunks
            for source in (chunk.get("current_metadata") or {}, chunk.get("gold_metadata") or {})
            for key in source
        }
    )
    required_counts = Counter(
        str(field) for test in tests for field in test.get("required_metadata_fields", [])
    )
    condition_counts = Counter(
        str(condition.get("field") or "")
        for test in tests
        for condition in _metadata_conditions(test)
    )
    diagnostic_counts = Counter(
        str(test["retrieval_filters"]["metadata_conditions"][0]["field"])
        for test in diagnostics
    )
    rows: list[dict[str, Any]] = []
    corpus_size = len(chunks)
    for field in fields:
        current_values = [
            (chunk.get("current_metadata") or {}).get(field) for chunk in chunks
        ]
        gold_values = [(chunk.get("gold_metadata") or {}).get(field) for chunk in chunks]
        current_present = [value for value in current_values if _present(value)]
        gold_present = [value for value in gold_values if _present(value)]
        frequencies = Counter(_serialized(value) for value in gold_present)
        candidate_counts = list(frequencies.values())
        paired = [
            (current, gold)
            for current, gold in zip(current_values, gold_values, strict=True)
            if _present(current) and _present(gold)
        ]
        agreements = sum(_serialized(current) == _serialized(gold) for current, gold in paired)
        false_positives = sum(
            _present(current)
            and (
                not _present(gold) or _serialized(current) != _serialized(gold)
            )
            for current, gold in zip(current_values, gold_values, strict=True)
        )
        false_negatives = sum(
            _present(gold) and not _present(current)
            for current, gold in zip(current_values, gold_values, strict=True)
        )
        weighted_candidates = (
            sum(count * count for count in frequencies.values()) / len(gold_present)
            if gold_present
            else 0.0
        )
        rows.append(
            {
                "field": field,
                "group": _field_group(field),
                "current_coverage": len(current_present),
                "gold_coverage": len(gold_present),
                "current_coverage_rate": round(len(current_present) / corpus_size, 6),
                "gold_coverage_rate": round(len(gold_present) / corpus_size, 6),
                "strict_reference_precision": round(agreements / len(current_present), 6)
                if current_present
                else "",
                "reference_recall": round(agreements / len(gold_present), 6)
                if gold_present
                else "",
                "unlabeled_or_mismatch_count": false_positives,
                "reference_missing_count": false_negatives,
                "distinct_gold_values": len(frequencies),
                "expected_candidates_for_observed_value": round(weighted_candidates, 3),
                "expected_candidate_reduction_pct": round(
                    (1 - weighted_candidates / corpus_size) * 100
                    if corpus_size and gold_present
                    else 0.0,
                    3,
                ),
                "p50_candidates_per_value": round(statistics.median(candidate_counts), 3)
                if candidate_counts
                else 0,
                "p95_candidates_per_value": round(_percentile(candidate_counts, 0.95), 3),
                "current_gold_overlap": len(paired),
                "current_gold_agreement_rate": round(agreements / len(paired), 6)
                if paired
                else "",
                "required_query_count": required_counts[field],
                "frozen_condition_count": condition_counts[field],
                "diagnostic_query_count": diagnostic_counts[field],
            }
        )
    return rows


def _redundancy_rows(chunks: list[dict[str, Any]]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for left, right in REDUNDANCY_PAIRS:
        pairs: list[tuple[str, str]] = []
        for chunk in chunks:
            metadata = chunk.get("gold_metadata") or {}
            left_value = metadata.get(left)
            right_value = metadata.get(right)
            if not _present(left_value) or not _present(right_value):
                continue
            if isinstance(left_value, dict | list) or isinstance(right_value, dict | list):
                continue
            pairs.append((_serialized(left_value), _serialized(right_value)))
        left_map: dict[str, set[str]] = defaultdict(set)
        right_map: dict[str, set[str]] = defaultdict(set)
        for left_value, right_value in pairs:
            left_map[left_value].add(right_value)
            right_map[right_value].add(left_value)
        left_deterministic_rows = sum(
            1 for left_value, _ in pairs if len(left_map[left_value]) == 1
        )
        right_deterministic_rows = sum(
            1 for _, right_value in pairs if len(right_map[right_value]) == 1
        )
        rows.append(
            {
                "left_field": left,
                "right_field": right,
                "overlap_chunks": len(pairs),
                "distinct_left": len(left_map),
                "distinct_right": len(right_map),
                "left_determines_right_rate": round(left_deterministic_rows / len(pairs), 6)
                if pairs
                else "",
                "right_determines_left_rate": round(right_deterministic_rows / len(pairs), 6)
                if pairs
                else "",
                "one_to_one": bool(pairs)
                and all(len(values) == 1 for values in left_map.values())
                and all(len(values) == 1 for values in right_map.values()),
            }
        )
    return rows


def _condition_matches(metadata: dict[str, Any], condition: dict[str, Any]) -> bool:
    actual = metadata.get(str(condition["field"]))
    expected = condition.get("value")
    return any(
        _serialized(left) == _serialized(right)
        for left in (actual if isinstance(actual, list) else [actual])
        for right in (expected if isinstance(expected, list) else [expected])
    )


def _candidate_rows(
    diagnostics: list[dict[str, Any]],
    chunks: list[dict[str, Any]],
    *,
    metadata_source: str = "gold",
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    detailed: list[dict[str, Any]] = []
    corpus_size = len(chunks)
    for test in diagnostics:
        condition = test["retrieval_filters"]["metadata_conditions"][0]
        matched = [
            chunk
            for chunk in chunks
            if _condition_matches(
                chunk.get(f"{metadata_source}_metadata") or {}, condition
            )
        ]
        matched_ids = {str(chunk["chunk_id"]) for chunk in matched}
        relevant_ids = {str(value) for value in test.get("relevant_chunk_ids", [])}
        forbidden_ids = {str(value) for value in test.get("forbidden_chunk_ids", [])}
        detailed.append(
            {
                "test_id": test["id"],
                "source_test_id": test["diagnostic_provenance"]["source_test_id"],
                "scenario_id": test.get("scenario_id", ""),
                "field": condition["field"],
                "value": json.dumps(condition.get("value"), ensure_ascii=False),
                "basis": test["diagnostic_provenance"]["basis"],
                "answerable": bool(test.get("answerable", True)),
                "candidate_count": len(matched),
                "candidate_reduction_pct": round((1 - len(matched) / corpus_size) * 100, 3),
                "relevant_count": len(relevant_ids),
                "relevant_retained": len(relevant_ids & matched_ids),
                "all_relevant_retained": relevant_ids <= matched_ids if relevant_ids else "",
                "forbidden_count": len(forbidden_ids),
                "forbidden_rejected": len(forbidden_ids - matched_ids),
            }
        )
    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in detailed:
        grouped[str(row["field"])].append(row)
    summary: list[dict[str, Any]] = []
    for field, rows in sorted(grouped.items()):
        counts = [float(row["candidate_count"]) for row in rows]
        answerable = [row for row in rows if row["answerable"]]
        relevant_total = sum(int(row["relevant_count"]) for row in answerable)
        relevant_retained = sum(int(row["relevant_retained"]) for row in answerable)
        basis_counts = Counter(str(row["basis"]) for row in rows)
        summary.append(
            {
                "field": field,
                "query_count": len(rows),
                "answerable_count": len(answerable),
                "null_count": len(rows) - len(answerable),
                "scenario_count": len({str(row["scenario_id"]) for row in rows}),
                "evidence_bases": json.dumps(dict(sorted(basis_counts.items()))),
                "mean_candidates": round(statistics.mean(counts), 3),
                "p50_candidates": round(statistics.median(counts), 3),
                "p95_candidates": round(_percentile(counts, 0.95), 3),
                "mean_candidate_reduction_pct": round(
                    statistics.mean(float(row["candidate_reduction_pct"]) for row in rows), 3
                ),
                "relevant_retention_rate": round(relevant_retained / relevant_total, 6)
                if relevant_total
                else "",
            }
        )
    return detailed, summary


def build_diagnostics(
    tests: list[dict[str, Any]], chunks: list[dict[str, Any]]
) -> list[dict[str, Any]]:
    chunks_by_id = {str(chunk["chunk_id"]): chunk for chunk in chunks}
    pair_maps = {
        source: _pair_mapping(chunks, source, target)
        for source, (target, _) in SUBSTITUTIONS.items()
    }
    diagnostics: list[dict[str, Any]] = []
    seen: set[tuple[str, str]] = set()

    def add(
        test: dict[str, Any],
        *,
        field: str,
        value: object,
        basis: str,
        source_field: str,
    ) -> None:
        key = (str(test["id"]), field)
        if key in seen or not _present(value):
            return
        diagnostics.append(
            _clone_diagnostic(
                test,
                field=field,
                value=value,
                basis=basis,
                source_field=source_field,
            )
        )
        seen.add(key)

    for test in tests:
        conditions = _metadata_conditions(test)
        for condition in conditions:
            field = str(condition.get("field") or "")
            add(
                test,
                field=field,
                value=condition.get("value"),
                basis="frozen_condition",
                source_field=field,
            )
            substitution = SUBSTITUTIONS.get(field)
            if substitution is None:
                continue
            target, basis = substitution
            mapping = pair_maps[field]
            source_value = _serialized(condition.get("value"))
            mapped = mapping.get(source_value, set())
            if target == "data_period":
                add(
                    test,
                    field=target,
                    value=str(condition.get("value")),
                    basis=basis,
                    source_field=field,
                )
            elif len(mapped) == 1:
                target_value = _consistent_relevant_value(test, target, chunks_by_id)
                if target_value is not None:
                    add(
                        test,
                        field=target,
                        value=target_value,
                        basis=basis,
                        source_field=field,
                    )

        required = {str(value) for value in test.get("required_metadata_fields", [])}
        query = _normalize(test.get("query", ""))
        for field in EXPLICIT_FIELDS:
            if field not in required:
                continue
            value = _consistent_relevant_value(test, field, chunks_by_id)
            if value is not None and _normalize(value) in query:
                add(
                    test,
                    field=field,
                    value=value,
                    basis="query_literal_value",
                    source_field=field,
                )
        if "content_kind" in required and any(token in query for token in ("bang", "table")):
            value = _consistent_relevant_value(test, "content_kind", chunks_by_id)
            if _normalize(value) == "table":
                add(
                    test,
                    field="content_kind",
                    value=value,
                    basis="deterministic_query_intent",
                    source_field="content_kind",
                )
    return diagnostics


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--testset", type=Path, default=DEFAULT_TESTSET)
    parser.add_argument("--corpus", type=Path, default=DEFAULT_CORPUS)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument(
        "--metadata-source",
        choices=("current", "gold"),
        default="gold",
        help="Metadata payload used for candidate-reduction and evidence-retention audits.",
    )
    args = parser.parse_args()

    tests = _load_jsonl(args.testset)
    chunks = _load_jsonl(args.corpus)
    diagnostics = build_diagnostics(tests, chunks)
    args.output_dir.mkdir(parents=True, exist_ok=True)

    profiles = _field_profiles(chunks, tests, diagnostics)
    redundancy = _redundancy_rows(chunks)
    candidate_details, candidate_summary = _candidate_rows(
        diagnostics,
        chunks,
        metadata_source=args.metadata_source,
    )
    review_rows = [
        {
            "review_status": "needs_human_review",
            "diagnostic_id": test["id"],
            "source_test_id": test["diagnostic_provenance"]["source_test_id"],
            "field": test["retrieval_filters"]["metadata_conditions"][0]["field"],
            "value": json.dumps(
                test["retrieval_filters"]["metadata_conditions"][0]["value"],
                ensure_ascii=False,
            ),
            "basis": test["diagnostic_provenance"]["basis"],
            "query": test["query"],
            "answerable": bool(test.get("answerable", True)),
            "relevant_chunk_ids": " | ".join(test.get("relevant_chunk_ids", [])),
        }
        for test in diagnostics
    ]

    _write_jsonl(args.output_dir / "diagnostic_testset.jsonl", diagnostics)
    _write_csv(args.output_dir / "metadata_field_profile.csv", profiles)
    _write_csv(args.output_dir / "metadata_field_redundancy.csv", redundancy)
    _write_csv(args.output_dir / "candidate_reduction_details.csv", candidate_details)
    _write_csv(args.output_dir / "candidate_reduction_summary.csv", candidate_summary)
    _write_csv(args.output_dir / "queries_for_review.csv", review_rows)

    field_counts = Counter(
        str(test["retrieval_filters"]["metadata_conditions"][0]["field"])
        for test in diagnostics
    )
    _write_json(
        args.output_dir / "diagnostic_manifest.json",
        {
            "schema_version": "1.0",
            "status": "generated_diagnostic_requires_human_review",
            "benchmark_kind": "derived_real_document_metadata_diagnostic",
            "frozen_gold_modified": False,
            "production_decision_ready": False,
            "source_testset": str(args.testset.resolve()),
            "source_testset_sha256": _sha256(args.testset),
            "source_corpus": str(args.corpus.resolve()),
            "source_corpus_sha256": _sha256(args.corpus),
            "candidate_metadata_source": args.metadata_source,
            "source_query_count": len(tests),
            "corpus_chunk_count": len(chunks),
            "diagnostic_query_count": len(diagnostics),
            "field_query_counts": dict(sorted(field_counts.items())),
            "condition_policy": [
                "existing frozen condition",
                "deterministic one-to-one substitution observed in gold",
                "literal field value in query",
                "deterministic table intent",
            ],
        },
    )
    print(
        f"Wrote {len(diagnostics)} diagnostic queries across {len(field_counts)} fields "
        f"to {args.output_dir}"
    )


if __name__ == "__main__":
    main()
