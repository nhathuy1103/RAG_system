from __future__ import annotations

from types import SimpleNamespace

from app.pipeline.indexing.adapters.vector_indexes import InMemoryVectorIndex, QdrantVectorIndex
from app.pipeline.indexing.domain.embedded_chunk import EmbeddedChunk


def test_qdrant_indexes_checksum_for_conditional_reconciliation_cleanup() -> None:
    assert QdrantVectorIndex.FILTER_INDEX_SCHEMAS["checksum"] == "keyword"


def test_qdrant_payload_contains_only_compact_retrieval_fields() -> None:
    chunk = EmbeddedChunk(
        id="chunk-1",
        document_id="document-1",
        document_version=1,
        owner_id="owner-1",
        tenant_id="tenant-1",
        chunk_index=17,
        page_number=18,
        section_title="Page 18",
        checksum="content-checksum",
        text="Chunk text",
        canonical_text="Canonical chunk text",
        token_count=2,
        embedding=(0.1, 0.2),
        embedding_model="text-embedding-3-small",
        metadata={
            "source_block_ids": "block-1,block-2",
            "strategy": "structure_recursive",
            "strategy_version": "2.0",
            "embedding_text": "Text sent to the embedding model",
            "document_checksum": "document-checksum",
        },
        retrieval_metadata={
            "content_kind": "paragraph",
            "contextual_summary": "Long semantic context stays out of Qdrant payload.",
            "project_name": "Display-only project name",
        },
        provenance_metadata={"source": "pdf"},
        authority_metadata={"visibility": "private"},
    )

    payload = QdrantVectorIndex._chunk_payload(chunk)

    assert payload == {
        "chunk_id": QdrantVectorIndex._point_id("chunk-1"),
        "source_chunk_id": "chunk-1",
        "document_id": "document-1",
        "document_version": 1,
        "owner_id": "owner-1",
        "tenant_id": "tenant-1",
        "chunk_index": 17,
        "page_number": 18,
        "section_title": "Page 18",
        "checksum": "content-checksum",
        "text": "Chunk text",
        "embedding_model": "text-embedding-3-small",
        "metadata": {
            "source_block_ids": ["block-1", "block-2"],
            "strategy": "structure_recursive",
            "strategy_version": "2.0",
        },
        "retrieval_metadata": {"content_kind": "paragraph"},
    }


def test_qdrant_payload_falls_back_to_chunk_strategy_name() -> None:
    chunk = EmbeddedChunk(
        id="chunk-1",
        document_id="document-1",
        document_version=1,
        owner_id="owner-1",
        tenant_id="tenant-1",
        chunk_index=0,
        page_number=None,
        section_title=None,
        checksum="checksum",
        text="Chunk text",
        canonical_text="Chunk text",
        token_count=2,
        embedding=(0.1,),
        embedding_model="test-model",
        metadata={
            "source_block_ids": ("block-1",),
            "chunk_strategy": "content_aware",
            "strategy_version": "2.0",
        },
    )

    payload = QdrantVectorIndex._chunk_payload(chunk)

    assert payload["metadata"] == {
        "source_block_ids": ["block-1"],
        "strategy": "content_aware",
        "strategy_version": "2.0",
    }


def test_qdrant_payload_preserves_versioned_entity_scope() -> None:
    entity_scope = {
        "version": "p2-entity-scope-metadata-v1",
        "entities": [{"canonical_id": "vinfast_vf8"}],
    }
    chunk = EmbeddedChunk(
        id="chunk-entity-scope",
        document_id="document-1",
        document_version=1,
        owner_id="owner-1",
        tenant_id="tenant-1",
        chunk_index=0,
        page_number=None,
        section_title=None,
        checksum="checksum",
        text="VF 8 Eco range is 450 km WLTP.",
        canonical_text="VF 8 Eco range is 450 km WLTP.",
        token_count=8,
        embedding=(0.1,),
        embedding_model="test-model",
        metadata={"entity_scope": entity_scope, "ignored": "large-value"},
    )

    payload = QdrantVectorIndex._chunk_payload(chunk)

    assert payload["metadata"] == {
        "source_block_ids": [],
        "strategy": "",
        "strategy_version": "",
        "entity_scope": entity_scope,
    }


