"""Dense semantic retrieval backed by the configured vector index."""

from __future__ import annotations

from dataclasses import dataclass, field

from app.infrastructure.telemetry import Telemetry
from app.pipeline.indexing.ports.embedding_provider import EmbeddingProvider
from app.pipeline.indexing.ports.vector_index import VectorIndex
from app.retrieval.domain.audit import candidate_metadata_audit
from app.retrieval.domain.metadata import EvidenceMetadata
from app.retrieval.domain.models import (
    EvidenceChunk,
    RetrievalCandidate,
    RetrievalFilters,
)


@dataclass
class DenseVectorRetrievalAdapter:
    """Dense retrieval over pgvector, Qdrant, or another VectorIndex port."""

    vector_index: VectorIndex
    embedding_provider: EmbeddingProvider
    telemetry: Telemetry = field(default_factory=Telemetry, repr=False)

    def index(self, chunk: EvidenceChunk) -> None:
        """No-op: chunks are indexed by the ingestion pipeline, not here."""

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

        with self.telemetry.observe(
            "retrieval.embed_query",
            as_type="embedding",
            input={"query": self.telemetry.content(query), "count": 1},
            model=self.embedding_provider.model_name,
        ) as observation:
            embedding = self.embedding_provider.embed([query])[0]
            observation.update(output={"vector_count": 1, "dimensions": len(embedding)})
        with self.telemetry.observe(
            "retrieval.dense_index_query",
            as_type="tool",
            input={
                "top_k": top_k,
                "document_count": (
                    len(filters.document_ids) if filters.document_ids is not None else None
                ),
                "notebook_id": filters.notebook_id,
                "document_ids": list(filters.document_ids or ()),
                "metadata_filters": filters.metadata.as_dict(),
                "vector_index_backend": type(self.vector_index).__name__,
            },
        ) as observation:
            hits = self.vector_index.query(
                embedding,
                owner_id=filters.owner_id,
                document_ids=filters.document_ids,
                limit=top_k,
                tenant_id=filters.notebook_id,
                metadata_filters=filters.metadata.as_dict(),
            )
            candidates = tuple(
                RetrievalCandidate(
                    chunk=EvidenceChunk(
                        id=hit.chunk_id,
                        document_id=hit.document_id,
                        text=hit.text,
                        metadata=EvidenceMetadata.from_mapping(
                            {
                                **hit.metadata,
                                "page_number": hit.page_number,
                                "section_title": hit.section_title,
                                "document_version": hit.document_version,
                                "checksum": hit.checksum,
                                "chunk_index": hit.chunk_index,
                                "normalized_content_hash": hit.normalized_content_hash,
                                "exact_duplicate_group_id": hit.exact_duplicate_group_id,
                            }
                        ),
                    ),
                    score=hit.score,
                    rank=rank,
                    source="dense",
                )
                for rank, hit in enumerate(hits, start=1)
            )
            observation.update(
                output={
                    "hit_count": len(hits),
                    "chunk_ids": [hit.chunk_id for hit in hits],
                    "scores": [hit.score for hit in hits],
                    "candidate_metadata_audit": self.telemetry.content(
                        candidate_metadata_audit(candidates, filters.metadata)
                    ),
                }
            )
            return candidates


QdrantDenseRetrievalAdapter = DenseVectorRetrievalAdapter

__all__ = ["DenseVectorRetrievalAdapter", "QdrantDenseRetrievalAdapter"]
