from __future__ import annotations

import re
from dataclasses import dataclass

from app.pipeline.documents.extraction.parsing.parsers import ParsedDocument
from app.pipeline.shared.text_utils import normalize_text


@dataclass(frozen=True)
class StructuredValidationIssue:
    code: str
    severity: str
    message: str
    table_id: str | None = None


FINANCIAL_CODE_COLUMNS = {"ma so", "mã số", "mã sô", "mÃ£ sá»‘"}
FINANCIAL_INDICATOR_COLUMNS = {
    "chi tieu",
    "chỉ tiêu",
    "tai san",
    "tài sản",
    "nguon von",
    "nguồn vốn",
    "chá»‰ tiÃªu",
}
FINANCIAL_NOTE_COLUMNS = {"thuyet minh", "thuyết minh"}
SUBSIDIARY_COLUMNS = {
    "stt",
    'tên công ty/chi nhánh ("tên viết tắt")',
    "tỷ lệ biểu quyết (%)",
    "tỷ lệ lợi ích (%)",
    "trụ sở chính",
    "hoạt động chính",
}
TOC_COLUMNS = {"mục lục", "trang"}
MONEY_TOKEN = re.compile(r"\(?\d{1,3}(?:\.\d{3}){2,}\)?")


def validate_structured_document(parsed: ParsedDocument) -> tuple[StructuredValidationIssue, ...]:
    issues: list[StructuredValidationIssue] = []
    for table in parsed.tables:
        header = {normalize_text(cell).lower() for cell in table.header}
        if (
            table.rows
            and _requires_financial_columns(header)
            and not _has_financial_columns(header)
        ):
            issues.append(
                StructuredValidationIssue(
                    "structured_missing_required_columns",
                    "error",
                    "Structured table is missing required identifier columns.",
                    table.table_id,
                )
            )
        for row in table.rows:
            for cell in row:
                token = normalize_text(cell)
                if _unbalanced_money_token(token):
                    issues.append(
                        StructuredValidationIssue(
                            "structured_unbalanced_negative_parenthesis",
                            "error",
                            "Structured amount has unbalanced negative parentheses.",
                            table.table_id,
                        )
                    )
                if _label_contains_glued_money(token):
                    issues.append(
                        StructuredValidationIssue(
                            "structured_amount_glued_to_label",
                            "warning",
                            "Structured amount appears glued to a label cell.",
                            table.table_id,
                        )
                    )
    return tuple(dict.fromkeys(issues))


def _requires_financial_columns(header: set[str]) -> bool:
    if _is_toc_header(header) or _is_subsidiary_header(header):
        return False
    return bool(
        header & FINANCIAL_CODE_COLUMNS
        or header & FINANCIAL_INDICATOR_COLUMNS
        or header & FINANCIAL_NOTE_COLUMNS
    )


def _has_financial_columns(header: set[str]) -> bool:
    return (
        bool(header & FINANCIAL_CODE_COLUMNS)
        and bool(header & FINANCIAL_INDICATOR_COLUMNS)
        and bool(header & FINANCIAL_NOTE_COLUMNS)
    )


def _is_toc_header(header: set[str]) -> bool:
    return bool(header & TOC_COLUMNS) and "trang" in header


def _is_subsidiary_header(header: set[str]) -> bool:
    return len(header & SUBSIDIARY_COLUMNS) >= 4


def _unbalanced_money_token(text: str) -> bool:
    for match in MONEY_TOKEN.finditer(text.replace(" ", "")):
        token = match.group(0)
        if token.count("(") != token.count(")"):
            return True
    return False


def _label_contains_glued_money(text: str) -> bool:
    return bool(re.search(r"[A-Za-zÀ-ỹ]\s*\d{1,3}(?:\.\d{3}){2,}", text))
