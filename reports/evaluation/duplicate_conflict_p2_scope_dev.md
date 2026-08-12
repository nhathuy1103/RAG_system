# P2 domain entity and business scope — DEV

- Pairs: 421
- Configuration status: `frozen`
- Dataset SHA-256: `FB02B62A0B50248209D50B81C02AAD456DC77481498F66A944CEA3FBCDD10D8D`
- Configuration SHA-256: `A80DC727BEB035C6FBF89373E83129A7E40FB347872815A8477574EB6FB05458`

## Frozen P1 state

- DEV Candidate Recall@50: 1.0
- Existing frozen TEST Candidate Recall@50: 1.0
- P1 retuned in P2: False

## Entity resolution

- Precision: 1.0
- Recall: 1.0
- F1: 1.0
- Same-entity pair accuracy: 1.0
- Different-entity pair accuracy: 1.0
- Entity unknown rate: 0.0
- False merges: 0

## Scope and conflict admission

- Scope relation accuracy: 0.874109
- Scope disjoint precision / recall: 0.777778 / 0.81982
- Admission precision / recall: 1.0 / 0.979079
- Admission FP / FN: 0 / 5
- Unknown rate: 0.097387

## Temporal and qualifier compatibility

- Temporal precision / recall / F1: 1.0 / 0.749319 / 0.856698
- Temporal unknown rate: 0.218527
- Qualifier precision / recall / F1: 0.756831 / 0.893548 / 0.819527

## Existing classifier after gate

- Oracle-pair accuracy: 0.380048
- Reached-classifier accuracy: 0.401709
- Conflict precision / recall: 0.916667 / 0.696203
- Conflict FP / FN: 5 / 24

## Safety

- False auto-reuse: 0
- False entity merges: 0
- False conflict admissions: 0

## Domain breakdown

| Group | Pairs | Entity P/R/F1 | Admission P/R | Admission FP/FN |
|---|---:|---:|---:|---:|
| vinfast | 214 | 1.0 / 1.0 / 1.0 | 1.0 / 0.957265 | 0 / 5 |
| vinhomes | 207 | 1.0 / 1.0 / 1.0 | 1.0 / 1.0 | 0 / 0 |

## Difficulty breakdown

| Group | Pairs | Entity P/R/F1 | Admission P/R | Admission FP/FN |
|---|---:|---:|---:|---:|
| easy | 39 | 1.0 / 1.0 / 1.0 | 1.0 / 1.0 | 0 / 0 |
| hard | 144 | 1.0 / 1.0 / 1.0 | 1.0 / 0.940476 | 0 / 5 |
| medium | 238 | 1.0 / 1.0 / 1.0 | 1.0 / 1.0 | 0 / 0 |

## Ocr Level breakdown

| Group | Pairs | Entity P/R/F1 | Admission P/R | Admission FP/FN |
|---|---:|---:|---:|---:|
| light | 33 | 1.0 / 1.0 / 1.0 | 1.0 / 1.0 | 0 / 0 |
| medium | 7 | 1.0 / 1.0 / 1.0 | 0.0 / 0.0 | 0 / 0 |
| none | 366 | 1.0 / 1.0 / 1.0 | 1.0 / 0.975124 | 0 / 5 |
| severe | 15 | 1.0 / 1.0 / 1.0 | 1.0 / 1.0 | 0 / 0 |

## Ablation

| Layer | Precision | Recall | F1 | False admissions removed vs registry |
|---|---:|---:|---:|---:|
| `legacy_scope_only` | 0.0 | 0.0 | 0.0 | 114 |
| `entity_registry` | 0.677054 | 1.0 | 0.807432 | 0 |
| `plus_vinhomes_scope` | 0.709199 | 1.0 | 0.829861 | 16 |
| `plus_vinfast_scope` | 0.787879 | 0.979079 | 0.873134 | 51 |
| `full_p2_scope_temporal_qualifiers` | 1.0 | 0.979079 | 0.989429 | 114 |

## Critical case matrix

| Case | Result |
|---|---:|
| `vinhomes_different_project` | PASS |
| `vinhomes_different_phase` | PASS |
| `vinhomes_different_building` | PASS |
| `vinhomes_different_unit` | PASS |
| `vinhomes_2pn_vs_3pn` | PASS |
| `vinhomes_official_vs_secondary` | PASS |
| `vinhomes_asking_vs_transaction` | PASS |
| `vinhomes_per_unit_vs_per_m2` | PASS |
| `vinhomes_2025_vs_2026` | PASS |
| `vinfast_vf8_vs_vf9` | PASS |
| `vinfast_eco_vs_plus` | PASS |
| `vinfast_model_year` | PASS |
| `vinfast_market` | PASS |
| `vinfast_protocol` | PASS |
| `vinfast_battery_variant` | PASS |
| `vinfast_charging_condition` | PASS |
| `true_vinhomes_price` | PASS |
| `true_vinfast_range` | PASS |

## Remaining P2 errors

- Missed entity resolutions: 0
- False conflict admissions: 0
- Blocked true conflicts: 5
- Taxonomy: VEHICLE_SCOPE_ERROR=5

## Acceptance

- entity_precision: PASS
- entity_recall: PASS
- admission_precision: PASS
- admission_recall: PASS
- false_auto_reuse: PASS
- critical_matrix: PASS

Pair-level evidence and complete error records are retained in the JSON report.
