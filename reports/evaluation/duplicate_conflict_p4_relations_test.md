# P4 relation aggregation — TEST

- Pairs: 179
- Configuration: `E61706CD2E6DD60D6B864467430CB9B5D254A2B5D570EBC8E77376D884AAEAFD` (frozen)
- Accuracy: 0.921788
- Macro P/R/F1: 0.929293 / 0.94636 / 0.91677
- Acceptance: **PARTIAL**

## Per-class metrics

| Relation | Support | Precision | Recall | F1 |
|---|---:|---:|---:|---:|
| EXACT_DUPLICATE | 21 | 1.0 | 1.0 | 1.0 |
| NEAR_DUPLICATE | 28 | 1.0 | 1.0 | 1.0 |
| VERSION_UPDATE | 18 | 1.0 | 1.0 | 1.0 |
| TEMPORAL_VARIANT | 18 | 1.0 | 1.0 | 1.0 |
| CONDITIONAL_VARIANT | 29 | 1.0 | 0.655172 | 0.791667 |
| TEMPLATE_VARIANT | 12 | 1.0 | 1.0 | 1.0 |
| CONFLICT | 29 | 1.0 | 0.862069 | 0.925926 |
| DISTINCT | 16 | 1.0 | 1.0 | 1.0 |
| UNCERTAIN | 8 | 0.363636 | 1.0 | 0.533333 |

## Safety

- false_exact_collapse: 0
- false_near_duplicate_suppression: 0
- false_version_supersession: 0
- false_conflict: 0
- missed_conflict: 4
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

- Aggregation ms/pair: {'mean': 0.036123, 'p50': 0.035, 'p95': 0.0464}
- Relation lookup ms: {'mean': 0.006074, 'p50': 0.0058, 'p95': 0.008}
- Retrieval policy ms/query: {'mean': 0.044257, 'p50': 0.0341, 'p95': 0.0931}

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
