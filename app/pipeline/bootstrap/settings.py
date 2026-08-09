from __future__ import annotations

import os
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

from app.pipeline.documents.application.extraction_pipeline import (
    AdvancedExtractionPipelineConfig,
)
from app.pipeline.documents.application.validation import (
    DEFAULT_EXTENSIONS,
    DEFAULT_MIME_TYPES,
    DocumentValidationConfig,
)
from app.pipeline.indexing.adapters.context_enrichers import OpenAIChunkContextEnricherConfig
from app.pipeline.indexing.adapters.embedding_providers import EmbeddingProviderConfig


def _as_bool(value: str | None, default: bool = False) -> bool:
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


def _as_int(value: str | None, default: int) -> int:
    return default if value is None else int(value)


def _csv(value: str | None, default: tuple[str, ...]) -> tuple[str, ...]:
    if value is None:
        return default
    return tuple(item.strip().lower() for item in value.split(",") if item.strip())


def _load_dotenv() -> None:
    env_path = Path(".env")
    if not env_path.exists():
        return
    for raw_line in env_path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        os.environ.setdefault(
            key.strip(),
            value.strip().strip('"').strip("'"),
        )


@dataclass(frozen=True)
class Settings:
    app_env: str = "development"
    max_file_size_bytes: int = 10 * 1024 * 1024
    allowed_extensions: tuple[str, ...] = DEFAULT_EXTENSIONS
    allowed_mime_types: tuple[str, ...] = DEFAULT_MIME_TYPES
    chunk_size: int = 600
    chunk_overlap: int = 80
    chunking_strategy: str = "structure_recursive"
    embedding_provider: str = "local"
    vector_store_backend: str = "memory"
    advanced_extraction_enabled: bool = True
    extraction_quality_mode: str = "rag"
    max_extraction_provider_attempts: int = 1
    ocr_enabled: bool = False
    openai_api_key: str | None = None
    openai_embedding_model: str = "text-embedding-3-small"
    openai_chat_model: str = "gpt-4o-mini"
    openai_base_url: str = "https://api.openai.com/v1"
    openai_timeout_seconds: int = 30
    openai_embedding_batch_size: int = 64
    contextual_enrichment_enabled: bool = False
    contextual_enrichment_model: str = "gpt-4o-mini"
    contextual_enrichment_document_max_chars: int = 12000
    contextual_enrichment_max_context_chars: int = 600
    contextual_enrichment_max_context_words: int = 45
    contextual_enrichment_max_search_terms: int = 0
    contextual_enrichment_max_output_tokens: int = 400
    contextual_enrichment_max_retries: int = 2
    contextual_enrichment_retry_backoff_ms: int = 500
    contextual_enrichment_strict: bool = False
    qdrant_url: str | None = None
    qdrant_port: int = 6333
    qdrant_api_key: str | None = None
    qdrant_collection: str = "rag_chunks_openai_v1"
    qdrant_location: str | None = None
    qdrant_timeout_seconds: int = 2
    qdrant_max_retries: int = 2
    qdrant_retry_backoff_ms: int = 100
    qdrant_upsert_batch_size: int = 64

    @property
    def validation_config(self) -> DocumentValidationConfig:
        return DocumentValidationConfig(
            allowed_extensions=self.allowed_extensions,
            allowed_mime_types=self.allowed_mime_types,
            max_file_size_bytes=self.max_file_size_bytes,
        )

    @property
    def advanced_extraction_config(self) -> AdvancedExtractionPipelineConfig:
        return AdvancedExtractionPipelineConfig(
            ocr_enabled=self.ocr_enabled,
            quality_mode=self.extraction_quality_mode,
            max_provider_attempts=self.max_extraction_provider_attempts,
        )

    @property
    def embedding_config(self) -> EmbeddingProviderConfig:
        return EmbeddingProviderConfig(
            provider=self.embedding_provider,
            openai_api_key=self.openai_api_key,
            openai_embedding_model=self.openai_embedding_model,
            openai_base_url=self.openai_base_url,
            openai_timeout_seconds=self.openai_timeout_seconds,
            openai_embedding_batch_size=self.openai_embedding_batch_size,
        )

    @property
    def context_enrichment_config(self) -> OpenAIChunkContextEnricherConfig:
        return OpenAIChunkContextEnricherConfig(
            model=self.contextual_enrichment_model,
            document_context_char_limit=self.contextual_enrichment_document_max_chars,
            max_context_chars=self.contextual_enrichment_max_context_chars,
            max_context_words=self.contextual_enrichment_max_context_words,
            max_search_terms=self.contextual_enrichment_max_search_terms,
            max_output_tokens=self.contextual_enrichment_max_output_tokens,
            max_retries=self.contextual_enrichment_max_retries,
            retry_backoff_seconds=self.contextual_enrichment_retry_backoff_ms / 1000,
            strict=self.contextual_enrichment_strict,
        )


