# P1 high-recall chunk candidate generation

## Scope and frozen inputs

P1 changes candidate generation only. The P0 gold files, labels, DEV/TEST split,
normalization, relation classifier, claim logic, thresholds, and automatic reuse
contract are unchanged. Tuning uses DEV. The CLI requires `--frozen-test` for TEST
and refuses to overwrite an existing TEST report by default.

## Confirmed P0 path

The legacy ingestion path fingerprints every chunk but marks at most eight chunks
for fuzzy lookup. PostgreSQL then uses eight aligned 8-bit SimHash bands and returns
five candidates per sampled chunk. After embedding, ANN independently samples at
most eight chunks and also returns five hits. PostgreSQL FTS exists on
`document_chunks.search_vector` with a GIN index, but it did not participate in
duplicate/conflict candidate generation.

These mechanics explain the P0 failure modes: long-document blind spots, an
aligned-band false negative at Hamming distance 21, small candidate budgets, and
no union of lexical/binary/semantic evidence.

## P1 data flow

For each auto-identity-eligible source chunk:

1. Strict SHA-256 identity remains the authoritative exact channel.
2. The binary channel generates 64 keys from eight deterministic permutations of
   the same 64-bit SimHash. PostgreSQL stores generated keys and indexes the
   `text[]` with GIN. Application code still applies the Hamming-24 guard to
   binary-only candidates before classification.
3. The FTS channel selects at most 16 deterministic OR terms and queries the
   existing `search_vector`/GIN infrastructure with `ts_rank_cd`.
4. After embedding, the ANN channel queries the configured vector index for every
   eligible chunk. It uses the production embedding and vector backend; P1 does
   not introduce a second embedding model or a network call.
5. Candidates are deduplicated by `(source_chunk_index, target_chunk_id)`. Each
   retained candidate carries its per-channel rank, score, and binary-key match
   count. Reciprocal-rank fusion uses `k=60`, reserves four slots per channel,
   applies stable UUID/index tie-breaks, and caps the final list at 50.
6. The existing deterministic relation classifier receives the fused candidates.
   No P1 classifier, NLI, or LLM decision was added.

## Binary strategy decision

DEV compares three bounded/indexable variants:

- existing fixed 8×8 aligned bands (8 stored/query keys);
- fixed 8×8 with radius-2 byte multi-probe (8 stored keys, 296 query keys);
- selected multi-layout 8×8 (64 stored/query keys).

Radius-2 multi-probe has stronger binary-only Recall@50 on DEV, but it expands
each query to 296 keys. Multi-layout uses a symmetric 64/64 storage/query budget,
recovers the frozen Hamming-21 zero-aligned-band case, and relies on independent
FTS and ANN channels for remaining recall. This is the selected production trade-off.

## Bounds and operational settings

The intentionally small public surface is:

- `KNOWLEDGE_CANDIDATE_GENERATION_MODE=legacy|shadow|on` (default `shadow`);
- `KNOWLEDGE_CANDIDATE_CHANNEL_K` (DEV-selected default 30, maximum 50);
- `KNOWLEDGE_CANDIDATE_FINAL_TOP_K` (default/maximum 50).

Hidden constants keep the RRF rank constant, four-slot channel reservation, binary
layout, and 16-term FTS bound stable. Probe payloads are batched at 128. SQL validates
the batch and per-channel limit and only accepts the service role.

## Tenant isolation and persisted-state filters

`find_chunk_candidates_v2` requires the same owner and notebook as the ingestion
job, excludes the source document, and keeps only ready, active, current,
non-canonicalized, non-duplicate/non-superseded documents. It joins the latest
successful ingestion job to validate persisted vector dimensions. The legacy RPC
and indexes remain in place for rollback.

## Exact reuse safety

Candidate generation is never authoritative identity. An embedding is reused only
when all existing gates pass:

- strict hash match;
- strict normalized source/target text equality (hash collision/inconsistent data
  raises `ChunkIdentityConflictError`);
- identical embedding-input checksum;
- identical embedding model;
- non-empty persisted vector.

FTS, binary, or ANN evidence alone can never trigger reuse. P1 DEV reports zero
false automatic reuse.

## Shadow rollout and rollback

In `shadow`, the worker executes v2 pre/post-embedding generation and records
probe, ANN, fused-candidate, relation, and channel counts, while legacy candidates
remain the active decision path. In `on`, v2 supplies active candidates. Set the
mode back to `legacy` for immediate application rollback; migration 32 is additive,
so rollback does not require dropping its generated column, index, or RPC.

Recommended promotion gates are: DEV and frozen TEST Recall@50 at least 95%, false
reuse zero, no tenant-scope regression, bounded p95 candidate count/latency, and
shadow metrics consistent with the offline channel mix.

## Evaluation and limits

Run DEV:

```powershell
python scripts/evaluate_p1_candidate_generation.py --split dev
```

Run frozen TEST once after configuration lock:

```powershell
python scripts/evaluate_p1_candidate_generation.py --split test --frozen-test
```

The offline FTS fixture approximates ranking over the same selected OR terms; the
migration is the real PostgreSQL FTS path. The deterministic ANN fixture is a
locked 1024-dimensional SHA-256 feature projection and makes no network calls; it
tests channel plumbing and repeatability, not OpenAI embedding quality. The 10k
stress measurement is an in-memory inverted-index diagnostic, not a claim about
production PostgreSQL/Qdrant latency. A 100k run is explicitly not reported because
of the workstation memory guard.
