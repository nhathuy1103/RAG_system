# Metadata lọc trước retrieval

## Hợp đồng đang dùng

Production hiện chỉ áp dụng scope bắt buộc: `owner_id`, `notebook_id` và
`document_ids`. Chưa có business metadata nào được phê duyệt làm exact-match
filter. Các field có trong schema chỉ biểu diễn khả năng kỹ thuật; chúng không
chứng minh rằng field tồn tại hoặc đủ tin cậy trong corpus.

`project_code` từng được thử trên subset benchmark có heading cấu trúc như
`P16 • Vinhomes Smart City`. Kết quả đó không được suy rộng sang tài liệu không
chứa mã Pxx. Audit live ngày 2026-08-06 ghi nhận 0/339 chunk có field này, nên
planner và allowlist production đang để trống.

## Phần nào được embedding

Các field identity/temporal/status mới (`project_id`, `project_code`, `year`,
`data_period`, `effective_status`) không được nối vào `embedding_text`.
Embedding vẫn dùng content cùng deterministic contextual header hiện có; header
đó vốn có `document_type`/`content_kind`. Metadata được lưu riêng trong
`retrieval_metadata` và dùng để giảm tập ứng viên trước dense/FTS.

## Triển khai

1. Chạy migration `15_structured_retrieval_filters.sql` trên bản sao/staging,
   kiểm tra kế hoạch bằng `EXPLAIN (ANALYZE, BUFFERS)`, rồi mới chạy production.
2. Giữ `RETRIEVAL_STRUCTURED_FILTERS_ENABLED=false` và allowlist trống. Migration
   chỉ tạo khả năng lưu/lọc; nó không tạo metadata nghiệp vụ đáng tin cậy.
3. Chỉ cấu hình resolver sau khi field canonical có nguồn authoritative,
   provenance, coverage, precision và kiểm thử non-regression trên corpus đại diện.
4. Backend pgvector không cần tạo lại embedding khi chỉ chuẩn hóa một giá trị đã
   tồn tại và có provenance. Không dùng migration để tạo field nghiệp vụ suy đoán.
5. Backend Qdrant phải re-ingest/upsert các chunk cũ một lần vì payload cũ không
   có `retrieval_metadata`; payload mới và payload indexes được tạo tự động.

## Kiểm tra sau triển khai

Telemetry `retrieval.metadata_plan` phải cho thấy business filter rỗng trong
trạng thái hiện tại. Chỉ thêm field vào allowlist sau khi inventory chứng minh
field có thật, nguồn tạo field rõ ràng, coverage và precision đạt gate, đồng thời
A/B không giảm Recall@5, MRR, null rejection hoặc permission safety.
