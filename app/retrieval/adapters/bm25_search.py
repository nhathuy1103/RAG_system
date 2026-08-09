"""In-memory Okapi BM25 retrieval — SPEC step ⑥, sparse half. Real BM25 math, dict storage."""

from __future__ import annotations

import math
from collections import Counter
from dataclasses import dataclass, field

from app.retrieval.adapters.keyword_matching import tokenize_list
from app.retrieval.adapters.scope_filter import matches_scope
from app.retrieval.domain.models import (
    EvidenceChunk,
    RetrievalCandidate,
    RetrievalFilters,
)

_K1 = 1.5
_B = 0.75


@dataclass
class InMemoryBM25RetrievalAdapter:
    """Okapi BM25 over an in-memory chunk store."""

    _chunks: dict[str, EvidenceChunk] = field(default_factory=dict, repr=False)
    _term_frequencies: dict[str, Counter[str]] = field(default_factory=dict, repr=False)
    _doc_lengths: dict[str, int] = field(default_factory=dict, repr=False)
    _document_frequency: Counter[str] = field(default_factory=Counter, repr=False)

    def index(self, chunk: EvidenceChunk) -> None:
        tokens = tokenize_list(chunk.search_text or chunk.text)
        self._chunks[chunk.id] = chunk
        self._term_frequencies[chunk.id] = Counter(tokens)
        self._doc_lengths[chunk.id] = len(tokens)
        for term in set(tokens):
            self._document_frequency[term] += 1

    def _idf(self, term: str) -> float:
        n = len(self._chunks)
        df = self._document_frequency.get(term, 0)
        return math.log((n - df + 0.5) / (df + 0.5) + 1)

    def _score(self, chunk_id: str, query_terms: list[str], avg_doc_length: float) -> float:
        term_frequencies = self._term_frequencies[chunk_id]
        doc_length = self._doc_lengths[chunk_id]
        score = 0.0
        for term in query_terms:
            frequency = term_frequencies.get(term, 0)
            if frequency == 0:
                continue
            idf = self._idf(term)
            numerator = frequency * (_K1 + 1)
            denominator = frequency + _K1 * (1 - _B + _B * doc_length / avg_doc_length)
            score += idf * (numerator / denominator)
        return score

    def search(
        self,
        query: str,
        filters: RetrievalFilters,
        *,
        top_k: int,
    ) -> tuple[RetrievalCandidate, ...]:
        if top_k <= 0:
            raise ValueError("top_k must be > 0")
        if not self._chunks:
            return ()

        query_terms = tokenize_list(query)
        if not query_terms:
            return ()

        in_scope_ids = [
            chunk_id for chunk_id, chunk in self._chunks.items() if matches_scope(chunk, filters)
        ]
        if not in_scope_ids:
            return ()

        # avgdl is a corpus-wide statistic (BM25 is normally one shared index
        # with per-query filters), not recomputed per tenant.
        avg_doc_length = sum(self._doc_lengths.values()) / len(self._doc_lengths)

        scored = [
            (self._score(chunk_id, query_terms, avg_doc_length), chunk_id)
            for chunk_id in in_scope_ids
        ]
        scored = [(score, chunk_id) for score, chunk_id in scored if score > 0.0]
        scored.sort(key=lambda item: (-item[0], item[1]))

        return tuple(
            RetrievalCandidate(chunk=self._chunks[chunk_id], score=score, rank=rank, source="bm25")
            for rank, (score, chunk_id) in enumerate(scored[:top_k], start=1)
        )


__all__ = ["InMemoryBM25RetrievalAdapter"]
