from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from app.infrastructure.telemetry import Telemetry
from app.pipeline.bootstrap.settings import Settings, get_settings
from app.pipeline.documents.adapters.parsers import ParserRegistry
from app.pipeline.documents.application.extraction_pipeline import AdvancedExtractionPipeline
from app.pipeline.indexing.adapters.context_enrichers import (
    create_openai_chunk_context_enricher,
)
from app.pipeline.indexing.adapters.embedding_providers import create_embedding_provider
from app.pipeline.indexing.adapters.vector_indexes import (
    InMemoryVectorIndex,
    PgVectorIndex,
    QdrantVectorIndex,
)
from app.pipeline.indexing.application.chunker import Chunker
from app.pipeline.indexing.application.pipeline import (
    IngestionEmbeddingPipeline,
    IngestionEmbeddingPipelineConfig,
)
from app.pipeline.indexing.ports.context_enricher import ChunkContextEnricher
from app.pipeline.indexing.ports.vector_index import VectorIndex


def build_chunk_context_enricher(
    settings: Settings,
    *,
    telemetry: Telemetry | None = None,
) -> ChunkContextEnricher | None:
    if not settings.contextual_enrichment_enabled or not settings.openai_api_key:
        return None
    return create_openai_chunk_context_enricher(
        api_key=settings.openai_api_key,
        base_url=settings.openai_base_url,
        timeout_seconds=settings.openai_timeout_seconds,
        config=settings.context_enrichment_config,
        telemetry=telemetry,
    )


def build_vector_index(
    settings: Settings,
    *,
    postgrest_base_url: str | None = None,
    postgrest_headers: Mapping[str, str] | None = None,
) -> VectorIndex:
    if settings.vector_store_backend == "memory":
        return InMemoryVectorIndex()
    if settings.vector_store_backend == "pgvector":
        if postgrest_base_url is None or postgrest_headers is None:
            raise ValueError(
                "VECTOR_STORE_BACKEND=pgvector requires postgrest_base_url and "
                "postgrest_headers - the composition root (services.py / runtime.py) "
                "must supply an authenticated Supabase REST client, pgvector has no "
                "own connection settings of its own to build one from."
            )
        return PgVectorIndex(base_url=postgrest_base_url, headers=postgrest_headers)

    from qdrant_client import QdrantClient

    client_kwargs: dict[str, Any] = {"timeout": settings.qdrant_timeout_seconds}
    if settings.qdrant_location:
        client_kwargs["location"] = settings.qdrant_location
    else:
        client_kwargs["url"] = settings.qdrant_url or "http://localhost"
        client_kwargs["port"] = settings.qdrant_port
        if settings.qdrant_api_key:
            client_kwargs["api_key"] = settings.qdrant_api_key
    client = QdrantClient(**client_kwargs)
    return QdrantVectorIndex(
        client=client,
        collection_name=settings.qdrant_collection,
        max_retries=settings.qdrant_max_retries,
        retry_backoff_ms=settings.qdrant_retry_backoff_ms,
        upsert_batch_size=settings.qdrant_upsert_batch_size,
    )


def build_ingestion_embedding_pipeline(
    settings: Settings | None = None,
    *,
    vector_index: VectorIndex | None = None,
    postgrest_base_url: str | None = None,
    postgrest_headers: Mapping[str, str] | None = None,
    telemetry: Telemetry | None = None,
) -> IngestionEmbeddingPipeline:
    effective = settings or get_settings()
    return IngestionEmbeddingPipeline(
        parser_catalog=ParserRegistry(),
        chunker=Chunker.from_settings(effective),
        embedding_provider=create_embedding_provider(
            effective.embedding_config,
            telemetry=telemetry,
        ),
        vector_index=vector_index
        or build_vector_index(
            effective,
            postgrest_base_url=postgrest_base_url,
            postgrest_headers=postgrest_headers,
        ),
        config=IngestionEmbeddingPipelineConfig(
            validation=effective.validation_config,
        ),
        extraction_pipeline=(
            AdvancedExtractionPipeline(effective.advanced_extraction_config)
            if effective.advanced_extraction_enabled
            else None
        ),
        context_enricher=build_chunk_context_enricher(effective, telemetry=telemetry),
        telemetry=telemetry,
    )


__all__ = [
    "build_chunk_context_enricher",
    "build_ingestion_embedding_pipeline",
    "build_vector_index",
]
