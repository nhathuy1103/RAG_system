# P5 Relation-Aware RAG and Grounded Generation

## Status

P5 is implemented and evaluated. The production default is `shadow`; `on` is available for
controlled rollout. The frozen controlled DEV and TEST suites both pass every acceptance gate.
The P5 TEST report was generated once after configuration freeze and must be treated as immutable.

## Production flow

```text
authorized notebook documents
  -> query context / intent parsing
  -> sparse + dense retrieval and fusion
  -> coarse exact-quality collapse
  -> MMR reranking
  -> final P4 relation-aware evidence policy
  -> typed P5 evidence context and deterministic budget
  -> closed-book generation prompt
  -> fail-closed citation validation
  -> persistence and SSE response
```

P5 keeps authorization as an absolute filter. Relation metadata is added only when both relation
endpoints are visible. A second context-boundary check removes unauthorized candidates and orphaned
relation/provenance hints before generation.

## Query understanding

`QueryContext` deterministically recognizes default, current, historical, temporal comparison,
version comparison, conflict check, and source comparison intents. It also carries requested years,
quarters, dates, ranges, entity/predicate terms, qualifiers, and output constraints. No LLM is used
for policy-critical intent parsing in the evaluated path.

## Relation-aware evidence policy

- Exact duplicates collapse to a canonical representative while retaining visible occurrence
  provenance.
- Near duplicates are capped without claiming that repeated occurrences are independent sources.
- Current and historical queries select the requested version deterministically.
- A current-value request abstains if every available version is explicitly historical and no
  current version is known.
- Temporal/version comparisons preserve all required endpoints atomically.
- Conditional variants are selected only when their qualifier matches; ambiguous requests preserve
  the variants without misclassifying them as conflicts.
- Confirmed conflict sides are mandatory context units and authority ranking cannot erase a side.
- Uncertain evidence remains traceable but produces controlled uncertainty.

The selected production placement is coarse exact collapse before MMR, followed by the full
relation policy after reranking. This reduces reranker load while preserving final relation rules.

## Evidence and context contracts

Generation receives `GenerationEvidence`, `EvidenceBundle`, and `GenerationContext` rather than raw
chunks alone. These contracts expose claim IDs, normalized value/qualifier/temporal fields,
provenance counts, authority, relation type, version/conflict groups, uncertainty state, and a
turn-local `SRC-n` identifier.

The context builder has fixed item and character budgets. Conflict pairs and requested temporal
comparison endpoints are atomic and may exceed the normal budget; diagnostics record that overrun.
All remaining evidence is ordered deterministically.

## Generation, citation, and no-answer behavior

The centralized prompt treats source text as untrusted data, prohibits outside knowledge, preserves
scope qualifiers, requires both sides of confirmed conflicts, and forbids averaging or selecting an
arbitrary winner. Source text that contains fake citation markers is sanitized before serialization.

In `on` mode token chunks are buffered until the completed answer passes citation validation. The
validator rejects unknown/fabricated IDs, marker/event mismatches, uncited material statements,
unsupported numbers, and incomplete conflict citations. A validation failure returns controlled
uncertainty and persists no citation rather than streaming an invalid partial answer.

No-answer reasons cover missing relevant evidence, permission filtering, missing temporal evidence,
unknown current version, missing qualifier scope, and low-confidence/uncertain evidence.

## Rollout and observability

- `off`: legacy behavior.
- `shadow`: build and log P5 context without changing the answer; this is the default.
- `on`: typed context, P5 prompt, buffered output, and P5 citation contract are enforced.

Telemetry records intent, selected/suppressed/unauthorized evidence IDs, conflict preservation,
context tokens before/after, no-answer reason, citation coverage, numeric support, and conflict
citation completeness.

## Evaluation design

The controlled benchmark contains 240 DEV and 120 frozen TEST queries across eight query types:
default fact, current fact, historical fact, temporal comparison, conflict check, conditional fact,
duplicate-heavy retrieval, and no-answer. TEST SHA-256 is
`7C9CC734621C3818D2C5A2CF6F885F5CE964CE17D5FD0F4994EBFB60549E0230`.

Generation evaluation uses the frozen deterministic evidence-contract generator
`p5-controlled-generator-v1` at temperature `0.0`; it does not call an external provider. This
isolates retrieval, context, answer-contract, and citation-policy correctness. The configured
production adapter is OpenAI Chat Completions with `gpt-4o-mini`, but live-model quality and token
usage were not measured by this benchmark.

