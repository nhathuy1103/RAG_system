"""Ports for structured-fact persistence and retrieval."""

from app.structured_facts.ports.repositories import (
    StructuredClaimCandidate,
    StructuredFactCandidateReader,
    StructuredFactEvidence,
    StructuredFactReader,
    StructuredFactRepositoryError,
    StructuredFactReviewConflictError,
    StructuredFactReviewRepository,
    StructuredFactReviewRepositoryError,
    StructuredFactSearch,
    StructuredFactStore,
    StructuredFactWriter,
    StructuredFactWriteResult,
)

__all__ = [
    "StructuredFactRepositoryError",
    "StructuredFactReviewConflictError",
    "StructuredFactReviewRepository",
    "StructuredFactReviewRepositoryError",
    "StructuredFactEvidence",
    "StructuredFactCandidateReader",
    "StructuredClaimCandidate",
    "StructuredFactReader",
    "StructuredFactSearch",
    "StructuredFactStore",
    "StructuredFactWriteResult",
    "StructuredFactWriter",
]
