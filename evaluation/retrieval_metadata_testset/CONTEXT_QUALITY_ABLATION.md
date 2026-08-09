# Context quality ablation A/B/C/D và shuffled control

## Mục tiêu

Bộ chạy này cô lập giá trị của deterministic header, raw OpenAI context và
gold/effective context. `contextual_search_terms` không được đưa vào text của năm
biến thể, nên kết quả không bị lẫn giữa summary và terms.

| Mode | Text được index |
|---|---|
| `ctx_a_chunk_only` | Chunk gốc |
| `ctx_b_deterministic_header` | Document/section/content/table header + chunk |
| `ctx_c_raw_context_dense_only` | B + raw OpenAI context chỉ trong dense embedding |
| `ctx_c_raw_context_sparse_only` | B + raw OpenAI context chỉ trong sparse/BM25 text |
| `ctx_c_raw_context` | B + raw OpenAI summary + chunk |
| `ctx_d_effective_context` | B + gold/effective summary + chunk |
| `ctx_e_shuffled_context` | B + summary của chunk khác trong cùng tài liệu + chunk |

Structured filter metadata được giữ cố định giữa năm mode. Vì vậy khác biệt retrieval
đến từ text được index, không phải do một mode có filter còn mode khác không có.

`ctx_e_shuffled_context` là negative control. Nếu mode này gần bằng
`ctx_c_raw_context`, raw summary có thể quá generic hoặc hệ thống chỉ được lợi từ
keyword cấp tài liệu.

## Chạy bằng OpenAI

```powershell
Set-ExecutionPolicy -Scope Process -ExecutionPolicy RemoteSigned
& ".\.venv\Scripts\Activate.ps1"

.\evaluation\retrieval_metadata_testset\run_context_quality_ablation.ps1 `
  -EmbeddingProvider openai `
  -EmbeddingModel text-embedding-3-small `
  -ContextMaxWords 45 `
  -ContextMaxOutputTokens 400 `
  -Repeats 3 `
  -BootstrapSamples 5000
```

Mặc định output nằm tại:

`evaluation/retrieval_metadata_testset/runs/real-benchmark-v3-context-quality-v4-openai`

## Chạy smoke test không tốn embedding OpenAI

Context vẫn dùng OpenAI, nhưng vector dùng hashing:

```powershell
.\evaluation\retrieval_metadata_testset\run_context_quality_ablation.ps1 `
  -EmbeddingProvider hashing `
  -ContextMaxWords 45 `
  -Repeats 1 `
  -BootstrapSamples 1000
```

## Các file cần xem

- `context_quality_audit.csv`: hai dòng raw/effective cho mỗi chunk và điểm 5 tiêu chí.
- `context_quality_audit.summary.json`: tổng hợp lỗi và quyết định quality gate.
- `metadata_audit.csv`: token trung bình/P95 của từng mode.
- `metrics_all_queries/retrieval_metric_comparison.csv`: paired delta toàn bộ query.
- `metrics_all_queries/retrieval_metric_by_slice.csv`: kết quả theo slice.
- `metrics_filter_capable/retrieval_metric_comparison.csv`: tập có structured filter.

## Cách đọc bốn comparison chính

- `header_minus_chunk`: deterministic header có giá trị hay không.
- `raw_dense_minus_header`: tác động riêng của context lên dense embedding.
- `raw_sparse_minus_header`: tác động riêng của context lên BM25.
- `raw_context_minus_header`: raw OpenAI summary có thêm giá trị ngoài header hay không.
- `effective_minus_raw`: gold/effective tốt hơn hay kém raw OpenAI.
- `correct_minus_shuffled`: context đúng chunk có tốt hơn context sai cùng tài liệu hay không.

Chỉ promote context khi `correct_minus_shuffled` dương rõ ràng, multi-hop không giảm,
summary không còn hard reject và null/permission safety vẫn đạt gate.

## Thử ba độ dài

Chạy ba thư mục riêng để tránh ghi đè:

```powershell
.\evaluation\retrieval_metadata_testset\run_context_quality_ablation.ps1 `
  -ContextMaxWords 30 `
  -RunDir evaluation\retrieval_metadata_testset\runs\context-v4-short

.\evaluation\retrieval_metadata_testset\run_context_quality_ablation.ps1 `
  -ContextMaxWords 45 `
  -RunDir evaluation\retrieval_metadata_testset\runs\context-v4-medium

.\evaluation\retrieval_metadata_testset\run_context_quality_ablation.ps1 `
  -ContextMaxWords 65 `
  -RunDir evaluation\retrieval_metadata_testset\runs\context-v4-long
```

So sánh medium với short/long bằng cùng query set, embedding model và seed. Không dùng
chung context cache giữa các prompt profile: `max_context_words` đã nằm trong cache key,
nên runner sẽ tự tạo entry riêng cho từng cấu hình.
