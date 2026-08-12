"""Deterministic query semantics needed by relation-aware RAG policy."""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass
from datetime import date
from enum import StrEnum

QUERY_POLICY_VERSION = "p5-query-context-v1"


class QueryIntent(StrEnum):
    DEFAULT_FACT = "DEFAULT_FACT"
    CURRENT_FACT = "CURRENT_FACT"
    HISTORICAL_FACT = "HISTORICAL_FACT"
    TEMPORAL_COMPARISON = "TEMPORAL_COMPARISON"
    VERSION_COMPARISON = "VERSION_COMPARISON"
    CONFLICT_CHECK = "CONFLICT_CHECK"
    SOURCE_COMPARISON = "SOURCE_COMPARISON"


@dataclass(frozen=True, slots=True)
class QueryContext:
    raw_query: str
    normalized_query: str
    owner_id: str
    notebook_id: str | None
    intent: QueryIntent
    reference_years: tuple[int, ...] = ()
    quarter: tuple[int, int] | None = None
    reference_date: date | None = None
    period_range: tuple[int, int] | None = None
    entity_terms: tuple[str, ...] = ()
    predicate_terms: tuple[str, ...] = ()
    qualifier_terms: tuple[str, ...] = ()
    comparison_requested: bool = False
    current_requested: bool = False
    historical_requested: bool = False
    conflict_requested: bool = False
    source_comparison_requested: bool = False
    source_type_preference: str | None = None
    requested_output_constraints: tuple[str, ...] = ()
    policy_version: str = QUERY_POLICY_VERSION


_YEAR = re.compile(r"(?<!\d)((?:19|20)\d{2})(?!\d)")
_QUARTER = re.compile(r"(?:\bq|\bquy\s*)([1-4])\s*[/\- ]\s*((?:19|20)\d{2})\b")
_ISO_DATE = re.compile(r"(?<!\d)((?:19|20)\d{2})-(\d{1,2})-(\d{1,2})(?!\d)")
_LOCAL_DATE = re.compile(r"(?<!\d)(\d{1,2})/(\d{1,2})/((?:19|20)\d{2})(?!\d)")
_VERSION = re.compile(r"\b(?:version|phien ban|v)\s*([a-z0-9][a-z0-9._-]*)\b")
_ENTITY = re.compile(r"\b(?:VF\d+|[A-Z]{2,}\d*[A-Z0-9-]*)\b")

_CURRENT_TERMS = ("current", "latest", "hien tai", "moi nhat", "dang hieu luc")
_HISTORICAL_TERMS = ("historical", "history", "truoc day", "da tung", "vao nam")
_COMPARE_TERMS = (
    "compare",
    "comparison",
    "between",
    "from",
    "changed",
    "change",
    "so sanh",
    "doi chieu",
    "thay doi",
    "tu ",
    " den ",
)
_CONFLICT_TERMS = (
    "conflict",
    "disagree",
    "inconsistent",
    "mau thuan",
    "khac nhau",
    "ch nieu",
    "chenh lech",
)
_SOURCE_COMPARE_TERMS = (
    "which source",
    "what source",
    "source says",
    "nguon nao",
    "tai lieu nao",
    "nguon noi",
)
_PREDICATE_TERMS = (
    "price",
    "gia",
    "range",
    "quang duong",
    "revenue",
    "doanh thu",
    "area",
    "dien tich",
    "fee",
    "phi",
    "quantity",
    "so luong",
)
_QUALIFIERS = (
    "wltp",
    "epa",
    "nedc",
    "vat",
    "per sqm",
    "per m2",
    "m2",
    "per unit",
    "list price",
    "transaction price",
    "vietnam",
    "usa",
    "europe",
)
_OUTPUT_CONSTRAINTS = {
    "table": ("table", "bang"),
    "timeline": ("timeline", "dong thoi gian"),
    "brief": ("brief", "short", "ngan gon"),
    "bullets": ("bullet", "list", "liet ke"),
}


