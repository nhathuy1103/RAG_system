"""Structured-fact application services."""

from app.structured_facts.application.comparison import build_structured_relation_payloads
from app.structured_facts.application.review import StructuredFactReviewService
from app.structured_facts.application.scope import (
    QualifierComparisonResult,
    ScopeComparisonResult,
    compare_business_scopes,
    compare_qualifiers,
    compare_temporal_intervals,
    explain_business_scope_relation,
    explain_qualifier_compatibility,
)
from app.structured_facts.application.table_analyzer import (
    MIN_TRUSTED_CLAIM_CONFIDENCE,
    TABLE_FACT_EXTRACTOR_VERSION,
    HeaderSpec,
    TableAnalysis,
    analyze_table,
    normalize_area,
    normalize_header,
    normalize_money,
)
from app.structured_facts.application.table_diff import TableDiff, diff_table_analyses

__all__ = [
    "QualifierComparisonResult",
    "ScopeComparisonResult",
    "HeaderSpec",
    "MIN_TRUSTED_CLAIM_CONFIDENCE",
    "TABLE_FACT_EXTRACTOR_VERSION",
    "TableAnalysis",
    "TableDiff",
    "StructuredFactReviewService",
    "analyze_table",
    "build_structured_relation_payloads",
    "compare_business_scopes",
    "compare_qualifiers",
    "compare_temporal_intervals",
    "explain_business_scope_relation",
    "explain_qualifier_compatibility",
    "diff_table_analyses",
    "normalize_area",
    "normalize_header",
    "normalize_money",
]
