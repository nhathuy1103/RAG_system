"""Port for generating one bounded semantic context per chunk."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Protocol

from app.pipeline.indexing.domain.context_enrichment import (
    ChunkContextEnrichment,
    ChunkContextEnrichmentRequest,
)


class ChunkContextEnricher(Protocol):
    @property
    def profile(self) -> Mapping[str, object]: ...

    @property
    def document_context_char_limit(self) -> int: ...

    def enrich(self, request: ChunkContextEnrichmentRequest) -> ChunkContextEnrichment: ...


__all__ = ["ChunkContextEnricher"]
