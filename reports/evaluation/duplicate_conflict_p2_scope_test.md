# P2 domain entity and business scope — TEST

- Pairs: 179
- Configuration status: `frozen`
- Dataset SHA-256: `F0E14D892E3F5E2D23BF9F1C11A08EFDE668F35FFCCA017B8AD891F2B2D8C0F0`
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

- Scope relation accuracy: 0.843575
- Scope disjoint precision / recall: 0.821429 / 0.807018
- Admission precision / recall: 1.0 / 0.958333
- Admission FP / FN: 0 / 4
- Unknown rate: 0.122905

## Temporal and qualifier compatibility

- Temporal precision / recall / F1: 1.0 / 0.763975 / 0.866197
- Temporal unknown rate: 0.212291
- Qualifier precision / recall / F1: 0.724138 / 0.860656 / 0.786517

## Existing classifier after gate

- Oracle-pair accuracy: 0.363128
- Reached-classifier accuracy: 0.413043
- Conflict precision / recall: 1.0 / 0.586207
- Conflict FP / FN: 0 / 12

## Safety

- False auto-reuse: 0
- False entity merges: 0
- False conflict admissions: 0

## Domain breakdown

| Group | Pairs | Entity P/R/F1 | Admission P/R | Admission FP/FN |
|---|---:|---:|---:|---:|
| vinfast | 86 | 1.0 / 1.0 / 1.0 | 1.0 / 0.916667 | 0 / 4 |
| vinhomes | 93 | 1.0 / 1.0 / 1.0 | 1.0 / 1.0 | 0 / 0 |

## Difficulty breakdown

| Group | Pairs | Entity P/R/F1 | Admission P/R | Admission FP/FN |
|---|---:|---:|---:|---:|
| easy | 21 | 1.0 / 1.0 / 1.0 | 1.0 / 1.0 | 0 / 0 |
| hard | 66 | 1.0 / 1.0 / 1.0 | 1.0 / 0.862069 | 0 / 4 |
| medium | 92 | 1.0 / 1.0 / 1.0 | 1.0 / 1.0 | 0 / 0 |

## Ocr Level breakdown

| Group | Pairs | Entity P/R/F1 | Admission P/R | Admission FP/FN |
|---|---:|---:|---:|---:|
| light | 16 | 1.0 / 1.0 / 1.0 | 1.0 / 1.0 | 0 / 0 |
| medium | 3 | 1.0 / 1.0 / 1.0 | 0.0 / 0.0 | 0 / 0 |
| none | 155 | 1.0 / 1.0 / 1.0 | 1.0 / 0.95 | 0 / 4 |
| severe | 5 | 1.0 / 1.0 / 1.0 | 0.0 / 0.0 | 0 / 0 |

## Ablation

| Layer | Precision | Recall | F1 | False admissions removed vs registry |
|---|---:|---:|---:|---:|
| `legacy_scope_only` | 0.0 | 0.0 | 0.0 | 55 |
| `entity_registry` | 0.635762 | 1.0 | 0.777328 | 0 |
| `plus_vinhomes_scope` | 0.695652 | 1.0 | 0.820513 | 13 |
| `plus_vinfast_scope` | 0.793103 | 0.958333 | 0.867925 | 31 |
| `full_p2_scope_temporal_qualifiers` | 1.0 | 0.958333 | 0.978723 | 55 |

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
- Blocked true conflicts: 4
- Taxonomy: VEHICLE_SCOPE_ERROR=4

## Acceptance

- entity_precision: PASS
- entity_recall: PASS
- admission_precision: PASS
- admission_recall: FAIL
- false_auto_reuse: PASS
- critical_matrix: PASS

Pair-level evidence and complete error records are retained in the JSON report.
