# P2 domain entity resolution and business scope

## Purpose and boundary

P2 answers whether two pieces of evidence refer to the same business subject under comparable
entity, business-scope, qualifier, and temporal conditions. It gates the existing relation
analyzer; it does not redesign value comparison, claim extraction, NLI, or P1 candidate retrieval.

The safety bias is precision-first: missing or ambiguous required evidence produces `UNKNOWN` and
cannot enter value-level conflict analysis. P2 never grants embedding reuse. Reuse remains limited
to the strict exact-content path frozen in P1.

## Architecture audit and convergence

Before P2, two partially overlapping representations existed:

- `knowledge_quality.domain.ClaimScope` represented document/project/contract routing plus coarse
  year, quarter, period, and version fields. It remains the legacy comparison and shadow baseline.
- `knowledge_quality.domain.ClaimKey` represented a text-derived subject/predicate/attribute/unit
  alignment key. It is value-free, but it lacked canonical domain entity and detailed applicability
  facets.
- `structured_facts.domain.BusinessScope` already represented location, product, and commercial
  facets. P2 extends this canonical type with `VehicleScope`, canonical `EntityRef` values, and
  explicit-breadth evidence instead of creating a third independent scope system.
- `structured_facts.domain.ClaimQualifiers` remains the stable/optional qualifier contract.
  Stable qualifiers affect comparable identity; optional qualifiers remain interpretable evidence
  but do not silently become wildcard scope.
- `structured_facts.domain.TemporalContext` remains the canonical temporal contract and now carries
  per-claim `reference_period` and `claim_periods` in addition to publication, effective,
  observation, and ingestion time.

`ResolvedBusinessContext` is an envelope over those canonical structured-facts types. Its
`ClaimComparableKey` combines canonical entity IDs, predicate, stable business-scope identity,
stable qualifiers, and temporal applicability. Claim values are deliberately excluded. The older
`ClaimScope` and `ClaimKey` are retained for backward compatibility and shadow comparison; they are
not copied into another domain model.

## Deterministic entity resolution

Versioned registries live in `configs/domain_entities`. Every entry contains a deterministic
canonical ID, entity type, canonical name, explicit aliases/codes, parent ID, and domain. The
resolver performs normalization and exact registry lookup only; there is no fuzzy auto-merge.

Evidence precedence is:

1. explicit claim text;
2. table cell and table header;
3. section heading;
4. parent section context;
5. verified document metadata;
6. registry-supported fallback.

An `EntityRef` retains canonical identity, parent, confidence, registry version, raw mentions,
match method, evidence source, source ID, and a source span for direct text. Ambiguous aliases or
OCR-corrupted identifiers fail closed.

The checked-in synthetic registry supports Vinhomes project aliases and VinFast `VF6` through
`VF9`, including the equivalent spellings `VF8`, `VF 8`, `VinFast VF8`, and `VinFast VF 8`.

## Vinhomes scope

The location facet supports developer, project, phase, subdivision, building, and unit. Project
identity comes from the registry; lower hierarchy levels are deterministic scoped entity refs with
parent provenance. `S1`/`S2` and unit `1208`/`1508` are identifiers, not quantities.

The product facet supports property type, bedrooms, area type, and product variant. The commercial
facet distinguishes official, primary, secondary, asking, transaction, reference, average, and
from-price semantics, plus per-unit/per-m2/per-month/total-contract basis, payment plan, discount,
VAT, and maintenance-fee applicability where evidence exists.

## VinFast scope

`VehicleScope` participates in the same `BusinessScope` comparison contract and supports
manufacturer, canonical model, trim, model year, battery variant, drivetrain, market, test
protocol, and charging variant. Model year is separate from document publication/effective time.
WLTP, EPA, and NEDC are applicability qualifiers, so protocol differences are conditional variants,
not plain numeric conflicts.

Structured table rows now pass vehicle cells through the same registry-backed resolver as prose.
For example, table `VF 8 | Eco | WLTP | 450 km` and prose `VF 8 Eco ... 480 km ... WLTP` both carry
model `vinfast_vf8`, manufacturer `vinfast`, trim `eco`, and protocol `WLTP`; table entity evidence
is explicitly marked `TABLE_CELL`.

