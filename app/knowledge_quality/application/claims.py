"""Deterministic, explainable claim extraction and conflict alignment."""

from __future__ import annotations

import re
from datetime import date
from decimal import Decimal, InvalidOperation
from difflib import SequenceMatcher
from functools import lru_cache

from app.knowledge_quality.application.scope import (
    compare_claim_scopes,
    extract_temporal_scope_qualifiers,
)
from app.knowledge_quality.domain.models import (
    ClaimConflict,
    ClaimKey,
    ClaimScope,
    ClaimValue,
    ExtractedClaim,
    NumericMention,
    NumericRole,
    PolicyModality,
    ScopeComparison,
)

MIN_CLAIM_ALIGNMENT = 0.58
MIN_VALIDATED_CLAIM_ALIGNMENT = 0.82

_WORD_PATTERN = re.compile(r"[^\W_]+", re.UNICODE)
_SENTENCE_PATTERN = re.compile(
    r"[^!?;\n]+?(?:(?<!\d)\.|\.(?!\d)|[!?;]+|(?=\n)|$)",
    re.UNICODE,
)
_CONNECTOR_PATTERN = re.compile(
    r"\s+(?:and|but|while|whereas|và|nhưng|trong\s+khi)\s+",
    re.IGNORECASE | re.UNICODE,
)
_ACTION_PATTERN = re.compile(
    (
        r"\b(?:allows?|receives?|applies?|lasts?|provides?|requires?|"
        r"is|are|was|were|has|have|work|works|submit|submits|"
        r"cho\s+phép|áp\s+dụng|kéo\s+dài|yêu\s+cầu|là|có|làm\s+việc|nộp)\b"
    ),
    re.IGNORECASE | re.UNICODE,
)

_PROHIBITED_PATTERN = re.compile(
    (
        r"\b(?:may|must|shall)\s+not\b|"
        r"\b(?:is|are|be)?\s*not\s+(?:permitted|allowed)\b|"
        r"\b(?:(?:is|are|be)\s+)?(?:prohibited|forbidden)"
        r"(?:\s+from)?\b|"
        r"\b(?:không|khong)\s+(?:được|duoc)\b|"
        r"\b(?:bị\s+)?(?:cấm|cam)\b"
    ),
    re.IGNORECASE | re.UNICODE,
)
_REQUIRED_PATTERN = re.compile(
    (
        r"\b(?:must|shall|required(?:\s+to)?|has\s+to|have\s+to|needs?\s+to)\b|"
        r"\b(?:phải|phai|bắt\s+buộc|bat\s+buoc|cần\s+phải|can\s+phai)\b"
    ),
    re.IGNORECASE | re.UNICODE,
)
_PERMITTED_PATTERN = re.compile(
    (
        r"\b(?:may|can)\b|"
        r"\b(?:(?:is|are|be)\s+)?(?:permitted|allowed)(?:\s+to)?\b|"
        r"\b(?:có\s+thể|co\s+the|được(?:\s+phép)?|duoc(?:\s+phep)?)\b"
    ),
    re.IGNORECASE | re.UNICODE,
)
_NEGATION_PATTERN = re.compile(
    r"\b(?:not|no|never|without|không|khong|chưa|chua|chẳng|chang)\b",
    re.IGNORECASE | re.UNICODE,
)

