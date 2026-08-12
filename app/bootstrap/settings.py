"""Environment-backed application settings."""

from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import AnyHttpUrl, Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Validated settings shared by API dependencies and composition roots."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    app_env: Literal["development", "test", "production"] = "development"
    supabase_url: AnyHttpUrl | None = None
    supabase_publishable_key: str | None = None
    supabase_service_role_key: SecretStr | None = None
    supabase_jwt_audience: str = "authenticated"
    cors_origins: list[str] = Field(
        default_factory=lambda: [
            "http://localhost:5173",
            "http://127.0.0.1:5173",
        ]
    )
    ingestion_worker_enabled: bool = True
    ingestion_worker_concurrency: int = Field(default=2, ge=1, le=8)
    ingestion_worker_poll_seconds: float = Field(default=2.0, gt=0)
    ingestion_worker_lease_seconds: int = Field(default=1800, ge=30)

    llm_temperature: float = Field(default=0.2, ge=0, le=2)
    llm_max_output_tokens: int | None = Field(default=None, gt=0)
    llm_timeout_seconds: float = Field(default=30.0, gt=0)
    llm_max_retries: int = Field(default=2, ge=0)
    generation_allow_outside_knowledge: bool = False
    chat_history_max_turns: int = Field(default=6, gt=0)

    retrieval_sparse_top_k: int = Field(default=20, gt=0)
    retrieval_dense_top_k: int = Field(default=20, gt=0)
    retrieval_final_top_k: int = Field(default=6, gt=0)
    retrieval_rrf_k: int = Field(default=60, gt=0)
    retrieval_min_dense_score: float | None = None
    retrieval_mmr_lambda: float = Field(default=0.7, ge=0.0, le=1.0)
    retrieval_max_chunks_per_document: int = Field(default=2, ge=1, le=20)
    retrieval_document_scope_planner_mode: Literal["off", "shadow", "on"] = "off"
    retrieval_structured_filters_enabled: bool = False
    retrieval_structured_filter_fields: str = "project_code"
    retrieval_project_registry_path: Path | None = None

    @property
    def retrieval_structured_filter_field_set(self) -> frozenset[str]:
        return frozenset(
            value.strip()
            for value in self.retrieval_structured_filter_fields.split(",")
            if value.strip()
        )

    knowledge_quality_mode: Literal["off", "shadow", "on"] = "on"
    knowledge_quality_max_probe_chunks: int = Field(default=8, ge=1, le=32)
    knowledge_quality_candidates_per_probe: int = Field(default=5, ge=1, le=20)
    knowledge_candidate_generation_mode: Literal["legacy", "shadow", "on"] = "shadow"
    knowledge_candidate_channel_k: int = Field(default=30, ge=1, le=50)
    knowledge_candidate_final_top_k: int = Field(default=50, ge=1, le=50)
    knowledge_quality_conflict_prompt_enabled: bool = True
    structured_fact_mode: Literal["off", "shadow", "on"] = "off"
    rag_p5_mode: Literal["off", "shadow", "on"] = "shadow"
    rag_p5_context_max_items: int = Field(default=10, ge=1, le=50)
    rag_p5_context_max_characters: int = Field(default=12_000, ge=500, le=200_000)
    rag_p5_characters_per_token: float = Field(default=4.0, gt=0)
    rag_p5_near_duplicate_representatives: int = Field(default=1, ge=1, le=5)

    langfuse_enabled: bool = False
    langfuse_public_key: str | None = None
    langfuse_secret_key: SecretStr | None = None
    langfuse_base_url: AnyHttpUrl = AnyHttpUrl("https://cloud.langfuse.com")
    langfuse_environment: str | None = None
    langfuse_release: str | None = None
    langfuse_sample_rate: float = Field(default=1.0, ge=0.0, le=1.0)
    langfuse_capture_content: bool = False

    @property
    def is_development(self) -> bool:
        return self.app_env == "development"

    @property
    def supabase_issuer(self) -> str | None:
        if self.supabase_url is None:
            return None
        return f"{str(self.supabase_url).rstrip('/')}/auth/v1"

    @property
    def supabase_jwks_url(self) -> str | None:
        if self.supabase_issuer is None:
            return None
        return f"{self.supabase_issuer}/.well-known/jwks.json"

    @property
    def supabase_rest_url(self) -> str | None:
        if self.supabase_url is None:
            return None
        return f"{str(self.supabase_url).rstrip('/')}/rest/v1"

    @property
    def supabase_storage_url(self) -> str | None:
        if self.supabase_url is None:
            return None
        return f"{str(self.supabase_url).rstrip('/')}/storage/v1"

    @property
    def ingestion_worker_is_configured(self) -> bool:
        if (
            not self.ingestion_worker_enabled
            or self.supabase_url is None
            or self.supabase_service_role_key is None
        ):
            return False
        return bool(self.supabase_service_role_key.get_secret_value().strip())

    @property
    def langfuse_is_configured(self) -> bool:
        if not self.langfuse_enabled:
            return False
        return bool(
            self.langfuse_public_key
            and self.langfuse_secret_key
            and self.langfuse_secret_key.get_secret_value().strip()
        )


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Load and cache settings for the current process."""
    return Settings()
