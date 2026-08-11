"""Deterministic document-scope extraction and conservative comparison."""

from __future__ import annotations

import re
import unicodedata
from dataclasses import replace
from datetime import date

from app.knowledge_quality.domain.models import ClaimScope, ScopeComparison

_PROJECT_LABEL_PATTERNS = (
    re.compile(
        r"\b(?:dự\s*án|du\s*an|project(?:\s+name)?)\s*[:\-]\s*"
        r"(?P<value>[^,.;\n]{2,100})",
        re.IGNORECASE | re.UNICODE,
    ),
)
_PROJECT_CONTEXT_PATTERN = re.compile(
    r"\b(?:dự\s*án|du\s*an|project)\s+"
    r"(?P<value>[\wÀ-ỹ]+(?:[\s\-]+[\wÀ-ỹ]+){0,11}?)"
    r"(?=\s+(?:có|áp\s+dụng|thuộc|tại|do|has|is|applies|located)\b)",
    re.IGNORECASE | re.UNICODE,
)
_PROJECT_DEFINITION_PATTERN = re.compile(
    r"\b(?:dự\s*án|du\s*an)\s*(?:[\"”']?\s*)?(?:có\s+nghĩa\s+là|nghĩa\s+là)\s*"
    r"(?P<value>[^.;\n]{4,140})",
    re.IGNORECASE | re.UNICODE,
)
_CONTRACT_PATTERN = re.compile(
    r"\b(?:s\u1ed1\s+h\u1ee3p\s+\u0111\u1ed3ng|so\s+hop\s+dong|"
    r"contract(?:\s+(?:id|number|no\.?))?|agreement\s+no\.?)\s*[:#\-]\s*"
    r"(?P<value>[A-Z0-9][A-Z0-9./\-]{4,79})\b",
    re.IGNORECASE | re.UNICODE,
)
_PLACEHOLDER_PATTERN = re.compile(r"^[.\-_/\s]+$")
_DOCUMENT_TYPES = (
    (
        "housing_sale_contract",
        re.compile(r"^\s*hợp\s+đồng\s+mua\s+bán\s+nhà\s+ở\b", re.IGNORECASE),
    ),
    (
        "commercial_area_sale_contract",
        re.compile(
            r"^\s*hợp\s+đồng\s+mua\s+bán\s+diện\s+tích\s+thương\s+mại\b",
            re.IGNORECASE,
        ),
    ),
    (
        "sale_contract",
        re.compile(r"^\s*(?:hợp\s+đồng\s+mua\s+bán|sale\s+contract)\b", re.IGNORECASE),
    ),
    ("contract", re.compile(r"^\s*(?:hợp\s+đồng|contract)\b", re.IGNORECASE)),
)
_AMBIGUOUS_PROJECT_PREFIXES = (
    "bao gom",
    "bat dau",
    "dang mo ban",
    "duoc mo ban",
    "gom",
    "khac",
    "la",
    "mo ban",
    "moi gom",
    "moi",
    "nay",
    "sap mo ban",
    "trien khai",
    "xay dung",
)
_YEAR_TOKEN = r"(?:19|20)\d{2}"
_YEAR_RANGE_PATTERN = re.compile(
    rf"\b(?:năm|nam|years?|giai\s+đoạn|giai\s+doan|period)\s*"
    rf"(?P<start>{_YEAR_TOKEN})\s*(?:-|–|—|đến|den|to)\s*"
    rf"(?P<end>{_YEAR_TOKEN})\b",
    re.IGNORECASE | re.UNICODE,
)
_QUARTER_PATTERN = re.compile(
    rf"\b(?:quý|quy|quarter|q)\s*(?P<quarter>[1-4])"
    rf"(?:\s*(?:[/,\-]|năm|nam|year)?\s*(?P<year>{_YEAR_TOKEN}))?\b",
    re.IGNORECASE | re.UNICODE,
)
_MONTH_PATTERN = re.compile(
    rf"\b(?:tháng|thang|month)\s*(?P<month>0?[1-9]|1[0-2])"
    rf"\s*(?:[/,\-]|năm|nam|year)\s*(?P<year>{_YEAR_TOKEN})\b",
    re.IGNORECASE | re.UNICODE,
)
_ENGLISH_MONTH_PATTERN = re.compile(
    rf"\b(?P<month>january|february|march|april|may|june|july|august|"
    rf"september|october|november|december)\s+(?P<year>{_YEAR_TOKEN})\b",
    re.IGNORECASE,
)
_ENGLISH_MONTHS = {
    "january": 1,
    "february": 2,
    "march": 3,
    "april": 4,
    "may": 5,
    "june": 6,
    "july": 7,
    "august": 8,
    "september": 9,
    "october": 10,
    "november": 11,
    "december": 12,
}
_YEAR_CONTEXT_PATTERN = re.compile(
    rf"\b(?:trong\s+năm|trong\s+nam|năm|nam|year|in|for|during|"
    rf"as\s+of|tại\s+thời\s+điểm|tai\s+thoi\s+diem|kỳ|ky)\s*"
    rf"(?P<year>{_YEAR_TOKEN})\b",
    re.IGNORECASE | re.UNICODE,
)
# Deliberately excludes IDs (HD-2026-001) and numeric dates (01/01/2026).
_BARE_YEAR_PATTERN = re.compile(
    rf"(?<![\w./\-])(?P<year>{_YEAR_TOKEN})(?![\w./\-])",
    re.UNICODE,
)
_INLINE_REFERENCE_YEAR_PATTERN = re.compile(
    rf"(?<![\w./\-])(?P<year>{_YEAR_TOKEN})(?![\w./\-])"
    r"(?=\s*(?:là|la|is|was|were|:))",
    re.IGNORECASE | re.UNICODE,
)
_TITLE_SENTENCE_VERB_PATTERN = re.compile(
    r"\b(?:là|la|có|co|is|are|was|were|has|have|applies?|requires?)\b",
    re.IGNORECASE | re.UNICODE,
)


