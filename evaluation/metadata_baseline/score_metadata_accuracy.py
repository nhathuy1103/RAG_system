"""Score adjudicated metadata annotations and inter-annotator agreement."""

from __future__ import annotations

import argparse
import csv
import json
import logging
import math
import sys
from collections import Counter, defaultdict
from collections.abc import Mapping, Sequence
from pathlib import Path

if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from evaluation.metadata_baseline.common import (  # noqa: E402
    MetadataBaselineError,
    SchemaField,
    ensure_outputs,
    generation_family,
    load_schema,
    normalized_surface,
    write_csv,
    write_json,
    write_text,
)

LOGGER = logging.getLogger("metadata_baseline.accuracy")

ACCURACY_COLUMNS = (
    "group_type",
    "group_value",
    "field_name",
    "expected_data_type",
    "generation_method",
    "generation_family",
    "labeled_count",
    "correct_count",
    "accuracy",
    "precision",
    "recall",
    "f1",
    "micro_precision",
    "micro_recall",
    "micro_f1",
    "macro_f1",
    "exact_set_accuracy",
    "jaccard_similarity",
    "missing_error_count",
    "incorrect_error_count",
    "ambiguous_error_count",
    "inconsistent_error_count",
    "outdated_error_count",
    "wrong_version_error_count",
    "wrong_scope_error_count",
    "other_error_count",
)

AGREEMENT_COLUMNS = (
    "field_name",
    "expected_data_type",
    "double_annotated_count",
    "agreement_basis",
    "raw_agreement",
    "cohen_kappa",
    "weighted_kappa",
    "multilabel_jaccard_agreement",
)


def load_annotation_rows(path: Path) -> list[dict[str, str]]:
    try:
        handle = path.open("r", encoding="utf-8-sig", newline="")
    except OSError as exc:
        raise MetadataBaselineError(f"Cannot read annotation CSV: {path}") from exc
    with handle:
        rows = [dict(row) for row in csv.DictReader(handle)]
    if not rows:
        raise MetadataBaselineError(f"Annotation CSV has no rows: {path}")
    return rows


def score_annotations(
    rows: Sequence[Mapping[str, str]],
    schema: Sequence[SchemaField],
) -> tuple[list[dict[str, object]], dict[str, object], list[dict[str, object]], str]:
    """Compute field/segment accuracy, confusion matrices and agreement."""

    schema_by_name = {field.field_name: field for field in schema}
    labeled = [row for row in rows if _final_correctness(row) is not None]
    grouped: dict[tuple[str, str, str], list[Mapping[str, str]]] = defaultdict(list)
    for row in labeled:
        field_name = str(row.get("field_name") or "")
        grouped[("field", "all", field_name)].append(row)
        for group_type, group_value in _segment_values(row, schema_by_name.get(field_name)):
            grouped[(group_type, group_value, field_name)].append(row)
            grouped[(group_type, group_value, "__all__")].append(row)

    accuracy_rows: list[dict[str, object]] = []
    confusion: dict[str, object] = {}
    for (group_type, group_value, field_name), group_rows in sorted(grouped.items()):
        field = schema_by_name.get(field_name)
        expected_type = field.expected_data_type if field else "mixed"
        is_multilabel = expected_type.casefold().startswith("array")
        if field_name == "__all__":
            result = _score_correctness_only(group_rows)
        else:
            result = (
                _score_multilabel(group_rows) if is_multilabel else _score_single_label(group_rows)
            )
        errors = Counter(
            str(row.get("error_type") or "").strip().casefold()
            for row in group_rows
            if str(row.get("error_type") or "").strip()
        )
        accuracy_rows.append(
            {
                "group_type": group_type,
                "group_value": group_value,
                "field_name": field_name,
                "expected_data_type": expected_type,
                "generation_method": field.generation_method if field else "unknown",
                "generation_family": (
                    generation_family(field)
                    if field
                    else group_value
                    if group_type == "generation_family"
                    else "mixed"
                ),
                **result,
                **{
                    f"{error_type}_error_count": errors[error_type]
                    for error_type in (
                        "missing",
                        "incorrect",
                        "ambiguous",
                        "inconsistent",
                        "outdated",
                        "wrong_version",
                        "wrong_scope",
                        "other",
                    )
                },
            }
        )
        if group_type == "field" and field is not None:
            confusion[field_name] = _confusion_matrix(group_rows, multilabel=is_multilabel)

    agreement_rows = score_inter_annotator_agreement(rows, schema_by_name)
    report = _render_accuracy_report(
        accuracy_rows,
        agreement_rows,
        len(rows),
        len(labeled),
        schema,
    )
    return accuracy_rows, confusion, agreement_rows, report


