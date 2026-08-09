from __future__ import annotations

from uuid import NAMESPACE_URL, uuid5

from app.knowledge_quality.application.analysis import build_chunk_fingerprint
from app.pipeline.documents.adapters.parsers import ParserRegistry, TxtParser
from app.pipeline.documents.domain.source import DocumentSource
from app.pipeline.indexing.adapters.embedding_providers import LocalEmbeddingProvider
from app.pipeline.indexing.adapters.vector_indexes import InMemoryVectorIndex
from app.pipeline.indexing.application.chunker import Chunker
from app.pipeline.indexing.application.pipeline import (
    ChunkEmbeddingPlan,
    IngestionEmbeddingPipeline,
    IngestionEmbeddingStage,
)
from app.pipeline.indexing.domain.context_enrichment import (
    ChunkContextEnrichment,
    ChunkContextEnrichmentRequest,
)
from app.pipeline.shared.text_utils import compute_checksum_text


class RecordingEmbeddingProvider:
    model_name = "recording-embedding-v1"

    def __init__(self) -> None:
        self.received_texts: list[str] = []

    def embed(self, texts: list[str]) -> list[list[float]]:
        self.received_texts.extend(texts)
        return [
            [float(index + 1), float(index + 2), float(index + 3)] for index in range(len(texts))
        ]


class RecordingContextEnricher:
    document_context_char_limit = 4000
    profile = {
        "contextual_enrichment_model": "context-test-v1",
        "contextual_enrichment_prompt_version": "chunk-context-test-v1",
    }

    def __init__(self) -> None:
        self.requests: list[ChunkContextEnrichmentRequest] = []

    def enrich(self, request: ChunkContextEnrichmentRequest) -> ChunkContextEnrichment:
        self.requests.append(request)
        return ChunkContextEnrichment(
            context_text="The allowance is governed by the travel expense policy.",
            search_terms=("Bangkok allowance",),
            status="generated",
            provider="test",
            model="context-test-v1",
            prompt_version="chunk-context-test-v1",
            input_checksum=f"input-{len(self.requests)}",
            source_scope=request.source_scope,
        )


def test_pipeline_preserves_validate_parse_chunk_embed_order() -> None:
    vector_index = InMemoryVectorIndex()
    pipeline = IngestionEmbeddingPipeline(
        parser_catalog=ParserRegistry(parsers=[TxtParser()]),
        chunker=Chunker.structure_recursive(chunk_size=8, overlap=2),
        embedding_provider=LocalEmbeddingProvider(),
        vector_index=vector_index,
    )
    source = DocumentSource(
        document_id="doc-1",
        owner_id="owner-1",
        tenant_id="tenant-1",
        title="notes.txt",
        mime_type="text/plain",
        content=(b"Heading\n\nalpha beta gamma delta epsilon zeta eta theta iota kappa lambda"),
    )

    result = pipeline.run(source)

    assert result.stages == (
        IngestionEmbeddingStage.VALIDATING,
        IngestionEmbeddingStage.PARSING,
        IngestionEmbeddingStage.SANITIZING,
        IngestionEmbeddingStage.CHUNKING,
        IngestionEmbeddingStage.EMBEDDING,
        IngestionEmbeddingStage.EMBEDDED,
    )
    assert result.parser_name == "txt"
    assert result.embedding_model == "local-hash-embedding-v1"
    assert len(result.embedded_chunks) == len(result.chunks)
    assert vector_index.list_chunks() == list(result.embedded_chunks)

    first_chunk = result.embedded_chunks[0]
    assert first_chunk.document_id == "doc-1"
    assert first_chunk.owner_id == "owner-1"
    assert first_chunk.tenant_id == "tenant-1"
    assert first_chunk.token_count > 0
    assert first_chunk.embedding
    assert result.chunks[0].strategy == "structure_recursive"
    assert result.chunks[0].embedding_text.startswith("Document: notes\n")
    assert "Page:" not in result.chunks[0].embedding_text
    assert first_chunk.retrieval_metadata["title"] == "notes.txt"
    fingerprint = build_chunk_fingerprint(first_chunk.canonical_text)
    exact_group_id = uuid5(
        NAMESPACE_URL,
        (
            "rag-chunk-exact-group:owner-1:tenant-1:"
            f"{fingerprint.normalization_version}:{fingerprint.strict_hash}"
        ),
    )
    assert first_chunk.metadata == {
        "source_block_ids": list(result.chunks[0].source_block_ids),
        "parser_name": "txt",
        "parser_version": result.parser_version,
        "strategy": "structure_recursive",
        "strategy_version": result.chunks[0].strategy_version,
        "config_checksum": result.chunks[0].config_checksum,
        "embedding_text_checksum": compute_checksum_text(result.chunks[0].embedding_text),
        "normalized_content_hash": fingerprint.strict_hash,
        "loose_content_signature": fingerprint.loose_signature,
        "normalization_version": fingerprint.normalization_version,
        "exact_duplicate_group_id": str(exact_group_id),
        "table_atomic": False,
    }


