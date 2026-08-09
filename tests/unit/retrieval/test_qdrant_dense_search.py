"""Unit tests for the Qdrant-backed dense retrieval adapter."""

from app.pipeline.indexing.ports.vector_index import VectorSearchHit
from app.retrieval.adapters.qdrant_dense_search import QdrantDenseRetrievalAdapter
from app.retrieval.domain.models import RetrievalFilters

OWNER_ID = "20000000-0000-0000-0000-000000000002"
NOTEBOOK_ID = "10000000-0000-0000-0000-000000000001"
DOCUMENT_ID = "30000000-0000-0000-0000-000000000003"
CHUNK_ID = "40000000-0000-0000-0000-000000000004"


class FakeEmbeddingProvider:
    model_name = "fake-embedding"

    def __init__(self) -> None:
        self.embedded_texts: list[str] = []

    def embed(self, texts: list[str]) -> list[list[float]]:
        self.embedded_texts.extend(texts)
        return [[0.1, 0.2, 0.3] for _ in texts]


class FakeVectorIndex:
    def __init__(self, hits: list[VectorSearchHit]) -> None:
        self._hits = hits
        self.last_query: dict[str, object] | None = None

    def is_ready(self) -> bool:
        return True

    def upsert_chunks(self, chunks: object) -> None:  # pragma: no cover - unused
        raise NotImplementedError

    def delete_document_vectors(self, document_id: str) -> None:  # pragma: no cover
        raise NotImplementedError

    def delete_document_version_vectors(
        self, document_id: str, document_version: int
    ) -> None:  # pragma: no cover
        raise NotImplementedError

    def query(
        self,
        embedding: list[float],
        *,
        owner_id: str,
        document_ids: tuple[str, ...] | None,
        limit: int,
        tenant_id: str | None = None,
        metadata_filters: dict[str, str | int] | None = None,
    ) -> list[VectorSearchHit]:
        self.last_query = {
            "embedding": embedding,
            "owner_id": owner_id,
            "document_ids": document_ids,
            "limit": limit,
            "tenant_id": tenant_id,
            "metadata_filters": metadata_filters,
        }
        return self._hits[:limit]


def test_search_embeds_query_and_maps_hits_to_candidates() -> None:
    hits = [
        VectorSearchHit(
            chunk_id=CHUNK_ID,
            document_id=DOCUMENT_ID,
            score=0.87,
            text="Nội dung chunk",
            page_number=3,
            section_title="Giới thiệu",
            document_version=2,
        )
    ]
    vector_index = FakeVectorIndex(hits)
    embedding_provider = FakeEmbeddingProvider()
    adapter = QdrantDenseRetrievalAdapter(
        vector_index=vector_index, embedding_provider=embedding_provider
    )
    filters = RetrievalFilters(
        owner_id=OWNER_ID,
        notebook_id=NOTEBOOK_ID,
        document_ids=(DOCUMENT_ID,),
    )

    candidates = adapter.search("câu hỏi", filters, top_k=5)

    assert embedding_provider.embedded_texts == ["câu hỏi"]
    assert vector_index.last_query == {
        "embedding": [0.1, 0.2, 0.3],
        "owner_id": OWNER_ID,
        "document_ids": (DOCUMENT_ID,),
        "limit": 5,
        "tenant_id": NOTEBOOK_ID,
        "metadata_filters": {},
    }
    assert len(candidates) == 1
    candidate = candidates[0]
    assert candidate.chunk.id == CHUNK_ID
    assert candidate.chunk.document_id == DOCUMENT_ID
    assert candidate.chunk.text == "Nội dung chunk"
    assert candidate.chunk.metadata["page_number"] == 3
    assert candidate.chunk.metadata["section_title"] == "Giới thiệu"
    assert candidate.chunk.metadata["document_version"] == 2
    assert candidate.score == 0.87
    assert candidate.rank == 1
    assert candidate.source == "dense"


def test_search_rejects_non_positive_top_k() -> None:
    adapter = QdrantDenseRetrievalAdapter(
        vector_index=FakeVectorIndex([]),
        embedding_provider=FakeEmbeddingProvider(),
    )
    filters = RetrievalFilters(owner_id=OWNER_ID)

    try:
        adapter.search("câu hỏi", filters, top_k=0)
    except ValueError as exc:
        assert "top_k" in str(exc)
    else:
        raise AssertionError("expected ValueError")


def test_search_with_empty_document_ids_skips_embedding_and_vector_query() -> None:
    vector_index = FakeVectorIndex([])
    embedding_provider = FakeEmbeddingProvider()
    adapter = QdrantDenseRetrievalAdapter(
        vector_index=vector_index,
        embedding_provider=embedding_provider,
    )
    filters = RetrievalFilters(
        owner_id=OWNER_ID,
        notebook_id=NOTEBOOK_ID,
        document_ids=(),
    )

    candidates = adapter.search("câu hỏi", filters, top_k=5)

    assert candidates == ()
    assert embedding_provider.embedded_texts == []
    assert vector_index.last_query is None


def test_index_is_a_no_op() -> None:
    adapter = QdrantDenseRetrievalAdapter(
        vector_index=FakeVectorIndex([]),
        embedding_provider=FakeEmbeddingProvider(),
    )
    adapter.index(None)  # type: ignore[arg-type]