def normalize_scope_value(value: str) -> str:
    """Normalize an identifier for comparison without changing source text."""
    decomposed = unicodedata.normalize("NFKD", value.casefold())
    ascii_like = "".join(
        character for character in decomposed if not unicodedata.combining(character)
    )
    return " ".join(re.findall(r"[^\W_]+", ascii_like, re.UNICODE))


def extract_claim_scope(
    text: str,
    *,
    document_id: str | None = None,
    canonical_document_id: str | None = None,
    filename: str | None = None,
    version_id: str | None = None,
) -> ClaimScope:
    """Extract only explicit, high-confidence project and contract scope."""
    project_id = _extract_project_id(text)
    contract_id = _extract_contract_id(text)
    document_type = _extract_document_type(text)
    reference_year, reference_quarter, reference_period_label = _extract_temporal_fields(
        text,
        allow_inline_year=True,
    )
    if reference_year is None and reference_quarter is None and filename:
        filename_stem = re.split(r"[\\/]", filename)[-1].rsplit(".", 1)[0]
        filename_text = re.sub(r"_+", " ", filename_stem)
        reference_year, reference_quarter, reference_period_label = _extract_temporal_fields(
            filename_text,
            allow_inline_year=True,
        )
    entities = tuple(
        value
        for value in (
            f"project:{project_id}" if project_id else None,
            f"contract:{contract_id}" if contract_id else None,
            f"document_type:{document_type}" if document_type else None,
        )
        if value is not None
    )
    return ClaimScope(
        document_id=document_id,
        canonical_document_id=canonical_document_id,
        project_id=project_id,
        contract_id=contract_id,
        document_type=document_type,
        contract_type=document_type,
        subject_entities=entities,
        reference_year=reference_year,
        reference_quarter=reference_quarter,
        reference_period_label=reference_period_label,
        version_id=version_id,
    )


