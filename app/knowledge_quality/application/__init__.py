from app.knowledge_quality.application.analysis import (
    ConflictEvidence,
    analyze_text_relation,
    build_chunk_fingerprint,
    build_document_fingerprint,
    build_legacy_document_fingerprint,
    detect_conflicts,
    loose_normalize_text,
    strict_normalize_text,
)
from app.knowledge_quality.application.chunk_preembedding import (
    ChunkDedupPlan,
    ChunkIdentityConflictError,
    build_chunk_dedup_probes,
    plan_chunk_deduplication,
    simhash_hamming_distance,
    simhash_lsh_bands,
)
from app.knowledge_quality.application.claims import (
    classify_numeric_mentions,
    detect_claim_conflicts,
    extract_claims,
    normalize_claim_comparison_text,
)
from app.knowledge_quality.application.scope import (
    compare_claim_scopes,
    extract_claim_scope,
)

__all__ = [
    "ConflictEvidence",
    "ChunkDedupPlan",
    "ChunkIdentityConflictError",
    "analyze_text_relation",
    "build_chunk_fingerprint",
    "build_document_fingerprint",
    "build_legacy_document_fingerprint",
    "build_chunk_dedup_probes",
    "classify_numeric_mentions",
    "compare_claim_scopes",
    "detect_conflicts",
    "detect_claim_conflicts",
    "extract_claims",
    "extract_claim_scope",
    "loose_normalize_text",
    "normalize_claim_comparison_text",
    "plan_chunk_deduplication",
    "simhash_hamming_distance",
    "simhash_lsh_bands",
    "strict_normalize_text",
]
