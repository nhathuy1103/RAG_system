"""Tests for the PostgreSQL full-text sparse retrieval adapter."""

import json

import httpx2 as httpx

from app.retrieval.adapters.postgrest_full_text_search import (
    PostgrestFullTextRetrievalAdapter,
)
from app.retrieval.domain.models import RetrievalFilters, StructuredMetadataFilters

OWNER_ID = "20000000-0000-0000-0000-000000000002"
NOTEBOOK_ID = "10000000-0000-0000-0000-000000000001"
DOCUMENT_ID = "30000000-0000-0000-0000-000000000003"
CHUNK_ID = "40000000-0000-0000-0000-000000000004"


def test_search_calls_scoped_fts_rpc_and_preserves_metadata_types() -> None:
    calls: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        assert request.method == "POST"
        assert request.url.path.endswith("/rpc/search_document_chunks_keyword")
        assert json.loads(request.content) == {
            "p_query": "travel policy lodging",
            "p_owner_id": OWNER_ID,
            "p_notebook_id": NOTEBOOK_ID,
            "p_document_ids": [DOCUMENT_ID],
            "p_limit": 5,
        }
        return httpx.Response(
            200,
            json=[
                {
                    "chunk_id": CHUNK_ID,
                    "document_id": DOCUMENT_ID,
                    "document_version": 3,
                    "chunk_index": 7,
                    "content": "The maximum allowance is 120 USD.",
                    "metadata": {
                        "page_number": 4,
                        "retrieval_metadata": {
                            "title": "Travel policy",
                            "section_title": "Lodging",
                            "section_path": ["Expenses", "Lodging"],
                        },
                    },
                    "normalized_content_hash": "a" * 64,
                    "exact_duplicate_group_id": "50000000-0000-0000-0000-000000000005",
                    "score": 0.75,
                }
            ],
        )

    client = httpx.Client(
        base_url="https://example.supabase.co/rest/v1",
        transport=httpx.MockTransport(handler),
    )
    adapter = PostgrestFullTextRetrievalAdapter(client=client)
    filters = RetrievalFilters(
        owner_id=OWNER_ID,
        notebook_id=NOTEBOOK_ID,
        document_ids=(DOCUMENT_ID,),
    )

    candidates = adapter.search("travel policy lodging", filters, top_k=5)

    assert len(calls) == 1
    assert len(candidates) == 1
    candidate = candidates[0]
    assert candidate.source == "postgres_fts"
    assert candidate.score == 0.75
    assert candidate.chunk.text == "The maximum allowance is 120 USD."
    assert candidate.chunk.typed_metadata.page_number == 4
    assert candidate.chunk.typed_metadata.document_version == 3
    assert candidate.chunk.typed_metadata.chunk_index == 7
    assert candidate.chunk.typed_metadata.strings("section_path") == (
        "Expenses",
        "Lodging",
    )


def test_empty_document_scope_does_not_call_fts_rpc() -> None:
    calls: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        return httpx.Response(200, json=[])

    client = httpx.Client(
        base_url="https://example.supabase.co/rest/v1",
        transport=httpx.MockTransport(handler),
    )
    adapter = PostgrestFullTextRetrievalAdapter(client=client)

    assert (
        adapter.search(
            "travel",
            RetrievalFilters(owner_id=OWNER_ID, document_ids=()),
            top_k=5,
        )
        == ()
    )
    assert calls == []


def test_search_passes_active_structured_filters_to_rpc() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        assert body["p_project_code"] == "P16"
        assert body["p_year"] == 2026
        assert body["p_effective_status"] == "current"
        assert "p_project_id" not in body
        return httpx.Response(200, json=[])

    client = httpx.Client(
        base_url="https://example.supabase.co/rest/v1",
        transport=httpx.MockTransport(handler),
    )
    adapter = PostgrestFullTextRetrievalAdapter(client=client)
    filters = RetrievalFilters(
        owner_id=OWNER_ID,
        metadata=StructuredMetadataFilters(
            project_code="P16",
            year=2026,
            effective_status="current",
        ),
    )

    assert adapter.search("tiện ích", filters, top_k=5) == ()
