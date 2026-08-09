from __future__ import annotations

import pytest

from app.retrieval.adapters.dense_search import (
    HashingDenseRetrievalAdapter,
    cosine_similarity,
    embed,
)
from app.retrieval.domain.models import EvidenceChunk, RetrievalFilters

FILTERS = RetrievalFilters(owner_id="user-1")


def _chunk(chunk_id: str, text: str, *, owner_id: str = "user-1") -> EvidenceChunk:
    return EvidenceChunk(
        id=chunk_id, document_id="doc-1", text=text, metadata={"owner_id": owner_id}
    )


def test_embed_is_deterministic() -> None:
    assert embed("doanh thu quý 3") == embed("doanh thu quý 3")


def test_identical_text_has_near_perfect_similarity() -> None:
    vector = embed("doanh thu quý 3 tăng mạnh")

    assert cosine_similarity(vector, vector) == pytest.approx(1.0)


def test_shared_substrings_score_higher_than_unrelated_text() -> None:
    query_vector = embed("doanh thu quý 3")
    related = embed("doanh thu quý 3 của công ty tăng 20%")
    unrelated = embed("thời tiết hôm nay rất đẹp")

    assert cosine_similarity(query_vector, related) > cosine_similarity(query_vector, unrelated)


def test_enforces_owner_scope() -> None:
    adapter = HashingDenseRetrievalAdapter()
    adapter.index(_chunk("mine", "doanh thu quý 3 là 5 tỷ đồng.", owner_id="user-1"))
    adapter.index(_chunk("theirs", "doanh thu quý 3 là 5 tỷ đồng.", owner_id="user-2"))

    results = adapter.search("doanh thu quý 3", FILTERS, top_k=5)

    result_ids = {c.chunk.id for c in results}
    assert "mine" in result_ids
    assert "theirs" not in result_ids


def test_rejects_non_positive_top_k() -> None:
    adapter = HashingDenseRetrievalAdapter()
    adapter.index(_chunk("c1", "doanh thu"))

    with pytest.raises(ValueError):
        adapter.search("doanh thu", FILTERS, top_k=0)
