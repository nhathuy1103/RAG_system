# Retrieval Metadata Test Set

Bộ test này dùng để kiểm tra metadata có thật sự cải thiện retrieval trên 3 tài liệu:

- `Vinhomes_TayMo.pdf`
- `Vinhomes_HaiVan.pdf`
- `demo_kb_chinh_sach_doi_tra_cskh - Copy.docx`

Mục tiêu không phải hỏi LLM trả lời hay, mà là đo retrieval có kéo đúng chunk/tài liệu/điều khoản không.

## Chạy Trọn Bộ Bằng PowerShell

Không cần bật BE/FE và không ghi vào Supabase. Lượt miễn phí dùng hashing để kiểm tra
toàn bộ pipeline A/B/C/D, 7 ablation, ground truth, latency và báo cáo:

```powershell
Set-ExecutionPolicy -Scope Process -ExecutionPolicy RemoteSigned
.\evaluation\retrieval_metadata_testset\run_complete_evaluation.ps1
```

Ba tài liệu mặc định được đọc từ `$env:USERPROFILE\Downloads`. Kết quả nằm tại:

```text
evaluation\retrieval_metadata_testset\runs\latest\experiment_report.md
```

Lượt dùng dense embedding giống production hơn:

```powershell
.\evaluation\retrieval_metadata_testset\run_complete_evaluation.ps1 `
  -EmbeddingProvider openai `
  -ContextualizeCurrent
```

Lượt này có phát sinh phí contextual enrichment và embedding. Lượt đầu tạo context và
embedding cho các projection; các lượt sau tái sử dụng `context_enrichment_cache.json`
và `embedding_cache.json` trong `evaluation\retrieval_metadata_testset\.cache`. API key
được đọc từ `.env`, không được ghi vào artifact hoặc cache.

Các output quan trọng:

- `frozen_snapshot.json`: checksum tài liệu, testset, gold metadata và cấu hình.
- `ground_truth_audit.csv`: ánh xạ 39 query vào chunk thật; phải có `unresolved=0`.
- `metadata_audit.csv`: coverage từng field và độ dài projection theo mode.
- `retrieval_results.jsonl`: top 10 cùng ba mẫu latency cho từng query/mode.
- `metrics/`: Recall, MRR, nDCG, phân tích query type, CI và permutation test.
- `experiment_report.md`: quality gates và kết luận cuối.

`hashing` và metadata cấu trúc cơ bản chỉ là proxy miễn phí để kiểm tra logic. Chỉ dùng
kết quả có cả `-EmbeddingProvider openai` và `-ContextualizeCurrent` để ra quyết định;
PostgreSQL FTS production vẫn có thể lệch nhẹ so với BM25 chạy offline.

Nếu muốn chạy đúng thí nghiệm `A - No Metadata`, `B - Current Metadata`,
`C - Shuffled Metadata`, `D - Gold Metadata`, xem:

```powershell
notepad evaluation\retrieval_metadata_testset\ABCD_EXPERIMENT.md
```

## Sinh Lại Bộ Test

```powershell
python evaluation\retrieval_metadata_testset\build_testset.py
```

Output:

- `testset.jsonl`: bộ câu hỏi chuẩn cho máy chạy.
- `evaluation_queries.csv`: format query set theo kiểu thí nghiệm metadata.
- `test_queries.csv`: bản dễ đọc/copy vào UI.
- `manifest.json`: số lượng test, nguồn, ngưỡng pass.
- `ablation_matrix.json`: các phiên bản metadata nên so sánh.

## Format Kết Quả Retrieval Cần Chấm

Tạo một file JSONL, ví dụ `retrieval_results.jsonl`, mỗi dòng ứng với một test:

```json
{"test_id":"cs_004_return_deadline","mode":"v5_context_terms","latency_ms":320,"results":[{"rank":1,"document_title":"demo_kb_chinh_sach_doi_tra_cskh - Copy.docx","page_number":null,"section_title":"Chính sách áp dụng","excerpt":"Thời hạn đổi trả | Khách hàng được yêu cầu đổi hoặc trả hàng tối đa 30 ngày kể từ ngày nhận hàng."}]}
```

Nếu bạn dùng endpoint `/chat`, có thể lấy `citations` của response đưa thẳng vào `results`.

## Chạy Qua API Chat Hiện Tại

Nếu muốn chạy nhanh qua BE hiện tại:

```powershell
$env:RAG_API_URL="http://127.0.0.1:8000"
$env:RAG_BEARER_TOKEN="<supabase_user_access_token>"
$env:RAG_NOTEBOOK_ID="<notebook_uuid>"

python evaluation\retrieval_metadata_testset\run_chat_testset.py `
  --output evaluation\retrieval_metadata_testset\retrieval_results.jsonl
