"""Composition-root proof for the sparse retrieval implementation."""

from unittest.mock import MagicMock

from pydantic import AnyHttpUrl

from app.api.dependencies.services import get_chat_service
from app.bootstrap.settings import Settings as ApiSettings
from app.infrastructure.telemetry import Telemetry
from app.pipeline.bootstrap.settings import Settings as IngestionSettings
from app.retrieval.adapters.hybrid_search import HybridRetrievalAdapter
from app.retrieval.adapters.postgrest_full_text_search import (
    PostgrestFullTextRetrievalAdapter,
)


def test_chat_runtime_wires_postgres_fts_as_the_sparse_adapter() -> None:
    provider = get_chat_service(
        notebook_repository=MagicMock(),
        document_repository=MagicMock(),
        chat_repository=MagicMock(),
        quality_repository=MagicMock(),
        access_token="test-token",
        settings=ApiSettings(
            supabase_url=AnyHttpUrl("https://example.supabase.co"),
            supabase_publishable_key="test-key",
        ),
        ingestion_settings=IngestionSettings(
            embedding_provider="openai",
            vector_store_backend="memory",
            openai_api_key="test-openai-key",
        ),
        telemetry=Telemetry(),
    )

    service = next(provider)
    try:
        retrieval = service.retrieval_handler.agentic_retrieval.retrieval_port
        assert isinstance(retrieval, HybridRetrievalAdapter)
        assert isinstance(retrieval.sparse, PostgrestFullTextRetrievalAdapter)
    finally:
        next(provider, None)
