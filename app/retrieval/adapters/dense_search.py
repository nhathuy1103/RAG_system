"""In-memory dense retrieval — SPEC step ⑥, dense half. Hashed-trigram placeholder."""

from __future__ import annotations

import hashlib
import math
from dataclasses import dataclass, field

from app.retrieval.adapters.scope_filter import matches_scope
from app.retrieval.domain.models import (
    EvidenceChunk,
    RetrievalCandidate,
    RetrievalFilters,
)

_DIMENSIONS = 256
_NGRAM_SIZE = 3


def _char_ngrams(text: str, *, n: int = _NGRAM_SIZE) -> list[str]:
    normalized = f"  {text.lower().strip()}  "
    if len(normalized) < n:
        return [normalized]
    return [normalized[i : i + n] for i in range(len(normalized) - n + 1)]


def _hash_bucket(token: str, dimensions: int) -> int:
    """Deterministic hash — Python's built-in ``hash()`` is randomized per
    process for strings, which would make embeddings non-reproducible."""
    digest = hashlib.md5(token.encode("utf-8")).digest()
    return int.from_bytes(digest[:4], "big") % dimensions


def embed(text: str, *, dimensions: int = _DIMENSIONS) -> tuple[float, ...]:
    """Deterministic hashed character-trigram embedding, L2-normalized."""
    vector = [0.0] * dimensions
    for ngram in _char_ngrams(text):
        vector[_hash_bucket(ngram, dimensions)] += 1.0
    norm = math.sqrt(sum(component * component for component in vector))
    if norm == 0.0:
        return tuple(vector)
    return tuple(component / norm for component in vector)


def cosine_similarity(a: tuple[float, ...], b: tuple[float, ...]) -> float:
    """Both vectors from ``embed`` are already L2-normalized, so cosine
    similarity is just their dot product."""
    return sum(x * y for x, y in zip(a, b, strict=True))


@dataclass
class HashingDenseRetrievalAdapter:
    """Cosine-similarity search over hashed character-trigram embeddings."""

    _chunks: dict[str, EvidenceChunk] = field(default_factory=dict, repr=False)
    _vectors: dict[str, tuple[float, ...]] = field(default_factory=dict, repr=False)

    def index(self, chunk: EvidenceChunk) -> None:
        self._chunks[chunk.id] = chunk
        self._vectors[chunk.id] = embed(chunk.text)

    def search(
        self,
        query: str,
        filters: RetrievalFilters,
        *,
        top_k: int,
    ) -> tuple[RetrievalCandidate, ...]:
        if top_k <= 0:
            raise ValueError("top_k must be > 0")

        query_vector = embed(query)
        scored: list[tuple[float, str]] = []
        for chunk_id, chunk in self._chunks.items():
            if not matches_scope(chunk, filters):
                continue
            similarity = cosine_similarity(query_vector, self._vectors[chunk_id])
            if similarity <= 0.0:
                continue
            scored.append((similarity, chunk_id))

        scored.sort(key=lambda item: (-item[0], item[1]))
        return tuple(
            RetrievalCandidate(chunk=self._chunks[chunk_id], score=score, rank=rank, source="dense")
            for rank, (score, chunk_id) in enumerate(scored[:top_k], start=1)
        )


__all__ = ["HashingDenseRetrievalAdapter", "cosine_similarity", "embed"]
