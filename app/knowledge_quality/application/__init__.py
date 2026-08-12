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
from app.knowledge_quality.application.authority_policy import (
    AuthorityPolicy,
    EvidencePreference,
    select_preferred_evidence,
)
from app.knowledge_quality.application.business_scope import (
    ScopeTextContext,
    load_or_resolve_business_context,
    resolve_business_context,
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
from app.knowledge_quality.application.conflict_admission import decide_conflict_admission
from app.knowledge_quality.application.entity_resolution import (
    EntityResolutionResult,
    EntityTextContext,
    resolve_entities,
)
from app.knowledge_quality.application.persisted_relation_aggregation import (
    aggregate_persisted_claim_relations,
)
from app.knowledge_quality.application.relation_aggregation import (
    AggregationPolicy,
    aggregate_claim_evidence,
    production_relation_for,
    to_quality_relation_candidate,
)
from app.knowledge_quality.application.relation_clusters import (
    RelationCluster,
    RelationClusterType,
    build_relation_clusters,
)
from app.knowledge_quality.application.scope import (
    compare_claim_scopes,
    extract_claim_scope,
    extract_temporal_scope_qualifiers,
    temporal_scopes_diverge,
)
from app.knowledge_quality.application.version_lineage import (
    VersionLineageEdge,
    VersionLineageResult,
    build_version_lineage,
    determine_version_direction,
    lineage_has_cycle,
)

__all__ = [
    "ConflictEvidence",
    "ChunkDedupPlan",
    "ChunkIdentityConflictError",
    "analyze_text_relation",
    "decide_conflict_admission",
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
    "extract_temporal_scope_qualifiers",
    "EntityResolutionResult",
    "EntityTextContext",
    "load_or_resolve_business_context",
    "loose_normalize_text",
    "normalize_claim_comparison_text",
    "plan_chunk_deduplication",
    "resolve_business_context",
    "resolve_entities",
    "simhash_hamming_distance",
    "simhash_lsh_bands",
    "strict_normalize_text",
    "ScopeTextContext",
    "temporal_scopes_diverge",
    "AggregationPolicy",
    "AuthorityPolicy",
    "EvidencePreference",
    "RelationCluster",
    "RelationClusterType",
    "VersionLineageEdge",
    "VersionLineageResult",
    "aggregate_claim_evidence",
    "aggregate_persisted_claim_relations",
    "build_relation_clusters",
    "build_version_lineage",
    "determine_version_direction",
    "lineage_has_cycle",
    "production_relation_for",
    "select_preferred_evidence",
    "to_quality_relation_candidate",
]
