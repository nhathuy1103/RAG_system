"""Shared fail-closed matching for structured retrieval metadata."""

from __future__ import annotations

from collections.abc import Mapping

from app.retrieval.domain.models import StructuredMetadataFilters


def matches_metadata_filters(
    metadata: Mapping[str, object],
    filters: StructuredMetadataFilters,
) -> bool:
    nested = metadata.get("retrieval_metadata")
    retrieval_metadata = nested if isinstance(nested, Mapping) else metadata
    for key, expected in filters.active_items():
        actual = retrieval_metadata.get(key)
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
