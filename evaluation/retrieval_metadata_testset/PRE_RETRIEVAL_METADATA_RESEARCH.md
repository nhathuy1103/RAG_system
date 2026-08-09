# Nghiên cứu metadata lọc trước retrieval

> **Cập nhật vòng 2:** nghiên cứu 12 field/581 diagnostic query đã hoàn tất tại
> `runs/extended-metadata-field-study-openai/EXTENDED_METADATA_FIELD_STUDY_REPORT.md`.
> Kết luận vòng 2 thay thế thứ tự P1 cũ: ưu tiên `project_code`, `year` + `data_period`,
> một `effective_status`, và pilot `content_kind`; chưa promote `source`. `project_name` là
> alias/display, `domain` được suy ra từ `document_type` trong corpus hiện tại.

## Kết luận hiện tại

Repo đã chứng minh hai quyết định khác nhau:

1. `owner_id`, `notebook_id`, `document_ids` là scope filter đang chạy trong production.
2. Frozen benchmark cho thấy năm field nghiệp vụ có nhu cầu lọc: `document_type`,
   `project_name`, `year`, `lifecycle_status`, `source`.

Chưa thể đưa cả năm field nghiệp vụ vào production ngay. Corpus của run
`real-benchmark-v3-context-quality-v4-openai` cho thấy chỉ `document_type` có trong
current metadata. Bốn field còn lại chỉ có trong gold annotation.

Leave-one-field-out ablation bằng OpenAI embedding đã hoàn tất tại
`runs/real-benchmark-v3-filter-field-ablation-openai/FILTER_FIELD_ABLATION_REPORT.md`.
Kết quả xác nhận `project_name` tạo giá trị ranking mạnh, `year` quyết định null rejection,
và bỏ toàn bộ domain filter làm Recall@5, MRR, NDCG cùng safety giảm rõ rệt.

## Bằng chứng từ 300 query

110/300 query có ít nhất một `retrieval_filters.metadata_conditions`. Tổng cộng có 310
điều kiện, tất cả dùng toán tử `eq`.

| Field | Số điều kiện | Current metadata | Gold metadata | Nhận định |
|---|---:|---:|---:|---|
| `document_type` | 90 | 277/277 chunk | 277/277 chunk | Sẵn sàng pilot |
| `project_name` | 80 | 0/277 chunk | 25/277 chunk | Cần extractor và canonical identity |
| `year` | 70 | 0/277 chunk | 125/277 chunk | Cần extractor kiểu integer |
| `lifecycle_status` | 40 | 0/277 chunk | 125/277 chunk | Cần derivation theo version, không nên tin LLM tự do |
| `source` | 30 | 0/277 chunk | 125/277 chunk | Bằng chứng còn hẹp, query chỉ dùng một source value |

Các tổ hợp condition thực tế:

| Tổ hợp | Query |
|---|---:|
| `document_type + project_name + year` | 30 |
| `document_type + lifecycle_status` | 30 |
| `document_type + project_name + source + year` | 30 |
| `lifecycle_status + project_name` | 10 |
| `project_name + year` | 10 |

## Bộ field đề xuất

### P0 - Bắt buộc và đã có

- `owner_id`: tenant/security boundary bắt buộc.
- `notebook_id`: giới hạn notebook.
- `document_ids`: allowlist tài liệu đã qua quyền truy cập/quality policy.

Ba field này phải fail-closed. Chúng không được dùng làm nội dung embedding hoặc ranking.

### P1 - Pilot đầu tiên

- `document_type`: field nghiệp vụ duy nhất current metadata đã phủ 277/277 và khớp gold về
  phân bố năm loại tài liệu.
- `project_code`: identity canonical ưu tiên cho filter.
- `project_name`: nhãn hiển thị; query planner phải resolve alias về `project_code`.
- `year`: integer đại diện năm báo cáo/dữ liệu, không lấy bừa mọi năm xuất hiện trong text.
- `data_period`, `as_of_date`: giữ ngữ nghĩa thời gian đầy đủ để tránh dùng `year` sai mục đích.
- `document_version`, `effective_status`, `lifecycle_status`: nhóm version/lifecycle. Giá trị
  `latest` phải được tính lại khi có version mới.
- `source_code`: identity canonical của nguồn.
- `source`: nhãn nguồn hiển thị.

Không nên chỉ lưu `project_name` hoặc `source` dạng chuỗi tự do. Frozen test có 34 cách gọi dự
án trong condition, gồm cả tên có/không có tiền tố `Vinhomes`; equality trực tiếp trên tên dễ
fail sai.

### P2 - Chỉ thêm khi có query và benchmark tương ứng

- `project_status`, `region`, `market_type`, `reliability_grade`.
- `clause_type`, `policy_field`, `fee_type`, `deadline_type`.
- `organization`, `department`, `faculty`, `location`, `currency`, `unit`, `table_units`.

Repo có schema/gold cho một phần các field này, nhưng frozen test hiện không dùng chúng trong
`metadata_conditions`. Vì vậy chưa có bằng chứng retrieval để tạo index production ngay.

## Field không dùng làm pre-filter nghiệp vụ

- `title`, `section_title`, `section_path`, `content_kind`, `table_header`: dùng cho ranking,
  định vị hoặc table routing; không phải business scope mặc định.
- `contextual_summary`, `contextual_search_terms`, `keyword_aliases`: tín hiệu search tùy chọn,
  không phải dữ liệu authoritative để fail-closed.
- `page_number`, `chunk_index`, `source_block_ids`, `bbox`, table cell provenance: citation và audit.
- checksum, parser/chunking version, cache key: vận hành và tái lập.

## Khoảng trống implementation

- `RetrievalFilters` production hiện chỉ có `owner_id`, `notebook_id`, `document_ids`.
- PostgreSQL RPC `match_document_chunks` và `search_document_chunks_keyword` chỉ nhận ba scope
  filter trên.
- Qdrant payload index chưa có domain filter indexes; payload chủ yếu chứa owner, tenant,
  document, version và operational fields.
- Current extraction chưa populate bốn field P1 quan trọng ngoài `document_type`.

## Thứ tự nghiên cứu và gate promote

1. Xây typed schema, canonical dictionary và extractor deterministic cho P1.
2. Audit current-vs-gold theo field trên 277 chunk; không dùng retrieval score để che lỗi extraction.
3. Chỉ pilot field có precision >= 0,98 và coverage >= 0,95 trên tập chunk nơi field áp dụng.
4. Chạy leave-one-field-out ablation trên 110 filter-capable query.
5. Chấm Recall@5/MRR cho 80 answerable, null rejection cho 30 null và filter preflight 1,0.
6. Resample theo `scenario_id`/`evidence_fact_id`, không chỉ bootstrap từng query.
7. Sau khi đạt gate mới mở rộng `RetrievalFilters`, PostgreSQL RPC và Qdrant payload indexes.

Trong thời gian extractor chưa đạt gate, missing/unsupported field phải fail-closed với query bắt
buộc filter; không được âm thầm bỏ condition rồi search toàn corpus.