def _score_single_label(rows: Sequence[Mapping[str, str]]) -> dict[str, object]:
    labels = [_final_correctness(row) for row in rows]
    valid_labels = [label for label in labels if label is not None]
    correct_count = sum(label == 1 for label in valid_labels)
    pairs = [
        (_normalized_label(row.get("current_value")), _normalized_label(_final_gold_value(row)))
        for row in rows
        if _final_gold_value(row).strip()
    ]
    precision, recall, f1 = _macro_classification_metrics(pairs)
    return {
        "labeled_count": len(valid_labels),
        "correct_count": correct_count,
        "accuracy": _ratio(correct_count, len(valid_labels)),
        "precision": precision,
        "recall": recall,
        "f1": f1,
        "micro_precision": "",
        "micro_recall": "",
        "micro_f1": "",
        "macro_f1": f1,
        "exact_set_accuracy": "",
        "jaccard_similarity": "",
    }


def _score_correctness_only(rows: Sequence[Mapping[str, str]]) -> dict[str, object]:
    labels = [_final_correctness(row) for row in rows]
    valid = [label for label in labels if label is not None]
    correct_count = sum(label == 1 for label in valid)
    return {
        "labeled_count": len(valid),
        "correct_count": correct_count,
        "accuracy": _ratio(correct_count, len(valid)),
        "precision": "",
        "recall": "",
        "f1": "",
        "micro_precision": "",
        "micro_recall": "",
        "micro_f1": "",
        "macro_f1": "",
        "exact_set_accuracy": "",
        "jaccard_similarity": "",
    }


def _score_multilabel(rows: Sequence[Mapping[str, str]]) -> dict[str, object]:
    tp = fp = fn = 0
    exact = 0
    jaccards: list[float] = []
    label_stats: dict[str, Counter[str]] = defaultdict(Counter)
    correct_labels = [_final_correctness(row) for row in rows]
    valid_correctness = [label for label in correct_labels if label is not None]
    for row in rows:
        gold_raw = _final_gold_value(row)
        if not gold_raw.strip():
            continue
        current = _parse_multilabel(str(row.get("current_value") or ""))
        gold = _parse_multilabel(gold_raw)
        intersection = current & gold
        tp += len(intersection)
        fp += len(current - gold)
        fn += len(gold - current)
        exact += current == gold
        union = current | gold
        jaccards.append(len(intersection) / len(union) if union else 1.0)
        for label in union:
            if label in current and label in gold:
                label_stats[label]["tp"] += 1
            elif label in current:
                label_stats[label]["fp"] += 1
            else:
                label_stats[label]["fn"] += 1
    micro_precision = _ratio(tp, tp + fp)
    micro_recall = _ratio(tp, tp + fn)
    micro_f1 = _harmonic(micro_precision, micro_recall)
    per_label_f1 = [
        _harmonic(
            _ratio(stats["tp"], stats["tp"] + stats["fp"]),
            _ratio(stats["tp"], stats["tp"] + stats["fn"]),
        )
        for stats in label_stats.values()
    ]
    macro_f1 = (
        round(sum(value for value in per_label_f1 if value is not None) / len(per_label_f1), 6)
        if per_label_f1
        else None
    )
    correct_count = sum(label == 1 for label in valid_correctness)
    return {
        "labeled_count": len(valid_correctness),
        "correct_count": correct_count,
        "accuracy": _ratio(correct_count, len(valid_correctness)),
        "precision": "",
        "recall": "",
        "f1": "",
        "micro_precision": micro_precision,
        "micro_recall": micro_recall,
        "micro_f1": micro_f1,
        "macro_f1": macro_f1,
        "exact_set_accuracy": _ratio(exact, len(jaccards)),
        "jaccard_similarity": (round(sum(jaccards) / len(jaccards), 6) if jaccards else None),
    }


