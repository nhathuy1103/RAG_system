# Real Metadata Retrieval Benchmark v3 Frozen Gold

Bộ này có 300 query trên 9 tài liệu thật, gồm 30 case cho mỗi slice. Toàn bộ case đã
được benchmark owner duyệt ngày 2026-08-04 và mang nhãn `approved_frozen_gold`.
Fingerprint được lưu trong `approval.json`; build sẽ dừng nếu nội dung hoặc chunk ID đổi.

## Những Điểm Đã Sửa

- Numeric gold giữ đủ dấu phân cách hàng nghìn và đơn vị, ví dụ `5.000 m²`.
  Đối chiếu từng fact nằm trong `numeric_fact_integrity_audit.csv`.
- ACL gồm 15 cặp cùng câu hỏi: user được phép phải retrieve/cite, user bị chặn phải
  không retrieve, không trích dẫn và không lộ term nhạy cảm.
- Null filter dùng `fail_closed`; scorer không thưởng null rejection nếu preflight fail.
- Multi-hop dùng `must_cite_document_titles` dạng danh sách.
- `table_structured` có `table_id`, row, column, cell, page logic và source block IDs.
- Version/conflict tách latest resolution, temporal qualification và scope difference.
- Query có sáu style; báo cáo có micro score và macro score theo scenario/evidence fact.

## Chạy Smoke Test Miễn Phí

Từ thư mục gốc repo:

```powershell
.\evaluation\retrieval_metadata_testset\run_real_metadata_benchmark.ps1 `
  -EmbeddingProvider hashing `
  -CurrentContextSource base `
  -Repeats 1
```

Kết quả mặc định nằm tại `runs\real-benchmark-v3-latest`. Đọc lần lượt:

1. `ground_truth_audit.csv`: phải không có unresolved case.
2. `metrics\retrieval_metric_summary.csv`: micro score toàn bộ query.
3. `metrics\retrieval_metric_by_slice.csv`: score theo capability.
4. `metrics\retrieval_metric_macro_summary.csv`: macro theo scenario và evidence fact.
5. `metrics\retrieval_metric_comparison.csv`: delta A/B/C/D và ablation.
6. `metadata_audit.csv`: token/latency cost của từng metadata projection.

Chạy production-like bằng `-EmbeddingProvider openai -Repeats 3`. Chỉ dùng
`-CurrentContextSource openai` khi
muốn đo riêng context LLM vì tùy chọn đó phát sinh thêm request và chi phí.

## Giới Hạn

- DOCX nguồn không có ảnh, scan hoặc biểu đồ; `table_structured` không đo OCR/vision.
- Các bảng được chunk atomic nên nhiều row-level fact cùng trỏ tới một chunk. Vì vậy
  phải đọc macro score, không chỉ micro score.
- Scope-difference cần answer evaluator để chấm việc cảnh báo/diễn giải xung đột.
- ACL ở đây kiểm tra isolated harness, không thay thế kiểm thử ACL production.
- Mọi thay đổi nguồn, parser, chunking hoặc testset đều làm fingerprint khác và yêu cầu
  một vòng human review mới.
