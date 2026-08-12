"""Boundary for tenant-scoped relation metadata enrichment."""

from typing import Protocol

from app.retrieval.domain.models import RetrievalCandidate, RetrievalFilters


class RelationMetadataPort(Protocol):
    def enrich(
        self,
        candidates: tuple[RetrievalCandidate, ...],
        filters: RetrievalFilters,
    ) -> tuple[RetrievalCandidate, ...]: ...


__all__ = ["RelationMetadataPort"]