def _macro_classification_metrics(
    pairs: Sequence[tuple[str, str]],
) -> tuple[object, object, object]:
    if not pairs:
        return "", "", ""
    labels = sorted({item for pair in pairs for item in pair})
    precisions: list[float] = []
    recalls: list[float] = []
    f1s: list[float] = []
    for label in labels:
        tp = sum(current == label and gold == label for current, gold in pairs)
        fp = sum(current == label and gold != label for current, gold in pairs)
        fn = sum(current != label and gold == label for current, gold in pairs)
        precision = tp / (tp + fp) if tp + fp else 0.0
        recall = tp / (tp + fn) if tp + fn else 0.0
        score = 2 * precision * recall / (precision + recall) if precision + recall else 0.0
        precisions.append(precision)
        recalls.append(recall)
        f1s.append(score)
    return (
        round(sum(precisions) / len(precisions), 6),
        round(sum(recalls) / len(recalls), 6),
        round(sum(f1s) / len(f1s), 6),
    )


def _confusion_matrix(rows: Sequence[Mapping[str, str]], *, multilabel: bool) -> dict[str, object]:
    if multilabel:
        counts: dict[str, Counter[str]] = defaultdict(Counter)
        for row in rows:
            gold_raw = _final_gold_value(row)
            if not gold_raw.strip():
                continue
            current = _parse_multilabel(str(row.get("current_value") or ""))
            gold_labels = _parse_multilabel(gold_raw)
            for label in current | gold_labels:
                state = (
                    "true_positive"
                    if label in current and label in gold_labels
                    else "false_positive"
                    if label in current
                    else "false_negative"
                )
                counts[label][state] += 1
        return {label: dict(values) for label, values in sorted(counts.items())}
    matrix: dict[str, Counter[str]] = defaultdict(Counter)
    for row in rows:
        gold_value = _final_gold_value(row)
        if not gold_value.strip():
            continue
        matrix[_normalized_label(gold_value)][
            _normalized_label(str(row.get("current_value") or ""))
        ] += 1
    return {gold: dict(predictions) for gold, predictions in sorted(matrix.items())}


def score_inter_annotator_agreement(
    rows: Sequence[Mapping[str, str]],
    schema_by_name: Mapping[str, SchemaField],
) -> list[dict[str, object]]:
    """Score independent A/B labels before adjudication."""

    by_field: dict[str, list[Mapping[str, str]]] = defaultdict(list)
    for row in rows:
        left_value = str(row.get("annotator_a_value") or "").strip()
        right_value = str(row.get("annotator_b_value") or "").strip()
        left_correct = _parse_binary(row.get("annotator_a_is_correct"))
        right_correct = _parse_binary(row.get("annotator_b_is_correct"))
        if (left_value and right_value) or (left_correct is not None and right_correct is not None):
            by_field[str(row.get("field_name") or "")].append(row)
    results: list[dict[str, object]] = []
    for field_name, field_rows in sorted(by_field.items()):
        field = schema_by_name.get(field_name)
        categorical_pairs = [
            (
                _normalized_label(row.get("annotator_a_value")),
                _normalized_label(row.get("annotator_b_value")),
            )
            for row in field_rows
            if str(row.get("annotator_a_value") or "").strip()
            and str(row.get("annotator_b_value") or "").strip()
        ]
        binary_pairs = [
            (str(left), str(right))
            for row in field_rows
            if (left := _parse_binary(row.get("annotator_a_is_correct"))) is not None
            and (right := _parse_binary(row.get("annotator_b_is_correct"))) is not None
        ]
        is_multilabel = bool(field and field.expected_data_type.casefold().startswith("array"))
        if categorical_pairs:
            basis = "multilabel_values" if is_multilabel else "categorical_values"
            if is_multilabel:
                set_pairs = [
                    (
                        _parse_multilabel(str(row.get("annotator_a_value") or "")),
                        _parse_multilabel(str(row.get("annotator_b_value") or "")),
                    )
                    for row in field_rows
                    if str(row.get("annotator_a_value") or "").strip()
                    and str(row.get("annotator_b_value") or "").strip()
                ]
                raw = _ratio(sum(left == right for left, right in set_pairs), len(set_pairs))
            else:
                raw = _ratio(
                    sum(left == right for left, right in categorical_pairs),
                    len(categorical_pairs),
                )
            kappa = "" if is_multilabel else _cohen_kappa(categorical_pairs)
            double_count = len(categorical_pairs)
        else:
            basis = "binary_correctness"
            raw = _ratio(sum(left == right for left, right in binary_pairs), len(binary_pairs))
            kappa = _cohen_kappa(binary_pairs)
            double_count = len(binary_pairs)
        weighted: float | str = ""
        if field and field.ordinal_values:
            ordinal_pairs = [
                (
                    str(row.get("annotator_a_value") or "").strip(),
                    str(row.get("annotator_b_value") or "").strip(),
                )
                for row in field_rows
                if str(row.get("annotator_a_value") or "").strip()
                and str(row.get("annotator_b_value") or "").strip()
            ]
            weighted = _weighted_kappa(ordinal_pairs, field.ordinal_values)
        multilabel_jaccards: list[float] = []
        if is_multilabel:
            for row in field_rows:
                left_raw = str(row.get("annotator_a_value") or "").strip()
                right_raw = str(row.get("annotator_b_value") or "").strip()
                if left_raw and right_raw:
                    left_set = _parse_multilabel(left_raw)
                    right_set = _parse_multilabel(right_raw)
                    union = left_set | right_set
                    multilabel_jaccards.append(
                        len(left_set & right_set) / len(union) if union else 1.0
                    )
        results.append(
            {
                "field_name": field_name,
                "expected_data_type": field.expected_data_type if field else "unknown",
                "double_annotated_count": double_count,
                "agreement_basis": basis,
                "raw_agreement": raw,
                "cohen_kappa": kappa,
                "weighted_kappa": weighted,
                "multilabel_jaccard_agreement": (
                    round(sum(multilabel_jaccards) / len(multilabel_jaccards), 6)
                    if multilabel_jaccards
                    else ""
                ),
            }
        )
    return results


