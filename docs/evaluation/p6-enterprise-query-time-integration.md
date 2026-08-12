# P6 Enterprise query-time integration

## Scope and root causes

The production Enterprise Q&A path previously concatenated recent questions with `OR`,
filtered years through `document_versions.effective_date`, and stopped after sparse/dense
fusion plus generic MMR. It did not consume the P4 relation projection or the P5
`GenerationContext`/citation contract. Duplicate copies could therefore consume slots,
follow-up years could retain stale constraints, and high-scoring methodology text could
displace the actual value row.

P6 keeps the ACL-gated PostgreSQL retrieval boundary, but makes query resolution and
evidence policy shared and deterministic:

1. bounded user-history resolution produces one typed `QueryContext`;
2. sparse and dense RPCs receive the same canonical temporal filters;
3. one batched, RLS-protected relation lookup enriches only already-visible candidates;
4. exact/near duplicates collapse while retaining authorized provenance;
5. conflict counterparts and temporal scopes are mandatory selection units;
6. value-bearing utility is applied before MMR and the context budget;
7. the frozen P5 context and fail-closed citation validator gate generation and persistence.

## Query and temporal policy

An explicit entity, predicate, qualifier, year, or current marker overrides inherited
history. A short compatible follow-up may inherit only missing dimensions. Raw history is
never emitted as an `OR` query. Explicit historical queries accept only matching canonical
reference years; unknown time is not guessed. Current queries keep only an explicitly
current member when a version family exists.

Migration 37 adds `enterprise_chunk_reference_year(metadata)` and the indexed generated
column `knowledge_chunks.canonical_reference_year`. The year priority is retrieval
metadata, claim scope, structured temporal metadata, then the top-level canonical value.
`effective_date` is deliberately not treated as a universal reference year. Both sparse
and dense RPCs retain their signatures and ACL/lifecycle gates and return canonical
identity plus temporal metadata.

## Duplicate, relation, conflict and evidence policy

Normalized content hash plus normalization version supplies exact identity when no
persisted group is present. A representative keeps the visible occurrence list. Relation
enrichment is one batched request; rows whose two endpoints are not in the visible
candidate set are discarded again in application code. Confirmed conflict pairs cannot
be erased by a bad duplicate annotation. Temporal comparisons reserve one value-bearing
candidate per required year, and conflicts reserve one candidate per visible side before
ordinary Top-K/MMR filling.

Tables receive no unconditional preference. Numeric/structured answer content,
predicate alignment, requested-period match, and query lexical overlap raise utility.
Methodology and boilerplate are penalized for factual questions, but promoted when the
method itself is requested. Mandatory temporal/conflict evidence may exceed the ordinary
Top-K; optional material remains bounded per document and by P5 character/item budgets.

## Controlled evaluation

The P6 DEV dataset contains 160 queries across 16 categories and 10 subjects. The frozen
TEST contains 64 held-out queries across the same categories and four held-out subjects.
These are deterministic engineering fixtures, not a claim about natural production
traffic or LLM quality.

| Metric | Baseline | DEV | Frozen TEST |
|---|---:|---:|---:|
| Evidence Recall@10 | not comparable in old raw pipeline | 1.000 | 1.000 |
| Temporal Coverage Recall | incomplete by design | 1.000 | 1.000 |
| Requested-Year Coverage | stale-history/effective-date risk | 1.000 | 1.000 |
| Follow-up Resolution Accuracy | unsafe OR concatenation | 1.000 | 1.000 |
| Value-Bearing Evidence Recall | methodology displacement reproduced | 1.000 | 1.000 |
| Current/Historical/Conditional Accuracy | no unified policy | 1.000 | 1.000 |
| Conflict Preservation Recall | not wired | 1.000 | 1.000 |
| Citation Support Accuracy | legacy marker validation only | 1.000 | 1.000 |
| Permission Leakage | 0 required | 0 | 0 |
| Provenance Retention | not guaranteed | 1.000 | 1.000 |
| Duplicate Slot Waste per query | 0.750 | 0.000 | 0.000 |

Controlled evidence precision is 0.698 because supporting evidence is intentionally
retained within Top-K; safety and required-evidence recall take priority. The in-process
benchmark records mean/p50/p95 pre-LLM policy latency in the JSON reports. It does not
measure networked sparse search, vector search, model latency, or a production SLA.

## Ablation and failure attribution

| Stage | Failure addressed |
|---|---|
| A — legacy Enterprise | baseline OR history, raw evidence, duplicate slot waste |
| B — QueryContext | wrong-history carryover and follow-up ambiguity |
| C — canonical temporal filter | effective-date/reference-year mismatch |
| D — duplicate identity | copy-document slot dilution |
| E — P4 enrichment | missing version/conflict/conditional semantics |
| F — reservation | missing years and suppressed conflict side |
| G — utility | methodology/table-title displacement of answer values |
| H — P5 context/citations | uncontrolled evidence serialization and weak citation checks |

Failure categories emitted by the service distinguish retrieval failure,
`RELATION_POLICY_ERROR`, controlled no-evidence/temporal abstention, generation failure,
and citation validation failure. Shadow mode logs proposed P6 evidence without changing
the answer path.

## Security and database validation

SQL RPCs still require authentication, functional `ASK_KNOWLEDGE`, published documents,
active versions, non-null embeddings, and per-document READ permission. Relation RLS
requires both endpoints to be readable. Generation receives only selected authorized
documents, and citation persistence maps aliases back to the turn-local candidate set.

Migration/reset contract tests and application ACL fixtures passed, including hidden
duplicate/conflict/temporal candidates. No live PostgreSQL/Supabase connection was used
for `EXPLAIN ANALYZE`; index effectiveness, network latency, and production query plans
remain unresolved and must be validated in staging.

## Rollout

Keep `RAG_P5_MODE=shadow` initially. Apply migration 37 after migrations 35 and 36, then
reprocess representative documents so canonical temporal and identity metadata exist.
Compare shadow diagnostics for requested-year coverage, duplicate suppression, conflict
completeness, no-answer rate, and p95 pre-LLM latency. Promote a tenant cohort to `on`,
retain `off` as rollback, and stop rollout on any permission leak, conflict suppression,
false duplicate collapse, provenance loss, unknown-year fabrication, or unauthorized
citation.

The legacy Enterprise MMR path remains only for `off`/baseline compatibility. After a
stable rollout it can be removed together with raw OR contextualization; P4/P5 modules
remain the shared source of truth.