def merge_claim_scopes(
    primary: ClaimScope | None,
    fallback: ClaimScope | None,
) -> ClaimScope | None:
    """Fill missing persisted fields from content-derived fallback evidence."""
    if primary is None:
        return fallback
    if fallback is None:
        return primary
    return replace(
        primary,
        document_id=primary.document_id or fallback.document_id,
        canonical_document_id=primary.canonical_document_id or fallback.canonical_document_id,
        project_id=primary.project_id or fallback.project_id,
        contract_id=primary.contract_id or fallback.contract_id,
        document_type=primary.document_type or fallback.document_type,
        contract_type=primary.contract_type or fallback.contract_type,
        subject_entities=primary.subject_entities or fallback.subject_entities,
        effective_date=primary.effective_date or fallback.effective_date,
        reference_year=primary.reference_year or fallback.reference_year,
        reference_quarter=primary.reference_quarter or fallback.reference_quarter,
        reference_period_label=(primary.reference_period_label or fallback.reference_period_label),
        version_id=primary.version_id or fallback.version_id,
    )


def compare_claim_scopes(
    left: ClaimScope | None,
    right: ClaimScope | None,
) -> ScopeComparison:
    """Compare only explicit logical identifiers; upload IDs alone are neutral."""
    if left is None or right is None:
        return ScopeComparison.UNKNOWN_SCOPE
    for left_value, right_value in (
        (left.canonical_document_id, right.canonical_document_id),
        (left.project_id, right.project_id),
        (left.contract_id, right.contract_id),
    ):
        if (
            left_value
            and right_value
            and normalize_scope_value(left_value) != normalize_scope_value(right_value)
        ):
            return ScopeComparison.DIFFERENT_SCOPE

    if temporal_scopes_diverge(left, right):
        return ScopeComparison.TEMPORAL_DIVERGENCE

    same_evidence = any(
        left_value
        and right_value
        and normalize_scope_value(left_value) == normalize_scope_value(right_value)
        for left_value, right_value in (
            (left.canonical_document_id, right.canonical_document_id),
            (left.project_id, right.project_id),
            (left.contract_id, right.contract_id),
        )
    )
    return ScopeComparison.SAME_SCOPE if same_evidence else ScopeComparison.UNKNOWN_SCOPE


def scope_reason_codes(
    left: ClaimScope | None,
    right: ClaimScope | None,
) -> tuple[str, ...]:
    """Explain which explicit identifiers caused a scope decision."""
    comparison = compare_claim_scopes(left, right)
    if comparison is ScopeComparison.TEMPORAL_DIVERGENCE:
        reasons = ["temporal_period_difference"]
        if left and right and _reference_years_diverge(left, right):
            reasons.append("different_reference_year")
        if left and right and _quarters_diverge(left, right):
            reasons.append("different_reference_quarter")
        if left and right and temporal_gap_exceeds_threshold(left, right):
            reasons.append("effective_date_gap")
        return tuple(reasons)
    if comparison is not ScopeComparison.DIFFERENT_SCOPE:
        return ()
    reasons = ["different_claim_scope"]
    if left and right and _different(left.project_id, right.project_id):
        reasons.append("different_project_entity")
    if left and right and _different(left.contract_id, right.contract_id):
        reasons.append("different_contract_entity")
    return tuple(reasons)


def extract_temporal_scope_qualifiers(text: str) -> tuple[str, ...]:
    """Return explicit per-claim temporal anchors for conservative alignment."""
    year, quarter, period_label = _extract_temporal_fields(
        text,
        allow_inline_year=False,
    )
    qualifiers: list[str] = []
    if year:
        qualifiers.append(f"year:{year}")
    if quarter:
        qualifiers.append(f"quarter:{quarter}")
    if period_label and not period_label.startswith(("year:", "quarter:")):
        qualifiers.append(period_label)
    return tuple(qualifiers)


def has_explicit_reference_period(scope: ClaimScope | None) -> bool:
    """Whether a scope carries a source-explicit year, quarter, or period."""
    return bool(
        scope and (scope.reference_year or scope.reference_quarter or scope.reference_period_label)
    )


