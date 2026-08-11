# Knowledge-quality operations runbook

## Scope

This runbook covers rollout, monitoring, review operations, reconciliation, and
incident response for duplicate/version/conflict handling. Database installation
is in `docs/migrations/08-09-knowledge-quality.md`; reversal and rollback are in
`docs/operations/knowledge-quality-rollback.md`.

## Pre-deployment checks

1. Back up the target database and record the deployed application revision.
2. Apply migrations 08 and 09 to a clone or local Supabase instance first.
3. Run backend tests and the deterministic benchmark:

   ```powershell
   uv run pytest
   uv run python -m tests.evaluation.knowledge_quality_benchmark
   ```

4. Require every benchmark gate to pass. In particular:

   - exact auto-reuse false-positive rate is `0`;
   - conflict recall is `1.0` on the mandatory unit/date/negation/policy cases;
   - cross-scope suppression is `1.0`;
   - `shadow` retrieval behavior equals `off`;
   - `on` preserves both sides of conflicts and distinct documents.

5. Run live two-user RLS tests and concurrent upload/resolution tests against the
   same PostgreSQL/Supabase version used in production.
6. Build the frontend from the exact source revision to be deployed.

## Rollout

The upload path records `KNOWLEDGE_QUALITY_MODE` in each durable ingestion job.
The worker uses the safer minimum of that enqueue-time value and its current
runtime value (`off < shadow < on`), and the database rejects an upgrade at
completion. Lowering the runtime mode therefore downgrades queued work; raising
it never upgrades jobs that were enqueued under `off` or `shadow`.

### Stage 1: off

Deploy schema-compatible application code with:

```dotenv
KNOWLEDGE_QUALITY_MODE=off
KNOWLEDGE_QUALITY_CONFLICT_PROMPT_ENABLED=false
```

Confirm normal upload, ingestion, retrieval, and chat behavior. `off` is a
behavior switch, not a database downgrade.

### Stage 2: shadow

Set:

```dotenv
KNOWLEDGE_QUALITY_MODE=shadow
KNOWLEDGE_QUALITY_CONFLICT_PROMPT_ENABLED=false
```

Run long enough to cover representative document families. Shadow may persist
candidates and telemetry, but must not reuse or suppress documents. Compare
retrieval result IDs and citations against `off`.

Sample daily checks:

- candidates created by relation type and detector version;
- confidence distribution;
- percent of candidates with structured evidence;
- reviewer agreement and dismissal rates;
- exact-content candidates that failed minimum content-length rules;
- cross-scope candidate rejection count;
- ingestion latency and failure rate relative to the pre-rollout baseline.

### Stage 3: on

Enable `on` only after shadow and security gates pass:

```dotenv
KNOWLEDGE_QUALITY_MODE=on
KNOWLEDGE_QUALITY_CONFLICT_PROMPT_ENABLED=true
```

Start with a small tenant cohort when the deployment platform supports scoped
configuration. Do not promote fuzzy candidates automatically. Monitor retrieval
suppression, stale version exposure, conflict citations, resolution latency, and
reversal count. Also verify every succeeded ingestion job has
`completion_disposition` set to `completed` or `duplicate_suppressed`. For
Qdrant, compare those outcomes with finalized/deleted claim-token generations
and use reconciliation for any residual external state.

## Review queue procedure

For every pending relation, the reviewer should inspect:

- both document names and permission scope;
- confidence and detector version;
- lexical/semantic/containment signals;
- source and target excerpts with page/section;
- normalized quantity, unit, date, negation, or modality differences;
- effective dates and source authority;
- prior decisions in the audit history.

For `temporal_series`, verify that entity/project identity matches and that both
period anchors are source-explicit. Prefer `mark_version` when the newer period
supersedes the older document; otherwise use `keep_separate`. Do not confirm a
conflict solely because values differ across years, quarters, or months.

Decision policy:

- **Duplicate:** only when the meaning and critical claims match. Keep the
  canonical document; never hard-delete the alias.
- **Version:** identify the newer document, effective time, and version family.
  Preserve the superseded row.
- **Conflict:** keep both sources and record authority/effective-time context.
  A preference must be explicit and audited.
- **Separate:** use when similarity is topical but the claims/documents are
  independently useful.
- **Dismiss:** use for a bad candidate without changing document lineage.

Enter a reason for version, conflict preference, and reversals. Refresh and
re-evaluate when the API returns `409`; never retry a stale decision blindly.

