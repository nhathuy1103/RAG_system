# P1 candidate generation — TEST

> Frozen P0 gold labels and split; deterministic offline ANN fixture; no network calls.

## Primary result

- Recall@1/5/10/20/50: **52.9% / 87.7% / 92.9% / 96.1% / 100.0%**.
- Retrieval population: **155**; final candidate cap: **50**.
- Latency mean/p50/p95/max (controlled 61-item corpus): **134.949907 / 137.8704 / 162.4938 / 171.0189 ms**.

## Binary strategies

| Strategy | R@5 | R@20 | R@50 |
| --- | ---: | ---: | ---: |
| fixed_8x8 | 47.7% | 49.0% | 49.0% |
| fixed_8x8_multiprobe_r2 | 74.2% | 83.2% | 94.8% |
| simhash-multilayout-8x8-v1 | 69.7% | 83.2% | 83.2% |

## Channel ablation

| Configuration | R@5 | R@20 | R@50 |
| --- | ---: | ---: | ---: |
| all_channels | 87.7% | 96.1% | 100.0% |
| all_minus_ann | 87.7% | 95.5% | 100.0% |
| all_minus_binary | 90.3% | 99.4% | 100.0% |
| all_minus_exact | 87.7% | 96.1% | 100.0% |
| all_minus_fts | 80.6% | 89.7% | 98.7% |
| exact_ann | 81.9% | 87.7% | 97.4% |
| exact_binary | 72.9% | 83.2% | 83.2% |
| exact_fts | 87.1% | 100.0% | 100.0% |
| exact_only | 13.5% | 13.5% | 13.5% |

## Stress and safety

- Long-document eligible/meaningful coverage: **100.0% / 100.0%**.
- Hamming-21 counterexample: fixed overlap **0**, multi-layout overlap **1**.
- False automatic reuse: **0**.

## Interpretation limits

- FTS is a deterministic local ranking approximation over the same bounded OR terms; the migration uses the real PostgreSQL `search_vector`/GIN/`ts_rank_cd` path.
- ANN uses a locked 1024-dimensional hashed fixture so CI requires no model or network; production uses the configured vector index and existing document embeddings.
- The 10k scale result is an in-memory inverted-index diagnostic, not a production PostgreSQL/Qdrant latency claim. No 100k run was made under the workstation memory guard.
