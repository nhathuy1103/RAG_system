"""Deterministic normalization for metadata used by pre-retrieval filters."""

from __future__ import annotations

import re
from collections.abc import Mapping

_PROJECT_HEADING = re.compile(
    r"^\s*(P\d{1,6})\s*(?:\u2022|\||:|-)\s*(.+?)\s*$",
    re.IGNORECASE,
)
_YEAR = re.compile(r"(?<!\d)((?:19|20)\d{2})(?!\d)")
_FILTER_FIELDS = (
    "document_type",
    "content_kind",
    "project_id",
    "project_code",
    "project_name",
    "project_aliases",
    "year",
    "data_period",
    "effective_status",
    "domain",
    "clause_type",
    "region",
    "region_code",
    "source",
    "source_code",
)


def normalize_chunk_retrieval_metadata(
    *,
    chunk_metadata: Mapping[str, object],
    document_metadata: Mapping[str, object],
    source_metadata: Mapping[str, object],
    title: str,
    section_title: str | None,
) -> dict[str, object]:
    """Merge authoritative layers and derive only unambiguous chunk fields."""

    result: dict[str, object] = {}
    for layer in (document_metadata, source_metadata, chunk_metadata):
        nested = layer.get("retrieval_metadata")
        if isinstance(nested, Mapping):
            result.update(nested)
        for field_name in _FILTER_FIELDS:
            value = layer.get(field_name)
            if value not in (None, ""):
                result[field_name] = value

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
        result["data_period"] = data_period.upper()

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

    for field_name in ("document_type", "content_kind"):
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


__all__ = ["normalize_chunk_retrieval_metadata"]
