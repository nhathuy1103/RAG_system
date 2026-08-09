from __future__ import annotations

import pytest

from app.retrieval.adapters.bm25_search import InMemoryBM25RetrievalAdapter
from app.retrieval.domain.models import EvidenceChunk, RetrievalFilters

FILTERS = RetrievalFilters(owner_id="user-1")


def _chunk(chunk_id: str, text: str, *, owner_id: str = "user-1") -> EvidenceChunk:
    return EvidenceChunk(
        id=chunk_id, document_id="doc-1", text=text, metadata={"owner_id": owner_id}
    )


def test_ranks_document_with_more_query_term_occurrences_higher() -> None:
    adapter = InMemoryBM25RetrievalAdapter()
    adapter.index(_chunk("mentions-once", "doanh thu quý 3 tăng nhẹ."))
    adapter.index(
        _chunk(
            "mentions-often",
            "doanh thu doanh thu doanh thu quý 3 là điểm nhấn chính của báo cáo doanh thu.",
        )
    )

    results = adapter.search("doanh thu", FILTERS, top_k=5)

    assert [c.chunk.id for c in results][0] == "mentions-often"


def test_enforces_owner_scope() -> None:
    adapter = InMemoryBM25RetrievalAdapter()
    adapter.index(_chunk("mine", "doanh thu quý 3 là 5 tỷ đồng.", owner_id="user-1"))
    adapter.index(_chunk("theirs", "doanh thu quý 3 là 5 tỷ đồng.", owner_id="user-2"))

    results = adapter.search("doanh thu quý 3", FILTERS, top_k=5)

    result_ids = {c.chunk.id for c in results}
    assert "mine" in result_ids
    assert "theirs" not in result_ids


def test_returns_nothing_for_unrelated_query() -> None:
    adapter = InMemoryBM25RetrievalAdapter()
    adapter.index(_chunk("c1", "doanh thu quý 3 là 5 tỷ đồng."))

    results = adapter.search("thời tiết hôm nay", FILTERS, top_k=5)

    assert results == ()


def test_returns_nothing_when_corpus_is_empty() -> None:
    adapter = InMemoryBM25RetrievalAdapter()

    results = adapter.search("doanh thu", FILTERS, top_k=5)

    assert results == ()


def test_rejects_non_positive_top_k() -> None:
    adapter = InMemoryBM25RetrievalAdapter()
    adapter.index(_chunk("c1", "doanh thu"))

    with pytest.raises(ValueError):
        adapter.search("doanh thu", FILTERS, top_k=0)
