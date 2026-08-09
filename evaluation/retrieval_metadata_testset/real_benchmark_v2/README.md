# Real Metadata Retrieval Benchmark v2

Bộ này đánh giá metadata retrieval trên 9 tài liệu thật trong `Downloads`:

- 6 DOCX mới là nguồn tạo câu hỏi: 4 hồ sơ giá 2023–2026, tiện ích toàn quốc và kế hoạch triển khai.
- 3 tài liệu pilot cũ vẫn nằm trong corpus để làm distractor: 2 PDF hợp đồng và 1 DOCX chính sách đổi trả.

## Thành phần

- `testset.jsonl`: 300 query có exact chunk ID và evidence group.
- `queries_for_review.csv`: sheet duyệt thủ công trước khi đổi trạng thái thành final gold.
- `gold_metadata.json`: metadata gold và rule gắn theo heading/table.
- `ground_truth_audit.csv`: kiểm tra ID, evidence group và term coverage.
- `slice_distribution.csv`: đúng 30 query cho mỗi primary slice.
- `ablation_matrix.json`: trường được bật dần từ `v0` đến `v6`.
- `manifest.json`: hash nguồn, số chunk, phân bố và giới hạn benchmark.

## Chạy miễn phí trước

Tại thư mục gốc repo:

```powershell
.\evaluation\retrieval_metadata_testset\run_real_metadata_benchmark.ps1 `
  -EmbeddingProvider hashing `
  -CurrentContextSource base `
  -Repeats 1
```

`hashing` không gọi OpenAI. Nó chỉ kiểm tra parser, chunk ID, filter, scoring và toàn bộ pipeline chạy đúng.

## Chạy production-like

Sau khi smoke test đạt và đã duyệt `queries_for_review.csv`:

```powershell
.\evaluation\retrieval_metadata_testset\run_real_metadata_benchmark.ps1 `
  -EmbeddingProvider openai `
  -CurrentContextSource base `
  -Repeats 3
```

Chỉ bật `-CurrentContextSource openai` khi cần đo context do LLM sinh. Tùy chọn đó gọi model cho từng chunk chưa có cache, nên tốn thêm chi phí và dễ gặp rate limit hơn embedding đơn thuần.

## Cách đọc kết quả

Đọc theo thứ tự:

1. `ground_truth_audit.csv`: phải có `unresolved=0`.
2. `retrieval_metric_by_slice.csv`: tìm slice giảm mạnh.
3. `retrieval_metric_comparison.csv`: xem `B-A`, `D-B`, `B-C` và `v1-v0` đến `v6-v5`.
4. `retrieval_metric_by_metadata_field.csv`: khoanh vùng field liên quan; đây là chẩn đoán, không tự nó chứng minh quan hệ nhân quả.
5. `metadata_audit.csv`: so token tăng thêm với recall và latency.

Ngưỡng khởi đầu:

- Answerable `Recall@5 >= 0.85`.
- Multi-hop all evidence groups `@10 >= 0.80`.
- Null rejection `@10 >= 0.95`.
- Permission leak `@10 = 0`.
- `B-C > 0`: metadata đúng phải tốt hơn metadata tráo.
- `D-B > 0`: cho biết còn khoảng trống giữa metadata hiện tại và gold.

## Phạm vi đúng

- `table_visual` chỉ đánh giá bảng DOCX đã extract thành text. Sáu file mới không chứa ảnh, nên bộ này không đo OCR, caption hình hay vision retrieval.
- Permission dùng evidence thật nhưng mô phỏng người dùng không có `document_ids`; không khẳng định ACL gốc của file.
- DOCX parser không giữ pagination Word, nên ground truth dựa trên exact chunk ID và heading.
- Bảng giá được giữ atomic bởi `structure_recursive`. Các câu version vẫn phụ thuộc vào bốn chunk bảng theo năm; xem `chunk_dependency` trong manifest và không diễn giải CI như 30 tài liệu độc lập.
- Nhãn hiện là `evidence_anchored_pending_human_review`. Chỉ coi là final gold sau khi duyệt CSV.
