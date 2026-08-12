# Vinhomes/VinFast duplicate-conflict gold dataset

This frozen P0 dataset evaluates chunk-level candidate generation, duplicate/version/variant classification, conflict safety, extraction noise, and missing context. It contains deterministic synthetic cases shaped by the supplied Vinhomes and VinFast reference documents.

> **Synthetic Vinhomes/VinFast values are not authoritative business facts. They exist only for system evaluation.**

No LLM or external model creates or judges the gold labels.

## Version and files

- Taxonomy/schema version: `duplicate-conflict-gold-v1`.
- Fixed split seed: `duplicate-conflict-gold-v1:20260812`.
- `gold_v1.jsonl`: all 600 pairs.
- `gold_v1_dev.jsonl`: 421 development pairs.
- `gold_v1_test.jsonl`: 179 frozen test pairs.
- `schema.json`: machine-readable JSON Schema.
- `stress_cases.json`: the 100-chunk sampling contract and SimHash/LSH counterexample.
- `tests/fixtures/duplicate_conflict_smoke.jsonl`: 18-pair CI smoke set, one case per domain and label.

The frozen test set must not be inspected to tune thresholds, rules, templates, or mappings. Use the development set for diagnosis and report the frozen test only for a predeclared comparison.

## Labels

| Label | Annotation rule |
| --- | --- |
| `EXACT_DUPLICATE` | Canonical text is identical after repository strict normalization. |
| `NEAR_DUPLICATE` | Same entity, business/time scope, claim, and value; materially different wording. |
| `VERSION_UPDATE` | A compatible successor adds or explicitly supersedes information without an overlapping contradiction. |
| `TEMPORAL_VARIANT` | Comparable claims apply to explicit non-overlapping periods. |
| `CONDITIONAL_VARIANT` | A material qualifier differs, such as trim, market, protocol, price type, or price basis. |
| `TEMPLATE_VARIANT` | Structure is strongly shared while entity/business identity differs. |
| `CONFLICT` | Entity, scope, qualifier, time, and claim align, but value or polarity is incompatible. |
| `DISTINCT` | No duplicate/version/variant/aligned-conflict relationship is justified. |
| `UNCERTAIN` | Extraction reliability or context is insufficient for a safe deterministic relation. |

The canonical descriptions and mappings from repository enums live in `configs/evaluation/duplicate_conflict_taxonomy.json`.

## Coverage

The full set has 300 Vinhomes and 300 VinFast pairs. Label distribution is:

| Label | Count |
| --- | ---: |
| `EXACT_DUPLICATE` | 60 |
| `NEAR_DUPLICATE` | 90 |
| `VERSION_UPDATE` | 72 |
| `TEMPORAL_VARIANT` | 72 |
| `CONDITIONAL_VARIANT` | 72 |
| `TEMPLATE_VARIANT` | 42 |
| `CONFLICT` | 108 |
| `DISTINCT` | 54 |
| `UNCERTAIN` | 30 |

Cases cover exact normalization variants, paraphrases, prices/ranges/operators, temporal changes, version extensions, property/model identity, structural numbers, price basis/type, market/trim/protocol qualifiers, battery/charging claims, negation, table-to-table, table-to-prose, OCR noise, parent context, same-value different-entity, and high-similarity conflicts.

## Important fields

- Identity/routing: `schema_version`, `pair_id`, `split`, `domain`, `category`.
- Gold input/output: `text_a`, `text_b`, `expected_relation`, `variation_type`.
- Annotation invariants: `same_entity`, `same_business_scope`, `same_temporal_scope`, `same_claim`, `same_value`, `critical_conflict`.
- Structured evidence: entity/scope objects, expected claims, expected claim relations, conflict fields, source forms, and optional table payloads.
- Reliability: OCR levels, extraction reliability, parent contexts, difficulty, annotation reason, and diagnostic hints.
- Provenance/safety: `is_synthetic`, source document names, review status, candidate requirement, and expected auto-reuse permission.

See `schema.json` for the exact types and required fields.

## Rebuild and validate

Run from the repository root with the checked project environment:

```powershell
# Regenerate all JSONL splits and stress/smoke artifacts deterministically
.\.venv\Scripts\python.exe scripts\build_duplicate_conflict_dataset.py

# Validate schema, taxonomy, annotation consistency, split stability, and suspicious duplicates
.\.venv\Scripts\python.exe scripts\validate_duplicate_conflict_dataset.py

# Fast smoke evaluation
.\.venv\Scripts\python.exe scripts\evaluate_duplicate_conflict.py tests\fixtures\duplicate_conflict_smoke.jsonl --no-write

# Full baseline evaluation and report regeneration
.\.venv\Scripts\python.exe scripts\evaluate_duplicate_conflict.py

# Focused tests
.\.venv\Scripts\python.exe -m pytest tests\evaluation\test_duplicate_conflict_dataset.py tests\evaluation\test_duplicate_conflict_metrics.py tests\evaluation\test_duplicate_conflict_runner.py -q
```

Generated files use stable pair IDs, sorted JSON keys, deterministic SHA-256 distractor ordering, and no timestamps. Two runs against unchanged code/data must be byte-identical.

## Evaluation interpretation

Stage A simulates the real pre-embedding SQL predicate and ordering over each annotated target plus 60 deterministic distractors. Stage B calls the real `analyze_text_relation()` only; it does not reimplement classification. The report also exposes direct/oracle-pair classification so candidate misses cannot hide classifier failures.

The code default has structured facts off (the audited workspace `.env` overrides it to `on`). The baseline separately reports prose-to-prose, table-to-table, and table-to-prose results through the generic text path, plus a real table-analyzer/table-diff capability diagnostic. Production ANN is explicitly unmeasured because it requires external OpenAI embeddings and the P0 run is offline.

## Limitations

- The corpus is template-generated, synthetic, and intentionally not a factual product/price database.
- Pair-level annotation cannot reproduce all parser, database tenancy, or document-aggregation effects.
- The controlled distractor corpus is realistic enough to test ranking ambiguity but is not a production notebook dump.
- ANN/vector quality is not approximated with a substitute embedding model.
- Parent context is annotated but intentionally withheld from the current isolated-chunk classifier to measure the existing gap.
- Gold labels were generated from explicit rules and mechanically validated; a second independent human review remains valuable before using the test split as an organization-wide release gate.
