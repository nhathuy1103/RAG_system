from __future__ import annotations

import pytest

from app.retrieval.adapters.bm25_search import InMemoryBM25RetrievalAdapter
from app.retrieval.adapters.dense_search import HashingDenseRetrievalAdapter
from app.retrieval.adapters.hybrid_search import HybridRetrievalAdapter
from app.retrieval.domain.models import EvidenceChunk, RetrievalCandidate, RetrievalFilters

FILTERS = RetrievalFilters(owner_id="user-1")


def _chunk(chunk_id: str, text: str, *, owner_id: str = "user-1") -> EvidenceChunk:
    return EvidenceChunk(
        id=chunk_id, document_id="doc-1", text=text, metadata={"owner_id": owner_id}
    )


class FakeRetriever:
    """Records index/search calls without doing any real scoring."""

    def __init__(self, results: tuple[RetrievalCandidate, ...] = ()) -> None:
        self.indexed: list[EvidenceChunk] = []
        self.searched: list[str] = []
        self._results = results

    def index(self, chunk: EvidenceChunk) -> None:
        self.indexed.append(chunk)

    def search(self, query, filters, *, top_k):
        self.searched.append(query)
        return self._results


def test_index_forwards_to_both_underlying_retrievers() -> None:
    bm25 = FakeRetriever()
    dense = FakeRetriever()
    hybrid = HybridRetrievalAdapter(sparse=bm25, dense=dense)
    chunk = _chunk("c1", "doanh thu quý 3")

    hybrid.index(chunk)

    assert bm25.indexed == [chunk]
    assert dense.indexed == [chunk]


def test_search_queries_both_retrievers_and_fuses_results() -> None:
    bm25 = FakeRetriever()
    dense = FakeRetriever()
    hybrid = HybridRetrievalAdapter(sparse=bm25, dense=dense)

    hybrid.search("doanh thu quý 3", FILTERS, top_k=5)

    assert bm25.searched == ["doanh thu quý 3"]
    assert dense.searched == ["doanh thu quý 3"]


def test_real_bm25_and_dense_together_still_enforce_owner_scope() -> None:
    hybrid = HybridRetrievalAdapter(
        sparse=InMemoryBM25RetrievalAdapter(), dense=HashingDenseRetrievalAdapter()
    )
    hybrid.index(_chunk("mine", "doanh thu quý 3 là 5 tỷ đồng.", owner_id="user-1"))
    hybrid.index(_chunk("theirs", "doanh thu quý 3 là 5 tỷ đồng.", owner_id="user-2"))

    results = hybrid.search("doanh thu quý 3", FILTERS, top_k=5)

    result_ids = {c.chunk.id for c in results}
    assert "mine" in result_ids
    assert "theirs" not in result_ids


def test_rejects_non_positive_top_k() -> None:
    hybrid = HybridRetrievalAdapter(sparse=FakeRetriever(), dense=FakeRetriever())

    with pytest.raises(ValueError):
        hybrid.search("q", FILTERS, top_k=0)


def test_rejects_non_positive_candidate_k() -> None:
    with pytest.raises(ValueError):
        HybridRetrievalAdapter(sparse=FakeRetriever(), dense=FakeRetriever(), sparse_candidate_k=0)
    with pytest.raises(ValueError):
        HybridRetrievalAdapter(sparse=FakeRetriever(), dense=FakeRetriever(), dense_candidate_k=0)
