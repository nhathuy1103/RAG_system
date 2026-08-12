# P4 — Relation aggregation, lineage, clustering, and retrieval policy

## Scope and invariants

P4 consumes the persisted P3 claim alignments and produces one conservative,
document-level relation plus orthogonal evidence facets. It does not rerun claim
extraction or alignment. P1 candidate generation, the P2 entity/scope gate, P3
normalization, and all frozen P1–P3 reports remain unchanged.

The implementation is deterministic, tenant scoped, and fail-open at the
retrieval integration boundary. Missing evidence becomes `UNCERTAIN`; it never
becomes an optimistic duplicate, update, or conflict.

## Architecture

The production path is:

1. P3 persists claim relations for a new document and its eligible prior
   snapshots.
2. `aggregate_persisted_claim_relations()` converts those already-produced P3
   payloads into typed alignment evidence without a second alignment pass.
3. `aggregate_claim_evidence()` calculates symmetric claim coverage, facets,
   the final relation, authority preference, review status, and cluster keys.
4. The worker calls the service-role-only `replace_p4_document_relations` RPC.
   Replacement is atomic for pending/auto-confirmed P4 rows and preserves
   confirmed or dismissed human decisions.
5. Retrieval loads relation metadata only for documents already present in the
   permission-filtered candidate set. `off`, `shadow`, and `on` modes support a
   controlled rollout.

The core modules are:

- `relation_models.py`: typed P4 contexts, taxonomy, facets, and summaries.
- `relation_aggregation.py`: precedence, coverage, abstention, review status,
  and production relation mapping.
- `persisted_relation_aggregation.py`: P3 persisted-payload bridge.
- `version_lineage.py`: deterministic direction and acyclic lineage.
- `relation_clusters.py`: separate exact, near, version, and conflict
  components.
- `authority_policy.py`: post-relation preference, never relation creation.
- `relation_policy.py`: retrieval-time suppression and preservation rules.
- `postgrest_relation_metadata.py`: tenant-safe metadata enrichment.

## Final relation taxonomy

| P4 relation | Meaning | Production relation type |
|---|---|---|
| `EXACT_DUPLICATE` | Strict normalized content identity and compatible version metadata | `exact_content` |
| `NEAR_DUPLICATE` | Symmetric, high-coverage unchanged claims | `near_duplicate` |
| `VERSION_UPDATE` | Same family with deterministic continuity and changed coverage | `version` |
| `TEMPORAL_VARIANT` | Comparable claim family for different effective periods | `temporal_series` |
| `CONDITIONAL_VARIANT` | Difference explained by scope or qualifier evidence | `related` |
| `TEMPLATE_VARIANT` | Strong template similarity after the distinctness gate | `template_variant` |
| `CONFLICT` | Comparable claims disagree in overlapping scope/time | `conflict` |
| `DISTINCT` | Sufficient evidence that documents are materially distinct | `distinct` |
| `UNCERTAIN` | Missing, ambiguous, low-confidence, or P2-blocked evidence | `related` |

The production row also retains all applicable facets, so a primary relation
does not erase conflict, temporal, conditional, authority, or version evidence.

## Decision precedence

The frozen precedence is:

1. strict exact identity;
2. tenant and P2 business-identity gate;
3. claim-grounded conflict;
4. temporal variant;
5. conditional variant;
6. version change;
7. uncertainty/abstention;
8. symmetric near duplicate;
9. distinct.

Template similarity is evaluated only after the distinctness gate and cannot
override a grounded conflict or a business-identity mismatch. Exact identity
requires strict content hashes and normalization compatibility; fuzzy scores do
not authorize automatic embedding reuse.

## Coverage and aggregation

Coverage is calculated in both directions:

```text
source coverage = aligned source claims / eligible source claims
target coverage = aligned target claims / eligible target claims
symmetric coverage = min(source coverage, target coverage)
```

The frozen near-duplicate thresholds are `0.8` for both sides. One-sided added
or removed claims become `VERSION_UPDATE` only when independent version-family
continuity exists; otherwise the relation is `UNCERTAIN`. This avoids treating
partial documents or unrelated entities as updates.

Multiple conflict alignments are aggregated without suppressing either side.
P2 remains authoritative: disjoint entity/scope evidence cannot be promoted to
conflict by P4.

## Version direction and lineage

Direction uses explicit version order first, then effective time, then
publication time when the documents share a deterministic family. Ingestion
time is never a semantic version signal. Ambiguous direction remains unknown.

Lineage is maintained independently from duplicate and conflict groups. Cycle
detection prevents invalid supersession graphs. Retrieval preserves every
candidate in a family when the query asks for the latest/current version but
`is_current` is absent or ambiguous; it does not guess.

## Authority and review

Authority is applied after the relation has been decided. Approval status and
source type can select a preferred representative but cannot turn a distinct
pair into a duplicate or make a conflict disappear. The policy contains no
Vinhomes/VinFast-specific source ranking.

Safe deterministic relations may be `auto_confirmed`. Conflicts, uncertain
relations, low-confidence evidence, and ambiguous version direction remain
`pending`. Human `confirmed` and `dismissed` rows are preserved by replacement.

## Provenance and clusters

Exact, near-duplicate, version-family, and conflict clusters have separate IDs.
This prevents transitive collapse across relation semantics. Retrieval attaches
only provenance from already-visible documents and keeps all retrieved chunks
from a selected representative document. P4 document-level exact grouping is
separate from the legacy chunk-level exact key.

## Retrieval policy

