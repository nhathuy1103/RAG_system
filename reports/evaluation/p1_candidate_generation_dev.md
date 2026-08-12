# P1 candidate generation — DEV

> Frozen P0 gold labels and split; deterministic offline ANN fixture; no network calls.

## Primary result

- Recall@1/5/10/20/50: **49.9% / 83.1% / 90.9% / 93.1% / 100.0%**.
- Retrieval population: **361**; final candidate cap: **50**.
- Latency mean/p50/p95/max (controlled 61-item corpus): **140.020041 / 130.3986 / 199.7105 / 238.1721 ms**.

## Binary strategies

| Strategy | R@5 | R@20 | R@50 |
| --- | ---: | ---: | ---: |
| fixed_8x8 | 47.1% | 49.6% | 49.6% |
| fixed_8x8_multiprobe_r2 | 67.3% | 79.8% | 92.2% |
| simhash-multilayout-8x8-v1 | 67.0% | 78.4% | 79.8% |

## Channel ablation

| Configuration | R@5 | R@20 | R@50 |
| --- | ---: | ---: | ---: |
| all_channels | 83.1% | 93.1% | 100.0% |
| all_minus_ann | 83.1% | 92.5% | 100.0% |
| all_minus_binary | 87.8% | 94.2% | 100.0% |
| all_minus_exact | 83.1% | 93.1% | 100.0% |
| all_minus_fts | 79.2% | 85.0% | 94.2% |
| exact_ann | 81.2% | 83.9% | 92.2% |
| exact_binary | 70.6% | 79.5% | 79.8% |
| exact_fts | 85.6% | 95.8% | 100.0% |
| exact_only | 10.8% | 10.8% | 10.8% |

## Stress and safety

- Long-document eligible/meaningful coverage: **100.0% / 100.0%**.
- Hamming-21 counterexample: fixed overlap **0**, multi-layout overlap **1**.
- False automatic reuse: **0**.

## Interpretation limits

- FTS is a deterministic local ranking approximation over the same bounded OR terms; the migration uses the real PostgreSQL `search_vector`/GIN/`ts_rank_cd` path.
- ANN uses a locked 1024-dimensional hashed fixture so CI requires no model or network; production uses the configured vector index and existing document embeddings.
- The 10k scale result is an in-memory inverted-index diagnostic, not a production PostgreSQL/Qdrant latency claim. No 100k run was made under the workstation memory guard.
