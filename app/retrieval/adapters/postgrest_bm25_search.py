"""Compatibility BM25 adapter; production sparse retrieval uses PostgreSQL FTS."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field

import httpx2 as httpx

from app.retrieval.adapters.bm25_search import InMemoryBM25RetrievalAdapter
from app.retrieval.domain.metadata import EvidenceMetadata
from app.retrieval.domain.models import (
    EvidenceChunk,
    RetrievalCandidate,
    RetrievalFilters,
)
from app.shared.contextual_text import ChunkContext, build_search_text

CHUNK_COLUMNS = (
    "id,document_id,owner_id,notebook_id,chunk_index,content,metadata,"
    "normalized_content_hash,exact_duplicate_group_id"
)


@dataclass
class PostgrestBM25RetrievalAdapter:
    """BM25 over a scoped snapshot, retained for local evaluation and comparison."""

    client: httpx.Client
    _corpora: dict[RetrievalFilters, InMemoryBM25RetrievalAdapter] = field(
        default_factory=dict,
        init=False,
        repr=False,
    )

    def index(self, chunk: EvidenceChunk) -> None:
        """No-op: chunks are fetched from Postgres on first search, not indexed here."""

    def search(
        self,
        query: str,
        filters: RetrievalFilters,
        *,
        top_k: int,
    ) -> tuple[RetrievalCandidate, ...]:
        if top_k <= 0:
            raise ValueError("top_k must be > 0")
        if filters.document_ids is not None and not filters.document_ids:
            return ()
        corpus = self._load_corpus(filters)
        return corpus.search(query, filters, top_k=top_k)

    def _load_corpus(self, filters: RetrievalFilters) -> InMemoryBM25RetrievalAdapter:
        cached = self._corpora.get(filters)
        if cached is not None:
            return cached

        params: dict[str, str] = {
            "owner_id": f"eq.{filters.owner_id}",
            "select": CHUNK_COLUMNS,
        }
        if filters.notebook_id is not None:
            params["notebook_id"] = f"eq.{filters.notebook_id}"
        if filters.document_ids is not None:
            params["document_id"] = f"in.({','.join(filters.document_ids)})"
        # Do not pre-filter a compatibility corpus through only the nested JSON
        # path.  Historical rows may keep retrieval fields flat.  The shared
        # in-memory matcher below applies the same fail-closed semantics to
        # either representation after the tenant/document scope is fetched.

        response = self.client.get("/document_chunks", params=params)
        response.raise_for_status()
        rows = response.json()
        if not isinstance(rows, list):
            raise TypeError("PostgREST chunk listing must be an array")

        corpus = InMemoryBM25RetrievalAdapter()
        for row in rows:
            if not isinstance(row, Mapping):
                raise TypeError("document_chunks row must be an object")
            metadata = row.get("metadata")
            if not isinstance(metadata, Mapping):
                metadata = {}
            content = str(row["content"])
            typed_metadata = EvidenceMetadata.from_mapping(
                metadata,
                owner_id=str(row["owner_id"]),
                notebook_id=str(row["notebook_id"]),
                chunk_index=row.get("chunk_index"),
                normalized_content_hash=row.get("normalized_content_hash"),
                exact_duplicate_group_id=row.get("exact_duplicate_group_id"),
            )
            corpus.index(
                EvidenceChunk(
                    id=str(row["id"]),
                    document_id=str(row["document_id"]),
                    text=content,
                    metadata=typed_metadata,
                    search_text=build_search_text(
                        content,
                        ChunkContext.from_metadata(typed_metadata),
                    ),
                )
            )
        self._corpora[filters] = corpus
        return corpus


__all__ = ["PostgrestBM25RetrievalAdapter"]
