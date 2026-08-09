# Vietnamese Knowledge-Quality Benchmark v1

Deterministic report generated from `tests/evaluation/data/knowledge_quality_vi_v1.jsonl`.
This is a labeled regression and policy-proxy benchmark, not a claim about production embedding quality.

## Dataset

- Cases: 29
- Eligible same-scope relation cases: 26
- Explicit cross-scope safety cases: 3
- Dataset SHA-256: `08b69d1ef5868c7e8fc0323133ec7d5ac4d94312b2509ed81f8682630ae6a0f9`

## Relation classification

- Accuracy: 1.000
- Macro F1: 1.000

| Class | Precision | Recall | F1 | Support |
|---|---:|---:|---:|---:|
| exact | 1.000 | 1.000 | 1.000 | 5 |
| near_duplicate | 1.000 | 1.000 | 1.000 | 5 |
| version | 1.000 | 1.000 | 1.000 | 5 |
| conflict | 1.000 | 1.000 | 1.000 | 6 |
| distinct | 1.000 | 1.000 | 1.000 | 5 |

## Safety

| Metric | Value |
|---|---:|
| Exact auto-reuse false-positive rate | 0.000 |
| Exact auto-reuse false-discovery rate | 0.000 |
| Exact auto-reuse recall | 1.000 |
| Cross-scope suppression rate | 1.000 |

## Off vs shadow vs on retrieval-quality proxy

`off` and `shadow` retain both documents. `on` applies safe exact reuse and confirmed version preference while preserving both sides of conflicts and unresolved fuzzy matches.

| Mode | Quality proxy | Selection exact match | Duplicate redundancy | Stale version exposure | Conflict both sides |
|---|---:|---:|---:|---:|---:|
| off | 0.872 | 0.615 | 1.000 | 1.000 | 1.000 |
| shadow | 0.872 | 0.615 | 1.000 | 1.000 | 1.000 |
| on | 1.000 | 1.000 | 0.000 | 0.000 | 1.000 |

## Gates

Overall: **PASS**

| Gate | Measured | Requirement | Result |
|---|---:|---|:---:|
| minimum_per_class_f1 | 1.000 | `>= 0.85` | PASS |
| macro_f1 | 1.000 | `>= 0.9` | PASS |
| conflict_recall | 1.000 | `>= 1.0` | PASS |
| exact_auto_reuse_false_positive_rate | 0.000 | `<= 0.0` | PASS |
| exact_auto_reuse_recall | 1.000 | `>= 1.0` | PASS |
| cross_scope_suppression_rate | 1.000 | `>= 1.0` | PASS |
| shadow_behavior_matches_off | 1.000 | `>= 1.0` | PASS |
| on_retrieval_quality_proxy | 1.000 | `>= 0.95` | PASS |
| on_quality_improvement_over_off | 0.128 | `>= 0.1` | PASS |
| on_duplicate_redundancy_rate | 0.000 | `<= 0.0` | PASS |
| on_stale_version_exposure_rate | 0.000 | `<= 0.0` | PASS |
| on_current_version_hit_rate | 1.000 | `>= 1.0` | PASS |
| on_conflict_both_sides_rate | 1.000 | `>= 1.0` | PASS |
| on_distinct_preservation_rate | 1.000 | `>= 1.0` | PASS |

## Misclassified eligible cases

None.