Permission filtering always precedes relation enrichment. The PostgREST adapter
queries rows by owner and notebook, ignores dismissed relations, and uses an
edge only if both endpoints already exist in the visible candidate set. Hidden
documents therefore cannot leak through relation IDs, provenance, or clusters.

Policy behavior:

- exact duplicates: select a representative document and keep its retrieved
  chunks plus visible provenance;
- near duplicates: cap representative documents while keeping their chunks;
- current/latest: select an explicitly current version only when unambiguous;
- historical/date query: retain the matching historical version;
- comparison query: retain the relevant version family;
- conflict: preserve evidence from both sides;
- uncertain: preserve candidates rather than suppress them.

`shadow` computes diagnostics on enriched candidates but returns the unchanged
raw candidate list. `on` applies the relation policy. Adapter or policy failure
falls back to raw retrieval.

## Persistence and security

Migration `34_p4_relation_replacement.sql` provides atomic replacement under a
service-role-only RPC. It validates active endpoints, owner/notebook equality,
confidence, relation types, review state, detector version, and preference
payloads. The mutation emits an audit event and preserves human decisions.

The ingestion worker performs P4 materialization after P3 persistence
reconciliation. A P4 failure is isolated: it does not invalidate the successful
P3 or vector-ingestion commit.

## Frozen evaluation protocol

The configuration was frozen at `2026-08-12T06:01:36Z` on Git HEAD
`2d226aa045451109cdd4b89fc21dc7ed2494f5db`. The configuration SHA-256 is
`E61706CD2E6DD60D6B864467430CB9B5D254A2B5D570EBC8E77376D884AAEAFD`.
The evaluator verifies hashes for the gold datasets and decision-bearing code
before allowing TEST. Frozen P4 TEST was executed once. The P3 frozen TEST was
not rerun.

### DEV

- 421 pairs; accuracy `0.942993`.
- Macro precision/recall/F1: `0.942029 / 0.943872 / 0.925644`.
- Exact, near, version, temporal, template, and distinct: precision/recall/F1
  all `1.0`.
- Conflict: precision `1.0`, recall `0.936709`, F1 `0.96732`.
- Conditional: precision `1.0`, recall `0.55814`, F1 `0.716418`.
- 24 conservative abstentions beyond gold `UNCERTAIN`: 19 conditional cases
  lack usable scope/qualifier evidence; 5 conflict cases are P2-gated because
  market is missing.

### Frozen TEST

- 179 pairs; accuracy `0.921788`.
- Macro precision/recall/F1: `0.929293 / 0.94636 / 0.91677`.
- Exact, near, version, temporal, template, and distinct: precision/recall/F1
  all `1.0`.
- Conflict: precision `1.0`, recall `0.862069`, F1 `0.925926`.
- Conditional: precision `1.0`, recall `0.655172`, F1 `0.791667`.
- 14 conservative abstentions beyond gold `UNCERTAIN`: 10 conditional cases
  lack usable scope/qualifier evidence; 4 conflict cases are P2-gated.

The acceptance result is `PARTIAL`: macro F1 is below `0.95`, and conflict
recall is below `0.95`. All false-collapse, false-conflict, suppression,
provenance, permission, and automatic-reuse safety counters are zero. The
system deliberately preserves the abstentions instead of tuning against TEST.

## Controlled retrieval and version results

The controlled evaluation has seven queries at `K=6`:

| Metric | Before | After |
|---|---:|---:|
| Duplicate Redundancy@K | 0.333333 | 0.0 |
| Unique Evidence@K | 4 | 6 |
| Document Diversity@K | 6 | 6 |
| Base relevance recall | 1.0 | 1.0 |
| Context chunks/items | 21 | 13 |
| Context characters | 430 | 280 |

Conflict preservation, temporal match, current-version selection, provenance
retention, and unknown-current-validity preservation are all `1.0`. Context is
reduced by `34.8837%` in characters and `38.0952%` in chunks/items.

The controlled lineage graph has two edges, direction and lineage accuracy
`1.0`, current/historical/temporal selection accuracy `1.0`, and zero cycles.

## Real-world bridge supplement

The separate Vinhomes/VinFast bridge contains four cases and is not mixed into
the frozen P0/P1/P2/P3 corpus. DEV and TEST both score `4/4`, covering
table-to-prose and prose-to-table directions for equivalent and conflicting
content.

## Ablation

On frozen TEST, raw P3 claim evidence alone yields macro F1 `0.386714`.
Document aggregation raises it to `0.91677`; lineage then provides version
accuracy `1.0`; clustering reduces controlled duplicate redundancy to `0.0`;
authority preserves both conflict sides; retrieval policy keeps six unique
evidence items while reducing context characters by `34.8837%`.

## Performance

Frozen TEST measurements on local deterministic Python 3.12, in memory, with
no DB or network:

- aggregation per pair: mean `0.036123 ms`, p50 `0.035 ms`, p95 `0.0464 ms`;
- relation lookup: mean `0.006074 ms`, p50 `0.0058 ms`, p95 `0.008 ms`;
- retrieval policy per query: mean `0.044257 ms`, p50 `0.0341 ms`, p95
  `0.0931 ms`.

PostgreSQL `EXPLAIN ANALYZE` was not run because no local PostgreSQL instance
was available. The migration remains covered by static contract tests.

## Rollout recommendation

Keep P4 in `shadow` by default. Promote to `on` only after migration 34 has been
applied in staging, RLS/RPC behavior has been verified with real tenants, query
telemetry confirms no relevance regression, and the conditional/P2 missing-
market abstentions have an explicit data-quality or review workflow. Do not
lower the conservative gates using frozen TEST outcomes.
