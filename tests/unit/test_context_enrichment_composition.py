from app.pipeline.bootstrap.composition import build_chunk_context_enricher
from app.pipeline.bootstrap.settings import Settings
from app.pipeline.indexing.adapters.context_enrichers import OpenAIChunkContextEnricher


def test_composition_builds_openai_context_enricher_when_enabled() -> None:
    enricher = build_chunk_context_enricher(
        Settings(
            app_env="test",
            openai_api_key="test-key",
            contextual_enrichment_enabled=True,
            contextual_enrichment_model="gpt-4o-mini",
        )
    )

    assert isinstance(enricher, OpenAIChunkContextEnricher)
    assert enricher.config.model == "gpt-4o-mini"
    assert enricher.profile["contextual_enrichment_prompt_version"] == "chunk-context-v4"


def test_composition_keeps_offline_pipeline_deterministic_without_key() -> None:
    assert build_chunk_context_enricher(Settings(app_env="test")) is None
    assert (
        build_chunk_context_enricher(
            Settings(
                app_env="test",
                openai_api_key="test-key",
            )
        )
        is None
    )
    assert (
        build_chunk_context_enricher(
            Settings(
                app_env="test",
                openai_api_key="test-key",
                contextual_enrichment_enabled=False,
            )
        )
        is None
    )
