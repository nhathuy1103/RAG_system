from __future__ import annotations

import hashlib
import math
from dataclasses import dataclass
from typing import Any

from app.infrastructure.telemetry import Telemetry
from app.infrastructure.telemetry.openai import create_openai_client
from app.pipeline.indexing.ports.embedding_provider import EmbeddingProvider


class LocalEmbeddingProvider:
    """Deterministic development/test provider; it is not semantic."""

    model_name = "local-hash-embedding-v1"

    def embed(self, texts: list[str]) -> list[list[float]]:
        return [self._embed_one(text) for text in texts]

    def _embed_one(self, text: str) -> list[float]:
        digest = hashlib.sha256(text.encode("utf-8")).digest()
        values = [((digest[i] / 255.0) * 2) - 1 for i in range(32)]
        norm = math.sqrt(sum(value * value for value in values)) or 1.0
        return [value / norm for value in values]


class OpenAIEmbeddingProvider:
    def __init__(
        self,
        *,
        api_key: str,
        model: str = "text-embedding-3-small",
        base_url: str = "https://api.openai.com/v1",
        timeout_seconds: float = 30.0,
        batch_size: int = 64,
        client: Any | None = None,
        telemetry: Telemetry | None = None,
    ) -> None:
        if not api_key:
            raise ValueError("OPENAI_API_KEY is required for OpenAI embeddings.")
        if not model:
            raise ValueError("OpenAI embedding model must not be empty.")
        if batch_size <= 0:
            raise ValueError("OpenAI embedding batch_size must be > 0.")
        self.model_name = model
        self.batch_size = batch_size
        self._telemetry = telemetry or Telemetry()
        if client is None:
            client = create_openai_client(
                telemetry=self._telemetry,
                api_key=api_key,
                base_url=base_url,
                timeout=timeout_seconds,
            )
        self._client = client

    def embed(self, texts: list[str]) -> list[list[float]]:
        if not texts:
            return []
        vectors: list[list[float]] = []
        for start in range(0, len(texts), self.batch_size):
            batch = texts[start : start + self.batch_size]
            with self._telemetry.observe(
                "embedding.openai_batch",
                as_type="embedding",
                input={
                    "texts": self._telemetry.content(batch),
                    "batch_size": len(batch),
                    "batch_index": start // self.batch_size,
                },
                model=self.model_name,
                model_parameters={"encoding_format": "float"},
            ) as observation:
                response = self._client.embeddings.create(
                    model=self.model_name,
                    input=batch,
                    encoding_format="float",
                )
                response_indexes = [int(item.index) for item in response.data]
                if len(response_indexes) != len(batch):
                    raise RuntimeError(
                        "OpenAI embeddings response count does not match input count."
                    )
                if len(set(response_indexes)) != len(response_indexes):
                    raise RuntimeError("OpenAI embeddings response has duplicate indexes.")
                indexed = {int(item.index): list(item.embedding) for item in response.data}
                if set(indexed) != set(range(len(batch))):
                    raise RuntimeError(
                        "OpenAI embeddings response indexes do not match input indexes."
                    )
                vectors.extend(indexed[index] for index in range(len(batch)))
                usage = getattr(response, "usage", None)
                prompt_tokens = getattr(usage, "prompt_tokens", None)
                observation.update(
                    output={
                        "vector_count": len(indexed),
                        "dimensions": len(indexed[0]) if indexed else 0,
                    },
                    usage_details=(
                        {"input": int(prompt_tokens)} if prompt_tokens is not None else {}
                    ),
                )
        return vectors


@dataclass(frozen=True)
class EmbeddingProviderConfig:
    provider: str = "local"
    openai_api_key: str | None = None
    openai_embedding_model: str = "text-embedding-3-small"
    openai_base_url: str = "https://api.openai.com/v1"
    openai_timeout_seconds: int = 30
    openai_embedding_batch_size: int = 64


def create_embedding_provider(
    config: EmbeddingProviderConfig,
    *,
    telemetry: Telemetry | None = None,
) -> EmbeddingProvider:
    provider = config.provider.strip().lower()
    if provider == "local":
        return LocalEmbeddingProvider()
    if provider != "openai":
        raise ValueError(f"Unsupported EMBEDDING_PROVIDER: {provider}")
    if not config.openai_api_key:
        raise ValueError("OPENAI_API_KEY must be configured when EMBEDDING_PROVIDER=openai.")
    return OpenAIEmbeddingProvider(
        api_key=config.openai_api_key,
        model=config.openai_embedding_model,
        base_url=config.openai_base_url,
        timeout_seconds=config.openai_timeout_seconds,
        batch_size=config.openai_embedding_batch_size,
        telemetry=telemetry,
    )


__all__ = [
    "EmbeddingProviderConfig",
    "LocalEmbeddingProvider",
    "OpenAIEmbeddingProvider",
    "create_embedding_provider",
]
