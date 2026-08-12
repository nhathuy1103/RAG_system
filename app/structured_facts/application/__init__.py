"""Structured-fact application services."""

from app.structured_facts.application.claim_alignment import (
    ClaimAlignmentResult,
    align_claims,
    compare_aligned_claims,
)
from app.structured_facts.application.claim_extraction import (
    ClaimExtractionResult,
    canonicalize_table_claims,
    extract_structured_claims,
)
from app.structured_facts.application.comparison import (
    build_structured_relation_payloads,
    build_unified_claim_relation_payloads,
)
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
from app.structured_facts.application.value_normalization import (
    OPERATOR_NORMALIZER_VERSION,
    ValueParseResult,
    compare_value_expressions,
    normalize_value_expression,
    parse_decimal_locale,
)

__all__ = [
    "QualifierComparisonResult",
    "ScopeComparisonResult",
    "HeaderSpec",
    "MIN_TRUSTED_CLAIM_CONFIDENCE",
    "OPERATOR_NORMALIZER_VERSION",
    "TABLE_FACT_EXTRACTOR_VERSION",
    "TableAnalysis",
    "TableDiff",
    "StructuredFactReviewService",
    "ClaimAlignmentResult",
    "ClaimExtractionResult",
    "ValueParseResult",
    "align_claims",
    "analyze_table",
    "build_structured_relation_payloads",
    "build_unified_claim_relation_payloads",
    "canonicalize_table_claims",
    "compare_business_scopes",
    "compare_qualifiers",
    "compare_temporal_intervals",
    "compare_aligned_claims",
    "compare_value_expressions",
    "explain_business_scope_relation",
    "explain_qualifier_compatibility",
    "diff_table_analyses",
    "extract_structured_claims",
    "normalize_area",
    "normalize_header",
    "normalize_money",
    "normalize_value_expression",
    "parse_decimal_locale",
]
