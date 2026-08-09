from __future__ import annotations

from app.pipeline.documents.extraction.parsing.parsers import ParsedDocument
from app.pipeline.documents.extraction.validation.structured import (
    StructuredValidationIssue,
    validate_structured_document,
)

FinancialValidationIssue = StructuredValidationIssue

_LEGACY_ISSUE_CODES = {
    "structured_missing_required_columns": "financial_missing_required_columns",
    "structured_unbalanced_negative_parenthesis": "financial_unbalanced_negative_parenthesis",
    "structured_amount_glued_to_label": "financial_amount_glued_to_label",
}


def validate_financial_document(parsed: ParsedDocument) -> tuple[FinancialValidationIssue, ...]:
    return tuple(
        FinancialValidationIssue(
            code=_LEGACY_ISSUE_CODES.get(issue.code, issue.code),
            severity=issue.severity,
            message=issue.message,
            table_id=issue.table_id,
        )
        for issue in validate_structured_document(parsed)
    )