def _load_settings() -> Settings:
    _load_dotenv()
    settings = Settings(
        app_env=os.getenv("APP_ENV", "development").strip().lower(),
        max_file_size_bytes=_as_int(
            os.getenv("MAX_FILE_SIZE_BYTES"),
            10 * 1024 * 1024,
        ),
        allowed_extensions=_csv(
            os.getenv("ALLOWED_EXTENSIONS"),
            DEFAULT_EXTENSIONS,
        ),
        allowed_mime_types=_csv(
            os.getenv("ALLOWED_MIME_TYPES"),
            DEFAULT_MIME_TYPES,
        ),
        chunk_size=_as_int(os.getenv("CHUNK_SIZE"), 600),
        chunk_overlap=_as_int(os.getenv("CHUNK_OVERLAP"), 80),
        chunking_strategy=os.getenv(
            "CHUNKING_STRATEGY",
            "structure_recursive",
        )
        .strip()
        .lower(),
        embedding_provider=os.getenv(
            "EMBEDDING_PROVIDER",
            "local",
        )
        .strip()
        .lower(),
        vector_store_backend=os.getenv(
            "VECTOR_STORE_BACKEND",
            "memory",
        )
        .strip()
        .lower(),
        advanced_extraction_enabled=_as_bool(
            os.getenv("ADVANCED_EXTRACTION_ENABLED"),
            True,
        ),
        extraction_quality_mode=os.getenv(
            "EXTRACTION_QUALITY_MODE",
            "rag",
        )
        .strip()
        .lower(),
        max_extraction_provider_attempts=_as_int(
            os.getenv("MAX_EXTRACTION_PROVIDER_ATTEMPTS"),
            1,
        ),
        ocr_enabled=_as_bool(os.getenv("OCR_ENABLED"), False),
        openai_api_key=os.getenv("OPENAI_API_KEY") or None,
        openai_embedding_model=os.getenv(
            "OPENAI_EMBEDDING_MODEL",
            "text-embedding-3-small",
        ),
        openai_chat_model=os.getenv(
            "OPENAI_CHAT_MODEL",
            "gpt-4o-mini",
        ),
        openai_base_url=os.getenv(
            "OPENAI_BASE_URL",
            "https://api.openai.com/v1",
        ),
        openai_timeout_seconds=_as_int(
            os.getenv("OPENAI_TIMEOUT_SECONDS"),
            30,
        ),
        openai_embedding_batch_size=_as_int(
            os.getenv("OPENAI_EMBEDDING_BATCH_SIZE"),
            64,
        ),
        contextual_enrichment_enabled=_as_bool(
            os.getenv("CONTEXTUAL_ENRICHMENT_ENABLED"),
            False,
        ),
        contextual_enrichment_model=os.getenv(
            "CONTEXTUAL_ENRICHMENT_MODEL",
            os.getenv("OPENAI_CHAT_MODEL", "gpt-4o-mini"),
        ).strip(),
        contextual_enrichment_document_max_chars=_as_int(
            os.getenv("CONTEXTUAL_ENRICHMENT_DOCUMENT_MAX_CHARS"),
            12000,
        ),
        contextual_enrichment_max_context_chars=_as_int(
            os.getenv("CONTEXTUAL_ENRICHMENT_MAX_CONTEXT_CHARS"),
            600,
        ),
        contextual_enrichment_max_context_words=_as_int(
            os.getenv("CONTEXTUAL_ENRICHMENT_MAX_CONTEXT_WORDS"),
            45,
        ),
        contextual_enrichment_max_search_terms=_as_int(
            os.getenv("CONTEXTUAL_ENRICHMENT_MAX_SEARCH_TERMS"),
            0,
        ),
        contextual_enrichment_max_output_tokens=_as_int(
            os.getenv("CONTEXTUAL_ENRICHMENT_MAX_OUTPUT_TOKENS"),
            400,
        ),
        contextual_enrichment_max_retries=_as_int(
            os.getenv("CONTEXTUAL_ENRICHMENT_MAX_RETRIES"),
            2,
        ),
        contextual_enrichment_retry_backoff_ms=_as_int(
            os.getenv("CONTEXTUAL_ENRICHMENT_RETRY_BACKOFF_MS"),
            500,
        ),
        contextual_enrichment_strict=_as_bool(
            os.getenv("CONTEXTUAL_ENRICHMENT_STRICT"),
            False,
        ),
        qdrant_url=os.getenv("QDRANT_URL") or None,
        qdrant_port=_as_int(os.getenv("QDRANT_PORT"), 6333),
        qdrant_api_key=os.getenv("QDRANT_API_KEY") or None,
        qdrant_collection=os.getenv(
            "QDRANT_COLLECTION",
            "rag_chunks_openai_v1",
        ).strip(),
        qdrant_location=os.getenv("QDRANT_LOCATION") or None,
        qdrant_timeout_seconds=_as_int(
            os.getenv("QDRANT_TIMEOUT_SECONDS"),
            2,
        ),
        qdrant_max_retries=_as_int(os.getenv("QDRANT_MAX_RETRIES"), 2),
        qdrant_retry_backoff_ms=_as_int(
            os.getenv("QDRANT_RETRY_BACKOFF_MS"),
            100,
        ),
        qdrant_upsert_batch_size=_as_int(
            os.getenv("QDRANT_UPSERT_BATCH_SIZE"),
            64,
        ),
    )
    _validate(settings)
    return settings