def parse_query_context(
    query: str,
    *,
    owner_id: str,
    notebook_id: str | None,
) -> QueryContext:
    raw = " ".join(query.split())
    normalized = _fold(raw)
    years = tuple(dict.fromkeys(int(value) for value in _YEAR.findall(normalized)))
    quarter = _parse_quarter(normalized)
    reference_date = _parse_date(normalized)
    comparison = len(years) > 1 or _contains_any(normalized, _COMPARE_TERMS)
    current = _contains_any(normalized, _CURRENT_TERMS)
    historical = bool(years or quarter or reference_date) or _contains_any(
        normalized, _HISTORICAL_TERMS
    )
    conflict = _contains_any(normalized, _CONFLICT_TERMS)
    source_comparison = _contains_any(normalized, _SOURCE_COMPARE_TERMS)
    versions = tuple(match.group(1) for match in _VERSION.finditer(normalized))

    if source_comparison:
        intent = QueryIntent.SOURCE_COMPARISON
    elif conflict:
        intent = QueryIntent.CONFLICT_CHECK
    elif versions and comparison:
        intent = QueryIntent.VERSION_COMPARISON
    elif comparison and (len(years) > 1 or historical):
        intent = QueryIntent.TEMPORAL_COMPARISON
    elif current:
        intent = QueryIntent.CURRENT_FACT
    elif historical:
        intent = QueryIntent.HISTORICAL_FACT
    else:
        intent = QueryIntent.DEFAULT_FACT

    period_range = (min(years), max(years)) if len(years) > 1 else None
    qualifiers = tuple(term for term in _QUALIFIERS if _phrase_present(normalized, term))
    predicates = tuple(term for term in _PREDICATE_TERMS if _phrase_present(normalized, term))
    source_preference = _source_preference(normalized)
    constraints = tuple(
        name for name, terms in _OUTPUT_CONSTRAINTS.items() if _contains_any(normalized, terms)
    )
    entities = tuple(dict.fromkeys(match.group(0).upper() for match in _ENTITY.finditer(raw)))
    return QueryContext(
        raw_query=raw,
        normalized_query=normalized,
        owner_id=owner_id,
        notebook_id=notebook_id,
        intent=intent,
        reference_years=years,
        quarter=quarter,
        reference_date=reference_date,
        period_range=period_range,
        entity_terms=entities,
        predicate_terms=predicates,
        qualifier_terms=qualifiers,
        comparison_requested=comparison,
        current_requested=current,
        historical_requested=historical,
        conflict_requested=conflict,
        source_comparison_requested=source_comparison,
        source_type_preference=source_preference,
        requested_output_constraints=constraints,
    )


def _parse_quarter(value: str) -> tuple[int, int] | None:
    match = _QUARTER.search(value)
    return (int(match.group(2)), int(match.group(1))) if match else None


def _parse_date(value: str) -> date | None:
    match = _ISO_DATE.search(value)
    if match:
        return _safe_date(int(match.group(1)), int(match.group(2)), int(match.group(3)))
    match = _LOCAL_DATE.search(value)
    if match:
        return _safe_date(int(match.group(3)), int(match.group(2)), int(match.group(1)))
    return None


def _safe_date(year: int, month: int, day: int) -> date | None:
    try:
        return date(year, month, day)
    except ValueError:
        return None


def _source_preference(value: str) -> str | None:
    if _contains_any(value, ("official", "approved", "chinh thuc", "da phe duyet")):
        return "official_or_approved"
    if _contains_any(value, ("internal", "noi bo")):
        return "internal"
    return None


def _phrase_present(value: str, phrase: str) -> bool:
    return re.search(rf"(?<!\w){re.escape(phrase)}(?!\w)", value) is not None


def _contains_any(value: str, terms: tuple[str, ...]) -> bool:
    return any(term in value for term in terms)


def _fold(value: str) -> str:
    normalized = unicodedata.normalize("NFKD", value.casefold()).replace("đ", "d")
    return " ".join(
        "".join(
            character for character in normalized if not unicodedata.combining(character)
        ).split()
    )


__all__ = ["QUERY_POLICY_VERSION", "QueryContext", "QueryIntent", "parse_query_context"]
