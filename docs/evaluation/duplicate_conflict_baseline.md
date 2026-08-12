# Duplicate/conflict architecture snapshot (P0)

This document freezes the implementation observed for `duplicate-conflict-gold-v1`. It is an audit, not a proposal. The P0 changes do not alter any production algorithm, threshold, candidate limit, or runtime mode.

## Current end-to-end flow

```text
Upload and storage download
  -> parser/extraction + chunking (`pipeline.prepare`, contextualize=False)
  -> document ClaimScope extraction
  -> parsed-document fingerprint (strict SHA-256 identity + loose 64-bit SimHash)
  -> eligible document-level exact lookup
       -> in quality mode `on`, complete as duplicate and stop before embedding
  -> optional structured-table analysis (only when structured_fact_mode != off)
  -> contextual enrichment
  -> fingerprint every chunk
       -> strict chunk hash for every chunk
       -> fuzzy flag for at most 8 evenly sampled eligible chunks
  -> database pre-embedding lookup
       -> exact hash OR any aligned 8-bit SimHash band
       -> at most 5 candidates per probe
  -> application verification
       -> strict text equality for exact identity
       -> Hamming distance <= 24 for fuzzy candidates
       -> current deterministic text/scope/claim relation analysis
  -> exact embedding reuse gate
       -> same embedding model, stored vector, and embedding-input checksum
  -> embed remaining chunks
  -> ANN/vector lookup for at most 8 sampled chunks, top 5 per probe
  -> current text/scope/claim relation analysis with vector score
  -> document relation aggregation
  -> vector/document/quality-relation persistence
  -> optional structured-fact persistence and comparison
```

The orchestration above is in `app/ingestion/application/worker.py`. An exact *document* duplicate may end processing early. An exact *chunk* duplicate normally reuses only the embedding and lets the new document continue through indexing.

## Exact chunk behavior

`build_chunk_dedup_probes()` chooses `metadata["canonical_content"]` when present, otherwise `chunk.text`. `build_chunk_fingerprint()` applies `strict_normalize_text()` and hashes the result with SHA-256 under normalization version `knowledge-chunk-identity-v1`.

Strict normalization is intentionally narrow:

- Unicode NFC;
- remove soft hyphen, zero-width space, word joiner, and BOM;
- replace NBSP with a normal space;
- collapse whitespace runs.

It preserves case, punctuation, digits, and semantic wording. Database lookup may return an exact-hash match regardless of fuzzy sampling. The application then re-normalizes both texts and fails closed if the same hash maps to different normalized content. Automatic vector reuse additionally requires:

- quality mode `on`;
- the candidate embedding model equals the current model;
- a non-empty stored vector;
- candidate `embedding_text_checksum` equals the current normalized embedding-input checksum.

Within one incoming batch, exact matches reuse the earliest matching chunk. A strict content match can therefore be observed without vector reuse when contextual embedding text differs.

## Components and current parameters

