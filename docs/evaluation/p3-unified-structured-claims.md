# P3 unified structured claims

## Decision boundary

P3 sits strictly after P1 candidate generation and the P2 entity/business-scope
gate. It extracts, aligns, and compares individual facts. It does not change
embedding reuse, merge entities, override a disjoint P2 scope, choose a winning
source, or aggregate final document relations.

```text
P1 candidate pair
  -> P2 entity/scope admission
  -> prose extraction or table analysis
  -> unified StructuredClaim
  -> value-free ClaimComparableKey
  -> bounded claim alignment
  -> ValueExpression comparison
  -> claim-level relation evidence for P4
```

## Audit of the two pre-P3 claim paths

The legacy prose path in `app/knowledge_quality/application/claims.py` emits
`ExtractedClaim`, `ClaimKey`, and `ClaimValue`. It is useful as a rollout
baseline: it retains clause spans, classifies identifier versus quantity roles,
and exposes conservative mismatch reasons. Its identity is still dominated by
surface comparison text and `SequenceMatcher`; negation is sentence/clause
level; numeric values are string/scalar representations; and the model has no
complete `BusinessScope`, `TemporalContext`, source authority, versioned value
operators, or durable structured-fact persistence contract.

The table path already emitted `StructuredClaim` with `NormalizedValue`,
`BusinessScope`, `ClaimQualifiers`, `TemporalContext`, `ClaimProvenance`, and
authority. P3 makes that model canonical for both source forms. `ExtractedClaim`
remains a legacy/shadow adapter only. No third long-lived claim model was added.

## Canonical contract and versioning

`StructuredClaim` now carries a `ValueExpression` and evidence while keeping a
legacy `NormalizedValue` adapter. It separates:

- comparable identity: canonical subject, predicate, stable scope, stable
  qualifiers, and claim-period applicability;
- occurrence identity: comparable hash plus document, value expression,
  provenance, derivation, and extractor version.

The value is deliberately absent from the comparable identity. Explicit
versions are recorded for the predicate registry, value normalization,
operator normalization, prose extraction, comparable key, and alignment.

## Predicate taxonomy and extraction

The versioned registry supports these source-grounded predicates:

- Vinhomes: `property_price`, `property_area`, `management_fee`,
  `maintenance_fee`, `discount_rate`, `payment_term`, `handover_time`,
  `availability`, `amenity`, `construction_progress`;
- VinFast: `vehicle_price`, `driving_range`, `battery_capacity`,
  `charging_time`, `charging_power`, `motor_power`, `torque`, `acceleration`,
  `feature_availability`, `warranty_duration`, `vehicle_dimensions`, and the
  observed `service_feature` predicate.

Extraction assembles P2 context, segments bounded sentences/clauses, resolves a
canonical P2 entity, recognizes domain predicates rather than generic verbs,
assigns numeric roles, parses one value expression per predicate, attaches
claim-local scope/qualifiers/time, and records source span, chunk, page, block,
evidence, confidence, and the composite extractor version. Headings and parent
context are inherited only through P2 evidence precedence. Missing VinFast
market evidence remains unknown.

Newline handling preserves ordinary OCR-wrapped prose but treats explicit
`YYYY: value` rows as claim boundaries. Thus a three-year chunk emits three
independent claims instead of one chunk-wide year.

## ValueExpression semantics

Supported operators are `EXACT`, `APPROXIMATE`, `RANGE`, `LT`, `LTE`, `GT`,
`GTE`, `BOOLEAN`, `ENUM`, `TEXT`, and fail-closed `UNKNOWN`. Values use
`Decimal`. Vietnamese and English decimal/group separators, billion/million
magnitudes, VND/USD/EUR dimensions, price basis, m², km/m, kWh/Wh, kW/W, Nm,
minutes/seconds, percent, months/years, boolean polarity, and OCR ambiguity are
handled deterministically. There is no live FX conversion and no implicit
price-per-unit/price-per-m² derivation.

Comparison converts only exact same-dimension units, constructs mathematical
intervals, and returns `EQUIVALENT`, `COMPATIBLE`, `DISJOINT`, `UNKNOWN`, or
`INCOMPATIBLE_DIMENSION`. Examples:

- `6.2B VND/unit` equals `6200M VND/unit`;
- `450 km` equals `450000 m`;
- `5.8–6.4B` is compatible with `6.2B` but disjoint from `7B`;
- `<=6.5B` is compatible with `6.2B`; `<=5B` is disjoint from `7B`;
- TRUE and FALSE for the same feature are disjoint;
- VND versus USD, km versus kWh, or per-unit versus per-m² is an incompatible
  dimension, never an inferred conversion.

