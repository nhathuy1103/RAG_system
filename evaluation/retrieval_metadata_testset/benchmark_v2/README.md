# Metadata Retrieval Benchmark v2

Đây là benchmark kiểm soát để stress-test metadata. Bộ 39 query dùng ba tài liệu tải lên vẫn là pilot dữ liệu thật; không trộn hai bộ khi báo cáo kết quả.

## Quy mô

- 300 query, 30 query cho mỗi primary slice.
- 30 scenario độc lập, chia `dev=60` và `test=240` theo scenario để tránh chỉnh theo test.
- 270 chunk có cặp bản cũ/mới, báo cáo cũ/mới, bảng hoặc biểu đồ, và tài liệu hạn chế quyền.
- Ground truth dùng exact chunk ID; multi-hop dùng các evidence group bắt buộc.

## Các slice

1. `content_only`
2. `explicit_filter`
3. `implicit_filter`
4. `cross_document_confusion`
5. `version_conflict`
6. `section_localization`
7. `table_visual`
8. `multi_hop`
9. `null_insufficient`
10. `permission_sensitive`

## Chạy PowerShell

Smoke test miễn phí:

```powershell
.\evaluation\retrieval_metadata_testset\run_metadata_benchmark.ps1 `
  -EmbeddingProvider hashing `
  -Repeats 1 `
  -BootstrapSamples 1000
```

Lấy số liệu dense embedding thực:

```powershell
.\evaluation\retrieval_metadata_testset\run_metadata_benchmark.ps1 `
  -EmbeddingProvider openai `
  -Repeats 3 `
  -BootstrapSamples 5000
```

Script tự chạy A/B/C/D và `v0` đến `v6`. Embedding OpenAI được cache tại `.cache/embedding_cache.json`.

## Đọc kết quả

- `retrieval_metric_summary.csv`: tổng quan theo mode.
- `retrieval_metric_by_slice.csv`: chất lượng và latency của từng slice.
- `retrieval_metric_by_metadata_field.csv`: tác động theo field được yêu cầu.
- `retrieval_metric_comparison.csv`: delta ghép cặp, CI 95%, permutation p-value.
- `retrieval_metric_details.csv`: lỗi từng query.
- `metadata_audit.csv`: coverage field và độ dài `embedding_text`/`search_text`.

Metric chính:

- Query có đáp án: `recall_at_5`, `mrr_at_10`.
- Multi-hop: `multi_hop_all_groups_at_10` và `multi_hop_group_coverage_at_10`.
- Null: `null_rejection_at_10`; chỉ pass khi retrieval trả rỗng sau filter.
- Permission: `permission_leak_at_10` phải bằng 0.
- Hỗn hợp mọi loại: `success_at_5`.

Metadata filter trong benchmark được cung cấp dưới dạng ground-truth condition và chỉ áp dụng nếu mode đang thử có field đó. Vì vậy benchmark cô lập chất lượng metadata/index; nó không chấm khả năng LLM phân tích filter từ câu tự nhiên.

`table_visual` chấm retrieval sau khi bảng/caption đã được trích xuất thành text. Nó không thay thế benchmark OCR hoặc vision extraction.
