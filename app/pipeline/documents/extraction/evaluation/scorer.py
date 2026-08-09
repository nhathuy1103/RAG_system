from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any

from app.pipeline.documents.extraction.documents.quality import DocumentQualityEvaluator
from app.pipeline.documents.extraction.evaluation.models import ExtractionGroundTruth
from app.pipeline.documents.extraction.evaluation.scoring_normalization import (
    POLICY_VERSION as SCORING_NORMALIZATION_POLICY_VERSION,
)
from app.pipeline.documents.extraction.evaluation.scoring_normalization import (
    exact_match_trace,
    normalized_text,
)
from app.pipeline.documents.extraction.parsing.parsers import ParsedDocument

ISSUE_CODE_ALIASES = {
    "financial_missing_required_columns": "structured_missing_required_columns",
    "financial_unbalanced_negative_parenthesis": "structured_unbalanced_negative_parenthesis",
    "financial_amount_glued_to_label": "structured_amount_glued_to_label",
}


@dataclass(frozen=True)
class ExtractionScore:
    case_id: str
    passed: bool
    text_recall: float
    table_recall: float
    issue_recall: float
    silent_p0: bool
    quality_status: str
    failures: tuple[str, ...] = field(default_factory=tuple)
    details: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def score_extraction(
    parsed: ParsedDocument,
    ground_truth: ExtractionGroundTruth,
) -> ExtractionScore:
    quality = DocumentQualityEvaluator().evaluate(parsed)
    failures: list[str] = []
    normalization_traces: list[dict[str, Any]] = []
    text_recall, text_silent_p0 = _expected_text_recall(
        parsed,
        ground_truth,
        failures,
        normalization_traces,
    )
    table_recall, table_silent_p0 = _expected_table_recall(
        parsed,
        ground_truth,
        failures,
        normalization_traces,
    )
    issue_recall, issue_silent_p0 = _expected_issue_recall(quality, ground_truth, failures)
    silent_p0 = text_silent_p0 or table_silent_p0 or issue_silent_p0
    passed = (
        text_recall == 1.0
        and table_recall == 1.0
        and issue_recall == 1.0
        and not silent_p0
        and quality.status != "FAIL"
    )
    return ExtractionScore(
        case_id=ground_truth.case_id,
        passed=passed,
        text_recall=text_recall,
        table_recall=table_recall,
        issue_recall=issue_recall,
        silent_p0=silent_p0,
        quality_status=quality.status,
        failures=tuple(failures),
        details={
            "quality": quality.to_dict(),
            "scoring_normalization": {
                "policy_version": SCORING_NORMALIZATION_POLICY_VERSION,
                "mismatches": normalization_traces,
            },
        },
    )


def _expected_text_recall(
    parsed: ParsedDocument,
    ground_truth: ExtractionGroundTruth,
    failures: list[str],
    normalization_traces: list[dict[str, Any]],
) -> tuple[float, bool]:
    expected = [item for item in ground_truth.expected_text if item.required]
    if not expected:
        return 1.0, False
    found = 0
    silent_p0 = False
    document_text = normalized_text(parsed.text).lower()
    raw_pages = {page.page_number: page.text for page in parsed.pages}
    pages = {page_number: normalized_text(text).lower() for page_number, text in raw_pages.items()}
    for item in expected:
        haystack = pages.get(item.page_number, document_text) if item.page_number else document_text
        expected_text = normalized_text(item.text).lower()
        if expected_text in haystack:
            found += 1
        else:
            failures.append(f"missing_text:{item.page_number or 'document'}:{item.text[:80]}")
            raw_actual = (
                raw_pages.get(item.page_number, parsed.text) if item.page_number else parsed.text
            )
            normalization_traces.append(
                {
                    "scope": "expected_text",
                    "field_path": f"expected_text[{expected.index(item)}].text",
                    "page_number": item.page_number,
                    "trace": exact_match_trace(item.text, _excerpt(raw_actual), join_lines=True),
                }
            )
            silent_p0 = silent_p0 or _is_p0(item.severity)
    return round(found / len(expected), 4), silent_p0


def _expected_table_recall(
    parsed: ParsedDocument,
    ground_truth: ExtractionGroundTruth,
    failures: list[str],
    normalization_traces: list[dict[str, Any]],
) -> tuple[float, bool]:
    expected = [table for table in ground_truth.expected_tables if table.required]
    if not expected:
        return 1.0, False
    found = 0
    silent_p0 = False
    for expected_table in expected:
        if _table_matches(parsed, expected_table):
            found += 1
        else:
            failures.append(f"missing_table:{expected_table.table_id}")
            normalization_traces.append(
                {
                    "scope": "expected_table",
                    "field_path": f"expected_tables[{expected.index(expected_table)}]",
                    "page_number": expected_table.page_number,
                    "trace": {
                        "policy_version": SCORING_NORMALIZATION_POLICY_VERSION,
                        "raw_expected": {
                            "columns": expected_table.columns,
                            "rows": expected_table.rows,
                        },
                        "raw_actual": _table_actual_snapshot(parsed, expected_table.page_number),
                        "normalized_expected": {
                            "columns": [
                                normalized_text(column).lower() for column in expected_table.columns
                            ],
                            "rows": [
                                {
                                    normalized_text(key).lower(): normalized_text(value).lower()
                                    for key, value in row.items()
                                }
                                for row in expected_table.rows
                            ],
                        },
                        "normalized_actual": [
                            {
                                "table_id": table.table_id,
                                "location": table.location,
                                "header": [normalized_text(cell).lower() for cell in table.header],
                            }
                            for table in parsed.tables
                            if expected_table.page_number is None
                            or _table_page_matches(parsed, table, expected_table.page_number)
                        ],
                        "normalization_operations": "safe_policy_applied_per_cell",
                        "matched": False,
                        "mismatch_reason": "exact_table_structure_or_cell_mismatch",
                    },
                }
            )
            silent_p0 = silent_p0 or _is_p0(expected_table.severity)
    return round(found / len(expected), 4), silent_p0


