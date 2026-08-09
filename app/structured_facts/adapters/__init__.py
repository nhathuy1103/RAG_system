"""Structured-fact infrastructure adapters."""

from app.structured_facts.adapters.postgrest_repository import (
    PostgrestStructuredFactReader,
    PostgrestStructuredFactRepository,
    PostgrestStructuredFactReviewRepository,
)

__all__ = [
    "PostgrestStructuredFactReader",
    "PostgrestStructuredFactRepository",
    "PostgrestStructuredFactReviewRepository",
]