Approximation uses a frozen relative interval after canonical unit conversion:
2% for property/vehicle prices, driving range, and charging time; 1% for
battery capacity, power, torque, and property area. The default for other
supported numeric predicates is 2%. These tolerances are comparison semantics,
not a rewrite to strict equality.

## Alignment and relations

Alignment groups claims by canonical subject and predicate, then uses the
value-free comparable hash. Unique groups are O(n+m). Duplicate comparable
keys are never zipped by position; a bounded ambiguous group becomes
`UNCERTAIN`. Equal values alone cannot align different entities or predicates,
and different values do not prevent alignment of the same fact.

The relation layer emits `UNCHANGED`, `UPDATED`, `ADDED`, `REMOVED`,
`CONDITIONAL_VARIANT`, `CONFLICT_CANDIDATE`, or `UNCERTAIN`. A conflict requires
an admitted comparable scope, overlapping applicability, adequate confidence,
and disjoint value expressions. Non-overlapping effective intervals produce
`UPDATED`; protocol/price-basis/other scope variants stay conditional; unknown
critical evidence stays uncertain.

## Table/prose bridge and persistence

Table claims pass through `canonicalize_table_claims` before persistence, so
table and prose share subject, predicate, scope, qualifier, temporal, and value
contracts. Both directions are exercised for Vinhomes prices and VinFast range
facts. Production comparison uses the legacy table diff for table↔table and the
P3 aligner whenever either snapshot is prose. A unified snapshot pair is seeded
only by an exact value-free candidate-identity overlap; P3 cannot manufacture a
cross-scope conflict from schema or value similarity.

Migration 16 already stores indexed candidate identity, subject/predicate,
qualifiers, temporal fields, normalized JSON values, provenance, confidence,
and extractor versions under owner/notebook RLS. P3 therefore needs no schema
migration or second claim database. Prose evidence is represented by a
deterministic zero-column source snapshot in the same atomic replacement RPC;
the actual P3 extractor/time/evidence is preserved in provenance for migration
16 wire compatibility. Existing legacy table claims are canonicalized when
loaded. Existing prose content is deterministically extracted during a P3
shadow/on ingestion, so rollout does not require destructive backfill.

## Evaluation annotation policy

The P0 pair dataset is reused only where its expected claims agree with visible
source evidence. Variations whose seed claims contradict the source or omit
operator/range semantics are excluded from extraction scoring and listed in
the frozen configuration. They remain in alignment, conflict, safety, and
coverage evaluation where applicable.

Value/operator/unit metrics use the independently hand-authored, versioned
`p3_value_gold_v1.jsonl`; expected values are not generated by the production
parser. Clean cross-format coverage absent from a P0 direction uses the
independently authored `p3_bridge_gold_v1.jsonl`, covering both directions and
both domains. TEST annotations are stored before configuration freeze and are
not used to tune DEV rules.

The DEV report contains 421 P0 pairs, 456 trusted extraction claims, 24 manual
value cases, and four clean bridge cases. All acceptance gates pass. Five true
conflict pairs remain blocked by frozen P2 because market evidence is absent;
P3 records `P2_GATE_BLOCKED` and does not guess a default market.

After freezing configuration hash
`A5BF4C391C27D7CF4535A6C853A24C55B40453E32F2D38F20B893C84CB34000E`,
TEST was run once. On 179 pairs it produced claim extraction 186/186,
alignment 141/141, and conflict classification 25 true positives, 67 true
negatives, zero false positives, and zero false negatives. All 16 TEST value
cases and all four clean bridge cases passed. Four true conflicts remain
`P2_GATE_BLOCKED` because source-visible VinFast market evidence is absent;
this is the frozen P2 safety behavior, not a P3 override opportunity.

## Rollout and safeguards

`STRUCTURED_FACT_MODE=off` adds no P3 metadata or persistence. `shadow` runs
and persists P3 evidence without changing retrieval/generation output. `on`
enables the existing structured-evidence path after acceptance. Extraction is
capped at 64 claims per chunk, ambiguous alignment is capped at eight claims,
and failures remain isolated from ordinary ingestion. No external LLM, NLI,
network unit service, or FX service is required.

P4 should consume these claim counts/relations to aggregate document outcomes
and apply authority/version lineage. P3 itself does not make that aggregation.