def _cohen_kappa(pairs: Sequence[tuple[str, str]]) -> float | None:
    if not pairs:
        return None
    observed = sum(left == right for left, right in pairs) / len(pairs)
    left_counts = Counter(left for left, _ in pairs)
    right_counts = Counter(right for _, right in pairs)
    expected = sum(
        (left_counts[label] / len(pairs)) * (right_counts[label] / len(pairs))
        for label in set(left_counts) | set(right_counts)
    )
    if math.isclose(expected, 1.0):
        return 1.0 if math.isclose(observed, 1.0) else 0.0
    return round((observed - expected) / (1 - expected), 6)


def _weighted_kappa(pairs: Sequence[tuple[str, str]], ordinal_values: Sequence[str]) -> float | str:
    if not pairs or len(ordinal_values) < 2:
        return ""
    indexes = {value: index for index, value in enumerate(ordinal_values)}
    valid = [
        (indexes[left], indexes[right])
        for left, right in pairs
        if left in indexes and right in indexes
    ]
    if not valid:
        return ""
    maximum = (len(ordinal_values) - 1) ** 2
    observed_disagreement = sum((left - right) ** 2 / maximum for left, right in valid) / len(valid)
    left_counts = Counter(left for left, _ in valid)
    right_counts = Counter(right for _, right in valid)
    expected_disagreement = sum(
        (left - right) ** 2
        / maximum
        * (left_counts[left] / len(valid))
        * (right_counts[right] / len(valid))
        for left in indexes.values()
        for right in indexes.values()
    )
    if math.isclose(expected_disagreement, 0.0):
        return 1.0 if math.isclose(observed_disagreement, 0.0) else 0.0
    return round(1 - observed_disagreement / expected_disagreement, 6)


def _segment_values(
    row: Mapping[str, str], field: SchemaField | None
) -> tuple[tuple[str, str], ...]:
    values: list[tuple[str, str]] = []
    for column in ("document_type", "source", "version_group_id", "error_type"):
        value = str(row.get(column) or "").strip()
        if value:
            values.append((column, value))
    if field:
        values.append(("generation_method", field.generation_method))
        values.append(("generation_family", generation_family(field)))
    return tuple(values)


def _final_correctness(row: Mapping[str, str]) -> int | None:
    for key in ("adjudicated_is_correct", "is_correct"):
        parsed = _parse_binary(row.get(key))
        if parsed is not None:
            return parsed
    return None


def _final_gold_value(row: Mapping[str, str]) -> str:
    adjudicated = str(row.get("adjudicated_value") or "").strip()
    return adjudicated if adjudicated else str(row.get("gold_value") or "").strip()


def _parse_binary(value: object) -> int | None:
    text = str(value or "").strip().casefold()
    if text in {"1", "true", "yes", "correct"}:
        return 1
    if text in {"0", "false", "no", "incorrect"}:
        return 0
    return None


def _normalized_label(value: object) -> str:
    text = normalized_surface(str(value or ""))
    return text or "<missing>"


def _parse_multilabel(value: str) -> set[str]:
    text = value.strip()
    if not text:
        return set()
    try:
        parsed = json.loads(text)
    except json.JSONDecodeError:
        parsed = None
    if isinstance(parsed, list):
        return {_normalized_label(item) for item in parsed if str(item).strip()}
    separator = "|" if "|" in text else ","
    return {_normalized_label(item) for item in text.split(separator) if item.strip()}


