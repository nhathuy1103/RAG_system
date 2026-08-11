# Chính sách metadata tài liệu và LLM enrichment

## Nguồn chuẩn

- `knowledge_documents` là nguồn chuẩn cho metadata nghiệp vụ xuyên phiên bản.
- `document_versions` là nguồn chuẩn cho hiệu lực, source và ingestion profile.
- `knowledge_parent_chunks` và `knowledge_chunks` lưu cấu trúc/citation.
- `chunk_retrieval_projections` chỉ là read model có thể dựng lại; không được dùng
  làm nguồn chuẩn cho ACL, lifecycle hoặc cập nhật ngược document.

## Thứ tự trích xuất

1. Giữ giá trị do người dùng hoặc system record cung cấp.
2. Giữ giá trị parser/rule trích xuất được khi có provenance rõ ràng.
3. Chỉ gọi LLM cho trường còn thiếu.
4. Nếu tài liệu không có bằng chứng rõ ràng, để trống; không đoán.

Prompt tiếng Việt `configs/prompts/document_metadata_llm_vi.txt`, version
`document-metadata-vi-v2`, chỉ cho phép các trường: `document_number`,
`document_type`, `category`, `domain`, `project_code`, `project_name`,
`department_code`, `effective_from`, `effective_to`, `year`, `data_period`.
`content_kind` và các trường section/page do parser hoặc chunker xác định, không
giao cho LLM. Mỗi kết quả phải có quote
liên tục khớp chính xác với `block_id` và page đã gửi. Application kiểm tra lại
quote, chuẩn hóa kiểu dữ liệu, giới hạn confidence LLM tối đa `0.89`, lưu model,
prompt version và input checksum.

## Review và hard filter

Mọi output LLM được lưu dưới dạng `llm_inferred + UNVERIFIED`. Candidate có thể
được đưa vào context/ranking metadata khi field xác định chưa có giá trị, nhưng
không được ghi đè parser/system/user data và không được tự động trở thành hard
filter. Nó không được copy vào canonical columns hoặc tạo security scope.
Reviewer có `REVIEW_DOCUMENT` cùng quyền `REVIEW`/`MANAGE` trên document phải
gọi `review_document_metadata_assertion`. Quyết định VERIFIED mới cập nhật
Document/Version canonical, tăng revision, refresh lexical projection và ghi
audit. Quyết định REJECTED bắt buộc có lý do.

Security/lifecycle (`ASK_KNOWLEDGE`, document `READ`, `PUBLISHED`, `ACTIVE`,
current version, chưa xóa) luôn được kiểm tra trong database trước sparse/dense.
Business filters chỉ đọc các canonical columns đã qua quy trình trên.
`effective_status` được suy ra ở query time từ `effective_from/effective_to`;
metadata legacy có thêm `effective_status_as_of` để không che giấu thời điểm
đã dùng khi tạo projection.
