from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from app.pipeline.documents.extraction.canonical.ir import CanonicalPage
from app.pipeline.documents.extraction.tables.geometry import (
    bbox_contains,
    validate_table_bbox_in_page,
)
from app.pipeline.documents.extraction.tables.models import (
    TABLE_VALIDATOR_VERSION,
    StructuredTable,
    TableIssue,
)


@dataclass(frozen=True)
class TableValidationResult:
    valid: bool
    issues: tuple[TableIssue, ...] = ()
    warnings: tuple[TableIssue, ...] = ()
    metrics: dict[str, Any] = field(default_factory=dict)

    @property
    def issue_codes(self) -> tuple[str, ...]:
        return tuple(dict.fromkeys(issue.issue_code for issue in (*self.issues, *self.warnings)))

    def to_dict(self) -> dict[str, Any]:
        return {
            "valid": self.valid,
            "issues": [issue.to_dict() for issue in self.issues],
            "warnings": [issue.to_dict() for issue in self.warnings],
            "issue_codes": list(self.issue_codes),
            "metrics": dict(self.metrics),
            "validator_version": TABLE_VALIDATOR_VERSION,
        }


def validate_structured_table(
    table: StructuredTable,
    *,
    page: CanonicalPage | None = None,
) -> TableValidationResult:
    issues: list[TableIssue] = []
    warnings: list[TableIssue] = []
    if page is not None:
        table_bbox = validate_table_bbox_in_page(table.bbox, page)
        if not table_bbox.valid:
            issues.append(
                _issue(
                    table,
                    "table_bbox_outside_page",
                    "fail_closed",
                    reason="Table bbox is outside page bounds.",
                    evidence={"reason_codes": list(table_bbox.reason_codes)},
                )
            )
    if not table.columns:
        issues.append(
            _issue(table, "missing_columns", "fail_closed", reason="Table has no columns.")
        )
    if not table.rows:
        issues.append(_issue(table, "missing_rows", "fail_closed", reason="Table has no rows."))
    if not table.cells:
        issues.append(_issue(table, "missing_cells", "fail_closed", reason="Table has no cells."))
    expected_cells = len(table.rows) * len(table.columns)
    occupied = {(cell.row_start, cell.column_start) for cell in table.cells}
    if len(occupied) != len(table.cells):
        issues.append(
            _issue(
                table,
                "duplicate_cell_slot",
                "fail_closed",
                reason="Multiple cells share one row/column slot.",
            )
        )
    if len(occupied) < expected_cells:
        warnings.append(
            _issue(
                table,
                "sparse_grid",
                "warning",
                reason="Table grid has unoccupied slots.",
                evidence={"expected_cells": expected_cells, "actual_cells": len(occupied)},
            )
        )
    for cell in table.cells:
        if cell.row_end >= len(table.rows) or cell.column_end >= len(table.columns):
            issues.append(
                _issue(
                    table,
                    "cell_index_outside_grid",
                    "fail_closed",
                    cell_ids=(cell.cell_id,),
                    reason="Cell index extends outside the table grid.",
                )
            )
        if not bbox_contains(table.bbox, cell.bbox):
            issues.append(
                _issue(
                    table,
                    "cell_bbox_outside_table",
                    "fail_closed",
                    cell_ids=(cell.cell_id,),
                    reason="Cell bbox extends outside table bbox.",
                )
            )
    header_cell_ids = {cell_id for header in table.header_structure for cell_id in header.cell_ids}
    cell_ids = {cell.cell_id for cell in table.cells}
    missing_headers = sorted(header_cell_ids - cell_ids)
    if missing_headers:
        issues.append(
            _issue(
                table,
                "header_cell_missing",
                "fail_closed",
                cell_ids=tuple(missing_headers),
                reason="Header references missing cells.",
            )
        )
    return TableValidationResult(
        valid=not issues,
        issues=tuple(issues),
        warnings=tuple(warnings),
        metrics={
            "row_count": len(table.rows),
            "column_count": len(table.columns),
            "cell_count": len(table.cells),
            "expected_cell_slots": expected_cells,
            "grid_valid": not issues,
        },
    )


def _issue(
    table: StructuredTable,
    issue_code: str,
    severity: str,
    *,
    cell_ids: tuple[str, ...] = (),
    reason: str,
    evidence: dict[str, Any] | None = None,
) -> TableIssue:
    return TableIssue(
        issue_code=issue_code,
        severity=severity,
        table_id=table.table_id,
        page_numbers=table.page_numbers,
        cell_ids=cell_ids,
        evidence=dict(evidence or {}),
        reason=reason,
        provenance={"validator_version": TABLE_VALIDATOR_VERSION},
    )


__all__ = [
    "TableValidationResult",
    "validate_structured_table",
]
