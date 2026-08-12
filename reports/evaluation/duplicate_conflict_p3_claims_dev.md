# P3 structured claims — DEV

- Pairs: 421
- Configuration: `frozen` / `A5BF4C391C27D7CF4535A6C853A24C55B40453E32F2D38F20B893C84CB34000E`
- Dataset SHA-256: `FB02B62A0B50248209D50B81C02AAD456DC77481498F66A944CEA3FBCDD10D8D`

## Claim and predicate extraction

- Claim P/R/F1: 1.0 / 1.0 / 1.0
- Predicate P/R/F1: 1.0 / 1.0 / 1.0

## Value normalization

- numeric_parse_accuracy: 1.0
- magnitude_accuracy: 1.0
- numeric_and_magnitude_accuracy: 1.0
- unit_accuracy: 1.0
- currency_accuracy: 1.0
- basis_accuracy: 1.0
- operator_accuracy: 1.0
- range_bound_accuracy: 1.0
- boolean_polarity_accuracy: 1.0
- unknown_accuracy: 1.0
- evaluated_claims: 24
- numeric_claims: 21
- boolean_claims: 2
- range_claims: 2
- unknown_claims: 1
- annotation_source: datasets\duplicate_conflict\p3_value_gold_v1.jsonl

## Alignment and conflict

- Alignment P/R/F1: 1.0 / 1.0 / 1.0
- Conflict P/R/F1: 1.0 / 1.0 / 1.0
- Conflict FP/FN: 0 / 0

## Source forms

| Transition | Pairs | Alignment P/R/F1 |
|---|---:|---:|
| prose→prose | 395 | 1.0 / 1.0 / 1.0 |
| table→table | 13 | 1.0 / 1.0 / 1.0 |
| table→prose | 13 | 1.0 / 1.0 / 1.0 |
| table→prose clean bridge | 2 | alignment=1.0; relation=1.0 |
| prose→table | 0 | 0.0 / 0.0 / 0.0 |
| prose→table clean bridge | 2 | alignment=1.0; relation=1.0 |

## Performance

- claim_extraction_ms_per_chunk: mean=1.03626, p50=0.8171, p95=2.6597
- claim_alignment_ms_per_pair: mean=0.076742, p50=0.0922, p95=0.1132
- value_normalization_ms_per_claim: mean=0.017367, p50=0.0181, p95=0.022

## Safety

- false_auto_reuse: 0
- false_entity_merge: 0
- false_conflict_admission: 0
- uncertain_count: 29
- uncertain_rate: 0.084548
- embedding_reuse_mutations: 0

## Failure taxonomy

- P2_GATE_BLOCKED: 5

## Acceptance

- claim_precision: PASS
- claim_recall: PASS
- alignment_precision: PASS
- alignment_recall: PASS
- value_accuracy: PASS
- conflict_precision: PASS
- conflict_recall: PASS
- table_prose: PASS
- prose_table: PASS
- false_auto_reuse: PASS
- false_entity_merge: PASS
- false_conflict_admission: PASS
