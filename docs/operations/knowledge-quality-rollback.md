# Knowledge-quality rollback and reversal

## Choose the smallest safe response

There are three different operations:

1. **Decision reversal:** undo one reviewed duplicate/version/conflict decision.
2. **Behavior rollback:** disable detection or retrieval effects using flags.
3. **Deployment rollback:** restore a prior compatible application revision.

None of these requires deleting documents or audit history. Do not use
`RESET_AND_REBUILD.sql`; it is a destructive local/bootstrap tool, not rollback.

## Reverse one decision

Use the authenticated application endpoint:

```http
POST /notebooks/{notebook_id}/quality/relations/{relation_id}/revert
Content-Type: application/json

{
  "expected_updated_at": "<current relation updated_at>",
  "reason": "<non-blank operator reason>"
}
```

The application calls `revert_document_relation_resolution` from migration 09.
The path key is the relation ID. A UI may begin from an audit-history row, but
it must send that row's `relation_id`; an audit ID is not an API or RPC input.

Preconditions:

- the relation belongs to the authenticated owner and notebook;
- it is the latest reversible event for the relation;
- the caller supplies the current expected relation timestamp;
- no later decision has changed the affected family;
- the reason is recorded.

The RPC locks the relation and affected family, restores whitelisted state from
the audited before-snapshot, and appends a `revert` audit event. It does not
update or delete the original audit row.

After reversal:

1. reload the relation and every document in the family;
2. verify canonical, current, version, effective-time, and quality fields;
3. verify a new audit row exists;
4. repeat the original retrieval query;
5. confirm expected documents and citations are restored.

Never repair lineage with direct table updates. Direct edits bypass concurrency
checks and can leave related documents inconsistent.

## Disable behavior

For a retrieval-impacting incident:

```dotenv
KNOWLEDGE_QUALITY_MODE=off
KNOWLEDGE_QUALITY_CONFLICT_PROMPT_ENABLED=false
```

Restart/redeploy all API and worker processes, then verify the effective
configuration. The worker uses the safer minimum of the durable enqueue-time
mode and its runtime mode, so switching runtime to `off` immediately downgrades
queued `shadow`/`on` jobs and can never upgrade older jobs. `off` stops new
knowledge-quality decisions and retrieval suppression but intentionally leaves
schema, documents, relations, audit history, and already persisted lineage
decisions intact.

Use `shadow` instead when candidate generation remains safe and operators still
need evidence:

```dotenv
KNOWLEDGE_QUALITY_MODE=shadow
KNOWLEDGE_QUALITY_CONFLICT_PROMPT_ENABLED=false
```

Confirm `shadow` returns the same retrieval document IDs as `off`.

## Roll back the application

Only deploy an older revision after confirming it is compatible with migrations
08 and 09. In particular, migration 09 removes the unsafe four-argument dense
search path, so code that still calls that signature must not be redeployed.

If no compatible older revision exists, keep the current schema and run the
current code in `off` mode while preparing a forward fix.

## Repair derived artifacts

Always run a dry reconciliation first:

```powershell
python -m scripts.reconcile_knowledge_quality
```

Use exactly one mutating action per operator run. Both require a non-blank
reason and a new atomic audit-artifact path:

```powershell
python -m scripts.reconcile_knowledge_quality --delete-orphans `
  --reason "Verified Postgres-authoritative orphan cleanup" `
  --output artifacts\knowledge-quality-orphan-cleanup.json
```

`--delete-orphans` is Qdrant-only. It acquires and independently heartbeats the
database ingestion-maintenance lease, rescans after the lease is held, rechecks
Postgres immediately before deletion, and applies a Qdrant payload
compare-and-set over point/document/scope/checksum/generation identity. Missing
identity evidence, a changed point, a lost lease, or a failed post-delete check
stops automatic cleanup safely.

```powershell
python -m scripts.reconcile_knowledge_quality --requeue-repairs `
  --reason "Restore derived vectors from verified source objects" `
  --output artifacts\knowledge-quality-repairs.json
```

`--requeue-repairs` calls an idempotent service-role RPC; it is not a public
user repair API. The RPC fences on scope, request key, expected document
timestamp, content/fingerprint/lineage state, last successful ingestion
profile, and the absence of another active attempt. It appends an audit event
and sends work through the normal lease- and generation-fenced worker.

Repair workers intentionally run quality decisions as `off`: they do not find
duplicates, create relations, or suppress a document. They may recompute an
existing normalized fingerprint only as completion compare-and-set evidence.
Never combine the two mutating flags, and never repair chunks, vectors, or
lineage with direct table writes.

## Database recovery

Do not drop knowledge-quality columns, relation tables, audit tables, indexes, or
RPCs during incident response. PostgreSQL DDL rollback after production writes
can destroy lineage and make old audit snapshots unverifiable.

For a migration failure:

1. keep workers stopped;
2. capture the exact error and current schema;
3. if the transaction rolled back fully, fix and revalidate on a clone;
4. if any out-of-transaction operation completed, restore the verified backup
   to a new project/instance rather than improvising destructive SQL;
5. run schema, RLS, concurrency, and benchmark gates before switching traffic.

## Exit criteria

Rollback is complete only when:

- no cross-scope relation/retrieval is possible;
- exact auto-reuse is disabled or has zero observed false positives;
- retrieval IDs match the chosen `off`/`shadow` policy;
- conflicts retain both sides; an audited preference may annotate/rank but does
  not remove the non-preferred evidence;
- every reversal has a corresponding audit row;
- reconciliation has no unexpected missing, orphan, unembedded, or mismatched
  derived artifact, and every repair requeue has an audit row;
- ingestion and chat health return to baseline;
- the incident timeline, configuration change, and recovery evidence are saved.
