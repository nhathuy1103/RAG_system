# Knowledge-quality architecture

## Purpose and invariants

The knowledge-quality subsystem detects and manages exact duplicates,
near-duplicates, document versions, and conflicting claims without destroying
source history.

The non-negotiable invariants are:

- only byte-identical or strictly normalized, sufficiently long content may be
  reused automatically;
- fuzzy similarity creates a review candidate, never an automatic delete;
- a new version preserves the prior document and effective-time history;
- an unresolved conflict keeps both sides available to retrieval and generation;
- every fuzzy decision stores a confidence score, evidence signals, and detector
  version;
- every human or automatic state change is append-only audited and reversible;
- candidate generation, retrieval suppression, and resolution never cross an
  owner/notebook permission scope.

## End-to-end flow

```text
upload
  -> atomic byte-hash check within owner + notebook
  -> durable-mode, generation-fenced ingestion job
  -> extraction and format-neutral identity projection
  -> strict/loose fingerprints
  -> exact-content identity check
  -> chunk embedding
  -> same-scope ANN candidate generation
  -> lexical + semantic + claim-level scoring
  -> relation queue with detector version and evidence
  -> fenced database completion with persisted completion disposition
  -> finalize the external vector generation, or delete it when suppressed
  -> human resolution for fuzzy relations
  -> version/canonical-aware retrieval
  -> conflict-aware generation with citations to both sides
```

The byte hash protects the upload boundary. The normalized hash is a second,
content-level identity after extraction. Document identity v2 projects adjacent
text blocks and structured table cells into canonical JSON while excluding
parser, filename, MIME, page, geometry, and storage metadata. This lets equivalent
TXT, DOCX, Markdown, HTML, CSV, XLSX, PPTX, and other structured parser outputs
share an identity without treating their container bytes as equal. The loose
signature and vector search are candidate generators only.

The authoritative projection uses NFC and preserves case, punctuation, token
order, ZWJ/ZWNJ, table row order, and table cell boundaries. A structured table
is not automatically equated with flat PDF text whose cell boundaries could not
be proven. OCR, replacement characters, low-confidence extraction, or
unrepresented visual content also disable automatic aliasing and remain
reviewable candidates.

For Qdrant, vectors are staged under the ingestion claim-token generation before
the authoritative database completion. A concurrent exact-identity winner may
cause `complete_ingestion_job` to return `duplicate_suppressed`; the worker then
deletes only its staged generation instead of publishing it. Otherwise it
finalizes that generation. The job stores the same disposition, so a lost or
ambiguous completion response is resolved by reading
`ingestion_jobs.completion_disposition`, not by replaying side effects.

## Data model

`documents` stores operational identity and lineage:

- `normalized_content_hash` and `normalization_version`;
- `loose_content_signature`;
- `canonical_document_id` for an exact-content alias;
- `version_group_id`, `version_number`, and `supersedes_document_id`;
- `effective_from`, `effective_to`, and `is_current`;
- `quality_status` as an operational summary.

`document_relations` is the review source of truth. A relation contains the two
document IDs, relation type, status, confidence, JSON evidence signals,
detector version, optional preferred document, reviewer, and timestamps.

`knowledge_quality_audit` is append-only. Each decision records the actor,
reason, and complete before/after snapshots needed for a guarded reversal.

`document_chunks` carries the owner/notebook-scoped normalized hash,
normalization version, loose signature, and deterministic exact-duplicate group
used by retrieval and reconciliation. The group identity cannot cross a
permission scope.

`ingestion_jobs` stores the enqueue-time knowledge-quality mode, claim token,
terminal `completion_disposition`, and an optional unique
`repair_request_key`. The singleton `ingestion_control` row carries the
tokenized maintenance lease used to pause new claims during external-vector
cleanup.

The composite foreign keys `(document_id, notebook_id, owner_id)` prevent a
relation from linking documents across a permission boundary even when a
service-role worker writes the row.

## Relation lifecycle

```text
detected
  -> pending
      -> confirmed exact duplicate
      -> confirmed version
      -> confirmed conflict
      -> confirmed distinct
      -> dismissed
```

Exact byte/content identity may enter `auto_confirmed`. Near-duplicate,
version, and conflict candidates remain `pending` until a reviewer decides.
Resolution uses an expected `updated_at` value, row locks, and family advisory
locks to reject stale or concurrent decisions.

A reversal does not mutate or delete an audit row. Migration 09 adds
`revert_document_relation_resolution`, which restores a valid latest snapshot
and appends a new `revert` audit event. The authenticated API and RPC are keyed
by the relation ID, notebook ID, current expected relation `updated_at`, and a
non-blank reason. The RPC selects and validates the latest still-effective
reversible audit event internally; callers do not submit an audit ID.

## Explainable conflict detection

The detector combines:

- lexical overlap and containment;
- semantic similarity;
- normalized quantities and magnitudes, including Vietnamese `triệu`/`tỷ`;
- units and percentages;
- date spans;
- scoped negation;
- policy modality such as permission, obligation, and prohibition.