## Reconciliation

Run reconciliation after detector upgrades, migration, recovery from a worker
incident, or a material change in permission policy.

All mutating commands require the service-role key, a non-blank `--reason`, and
a new `--output` path for an atomic JSON audit artifact. The script refuses to
overwrite an artifact unless `--overwrite-output` is explicit. Never combine
`--delete-orphans` and `--requeue-repairs`; scan, cleanup, and repair should
remain independently reviewable operations.

1. Record the detector version, effective runtime mode, application revision,
   vector backend, and operator.
2. Run the inventory command in dry-run mode:

   ```powershell
   python -m scripts.reconcile_knowledge_quality
   ```

   It compares canonical chunk IDs, scope, checksum, strict identity group and
   ingestion generation. Exit code `0` means no drift; exit code `1` means the
   JSON report contains missing, orphan, unembedded or mismatched records.
3. Review the complete report. For Qdrant only, remove explicitly reported
   orphan point IDs when Postgres is known to be authoritative:

   ```powershell
   python -m scripts.reconcile_knowledge_quality --delete-orphans `
     --reason "Verified Postgres-authoritative orphan cleanup" `
     --output artifacts\knowledge-quality-orphan-cleanup.json
   ```

   The command first acquires a tokenized database maintenance lease. The lease
   refuses to start while an ingestion job is running, blocks new claims, and
   is renewed by an independent heartbeat. The script rescans under the lease,
   writes its planned artifact, and then rechecks Postgres before every batch.
   Qdrant deletion uses compare-and-set evidence over point ID, document,
   owner, notebook tenant, checksum, and ingestion generation, followed by a
   read-back verification and final inventory scan. Changed points and legacy
   points without sufficient identity/generation evidence are reported for
   manual review. No document, chunk row, or Storage object is deleted.
4. Requeue missing, unembedded, or mismatched derived vectors through the
   fenced repair path:

   ```powershell
   python -m scripts.reconcile_knowledge_quality --requeue-repairs `
     --reason "Restore derived vectors from verified source objects" `
     --output artifacts\knowledge-quality-repairs.json
   ```

   The service-role RPC is idempotent for response-loss retries within an
   operator run. It checks owner/notebook scope, document `updated_at`, active
   attempt state, the last successful ingestion profile, and expected
   content/fingerprint/lineage before creating one pending repair job and audit
   event. Repair workers run decision logic as `off`, skip duplicate/relation
   detection and suppression, and preserve quality and lineage fields.
   Completion revalidates the saved expectations before replacing derived
   artifacts. Do not write chunks, vectors, fingerprints, or lineage by hand.
5. Wait for queued repairs to reach a terminal state, then rerun dry-run
   reconciliation. For `--requeue-repairs`, exit code `0` means all requested
   jobs were accepted; it does not mean those asynchronous jobs have completed.
6. Find ready/current documents without a normalization version or fingerprint.
7. Find pending relations whose detector version is obsolete.
   Detector upgrades are intentionally non-retroactive: migration 26 does not
   rewrite existing reviewed or pending relations. The reconciliation repair
   path also skips relation detection, so do not use `--requeue-repairs` as a
   re-detection mechanism. Re-submit selected documents through normal ingestion
   only after inventorying obsolete `conflict_candidate` rows and preserving the
   existing audit history.
8. Verify every canonical target and supersedes target belongs to the same
   owner/notebook.
9. Verify each version family has at most one current canonical document.
10. Verify every confirmed/dismissed relation and every repair requeue has a
    matching audit event.
11. Run the benchmark and a representative retrieval comparison again.

## Alert and incident thresholds

Immediately switch to `shadow` or `off` when any of these occur:

- any confirmed cross-scope relation or cross-scope retrieval result;
- any exact auto-reuse false positive;
- multiple current documents in a version family after resolution;
- audit rows missing for a state-changing decision;
- conflict sources disappearing without an explicit preference;
- sustained ingestion failure or latency regression attributable to detection.

Use `off` for retrieval-impacting incidents and `shadow` when detection evidence
is still useful and safe. Follow the rollback runbook for individual decisions
or deployment rollback.

## Post-deployment evidence

Keep the following with the release record:

- migration output and schema version;
- backend/frontend test results;
- JSON and Markdown benchmark reports;
- live RLS/concurrency test result;
- rollout mode changes and timestamps;
- threshold/configuration values;
- sampled review decisions and any reversals.
