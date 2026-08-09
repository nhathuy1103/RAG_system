"""Deterministic benchmark for Vietnamese duplicate/version/conflict behavior.

This benchmark is deliberately local and reproducible. It measures the
deterministic relation analyzer and a small retrieval-policy proxy; it does not
claim to replace a production benchmark over real embeddings, Supabase, or
human-adjudicated customer documents.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from collections import Counter
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import cast
from uuid import NAMESPACE_URL, UUID, uuid5

from app.chat.application.services import (
    _resolve_allowed_document_ids,
    _resolve_legacy_document_ids,
)
from app.documents.domain.models import Document
from app.knowledge_quality.application.analysis import (
    analyze_text_relation,
    build_document_fingerprint,
    is_auto_identity_eligible,
)

DATASET_SCHEMA_VERSION = "knowledge-quality-vi-v1"
REPORT_SCHEMA_VERSION = "knowledge-quality-benchmark-report-v1"
RELATION_LABELS = ("exact", "near_duplicate", "version", "conflict", "distinct")

EVALUATION_DIR = Path(__file__).resolve().parent
DEFAULT_DATASET_PATH = EVALUATION_DIR / "data" / "knowledge_quality_vi_v1.jsonl"
DEFAULT_JSON_REPORT_PATH = EVALUATION_DIR / "reports" / "knowledge_quality_vi_v1_report.json"
DEFAULT_MARKDOWN_REPORT_PATH = EVALUATION_DIR / "reports" / "knowledge_quality_vi_v1_report.md"

_LABEL_BY_RELATION_VALUE = {
    "exact_content": "exact",
    "technical_duplicate": "exact",
    "near_duplicate": "near_duplicate",
    "version_candidate": "version",
    "version": "version",
    "conflict_candidate": "conflict",
    "conflict": "conflict",
    "related": "distinct",
    "distinct": "distinct",
    "template_variant": "distinct",
}


@dataclass(frozen=True, slots=True)
class DocumentSample:
    document_id: str
    owner_id: str
    notebook_id: str
    text: str
    effective_date: str | None
    authority: str

    @property
    def permission_scope(self) -> str:
        return f"{self.owner_id}/{self.notebook_id}"


@dataclass(frozen=True, slots=True)
class BenchmarkCase:
    schema_version: str
    id: str
    relation_label: str
    phenomena: tuple[str, ...]
    source: DocumentSample
    target: DocumentSample
    same_permission_scope: bool
    semantic_similarity: float | None
    eligible_for_comparison: bool
    expected_auto_reuse: bool
    review_state: str
    retrieval_evaluation: bool
    expected_on_document_ids: tuple[str, ...]
    notes: str


def load_dataset(path: Path = DEFAULT_DATASET_PATH) -> tuple[BenchmarkCase, ...]:
    """Load and strictly validate the versioned JSONL dataset."""
    cases: list[BenchmarkCase] = []
    seen_ids: set[str] = set()
    for line_number, raw_line in enumerate(
        path.read_text(encoding="utf-8").splitlines(),
        start=1,
    ):
        if not raw_line.strip():
            continue
        try:
            payload = json.loads(raw_line)
        except json.JSONDecodeError as exc:
            raise ValueError(f"{path}:{line_number}: invalid JSON") from exc
        case = _parse_case(payload, path=path, line_number=line_number)
        if case.id in seen_ids:
            raise ValueError(f"{path}:{line_number}: duplicate case id {case.id!r}")
        seen_ids.add(case.id)
        cases.append(case)

    if not cases:
        raise ValueError(f"{path}: dataset must not be empty")
    missing_labels = set(RELATION_LABELS) - {case.relation_label for case in cases}
    if missing_labels:
        raise ValueError(f"{path}: missing relation labels {sorted(missing_labels)}")
    return tuple(cases)


def predict_relation_label(case: BenchmarkCase) -> str | None:
    """Predict only within one permission scope; cross-scope pairs are excluded."""
    if not case.eligible_for_comparison:
        return None
    analysis = analyze_text_relation(
        case.source.text,
        case.target.text,
        semantic_similarity=case.semantic_similarity,
    )
    try:
        return _LABEL_BY_RELATION_VALUE[analysis.relation_type.value]
    except KeyError as exc:
        raise ValueError(
            f"Unsupported detector relation type {analysis.relation_type.value!r}"
        ) from exc


def run_benchmark(
    dataset_path: Path = DEFAULT_DATASET_PATH,
) -> dict[str, object]:
    """Run classification, safety, and retrieval-policy proxy evaluations."""
    cases = load_dataset(dataset_path)
    predictions = {
        case.id: prediction
        for case in cases
        if (prediction := predict_relation_label(case)) is not None
    }
    classification = _classification_metrics(cases, predictions)
    safety = _safety_metrics(cases, predictions)
    retrieval_proxy = _retrieval_proxy_metrics(cases, predictions)
    gates = _quality_gates(classification, safety, retrieval_proxy)

    total_by_label = Counter(case.relation_label for case in cases)
    eligible_by_label = Counter(
        case.relation_label for case in cases if case.eligible_for_comparison
    )
    phenomena = sorted({phenomenon for case in cases for phenomenon in case.phenomena})
    return {
        "report_schema_version": REPORT_SCHEMA_VERSION,
        "dataset_schema_version": DATASET_SCHEMA_VERSION,
        "dataset_sha256": hashlib.sha256(dataset_path.read_bytes()).hexdigest(),
        "dataset": {
            "case_count": len(cases),
            "eligible_relation_case_count": len(predictions),
            "cross_scope_case_count": sum(not case.same_permission_scope for case in cases),
            "retrieval_proxy_case_count": sum(case.retrieval_evaluation for case in cases),
            "case_count_by_label": {label: total_by_label[label] for label in RELATION_LABELS},
            "eligible_count_by_label": {
                label: eligible_by_label[label] for label in RELATION_LABELS
            },
            "phenomena": phenomena,
        },
        "classification": classification,
        "safety": safety,
        "retrieval_proxy": retrieval_proxy,
        "gates": gates,
    }


def render_json_report(report: dict[str, object]) -> str:
    return json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + "\n"


def render_markdown_report(report: dict[str, object]) -> str:
    dataset = cast(dict[str, object], report["dataset"])
    classification = cast(dict[str, object], report["classification"])
    safety = cast(dict[str, object], report["safety"])
    retrieval = cast(dict[str, object], report["retrieval_proxy"])
    gates = cast(dict[str, object], report["gates"])
    per_class = cast(dict[str, dict[str, object]], classification["per_class"])
    modes = cast(dict[str, dict[str, object]], retrieval["modes"])
    gate_results = cast(dict[str, dict[str, object]], gates["results"])
    errors = cast(list[dict[str, object]], classification["errors"])

    lines = [
        "# Vietnamese Knowledge-Quality Benchmark v1",
        "",
        "Deterministic report generated from "
        "`tests/evaluation/data/knowledge_quality_vi_v1.jsonl`.",
        "This is a labeled regression and policy-proxy benchmark, not a claim "
        "about production embedding quality.",
        "",
        "## Dataset",
        "",
        f"- Cases: {dataset['case_count']}",
        f"- Eligible same-scope relation cases: {dataset['eligible_relation_case_count']}",
        f"- Explicit cross-scope safety cases: {dataset['cross_scope_case_count']}",
        f"- Dataset SHA-256: `{report['dataset_sha256']}`",
        "",
        "## Relation classification",
        "",
        f"- Accuracy: {_fmt(classification['accuracy'])}",
        f"- Macro F1: {_fmt(classification['macro_f1'])}",
        "",
        "| Class | Precision | Recall | F1 | Support |",
        "|---|---:|---:|---:|---:|",
    ]
    for label in RELATION_LABELS:
        metrics = per_class[label]
        lines.append(
            f"| {label} | {_fmt(metrics['precision'])} | "
            f"{_fmt(metrics['recall'])} | {_fmt(metrics['f1'])} | "
            f"{metrics['support']} |"
        )

    lines.extend(
        [
            "",
            "## Safety",
            "",
            "| Metric | Value |",
            "|---|---:|",
            f"| Exact auto-reuse false-positive rate | "
            f"{_fmt(safety['exact_auto_reuse_false_positive_rate'])} |",
            f"| Exact auto-reuse false-discovery rate | "
            f"{_fmt(safety['exact_auto_reuse_false_discovery_rate'])} |",
            f"| Exact auto-reuse recall | {_fmt(safety['exact_auto_reuse_recall'])} |",
            f"| Cross-scope suppression rate | {_fmt(safety['cross_scope_suppression_rate'])} |",
            "",
            "## Off vs shadow vs on retrieval-quality proxy",
            "",
            "`off` and `shadow` retain both documents. `on` applies safe exact "
            "reuse and confirmed version preference while preserving both sides "
            "of conflicts and unresolved fuzzy matches.",
            "",
            "| Mode | Quality proxy | Selection exact match | Duplicate redundancy "
            "| Stale version exposure | Conflict both sides |",
            "|---|---:|---:|---:|---:|---:|",
        ]
    )
    for mode_name in ("off", "shadow", "on"):
        metrics = modes[mode_name]
        lines.append(
            f"| {mode_name} | {_fmt(metrics['retrieval_quality_proxy'])} | "
            f"{_fmt(metrics['selection_exact_match_rate'])} | "
            f"{_fmt(metrics['duplicate_redundancy_rate'])} | "
            f"{_fmt(metrics['stale_version_exposure_rate'])} | "
            f"{_fmt(metrics['conflict_both_sides_rate'])} |"
        )

    lines.extend(
        [
            "",
            "## Gates",
            "",
            f"Overall: **{'PASS' if gates['all_passed'] else 'FAIL'}**",
            "",
            "| Gate | Measured | Requirement | Result |",
            "|---|---:|---|:---:|",
        ]
    )
    for gate_name, result in gate_results.items():
        lines.append(
            f"| {gate_name} | {_fmt(result['measured'])} | "
            f"`{result['comparator']} {result['threshold']}` | "
            f"{'PASS' if result['passed'] else 'FAIL'} |"
        )

    lines.extend(["", "## Misclassified eligible cases", ""])
    if errors:
        lines.extend(
            [
                "| Case | Expected | Predicted | Phenomena |",
                "|---|---|---|---|",
            ]
        )
        for error in errors:
            phenomena_text = ", ".join(cast(list[str], error["phenomena"]))
            lines.append(
                f"| {error['id']} | {error['expected']} | {error['predicted']} | {phenomena_text} |"
            )
    else:
        lines.append("None.")
    return "\n".join(lines) + "\n"


def write_reports(
    report: dict[str, object],
    *,
    json_path: Path = DEFAULT_JSON_REPORT_PATH,
    markdown_path: Path = DEFAULT_MARKDOWN_REPORT_PATH,
) -> None:
    json_path.parent.mkdir(parents=True, exist_ok=True)
    markdown_path.parent.mkdir(parents=True, exist_ok=True)
    json_path.write_text(render_json_report(report), encoding="utf-8")
    markdown_path.write_text(render_markdown_report(report), encoding="utf-8")


def _classification_metrics(
    cases: tuple[BenchmarkCase, ...],
    predictions: dict[str, str],
) -> dict[str, object]:
    eligible = tuple(case for case in cases if case.eligible_for_comparison)
    confusion = {
        expected: {predicted: 0 for predicted in RELATION_LABELS} for expected in RELATION_LABELS
    }
    errors: list[dict[str, object]] = []
    for case in eligible:
        predicted = predictions[case.id]
        confusion[case.relation_label][predicted] += 1
        if predicted != case.relation_label:
            errors.append(
                {
                    "id": case.id,
                    "expected": case.relation_label,
                    "predicted": predicted,
                    "phenomena": list(case.phenomena),
                }
            )

    per_class: dict[str, dict[str, object]] = {}
    for label in RELATION_LABELS:
        true_positive = confusion[label][label]
        false_positive = sum(confusion[other][label] for other in RELATION_LABELS if other != label)
        false_negative = sum(confusion[label][other] for other in RELATION_LABELS if other != label)
        precision = _ratio(true_positive, true_positive + false_positive)
        recall = _ratio(true_positive, true_positive + false_negative)
        per_class[label] = {
            "precision": _rounded(precision),
            "recall": _rounded(recall),
            "f1": _rounded(_f1(precision, recall)),
            "support": sum(confusion[label].values()),
            "predicted_count": sum(confusion[row][label] for row in RELATION_LABELS),
            "true_positive": true_positive,
        }

    correct = sum(confusion[label][label] for label in RELATION_LABELS)
    return {
        "accuracy": _rounded(_ratio(correct, len(eligible))),
        "macro_f1": _rounded(
            sum(_float_metric(per_class[label]["f1"]) for label in RELATION_LABELS)
            / len(RELATION_LABELS)
        ),
        "per_class": per_class,
        "confusion_matrix": confusion,
        "errors": errors,
    }


def _safety_metrics(
    cases: tuple[BenchmarkCase, ...],
    predictions: dict[str, str],
) -> dict[str, object]:
    true_positive = false_positive = true_negative = false_negative = 0
    suppressed_cross_scope = 0
    cross_scope_count = 0

    for case in cases:
        fingerprint_eligible = is_auto_identity_eligible(
            build_document_fingerprint(case.source.text)
        )
        predicted_auto_reuse = (
            case.eligible_for_comparison
            and predictions.get(case.id) == "exact"
            and fingerprint_eligible
        )
        if predicted_auto_reuse and case.expected_auto_reuse:
            true_positive += 1
        elif predicted_auto_reuse:
            false_positive += 1
        elif case.expected_auto_reuse:
            false_negative += 1
        else:
            true_negative += 1

        if not case.same_permission_scope:
            cross_scope_count += 1
            if not predicted_auto_reuse and case.id not in predictions:
                suppressed_cross_scope += 1

    return {
        "exact_auto_reuse_true_positive": true_positive,
        "exact_auto_reuse_false_positive": false_positive,
        "exact_auto_reuse_true_negative": true_negative,
        "exact_auto_reuse_false_negative": false_negative,
        "exact_auto_reuse_false_positive_rate": _rounded(
            _ratio(false_positive, false_positive + true_negative)
        ),
        "exact_auto_reuse_false_discovery_rate": _rounded(
            _ratio(false_positive, true_positive + false_positive)
        ),
        "exact_auto_reuse_recall": _rounded(_ratio(true_positive, true_positive + false_negative)),
        "cross_scope_case_count": cross_scope_count,
        "cross_scope_suppression_rate": _rounded(_ratio(suppressed_cross_scope, cross_scope_count)),
    }


def _retrieval_proxy_metrics(
    cases: tuple[BenchmarkCase, ...],
    predictions: dict[str, str],
) -> dict[str, object]:
    retrieval_cases = tuple(case for case in cases if case.retrieval_evaluation)
    modes = {
        mode: _evaluate_retrieval_mode(retrieval_cases, predictions, mode)
        for mode in ("off", "shadow", "on")
    }
    return {
        "description": (
            "Policy proxy over labeled document pairs; no embedding or live database is used."
        ),
        "modes": modes,
    }


def _evaluate_retrieval_mode(
    cases: tuple[BenchmarkCase, ...],
    predictions: dict[str, str],
    mode: str,
) -> dict[str, object]:
    quality_scores: list[float] = []
    exact_selection_matches = 0
    exact_cases = version_cases = conflict_cases = distinct_cases = near_cases = 0
    redundant_exact = stale_versions = current_versions = 0
    conflict_both_sides = distinct_both = near_both = 0

    for case in cases:
        selected = _selected_document_ids(case, predictions[case.id], mode)
        expected = set(case.expected_on_document_ids)
        precision = _ratio(len(selected & expected), len(selected))
        recall = _ratio(len(selected & expected), len(expected))
        quality_scores.append(_f1(precision, recall))
        exact_selection_matches += selected == expected

        if case.relation_label == "exact":
            exact_cases += 1
            redundant_exact += len(selected) > 1
        elif case.relation_label == "version":
            version_cases += 1
            current_versions += case.source.document_id in selected
            stale_versions += case.target.document_id in selected
        elif case.relation_label == "conflict":
            conflict_cases += 1
            conflict_both_sides += {
                case.source.document_id,
                case.target.document_id,
            }.issubset(selected)
        elif case.relation_label == "distinct":
            distinct_cases += 1
            distinct_both += {
                case.source.document_id,
                case.target.document_id,
            }.issubset(selected)
        elif case.relation_label == "near_duplicate":
            near_cases += 1
            near_both += {
                case.source.document_id,
                case.target.document_id,
            }.issubset(selected)

    return {
        "retrieval_quality_proxy": _rounded(sum(quality_scores) / len(quality_scores)),
        "selection_exact_match_rate": _rounded(_ratio(exact_selection_matches, len(cases))),
        "duplicate_redundancy_rate": _rounded(_ratio(redundant_exact, exact_cases)),
        "current_version_hit_rate": _rounded(_ratio(current_versions, version_cases)),
        "stale_version_exposure_rate": _rounded(_ratio(stale_versions, version_cases)),
        "conflict_both_sides_rate": _rounded(_ratio(conflict_both_sides, conflict_cases)),
        "distinct_preservation_rate": _rounded(_ratio(distinct_both, distinct_cases)),
        "near_duplicate_preservation_rate": _rounded(_ratio(near_both, near_cases)),
    }


def _selected_document_ids(
    case: BenchmarkCase,
    predicted_label: str,
    mode: str,
) -> set[str]:
    documents, original_ids = _policy_documents(case, predicted_label)
    if mode == "on":
        selected_ids = _resolve_allowed_document_ids(documents, None)
    elif mode in {"off", "shadow"}:
        selected_ids = _resolve_legacy_document_ids(documents, None)
    else:
        raise ValueError(f"Unsupported benchmark mode {mode!r}")
    return {original_ids[document_id] for document_id in selected_ids}


def _policy_documents(
    case: BenchmarkCase,
    predicted_label: str,
) -> tuple[tuple[Document, Document], dict[UUID, str]]:
    """Materialize detector output and run the production document policy."""
    source_id = uuid5(NAMESPACE_URL, f"quality-benchmark:{case.source.document_id}")
    target_id = uuid5(NAMESPACE_URL, f"quality-benchmark:{case.target.document_id}")
    owner_id = uuid5(NAMESPACE_URL, f"quality-benchmark:{case.source.owner_id}")
    notebook_id = uuid5(
        NAMESPACE_URL,
        f"quality-benchmark:{case.source.owner_id}:{case.source.notebook_id}",
    )
    exact_alias = predicted_label == "exact" and is_auto_identity_eligible(
        build_document_fingerprint(case.source.text)
    )
    confirmed_version = predicted_label == "version" and case.review_state == "confirmed"
    created_at = datetime(2025, 1, 1, tzinfo=UTC)

    def document(
        sample: DocumentSample,
        document_id: UUID,
        *,
        canonical_document_id: UUID | None = None,
        is_current: bool = True,
    ) -> Document:
        return Document(
            id=document_id,
            owner_id=owner_id,
            notebook_id=notebook_id,
            original_filename=f"{sample.document_id}.txt",
            storage_bucket="benchmark",
            storage_object_path=f"benchmark/{sample.document_id}.txt",
            mime_type="text/plain",
            size_bytes=len(sample.text.encode("utf-8")),
            content_hash=None,
            status="ready",
            error_message=None,
            is_active=True,
            created_at=created_at,
            updated_at=created_at,
            canonical_document_id=canonical_document_id,
            is_current=is_current,
        )

    source = document(
        case.source,
        source_id,
        canonical_document_id=target_id if exact_alias else None,
        is_current=not exact_alias,
    )
    target = document(
        case.target,
        target_id,
        is_current=not confirmed_version,
    )
    return (
        (source, target),
        {
            source_id: case.source.document_id,
            target_id: case.target.document_id,
        },
    )


def _quality_gates(
    classification: dict[str, object],
    safety: dict[str, object],
    retrieval_proxy: dict[str, object],
) -> dict[str, object]:
    per_class = cast(dict[str, dict[str, object]], classification["per_class"])
    modes = cast(dict[str, dict[str, object]], retrieval_proxy["modes"])
    off = modes["off"]
    shadow = modes["shadow"]
    on = modes["on"]

    minimum_class_f1 = min(_float_metric(per_class[label]["f1"]) for label in RELATION_LABELS)
    results = {
        "minimum_per_class_f1": _gate(minimum_class_f1, ">=", 0.85),
        "macro_f1": _gate(_float_metric(classification["macro_f1"]), ">=", 0.90),
        "conflict_recall": _gate(
            _float_metric(per_class["conflict"]["recall"]),
            ">=",
            1.0,
        ),
        "exact_auto_reuse_false_positive_rate": _gate(
            _float_metric(safety["exact_auto_reuse_false_positive_rate"]),
            "<=",
            0.0,
        ),
        "exact_auto_reuse_recall": _gate(
            _float_metric(safety["exact_auto_reuse_recall"]),
            ">=",
            1.0,
        ),
        "cross_scope_suppression_rate": _gate(
            _float_metric(safety["cross_scope_suppression_rate"]),
            ">=",
            1.0,
        ),
        "shadow_behavior_matches_off": _gate(
            1.0 if shadow == off else 0.0,
            ">=",
            1.0,
        ),
        "on_retrieval_quality_proxy": _gate(
            _float_metric(on["retrieval_quality_proxy"]),
            ">=",
            0.95,
        ),
        "on_quality_improvement_over_off": _gate(
            _float_metric(on["retrieval_quality_proxy"])
            - _float_metric(off["retrieval_quality_proxy"]),
            ">=",
            0.10,
        ),
        "on_duplicate_redundancy_rate": _gate(
            _float_metric(on["duplicate_redundancy_rate"]),
            "<=",
            0.0,
        ),
        "on_stale_version_exposure_rate": _gate(
            _float_metric(on["stale_version_exposure_rate"]),
            "<=",
            0.0,
        ),
        "on_current_version_hit_rate": _gate(
            _float_metric(on["current_version_hit_rate"]),
            ">=",
            1.0,
        ),
        "on_conflict_both_sides_rate": _gate(
            _float_metric(on["conflict_both_sides_rate"]),
            ">=",
            1.0,
        ),
        "on_distinct_preservation_rate": _gate(
            _float_metric(on["distinct_preservation_rate"]),
            ">=",
            1.0,
        ),
    }
    return {
        "all_passed": all(bool(result["passed"]) for result in results.values()),
        "results": results,
    }


def _gate(measured: float, comparator: str, threshold: float) -> dict[str, object]:
    if comparator == ">=":
        passed = measured >= threshold
    elif comparator == "<=":
        passed = measured <= threshold
    else:
        raise ValueError(f"Unsupported comparator {comparator!r}")
    return {
        "measured": _rounded(measured),
        "comparator": comparator,
        "threshold": threshold,
        "passed": passed,
    }


def _parse_case(payload: object, *, path: Path, line_number: int) -> BenchmarkCase:
    row = _require_mapping(payload, path=path, line_number=line_number)
    schema_version = _required_string(row, "schema_version", path, line_number)
    if schema_version != DATASET_SCHEMA_VERSION:
        raise ValueError(f"{path}:{line_number}: unsupported schema_version {schema_version!r}")

    case_id = _required_string(row, "id", path, line_number)
    relation_label = _required_string(row, "relation_label", path, line_number)
    if relation_label not in RELATION_LABELS:
        raise ValueError(f"{path}:{line_number}: unsupported relation_label {relation_label!r}")

    source = _parse_document(row.get("source"), path, line_number, "source")
    target = _parse_document(row.get("target"), path, line_number, "target")
    if source.document_id == target.document_id:
        raise ValueError(f"{path}:{line_number}: document ids must differ")

    phenomena_value = row.get("phenomena")
    if not isinstance(phenomena_value, list) or not phenomena_value:
        raise ValueError(f"{path}:{line_number}: phenomena must be a non-empty list")
    if not all(isinstance(item, str) and item.strip() for item in phenomena_value):
        raise ValueError(f"{path}:{line_number}: phenomena entries must be strings")

    permission = _require_mapping(
        row.get("permission_scope"),
        path=path,
        line_number=line_number,
        field="permission_scope",
    )
    same_scope = _required_bool(
        permission,
        "same_scope",
        path,
        line_number,
    )
    if _required_string(permission, "source", path, line_number) != (source.permission_scope):
        raise ValueError(f"{path}:{line_number}: source permission scope mismatch")
    if _required_string(permission, "target", path, line_number) != (target.permission_scope):
        raise ValueError(f"{path}:{line_number}: target permission scope mismatch")
    derived_same_scope = source.permission_scope == target.permission_scope
    if same_scope != derived_same_scope:
        raise ValueError(f"{path}:{line_number}: same_scope is inconsistent")

    eligible = _required_bool(
        row,
        "eligible_for_comparison",
        path,
        line_number,
    )
    if eligible != same_scope:
        raise ValueError(
            f"{path}:{line_number}: comparison eligibility must match permission scope"
        )

    semantic_value = row.get("semantic_similarity")
    if semantic_value is not None and (
        isinstance(semantic_value, bool)
        or not isinstance(semantic_value, int | float)
        or not 0.0 <= float(semantic_value) <= 1.0
    ):
        raise ValueError(f"{path}:{line_number}: semantic_similarity must be null or [0, 1]")

    expected_auto_reuse = _required_bool(
        row,
        "expected_auto_reuse",
        path,
        line_number,
    )
    if expected_auto_reuse and (relation_label != "exact" or not same_scope):
        raise ValueError(
            f"{path}:{line_number}: auto reuse is only valid for same-scope exact cases"
        )

    retrieval_evaluation = _required_bool(
        row,
        "retrieval_evaluation",
        path,
        line_number,
    )
    if retrieval_evaluation and not same_scope:
        raise ValueError(f"{path}:{line_number}: cross-scope cases cannot enter retrieval proxy")
    expected_ids_value = row.get("expected_on_document_ids")
    if not isinstance(expected_ids_value, list) or not all(
        isinstance(item, str) and item for item in expected_ids_value
    ):
        raise ValueError(f"{path}:{line_number}: expected_on_document_ids must be a string list")
    expected_ids = tuple(cast(list[str], expected_ids_value))
    if retrieval_evaluation and not expected_ids:
        raise ValueError(f"{path}:{line_number}: retrieval cases need expected on-mode documents")
    valid_ids = {source.document_id, target.document_id}
    if not set(expected_ids).issubset(valid_ids):
        raise ValueError(f"{path}:{line_number}: expected retrieval ids must belong to the pair")

    return BenchmarkCase(
        schema_version=schema_version,
        id=case_id,
        relation_label=relation_label,
        phenomena=tuple(cast(list[str], phenomena_value)),
        source=source,
        target=target,
        same_permission_scope=same_scope,
        semantic_similarity=(float(semantic_value) if semantic_value is not None else None),
        eligible_for_comparison=eligible,
        expected_auto_reuse=expected_auto_reuse,
        review_state=_required_string(row, "review_state", path, line_number),
        retrieval_evaluation=retrieval_evaluation,
        expected_on_document_ids=expected_ids,
        notes=_required_string(row, "notes", path, line_number),
    )


def _parse_document(
    payload: object,
    path: Path,
    line_number: int,
    field: str,
) -> DocumentSample:
    row = _require_mapping(
        payload,
        path=path,
        line_number=line_number,
        field=field,
    )
    effective_date = row.get("effective_date")
    if effective_date is not None and not isinstance(effective_date, str):
        raise ValueError(f"{path}:{line_number}: {field}.effective_date must be null or string")
    return DocumentSample(
        document_id=_required_string(row, "document_id", path, line_number),
        owner_id=_required_string(row, "owner_id", path, line_number),
        notebook_id=_required_string(row, "notebook_id", path, line_number),
        text=_required_string(row, "text", path, line_number),
        effective_date=effective_date,
        authority=_required_string(row, "authority", path, line_number),
    )


def _require_mapping(
    payload: object,
    *,
    path: Path,
    line_number: int,
    field: str = "row",
) -> dict[str, object]:
    if not isinstance(payload, dict):
        raise ValueError(f"{path}:{line_number}: {field} must be an object")
    if not all(isinstance(key, str) for key in payload):
        raise ValueError(f"{path}:{line_number}: {field} keys must be strings")
    return cast(dict[str, object], payload)


def _required_string(
    row: dict[str, object],
    field: str,
    path: Path,
    line_number: int,
) -> str:
    value = row.get(field)
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{path}:{line_number}: {field} must be a non-empty string")
    return value


def _required_bool(
    row: dict[str, object],
    field: str,
    path: Path,
    line_number: int,
) -> bool:
    value = row.get(field)
    if not isinstance(value, bool):
        raise ValueError(f"{path}:{line_number}: {field} must be boolean")
    return value


def _float_metric(value: object) -> float:
    if isinstance(value, bool) or not isinstance(value, int | float):
        raise TypeError(f"Expected numeric benchmark metric, got {value!r}")
    return float(value)


def _ratio(numerator: int, denominator: int) -> float:
    return numerator / denominator if denominator else 0.0


def _f1(precision: float, recall: float) -> float:
    return 2.0 * precision * recall / (precision + recall) if precision + recall else 0.0


def _rounded(value: float) -> float:
    return round(value, 6)


def _fmt(value: object) -> str:
    if isinstance(value, bool):
        return "1.000" if value else "0.000"
    if isinstance(value, int | float):
        return f"{float(value):.3f}"
    return str(value)


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Run the deterministic Vietnamese knowledge-quality benchmark."
    )
    parser.add_argument("--dataset", type=Path, default=DEFAULT_DATASET_PATH)
    parser.add_argument("--json-output", type=Path, default=DEFAULT_JSON_REPORT_PATH)
    parser.add_argument(
        "--markdown-output",
        type=Path,
        default=DEFAULT_MARKDOWN_REPORT_PATH,
    )
    args = parser.parse_args()
    report = run_benchmark(args.dataset)
    write_reports(
        report,
        json_path=args.json_output,
        markdown_path=args.markdown_output,
    )
    gates = cast(dict[str, object], report["gates"])
    print(render_markdown_report(report))
    return 0 if bool(gates["all_passed"]) else 1


if __name__ == "__main__":
    raise SystemExit(main())


__all__ = [
    "BenchmarkCase",
    "DATASET_SCHEMA_VERSION",
    "DEFAULT_DATASET_PATH",
    "DEFAULT_JSON_REPORT_PATH",
    "DEFAULT_MARKDOWN_REPORT_PATH",
    "RELATION_LABELS",
    "load_dataset",
    "predict_relation_label",
    "render_json_report",
    "render_markdown_report",
    "run_benchmark",
    "write_reports",
]