def test_pipeline_embeds_only_chunks_without_exact_reuse_vectors() -> None:
    provider = RecordingEmbeddingProvider()
    pipeline = IngestionEmbeddingPipeline(
        parser_catalog=ParserRegistry(parsers=[TxtParser()]),
        chunker=Chunker.structure_recursive(chunk_size=5, overlap=0),
        embedding_provider=provider,
    )
    source = DocumentSource(
        document_id="doc-reuse",
        owner_id="owner-1",
        tenant_id="tenant-1",
        title="reuse.txt",
        mime_type="text/plain",
        content=(
            b"alpha beta gamma delta epsilon zeta eta theta iota kappa "
            b"lambda mu nu xi omicron pi rho sigma tau"
        ),
    )
    prepared = pipeline.prepare(source)
    assert len(prepared.chunks) >= 3
    first_index = prepared.chunks[0].chunk_index
    second_index = prepared.chunks[1].chunk_index
    reused_vector = (0.1, 0.2, 0.3)

    result = pipeline.embed(
        prepared,
        persist_vectors=False,
        chunk_plan=ChunkEmbeddingPlan(
            precomputed_vectors={first_index: reused_vector},
            reuse_from_chunk_index={second_index: first_index},
            metadata_by_chunk_index={
                first_index: {
                    "action": "reuse_exact_embedding",
                    "embedding_reused": True,
                },
                second_index: {
                    "action": "reuse_batch_exact_embedding",
                    "embedding_reused": True,
                },
            },
        ),
    )

    assert len(provider.received_texts) == len(prepared.chunks) - 2
    assert result.embedded_chunks[0].embedding == reused_vector
    assert result.embedded_chunks[1].embedding == reused_vector
    quality = result.embedded_chunks[0].metadata["pre_embedding_quality"]
    assert isinstance(quality, dict)
    assert quality["action"] == "reuse_exact_embedding"


def test_llm_context_is_added_before_dedup_probe_and_embedding_without_changing_content() -> None:
    provider = RecordingEmbeddingProvider()
    enricher = RecordingContextEnricher()
    source = DocumentSource(
        document_id="doc-context",
        owner_id="owner-secret",
        tenant_id="tenant-secret",
        title="travel-policy.txt",
        mime_type="text/plain",
        content=b"Lodging\n\nThe maximum allowance in Bangkok is 120 USD.",
    )
    baseline = IngestionEmbeddingPipeline(
        parser_catalog=ParserRegistry(parsers=[TxtParser()]),
        chunker=Chunker.structure_recursive(chunk_size=30, overlap=0),
        embedding_provider=LocalEmbeddingProvider(),
    ).prepare(source)
    pipeline = IngestionEmbeddingPipeline(
        parser_catalog=ParserRegistry(parsers=[TxtParser()]),
        chunker=Chunker.structure_recursive(chunk_size=30, overlap=0),
        embedding_provider=provider,
        context_enricher=enricher,
    )

    prepared = pipeline.prepare(source)

    assert prepared.stages[-1] == IngestionEmbeddingStage.CONTEXTUALIZING
    assert len(enricher.requests) == len(prepared.chunks)
    assert [chunk.text for chunk in prepared.chunks] == [chunk.text for chunk in baseline.chunks]
    assert [chunk.checksum for chunk in prepared.chunks] == [
        chunk.checksum for chunk in baseline.chunks
    ]
    first = prepared.chunks[0]
    assert (
        "Context: The allowance is governed by the travel expense policy."
        in first.embedding_text
    )
    assert "Bangkok allowance" not in first.search_text
    retrieval = first.metadata["retrieval_metadata"]
    assert isinstance(retrieval, dict)
    assert retrieval["contextual_summary"].startswith("The allowance is governed")
    assert "contextual_search_terms" not in retrieval
    assert first.metadata["context_enrichment"] == {
        "status": "generated",
        "needs_context": True,
        "provider": "test",
        "model": "context-test-v1",
        "prompt_version": "chunk-context-test-v1",
        "input_checksum": "input-1",
        "source_scope": "whole_document",
        "output_word_count": 9,
    }
    request = enricher.requests[0]
    assert dict(request.scope_metadata)["document_version"] == "1"
    assert request.source_scope == "whole_document"
    assert not hasattr(request, "owner_id")
    assert not hasattr(request, "tenant_id")

    result = pipeline.embed(prepared, persist_vectors=False)

    assert provider.received_texts[0] == first.embedding_text
    embedded = result.embedded_chunks[0]
    assert embedded.canonical_text == baseline.chunks[0].text
    assert embedded.metadata["context_enrichment"] == first.metadata["context_enrichment"]
    assert build_chunk_fingerprint(embedded.canonical_text) == build_chunk_fingerprint(
        baseline.chunks[0].text
    )