_STRUCTURAL_REFERENCE_PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = (
    (
        "page_number",
        re.compile(
            r"\b(?:trang|page)\s+(?:\d+(?:[.,]\d+)*)"
            r"(?:\s*(?:trên|tren|of|/)\s*\d+(?:[.,]\d+)*)?",
            re.IGNORECASE | re.UNICODE,
        ),
    ),
    (
        "article_number",
        re.compile(
            r"\b(?:điều|dieu|article)\s+\d+(?:[.,]\d+)*(?:\s*\([a-z0-9]+\))?",
            re.IGNORECASE | re.UNICODE,
        ),
    ),
    (
        "clause_number",
        re.compile(
            r"\b(?:(?<!tài\s)khoản|(?<!tai\s)khoan|clause)\s+\d+(?:[.,]\d+)*",
            re.IGNORECASE | re.UNICODE,
        ),
    ),
    (
        "point_number",
        re.compile(
            r"\b(?:điểm|diem|point)\s+(?:[a-z]|\d+(?:[.,]\d+)*)",
            re.IGNORECASE | re.UNICODE,
        ),
    ),
    (
        "section_number",
        re.compile(
            r"\b(?:mục|muc|section)\s+\d+(?:[.,]\d+)*",
            re.IGNORECASE | re.UNICODE,
        ),
    ),
    (
        "chapter_number",
        re.compile(
            r"\b(?:chương|chuong|chapter|phần|phan|part)\s+(?:[ivxlcdm]+|\d+)\b",
            re.IGNORECASE | re.UNICODE,
        ),
    ),
    (
        "appendix_number",
        re.compile(
            r"\b(?:phụ\s+lục|phu\s+luc|appendix)\s+\d+(?:[.,]\d+)*",
            re.IGNORECASE | re.UNICODE,
        ),
    ),
    (
        "table_or_figure_number",
        re.compile(
            r"\b(?:bảng|bang|table|hình|hinh|figure)\s+\d+(?:[.,]\d+)*",
            re.IGNORECASE | re.UNICODE,
        ),
    ),
)
_IDENTIFIER_CONTEXT_PATTERN = re.compile(
    r"\b(?:mã|ma|code|identifier|id|số\s+hiệu|so\s+hieu)\s*[:#\-]?\s*$",
    re.IGNORECASE | re.UNICODE,
)
_PREDICATE_PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("pay", re.compile(r"\b(?:thanh\s+toán|thanh\s+toan|pay|pays|payment)\b", re.I)),
    ("apply", re.compile(r"\b(?:áp\s+dụng|ap\s+dung|apply|applies)\b", re.I)),
    ("submit", re.compile(r"\b(?:nộp|nop|submit|submits)\b", re.I)),
    ("provide", re.compile(r"\b(?:cung\s+cấp|cung\s+cap|provide|provides)\b", re.I)),
    ("transfer", re.compile(r"\b(?:chuyển\s+nhượng|chuyen\s+nhuong|transfer)\b", re.I)),
    ("allow", re.compile(r"\b(?:cho\s+phép|cho\s+phep|allow|allows)\b", re.I)),
    ("last", re.compile(r"\b(?:kéo\s+dài|keo\s+dai|last|lasts)\b", re.I)),
    ("work", re.compile(r"\b(?:làm\s+việc|lam\s+viec|work|works)\b", re.I)),
    ("be", re.compile(r"\b(?:là|la|is|are|was|were)\b", re.I)),
    ("have", re.compile(r"\b(?:có|co|has|have)\b", re.I)),
)

