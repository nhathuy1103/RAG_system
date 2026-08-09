from __future__ import annotations

from typing import Protocol


class EmbeddingProvider(Protocol):
    model_name: str

    def embed(self, texts: list[str]) -> list[list[float]]: ...


__all__ = ["EmbeddingProvider"]
