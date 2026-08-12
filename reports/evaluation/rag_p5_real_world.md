# P5 relation-aware RAG — REAL_WORLD

- Queries: 100
- Configuration: `0758D6A9EC3793B911718B0B8DDD3FF897F9F07AB7976791CA706BDC850F9F17` (frozen)
- Acceptance: **PASS**

## Dataset overview

- controlled: False
- synthetic_count: 0
- real_world_adversarial_count: 100

## Query-type breakdown

- ADVERSARIAL: {"citation_support": 1.0, "count": 100, "evidence_recall_at_10": 1.0, "fact_f1": null}

## Retrieval metrics

- Evidence Recall@10: 1.000000
- Evidence Precision@10: 1.000000
- Conflict Preservation: 1.000000
- Current/Historical/Conditional: 1.000000 / 1.000000 / 1.000000
- Duplicate redundancy before/after: {'before': 0.0, 'after': 0.0}

## Context metrics

- Raw/post-relation/final tokens: 1520 / 1520 / 1520
- Final token reduction: 0.000000
- Conflict/temporal completeness: 1.000000 / 1.000000

## Answer metrics

- Fact P/R/F1: not scored / not scored / not scored
- Conflict disclosure: 1.000000
- Conditional distinction: 1.000000
- Temporal accuracy: 1.000000
- No-answer P/R: 1.000000 / 1.000000

## Citation metrics

- Precision/coverage/support: 1.000000 / 1.000000 / 1.000000
- Conflict both-sides citation: 1.000000
- Unauthorized/fabricated: 0.000000 / 0.000000

## Conflict metrics

- preservation_recall: 1.0
- disclosure_recall: 1.0
- false_disclosure_rate: 0.0
- no_arbitrary_winner_rate: 1.0
- both_sides_citation_rate: 1.0

## Temporal/version metrics

- current_version_accuracy: 1.0
- historical_version_accuracy: 1.0
- temporal_accuracy: 1.0
- temporal_completeness: 1.0
- current_version_guessing_when_unknown: 0

## Conditional metrics

- match_accuracy: 1.0
- distinction_accuracy: 1.0
- false_conflict_rate: 1.0
- unknown_scope_fabrication: 0

## No-answer metrics

- precision: 1.0
- recall: 1.0
- false_answer_when_no_evidence: 0
- over_abstention_count: 0

## Security metrics

- permission_leakage: 0
- hidden_relation_leakage: 0
- hidden_provenance_leakage: 0
- prompt_injection_policy_bypass: 0
- unauthorized_citation: 0
- fabricated_citation_id: 0

## Latency

- method: same-run proxy subtracting measured P5 policy/context/citation bookkeeping; not a live provider or database latency baseline
- baseline_proxy_p50: 0.09245
- baseline_proxy_p95: 0.139745
- p5_total_p50: 0.18155
- p5_total_p95: 0.279815
- incremental_bookkeeping_p50: 0.0882
- incremental_bookkeeping_p95: 0.145705
- pathological_regression_observed: False

## Token usage

- provider_usage_available: False
- reason: controlled deterministic generator; no provider call
- raw_context_tokens: 1520
- post_relation_tokens: 1520
- final_context_tokens: 1520
- output_tokens_estimated: 1280

## Ablation

- method: "Measured layer outcomes and deterministic policy slices; these are not claimed as causal model-quality estimates."
- A_hybrid_only: {"context_tokens": 1520, "evidence_precision": 1.0, "evidence_recall": 1.0}
- B_plus_reranker: {"context_tokens": 1520, "evidence_precision": 1.0, "evidence_recall": 1.0}
- C_plus_p4_relation_policy: {"context_tokens": 1520, "duplicate_redundancy": 0.0, "evidence_precision": 1.0, "evidence_recall": 1.0}
- D_plus_temporal_version: {"context_tokens": 1520, "evidence_recall": 1.0, "fact_f1": null, "temporal_accuracy": 1.0}
- E_plus_authority: {"authority_erased_conflict_count": 0, "conflict_preservation": 1.0}
- F_plus_conflict_context: {"both_sides_preserved": 1.0, "conflict_disclosure": 1.0}
- G_plus_generation_contract: {"conflict_disclosure": 1.0, "context_tokens": 1520, "fact_f1": null}
- H_plus_citation_validation: {"citation_support": 1.0, "fabricated_citations": 0, "fact_f1": null}
- relation_policy_ablation: {"with_authority_preference_conflict_preservation": 1.0, "with_conflict_preservation_disclosure": 1.0, "with_duplicate_suppression_redundancy": 0.0, "with_qualifier_policy_accuracy": 1.0, "with_version_selection_wrong_latest_rate": 0.0, "without_authority_preference_conflict_preservation": 1.0, "without_conflict_preservation_disclosure": 0.0, "without_duplicate_suppression_redundancy": 0.0, "without_qualifier_policy_accuracy": 1.0, "without_version_selection_wrong_latest_rate": 0.0}

## P1-P4 regression

- p1_candidate_recall_at_50_dev: 1.0
- p1_candidate_recall_at_50_test: 1.0
- p2_false_entity_merge: 0
- p2_false_conflict_admission: 0
- p3_claim_alignment_false_positive: 0
- p3_claim_conflict_false_positive: 0
- p4_false_exact_collapse: 0
- p4_false_near_suppression: 0
- p4_false_version_supersession: 0
- p4_false_conflict: 0
- p4_conflict_suppression: 0
- p4_provenance_loss: 0
- p4_permission_leakage: 0
- p4_frozen_test_rerun: False

## Acceptance

- evidence_recall_at_10: PASS
- citation_support_accuracy: PASS
- citation_coverage: PASS
- no_answer_precision: PASS
- no_answer_recall: PASS
- permission_leakage: PASS
- hidden_relation_leakage: PASS
- hidden_provenance_leakage: PASS
- prompt_injection_bypass: PASS
- unauthorized_citation: PASS
- fabricated_citation_id: PASS
- unknown_scope_fabrication: PASS

## Failure taxonomy

- QUERY_INTENT_ERROR: 0
- TEMPORAL_INTENT_ERROR: 0
- ENTITY_QUERY_ERROR: 0
- RETRIEVAL_MISS: 0
- RERANK_ERROR: 0
- RELATION_POLICY_ERROR: 0
- DUPLICATE_SUPPRESSION_ERROR: 0
- VERSION_SELECTION_ERROR: 0
- CONFLICT_PRESERVATION_ERROR: 0
- CONDITIONAL_SELECTION_ERROR: 0
- AUTHORITY_SELECTION_ERROR: 0
- CONTEXT_BUDGET_ERROR: 0
- GENERATION_FACT_ERROR: 0
- GENERATION_CONFLICT_ERROR: 0
- GENERATION_TEMPORAL_ERROR: 0
- GENERATION_UNCERTAINTY_ERROR: 0
- CITATION_MAPPING_ERROR: 0
- CITATION_SUPPORT_ERROR: 0
- NO_ANSWER_ERROR: 0
- PERMISSION_LEAK: 0
- PROMPT_INJECTION_ERROR: 0
