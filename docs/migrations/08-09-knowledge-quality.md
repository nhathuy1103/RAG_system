# Migrations 08 and 09: knowledge quality

## Order

For a new database, apply migrations in numeric order. The knowledge-quality
migrations are:

1. `08_knowledge_quality.sql`
2. `09_knowledge_quality_hardening.sql`

Migration 09 depends on every earlier schema and must not be run by itself on a
pre-08 database.

## Migration 08

Migration 08 introduces:

- strict/loose document fingerprints and quality metadata;
- canonical aliases, version families, effective-time fields, and current flags;
- `document_relations` and append-only `knowledge_quality_audit`;
- owner/notebook composite constraints and RLS;
- atomic exact-upload/content identity protections;
- claim-generation fencing for ingestion completion/failure;
- relation candidate persistence;
- guarded `resolve_document_relation`.

It also backfills existing byte-identical active documents into canonical/alias
relationships before creating the partial unique byte-hash index. Review this
backfill on a production clone before applying it to the primary database.

## Migration 09

Migration 09 hardens concurrency, retrieval scope, and reversibility:

- replaces the dense-search RPC with the five-argument, owner/notebook-scoped
  `match_document_chunks`;
- makes ingestion enqueue idempotent;
- persists the terminal ingestion `completion_disposition` (`completed` or
  `duplicate_suppressed`) so an ambiguous RPC response can be reconciled;
- serializes normalized canonical identity races;
- enforces one version number per canonical family and at most one current
  canonical document;
- adds a database-backed ingestion-maintenance lease that blocks new claims
  during guarded Qdrant orphan cleanup;
- adds an idempotent, service-role-only reconciliation repair RPC with expected
  document identity, lineage, and timestamp fencing;
- expands resolution snapshots to every affected document and locks the family;
- adds guarded `revert_document_relation_resolution`.

The reversal RPC takes a relation ID, notebook ID, current expected relation
`updated_at`, and reason. It finds and validates the latest still-effective
reversible audit event internally. It rejects cross-owner, stale, non-latest,
or unsafe reversals and appends a new audit event instead of changing existing
audit history. An audit ID is not an RPC or API input.

## Preflight

Before applying either migration:

1. Stop or drain ingestion workers.
2. Put application traffic in maintenance mode or prevent relation decisions.
3. Create and verify a database backup.
4. Apply the migrations to a production-like clone.
5. Inspect duplicate byte hashes, normalized hashes, canonical chains, and
   version families for data that would violate the new unique indexes.
6. Run the SQL behavioral fixture and two-user RLS tests.
7. Record the existing overloads of `match_document_chunks` and relation RPCs.

Do not use `RESET_AND_REBUILD.sql` on a database whose application data must be
preserved.

## Apply

For Supabase SQL Editor, run the numbered files one at a time and stop on the
first error. For a local disposable Supabase database, a full reset may be used
to validate the consolidated rebuild script.

After migration, restart the application in `KNOWLEDGE_QUALITY_MODE=off`, verify
normal traffic, and then follow the staged rollout in the operations runbook.

## Verification

Verify at minimum:

- the new document columns and both relation/audit tables exist;
- authenticated users can select only their own relation/audit rows;
- authenticated users cannot directly update either table;
- cross-owner and cross-notebook resolve/revert calls fail;
- a stale `expected_updated_at` fails without partial document changes;
- audit update/delete is rejected;
- exact uploads converge on one canonical row under concurrent sessions;
- normalized exact ingestion converges under concurrent workers;
- a successful ingestion persists exactly one valid completion disposition,
  including `duplicate_suppressed` when an exact-identity race is resolved
  inside the completion transaction;
- the maintenance lease refuses to start while a job is running and prevents
  new job claims while held;
- reconciliation repair is request-key idempotent, permits only one active
  attempt per document, rejects stale identity/lineage, and appends an audit
  event;
- a version family cannot have duplicate version numbers or multiple current
  canonical rows;
- resolution and reversal restore the complete affected family state;
- dense search cannot return a chunk outside the requested owner/notebook.

Run:

```powershell
uv run pytest
uv run python -m tests.evaluation.knowledge_quality_benchmark
```

Keep the generated reports under `tests/evaluation/reports/` with the release.

## Compatibility

Application code that calls the four-argument dense-search RPC is incompatible
with migration 09. Deploy code using the five-argument owner/notebook-scoped
signature with the migration.

Ingestion adapters deployed with migration 09 must accept the text result from
`complete_ingestion_job` and recover lost responses from
`ingestion_jobs.completion_disposition`. Reconciliation operators must use the
service-role CLI path described in the runbook rather than writing chunks,
vectors, or lineage fields directly.

Migration 09 is forward-only. Operational rollback uses feature flags and the
audited reversal RPC; schema objects are not dropped during an incident.