def _ratio(numerator: int, denominator: int) -> float | None:
    return round(numerator / denominator, 6) if denominator else None


def _metric_int(value: object) -> int:
    if isinstance(value, bool):
        return int(value)
    if isinstance(value, int | float):
        return int(value)
    if isinstance(value, str):
        try:
            return int(value)
        except ValueError:
            return 0
    return 0


def _metric_float(value: object, default: float = 0.0) -> float:
    if isinstance(value, bool):
        return float(value)
    if isinstance(value, int | float):
        return float(value)
    if isinstance(value, str):
        try:
            return float(value)
        except ValueError:
            return default
    return default


def _harmonic(left: float | None, right: float | None) -> float | None:
    if left is None or right is None:
        return None
    return round(2 * left * right / (left + right), 6) if left + right else 0.0


def _render_accuracy_report(
    accuracy_rows: Sequence[Mapping[str, object]],
    agreement_rows: Sequence[Mapping[str, object]],
    total_rows: int,
    labeled_rows: int,
    schema: Sequence[SchemaField],
) -> str:
    field_rows = [
        row
        for row in accuracy_rows
        if row.get("group_type") == "field"
        and row.get("field_name") != "__all__"
        and _metric_int(row.get("labeled_count")) > 0
    ]
    ranked = sorted(field_rows, key=lambda row: _metric_float(row.get("accuracy")))
    missing_ranked = sorted(
        field_rows,
        key=lambda row: _metric_int(row.get("missing_error_count")),
        reverse=True,
    )
    low_agreement = sorted(
        (
            row
            for row in agreement_rows
            if _metric_int(row.get("double_annotated_count")) > 0
        ),
        key=lambda row: _metric_float(row.get("cohen_kappa"), -1.0),
    )[:10]
    family_rows = [
        row
        for row in accuracy_rows
        if row.get("group_type") == "generation_family" and row.get("field_name") == "__all__"
    ]
    schema_by_name = {field.field_name: field for field in schema}
    retrieval_fields = {
        field.field_name
        for field in schema
        if field.used_in_embedding or field.used_in_filter or field.used_in_boost
    }
    version_fields = {
        field.field_name
        for field in schema
        if "version" in field.category.casefold()
        or field.field_name in {"effective_from", "effective_to", "is_current", "status"}
    }
    access_fields = {field.field_name for field in schema if field.used_in_access_control}
    retrieval_errors = sum(
        _metric_int(row.get("labeled_count")) - _metric_int(row.get("correct_count"))
        for row in field_rows
        if str(row.get("field_name")) in retrieval_fields
    )
    version_errors = sum(
        _metric_int(row.get("labeled_count")) - _metric_int(row.get("correct_count"))
        for row in field_rows
        if str(row.get("field_name")) in version_fields
    )
    security_scope_errors = sum(
        _metric_int(row.get("wrong_scope_error_count"))
        for row in field_rows
        if str(row.get("field_name")) in access_fields
    )
    filter_rows = [
        row
        for row in field_rows
        if (field := schema_by_name.get(str(row.get("field_name")))) and field.used_in_filter
    ]
    if not filter_rows:
        hard_filter_verdict = (
            "Chưa thể kết luận: chưa có gold label cho các field đang dùng làm filter."
        )
    elif all(
        _metric_int(row.get("labeled_count")) >= 30
        and _metric_float(row.get("accuracy")) >= 0.99
        and _metric_int(row.get("wrong_scope_error_count")) == 0
        for row in filter_rows
    ):
        hard_filter_verdict = (
            "Mẫu hiện tại đạt ngưỡng audit bảo thủ (n>=30/field, accuracy>=0.99, "
            "không có wrong_scope); vẫn cần xác nhận coverage toàn corpus."
        )
    else:
        hard_filter_verdict = (
            "Chưa đủ đáng tin cậy cho hard filter theo ngưỡng audit bảo thủ; xem từng "
            "field và lỗi wrong_scope."
        )
    if not labeled_rows:
        highest = lowest = ["- Chưa có nhãn adjudicated."]
        missing_lines = ["- Chưa có gold label để xếp hạng lỗi missing."]
        risk_lines = [
            "- Chưa có gold label để định lượng lỗi retrieval, version hoặc access control.",
            "- Không được diễn giải số lỗi bằng 0 khi số row đã gán nhãn cũng bằng 0.",
        ]
    else:
        highest = [
            f"- `{row.get('field_name')}`: {row.get('accuracy')} (n={row.get('labeled_count')})"
            for row in reversed(ranked[-5:])
        ]
        lowest = [
            f"- `{row.get('field_name')}`: {row.get('accuracy')} (n={row.get('labeled_count')})"
            for row in ranked[:5]
        ]
        missing_lines = [
            f"- `{row.get('field_name')}`: {row.get('missing_error_count')} lỗi missing"
            for row in missing_ranked[:10]
            if _metric_int(row.get("missing_error_count")) > 0
        ] or ["- Chưa ghi nhận lỗi missing trong các row đã gán nhãn."]
        risk_lines = [
            f"- Lỗi trên field ảnh hưởng retrieval: **{retrieval_errors}**.",
            f"- Lỗi trên field version/temporal: **{version_errors}**.",
            f"- Lỗi `wrong_scope` trên access-control field: **{security_scope_errors}**.",
            "- Bất kỳ lỗi security nào trong sample cũng là tín hiệu chặn; không ngoại suy "
            "tỷ lệ bằng 0 từ một sample nhỏ.",
        ]
    return "\n".join(
        [
            "# Báo cáo độ chính xác metadata hiện tại",
            "",
            f"- Tổng annotation rows: **{total_rows}**",
            f"- Rows đã có gold/adjudication: **{labeled_rows}**",
            "",
            "## Field chính xác nhất",
            "",
            *highest,
            "",
            "## Field sai nhiều nhất",
            "",
            *lowest,
            "",
            "## Field thiếu nhiều nhất",
            "",
            *missing_lines,
            "",
            "## Parser, rule, database và LLM",
            "",
            *(
                [
                    f"- `{row.get('group_value')}`: accuracy={row.get('accuracy')}, "
                    f"n={row.get('labeled_count')}"
                    for row in sorted(family_rows, key=lambda item: str(item.get("group_value")))
                ]
                or ["- Chưa đủ nhãn để so sánh generation family."]
            ),
            "",
            "## Đồng thuận annotator thấp nhất",
            "",
            *(
                [
                    f"- `{row.get('field_name')}`: raw={row.get('raw_agreement')}, "
                    f"kappa={row.get('cohen_kappa')}, basis={row.get('agreement_basis')}"
                    for row in low_agreement
                ]
                or ["- Chưa có row được hai annotator gán độc lập."]
            ),
            "",
            "## Rủi ro theo mục đích sử dụng",
            "",
            *risk_lines,
            "",
            "## Có đủ tin cậy cho hard filter không?",
            "",
            hard_filter_verdict,
            "",
            "## Biên diễn giải",
            "",
            "Báo cáo chỉ đánh giá metadata hiện tại. Nó không thiết kế hoặc đề xuất schema mới.",
        ]
    )


