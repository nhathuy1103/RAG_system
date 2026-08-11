"""Port for evidence-backed, document-level metadata enrichment."""

from __future__ import annotations

from typing import Protocol

from app.pipeline.indexing.domain.document_metadata import (
    DocumentMetadataEnrichment,
    DocumentMetadataEnrichmentRequest,
)


class DocumentMetadataEnricher(Protocol):
    @property
    def profile(self) -> dict[str, object]: ...

    def enrich(
        self,
        request: DocumentMetadataEnrichmentRequest,
    ) -> DocumentMetadataEnrichment: ...


__all__ = ["DocumentMetadataEnricher"]
