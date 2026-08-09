"""Backend-neutral structured-fact persistence contracts."""

from __future__ import annotations

import math
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from datetime import date, datetime
from typing import Protocol
from uuid import UUID

from app.structured_facts.domain.review import (
    StructuredClaimRelation,
    StructuredClaimRelationEvidence,
    StructuredClaimResolutionAction,
)


class StructuredFactRepositoryError(RuntimeError):
    """Structured fact persistence or retrieval failed safely."""


class StructuredFactReviewRepositoryError(StructuredFactRepositoryError):
    """Structured relation review storage is unavailable or inconsistent."""


class StructuredFactReviewConflictError(StructuredFactReviewRepositoryError):
    """A reviewer attempted to resolve a stale relation snapshot."""


@dataclass(frozen=True, slots=True)
class StructuredFactWriteResult:
    table_count: int
    claim_count: int
    relation_count: int


@dataclass(frozen=True, slots=True)
class StructuredFactSearch:
    notebook_id: UUID
    document_ids: tuple[UUID, ...]
    predicate: str
    subject_query: str
    valid_from: date | datetime | None = None
    valid_to: date | datetime | None = None
    limit: int = 20
    qualifiers: Mapping[str, object] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.predicate.strip() or not self.subject_query.strip():
            raise ValueError("predicate and subject_query are required")
        if not 1 <= self.limit <= 100:
            raise ValueError("structured fact search limit must be between 1 and 100")
        if self.valid_from is not None and self.valid_to is not None:
            try:
                reversed_interval = self.valid_to < self.valid_from
            except TypeError as exc:
                raise ValueError("structured fact validity bounds must be comparable") from exc
            if reversed_interval:
                raise ValueError("structured fact validity interval cannot be reversed")
        _validate_qualifier_filters(self.qualifiers)


def _validate_qualifier_filters(filters: Mapping[str, object]) -> None:
    unknown_groups = set(filters) - {"stable", "optional"}
    if unknown_groups:
        raise ValueError("structured fact qualifier groups must be stable or optional")
    for group_name, raw_group in filters.items():
        if not isinstance(raw_group, Mapping):
            raise ValueError(f"structured fact qualifier group {group_name} must be an object")
        for raw_key, value in raw_group.items():
            if not isinstance(raw_key, str) or not raw_key.strip():
                raise ValueError("structured fact qualifier names must be non-empty strings")
            if not isinstance(value, str | int | float | bool) or (
                isinstance(value, float) and not math.isfinite(value)
            ):
                raise ValueError("structured fact qualifier values must be finite JSON scalars")


@dataclass(frozen=True, slots=True)
class StructuredFactEvidence:
    claim_id: str
    document_id: UUID
    source_chunk_id: UUID
    document_version: int
    subject_key: str
    predicate: str
    normalized_value: Mapping[str, object]
    qualifiers: Mapping[str, object]
    temporal: Mapping[str, object]
    provenance: Mapping[str, object]
    confidence: float
    source_text: str = ""
    relation_warnings: tuple[Mapping[str, object], ...] = ()
    authority: Mapping[str, object] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class StructuredClaimCandidate:
    claim_id: UUID
    snapshot_id: UUID
    document_id: UUID
    document_version: int
    snapshot_key: str
    schema_fingerprint: str
    template_fingerprint: str | None
    normalized_schema: Mapping[str, object]
    candidate_identity_hash: str
    claim: Mapping[str, object]


class StructuredFactWriter(Protocol):
    """Trusted worker port for idempotent document-level replacement."""

    async def replace_for_document(
        self,
        *,
        job_id: UUID,
        document_id: UUID,
        extractor_version: str,
        table_snapshots: Sequence[Mapping[str, object]],
        claims: Sequence[Mapping[str, object]],
        relations: Sequence[Mapping[str, object]] = (),
    ) -> StructuredFactWriteResult: ...


class StructuredFactReader(Protocol):
    def search(
        self,
        query: StructuredFactSearch,
    ) -> tuple[StructuredFactEvidence, ...]: ...


class StructuredFactCandidateReader(Protocol):
    async def load_claim_candidates(
        self,
        *,
        notebook_id: UUID,
        document_id: UUID,
        candidate_identity_hashes: Sequence[str],
        schema_fingerprints: Sequence[str] = (),
        limit: int = 10000,
    ) -> tuple[StructuredClaimCandidate, ...]: ...


class StructuredFactStore(
    StructuredFactWriter,
    StructuredFactCandidateReader,
    Protocol,
):
    """Worker-side read/write boundary for fact replacement and diffing."""


class StructuredFactReviewRepository(Protocol):
    """Owner-scoped read and resolution boundary for structured relations."""

    async def list_pending_relations(
        self,
        notebook_id: UUID,
        *,
        limit: int,
        offset: int,
    ) -> tuple[list[StructuredClaimRelation], int]: ...

    async def get_relation_evidence(
        self,
        notebook_id: UUID,
        relation_id: UUID,
    ) -> StructuredClaimRelationEvidence | None: ...

    async def resolve_relation(
        self,
        notebook_id: UUID,
        relation_id: UUID,
        action: StructuredClaimResolutionAction,
        expected_updated_at: datetime,
        reason: str,
    ) -> StructuredClaimRelation | None: ...


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