```

Nếu muốn giới hạn đúng 3 document đang test:

```powershell
$env:RAG_DOCUMENT_IDS="<doc_id_1>,<doc_id_2>,<doc_id_3>"
```

Lưu ý: cách này đo end-to-end `/chat`, nên latency và chi phí có cả phần LLM sinh câu trả lời. Để đo tốc độ retrieval thuần, hãy export trực tiếp top-k candidates từ retrieval layer theo format JSONL ở trên.

## Chấm Điểm

```powershell
python evaluation\retrieval_metadata_testset\score_retrieval_results.py `
  --results evaluation\retrieval_metadata_testset\retrieval_results.jsonl `
  --output-dir evaluation\retrieval_metadata_testset\results
```

Metric chính:

- `recall@5`: expected evidence có nằm trong top 5 không.
- `mrr@10`: evidence đúng đứng càng cao càng tốt.
- `terms@10`: các expected terms có xuất hiện trong top results không.
- `bad_doc@1`: top 1 có bị kéo nhầm sang tài liệu cấm không.
- `mojibake@1`: top 1 có dấu hiệu lỗi encoding như `CÃ`, `Ä`, `áº` không.
- `p95_ms`: latency p95 nếu bạn log `latency_ms`.

Với kết quả có nhiều mode A/B/C/D, chạy thêm:

```powershell
python evaluation\retrieval_metadata_testset\score_experiment_comparison.py `
  --results evaluation\retrieval_metadata_testset\retrieval_results.jsonl `
  --output-dir evaluation\retrieval_metadata_testset\results\abcd
```

Script này xuất `retrieval_metric_summary.csv`, `retrieval_metric_by_query_type.csv`,
`retrieval_metric_comparison.csv`, và tự tính các delta mặc định:

- `current_metadata - no_metadata`
- `gold_metadata - current_metadata`
- `current_metadata - shuffled_metadata`

Ngưỡng pass gợi ý:

- `recall@5 >= 0.85`
- `mrr@10 >= 0.65`
- `terms@5 >= 0.90`
- `bad_doc@1 <= 0.10`
- `mojibake@1 = 0`
- `p95_ms < 1000` nếu chỉ đo retrieval, chưa gọi LLM sinh answer.

## Cách Test Metadata

Chạy lần lượt các biến thể trong `ablation_matrix.json`:

1. `v0_raw_text`: chỉ chunk text.
2. `v1_document_identity`: thêm title + document_type.
3. `v2_section_structure`: thêm section_title + section_path.
4. `v3_block_aware`: thêm content_kind + table_header.
5. `v4_context_summary`: thêm contextual_summary.
6. `v5_context_terms`: thêm contextual_search_terms vào search_text.
7. `v6_domain_metadata`: thêm metadata chuyên ngành như clause_type, fee_type, deadline_type, policy_field.

Nếu version nào tăng recall nhưng làm latency tăng nhiều, ưu tiên giữ metadata ở `search_text` thay vì nhồi hết vào `embedding_text`.

## Diễn Giải Kết Quả

- Nếu sai nhiều ở `cs_*`: thiếu `table_header`, `content_kind`, hoặc search_text chưa giữ nguyên cặp key-value trong bảng.
- Nếu sai giữa `tm_*` và `hv_*`: thiếu `document_type`, `title`, `section_path`, hoặc contextual_summary chưa phân biệt `Diện Tích Thương Mại` với `Nhà Ở`.
- Nếu sai ở các câu `30 ngày`, `05 ngày`, `10%/năm`: cần thêm `deadline_type`, `rate_type`, `clause_type`, và giữ numeric phrase trong `search_text`.
- Nếu `mojibake@1 > 0`: phải fix encoding trước khi embedding lại.

## Benchmark v2 (300 Query)

Bộ 39 query từ ba tài liệu tải lên là pilot dữ liệu thật. Để kiểm tra đủ version,
null, quyền truy cập và multi-hop, dùng thêm benchmark kiểm soát 300 query:

```powershell
.\evaluation\retrieval_metadata_testset\run_metadata_benchmark.ps1 `
  -EmbeddingProvider hashing `
  -Repeats 1
```

Khi smoke test đạt, đổi `hashing` thành `openai` và `Repeats 3`. Hướng dẫn cùng
định nghĩa metric nằm tại `benchmark_v2\README.md`.

## Benchmark tài liệu thật v3 frozen gold

Sáu DOCX giá, tiện ích và kế hoạch mới được dùng để tạo 300 query evidence-anchored;
ba tài liệu pilot cũ vẫn nằm trong corpus làm distractor. Chạy bản miễn phí trước:

```powershell
.\evaluation\retrieval_metadata_testset\run_real_metadata_benchmark.ps1 `
  -EmbeddingProvider hashing `
  -CurrentContextSource base `
  -Repeats 1
```

Kết quả nằm trong `runs\real-benchmark-v3-latest`. Bộ 300 case đã được duyệt và đóng
băng bằng `real_benchmark_v3\approval.json`; mọi thay đổi testset sẽ yêu cầu duyệt lại.
Chạy số liệu production-like với `-EmbeddingProvider openai -Repeats 3`. Chi tiết nằm tại
`real_benchmark_v3\README.md`. Báo cáo v3 có thêm macro score theo `scenario_id` và
`evidence_fact_id`, paired ACL, fail-closed preflight và table cell provenance.
