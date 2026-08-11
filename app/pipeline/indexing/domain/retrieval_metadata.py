"""Deterministic normalization for metadata used by pre-retrieval filters."""

from __future__ import annotations

import re
from collections.abc import Mapping
from datetime import date

_PROJECT_HEADING = re.compile(
    r"^\s*(P\d{1,6})\s*(?:\u2022|\||:|-)\s*(.+?)\s*$",
    re.IGNORECASE,
)
_YEAR = re.compile(r"(?<!\d)((?:19|20)\d{2})(?!\d)")
_FILTER_FIELDS = (
    "document_number",
    "document_type",
    "category",
    "content_kind",
    "project_id",
    "project_code",
    "project_name",
    "project_aliases",
    "department_code",
    "year",
    "data_period",
    "effective_from",
    "effective_to",
    "effective_status",
    "domain",
    "clause_type",
    "region",
    "region_code",
    "source",
    "source_code",
)

# These LLM fields are evidence-backed candidates.  Explicit parser, source,
# user-confirmed and chunk values below always overwrite them.  Security scope
# (owner/notebook/ACL) is intentionally never inferred here.
_INFERRED_PROMOTION_FIELDS = frozenset(_FILTER_FIELDS) - {
    "content_kind",
    "project_id",
    "project_aliases",
    "effective_status",
    "clause_type",
    "region",
    "region_code",
    "source",
    "source_code",
}


def normalize_chunk_retrieval_metadata(
    *,
    chunk_metadata: Mapping[str, object],
    document_metadata: Mapping[str, object],
    source_metadata: Mapping[str, object],
    title: str,
    section_title: str | None,
    reference_date: date | None = None,
) -> dict[str, object]:
    """Merge authoritative layers and derive only unambiguous chunk fields."""

    result: dict[str, object] = {}
    raw_inferred = document_metadata.get("inferred_metadata")
    promoted_fields: set[str] = set()
    if isinstance(raw_inferred, Mapping):
        for field_name in _INFERRED_PROMOTION_FIELDS:
            value = raw_inferred.get(field_name)
            if value not in (None, ""):
                result[field_name] = value
                promoted_fields.add(field_name)

    for layer in (document_metadata, source_metadata, chunk_metadata):
        nested = layer.get("retrieval_metadata")
        if isinstance(nested, Mapping):
            result.update(nested)
        for field_name in _FILTER_FIELDS:
            value = layer.get(field_name)
            if value not in (None, ""):
                result[field_name] = value

    if promoted_fields:
        # Preserve provenance for audit/UI.  Explicit values may replace the
        # candidate, but the assertion record remains available separately.
        result["inferred_metadata_fields"] = sorted(promoted_fields)

    result.setdefault("title", title)
    if section_title:
        result.setdefault("section_title", section_title)

    heading = str(result.get("section_title") or section_title or "")
    project_match = _PROJECT_HEADING.match(heading)
    if project_match:
        result.setdefault("project_code", project_match.group(1).upper())
        result.setdefault("project_name", project_match.group(2).strip())

    project_code = _clean_text(result.get("project_code"))
    if project_code:
        result["project_code"] = project_code.upper()

    year = _valid_year(result.get("year"))
    if year is None:
        title_years = {int(value) for value in _YEAR.findall(title)}
        if len(title_years) == 1:
            year = next(iter(title_years))
    if year is not None:
        result["year"] = year

    data_period = _clean_text(result.get("data_period"))
    if data_period:
        result["data_period"] = _canonical_data_period(data_period)

    for field_name in ("effective_from", "effective_to"):
        parsed_date = _valid_date(result.get(field_name))
        if parsed_date is None:
            result.pop(field_name, None)
        else:
            result[field_name] = parsed_date.isoformat()

    status = _clean_text(result.get("effective_status"))
    if status:
        canonical_status = {
            "latest": "current",
            "active": "current",
            "effective": "current",
            "expired": "expired",
            "superseded": "superseded",
        }.get(status.casefold(), status.casefold())
        result["effective_status"] = canonical_status

    if not status and reference_date is not None:
        effective_from = _valid_date(result.get("effective_from"))
        effective_to = _valid_date(result.get("effective_to"))
        if effective_to is not None and reference_date > effective_to:
            result["effective_status"] = "expired"
        elif (
            (effective_from is None or effective_from <= reference_date)
            and (effective_to is None or reference_date <= effective_to)
            and (effective_from is not None or effective_to is not None)
        ):
            result["effective_status"] = "current"
        elif effective_from is not None and reference_date < effective_from:
            result["effective_status"] = "scheduled"
        if "effective_status" in result:
            result["effective_status_as_of"] = reference_date.isoformat()

    for field_name in ("document_type", "category", "domain", "content_kind"):
        value = _clean_text(result.get(field_name))
        if value:
            result[field_name] = value.casefold()
    return result


def _clean_text(value: object) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _valid_year(value: object) -> int | None:
    if isinstance(value, bool) or value in (None, ""):
        return None
    if not isinstance(value, str | int | float):
        return None
    try:
        year = int(value)
    except (TypeError, ValueError):
        return None
    return year if 1900 <= year <= 2100 else None


def _valid_date(value: object) -> date | None:
    if isinstance(value, date):
        return value
    text = _clean_text(value)
    if text is None:
        return None
    try:
        return date.fromisoformat(text)
    except ValueError:
        return None


def _canonical_data_period(value: str) -> str:
    compact = re.sub(r"\s+", "", value).upper()
    compact = re.sub(
        r"^(Q[1-4]|H[12]|(?:0[1-9]|1[0-2]))/((?:19|20)\d{2})$",
        r"\1-\2",
        compact,
    )
    quarter = re.fullmatch(r"Q([1-4])[-_]?((?:19|20)\d{2})", compact)
    if quarter:
        return f"Q{quarter.group(1)}-{quarter.group(2)}"
    half = re.fullmatch(r"H([12])[-_]?((?:19|20)\d{2})", compact)
    if half:
        return f"H{half.group(1)}-{half.group(2)}"
    return compact


__all__ = ["normalize_chunk_retrieval_metadata"]
