# P4 relation aggregation — DEV

- Pairs: 421
- Configuration: `E61706CD2E6DD60D6B864467430CB9B5D254A2B5D570EBC8E77376D884AAEAFD` (frozen)
- Accuracy: 0.942993
- Macro P/R/F1: 0.942029 / 0.943872 / 0.925644
- Acceptance: **PARTIAL**

## Per-class metrics

| Relation | Support | Precision | Recall | F1 |
|---|---:|---:|---:|---:|
| EXACT_DUPLICATE | 39 | 1.0 | 1.0 | 1.0 |
| NEAR_DUPLICATE | 62 | 1.0 | 1.0 | 1.0 |
| VERSION_UPDATE | 54 | 1.0 | 1.0 | 1.0 |
| TEMPORAL_VARIANT | 54 | 1.0 | 1.0 | 1.0 |
| CONDITIONAL_VARIANT | 43 | 1.0 | 0.55814 | 0.716418 |
| TEMPLATE_VARIANT | 30 | 1.0 | 1.0 | 1.0 |
| CONFLICT | 79 | 1.0 | 0.936709 | 0.96732 |
| DISTINCT | 38 | 1.0 | 1.0 | 1.0 |
| UNCERTAIN | 22 | 0.478261 | 1.0 | 0.647059 |

## Safety

- false_exact_collapse: 0
- false_near_duplicate_suppression: 0
- false_version_supersession: 0
- false_conflict: 0
- missed_conflict: 5
- conflict_suppression: 0
- provenance_loss: 0
- permission_relation_leakage: 0
- p2_disjoint_to_conflict: 0
- false_automatic_embedding_reuse: 0

## Version

- Lineage accuracy: 1.0
- Direction accuracy: 1.0
- Current selection: 1.0
- Historical selection: 1.0
- Unknown current validity preserved: 1.0
- Cycles: 0

## Retrieval

- Duplicate Redundancy@K: {'before': 0.333333, 'after': 0.0}
- Unique Evidence@K: {'before': 4, 'after': 6}
- Document Diversity@K: {'before': 6, 'after': 6}
- Conflict Preservation Recall@K: 1.0
- Temporal Match@K: 1.0
- Base relevance recall: {'before': 1.0, 'after': 1.0, 'delta': 0.0}
- Context impact: {'before_chunks': 21, 'after_evidence_items': 13, 'before_characters': 430, 'after_characters': 280, 'character_reduction': 0.348837, 'chunk_reduction': 0.380952}

## Performance

- Aggregation ms/pair: {'mean': 0.035818, 'p50': 0.0348, 'p95': 0.0473}
- Relation lookup ms: {'mean': 0.006149, 'p50': 0.0058, 'p95': 0.0085}
- Retrieval policy ms/query: {'mean': 0.044486, 'p50': 0.036, 'p95': 0.0947}

## Acceptance

- p1_recall_at_50: PASS
- p2_p3_safety: PASS
- macro_f1: FAIL
- exact_duplicate_precision: PASS
- conflict_precision: PASS
- conflict_recall: FAIL
- version_update_precision: PASS
- near_duplicate_precision: PASS
- false_exact_collapse: PASS
- conflict_suppression: PASS
- provenance_loss: PASS
- permission_leakage: PASS
- duplicate_redundancy_reduced: PASS
- unique_evidence_maintained: PASS
- conflict_preservation: PASS
- provenance_retention: PASS
- base_relevance_not_regressed: PASS
- unknown_current_validity_preserved: PASS