def _is_p0(severity: str) -> bool:
    return severity.lower() in {"p0", "critical"}


def _table_matches(parsed: ParsedDocument, expected_table: Any) -> bool:
    expected_columns = [normalized_text(column).lower() for column in expected_table.columns]
    for table in parsed.tables:
        actual_columns = [normalized_text(column).lower() for column in table.header]
        if expected_columns and actual_columns[: len(expected_columns)] != expected_columns:
            continue
        if expected_table.column_count is not None and table.columns != expected_table.column_count:
            continue
        if expected_table.row_count is not None and len(table.rows) != expected_table.row_count:
            continue
        if (
            _is_structured_table_expectation(expected_table)
            and expected_columns
            and table.columns != len(expected_columns)
        ):
            continue
        if expected_table.page_number is not None and not _table_page_matches(
            parsed, table, expected_table.page_number
        ):
            continue
        if not expected_table.rows:
            return True
        if all(
            _expected_row_matches_table(
                table,
                expected_columns,
                row,
                strict=_is_structured_table_expectation(expected_table),
            )
            for row in expected_table.rows
        ):
            return True
    return False


def _expected_row_matches_table(
    table: Any,
    expected_columns: list[str],
    expected_row: dict[str, str],
    *,
    strict: bool = False,
) -> bool:
    column_indexes = {column: index for index, column in enumerate(expected_columns)}
    actual_rows = _data_rows(table.rows, expected_columns)
    for actual_row in actual_rows:
        if _expected_row_matches_actual_row(
            actual_row,
            column_indexes,
            expected_row,
            strict=strict,
        ):
            return True
    return False


def _data_rows(rows: list[list[str]], expected_columns: list[str]) -> list[list[str]]:
    if not rows:
        return []
    first_row = [_cell_text(cell) for cell in rows[0]]
    if first_row[: len(expected_columns)] == expected_columns:
        return rows[1:]
    return rows


def _expected_row_matches_actual_row(
    actual_row: list[str],
    column_indexes: dict[str, int],
    expected_row: dict[str, str],
    *,
    strict: bool = False,
) -> bool:
    for key, value in expected_row.items():
        column = normalized_text(key).lower()
        expected_value = _cell_text(value)
        if not expected_value:
            continue
        if column not in column_indexes:
            return False
        index = column_indexes[column]
        actual_value = _cell_text(actual_row[index]) if index < len(actual_row) else ""
        if strict or _is_numeric_token(expected_value):
            if expected_value != actual_value:
                return False
            continue
        if expected_value not in actual_value:
            return False
    return True


def _cell_text(value: Any) -> str:
    return normalized_text(str(value)).lower()


def _is_numeric_token(value: str) -> bool:
    normalized = value.replace(" ", "")
    return any(char.isdigit() for char in normalized) and any(
        char in normalized for char in ".(),-"
    )


def _is_structured_table_expectation(expected_table: Any) -> bool:
    return bool(
        expected_table.rows
        or expected_table.row_count is not None
        or expected_table.column_count is not None
    )


def _table_page_matches(parsed: ParsedDocument, table: Any, expected_page_number: int) -> bool:
    location = str(table.location or "")
    if f"page:{expected_page_number}" in location or f"page-{expected_page_number}" in location:
        return True
    return bool(
        expected_page_number == 1
        and len(parsed.pages) == 1
        and "page:" not in location
        and "page-" not in location
    )


def _expected_issue_recall(
    quality: Any,
    ground_truth: ExtractionGroundTruth,
    failures: list[str],
) -> tuple[float, bool]:
    expected = ground_truth.expected_issues
    if not expected:
        return 1.0, False
    actual_codes = {_canonical_issue_code(issue.code) for issue in quality.issues}
    found = 0
    silent_p0 = False
    for issue in expected:
        canonical_expected = _canonical_issue_code(issue.code)
        appears = canonical_expected in actual_codes
        if issue.must_not_appear:
            if appears:
                failures.append(f"unexpected_issue:{issue.code}")
            else:
                found += 1
            continue
        if appears:
            found += 1
        else:
            failures.append(f"missing_issue:{issue.code}")
            if issue.severity.lower() in {"p0", "error"}:
                silent_p0 = True
    return round(found / len(expected), 4), silent_p0


def _canonical_issue_code(code: str) -> str:
    return ISSUE_CODE_ALIASES.get(code, code)


def _excerpt(value: str, limit: int = 500) -> str:
    if len(value) <= limit:
        return value
    return value[:limit] + "..."


def _table_actual_snapshot(parsed: ParsedDocument, page_number: int | None) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for table in parsed.tables:
        if page_number is not None and not _table_page_matches(parsed, table, page_number):
            continue
        rows.append(
            {
                "table_id": table.table_id,
                "location": table.location,
                "header": table.header,
                "rows": table.rows[:3],
            }
        )
    return rows[:5]
