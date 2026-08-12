# P3 structured claims — TEST

- Pairs: 179
- Configuration: `frozen` / `A5BF4C391C27D7CF4535A6C853A24C55B40453E32F2D38F20B893C84CB34000E`
- Dataset SHA-256: `F0E14D892E3F5E2D23BF9F1C11A08EFDE668F35FFCCA017B8AD891F2B2D8C0F0`

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
- evaluated_claims: 16
- numeric_claims: 13
- boolean_claims: 2
- range_claims: 1
- unknown_claims: 1
- annotation_source: datasets\duplicate_conflict\p3_value_gold_v1.jsonl

## Alignment and conflict

- Alignment P/R/F1: 1.0 / 1.0 / 1.0
- Conflict P/R/F1: 1.0 / 1.0 / 1.0
- Conflict FP/FN: 0 / 0

## Source forms

| Transition | Pairs | Alignment P/R/F1 |
|---|---:|---:|
| prose→prose | 169 | 1.0 / 1.0 / 1.0 |
| table→table | 5 | 1.0 / 1.0 / 1.0 |
| table→prose | 5 | 1.0 / 1.0 / 1.0 |
| table→prose clean bridge | 2 | alignment=1.0; relation=1.0 |
| prose→table | 0 | 0.0 / 0.0 / 0.0 |
| prose→table clean bridge | 2 | alignment=1.0; relation=1.0 |

## Performance

- claim_extraction_ms_per_chunk: mean=1.03848, p50=0.8198, p95=3.1914
- claim_alignment_ms_per_pair: mean=0.084108, p50=0.078, p95=0.1122
- value_normalization_ms_per_claim: mean=0.015801, p50=0.0164, p95=0.0209

## Safety

- false_auto_reuse: 0
- false_entity_merge: 0
- false_conflict_admission: 0
- uncertain_count: 15
- uncertain_rate: 0.100671
- embedding_reuse_mutations: 0

## Failure taxonomy

- P2_GATE_BLOCKED: 4

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
