"""PostgreSQL full-text sparse retrieval through a scoped PostgREST RPC."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field

import httpx2 as httpx

from app.infrastructure.telemetry import Telemetry
from app.retrieval.domain.audit import candidate_metadata_audit
from app.retrieval.domain.metadata import EvidenceMetadata
from app.retrieval.domain.models import (
    EvidenceChunk,
    RetrievalCandidate,
    RetrievalFilters,
)


@dataclass
class PostgrestFullTextRetrievalAdapter:
    """Rank chunks in Postgres without loading the caller's corpus into Python."""

    client: httpx.Client
    telemetry: Telemetry = field(default_factory=Telemetry, repr=False)

    def index(self, chunk: EvidenceChunk) -> None:
        """No-op: the generated tsvector column is maintained by Postgres."""

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
        if not query.strip():
            return ()

        rpc_metadata_parameters = {
            f"p_{field_name}": value for field_name, value in filters.metadata.active_items()
        }
        request_body = {
            "p_query": query,
            "p_owner_id": filters.owner_id,
            "p_notebook_id": filters.notebook_id,
            "p_document_ids": (
                list(filters.document_ids) if filters.document_ids is not None else None
            ),
            "p_limit": top_k,
            **rpc_metadata_parameters,
        }
        with self.telemetry.observe(
            "retrieval.postgres_fts_query",
            as_type="tool",
            input={
                "query": self.telemetry.content(query),
                "top_k": top_k,
                "notebook_id": filters.notebook_id,
                "document_ids": list(filters.document_ids or ()),
                "metadata_filters": filters.metadata.as_dict(),
                "rpc_metadata_parameters": rpc_metadata_parameters,
            },
        ) as observation:
            response = self.client.post(
                "/rpc/search_document_chunks_keyword",
                json=request_body,
            )
            response.raise_for_status()
            rows = response.json()
            if not isinstance(rows, list):
                raise TypeError("PostgreSQL full-text RPC response must be an array")

            candidates: list[RetrievalCandidate] = []
            for rank, row in enumerate(rows, start=1):
                if not isinstance(row, Mapping):
                    raise TypeError("PostgreSQL full-text result must be an object")
                raw_metadata = row.get("metadata")
                metadata = EvidenceMetadata.from_mapping(
                    raw_metadata if isinstance(raw_metadata, Mapping) else {},
                    owner_id=filters.owner_id,
                    notebook_id=filters.notebook_id,
                    chunk_index=row.get("chunk_index"),
                    document_version=row.get("document_version"),
                    normalized_content_hash=row.get("normalized_content_hash"),
                    exact_duplicate_group_id=row.get("exact_duplicate_group_id"),
                )
                candidates.append(
                    RetrievalCandidate(
                        chunk=EvidenceChunk(
                            id=str(row["chunk_id"]),
                            document_id=str(row["document_id"]),
                            text=str(row["content"]),
                            metadata=metadata,
                        ),
                        score=float(row["score"]),
                        rank=rank,
                        source="postgres_fts",
                    )
                )
            result = tuple(candidates)
            observation.update(
                output={
                    "hit_count": len(result),
                    "chunk_ids": [item.chunk.id for item in result],
                    "scores": [item.score for item in result],
                    "candidate_metadata_audit": self.telemetry.content(
                        candidate_metadata_audit(result, filters.metadata)
                    ),
                }
            )
            return result


__all__ = ["PostgrestFullTextRetrievalAdapter"]
