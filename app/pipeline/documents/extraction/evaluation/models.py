from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class ExpectedTextSpan:
    text: str
    page_number: int | None = None
    required: bool = True
    severity: str = "error"


@dataclass(frozen=True)
class ExpectedTable:
    table_id: str
    page_number: int | None
    columns: list[str]
    rows: list[dict[str, str]] = field(default_factory=list)
    row_count: int | None = None
    column_count: int | None = None
    required: bool = True
    severity: str = "error"


@dataclass(frozen=True)
class ExpectedIssue:
    code: str
    severity: str = "error"
    must_not_appear: bool = False


@dataclass(frozen=True)
class ExtractionGroundTruth:
    case_id: str
    document_path: str
    sha256: str | None = None
    domain: str = "unknown"
    parser_mode: str = "auto"
    validation_status: str = "DRAFT"
    expected_text: list[ExpectedTextSpan] = field(default_factory=list)
    expected_tables: list[ExpectedTable] = field(default_factory=list)
    expected_issues: list[ExpectedIssue] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_mapping(cls, data: dict[str, Any]) -> ExtractionGroundTruth:
        return cls(
            case_id=str(data["case_id"]),
            document_path=str(data["document_path"]),
            sha256=data.get("sha256"),
            domain=str(data.get("domain") or "unknown"),
            parser_mode=str(data.get("parser_mode") or "auto"),
            validation_status=str(data.get("validation_status") or "DRAFT"),
            expected_text=[
                ExpectedTextSpan(
                    text=str(item["text"]),
                    page_number=item.get("page_number"),
                    required=bool(item.get("required", True)),
                    severity=str(item.get("severity") or "error"),
                )
                for item in data.get("expected_text", [])
            ],
            expected_tables=[
                ExpectedTable(
                    table_id=str(item["table_id"]),
                    page_number=item.get("page_number"),
                    columns=[str(column) for column in item.get("columns", [])],
                    rows=[
                        {str(key): str(value) for key, value in row.items()}
                        for row in item.get("rows", [])
                    ],
                    row_count=item.get("row_count"),
                    column_count=item.get("column_count"),
                    required=bool(item.get("required", True)),
                    severity=str(item.get("severity") or "error"),
                )
                for item in data.get("expected_tables", [])
            ],
            expected_issues=[
                ExpectedIssue(
                    code=str(item["code"]),
                    severity=str(item.get("severity") or "error"),
                    must_not_appear=bool(item.get("must_not_appear", False)),
                )
                for item in data.get("expected_issues", [])
            ],
            metadata=dict(data.get("metadata") or {}),
        )
