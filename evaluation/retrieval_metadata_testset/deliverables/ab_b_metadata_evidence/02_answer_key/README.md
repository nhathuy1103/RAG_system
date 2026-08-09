# Cách hiểu answer key

- `answer_key.jsonl`: nguồn gold chính để scorer đọc.
- `answer_key_review.csv`: bản phẳng cho người review.
- `ground_truth_audit.csv`: kết quả resolver kiểm tra gold với corpus của run.
- `gold_metadata_oracle.json`: metadata oracle phục vụ ablation; không phải đáp án câu hỏi.

Benchmark chấm evidence/chunk/citation/term thay vì ép mô hình sinh đúng một câu văn mẫu.
