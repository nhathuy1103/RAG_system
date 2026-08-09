"""Retrieval adapter implementations."""

from app.retrieval.adapters.bm25_search import InMemoryBM25RetrievalAdapter
from app.retrieval.adapters.dense_search import HashingDenseRetrievalAdapter
from app.retrieval.adapters.fusion import ReciprocalRankFusion
from app.retrieval.adapters.hybrid_search import (
    HybridRetrievalAdapter,
    IndexableRetrievalPort,
)
from app.retrieval.adapters.local_adaptive import HeuristicAdaptiveClassifier
from app.retrieval.adapters.local_contextualizer import HeuristicContextualizer
from app.retrieval.adapters.local_reformulation import FallbackQueryReformulator
from app.retrieval.adapters.local_reranker import IdentityReranker
from app.retrieval.adapters.local_sufficiency import KeywordOverlapSufficiencyChecker
from app.retrieval.adapters.postgrest_full_text_search import (
    PostgrestFullTextRetrievalAdapter,
)

__all__ = [
    "FallbackQueryReformulator",
    "HashingDenseRetrievalAdapter",
    "HeuristicAdaptiveClassifier",
    "HeuristicContextualizer",
    "HybridRetrievalAdapter",
    "IdentityReranker",
    "IndexableRetrievalPort",
    "InMemoryBM25RetrievalAdapter",
    "KeywordOverlapSufficiencyChecker",
    "PostgrestFullTextRetrievalAdapter",
    "ReciprocalRankFusion",
]