def test_qdrant_search_hit_uses_point_id_instead_of_legacy_payload_chunk_id() -> None:
    canonical_id = QdrantVectorIndex._point_id("source:chunk:1")
    point = SimpleNamespace(
        id=canonical_id,
        score=0.87,
        payload={
            "chunk_id": "source:chunk:1",
            "document_id": "document-1",
            "text": "Chunk text",
            "page_number": 3,
            "section_title": "Introduction",
            "document_version": 2,
        },
    )

    hit = QdrantVectorIndex._search_hit(point)

    assert hit.chunk_id == canonical_id
    assert hit.document_id == "document-1"
    assert hit.text == "Chunk text"
    assert hit.page_number == 3
    assert hit.section_title == "Introduction"
    assert hit.document_version == 2


def test_in_memory_query_with_empty_document_ids_returns_empty() -> None:
    index = InMemoryVectorIndex()

    hits = index.query(
        [0.1, 0.2],
        owner_id="owner-1",
        document_ids=(),
        limit=5,
    )

    assert hits == []


def test_in_memory_query_applies_metadata_filters_fail_closed() -> None:
    index = InMemoryVectorIndex()
    matching = EmbeddedChunk(
        id="chunk-match",
        document_id="document-1",
        document_version=1,
        owner_id="owner-1",
        tenant_id="tenant-1",
        chunk_index=0,
        page_number=1,
        section_title="P16 - Smart City",
        checksum="checksum-1",
        text="Matching chunk",
        canonical_text="Matching chunk",
        token_count=2,
        embedding=(1.0, 0.0),
        embedding_model="test-model",
        retrieval_metadata={"project_code": "P16", "year": 2026},
    )
    missing_field = EmbeddedChunk(
        **{
            **matching.__dict__,
            "id": "chunk-missing",
            "document_id": "document-2",
            "retrieval_metadata": {"project_code": "P16"},
        }
    )
    index.upsert_chunks([matching, missing_field])

    hits = index.query(
        [1.0, 0.0],
        owner_id="owner-1",
        document_ids=None,
        limit=5,
        tenant_id="tenant-1",
        metadata_filters={"project_code": "P16", "year": 2026},
    )

    assert [hit.document_id for hit in hits] == ["document-1"]


def test_in_memory_query_is_scoped_to_notebook_tenant() -> None:
    index = InMemoryVectorIndex()
    chunks = [
        EmbeddedChunk(
            id=f"chunk-{tenant_id}",
            document_id=f"document-{tenant_id}",
            document_version=1,
            owner_id="owner-1",
            tenant_id=tenant_id,
            chunk_index=0,
            page_number=1,
            section_title=None,
            checksum=f"checksum-{tenant_id}",
            text=f"Chunk in {tenant_id}",
            canonical_text=f"Chunk in {tenant_id}",
            token_count=3,
            embedding=(1.0, 0.0),
            embedding_model="test-model",
        )
        for tenant_id in ("tenant-1", "tenant-2")
    ]
    index.upsert_chunks(chunks)

    hits = index.query(
        [1.0, 0.0],
        owner_id="owner-1",
        document_ids=None,
        limit=5,
        tenant_id="tenant-1",
    )

    assert [hit.document_id for hit in hits] == ["document-tenant-1"]


def test_qdrant_query_with_empty_document_ids_does_not_touch_client() -> None:
    index = QdrantVectorIndex(client=object(), collection_name="test-collection")

    hits = index.query(
        [0.1, 0.2],
        owner_id="owner-1",
        document_ids=(),
        limit=5,
    )

    assert hits == []
