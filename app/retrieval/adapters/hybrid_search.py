"""Hybrid retrieval: dense and sparse search fused by RRF."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Protocol

from app.infrastructure.telemetry import Telemetry
from app.retrieval.adapters.fusion import ReciprocalRankFusion
from app.retrieval.domain.audit import candidate_metadata_audit
from app.retrieval.domain.models import (
    EvidenceChunk,
    RetrievalCandidate,
    RetrievalFilters,
)
from app.retrieval.ports.retrieval_port import RetrievalPort

DEFAULT_CANDIDATE_K = 20


class IndexableRetrievalPort(RetrievalPort, Protocol):
    """A RetrievalPort that also accepts chunks one at a time (in-memory adapters only)."""

    def index(self, chunk: EvidenceChunk) -> None: ...


@dataclass
class HybridRetrievalAdapter:
    """Composes sparse and dense retrievers, fused by RRF."""

    sparse: IndexableRetrievalPort
    dense: IndexableRetrievalPort
    fusion: ReciprocalRankFusion = field(default_factory=ReciprocalRankFusion)
    sparse_candidate_k: int = DEFAULT_CANDIDATE_K
    dense_candidate_k: int = DEFAULT_CANDIDATE_K
    telemetry: Telemetry = field(default_factory=Telemetry, repr=False)

    def __post_init__(self) -> None:
        if self.sparse_candidate_k <= 0:
            raise ValueError("sparse_candidate_k must be > 0")
        if self.dense_candidate_k <= 0:
            raise ValueError("dense_candidate_k must be > 0")

    def index(self, chunk: EvidenceChunk) -> None:
        self.sparse.index(chunk)
        self.dense.index(chunk)

    def search(
        self,
        query: str,
        filters: RetrievalFilters,
        *,
        top_k: int,
    ) -> tuple[RetrievalCandidate, ...]:
        if top_k <= 0:
            raise ValueError("top_k must be > 0")

        with self.telemetry.observe(
            "retrieval.hybrid_search",
            as_type="retriever",
            input={
                "query": self.telemetry.content(query),
                "sparse_candidate_k": self.sparse_candidate_k,
                "dense_candidate_k": self.dense_candidate_k,
                "fused_top_k": top_k,
                "metadata_filters": filters.metadata.as_dict(),
                "notebook_id": filters.notebook_id,
                "document_ids": list(filters.document_ids or ()),
            },
        ) as root_observation:
            with self.telemetry.observe(
                "retrieval.sparse_search",
                as_type="retriever",
                input={
                    "query": self.telemetry.content(query),
                    "metadata_filters": filters.metadata.as_dict(),
                },
            ) as observation:
                sparse_results = self.sparse.search(query, filters, top_k=self.sparse_candidate_k)
                observation.update(
                    output={
                        "count": len(sparse_results),
                        "chunk_ids": [item.chunk.id for item in sparse_results],
                        "scores": [item.score for item in sparse_results],
                        "candidate_metadata_audit": self.telemetry.content(
                            candidate_metadata_audit(sparse_results, filters.metadata)
                        ),
                    }
                )
            with self.telemetry.observe(
                "retrieval.dense_search",
                as_type="retriever",
                input={
                    "query": self.telemetry.content(query),
                    "metadata_filters": filters.metadata.as_dict(),
                },
            ) as observation:
                dense_results = self.dense.search(query, filters, top_k=self.dense_candidate_k)
                observation.update(
                    output={
                        "count": len(dense_results),
                        "chunk_ids": [item.chunk.id for item in dense_results],
                        "scores": [item.score for item in dense_results],
                        "candidate_metadata_audit": self.telemetry.content(
                            candidate_metadata_audit(dense_results, filters.metadata)
                        ),
                    }
                )
            with self.telemetry.observe(
                "retrieval.rrf_fusion",
                as_type="chain",
                input={
                    "sparse_count": len(sparse_results),
                    "dense_count": len(dense_results),
                    "top_k": top_k,
                },
            ) as observation:
                fused = self.fusion.fuse(
                    {"sparse": sparse_results, "dense": dense_results},
                    top_k=top_k,
                )
                observation.update(
                    output={
                        "count": len(fused),
                        "chunk_ids": [item.chunk.id for item in fused],
                        "scores": [item.score for item in fused],
                        "candidate_metadata_audit": self.telemetry.content(
                            candidate_metadata_audit(fused, filters.metadata)
                        ),
                    }
                )
            root_observation.update(
                output={
                    "sparse_count": len(sparse_results),
                    "dense_count": len(dense_results),
                    "fused_count": len(fused),
                }
            )
            return fused


__all__ = ["DEFAULT_CANDIDATE_K", "HybridRetrievalAdapter", "IndexableRetrievalPort"]