def test_contextualization_can_be_deferred_until_after_document_identity_check() -> None:
    enricher = RecordingContextEnricher()
    pipeline = IngestionEmbeddingPipeline(
        parser_catalog=ParserRegistry(parsers=[TxtParser()]),
        chunker=Chunker.structure_recursive(chunk_size=30, overlap=0),
        embedding_provider=LocalEmbeddingProvider(),
        context_enricher=enricher,
    )
    source = DocumentSource(
        document_id="doc-deferred-context",
        owner_id="owner-1",
        tenant_id="tenant-1",
        title="travel-policy.txt",
        mime_type="text/plain",
        content=b"Lodging\n\nThe maximum allowance in Bangkok is 120 USD.",
    )

    prepared = pipeline.prepare(source, contextualize=False)

    assert IngestionEmbeddingStage.CONTEXTUALIZING not in prepared.stages
    assert enricher.requests == []

    contextualized = pipeline.contextualize(prepared, enabled=True)

    assert contextualized.stages[-1] == IngestionEmbeddingStage.CONTEXTUALIZING
    assert len(enricher.requests) == len(contextualized.chunks)
    assert pipeline.contextualize(contextualized, enabled=True) is contextualized


def test_self_contained_chunk_keeps_header_without_generated_context() -> None:
    class NotNeededContextEnricher(RecordingContextEnricher):
        def enrich(self, request: ChunkContextEnrichmentRequest) -> ChunkContextEnrichment:
            self.requests.append(request)
            return ChunkContextEnrichment(
                context_text=None,
                status="not_needed",
                provider="test",
                model="context-test-v1",
                prompt_version="chunk-context-test-v2",
                input_checksum="not-needed",
                needs_context=False,
                source_scope=request.source_scope,
            )

    pipeline = IngestionEmbeddingPipeline(
        parser_catalog=ParserRegistry(parsers=[TxtParser()]),
        chunker=Chunker.structure_recursive(chunk_size=30, overlap=0),
        embedding_provider=LocalEmbeddingProvider(),
        context_enricher=NotNeededContextEnricher(),
    )
    source = DocumentSource(
        document_id="doc-self-contained",
        owner_id="owner-1",
        tenant_id="tenant-1",
        title="travel-policy.txt",
        mime_type="text/plain",
        content=b"Lodging\n\nThe Bangkok lodging allowance is 120 USD.",
    )

    prepared = pipeline.prepare(source)
    first = prepared.chunks[0]
    retrieval = first.metadata["retrieval_metadata"]

    assert isinstance(retrieval, dict)
    assert "contextual_summary" not in retrieval
    assert "contextual_search_terms" not in retrieval
    assert "Context:" not in first.embedding_text
    assert first.metadata["context_enrichment"]["status"] == "not_needed"
    assert first.metadata["context_enrichment"]["needs_context"] is False
