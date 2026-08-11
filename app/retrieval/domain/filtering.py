"""Shared fail-closed matching for structured retrieval metadata."""

from __future__ import annotations

from collections.abc import Mapping

from app.retrieval.domain.models import StructuredMetadataFilters


def matches_metadata_filters(
    metadata: Mapping[str, object],
    filters: StructuredMetadataFilters,
) -> bool:
    nested = metadata.get("retrieval_metadata")
    retrieval_metadata = nested if isinstance(nested, Mapping) else {}
    for key, expected in filters.active_items():
        # During the compatibility window old rows can be flat, new rows are
        # nested, and some rows legitimately contain both shapes.  Prefer the
        # canonical nested value but fall back per-field instead of selecting
        # one entire object and silently losing the other.
        actual = retrieval_metadata.get(key)
        if actual is None:
            actual = metadata.get(key)
        if actual is None:
            return False
        if key == "year":
            try:
                if not isinstance(actual, str | int | float) or isinstance(actual, bool):
                    return False
                if int(actual) != expected:
                    return False
            except (TypeError, ValueError):
                return False
        elif str(actual).strip().casefold() != str(expected).strip().casefold():
            return False
    return True


__all__ = ["matches_metadata_filters"]
