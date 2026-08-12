# Enterprise P6 DEV evaluation

Queries: **160**

## Metrics

- evidence_recall_at_10: `1.000000`
- evidence_precision_at_10: `0.697917`
- mrr: `0.775000`
- ndcg_at_10: `0.833918`
- temporal_coverage_recall: `1.000000`
- requested_year_coverage: `1.000000`
- followup_resolution_accuracy: `1.000000`
- value_bearing_evidence_recall: `1.000000`
- historical_selection_accuracy: `1.000000`
- current_version_accuracy: `1.000000`
- conditional_selection_accuracy: `1.000000`
- conflict_preservation_recall: `1.000000`
- permission_leakage: `0.000000`
- citation_support_accuracy: `1.000000`
- provenance_retention: `1.000000`
- duplicate_slot_waste_baseline: `0.750000`
- duplicate_slot_waste_p6: `0.000000`

## Latency

Controlled in-process timing only; production PostgreSQL EXPLAIN and SLA remain unresolved.

- mean: `0.7435 ms`
- p50: `0.6955 ms`
- p95: `1.0154 ms`

Failures: **0**

## Dataset and architecture

The DEV split contains 160 controlled queries: 10 cases in each of 16 required
categories. The legacy baseline was `raw question + OR history -> sparse/dense
-> RRF -> generic MMR -> raw chunks`. P6 is `bounded QueryContext -> canonical
temporal retrieval -> one batched P4 enrichment -> duplicate/temporal/conflict
policy -> value utility -> protected MMR -> P5 GenerationContext -> fail-closed
citations`.

## Query context and follow-up

Follow-up intent, inherited entity/predicate and temporal override accuracy were
1.000. Wrong-history carryover was 0 on controlled cases; the resolved sparse
query never contained the legacy history `OR` expression.

## Temporal and value evidence

Requested-year and multi-period coverage were 1.000. Explicit-year selection,
current-version selection and value-bearing recall were 1.000. Unknown periods
were not relabeled as a requested year. Tables received no unconditional boost;
answer content won factual queries while methodology won method queries.

## Duplicate, conflict and citation safety

Duplicate slot waste fell from 0.750 to 0.000 per controlled query, with
provenance retention 1.000 and no false independent corroboration observed.
Conflict preservation and both-side context/citation checks were 1.000.
Permission leakage, unauthorized citations, fabricated IDs and provenance loss
were all 0.

## Generation metrics

The deterministic closed-book generator/citation contract achieved citation
support accuracy 1.000. This fixture validates evidence serialization and
fail-closed citation mapping; it is not an external-LLM quality or production
fact-accuracy claim.

## Ablation

- QueryContext fixes follow-up history carryover.
- Canonical temporal filters fix `effective_date`/reference-year mismatch.
- Normalized identity and P4 enrichment eliminate copy-slot dilution.
- Temporal/conflict reservation preserves required scopes and both sides.
- Value utility fixes methodology displacement.
- P5 GenerationContext and validation close the evidence/citation boundary.

## Security, PostgreSQL and regression

ACL-sensitive fixtures yielded zero leaks and relation enrichment accepted only
edges whose two endpoints were already visible. Migration/reset contract tests
passed. Live PostgreSQL `EXPLAIN ANALYZE`, network latency and staging index
plans were not available and remain unresolved. Relevant P1-P5/P6 regression:
309 focused tests passed; the wider unit/contract/integration run passed 923
tests and its three temp-directory setup errors passed separately with a
workspace `--basetemp`.

## Failure taxonomy

No DEV query failed. Runtime attribution distinguishes retrieval failure,
relation-policy failure, controlled temporal/no-evidence abstention, generation
failure and citation-validation failure.
