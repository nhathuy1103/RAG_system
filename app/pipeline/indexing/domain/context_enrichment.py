"""Value objects for bounded, per-chunk contextual enrichment."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Literal

ContextEnrichmentStatus = Literal["generated", "not_needed", "fallback"]
ContextSourceScope = Literal["whole_document", "bounded_context_package"]

CONTEXT_SCOPE_FIELDS = (
    "document_version",
    "year",
    "data_period",
    "reporting_period",
    "as_of_date",
    "effective_date",
    "effective_status",
    "lifecycle_status",
    "project_name",
    "project_code",
    "project_status",
    "organization",
    "department",
    "faculty",
    "region",
    "location",
    "market_type",
    "currency",
    "unit",
    "table_units",
)


@dataclass(frozen=True, slots=True)
class ChunkContextEnrichmentRequest:
    """Trusted structure plus untrusted document text sent to an enricher."""

    document_title: str
    document_type: str | None
    language: str | None
    section_title: str | None
    section_path: tuple[str, ...]
    content_kind: str | None
    table_header: str | None
    document_outline: str
    document_excerpt: str
    chunk_text: str
    scope_metadata: tuple[tuple[str, str], ...] = ()
    source_scope: ContextSourceScope = "bounded_context_package"


@dataclass(frozen=True, slots=True)
class ChunkContextEnrichment:
    """Validated semantic additions; never authoritative business metadata."""

    context_text: str | None
    status: ContextEnrichmentStatus
    provider: str
    model: str
    prompt_version: str
    input_checksum: str
    needs_context: bool = True
    search_terms: tuple[str, ...] = ()
    quality_flags: tuple[str, ...] = ()
    source_scope: ContextSourceScope = "bounded_context_package"
    error_code: str | None = None


def select_context_scope_metadata(
    metadata: Mapping[str, object],
) -> tuple[tuple[str, str], ...]:
    """Select bounded semantic scope without leaking IDs or access-control fields."""
    nested = metadata.get("retrieval_metadata")
    retrieval = nested if isinstance(nested, Mapping) else {}
    selected: list[tuple[str, str]] = []
    for field in CONTEXT_SCOPE_FIELDS:
        value = metadata.get(field)
        if value in (None, "", [], {}, ()):
            value = retrieval.get(field)
        text = _scope_text(value)
        if text:
            selected.append((field, text))
    return tuple(selected)


def _scope_text(value: object) -> str | None:
    if isinstance(value, str):
        text = " ".join(value.split()).strip()
    elif isinstance(value, bool):
        text = str(value).lower()
    elif isinstance(value, int | float):
        text = str(value)
    elif isinstance(value, list | tuple | set | frozenset):
        values = sorted(value, key=str) if isinstance(value, set | frozenset) else value
        parts = [
            part
            for item in values
            if (part := _scope_text(item)) is not None
        ]
        text = " | ".join(parts)
    else:
        return None
    if not text:
        return None
    return text[:500].rsplit(" ", 1)[0].strip() if len(text) > 500 else text


__all__ = [
    "CONTEXT_SCOPE_FIELDS",
    "ChunkContextEnrichment",
    "ChunkContextEnrichmentRequest",
    "ContextEnrichmentStatus",
    "ContextSourceScope",
    "select_context_scope_metadata",
]