def _validate(settings: Settings) -> None:
    if settings.app_env not in {"development", "test", "production"}:
        raise ValueError("APP_ENV must be development, test, or production.")
    if settings.embedding_provider not in {"local", "openai"}:
        raise ValueError("EMBEDDING_PROVIDER must be local or openai.")
    if settings.vector_store_backend not in {"memory", "qdrant", "pgvector"}:
        raise ValueError("VECTOR_STORE_BACKEND must be memory, qdrant, or pgvector.")
    if settings.extraction_quality_mode not in {"rag", "structured"}:
        raise ValueError("EXTRACTION_QUALITY_MODE must be rag or structured.")
    if settings.max_extraction_provider_attempts <= 0:
        raise ValueError("MAX_EXTRACTION_PROVIDER_ATTEMPTS must be > 0.")
    if settings.chunking_strategy not in {"structure_recursive", "content_aware"}:
        raise ValueError("CHUNKING_STRATEGY must be structure_recursive or content_aware.")
    if settings.chunk_size <= 0:
        raise ValueError("CHUNK_SIZE must be > 0.")
    if settings.chunk_overlap < 0:
        raise ValueError("CHUNK_OVERLAP must be >= 0.")
    if settings.chunk_overlap >= settings.chunk_size:
        raise ValueError("CHUNK_OVERLAP must be smaller than CHUNK_SIZE.")
    if settings.max_file_size_bytes != 10 * 1024 * 1024:
        raise ValueError("MAX_FILE_SIZE_BYTES must be 10485760 to match upload and Storage limits.")
    if settings.app_env == "production" and settings.embedding_provider == "local":
        raise ValueError("Local hash embeddings are forbidden in production.")
    if settings.embedding_provider == "openai" and not settings.openai_api_key:
        raise ValueError("OPENAI_API_KEY is required for OpenAI embeddings.")
    if settings.embedding_provider == "openai" and settings.vector_store_backend not in {
        "qdrant",
        "pgvector",
    }:
        raise ValueError("VECTOR_STORE_BACKEND must be qdrant or pgvector for OpenAI embeddings.")
    if settings.openai_embedding_batch_size <= 0:
        raise ValueError("OPENAI_EMBEDDING_BATCH_SIZE must be > 0.")
    if settings.contextual_enrichment_enabled and not settings.contextual_enrichment_model:
        raise ValueError("CONTEXTUAL_ENRICHMENT_MODEL must not be empty when enabled.")
    if settings.contextual_enrichment_document_max_chars <= 0:
        raise ValueError("CONTEXTUAL_ENRICHMENT_DOCUMENT_MAX_CHARS must be > 0.")
    if settings.contextual_enrichment_max_context_chars <= 0:
        raise ValueError("CONTEXTUAL_ENRICHMENT_MAX_CONTEXT_CHARS must be > 0.")
    if settings.contextual_enrichment_max_context_words <= 0:
        raise ValueError("CONTEXTUAL_ENRICHMENT_MAX_CONTEXT_WORDS must be > 0.")
    if settings.contextual_enrichment_max_search_terms < 0:
        raise ValueError("CONTEXTUAL_ENRICHMENT_MAX_SEARCH_TERMS must be >= 0.")
    if settings.contextual_enrichment_max_output_tokens <= 0:
        raise ValueError("CONTEXTUAL_ENRICHMENT_MAX_OUTPUT_TOKENS must be > 0.")
    if settings.contextual_enrichment_max_retries < 0:
        raise ValueError("CONTEXTUAL_ENRICHMENT_MAX_RETRIES must be >= 0.")
    if settings.contextual_enrichment_retry_backoff_ms < 0:
        raise ValueError("CONTEXTUAL_ENRICHMENT_RETRY_BACKOFF_MS must be >= 0.")
    if (
        settings.app_env == "production"
        and settings.contextual_enrichment_enabled
        and not settings.openai_api_key
    ):
        raise ValueError("OPENAI_API_KEY is required for contextual enrichment in production.")
    if settings.qdrant_upsert_batch_size <= 0:
        raise ValueError("QDRANT_UPSERT_BATCH_SIZE must be > 0.")
    if settings.qdrant_max_retries < 0:
        raise ValueError("QDRANT_MAX_RETRIES must be >= 0.")
    if settings.qdrant_retry_backoff_ms < 0:
        raise ValueError("QDRANT_RETRY_BACKOFF_MS must be >= 0.")


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return _load_settings()


__all__ = ["Settings", "get_settings"]