def temporal_scopes_diverge(
    left: ClaimScope | None,
    right: ClaimScope | None,
) -> bool:
    """Return true only for explicit non-overlapping periods or a large effective gap."""
    if left is None or right is None:
        return False
    if _reference_years_diverge(left, right) or _quarters_diverge(left, right):
        return True
    if _same_granularity_periods_diverge(left, right):
        return True
    return temporal_gap_exceeds_threshold(left, right)


def temporal_gap_exceeds_threshold(
    left: ClaimScope | None,
    right: ClaimScope | None,
    *,
    threshold_years: int = 1,
) -> bool:
    """Compare persisted effective dates using a calendar-year threshold."""
    if left is None or right is None or threshold_years < 1:
        return False
    left_date = _parse_effective_date(left.effective_date)
    right_date = _parse_effective_date(right.effective_date)
    if left_date is None or right_date is None:
        return False
    earlier, later = sorted((left_date, right_date))
    try:
        threshold = earlier.replace(year=earlier.year + threshold_years)
    except ValueError:
        # February 29 reaches its anniversary on February 28 in a non-leap year.
        threshold = earlier.replace(
            year=earlier.year + threshold_years,
            month=2,
            day=28,
        )
    return later >= threshold


def _different(left: str | None, right: str | None) -> bool:
    return bool(left and right and normalize_scope_value(left) != normalize_scope_value(right))


def _extract_temporal_fields(
    text: str,
    *,
    allow_inline_year: bool,
) -> tuple[str | None, str | None, str | None]:
    candidates: list[tuple[int, int, str | None, str | None, str | None]] = []

    for match in _YEAR_RANGE_PATTERN.finditer(text):
        start, end = match.group("start"), match.group("end")
        if int(start) > int(end):
            start, end = end, start
        candidates.append((match.start(), 0, f"{start}-{end}", None, f"period:{start}-{end}"))
    for match in _QUARTER_PATTERN.finditer(text):
        quarter = f"Q{match.group('quarter')}"
        year = match.group("year")
        label = f"quarter:{year}-{quarter}" if year else f"quarter:{quarter}"
        candidates.append((match.start(), 1, year, quarter, label))
    for match in _MONTH_PATTERN.finditer(text):
        year = match.group("year")
        month = int(match.group("month"))
        candidates.append((match.start(), 2, year, None, f"month:{year}-{month:02d}"))
    for match in _ENGLISH_MONTH_PATTERN.finditer(text):
        year = match.group("year")
        month = _ENGLISH_MONTHS[match.group("month").casefold()]
        candidates.append((match.start(), 2, year, None, f"month:{year}-{month:02d}"))
    for match in _YEAR_CONTEXT_PATTERN.finditer(text):
        year = match.group("year")
        candidates.append((match.start(), 3, year, None, f"year:{year}"))
    for match in _INLINE_REFERENCE_YEAR_PATTERN.finditer(text):
        year = match.group("year")
        candidates.append((match.start(), 4, year, None, f"year:{year}"))

    if allow_inline_year and not candidates:
        header_lines = [line.strip() for line in text[:4000].splitlines() if line.strip()][:6]
        for line_index, line in enumerate(header_lines):
            if (
                len(line) > 200
                or any(marker in line for marker in ".!?;")
                or _TITLE_SENTENCE_VERB_PATTERN.search(line)
            ):
                continue
            for match in _BARE_YEAR_PATTERN.finditer(line):
                year = match.group("year")
                candidates.append((line_index, 5, year, None, f"year:{year}"))

    if not candidates:
        return None, None, None
    _, _, selected_year, selected_quarter, selected_label = min(
        candidates,
        key=lambda item: (item[0], item[1]),
    )
    return selected_year, selected_quarter, selected_label


def _reference_years_diverge(left: ClaimScope, right: ClaimScope) -> bool:
    left_bounds = _year_bounds(left.reference_year)
    right_bounds = _year_bounds(right.reference_year)
    if left_bounds is None or right_bounds is None:
        return False
    return left_bounds[1] < right_bounds[0] or right_bounds[1] < left_bounds[0]


