# Structured-fact duplicate and conflict architecture

## Purpose

The structured-fact subsystem complements the existing document/chunk quality
pipeline. It is the authoritative path for comparing large business tables,
temporal price lists, and other row-oriented facts. It does not replace strict
document identity, SimHash/ANN candidate generation, or the human document
review queue.

## Safety invariants

- Exact byte/document/chunk identity remains owned by the existing knowledge-
  quality pipeline.
- A table template signature is routing evidence only; it never suppresses a
  document or reuses an embedding.
- Business scope is a set of location, product, and commercial facets. A
  document type is not business-scope identity.
- Scope relations are directional: same, left-contains-right,
  right-contains-left, overlaps, disjoint, or unknown.
- Missing scope or qualifier evidence cannot produce an automatic conflict.
- Low-confidence/OCR-derived rows are persisted as uncertain evidence.
- Source authority is applied only after subject, predicate, qualifiers, and
  effective time have been shown to be comparable.
- Publication time is not effective time. A later publication does not
  automatically supersede an earlier source.
- Every structured claim retains document/table/row/cell provenance and an
  extractor version.
- Claim/row relations are the source of truth. A document relation is only an
  aggregate summary for review and retrieval policy.
- All storage, comparison, review, and retrieval operations remain scoped by
  owner and notebook.

## Flow

```text
canonical extraction
  -> physical table rows/header/cells
  -> semantic header normalization
  -> business scope and row identity
  -> structured claims with qualifiers, time, authority, and provenance
  -> indexed row-key lookup
  -> qualifier compatibility
  -> temporal compatibility
  -> normalized/derived value comparison with tolerance
  -> claim relations: unchanged | updated | added | removed |
                      conditional_variant | conflict_candidate | uncertain
  -> document relation summary
  -> structured retrieval before vector retrieval for exact fact questions
  -> cited generation using the original row/cell evidence
```

Row-key comparison is `O(n + m)` for two tables. SimHash and ANN are fallbacks
when a deterministic key cannot be extracted; increasing fuzzy probe counts is
not the primary table-comparison strategy.

## Ingestion and comparison lifecycle

1. Canonical extraction keeps the physical table, source page, row, and cell
   coordinates. The analyzer normalizes headers, business scope, row identity,
   values, units, qualifiers, authority, and effective time without storing a
   second raw-table dump.
2. The worker builds `table_snapshots` and `structured_claims`. A claim receives
   a chunk citation only when that chunk demonstrably covers the source row;
   uncitable claims remain stored but cannot enter structured retrieval.
3. Before replacing one document's extractor output, the worker loads prior
   candidates by indexed candidate-identity and schema fingerprints. A current
   table is compared only with a unique compatible prior table; an ambiguous
   best match is skipped.
4. Deterministic row-key diff classifies comparable claims. Persistence maps
   current-only and prior-only rows to directional `source_only` and
   `target_only` relations. `conflict_candidate` and `uncertain` enter
   `pending`; deterministic `unchanged`, `updated`, `conditional_variant`, and
   one-sided relations enter `auto_confirmed`.
5. `replace_structured_facts_for_document` atomically replaces the selected
   document/extractor output and records an audit event. It never suppresses
   the source document or changes embedding reuse.
6. After a successful replace, the worker reloads candidates once. If another
   document committed concurrently, it performs one bounded reconciliation
   replace so the later observable database state still contains the
   cross-document relations; retries never reuse a stale candidate set.

## Review lifecycle

Pending relations retain both claims and their evidence. An authenticated
owner resolves a relation through `resolve_structured_claim_relation`, supplies
a reason, and includes the expected `updated_at` value. The optimistic
concurrency check rejects stale review writes. Actions can confirm equivalence,
an update, a conflict, or a conditional variant, or dismiss the candidate. Each
transition stores before/after state in append-only `structured_claim_audit`;
direct authenticated table updates are not exposed.

Structured retrieval returns non-dismissed conflict/uncertainty warnings beside
the claim as structured relation metadata. Generation pairs claims by relation
ID and requires citations to both sides instead of silently choosing one.
Source authority (publisher, type, approval, officiality, and configured level)
is exposed only after scope, predicate, qualifiers, and effective time have
passed the exact lookup gates. A preference or review decision annotates
evidence; it does not delete the competing source.

The owner-scoped review API lists pending relations, returns both claim/snapshot
evidence sides, and resolves a relation with an expected `updated_at` value:

- `GET /notebooks/{notebook_id}/structured-facts/relations`
- `GET /notebooks/{notebook_id}/structured-facts/relations/{relation_id}/evidence`
- `POST /notebooks/{notebook_id}/structured-facts/relations/{relation_id}/resolve`

## Rollout

`STRUCTURED_FACT_MODE` is independent from `KNOWLEDGE_QUALITY_MODE`:

| Mode | Extraction/persistence | Retrieval/generation effect |
|---|---|---|
| `off` | disabled | none |
| `shadow` | enabled with metrics | none |
| `on` | enabled | temporal/structured policy enabled |

Jobs persist the enqueue-time mode. Workers use the safer minimum of the
durable and runtime values so raising the runtime flag cannot upgrade an older
job silently.

In `shadow`, ingestion, persistence, candidate comparison, lookup, and metrics
run, but structured evidence is not merged into the answer. This makes output
drift measurable before promotion to `on`.

## Failure isolation and fallback

The structured-fact path is additive and fail-open relative to the established
RAG path:

- a per-table analysis failure skips that table and preserves normal chunking,
  embedding, and document completion;
- candidate-loading failure still permits replacement of the current facts
  without cross-document relations;
- persistence failure is logged after a bounded retry and does not convert an
  otherwise completed ingestion job to failed;
- structured lookup failure, an unsupported/broad question, missing subject or
  predicate, or no citable structured evidence falls back to the existing
  hybrid/vector retrieval path;
- time-qualified structured lookup is fail-closed: claims without a compatible
  effective interval are not returned.

`STRUCTURED_FACT_MODE=off` is the immediate independent kill switch. It disables
structured extraction and reads while leaving `KNOWLEDGE_QUALITY_MODE` and the
document/chunk duplicate pipeline unchanged.

## Database installation and permissions

Run `supabase/migrations/16_structured_fact_layer.sql` after migration 15. It
adds `table_snapshots`, `structured_claims`, directional `claim_relations`, and
append-only `structured_claim_audit`, plus replacement, review, search, and
candidate-loading RPCs. The reset script contains the same layer.

All tables have owner/notebook RLS. Atomic replacement and candidate loading
require `service_role`; search is owner-scoped; review is authenticated,
owner-scoped, and concurrency-guarded. The service-role key remains backend
only.

## Promotion gates

- different-building/same-unit false-conflict rate is zero;
- qualifier-unknown cases never become automatic conflicts;
- full-row candidate recall meets the project target on large tables;
- conflict and uncertain temporal cases are human-adjudicated;
- row/cell citations resolve to the source artifact;
- tenant/RLS and concurrent replacement tests pass;
- shadow mode has zero retrieval and generation drift;
- reconciliation can detect missing, stale, or duplicate extractor outputs.