def _build_parser() -> argparse.ArgumentParser:
    base = Path(__file__).parent
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--annotations", type=Path, required=True)
    parser.add_argument("--schema", type=Path, default=base / "metadata_schema.csv")
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--overwrite", action="store_true")
    parser.add_argument(
        "--log-level",
        choices=("DEBUG", "INFO", "WARNING", "ERROR"),
        default="INFO",
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)
    logging.basicConfig(
        level=getattr(logging, args.log_level),
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    outputs = {
        "accuracy": args.output_dir / "metadata_field_accuracy.csv",
        "confusion": args.output_dir / "metadata_confusion_matrices.json",
        "agreement": args.output_dir / "metadata_inter_annotator_agreement.csv",
        "report": args.output_dir / "metadata_accuracy_report.md",
    }
    try:
        ensure_outputs(outputs.values(), overwrite=args.overwrite)
        schema = load_schema(args.schema)
        rows = load_annotation_rows(args.annotations)
        accuracy, confusion, agreement, report = score_annotations(rows, schema)
        write_csv(outputs["accuracy"], accuracy, ACCURACY_COLUMNS)
        write_json(outputs["confusion"], confusion)
        write_csv(outputs["agreement"], agreement, AGREEMENT_COLUMNS)
        write_text(outputs["report"], report)
    except MetadataBaselineError as exc:
        LOGGER.error("Metadata scoring failed: %s", exc)
        return 2
    except Exception:
        LOGGER.exception("Unexpected metadata scoring failure")
        return 1
    LOGGER.info("Metadata accuracy outputs written to %s", args.output_dir)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())


__all__ = [
    "load_annotation_rows",
    "main",
    "score_annotations",
    "score_inter_annotator_agreement",
]