def _quarters_diverge(left: ClaimScope, right: ClaimScope) -> bool:
    if not left.reference_quarter or not right.reference_quarter:
        return False
    if left.reference_quarter.casefold() == right.reference_quarter.casefold():
        return False
    left_bounds = _year_bounds(left.reference_year)
    right_bounds = _year_bounds(right.reference_year)
    return left_bounds is None or right_bounds is None or left_bounds == right_bounds


def _same_granularity_periods_diverge(left: ClaimScope, right: ClaimScope) -> bool:
    left_label = left.reference_period_label
    right_label = right.reference_period_label
    if not left_label or not right_label or left_label.casefold() == right_label.casefold():
        return False
    left_kind = left_label.partition(":")[0].casefold()
    right_kind = right_label.partition(":")[0].casefold()
    return left_kind == right_kind and left_kind in {"month", "quarter"}


def _year_bounds(value: str | None) -> tuple[int, int] | None:
    if value is None:
        return None
    match = re.fullmatch(r"(?P<start>(?:19|20)\d{2})(?:-(?P<end>(?:19|20)\d{2}))?", value)
    if match is None:
        return None
    start = int(match.group("start"))
    end = int(match.group("end") or start)
    return min(start, end), max(start, end)


def _parse_effective_date(value: str | None) -> date | None:
    if value is None:
        return None
    normalized = value.strip()
    try:
        if re.fullmatch(_YEAR_TOKEN, normalized):
            return date(int(normalized), 1, 1)
        return date.fromisoformat(normalized[:10])
    except ValueError:
        return None


def _extract_project_id(text: str) -> str | None:
    definition = _PROJECT_DEFINITION_PATTERN.search(text)
    if definition is not None:
        return _confident_project_identifier(definition.group("value"))
    for pattern in _PROJECT_LABEL_PATTERNS:
        match = pattern.search(text)
        if match is not None:
            value = _confident_project_identifier(match.group("value"))
            if value:
                return value
    contextual = _PROJECT_CONTEXT_PATTERN.search(text)
    if contextual is not None:
        return _confident_project_identifier(
            contextual.group("value"),
            require_name_shape=True,
        )
    return None


def _extract_contract_id(text: str) -> str | None:
    for match in _CONTRACT_PATTERN.finditer(text[:12000]):
        value = match.group("value").strip()
        if not _PLACEHOLDER_PATTERN.fullmatch(value) and any(
            character.isdigit() for character in value
        ):
            return normalize_scope_value(value)
    return None


def _extract_document_type(text: str) -> str | None:
    # A document type must be declared by a title-like line near the beginning.
    # Merely mentioning a contract inside a report, policy, or disclaimer is not
    # sufficient evidence to classify the whole document as a contract.
    header_lines = [line.strip() for line in text[:4000].splitlines() if line.strip()][:12]
    for line in header_lines:
        if len(line) > 240:
            continue
        for name, pattern in _DOCUMENT_TYPES:
            if pattern.search(line):
                return name
    return None


def _confident_project_identifier(
    value: str,
    *,
    require_name_shape: bool = False,
) -> str | None:
    normalized = _clean_identifier(value)
    if normalized is None:
        return None
    if any(
        normalized == prefix or normalized.startswith(f"{prefix} ")
        for prefix in _AMBIGUOUS_PROJECT_PREFIXES
    ):
        return None
    if require_name_shape and not _looks_like_project_name(value):
        return None
    return normalized


def _looks_like_project_name(value: str) -> bool:
    words = re.findall(r"[^\W\d_][\wÀ-ỹ]*", value, re.UNICODE)
    return bool(words) and any(word[0].isupper() for word in words)


def _clean_identifier(value: str) -> str | None:
    normalized = normalize_scope_value(value)
    return normalized[:160] or None


__all__ = [
    "compare_claim_scopes",
    "extract_claim_scope",
    "extract_temporal_scope_qualifiers",
    "has_explicit_reference_period",
    "merge_claim_scopes",
    "normalize_scope_value",
    "scope_reason_codes",
    "temporal_gap_exceeds_threshold",
    "temporal_scopes_diverge",
]
