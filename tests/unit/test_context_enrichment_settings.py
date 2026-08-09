from __future__ import annotations

import pytest

from app.pipeline.bootstrap import settings as settings_module


def test_contextual_enrichment_is_disabled_by_default(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(settings_module, "_load_dotenv", lambda: None)
    monkeypatch.setenv("APP_ENV", "test")
    monkeypatch.setenv("EMBEDDING_PROVIDER", "local")
    monkeypatch.setenv("VECTOR_STORE_BACKEND", "memory")
    monkeypatch.delenv("CONTEXTUAL_ENRICHMENT_ENABLED", raising=False)

    settings = settings_module._load_settings()

    assert settings.contextual_enrichment_enabled is False


def test_environment_loads_contextual_enrichment_controls(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def skip_dotenv() -> None:
        return None

    monkeypatch.setattr(settings_module, "_load_dotenv", skip_dotenv)
    monkeypatch.setenv("APP_ENV", "test")
    monkeypatch.setenv("MAX_FILE_SIZE_BYTES", "10485760")
    monkeypatch.setenv("EMBEDDING_PROVIDER", "local")
    monkeypatch.setenv("VECTOR_STORE_BACKEND", "memory")
    monkeypatch.setenv("CONTEXTUAL_ENRICHMENT_ENABLED", "true")
    monkeypatch.setenv("CONTEXTUAL_ENRICHMENT_MODEL", "context-model-v2")
    monkeypatch.setenv("CONTEXTUAL_ENRICHMENT_DOCUMENT_MAX_CHARS", "9000")
    monkeypatch.setenv("CONTEXTUAL_ENRICHMENT_MAX_CONTEXT_CHARS", "500")
    monkeypatch.setenv("CONTEXTUAL_ENRICHMENT_MAX_CONTEXT_WORDS", "42")
    monkeypatch.setenv("CONTEXTUAL_ENRICHMENT_MAX_SEARCH_TERMS", "6")
    monkeypatch.setenv("CONTEXTUAL_ENRICHMENT_MAX_OUTPUT_TOKENS", "180")
    monkeypatch.setenv("CONTEXTUAL_ENRICHMENT_MAX_RETRIES", "1")
    monkeypatch.setenv("CONTEXTUAL_ENRICHMENT_RETRY_BACKOFF_MS", "250")
    monkeypatch.setenv("CONTEXTUAL_ENRICHMENT_STRICT", "true")

    settings = settings_module._load_settings()
    config = settings.context_enrichment_config

    assert settings.contextual_enrichment_enabled is True
    assert config.model == "context-model-v2"
    assert config.document_context_char_limit == 9000
    assert config.max_context_chars == 500
    assert config.max_context_words == 42
    assert config.max_search_terms == 6
    assert config.max_output_tokens == 180
    assert config.max_retries == 1
    assert config.retry_backoff_seconds == 0.25
    assert config.strict is True