## Scope, qualifier, and temporal comparison

The common scope result is one of `SAME`, `LEFT_CONTAINS_RIGHT`, `RIGHT_CONTAINS_LEFT`, `OVERLAPS`,
`DISJOINT`, or `UNKNOWN`. Missing evidence is `UNKNOWN`. Containment is available only when broad
applicability is explicit, such as “all VF 8 variants.”

Qualifier stability is predicate-aware. Vehicle range uses model/trim/model-year/battery/market/
protocol; vehicle price uses model/trim/model-year/market/commercial price type; property price uses
project/product/commercial/basis/temporal applicability. A missing required stable qualifier blocks
admission rather than being treated as “all.”

`TemporalContext` distinguishes publication, effective interval, observation, ingestion,
reference period, and per-claim periods. Ingestion time never acts as business validity. Multi-year
text retains all claim periods so a later StructuredClaim extractor can align 2024↔2024,
2025↔2025, and 2026↔2026 rather than choosing one representative year.

## Conflict admission and rollout

The admission gate applies in this order:

1. unresolved/ambiguous required entity → `UNCERTAIN`;
2. different canonical entity → `DISTINCT_ENTITY`;
3. disjoint stable business/measurement scope → `CONDITIONAL_VARIANT`;
4. non-overlapping temporal applicability → `TEMPORAL_VARIANT`;
5. missing required business, qualifier, or temporal evidence → `UNCERTAIN`;
6. compatible entity + scope + qualifiers + time + predicate → `ADMIT`.

`domain_scope_mode="shadow"` records the legacy and P2 decisions plus reason codes without
suppressing the existing classifier. `domain_scope_mode="on"` enforces the gate. Persisted
`entity_scope` metadata is versioned and preferred; legacy chunks fall back to deterministic
resolution without requiring immediate re-ingestion.

## Persistence and versions

Chunk metadata persists the schema version, business-scope version, registry versions, entities,
scope facets, qualifiers, temporal evidence, predicate, evidence provenance, ambiguity markers,
and a value-free comparable-key hash. Supabase migration `33_domain_entity_scope_metadata.sql`
adds optional metadata indexing without changing P1 candidate or embedding-reuse logic.

Current versions are:

- entity normalization: `p2-entity-normalization-v1`;
- entity-scope metadata: `p2-entity-scope-metadata-v1`;
- business scope: `p2-business-scope-v1`;
- conflict admission: `p2-conflict-admission-v1`;
- Vinhomes registry: `p2-vinhomes-entities-v1`;
- VinFast registry: `p2-vinfast-entities-v1`.

## Evaluation and frozen-test policy

The P2 evaluator consumes the frozen gold splits and does not retune P1. It reports entity,
scope, temporal, qualifier, admission, safety, domain/difficulty/OCR breakdowns, ablations,
critical cases, classifier impact, and pair-level evidence.

Frozen configuration was finalized before the single P2 TEST run. DEV meets every configured
acceptance target. Frozen TEST preserves perfect entity and admission precision and all safety
invariants, but admission recall is `0.958333`, below the `0.97` target, because four otherwise true
VinFast conflicts lack recoverable market evidence and are conservatively `UNKNOWN`. No rule was
tuned after seeing TEST.

See:

- `reports/evaluation/duplicate_conflict_p2_scope_dev.md` and `.json`;
- `reports/evaluation/duplicate_conflict_p2_scope_test.md` and `.json`;
- `reports/evaluation/p1_candidate_generation_dev.md` and frozen TEST report.

## Remaining boundary for P3

P2 still operates on deterministic text-level predicates and existing table claims. The remaining
errors are dominated by claim extraction/alignment, value and operator/range normalization,
table↔prose claim alignment beyond shared scope, and unchanged classifier thresholds. P3 should
introduce a unified `StructuredClaim` extraction/alignment path while reusing P2 canonical entity,
scope, qualifier, temporal, and provenance contracts unchanged.