| Component | Current mechanism | Input -> output | Parameters / limit | Scope and failure risk | Source |
| --- | --- | --- | --- | --- | --- |
| Document identity | Canonical parsed-document projection, strict SHA-256 and 64-bit SimHash | parsed document -> `DocumentFingerprint` | auto identity requires >=40 characters, >=6 tokens, trusted extraction, no unrepresented visuals | exact full-document shortcut; extraction omissions can make identity unsafe, therefore eligibility is conservative | `app/knowledge_quality/application/analysis.py`; `app/knowledge_quality/application/canonical_content.py`; `app/ingestion/application/worker.py` |
| Exact chunk | SHA-256 of strict-normalized canonical chunk | chunk text -> strict hash | normalization `knowledge-chunk-identity-v1`; every chunk is fingerprinted | exact hash is authoritative only after normalized-text verification | `app/knowledge_quality/application/analysis.py::build_chunk_fingerprint`; `app/knowledge_quality/application/chunk_preembedding.py` |
| Fuzzy chunk fingerprint | token SimHash | loose-normalized tokens -> 64-bit hex signature | width 64 bits; maximum Hamming distance 24 | Hamming is a recheck, not an exhaustive index query | `app/knowledge_quality/application/analysis.py`; `app/knowledge_quality/application/chunk_preembedding.py` |
| LSH candidate lookup | aligned-band equality | 64-bit signature -> SQL candidates | 8 bands x 8 bits; any one aligned band; exact hash bypasses band requirement; 5 candidates/probe at runtime | a pair can be within Hamming 24 yet share zero aligned bands; P0 stress case proves this | `supabase/migrations/10_chunk_preembedding_dedup.sql`; `simhash_lsh_bands()` |
| Fuzzy probe selection | evenly spaced sampling over eligible chunks | all chunk indexes -> probe flags | maximum 8 by default; exact lookup still applies to all chunks | relations located between sampled positions are never requested as fuzzy candidates | `build_chunk_dedup_probes()` and `_sample_indexes()` |
| Pre-embedding classifier | lexical, containment, claim projection, explicit scope and aligned claim checks | candidate text pair -> `TextRelationAnalysis` | near gates: semantic >=.92, or projection >=.86 + length ratio >=.85; later semantic >=.88 + projection >=.40, or projection >=.82; version containment >=.72 + projection >=.52; temporal support >=.35 | no native generic `CONDITIONAL_VARIANT` or `UNCERTAIN`; rich domain qualifiers are largely absent | `app/knowledge_quality/application/analysis.py` |
| Claim alignment | deterministic clauses, dates, quantities, modality, negation | text pair -> aligned claim conflicts | candidate alignment >=.58; validated alignment >=.82 | model/building/unit codes and domain-specific units can be confused with semantic quantities or remain unknown | `app/knowledge_quality/application/claims.py` |
| Scope | explicit document/project/contract and temporal extraction | text/filename -> `ClaimScope` and comparison | temporal divergence needs explicit periods; a one-year-or-more effective-date gap is divergent | no complete Vinhomes building/unit/property/price-basis or VinFast model/trim/market/protocol scope | `app/knowledge_quality/application/scope.py` |
| Pre-embedding aggregation | relation priority and coverage | matched chunk pairs -> document relation | conflict confidence >=.62 with validated aligned claims/same scope; other relations require coverage >=.35 | only sampled fuzzy evidence contributes | `app/knowledge_quality/application/chunk_preembedding.py` |
| ANN candidate lookup | configured vector index cosine/distance query | embedded sampled chunks -> nearest chunks | maximum 8 probes, top 5 each | requires the production OpenAI embedding path; not executed by the offline P0 run | `app/knowledge_quality/application/detection.py`; `app/pipeline/indexing/adapters/vector_indexes.py` |
| ANN aggregation | group matched chunk pairs by target document | pair analyses -> document relation | exact coverage >=.65 selects version otherwise near; non-conflict coverage >=.35; conflict minimum coverage 0 but still requires validated aligned claims and compatible scope | sampling and vector top-k can hide isolated conflicts | `app/knowledge_quality/application/detection.py` |
| Structured table extraction | deterministic every-row header/value normalization | `ParsedTable` -> structured claims | trusted claim confidence >=.70; extractor `structured-table-v1` | strong Vinhomes commercial headers, weaker VinFast-specific vocabulary; no prose bridge | `app/structured_facts/application/table_analyzer.py` |
| Structured table diff | linear subject+predicate and stable-qualifier join | two table analyses -> claim relations | low confidence/unknown scope or qualifiers -> uncertain; disjoint qualifiers -> conditional; non-overlap time -> updated | duplicate business keys are uncertain; only table-to-table | `app/structured_facts/application/table_diff.py` |

## Runtime defaults audited

| Setting | Default |
| --- | ---: |
| `knowledge_quality_mode` | `on` |
| `knowledge_quality_max_probe_chunks` | `8` |
| `knowledge_quality_candidates_per_probe` | `5` |
| `knowledge_quality_conflict_prompt_enabled` | `true` |
| `structured_fact_mode` | `off` |
| SimHash width | `64` bits |
| SimHash LSH layout | `8 x 8` bits |
| SimHash recheck threshold | Hamming `<= 24` |
| sparse retrieval top-k | `20` |
| dense retrieval top-k | `20` |
| final retrieval top-k | `6` |
| RRF k | `60` |
| MMR lambda | `0.7` |
| max retrieved chunks/document | `2` |

Settings are defined in `app/bootstrap/settings.py` and mirrored by `.env.example`. Production ingestion additionally enforces OpenAI `text-embedding-3-small`; this P0 benchmark does not make external embedding or LLM calls.

At audit time, the workspace `.env` explicitly overrides `STRUCTURED_FACT_MODE=on` and selects the required OpenAI embedding provider/model; the knowledge-quality limits are not overridden there. This is a local effective configuration, not the class/default contract. The reproducible aggregate report freezes the code defaults and adds a separate real table-analyzer/table-diff capability diagnostic so that the local override does not make report bytes environment-dependent.

## Candidate storage scope

The chunk-candidate RPC in `supabase/migrations/10_chunk_preembedding_dedup.sql` limits lookup to the same owner/notebook, excludes the current document, and considers ready/active/current/canonical documents. It excludes documents already marked duplicate/superseded and requires the latest succeeded ingestion to use the same embedding model and dimensions. Results sort exact hash first, then aligned-band count, then stable document/chunk identifiers.

## Known risks frozen for measurement

1. Aligned-band LSH has false negatives even inside the Hamming recheck radius.
2. Eight evenly spaced probes can miss isolated relations in long documents.
3. Generic scope does not represent many decisive Vinhomes/VinFast qualifiers.
4. Generic text classification cannot emit all gold taxonomy classes.
5. Table-to-prose has no structured claim bridge, and structured facts are off by default.
6. Exact canonical text can legitimately fail vector reuse when contextual embedding input changes; this protects correctness but reduces reuse.
7. ANN quality is dependent on external embeddings and was deliberately left unmeasured in the deterministic offline P0 baseline.

Measured evidence for these risks is in `reports/evaluation/duplicate_conflict_baseline.md` and its JSON companion.