Detector v4 also extracts explicit reference year, quarter, month/range labels,
and persisted effective dates into `ClaimScope`. A matching entity with
non-overlapping reference periods is `temporal_divergence`, not `same_scope`.
Per-claim temporal qualifiers prevent values from different periods from being
aligned as one claim. The analysis layer emits `temporal_series` for explicit
historical periods, or `version_candidate` for effective dates at least one
calendar year apart. Both pre-embedding and ANN aggregation apply a temporal
majority guard before promoting any document pair to `conflict_candidate`.

Structured claim conflicts belong in `signals.claim_conflicts`. A review client
should show both claims, normalized values/units, source chunk/page, reason
codes, confidence, and detector version. A score alone is not sufficient
evidence for a destructive action.

## Runtime modes

`KNOWLEDGE_QUALITY_MODE` controls rollout:

| Mode | Detection | Persistence | Automatic exact reuse | Retrieval behavior |
|---|---|---|---|---|
| `off` | disabled | no new candidates | disabled | legacy behavior |
| `shadow` | enabled | candidates and telemetry | disabled | same as `off` |
| `on` | enabled | enabled | enabled for safe exact identity | canonical/current and reviewed relation policy |

`shadow` must have zero retrieval behavior drift from `off`. Promotion to `on`
requires the benchmark gates, migration checks, and permission tests described
in the runbook.

New installations default to `on` for conservative exact identity. Operators
can still start or roll back in `shadow`/`off`. Changing the runtime flag does
not upgrade jobs already enqueued under a safer mode.

The mode captured in the ingestion job is durable. At claim time, the worker
uses the safer minimum of that enqueue-time mode and its current runtime mode:
`off < shadow < on`. A missing or invalid durable mode fails closed to `off`.
This lets an operational rollback downgrade already queued work but never
upgrades a job that was enqueued under a safer mode. The database repeats the
no-upgrade check; automatic exact reuse is possible only when both the durable
and effective completion modes are `on`.

Reconciliation repair attempts deliberately execute knowledge-quality decision
logic as `off`: they do not look up duplicates, create relation candidates, or
suppress documents. If the document already has a normalized fingerprint, the
worker recomputes and submits it only as compare-and-set evidence for repair
completion.

`KNOWLEDGE_QUALITY_CONFLICT_PROMPT_ENABLED` controls deterministic conflict
annotations sent to generation. Disabling it is an independent response option;
it does not delete conflict relations.

## Retrieval and generation policy

Default notebook retrieval:

- resolves exact aliases to their canonical document;
- selects the current document in a confirmed version family;
- keeps both sides of conflicts even when one source is preferred; preference
  changes authority/ranking annotations, not evidence availability;
- preserves explicitly requested historical versions for comparison;
- collapses duplicate chunk evidence before final reranking.

Generation receives stable source aliases and structured conflict notices. It
must describe material disagreement, avoid silently reconciling the values, and
cite each side separately.

## Reconciliation and repair

Reconciliation treats Postgres chunk rows as authoritative and scans the
configured vector backend. Dry-run is the default.

Rows fingerprinted with legacy `knowledge-identity-v1` remain valid and repair
jobs verify them with the legacy algorithm. They are not compared directly with
`knowledge-document-identity-v2`; an operator must re-download and re-ingest
legacy source objects to migrate their document identity safely.

Qdrant orphan deletion is an explicitly audited operator action. It acquires a
database maintenance lease that refuses active running jobs and prevents new
claims, renews that lease on an independent heartbeat, and builds a fresh
manifest while the gate is held. Before each delete it rechecks Postgres and
compares the current Qdrant point with the manifest. The delete filter binds the
point ID, document, owner, notebook tenant, checksum, and ingestion generation,
and the result is verified afterward. A point missing this identity evidence, or
one that changed after the scan, is reported rather than automatically deleted.

Missing or mismatched derived vectors use the service-role-only,
`requeue_document_ingestion_repair` RPC. Each operator run writes a planned
audit artifact before RPC calls and uses a request key that is stable for
response-loss retries within that run. The database locks the scoped document,
rejects a competing active attempt, verifies the expected timestamp and saved
ingestion profile, records expected content/fingerprint/lineage state, creates
one pending repair attempt, and appends a `repair_requeue` audit event. Worker
completion revalidates those expectations before replacing derived chunks or
vectors and preserves existing lineage and quality decisions.

## Safety and observability

All user-facing repository calls use the user's JWT and Supabase RLS. The
service-role key is limited to trusted worker transitions and operator
reconciliation processes. Direct authenticated writes to derived chunk fields,
relation tables, and audit tables are denied; resolution and reversal use
guarded authenticated RPCs.

Telemetry should include mode, detector version, candidate counts by class,
confidence distribution, review outcomes, stale-write conflicts, reversals,
cross-scope rejection counts, and retrieval suppression counts. Document text
and claims remain redacted unless content capture has been explicitly approved.

The deterministic Vietnamese regression benchmark is documented in
`tests/evaluation/knowledge_quality_benchmark.py`; it complements rather than
replaces evaluation on project-owned, human-adjudicated documents.
