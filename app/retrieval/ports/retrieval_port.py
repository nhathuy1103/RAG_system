"""Port for the search backend (semantic / keyword / hybrid) — SPEC step ④-⑤."""

from __future__ import annotations

from typing import Protocol

from app.retrieval.domain.models import RetrievalCandidate, RetrievalFilters


class RetrievalPort(Protocol):
    """Implementations MUST enforce filters.owner_id themselves - not re-filtered above."""

    def search(
        self,
        query: str,
        filters: RetrievalFilters,
        *,
        top_k: int,
    ) -> tuple[RetrievalCandidate, ...]: ...


__all__ = ["RetrievalPort"]
