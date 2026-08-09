"""Behavior proof that contextual text improves lexical retrieval recall."""

from app.retrieval.adapters.bm25_search import InMemoryBM25RetrievalAdapter
from app.retrieval.domain.models import EvidenceChunk, RetrievalFilters
from app.shared.contextual_text import ChunkContext, build_search_text


def test_llm_context_recovers_business_query_while_content_only_misses() -> None:
    filters = RetrievalFilters(owner_id="owner-1", notebook_id="notebook-1")
    metadata = {"owner_id": "owner-1", "notebook_id": "notebook-1"}
    content = "The approved maximum is 120 USD."
    baseline = InMemoryBM25RetrievalAdapter()
    baseline.index(
        EvidenceChunk(
            id="baseline",
            document_id="doc-1",
            text=content,
            metadata=metadata,
        )
    )
    contextual = InMemoryBM25RetrievalAdapter()
    contextual.index(
        EvidenceChunk(
            id="contextual",
            document_id="doc-1",
            text=content,
            metadata=metadata,
            search_text=build_search_text(
                content,
                ChunkContext(
                    contextual_summary=(
                        "This chunk defines the Bangkok lodging reimbursement allowance."
                    ),
                    contextual_search_terms=("Bangkok lodging",),
                ),
            ),
        )
    )

    assert baseline.search("Bangkok lodging", filters, top_k=5) == ()
    result = contextual.search("Bangkok lodging", filters, top_k=5)
    assert [candidate.chunk.id for candidate in result] == ["contextual"]