An additional 100-case constructed adversarial supplement covers prompt/citation injection, noisy
OCR-like text, mixed table/prose text, and missing-scope uncertainty. It is separate from controlled
TEST and is not presented as production traffic or a real customer-document corpus. It has no gold
fact annotations, so fact precision/recall are explicitly unscored there.

## Results

| Metric | DEV (240) | Frozen TEST (120) |
|---|---:|---:|
| Evidence Recall@10 | 1.0000 | 1.0000 |
| Evidence Precision@10 | 0.9375 | 0.9375 |
| Conflict preservation | 1.0000 | 1.0000 |
| Current version accuracy | 1.0000 | 1.0000 |
| Historical version accuracy | 1.0000 | 1.0000 |
| Conditional match accuracy | 1.0000 | 1.0000 |
| Fact precision / recall / F1 | 1 / 1 / 1 | 1 / 1 / 1 |
| Conflict disclosure | 1.0000 | 1.0000 |
| Temporal accuracy | 1.0000 | 1.0000 |
| No-answer precision / recall | 1 / 1 | 1 / 1 |
| Citation precision / coverage / support | 1 / 1 / 1 | 1 / 1 / 1 |
| Conflict both-sides citation | 1.0000 | 1.0000 |
| Permission / hidden relation / hidden provenance leakage | 0 / 0 / 0 | 0 / 0 / 0 |
| Unauthorized / fabricated citations | 0 / 0 | 0 / 0 |
| Failed queries | 0 | 0 |

Duplicate redundancy fell from `0.229167` to `0.062500`, while independent evidence remained
`2.0 -> 2.0` on duplicate-heavy cases. Controlled context tokens fell by `25.55%`: DEV
`4110 -> 3060`, TEST `2055 -> 1530`.

The deterministic TEST run measured total policy/evaluation latency at p50 `0.2463 ms` and p95
`0.30373 ms`. P5 relation/context/citation bookkeeping contributed p50 `0.1313 ms` and p95
`0.16332 ms`. These are same-process benchmark measurements, not live database or model latency and
are not an SLA.

The adversarial supplement passed all 12 annotated safety/grounding checks: evidence recall,
citation support/coverage, no-answer precision/recall, permission and hidden metadata isolation,
prompt-injection resistance, citation authorization, and scope-fabrication checks.

## Freeze and reproducibility

- Frozen at: `2026-08-12T07:59:11Z`
- Git base: `2d226aa045451109cdd4b89fc21dc7ed2494f5db`
- Canonical evaluation-config SHA-256 stored in DEV/TEST reports:
  `0758D6A9EC3793B911718B0B8DDD3FF897F9F07AB7976791CA706BDC850F9F17`
- Raw config-file SHA-256 at freeze:
  `D200B7783CF60CDB79DA025636AF2BE4B8CA18761785E62874B714F5DF06E526`
- The worktree was dirty from the accumulated P1-P5 implementation, so reproducibility is enforced
  by the 13 per-file SHA-256 values in `configs/evaluation/p5_rag.json`.
- Frozen P5 TEST execution count: exactly one.

P1-P4 historical reports/configurations were not overwritten or rerun. Their safety counters remain
zero and their frozen metrics are copied into P5 only as explicit historical regression references.

## PostgreSQL and staging status

Migration 34 and the P4 relation schema were inspected statically. No local/staging PostgreSQL
connection was available for this work, so migration application, RLS behavior, and
`EXPLAIN ANALYZE` were not live-verified. The reports mark all three as unresolved rather than
claiming production database validation.

## Remaining limitations and recommendation

Controlled results validate deterministic policy behavior, not open-ended LLM answer quality. The
adversarial set is constructed rather than sampled from production. Provider token usage,
first-token latency, sparse/dense/fusion latency, PostgreSQL performance, and live RLS still require
staging measurements.

Keep `RAG_P5_MODE=shadow` as the production default. Move to a small `on` canary only after staging
migration/RLS verification, `EXPLAIN ANALYZE`, live-provider evaluation on permission-cleared
documents, and alerting for abstention, conflict, citation rejection, and latency rates. Do not make
a broad production cutover from the controlled benchmark alone.

## Artifacts

- `configs/evaluation/p5_rag.json`
- `datasets/rag_p5/p5_rag_queries_v1_dev.jsonl`
- `datasets/rag_p5/p5_rag_queries_v1_test.jsonl`
- `datasets/rag_p5/p5_rag_queries_v1_real_world.jsonl`
- `reports/evaluation/rag_p5_dev.json` and `.md`
- `reports/evaluation/rag_p5_test.json` and `.md`
- `reports/evaluation/rag_p5_real_world.json` and `.md`
- `evaluation/rag_p5/evaluate.py`
- `tests/evaluation/test_p5_rag.py`