_NUMERIC_DATE_PATTERN = re.compile(r"(?<!\d)(?P<value>\d{1,4}[/-]\d{1,2}[/-]\d{1,4})(?!\d)")
_VIETNAMESE_DATE_PATTERN = re.compile(
    (
        r"\bngày\s+(?P<day>\d{1,2})\s+tháng\s+(?P<month>\d{1,2})"
        r"\s+năm\s+(?P<year>\d{4})\b"
    ),
    re.IGNORECASE | re.UNICODE,
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
_ENGLISH_MONTH_PATTERN = "|".join(_ENGLISH_MONTHS)
_ENGLISH_DATE_DAY_FIRST_PATTERN = re.compile(
    (
        rf"\b(?P<day>\d{{1,2}})\s+(?P<month>{_ENGLISH_MONTH_PATTERN})"
        r"\s*,?\s*(?P<year>\d{4})\b"
    ),
    re.IGNORECASE,
)
_ENGLISH_DATE_MONTH_FIRST_PATTERN = re.compile(
    (
        rf"\b(?P<month>{_ENGLISH_MONTH_PATTERN})\s+(?P<day>\d{{1,2}})"
        r"\s*,?\s*(?P<year>\d{4})\b"
    ),
    re.IGNORECASE,
)

_NUMBER_BODY = (
    r"[+-]?(?:"
    r"\d{1,3}(?:(?:[.,]\d{3})+|(?:\s\d{3})+)(?:[.,]\d+)?"
    r"|\d+(?:[.,]\d+)?"
    r")"
)
_MAGNITUDE_BODY = (
    r"nghìn\s+tỷ|nghin\s+ty|trillion|billion|million|thousand|"
    r"triệu|trieu|tỷ|ty|tỉ|ti|nghìn|nghin|ngàn|ngan"
)
_UNIT_BODY = (
    r"phần\s+trăm|phan\s+tram|percent(?:age)?|%"
    r"|vnd|vnđ|đồng|dong|usd|dollars?"
    r"|gigabytes?|gb|megabytes?|mb|kilobytes?|kb"
    r"|square\s+met(?:er|re)s?|m²|m2|mét\s+vuông|met\s+vuong"
    r"|kilomet(?:er|re)s?|km|centimet(?:er|re)s?|cm|millimet(?:er|re)s?|mm"
    r"|met(?:er|re)s?|m|kilograms?|kg|grams?|g"
    r"|days?|ngày|ngay|months?|tháng|thang|years?|năm|nam"
)
_QUANTITY_PATTERN = re.compile(
    (
        rf"(?<!\w)(?:(?P<prefix>usd|vnd|vnđ|\$)\s*)?"
        rf"(?P<number>{_NUMBER_BODY})"
        rf"(?:\s*(?P<magnitude>{_MAGNITUDE_BODY}))?"
        rf"(?:\s*(?P<unit>{_UNIT_BODY}))?(?!\w)"
    ),
    re.IGNORECASE | re.UNICODE,
)

_MAGNITUDES: dict[str, tuple[str, Decimal]] = {
    "thousand": ("thousand", Decimal("1000")),
    "nghìn": ("thousand", Decimal("1000")),
    "nghin": ("thousand", Decimal("1000")),
    "ngàn": ("thousand", Decimal("1000")),
    "ngan": ("thousand", Decimal("1000")),
    "million": ("million", Decimal("1000000")),
    "triệu": ("million", Decimal("1000000")),
    "trieu": ("million", Decimal("1000000")),
    "billion": ("billion", Decimal("1000000000")),
    "tỷ": ("billion", Decimal("1000000000")),
    "ty": ("billion", Decimal("1000000000")),
    "tỉ": ("billion", Decimal("1000000000")),
    "ti": ("billion", Decimal("1000000000")),
    "trillion": ("trillion", Decimal("1000000000000")),
    "nghìn tỷ": ("trillion", Decimal("1000000000000")),
    "nghin ty": ("trillion", Decimal("1000000000000")),
}
_UNITS: dict[str, tuple[str, Decimal]] = {
    "%": ("percent", Decimal("1")),
    "percent": ("percent", Decimal("1")),
    "percentage": ("percent", Decimal("1")),
    "phần trăm": ("percent", Decimal("1")),
    "phan tram": ("percent", Decimal("1")),
    "vnd": ("vnd", Decimal("1")),
    "vnđ": ("vnd", Decimal("1")),
    "đồng": ("vnd", Decimal("1")),
    "dong": ("vnd", Decimal("1")),
    "usd": ("usd", Decimal("1")),
    "$": ("usd", Decimal("1")),
    "dollar": ("usd", Decimal("1")),
    "dollars": ("usd", Decimal("1")),
    "kilobyte": ("byte", Decimal("1000")),
    "kilobytes": ("byte", Decimal("1000")),
    "kb": ("byte", Decimal("1000")),
    "megabyte": ("byte", Decimal("1000000")),
    "megabytes": ("byte", Decimal("1000000")),
    "mb": ("byte", Decimal("1000000")),
    "gigabyte": ("byte", Decimal("1000000000")),
    "gigabytes": ("byte", Decimal("1000000000")),
    "gb": ("byte", Decimal("1000000000")),
    "square meter": ("m2", Decimal("1")),
    "square meters": ("m2", Decimal("1")),
    "square metre": ("m2", Decimal("1")),
    "square metres": ("m2", Decimal("1")),
    "m²": ("m2", Decimal("1")),
    "m2": ("m2", Decimal("1")),
    "mét vuông": ("m2", Decimal("1")),
    "met vuong": ("m2", Decimal("1")),
    "day": ("day", Decimal("1")),
    "days": ("day", Decimal("1")),
    "ngày": ("day", Decimal("1")),
    "ngay": ("day", Decimal("1")),
    "month": ("month", Decimal("1")),
    "months": ("month", Decimal("1")),
    "tháng": ("month", Decimal("1")),
    "thang": ("month", Decimal("1")),
    "year": ("year", Decimal("1")),
    "years": ("year", Decimal("1")),
    "năm": ("year", Decimal("1")),
    "nam": ("year", Decimal("1")),
    "kilometer": ("m", Decimal("1000")),
    "kilometers": ("m", Decimal("1000")),
    "kilometre": ("m", Decimal("1000")),
    "kilometres": ("m", Decimal("1000")),
    "km": ("m", Decimal("1000")),
    "centimeter": ("m", Decimal("0.01")),
    "centimeters": ("m", Decimal("0.01")),
    "centimetre": ("m", Decimal("0.01")),
    "centimetres": ("m", Decimal("0.01")),
    "cm": ("m", Decimal("0.01")),
    "millimeter": ("m", Decimal("0.001")),
    "millimeters": ("m", Decimal("0.001")),
    "millimetre": ("m", Decimal("0.001")),
    "millimetres": ("m", Decimal("0.001")),
    "mm": ("m", Decimal("0.001")),
    "meter": ("m", Decimal("1")),
    "meters": ("m", Decimal("1")),
    "metre": ("m", Decimal("1")),
    "metres": ("m", Decimal("1")),
    "m": ("m", Decimal("1")),
    "kilogram": ("kg", Decimal("1")),
    "kilograms": ("kg", Decimal("1")),
    "kg": ("kg", Decimal("1")),
    "gram": ("kg", Decimal("0.001")),
    "grams": ("kg", Decimal("0.001")),
    "g": ("kg", Decimal("0.001")),
}

_REASON_ORDER = (
    "semantic_quantity_mismatch",
    "unit_value_mismatch",
    "date_value_mismatch",
    "negation_mismatch",
    "policy_modality_mismatch",
)


@lru_cache(maxsize=2048)
def extract_claims(text: str) -> tuple[ExtractedClaim, ...]:
    """Extract sentence/clause claims with absolute spans and normalized values."""
    claims: list[ExtractedClaim] = []
    for sentence_match in _SENTENCE_PATTERN.finditer(text):
        sentence_start, sentence_end = _trim_span(
            text,
            sentence_match.start(),
            sentence_match.end(),
        )
        if sentence_start >= sentence_end:
            continue
        for claim_start, claim_end in _split_clause_span(text, sentence_start, sentence_end):
            claim_text = text[claim_start:claim_end]
            date_values = _extract_dates(claim_text, base_offset=claim_start)
            quantity_values = _extract_quantities(
                claim_text,
                base_offset=claim_start,
                excluded_spans=tuple((value.span_start, value.span_end) for value in date_values),
            )
            modality = _detect_modality(claim_text)
            negated = _NEGATION_PATTERN.search(claim_text) is not None
            values = tuple(
                sorted(
                    (*date_values, *quantity_values),
                    key=lambda value: (value.span_start, value.span_end),
                )
            )
            comparison_text = normalize_claim_comparison_text(claim_text)
            alignment_key = _alignment_key(
                claim_text,
                claim_start=claim_start,
                values=values,
            )
            claims.append(
                ExtractedClaim(
                    text=claim_text,
                    alignment_key=alignment_key,
                    span_start=claim_start,
                    span_end=claim_end,
                    modality=modality,
                    negated=negated,
                    values=values,
                    claim_key=_extract_claim_key(
                        comparison_text,
                        alignment_key,
                        values,
                        scope_qualifiers=extract_temporal_scope_qualifiers(claim_text),
                    ),
                    comparison_text=comparison_text,
                )
            )
    return tuple(claims)


def detect_claim_conflicts(
    left: str,
    right: str,
    *,
    left_scope: ClaimScope | None = None,
    right_scope: ClaimScope | None = None,
) -> tuple[ClaimConflict, ...]:
    """Align claims one-to-one and report only explicit critical differences."""
    scope_comparison = compare_claim_scopes(left_scope, right_scope)
    if scope_comparison in {
        ScopeComparison.DIFFERENT_SCOPE,
        ScopeComparison.TEMPORAL_DIVERGENCE,
    }:
        return ()
    left_claims = extract_claims(left)
    right_claims = extract_claims(right)
    conflicts: list[ClaimConflict] = []
    for left_claim, right_claim, alignment_score in _align_claims(
        left_claims,
        right_claims,
    ):
        if not _claim_keys_align(
            left_claim,
            right_claim,
            alignment_score=alignment_score,
            scope_comparison=scope_comparison,
        ):
            continue
        reasons = _claim_difference_reasons(left_claim, right_claim)
        if reasons:
            conflicts.append(
                ClaimConflict(
                    left_claim=left_claim,
                    right_claim=right_claim,
                    alignment_score=alignment_score,
                    reason_codes=reasons,
                )
            )
    return tuple(conflicts)


def classify_numeric_mentions(text: str) -> tuple[NumericMention, ...]:
    """Classify structural references separately from semantic quantities."""
    structural = _structural_reference_spans(text)
    mentions: list[NumericMention] = [
        NumericMention(
            raw_text=text[start:end],
            normalized_value=normalized_number_literal(text[start:end]),
            unit=None,
            role=NumericRole.STRUCTURAL_REFERENCE,
            span_start=start,
            span_end=end,
            context=_mention_context(text, start, end),
            reference_type=reference_type,
        )
        for start, end, reference_type in structural
    ]
    date_values = _extract_dates(text, base_offset=0)
    occupied = [(start, end) for start, end, _ in structural]
    occupied.extend((value.span_start, value.span_end) for value in date_values)
    mentions.extend(
        NumericMention(
            raw_text=value.raw_text,
            normalized_value=value.normalized_value,
            unit="date",
            role=NumericRole.SEMANTIC_QUANTITY,
            span_start=value.span_start,
            span_end=value.span_end,
            context=_mention_context(text, value.span_start, value.span_end),
        )
        for value in date_values
    )
    for match in _QUANTITY_PATTERN.finditer(text):
        if _overlaps(match.start(), match.end(), occupied):
            continue
        try:
            normalized = normalized_number_literal(match.group("number"))
        except (InvalidOperation, ValueError):
            continue
        raw_unit = _normalized_phrase(match.group("unit") or match.group("prefix"))
        unit = _UNITS[raw_unit][0] if raw_unit in _UNITS else None
        prefix = text[max(0, match.start() - 32) : match.start()]
        role = (
            NumericRole.IDENTIFIER
            if unit is None and _IDENTIFIER_CONTEXT_PATTERN.search(prefix)
            else NumericRole.SEMANTIC_QUANTITY
        )
        mentions.append(
            NumericMention(
                raw_text=match.group(0),
                normalized_value=normalized,
                unit=unit,
                role=role,
                span_start=match.start(),
                span_end=match.end(),
                context=_mention_context(text, match.start(), match.end()),
            )
        )
    return tuple(
        sorted(mentions, key=lambda item: (item.span_start, item.span_end, item.role.value))
    )


@lru_cache(maxsize=4096)
def normalize_claim_comparison_text(text: str) -> str:
    """Remove structural numbering while preserving semantic values and entities."""
    projected = list(text)
    for start, end, _ in _structural_reference_spans(text):
        for index in range(start, end):
            projected[index] = " "
    return " ".join("".join(projected).split()).strip(" .;:-")


def normalized_number_literal(raw: str) -> str:
    """Normalize common decimal/thousands notation without assuming one locale."""
    try:
        return _decimal_text(_parse_decimal(raw))
    except InvalidOperation:
        return raw.strip().casefold()


def normalized_dates(text: str) -> tuple[str, ...]:
    """Return unique normalized ISO dates found in text."""
    return tuple(sorted({value.normalized_value for value in _extract_dates(text, base_offset=0)}))


def normalized_quantities(text: str) -> tuple[str, ...]:
    """Return normalized non-date quantities across all extracted claims."""
    return tuple(
        sorted(
            {
                value.normalized_value
                for claim in extract_claims(text)
                for value in claim.values
                if value.kind == "quantity"
            }
        )
    )


def _split_clause_span(text: str, start: int, end: int) -> tuple[tuple[int, int], ...]:
    segment = text[start:end]
    for connector in _CONNECTOR_PATTERN.finditer(segment):
        left_start, left_end = _trim_span(text, start, start + connector.start())
        right_start, right_end = _trim_span(text, start + connector.end(), end)
        if (
            left_start < left_end
            and right_start < right_end
            and _looks_independent(text[left_start:left_end])
            and _looks_independent(text[right_start:right_end])
        ):
            return (
                *_split_clause_span(text, left_start, left_end),
                *_split_clause_span(text, right_start, right_end),
            )
    trimmed_start, trimmed_end = _trim_span(text, start, end)
    return ((trimmed_start, trimmed_end),) if trimmed_start < trimmed_end else ()


def _looks_independent(text: str) -> bool:
    words = tuple(match.group(0) for match in _WORD_PATTERN.finditer(text))
    return len(words) >= 2 and (
        _detect_modality(text) is not None or _ACTION_PATTERN.search(text) is not None
    )


def _trim_span(text: str, start: int, end: int) -> tuple[int, int]:
    while start < end and (text[start].isspace() or text[start] in ".!?;"):
        start += 1
    while end > start and (text[end - 1].isspace() or text[end - 1] in ".!?;"):
        end -= 1
    return start, end


def _detect_modality(text: str) -> PolicyModality | None:
    if _PROHIBITED_PATTERN.search(text):
        return PolicyModality.PROHIBITED
    if _REQUIRED_PATTERN.search(text):
        return PolicyModality.REQUIRED
    if _PERMITTED_PATTERN.search(text):
        return PolicyModality.PERMITTED
    return None


def _extract_dates(text: str, *, base_offset: int) -> tuple[ClaimValue, ...]:
    values: list[ClaimValue] = []
    occupied: list[tuple[int, int]] = []
    patterns = (
        (_VIETNAMESE_DATE_PATTERN, _date_from_named_parts),
        (_ENGLISH_DATE_DAY_FIRST_PATTERN, _date_from_english_parts),
        (_ENGLISH_DATE_MONTH_FIRST_PATTERN, _date_from_english_parts),
        (_NUMERIC_DATE_PATTERN, _date_from_numeric),
    )
    for pattern, parser in patterns:
        for match in pattern.finditer(text):
            if _overlaps(match.start(), match.end(), occupied):
                continue
            normalized = parser(match)
            if normalized is None:
                continue
            occupied.append((match.start(), match.end()))
            values.append(
                ClaimValue(
                    kind="date",
                    raw_text=match.group(0),
                    normalized_value=normalized,
                    unit=None,
                    magnitude=None,
                    span_start=base_offset + match.start(),
                    span_end=base_offset + match.end(),
                )
            )
    return tuple(sorted(values, key=lambda value: value.span_start))


def _date_from_named_parts(match: re.Match[str]) -> str | None:
    return _validated_date(
        year=int(match.group("year")),
        month=int(match.group("month")),
        day=int(match.group("day")),
    )


def _date_from_english_parts(match: re.Match[str]) -> str | None:
    return _validated_date(
        year=int(match.group("year")),
        month=_ENGLISH_MONTHS[match.group("month").casefold()],
        day=int(match.group("day")),
    )


def _date_from_numeric(match: re.Match[str]) -> str | None:
    raw = match.group("value")
    parts = re.split(r"[/-]", raw)
    if len(parts[0]) == 4:
        year, month, day = (int(part) for part in parts)
    else:
        day, month, year = (int(part) for part in parts)
    if year < 100:
        year += 2000 if year <= 69 else 1900
    return _validated_date(year=year, month=month, day=day)


def _validated_date(*, year: int, month: int, day: int) -> str | None:
    try:
        return date(year, month, day).isoformat()
    except ValueError:
        return None


def _extract_quantities(
    text: str,
    *,
    base_offset: int,
    excluded_spans: tuple[tuple[int, int], ...],
) -> tuple[ClaimValue, ...]:
    values: list[ClaimValue] = []
    local_excluded = tuple(
        (span_start - base_offset, span_end - base_offset)
        for span_start, span_end in excluded_spans
    )
    structural_spans = tuple(
        (span_start, span_end) for span_start, span_end, _ in _structural_reference_spans(text)
    )
    for match in _QUANTITY_PATTERN.finditer(text):
        if _overlaps(match.start(), match.end(), (*local_excluded, *structural_spans)):
            continue
        try:
            numeric_value = _parse_decimal(match.group("number"))
        except InvalidOperation:
            continue
        raw_magnitude = _normalized_phrase(match.group("magnitude"))
        magnitude_name: str | None = None
        magnitude_factor = Decimal("1")
        if raw_magnitude is not None:
            magnitude_name, magnitude_factor = _MAGNITUDES[raw_magnitude]

        raw_unit = _normalized_phrase(match.group("unit") or match.group("prefix"))
        unit: str | None = "count" if magnitude_name is not None else None
        unit_factor = Decimal("1")
        if raw_unit is not None:
            unit, unit_factor = _UNITS[raw_unit]

        prefix = text[max(0, match.start() - 32) : match.start()]
        if unit is None and _IDENTIFIER_CONTEXT_PATTERN.search(prefix):
            continue

        values.append(
            ClaimValue(
                kind="quantity",
                raw_text=match.group(0),
                normalized_value=_decimal_text(numeric_value * magnitude_factor * unit_factor),
                unit=unit,
                magnitude=magnitude_name,
                span_start=base_offset + match.start(),
                span_end=base_offset + match.end(),
            )
        )
    return tuple(values)


def _parse_decimal(raw: str) -> Decimal:
    value = re.sub(r"\s+", "", raw.strip().rstrip("%"))
    sign = ""
    if value[:1] in {"+", "-"}:
        sign, value = value[0], value[1:]
    if not value or not any(character.isdigit() for character in value):
        raise InvalidOperation

    comma_count = value.count(",")
    dot_count = value.count(".")
    if comma_count and dot_count:
        decimal_separator = "," if value.rfind(",") > value.rfind(".") else "."
        grouping_separator = "." if decimal_separator == "," else ","
        value = value.replace(grouping_separator, "")
        value = value.replace(decimal_separator, ".")
    elif comma_count or dot_count:
        separator = "," if comma_count else "."
        pieces = value.split(separator)
        is_grouped_integer = (len(pieces) > 2 and all(len(piece) == 3 for piece in pieces[1:])) or (
            len(pieces) == 2
            and len(pieces[1]) == 3
            and pieces[0] != "0"
            and 1 <= len(pieces[0]) <= 3
        )
        value = "".join(pieces) if is_grouped_integer else ".".join(pieces)
    return Decimal(sign + value)


def _decimal_text(value: Decimal) -> str:
    if value == 0:
        return "0"
    rendered = format(value.normalize(), "f")
    if "." in rendered:
        rendered = rendered.rstrip("0").rstrip(".")
    return rendered


def _normalized_phrase(value: str | None) -> str | None:
    if value is None:
        return None
    return " ".join(value.casefold().split())


def _alignment_key(
    text: str,
    *,
    claim_start: int,
    values: tuple[ClaimValue, ...],
) -> str:
    masked = list(text.casefold())
    spans = [(value.span_start - claim_start, value.span_end - claim_start) for value in values]
    spans.extend((start, end) for start, end, _ in _structural_reference_spans(text))
    for pattern in (
        _PROHIBITED_PATTERN,
        _REQUIRED_PATTERN,
        _PERMITTED_PATTERN,
        _NEGATION_PATTERN,
    ):
        spans.extend((match.start(), match.end()) for match in pattern.finditer(text))
    for span_start, span_end in spans:
        for index in range(max(0, span_start), min(len(masked), span_end)):
            masked[index] = " "
    return " ".join(
        _alignment_token(match.group(0)) for match in _WORD_PATTERN.finditer("".join(masked))
    )


def _alignment_token(token: str) -> str:
    """Apply tiny, deterministic morphology only to alignment keys."""
    if len(token) > 5 and token.endswith("ing"):
        return token[:-3]
    return token


def _extract_claim_key(
    comparison_text: str,
    alignment_key: str,
    values: tuple[ClaimValue, ...],
    *,
    scope_qualifiers: tuple[str, ...],
) -> ClaimKey:
    predicate: str | None = None
    predicate_span: tuple[int, int] | None = None
    for canonical, pattern in _PREDICATE_PATTERNS:
        match = pattern.search(comparison_text)
        if match is not None:
            predicate = canonical
            predicate_span = match.span()
            break

    key_tokens = tuple(_WORD_PATTERN.findall(alignment_key))
    if predicate_span is None:
        subject_tokens = key_tokens[:8]
        attribute_tokens = key_tokens[8:20]
    else:
        subject_tokens = tuple(
            _WORD_PATTERN.findall(comparison_text[: predicate_span[0]].casefold())
        )
        attribute_tokens = tuple(
            _WORD_PATTERN.findall(comparison_text[predicate_span[1] :].casefold())
        )
    subject = " ".join(subject_tokens[-8:]) or None
    attribute = " ".join(attribute_tokens[:12]) or None
    units = {value.unit for value in values if value.kind == "quantity" and value.unit is not None}
    unit_family = next(iter(units)) if len(units) == 1 else None
    object_type = _object_type(comparison_text)
    return ClaimKey(
        subject=subject,
        predicate=predicate,
        attribute=attribute,
        object_type=object_type,
        unit_family=unit_family,
        scope_qualifiers=scope_qualifiers,
    )


def _object_type(text: str) -> str | None:
    normalized = text.casefold()
    for object_type, pattern in (
        ("commercial_area", r"\b(?:diện\s+tích\s+thương\s+mại|khu\s+tm|dttm)\b"),
        ("housing", r"\b(?:nhà\s+ở|khu\s+nhà\s+ở|housing)\b"),
    ):
        if re.search(pattern, normalized, re.UNICODE):
            return object_type
    return None


def _claim_keys_align(
    left: ExtractedClaim,
    right: ExtractedClaim,
    *,
    alignment_score: float,
    scope_comparison: ScopeComparison,
) -> bool:
    if alignment_score < MIN_VALIDATED_CLAIM_ALIGNMENT:
        return False
    left_key, right_key = left.claim_key, right.claim_key
    if (
        left_key is not None
        and right_key is not None
        and left_key.scope_qualifiers
        and right_key.scope_qualifiers
        and left_key.scope_qualifiers != right_key.scope_qualifiers
    ):
        return False
    if left.alignment_key and left.alignment_key == right.alignment_key:
        return True
    if left_key is None or right_key is None:
        return False
    if (
        left_key.object_type
        and right_key.object_type
        and left_key.object_type != right_key.object_type
    ):
        return False
    if (
        left_key.unit_family
        and right_key.unit_family
        and left_key.unit_family != right_key.unit_family
    ):
        return False
    if not left_key.subject or left_key.subject != right_key.subject:
        return False
    if not left_key.predicate or left_key.predicate != right_key.predicate:
        return False
    return scope_comparison is ScopeComparison.SAME_SCOPE or alignment_score >= 0.94


def _align_claims(
    left_claims: tuple[ExtractedClaim, ...],
    right_claims: tuple[ExtractedClaim, ...],
) -> tuple[tuple[ExtractedClaim, ExtractedClaim, float], ...]:
    candidates = [
        (_claim_similarity(left, right), left_index, right_index)
        for left_index, left in enumerate(left_claims)
        for right_index, right in enumerate(right_claims)
    ]
    candidates.sort(key=lambda item: (-item[0], item[1], item[2]))
    selected_left: set[int] = set()
    selected_right: set[int] = set()
    alignments: list[tuple[ExtractedClaim, ExtractedClaim, float]] = []
    for score, left_index, right_index in candidates:
        if score < MIN_CLAIM_ALIGNMENT:
            break
        if left_index in selected_left or right_index in selected_right:
            continue
        selected_left.add(left_index)
        selected_right.add(right_index)
        alignments.append((left_claims[left_index], right_claims[right_index], score))
    alignments.sort(key=lambda item: (item[0].span_start, item[1].span_start))
    return tuple(alignments)


def _claim_similarity(left: ExtractedClaim, right: ExtractedClaim) -> float:
    if left.alignment_key == right.alignment_key and left.alignment_key:
        return 1.0
    left_tokens = tuple(_WORD_PATTERN.findall(left.alignment_key))
    right_tokens = tuple(_WORD_PATTERN.findall(right.alignment_key))
    if not left_tokens or not right_tokens:
        return 0.0
    left_set, right_set = set(left_tokens), set(right_tokens)
    union = left_set | right_set
    jaccard = len(left_set & right_set) / len(union) if union else 0.0
    containment = len(left_set & right_set) / min(len(left_set), len(right_set))
    sequence = SequenceMatcher(None, left_tokens, right_tokens, autojunk=False).ratio()
    return max(jaccard, sequence, 0.9 * containment)


def _claim_difference_reasons(
    left: ExtractedClaim,
    right: ExtractedClaim,
) -> tuple[str, ...]:
    reasons: set[str] = set()
    left_quantities = _values_of_kind(left, "quantity")
    right_quantities = _values_of_kind(right, "quantity")
    if bool(left_quantities) != bool(right_quantities):
        reasons.add("semantic_quantity_mismatch")
    elif left_quantities and right_quantities:
        left_numbers = tuple(value.normalized_value for value in left_quantities)
        right_numbers = tuple(value.normalized_value for value in right_quantities)
        if left_numbers != right_numbers:
            reasons.add("semantic_quantity_mismatch")
        left_units = tuple((value.unit, value.magnitude) for value in left_quantities)
        right_units = tuple((value.unit, value.magnitude) for value in right_quantities)
        if left_units != right_units:
            reasons.add("unit_value_mismatch")

    left_dates = tuple(value.normalized_value for value in _values_of_kind(left, "date"))
    right_dates = tuple(value.normalized_value for value in _values_of_kind(right, "date"))
    if left_dates != right_dates:
        reasons.add("date_value_mismatch")

    equivalent_prohibition = (
        left.modality is PolicyModality.PROHIBITED and right.modality is PolicyModality.PROHIBITED
    )
    if left.negated != right.negated and not equivalent_prohibition:
        reasons.add("negation_mismatch")
    if (
        left.modality is not None
        and right.modality is not None
        and left.modality is not right.modality
    ):
        reasons.add("policy_modality_mismatch")
    return tuple(reason for reason in _REASON_ORDER if reason in reasons)


def _values_of_kind(claim: ExtractedClaim, kind: str) -> tuple[ClaimValue, ...]:
    return tuple(value for value in claim.values if value.kind == kind)


@lru_cache(maxsize=4096)
def _structural_reference_spans(text: str) -> tuple[tuple[int, int, str], ...]:
    candidates: list[tuple[int, int, str]] = []
    for reference_type, pattern in _STRUCTURAL_REFERENCE_PATTERNS:
        candidates.extend(
            (match.start(), match.end(), reference_type) for match in pattern.finditer(text)
        )
    candidates.sort(key=lambda item: (item[0], -(item[1] - item[0]), item[2]))
    selected: list[tuple[int, int, str]] = []
    for candidate in candidates:
        if any(candidate[0] < end and candidate[1] > start for start, end, _ in selected):
            continue
        selected.append(candidate)
    return tuple(sorted(selected, key=lambda item: item[0]))


def _mention_context(text: str, start: int, end: int) -> str:
    return " ".join(text[max(0, start - 40) : min(len(text), end + 40)].split())


def _overlaps(
    start: int, end: int, spans: list[tuple[int, int]] | tuple[tuple[int, int], ...]
) -> bool:
    return any(start < span_end and end > span_start for span_start, span_end in spans)


__all__ = [
    "MIN_CLAIM_ALIGNMENT",
    "MIN_VALIDATED_CLAIM_ALIGNMENT",
    "classify_numeric_mentions",
    "detect_claim_conflicts",
    "extract_claims",
    "normalize_claim_comparison_text",
    "normalized_dates",
    "normalized_number_literal",
    "normalized_quantities",
]
