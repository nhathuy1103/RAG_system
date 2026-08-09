# A/B test contextual_summary cho v6a_filter_only

## Mục tiêu

So sánh đúng một biến duy nhất trên cùng cấu hình `v6a_filter_only`:

| Nhánh | Embedding | Nguồn contextual_summary |
|---|---|---|
| BEFORE | OpenAI | `base` |
| AFTER | OpenAI | OpenAI `chunk-context-v3` |

`v6a_filter_only` vẫn kế thừa các trường từ v1 đến v5, bao gồm
`contextual_summary`. Cụm `filter_only` chỉ nói rằng metadata miền v6 như `year`,
`project_name` và `effective_status` chỉ được dùng làm structured filter.

## 1. Mở PowerShell tại thư mục dự án

```powershell
Set-ExecutionPolicy -Scope Process -ExecutionPolicy RemoteSigned
& ".\.venv\Scripts\Activate.ps1"
```

## 2. Kiểm tra cấu hình OpenAI

File `.env` cần có tối thiểu:

```dotenv
OPENAI_API_KEY=<your-key>
OPENAI_BASE_URL=https://api.openai.com/v1
OPENAI_EMBEDDING_MODEL=text-embedding-3-small
CONTEXTUAL_ENRICHMENT_MODEL=gpt-4o-mini
CONTEXTUAL_ENRICHMENT_MAX_CONTEXT_WORDS=45
```

Không in giá trị API key ra terminal hoặc đưa `.env` vào Git.

Để giảm nguy cơ rate limit trong lần chạy dài, đặt cho PowerShell hiện tại:

```powershell
$env:CONTEXTUAL_ENRICHMENT_MAX_RETRIES = "5"
$env:CONTEXTUAL_ENRICHMENT_RETRY_BACKOFF_MS = "2000"
$env:CONTEXTUAL_ENRICHMENT_MAX_OUTPUT_TOKENS = "400"
$env:OPENAI_TIMEOUT_SECONDS = "60"
```

## 3. Chạy A/B test

```powershell
.\evaluation\retrieval_metadata_testset\run_v6a_context_ab_test.ps1 `
  -EmbeddingProvider openai `
  -EmbeddingModel text-embedding-3-small `
  -ContextMaxWords 45 `
  -ContextMaxOutputTokens 400 `
  -Repeats 3 `
  -BootstrapSamples 5000
```

Runner sẽ tự động:

1. Xác minh frozen benchmark và tài liệu nguồn.
2. Chạy BEFORE với `CurrentContextSource=base`.
3. Chạy AFTER với `CurrentContextSource=openai`.
4. Yêu cầu hai nhánh có cùng resolved testset và embedding provider.
5. Dừng nếu AFTER còn bất kỳ chunk `fallback` nào.
6. Ghép hai kết quả theo query để tính paired delta và CI 95%.
7. Xuất bảng so sánh `contextual_summary` cho từng chunk.

Lần đầu có thể sinh context cho tối đa 277 chunk. Context và embedding được cache;
chạy lại cùng model, prompt và dữ liệu sẽ tái sử dụng kết quả đã thành công.

## 4. Kiểm tra tính hợp lệ

```powershell
$Run = "evaluation\retrieval_metadata_testset\runs\real-benchmark-v3-v6a-context-v3-ab-openai"
$After = Get-Content "$Run\after_openai_context_v3\run_manifest.json" -Raw |
  ConvertFrom-Json

$After | Select-Object `
  embedding_provider, `
  current_context_source, `
  context_enrichment_model, `
  context_enrichment_prompt_version, `
  context_enrichment_generated_count, `
  context_enrichment_fallback_count, `
  production_comparable |
  Format-List
```

Kết quả AFTER hợp lệ khi:

```text
embedding_provider: openai
current_context_source: openai
context_enrichment_prompt_version: chunk-context-v3
context_enrichment_generated_count: 277
context_enrichment_fallback_count: 0
production_comparable: true
```

## 5. Xem paired metrics

```powershell
Import-Csv "$Run\metrics_all_queries\retrieval_metric_comparison.csv" |
  Where-Object metric -In @(
    "recall_at_5",
    "mrr_at_10",
    "ndcg_at_10",
    "term_hit_rate_at_5",
    "null_rejection_at_10"
  ) |
  Format-Table comparison,metric,left_mean,right_mean,absolute_delta,ci95_low,ci95_high,win,tie,loss
```

Xem riêng các query có structured filter:

```powershell
Import-Csv "$Run\metrics_filter_capable\retrieval_metric_comparison.csv" |
  Format-Table comparison,metric,left_mean,right_mean,absolute_delta,ci95_low,ci95_high,win,tie,loss
```

Cách đọc:

- `right_mean` là AFTER dùng OpenAI context v3.
- `absolute_delta = right_mean - left_mean`; số dương có lợi cho AFTER.
- `ci95_low > 0` cho thấy cải thiện ổn định hơn trên tập query hiện tại.
- Khoảng tin cậy đi qua `0` nghĩa là chưa đủ bằng chứng kết luận hai bản khác nhau.
- Luôn xem thêm `retrieval_metric_by_slice.csv`, không chỉ điểm trung bình toàn bộ.

## 6. Xem contextual_summary trước và sau

```powershell
Import-Csv "$Run\context_summary_comparison.csv" |
  Where-Object changed -eq "True" |
  Select-Object -First 20 `
    document_title,section_title,before_contextual_summary,openai_raw_contextual_summary, `
    effective_contextual_summary,summary_overridden_by_gold,openai_status |
  Format-List
```

## 7. Khi gặp rate limit

Giữ nguyên `RunDir`, tăng backoff rồi chạy lại đúng lệnh ở bước 3:

```powershell
$env:CONTEXTUAL_ENRICHMENT_MAX_RETRIES = "7"
$env:CONTEXTUAL_ENRICHMENT_RETRY_BACKOFF_MS = "4000"
```

Runner sẽ xóa riêng cache entry có trạng thái `fallback` để thử lại và giữ nguyên các
context đã sinh thành công, tránh trả phí lại toàn bộ 277 chunk.
