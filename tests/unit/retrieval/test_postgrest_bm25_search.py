"""Tests for the compatibility PostgREST-backed BM25 adapter."""

import httpx2 as httpx

from app.retrieval.adapters.bm25_search import InMemoryBM25RetrievalAdapter
from app.retrieval.adapters.postgrest_bm25_search import (
    PostgrestBM25RetrievalAdapter,
)
from app.retrieval.domain.models import (
    EvidenceChunk,
    RetrievalFilters,
    StructuredMetadataFilters,
)

OWNER_ID = "20000000-0000-0000-0000-000000000002"
NOTEBOOK_ID = "10000000-0000-0000-0000-000000000001"
DOCUMENT_ID = "30000000-0000-0000-0000-000000000003"
CHUNK_ROW = {
    "id": "40000000-0000-0000-0000-000000000004",
    "document_id": DOCUMENT_ID,
    "owner_id": OWNER_ID,
    "notebook_id": NOTEBOOK_ID,
    "content": "Chính sách nghỉ phép cho nhân viên toàn thời gian",
    "metadata": {"page_number": 2, "section_title": "Nghỉ phép", "document_version": 1},
}


def test_search_fetches_scoped_chunks_and_ranks_with_bm25() -> None:
    calls: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        assert request.method == "GET"
        assert request.url.params["owner_id"] == f"eq.{OWNER_ID}"
        assert request.url.params["notebook_id"] == f"eq.{NOTEBOOK_ID}"
        assert request.url.params["document_id"] == f"in.({DOCUMENT_ID})"
        return httpx.Response(200, json=[CHUNK_ROW])

    client = httpx.Client(
        base_url="https://example.supabase.co/rest/v1",
        transport=httpx.MockTransport(handler),
    )
    adapter = PostgrestBM25RetrievalAdapter(client=client)
    filters = RetrievalFilters(
        owner_id=OWNER_ID,
        notebook_id=NOTEBOOK_ID,
        document_ids=(DOCUMENT_ID,),
    )

    candidates = adapter.search("chính sách nghỉ phép", filters, top_k=5)

    assert len(calls) == 1
    assert len(candidates) == 1
    candidate = candidates[0]
    assert candidate.chunk.id == CHUNK_ROW["id"]
    assert candidate.chunk.document_id == DOCUMENT_ID
    assert candidate.source == "bm25"


def test_search_caches_corpus_across_multiple_calls() -> None:
    call_count = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal call_count
        call_count += 1
        return httpx.Response(200, json=[CHUNK_ROW])

    client = httpx.Client(
        base_url="https://example.supabase.co/rest/v1",
        transport=httpx.MockTransport(handler),
    )
    adapter = PostgrestBM25RetrievalAdapter(client=client)
    filters = RetrievalFilters(owner_id=OWNER_ID, notebook_id=NOTEBOOK_ID)

    adapter.search("nghỉ phép", filters, top_k=5)
    adapter.search("nhân viên", filters, top_k=5)

    assert call_count == 1


def test_search_returns_empty_when_no_chunks_match_query_terms() -> None:
    client = httpx.Client(
        base_url="https://example.supabase.co/rest/v1",
        transport=httpx.MockTransport(lambda _request: httpx.Response(200, json=[CHUNK_ROW])),
    )
    adapter = PostgrestBM25RetrievalAdapter(client=client)
    filters = RetrievalFilters(owner_id=OWNER_ID, notebook_id=NOTEBOOK_ID)

    candidates = adapter.search("bóng đá world cup", filters, top_k=5)

    assert candidates == ()


def test_search_with_empty_document_ids_returns_empty_without_fetching() -> None:
    calls: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        return httpx.Response(200, json=[CHUNK_ROW])

    client = httpx.Client(
        base_url="https://example.supabase.co/rest/v1",
        transport=httpx.MockTransport(handler),
    )
    adapter = PostgrestBM25RetrievalAdapter(client=client)
    filters = RetrievalFilters(
        owner_id=OWNER_ID,
        notebook_id=NOTEBOOK_ID,
        document_ids=(),
    )

    candidates = adapter.search("nghỉ phép", filters, top_k=5)

    assert candidates == ()
    assert calls == []


def test_context_metadata_recovers_a_chunk_that_content_only_bm25_misses() -> None:
    filters = RetrievalFilters(owner_id=OWNER_ID, notebook_id=NOTEBOOK_ID)
    content = "The maximum allowance is 120 USD."
    baseline = InMemoryBM25RetrievalAdapter()
    baseline.index(
        EvidenceChunk(
            id=str(CHUNK_ROW["id"]),
            document_id=DOCUMENT_ID,
            text=content,
            metadata={"owner_id": OWNER_ID, "notebook_id": NOTEBOOK_ID},
        )
    )
    assert baseline.search("travel policy lodging", filters, top_k=5) == ()

    contextual_row = {
        **CHUNK_ROW,
        "content": content,
        "metadata": {
            "page_number": 2,
            "document_version": 1,
            "retrieval_metadata": {
                "title": "Travel policy",
                "section_title": "Lodging",
                "section_path": ["Expenses", "Lodging"],
            },
        },
    }
    client = httpx.Client(
        base_url="https://example.supabase.co/rest/v1",
        transport=httpx.MockTransport(lambda _request: httpx.Response(200, json=[contextual_row])),
    )

    candidates = PostgrestBM25RetrievalAdapter(client=client).search(
        "travel policy lodging",
        filters,
        top_k=5,
    )

    assert len(candidates) == 1
    assert candidates[0].chunk.text == content
    assert candidates[0].chunk.search_text is not None
    assert "Travel policy" in candidates[0].chunk.search_text


def test_metadata_filter_matches_flat_and_nested_compatibility_rows() -> None:
    rows = [
        {
            **CHUNK_ROW,
            "id": "40000000-0000-0000-0000-000000000041",
            "metadata": {
                "document_type": "policy",
                "retrieval_metadata": {"title": "Legacy mixed row"},
            },
        },
        {
            **CHUNK_ROW,
            "id": "40000000-0000-0000-0000-000000000042",
            "metadata": {"retrieval_metadata": {"document_type": "policy"}},
        },
    ]
    captured: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        captured.append(request)
        return httpx.Response(200, json=rows)

    client = httpx.Client(
        base_url="https://example.supabase.co/rest/v1",
        transport=httpx.MockTransport(handler),
    )
    filters = RetrievalFilters(
        owner_id=OWNER_ID,
        notebook_id=NOTEBOOK_ID,
        metadata=StructuredMetadataFilters(document_type="policy"),
    )

    candidates = PostgrestBM25RetrievalAdapter(client=client).search(
        "chính sách nghỉ phép",
        filters,
        top_k=5,
    )

    assert {candidate.chunk.id for candidate in candidates} == {
        "40000000-0000-0000-0000-000000000041",
        "40000000-0000-0000-0000-000000000042",
    }
    assert "metadata->retrieval_metadata->>document_type" not in captured[0].url.params
