# Báo cáo nghiên cứu context và metadata trước retrieval

**Phiên bản đối soát:** 06/08/2026  
**Phạm vi:** mã nguồn, benchmark frozen v3, context-quality v4, metadata live và cấu hình runtime hiện tại trong repo  
**Nguyên tắc:** chỉ kết luận trong phạm vi có artifact; không xem metadata gold là metadata production

## 1. Tóm tắt điều hành

Nghiên cứu này trả lời hai câu hỏi độc lập:

1. Nên tạo văn bản nào từ chunk và metadata cấu trúc để đưa vào dense embedding và sparse index?
2. Metadata nào đủ tin cậy để loại bớt candidate trước retrieval?

Kết quả chốt:

- **Text projection được chọn là B: chunk + deterministic header.** Trên benchmark frozen, Recall@5 tăng từ **64,71% lên 96,47%**, tương đương **+31,76 điểm phần trăm**, CI95% **[+25,49; +38,04]**, permutation `p=0,0002`.
- **Không bật `contextual_summary` trong production mặc định.** Khi summary OpenAI được thêm vào cả dense và sparse, Recall@5 giảm từ **96,47% xuống 95,29%**. C-sparse có tín hiệu dương nhỏ lên **97,25%**, nhưng chỉ thắng 2/255 query, CI chạm 0 và `p=0,4981`, nên chưa đủ bằng chứng rollout.
- **Chưa có business metadata nào được duyệt làm hard filter production.** Audit live trên đúng đường dẫn `document_chunks.metadata.retrieval_metadata` có 8 tài liệu, 187 chunk active/current. Các field có coverage tốt là `title` 100%, `section_title`, `section_path`, `content_kind` cùng 96,26%. Các field `project_code`, `project_name`, `domain`, `clause_type`, `region`, `data_period`, `effective_status`, `lifecycle_status`, `source` đều 0/187.
- **Metadata thật được áp dụng trước retrieval hiện tại là security/document scope:** `owner_id`, `notebook_id`, `document_ids`. Structured business filter đang tắt. Resolver theo `documents.original_filename` chỉ chạy `shadow`, có ghi telemetry nhưng không loại evidence.
- **A/B live cho document identity metadata là kết quả âm:** candidate trung bình giảm 65,63%, nhưng Recall@5 giảm 5,26 điểm và median latency tăng 18,20 ms. Vì vậy không promote sang mode `on`.

Kết luận cần trình bày chính xác:

> Đồ án chứng minh được deterministic structural context cải thiện retrieval. Đồ án chưa chứng minh được business metadata hiện có giúp hard-filter production. Kết quả âm này dẫn đến một quyết định an toàn: giữ scope bắt buộc, chạy resolver ở shadow và không dùng field thiếu coverage để loại candidate.

## 2. Ý tưởng nghiên cứu

### 2.1. Vấn đề sau khi chunking

Một chunk có thể đúng về nội dung nhưng mất ngữ cảnh khi tách khỏi tài liệu. Ví dụ:

- một dòng bảng chỉ chứa giá trị mà không có tên tài liệu, tên section hoặc header cột;
- một đoạn hợp đồng dùng đại từ hoặc khái niệm đã định nghĩa ở phần trước;
- nhiều tài liệu chứa các câu gần giống nhau nhưng thuộc dự án, năm hoặc section khác nhau.

Nếu chỉ embed `chunk.text`, vector có thể không mang đủ tín hiệu định vị. Có hai hướng bổ sung:

1. **Deterministic context:** lấy trực tiếp từ parser/chunker như title, section, loại content, table header.
2. **Generated context:** dùng LLM đọc ngữ cảnh rộng hơn và sinh một câu `contextual_summary` cho chunk.

### 2.2. Vấn đề metadata filter

Metadata có thể giảm không gian tìm kiếm trước khi ranking, nhưng exact-match filter là fail-closed. Khi query yêu cầu `year=2025`, chunk thiếu `year` sẽ bị loại dù nội dung đúng. Do đó một field chỉ được dùng làm hard filter khi đồng thời đạt:

- có nguồn authoritative hoặc phép suy ra deterministic rõ ràng;
- coverage đủ cao trên corpus thực;
- giá trị được chuẩn hóa và có precision cao;
- giữ lại 100% evidence liên quan trên tập đánh giá;
- không làm giảm Recall/MRR;
- mang lại lợi ích candidate hoặc latency thực tế.

Đây là lý do nghiên cứu tách text projection khỏi metadata pre-filter. Nếu trộn hai thay đổi trong cùng một mode, không thể biết mức tăng đến từ embedding text hay từ filter.

## 3. Ba lớp dữ liệu phải phân biệt

### 3.1. Text được lập chỉ mục

Đây là chuỗi thực sự được đưa vào hai kênh retrieval:

- `embedding_text`: gửi tới embedding model, sau đó lưu vector.
- `search_text`: dùng cho sparse/full-text search.

Mã nguồn: `app/shared/contextual_text.py`, hàm `build_embedding_text` và `build_search_text`.

### 3.2. Metadata payload cạnh chunk/vector

Đây là JSON dùng cho hiển thị, citation, provenance, audit hoặc làm nguồn cho filter nếu sau này được duyệt. Có field trong payload không có nghĩa field đó đang ảnh hưởng retrieval.

Đường dẫn live được audit:

```text
document_chunks.metadata.retrieval_metadata
```

### 3.3. Metadata được áp dụng trước retrieval

Đây là điều kiện thực sự truyền xuống dense và sparse adapter. Runtime model nằm tại `app/retrieval/domain/models.py`:

```text
RetrievalFilters
├── owner_id
├── notebook_id
├── document_ids
└── metadata: StructuredMetadataFilters
```

`StructuredMetadataFilters` có khả năng biểu diễn `document_type`, `content_kind`, `project_id`, `project_code`, `year`, `data_period`, `effective_status`. Tuy nhiên khả năng của schema không đồng nghĩa các field đang được bật.

## 4. Trạng thái runtime hiện tại

Đọc trực tiếp settings hiện tại cho kết quả:

```text
vector_store_backend = pgvector
contextual_enrichment_enabled = false
document_scope_planner_mode = shadow
structured_filters_enabled = false
structured_filter_fields = []
knowledge_quality_mode = on
```

Nguồn cấu hình: `.env`, `app/bootstrap/settings.py`, `app/pipeline/bootstrap/settings.py`.

Cần đọc các giá trị trên theo **cấu hình hiệu lực**, không chỉ tìm một dòng trong `.env`:

- `.env` ghi trực tiếp `VECTOR_STORE_BACKEND=pgvector`, `RETRIEVAL_DOCUMENT_SCOPE_PLANNER_MODE=shadow`, `RETRIEVAL_STRUCTURED_FILTERS_ENABLED=false` và để `RETRIEVAL_STRUCTURED_FILTER_FIELDS` rỗng;
- `.env` không khai báo `CONTEXTUAL_ENRICHMENT_ENABLED`, vì vậy loader của ingestion dùng default `false` tại `app/pipeline/bootstrap/settings.py`;
- `.env` không khai báo `KNOWLEDGE_QUALITY_MODE`, vì vậy application settings dùng default `on` tại `app/bootstrap/settings.py`;
- các tham số model, context window và retry vẫn có trong `.env` nhưng không làm generator chạy khi cờ enable đang `false`.

Do đó phát biểu “context enrichment đang tắt” là kết quả của phép hợp nhất `.env + default trong code`, không phải suy luận từ việc model có hay không có trong `.env`.

### 4.1. Metadata thực sự lọc trước retrieval

| Field | Vai trò hiện tại | Có loại candidate không? |
|---|---|---:|
| `owner_id` | Cô lập dữ liệu theo chủ sở hữu | Có |
| `notebook_id` | Giới hạn notebook | Có |
| `document_ids` | Danh sách tài liệu đã được cấp phép/chọn | Có |
| `documents.original_filename` | Resolver nhận diện tài liệu trong câu hỏi | Không, shadow |
| Structured business fields | Exact-match semantic filter | Không, đang tắt |

`retrieval.metadata_plan` trong Langfuse cho biết `effective_metadata_filters`, `filter_count`, dense filters và sparse RPC parameters. Với cấu hình hiện tại, business filter hợp lệ phải là `{}`.

`retrieval.document_scope_plan` cho biết:

- danh sách `documents.id` và `documents.original_filename` được dùng để resolve;
- `execution_mode=shadow`;
- `counterfactual_document_ids` là phạm vi nếu planner được áp dụng;
- `selected_document_ids` vẫn là phạm vi thực thi hiện tại;
- `applied=false` và `fail_open=true` khi chỉ shadow.

`retrieval.postgres_fts_query` và `retrieval.dense_index_query` cho thấy `document_ids` thực sự được truyền xuống hai kênh. Dense backend hiện là `PgVectorIndex`, không phải Qdrant.

### 4.2. Không được diễn giải sai object metadata lớn

Object mà người dùng thấy trong Supabase có thể chứa:

- checksum, config checksum, parser/chunking version;
- pre-embedding quality và duplicate group;
- ingestion generation;
- provenance, page, source block;
- nested `retrieval_metadata`.

Các field vận hành và provenance không tự động trở thành pre-filter. Muốn trả lời “metadata trước retrieval là gì”, phải xem `RetrievalFilters` và telemetry request, không được liệt kê toàn bộ JSON của chunk.

## 5. Audit metadata live có thật

### 5.1. Cách audit

Script `evaluation/retrieval_metadata_testset/audit_live_retrieval_metadata.py`:

1. Đọc bảng `documents` với điều kiện `status=ready`, `is_active=true`, `is_current=true`, `canonical_document_id is null`.
2. Đọc chunk cùng notebook.
3. Chỉ giữ chunk thuộc 8 document active/current.
4. Chỉ đếm field không rỗng trong `metadata.retrieval_metadata`.
5. Không ghi Supabase, không inject gold metadata.

Artifact:

- `evaluation/retrieval_metadata_testset/runs/live-retrieval-metadata-audit/summary.json`
- `evaluation/retrieval_metadata_testset/runs/live-retrieval-metadata-audit/field_coverage.csv`
- `evaluation/retrieval_metadata_testset/runs/live-retrieval-metadata-audit/documents.csv`

Snapshot được audit lúc `2026-08-06T00:34:02Z`, gồm 8 document và 187 chunk.

### 5.2. Coverage thật

| Field trong `retrieval_metadata` | Có giá trị | Coverage | Nhận xét |
|---|---:|---:|---|
| `title` | 187/187 | 100% | Đủ tin cậy cho header/display |
| `section_title` | 180/187 | 96,26% | Cấu trúc parser, không nên exact-filter tự động |
| `section_path` | 180/187 | 96,26% | Cấu trúc parser, phù hợp ranking/display |
| `content_kind` | 180/187 | 96,26% | Chỉ có `paragraph` và `table` |
| `contextual_summary` | 64/187 | 34,22% | Dữ liệu lịch sử, coverage thấp |
| `contextual_search_terms` | 63/187 | 33,69% | Dữ liệu lịch sử, không được generator v4 tạo thêm |
| `year` | 13/187 | 6,95% | Chỉ có giá trị 2025 trong snapshot |
| `document_type` | 1/187 | 0,53% | Không đủ dùng làm filter chung |
| `table_header` | 0/187 | 0% | Snapshot live hiện không có field này trong nested payload |
| `keyword_aliases` | 0/187 | 0% | Không có trên corpus live này |
| `project_code`, `project_name` | 0/187 | 0% | Không phải metadata gốc live hiện tại |
| `domain`, `clause_type`, `region` | 0/187 | 0% | Không có dữ liệu production |
| `data_period`, `effective_status`, `lifecycle_status` | 0/187 | 0% | Không có dữ liệu production |
| `source` | 0/187 | 0% | Không có trong nested payload live |

### 5.3. Ý nghĩa của coverage

- Field 0/187 không được đưa vào báo cáo như metadata production.
- Field coverage thấp không được dùng fail-closed vì sẽ loại phần lớn chunk không mang field.
- Field coverage cao vẫn chưa đủ để hard-filter. Ví dụ `section_title` có thể là `Page 12` hoặc `DOCX`, không phải canonical business key.
- `contextual_summary` vẫn còn trên 64 chunk vì tắt generator không xóa dữ liệu lịch sử và không tự động re-embed. Vì vậy không được khẳng định toàn bộ live index hiện tại là một rebuild B thuần nếu chưa re-ingest/reindex và xác minh checksum.

## 6. Text projection B được tạo như thế nào

### 6.1. Công thức

`build_embedding_text` tạo prefix theo thứ tự:

```text
Document: <semantic document title>
Document type: <document type nếu khác unknown>
Section: <semantic section/path nếu không generic>
Content type: <content kind nếu khác paragraph>
Table header: <table header nếu có>
Context: <contextual summary nếu có và được bật trong mode>

<chunk text>
```

Mode B chỉ dùng các dòng deterministic, không có dòng `Context:`.

Các phép chuẩn hóa đáng chú ý:

- title bỏ đường dẫn, extension, hậu tố `- Copy`, đổi `_` thành khoảng trắng;
- section generic như `DOCX`, `PDF`, `Page 12`, `Trang 12` bị loại khỏi semantic section;
- paragraph không cần thêm `Content type: paragraph` vì ít thông tin;
- ID, ACL, hash, page locator và operational metadata không vào embedding.

### 6.2. Tại sao chọn các field này

| Field | Lý do đưa vào deterministic header |
|---|---|
| `title` | Xác định tài liệu và giữ tên riêng sau khi chunk bị tách |
| `document_type` | Bổ sung loại tài liệu khi parser/source thật sự cung cấp |
| `section_path`/`section_title` | Khôi phục vị trí ngữ nghĩa của chunk |
| `content_kind` | Phân biệt bảng với văn bản thường |
| `table_header` | Khôi phục tên cột, đơn vị và ý nghĩa của row |

Chúng được chọn vì có thể lấy deterministic từ parser/chunker, không cần LLM đoán. Tuy nhiên “đưa vào text index” khác với “dùng làm exact filter”. Section có thể hữu ích cho similarity dù chưa đủ chuẩn hóa làm khóa lọc.

### 6.3. Dense và sparse

- Dense dùng `embedding_text`.
- Sparse dùng `search_text`.
- Hai danh sách kết quả được hợp nhất bằng Reciprocal Rank Fusion, sau đó MMR rerank.
- Trong benchmark context, B dùng cùng deterministic header ở dense và sparse.

## 7. `contextual_summary` được sinh như thế nào

### 7.1. Vị trí trong pipeline

Luồng ingestion:

```text
parse -> structure-aware chunking -> deterministic metadata/header
      -> optional contextual enrichment
      -> build embedding_text/search_text
      -> embed -> persist chunk/vector/payload
```

Context enrichment xảy ra sau khi đã có chunk và metadata cấu trúc, trước embedding. Mã chính:

- `app/pipeline/indexing/application/pipeline.py`
- `app/pipeline/indexing/adapters/context_enrichers.py`
- `app/pipeline/indexing/domain/context_enrichment.py`

### 7.2. Dữ liệu đầu vào cho LLM

Mỗi request gồm:

- `document_title`, `document_type`, `language`;
- `section_title`, `section_path`;
- `content_kind`, `table_header`;
- `document_outline`;
- `document_context`;
- `source_scope`;
- chính `chunk` cần contextualize;
- scope metadata có whitelist như version, year, period, date/status, project, organization, region, unit.

Các ID nội bộ và ACL không nằm trong scope metadata.

Nếu toàn bộ document không vượt 12.000 ký tự, `document_context` là toàn văn. Nếu dài hơn, pipeline tạo bounded package gồm:

1. phần mở đầu tài liệu;
2. passage cùng section;
3. tối đa hai chunk trước và hai chunk sau;
4. source passage quanh offset của chunk;
5. outline các section khác.

Cách này cho LLM đủ ngữ cảnh để giải quyết tham chiếu nhưng giới hạn token và giảm nguy cơ kéo thông tin xa, không liên quan vào summary.

### 7.3. Prompt `chunk-context-v4`

Prompt yêu cầu trả đúng JSON:

```json
{
  "needs_context": true,
  "context": "Một câu ngữ cảnh bổ sung.",
  "quality_flags": []
}
```

Nguyên tắc của prompt:

- nếu chunk đã tự đủ nghĩa sau deterministic metadata, trả `needs_context=false` và context rỗng;
- nếu cần, chỉ thêm thông tin đang thiếu như actor/object, vai trò chunk, scope/trigger, tham chiếu mơ hồ, table header hoặc unit;
- không tóm tắt lại chunk;
- không tạo search terms;
- không lặp filename, title, section, page hoặc boilerplate;
- không thêm số liệu/fact không xuất hiện trong evidence;
- tối đa 45 từ và đúng một câu theo cấu hình thí nghiệm.

### 7.4. Validation và fallback

Output bị từ chối nếu:

- không phải JSON đúng ba field;
- `needs_context`, `context`, `quality_flags` mâu thuẫn;
- dài hơn 600 ký tự hoặc 45 từ;
- không kết thúc bằng dấu câu hoặc có nhiều câu;
- chứa filename/page locator/boilerplate;
- đưa vào số không có trong evidence;
- không có token mới được hỗ trợ bởi ngữ cảnh ngoài chunk;
- gần như chỉ lặp lại chunk/header.

Khi lỗi validation, retry sau dùng chính response trước cùng repair instruction ngắn dần. Nếu vẫn lỗi và `strict=false`, pipeline fail-open: không tạo summary mới, ghi `status=fallback`, `error_code`, checksum và tiếp tục ingestion.

Các log “exceeded 45 words” hoặc “must contain exactly one sentence” là bằng chứng guard đã chặn output không hợp lệ, không phải output đó đã được index. Run v4 cuối cùng có `fallback_count=0`.

### 7.5. Vì sao thiết kế như vậy

Thiết kế này cố tái hiện ý tưởng contextual retrieval nhưng thêm guard production:

- deterministic header xử lý phần ngữ cảnh chắc chắn trước;
- LLM chỉ lấp phần thiếu, tránh kể lại cả chunk;
- một câu ngắn giảm dilution trong embedding/BM25;
- temperature 0 và cache theo prompt/model/input checksum tăng tính tái lập;
- số liệu phải xuất hiện trong evidence để giảm hallucination;
- fallback không làm hỏng cả ingestion.

## 8. Bộ benchmark frozen được xây như thế nào

### 8.1. Quy mô corpus

Manifest `real_benchmark_v3/manifest.json` ghi:

- 9 tài liệu thật;
- 277 chunk retrieval;
- 300 query tiếng Việt;
- 121 scenario;
- 123 evidence fact;
- 255 query answerable, 45 case null/permission denied không có đáp án được phép;
- unresolved ground truth: 0.

9 tài liệu gồm hai hợp đồng PDF, một tài liệu chính sách DOCX, bốn hồ sơ giá 2023-2026, một catalogue tiện ích và một kế hoạch triển khai.

### 8.2. Mười capability slice

Mỗi primary slice có đúng 30 query:

| Slice | Mục tiêu |
|---|---|
| `content_only` | Tìm bằng nội dung, không dựa filter |
| `explicit_filter` | Query nói rõ metadata điều kiện |
| `implicit_filter` | Query ngụ ý điều kiện metadata |
| `cross_document_confusion` | Phân biệt fact gần giống giữa tài liệu |
| `version_conflict` | Phiên bản, thời gian và xung đột scope |
| `section_localization` | Tìm đúng section |
| `table_structured` | Tìm đúng table/cell và provenance |
| `multi_hop` | Phải thu đủ nhiều evidence group |
| `null_insufficient` | Không trả evidence khi không có match hợp lệ |
| `permission_sensitive` | Cặp cùng query nhưng khác quyền truy cập |

Target types: 200 single, 40 multi-hop, 30 null, 15 permission allowed và 15 permission denied.

### 8.3. Độ đa dạng câu hỏi

300 query được phân phối qua sáu style:

- canonical: 51;
- concise: 51;
- conversational: 51;
- abbreviated: 49;
- light typo: 49;
- no accents: 49.

Mục đích là tránh benchmark chỉ đo exact keyword match trên một kiểu diễn đạt chuẩn.

### 8.4. Ground truth được tạo và kiểm tra

Builder `build_real_metadata_benchmark.py`:

1. Parse tài liệu nguồn bằng pipeline của repo.
2. Trích fact từ bảng/section có quy tắc xác định.
3. Ánh xạ mỗi fact tới deterministic chunk ID.
4. Tạo query theo scenario và style.
5. Gắn relevant chunk IDs, relevant document titles, evidence groups, expected terms và metadata conditions.
6. Kiểm tra tất cả referenced chunk đều tồn tại.
7. Kiểm tra expected term thực sự nằm trong source chunk.
8. Kiểm tra numeric term không bị cắt mất phần nghìn/đơn vị.
9. Kiểm tra multi-hop có ít nhất hai evidence group.
10. Kiểm tra 15 permission pair có cùng query text và chỉ khác access scope.
11. Kiểm tra table case khớp parser-native `table_id` và `source_block_ids`.

### 8.5. Human review và đóng băng

`approval.json` xác nhận:

- status `approved_frozen_gold`;
- approved date 04/08/2026;
- 300 case đã được benchmark owner duyệt;
- testset SHA-256 `e0173d337a62060775ceae2833989d5f831f85bd585c6d8d129d925ba2d6e497`;
- query-source bundle và gold metadata cũng có fingerprint.

Builder dừng nếu source, testset hoặc gold metadata thay đổi nhưng approval cũ vẫn được dùng. Điều này ngăn việc âm thầm sửa đáp án sau khi xem kết quả.

### 8.6. Vì sao bộ test có giá trị

Các điểm làm benchmark đáng tin hơn một danh sách câu hỏi tự phát:

- dùng tài liệu thật và chunk ID deterministic;
- đáp án neo vào evidence cụ thể;
- có negative/null và permission controls;
- có cross-document, version, table và multi-hop;
- có query style đa dạng;
- có human approval và hash đóng băng;
- các mode dùng cùng query/corpus/gold;
- kết quả so sánh paired trên cùng query;
- có W/T/L, bootstrap CI và permutation test;
- có macro summary theo scenario/evidence fact để giảm ảnh hưởng fact bị lặp.

### 8.7. Giới hạn của benchmark

- 9 tài liệu đều thuộc phạm vi dữ liệu hiện tại, chưa đại diện mọi file người dùng có thể upload.
- DOCX table được chunk atomic, nên nhiều row-level query có thể trỏ cùng một chunk. Manifest ghi chỉ có 45 unique relevant chunk và tối đa 40 query/chunk.
- Context comparison v4 hiện có paired bootstrap/permutation theo query; cần đọc thêm macro scenario/evidence-fact vì dependency giữa query chưa được phản ánh vào CI của file comparison cũ.
- Không có image/chart/scan/OCR trong table slice.
- Permission slice là isolated harness, không thay thế security test production.
- Local BM25 trong context harness production-like nhưng tokenizer có thể khác PostgreSQL FTS.

## 9. Tập đáp án dùng để đối soát

Đây là phần dễ nhầm nhất.

### 9.1. Answer key chính

`evaluation/retrieval_metadata_testset/real_benchmark_v3/testset.jsonl`

Mỗi dòng chứa:

- `query`;
- `answerable`, `target_type`;
- `relevant_chunk_ids`, `relevant_chunk_groups`;
- `relevant_doc_ids`, `relevant_doc_titles`;
- `expected.must_include_terms`;
- citation bắt buộc/cấm;
- protected/forbidden chunk IDs;
- table cell/provenance nếu là table case;
- retrieval filter conditions;
- human review status.

Đây là “tập đáp án” cho retrieval. Nó không nhất thiết chứa một đoạn văn trả lời mẫu hoàn chỉnh; scorer đối chiếu chunk, evidence group, term và citation.

### 9.2. Bản dễ đọc để review

`evaluation/retrieval_metadata_testset/real_benchmark_v3/queries_for_review.csv`

CSV có 300 dòng, gồm câu hỏi, relevant document/chunk, expected terms, expected response class, table target và xác nhận human review. Đây là file phù hợp nhất để mở cho giảng viên kiểm tra thủ công.

### 9.3. Các file không phải answer key

- `gold_metadata.json`: metadata oracle/rule dùng trong benchmark; không phải metadata production và không phải câu trả lời mẫu.
- `testset.resolved.jsonl`: testset sau khi runner xác minh lại chunk IDs với corpus của run.
- `retrieval_results.jsonl`: output của từng mode, dùng để chấm, không phải đáp án.
- `ground_truth_audit.csv`: biên bản kiểm tra ground truth, không phải đáp án.

### 9.4. Cách đối soát một case

1. Lấy `query_id` trong `queries_for_review.csv`.
2. Xem `relevant_chunk_ids` và `must_include_terms`.
3. Tìm chunk đó trong `runs/.../corpus.jsonl`.
4. Tìm cùng `query_id + mode` trong `retrieval_results.jsonl`.
5. Xem top-k có relevant chunk không.
6. Đọc dòng tương ứng trong `metrics_all_queries/retrieval_metric_details.csv`.

### 9.5. Có hai answer key khác nhau cho hai phép đo

Không nên trộn answer key của frozen benchmark với answer key của A/B live:

| Phép đo | Answer key/ground truth | Dạng đáp án |
|---|---|---|
| Context và metadata benchmark 300 query | `real_benchmark_v3/testset.jsonl` | Chunk/evidence group, term bắt buộc, citation, filter condition, response class |
| Review thủ công benchmark 300 query | `real_benchmark_v3/queries_for_review.csv` | Cùng gold ở dạng bảng dễ đọc |
| A/B document scope live 19 query | `live_document_scope_testset.jsonl` | `expected_document_id`, `expected_chunk_id`, `expected_terms` |

Frozen benchmark **không có một cột “câu trả lời văn mẫu hoàn chỉnh”**. Đây là chủ ý: phần retrieval được chấm bằng evidence đúng, còn một câu trả lời có thể diễn đạt theo nhiều cách. `expected.must_include_terms` và yêu cầu citation là hợp đồng tối thiểu để chấm answer grounding, không phải đoạn văn bắt mô hình phải chép lại. File `generation_quality.csv` của A/B live là output đã chấm theo answer key 19 case, không phải tập đáp án gốc.

## 10. Thử nghiệm context v4 được thực hiện như thế nào

### 10.1. Quy trình end-to-end của một lần chạy

Runner thực hiện theo thứ tự sau:

1. Đọc 300 case đã frozen và 277 chunk; kiểm tra fingerprint/approval.
2. Resolve ground truth sang chunk ID tồn tại trong đúng corpus của run. Nếu còn case `unresolved`, run dừng trừ khi người chạy bật cờ bỏ qua có chủ ý.
3. Tạo bảy projection A-E trên **cùng chunk text**. Với mode cần OpenAI context, gọi/cached `gpt-4o-mini`, validate output rồi mới ghép vào projection.
4. Tạo một index riêng cho mỗi mode: BM25 trên `search_text`, vector cosine trên `embedding_text`, sau đó RRF và MMR.
5. Với mỗi query, giữ nguyên scope và gold filter giữa các mode; chỉ projection context thay đổi.
6. Lấy 20 candidate mỗi kênh, fusion/rerank và ghi top 10.
7. Mỗi cặp `query × mode` chạy retrieval ba lần. Runner ghi **một** row, dùng median của ba latency sample và lưu cả `latency_samples_ms`. Vì vậy manifest có 2.100 row = 300 query × 7 mode, không phải 6.300 row.
8. Scorer tính Recall/MRR/NDCG, safety/null/permission/table/multi-hop; sau đó so sánh paired trên cùng query bằng bootstrap và sign-flip permutation.
9. Chạy audit riêng trên text summary để phân biệt “retrieval tốt/xấu” với “summary có grounded, có thêm giá trị hay chỉ lặp lại”.

Pipeline đo có thể tóm tắt như sau:

```text
frozen source + frozen query/gold
        -> resolve/audit ground truth
        -> A/B/C/D/E text projections
        -> BM25 + dense cosine
        -> RRF -> MMR -> top 10
        -> paired retrieval metrics + context quality audit
        -> đối chiếu live coverage/A-B trước quyết định production
```

### 10.2. Biến kiểm soát

Các mode dùng chung:

- corpus 277 chunk;
- 300 query frozen;
- OpenAI `text-embedding-3-small`;
- OpenAI context model `gpt-4o-mini`;
- seed `20260803`;
- BM25 + dense cosine search;
- RRF + MMR;
- candidate-k=20, runner xuất top 10 và metric chính đọc Recall@5;
- gold relevance/metadata filter policy;
- 3 lần lặp;
- 5.000 bootstrap/permutation samples.

Chỉ text projection thay đổi giữa A, B, C, D, E.

### 10.3. Lưu ý về gold filter

Manifest ghi:

```text
ablation_metadata_source = gold
domain_metadata_channel_policy_by_mode[*].filter = true
```

Tất cả mode A-E có cùng filter policy. Vì vậy:

- A so với B đo deterministic header;
- B so với C đo vị trí/tác động của raw summary;
- không được dùng A-B để nói “metadata hard filter tăng 31,76 điểm”.

### 10.4. Định nghĩa từng mode

| Mode | Dense embedding text | Sparse search text | Ý nghĩa |
|---|---|---|---|
| A | Chunk | Chunk | Lower bound |
| B | Header + chunk | Header + chunk | Deterministic baseline |
| C-dense | Header + raw summary + chunk | Header + chunk | Đo summary trên dense |
| C-sparse | Header + chunk | Header + raw summary + chunk | Đo summary trên sparse |
| C | Header + raw summary + chunk | Header + raw summary + chunk | Raw context cả hai kênh |
| D | Header + gold/effective summary + chunk | Tương tự | Oracle/upper bound |
| E | Header + summary của chunk khác cùng document + chunk | Tương tự | Negative control |

E chỉ hoán đổi summary trong cùng document. Nếu E gần C, summary có thể chỉ chứa keyword chung cấp tài liệu. Nếu C tốt hơn E, summary đúng chunk có mang tín hiệu đặc thù.

Tên “gold/effective” của D cần được hiểu chính xác. Runner tạo `gold_metadata` bằng cách lấy current metadata làm nền, ghi đè document/rule metadata trên chunk match, rồi mới tạo fallback summary từ `contextual_search_terms` nếu rule match nhưng chưa có summary. Run có 106/277 chunk mang gold annotation; vì vậy D không phải 277 câu summary đều do người viết thủ công. Nó là projection tốt nhất sẵn có từ hỗn hợp current + rule/gold override, phù hợp làm mốc chẩn đoán tiềm năng, nhưng không phải một pipeline production tự động hay một “human oracle tuyệt đối”.

## 11. Kết quả context v4

### 11.1. Kết quả tuyệt đối

| Mode | Recall@5 | MRR@10 | NDCG@10 | Success@5 | Multi-hop đủ nhóm@10 | Table success@10 |
|---|---:|---:|---:|---:|---:|---:|
| A | 64,71% | 50,56% | 56,09% | 62,67% | 30,00% | 53,33% |
| **B** | **96,47%** | **81,83%** | **86,34%** | **90,67%** | **72,50%** | **100%** |
| C-dense | 96,08% | 81,61% | 86,08% | 88,67% | 67,50% | 96,67% |
| C-sparse | 97,25% | 82,82% | 87,08% | 92,00% | 72,50% | 100% |
| C | 95,29% | 80,89% | 85,50% | 89,00% | 67,50% | 96,67% |
| D | 97,25% | 85,61% | 89,17% | 93,33% | 80,00% | 100% |
| E | 90,59% | 76,11% | 81,70% | 84,67% | 65,00% | 100% |

### 11.2. Paired Recall@5 comparison

| Comparison | Delta | CI95% | W/T/L | p permutation | Kết luận |
|---|---:|---:|---:|---:|---|
| B - A | +31,76 đ.% | [+25,49; +38,04] | 86/164/5 | 0,0002 | B cải thiện rõ |
| C-dense - B | -0,39 đ.% | [-2,35; +1,18] | 2/250/3 | 1,0000 | Không cải thiện |
| C-sparse - B | +0,78 đ.% | [0; +1,96] | 2/253/0 | 0,4981 | Tín hiệu nhỏ, chưa đủ |
| C - B | -1,18 đ.% | [-3,53; +1,18] | 3/246/6 | 0,5141 | Không vượt B |
| D - C | +1,96 đ.% | [-0,39; +4,71] | 8/244/3 | 0,2188 | Oracle tốt hơn nhưng chưa rõ ở Recall |
| C - E | +4,71 đ.% | [+1,57; +8,24] | 16/235/4 | 0,0130 | Summary đúng chunk có tín hiệu thật |

### 11.3. Phân tích từng kết quả

**B so với A:** deterministic header giải quyết mạnh vấn đề chunk mất title/section/table context. Tăng không chỉ ở Recall mà còn MRR, NDCG, multi-hop và table retrieval. Đây là bằng chứng chắc nhất của nghiên cứu.

**C-dense:** summary không cải thiện vector similarity ngoài header. CI chứa 0 và số query thay đổi rất ít.

**C-sparse:** tăng 0,78 điểm nhưng chỉ 2 query thắng, 253 hòa, không có bằng chứng thống kê. Có thể summary thêm đúng keyword cho một vài case, nhưng chưa đủ để trả chi phí LLM và rủi ro chất lượng cho toàn corpus.

**C cả hai kênh:** thấp hơn B. Một summary có thể thêm từ đồng nghĩa hữu ích cho sparse nhưng đồng thời làm lệch dense hoặc tăng nhiễu trong fusion. Vì vậy không thể suy từ C-sparse rằng nên bật summary ở mọi kênh.

**D:** cho thấy nếu có context chất lượng cao hơn, MRR/NDCG và multi-hop còn dư địa. Nhưng D dùng effective context có gold/rule override trên phần được annotation và current làm nền; đây là mốc trần chẩn đoán tương đối, không phải pipeline tự động hiện tại và cũng không phải human oracle đầy đủ trên toàn bộ 277 chunk.

**E:** C tốt hơn E có ý nghĩa. Điều này bác bỏ nhận định cực đoan rằng summary hoàn toàn vô dụng. Kết luận đúng là raw summary có tín hiệu chunk-specific, nhưng chất lượng/placement chưa đủ ổn định để vượt B.

### 11.4. Chi phí text

| Mode | Avg dense tokens | Avg sparse tokens |
|---|---:|---:|
| A | 239,21 | 239,21 |
| B | 249,86 | 245,35 |
| C-dense | 258,06 | 245,35 |
| C-sparse | 249,86 | 253,23 |
| C | 258,06 | 253,23 |
| D | 261,89 | 256,81 |

B chỉ tăng khoảng 10,65 token dense trung bình so với A nhưng tăng Recall rất lớn. C tăng thêm khoảng 8 token mà không tạo cải thiện đáng tin cậy. Đây là một lý do kinh tế để giữ B.

## 12. Audit chất lượng `contextual_summary`

Manifest v4:

- 277 chunk;
- generated: 89;
- not needed: 188;
- fallback: 0;
- context cache hits: 271.

Audit heuristic trên 89 raw summary:

- keep: 9;
- keep and monitor: 38;
- regenerate: 31;
- reject: 11.

Như vậy 42/89 summary sinh ra bị đánh dấu regenerate/reject theo rule audit. Ví dụ một summary có thể grounded và đúng một câu nhưng chỉ lặp lại chunk, nên `added_value_score` và `non_redundancy_score` bằng 0.

Audit này là rule-based quality gate, không phải human semantic judgment. Nó hữu ích để tìm lỗi hệ thống nhưng không tự chứng minh câu context đúng hoàn toàn.

Kết hợp audit và retrieval result:

- generator v4 tuân thủ format tốt, không fallback;
- nhiều chunk được xác định đúng là không cần context;
- số summary thật sự có added value còn hạn chế;
- raw summary không vượt B khi đưa vào cả hai kênh;
- production mặc định vì vậy để enrichment `false`.

## 13. Nghiên cứu lựa chọn field metadata

### 13.1. Field study trên frozen snapshot

Một nghiên cứu field-level từng đo các candidate trên snapshot 277 chunk:

| Field | Coverage snapshot | Relevant retention | Recall@5 có filter | Không filter | Delta | Cluster p |
|---|---:|---:|---:|---:|---:|---:|
| `project_code` | 36/277 | 100% | 100% | 88,89% | +11,11 đ.% | 0,1204 |
| `content_kind` | 277/277 | 100% | 93,33% | 96,67% | -3,33 đ.% | 1,0000 |
| `project_name` | 36/277 | 36% | 36,00% | 82,00% | -46,00 đ.% | 0,0006 |
| `section_title` | 277/277 | 100% | 100% | 93,55% | +6,45 đ.% | 0,5027 |
| `year` | 52/277 | 55% | 55,00% | 87,50% | -32,50 đ.% | 0,0020 |

Artifact: `runs/production-metadata-field-study-openai/production_field_decision.csv`.

Manifest của run này ghi `production_metadata_only=false`. Vì vậy nó là evidence nghiên cứu trên aligned/frozen snapshot, không đủ để tự động activate production.

### 13.2. Leave-one-field-out mới nhất: field có giá trị gì khi metadata đúng

Run `real-benchmark-v3-filter-field-ablation-openai` cô lập đúng vai trò pre-filter. Nó giữ cố định deterministic header B, OpenAI embedding, corpus, query và ranking; `filter_full` dùng năm field gold, sau đó mỗi mode chỉ bỏ một field. Phần chấm field dùng 110 query có khả năng filter, gồm 80 answerable và 30 null.

Kết quả full filter trên tập 110 query:

- Recall@5 = 100% trên 80 query answerable;
- MRR@10 = 90,625%, NDCG@10 = 93,041%;
- null rejection@10 = 100% trên 30 query null;
- forbidden top-1 = 0%.

Khi bỏ toàn bộ năm field domain, Recall@5 còn 93,75%, MRR còn 73,121%, NDCG còn 79,173%; cả 30/30 null case đều thất bại và forbidden top-1 tăng lên 10%. Điều này chứng minh **metadata filter đúng có giá trị**, nhưng chỉ trong điều kiện oracle/gold.

| Field bị bỏ | Tập query liên quan | Tác động chính so với full | Cách đọc đúng |
|---|---:|---|---|
| `project_name` | 80 (50 answerable, 30 null) | Recall@5 -4,00 điểm; MRR -16,998; NDCG -12,861 | Project identity đưa đúng project lên sớm; MRR/NDCG giảm có ý nghĩa, Recall chỉ mất 2/50 case |
| `year` | 70 (40 answerable, 30 null) | Recall không đổi; null rejection 100% -> 0% | Year là correctness gate cho câu hỏi “năm không tồn tại”, không chỉ là ranking hint |
| `lifecycle_status` | 40 answerable | MRR -3,333; NDCG -2,50; scenario `p=0,1226` | Có tín hiệu rủi ro nhưng chưa đủ mạnh để chốt độc lập |
| `document_type` | 90 | Recall/null không đổi; bỏ field còn làm MRR tăng nhẹ 0,972 điểm, `p=0,4863` | Dư thừa trong test hiện tại vì đồng xuất hiện với field khác và header B đã chứa document type |
| `source` | 30 | Mọi metric giữ 100% | Benchmark chỉ có một source value và luôn đồng xuất hiện; chưa có sức phân biệt |

Điểm quan trọng: run này **không thử chất lượng extractor production**. Manifest ghi `ablation_metadata_source=gold`; do đó nó trả lời “nếu field đúng thì field có ích không?”, chưa trả lời “repo hiện sinh field đủ đúng/đủ phủ để bật chưa?”.

### 13.3. Hợp nhất hai trục bằng chứng: utility và deployability

Một field chỉ được chọn production khi qua cả hai trục:

| Trục | Câu hỏi | Artifact trả lời |
|---|---|---|
| Utility | Nếu giá trị field đúng, bỏ nó có làm retrieval/safety xấu đi không? | `FILTER_FIELD_ABLATION_REPORT.md` |
| Deployability | Current extractor/live payload có tạo field đúng, đủ coverage và giữ đủ relevant evidence không? | field study, live coverage audit, live A/B |

Đây là cách giải thích các kết quả tưởng như mâu thuẫn:

- `project_name` **có utility cao khi gold đúng**, vì bỏ nó làm MRR giảm gần 17 điểm; nhưng current/exact-name study chỉ giữ 36% relevant evidence và live coverage là 0/187. Vì vậy nên dùng tên/alias để resolve sang `project_code` canonical, chưa dùng equality trực tiếp trên tên tự do.
- `year` **rất cần cho null rejection khi gold đúng**, nhưng current study chỉ giữ 55% relevant evidence, làm Recall giảm 32,5 điểm và live coverage chỉ 6,95%. Vì vậy phải xây typed temporal extractor và backfill có provenance trước khi bật.
- `document_type` có trong schema/header nhưng chưa có incremental filter value trong ablation và live chỉ 1/187; giữ cho ranking/header ở nơi có nguồn thật, không bật hard filter chung.
- `source` và `lifecycle_status` chưa đủ variation/scenario để kết luận; dữ liệu live lại không có, nên tiếp tục shadow/research.

Quy tắc quyết định cuối cùng là:

```text
approved hard filter
= field có utility đo được
+ nguồn authoritative/deterministic
+ coverage và agreement đạt gate
+ relevant retention = 100%
+ A/B current-metadata không regression
```

Hiện không field business nào thỏa toàn bộ phép giao này, nên `hard_filter_fields=[]` là nhất quán với bằng chứng chứ không phủ nhận giá trị oracle của metadata.

### 13.4. Vì sao không chọn từng field làm hard filter

**`project_code`:** có logic deterministic chặt từ heading dạng `P<digits> • <project name>` và kết quả subset dương. Nhưng chỉ có 18 scenario, cluster `p=0,1204`, đồng thời live coverage là 0/187. Nó là candidate tốt cho một corpus chuyên biệt đã chuẩn hóa mã dự án, không phải filter chung hiện tại.

**`project_name`:** exact name không giữ được alias/biến thể và chỉ retention 36%, làm Recall giảm 46 điểm. Nếu sau này có canonical map, name chỉ nên resolve sang ID/code, không trực tiếp fail-closed.

**`year`:** extractor đúng ở nơi filename có duy nhất một năm nhưng bỏ thiếu nhiều chunk cần năm; retention 55% và Recall giảm 32,5 điểm. Coverage live chỉ 6,95%.

**`section_title`:** giúp localization và ranking nhưng agreement snapshot chỉ 88,09%, có giá trị generic như `Page 12` hoặc `DOCX`. Nó không phải canonical exact key.

**`content_kind`:** coverage tốt nhưng query có thể cần evidence table lẫn paragraph; filter làm Recall giảm. Field này phù hợp boost/routing có kiểm soát, không hard filter tự động.

**`document_type`:** live chỉ 1/187. Không đủ dữ liệu để activate.

**`domain`, `clause_type`, `region`, period/status/source:** live 0/187, nên bị loại trước khi bàn tới A/B production.

**`contextual_summary` và `contextual_search_terms`:** đây là generated/ranking context, không phải canonical key. Dùng chúng làm exact metadata filter là sai loại dữ liệu.

## 14. A/B metadata định danh tài liệu trên live corpus

### 14.1. Thiết kế

Live test dùng:

- Supabase/PostgreSQL FTS và pgvector thật;
- 8 tài liệu active/current, 187 chunk;
- 19 query source-anchored;
- 3 repeats, thứ tự mode được shuffle bằng seed `20260806`;
- top-k=5;
- 16 query có filename identity đủ rõ để route;
- không inject gold metadata vào chunk;
- expected document/chunk UUID phải tồn tại live;
- expected terms phải nằm trong chính source chunk trước khi test chạy;
- answer pass chỉ khi đủ expected terms và citation đúng expected chunk.

Hai mode:

1. `baseline_all_authorized_documents`: tìm trên toàn bộ document được phép.
2. `document_identity_scope`: nếu query match duy nhất `original_filename`, chỉ tìm trong document đó; query mơ hồ fail-open về toàn scope.

Đây là A/B của **document scope metadata trên current live index**, không phải A/B thuần B text projection. Live index có lịch sử ingestion hỗn hợp, nên không được gọi mode baseline là “B thuần”.

### 14.2. Kết quả

| Metric | Toàn authorized scope | Route theo document identity | Delta |
|---|---:|---:|---:|
| Recall@5 | 63,16% | 57,89% | -5,26 đ.% |
| MRR | 52,63% | 52,63% | 0 |
| Candidate chunk trung bình | 187,00 | 64,26 | -65,63% |
| Median retrieval latency | 597,06 ms | 615,25 ms | +18,20 ms |
| Grounded answer pass | 57,89% | 57,89% | 0 |
| Expected term recall | 68,42% | 68,42% | 0 |
| Citation đúng expected chunk | 63,16% | 57,89% | -5,26 đ.% |

### 14.3. Diễn giải

Metadata định danh tài liệu thực sự làm giảm search space, nhưng corpus chỉ có 187 chunk nên phần tiết kiệm ở database không thắng được overhead/planner/agentic retrieval. Quan trọng hơn, một số kết quả sau route bị dừng sớm hoặc rerank khác, làm expected chunk rơi khỏi top 5.

Kết quả này không chứng minh document routing luôn xấu. Nó chứng minh trên snapshot live và pipeline hiện tại, resolver chưa vượt gate non-regression và latency. Quyết định đúng là `shadow`, thu telemetry trước khi bật.

## 15. Metadata được chốt theo từng vai trò

### 15.1. Luôn áp dụng trước retrieval

```text
owner_id + notebook_id + authorized document_ids
```

Đây là scope/security contract, không phải cải tiến semantic metadata.

### 15.2. Dùng tạo text index khi nguồn có thật

```text
title
document_type (nếu khác unknown)
semantic section_path/section_title
content_kind (nếu khác paragraph)
table_header (nếu parser cung cấp)
```

Đây là cấu hình B đã có bằng chứng retrieval tốt.

### 15.3. Giữ trong payload để giải thích/provenance

```text
title
section_title
section_path
content_kind
year (chỉ nơi suy ra chắc chắn)
contextual_summary/contextual_search_terms lịch sử
page/chunk/source block/provenance fields
```

Payload field không đồng nghĩa hard filter.

### 15.4. Shadow/resolver only

```text
documents.original_filename -> document IDs
```

### 15.5. Chưa được dùng hard filter

```text
project_code, project_name, project aliases
document_type, content_kind, section_title, year
data_period, effective_status, lifecycle_status
domain, clause_type, region, source
contextual_summary, contextual_search_terms
```

Policy machine-readable: `configs/retrieval_metadata_policy.json` có `hard_filter_fields=[]` và decision `shadow_only_failed_non_regression_and_latency_gates`.

## 16. Những điều đã chứng minh và chưa chứng minh

### Đã chứng minh

- B tốt hơn A rõ ràng trên frozen benchmark.
- Summary đúng chunk tốt hơn shuffled summary.
- Raw summary cả hai kênh không vượt B.
- C-sparse chỉ là tín hiệu nhỏ, chưa có significance.
- Live document routing giảm candidate nhưng chưa tăng chất lượng hoặc tốc độ.
- Business field coverage live hiện không đủ để hard-filter.

### Chưa chứng minh

- Không chứng minh metadata filter tạo ra mức tăng B-A.
- Không chứng minh D là cấu hình production vì D dùng oracle/gold.
- Không chứng minh `project_code` dùng được cho mọi tài liệu.
- Không chứng minh tắt enrichment đã làm toàn bộ vector live trở thành B; cần reindex để khẳng định.
- Không chứng minh 19 live query đại diện cho toàn bộ traffic.
- Không chứng minh candidate reduction sẽ giảm latency khi corpus lớn; cần canary ở quy mô lớn hơn.

## 17. Cách trình diễn bằng Langfuse

Với một query thật, mở trace và lần lượt chỉ:

1. `retrieval.document_scope_plan`
   - input có authoritative documents;
   - output có `execution_mode=shadow`, selected và counterfactual IDs.
2. `retrieval.metadata_plan`
   - `effective_metadata_filters={}`;
   - `filter_count=0`;
   - dense/sparse business parameters rỗng.
3. `retrieval.hybrid_search`
   - `notebook_id`, `document_ids`, metadata filters.
4. `retrieval.postgres_fts_query`
   - sparse RPC nhận `p_owner_id`, `p_notebook_id`, `p_document_ids`;
   - không có business RPC parameter khi filter tắt.
5. `retrieval.dense_index_query`
   - backend `PgVectorIndex`;
   - cùng document scope và metadata filters.
6. `retrieval.rrf_fusion`
   - chunk IDs sau hợp nhất.

Câu trình bày:

> Trace này chứng minh scope nào đã được truyền xuống retrieval, field nào chỉ được planner đề xuất và field nào thực sự được áp dụng. Metadata business đang rỗng là quyết định có chủ đích sau A/B, không phải hệ thống quên lưu metadata.

## 18. Lệnh tái lập

### 18.1. Context-quality v4

```powershell
.\evaluation\retrieval_metadata_testset\run_context_quality_ablation.ps1 `
  -EmbeddingProvider openai `
  -EmbeddingModel text-embedding-3-small `
  -ContextMaxWords 45 `
  -ContextMaxOutputTokens 400 `
  -Repeats 3 `
  -BootstrapSamples 5000
```

### 18.2. Audit metadata live chỉ đọc

```powershell
.\.venv\Scripts\python.exe `
  .\evaluation\retrieval_metadata_testset\audit_live_retrieval_metadata.py
```

### 18.3. Live document-scope A/B

```powershell
.\.venv\Scripts\python.exe `
  .\evaluation\retrieval_metadata_testset\run_live_document_scope_ablation.py
```

Lưu ý: live A/B gọi embedding/generation API và cần service-role credential. Audit coverage chỉ đọc Supabase và không gọi generation.

### 18.4. Leave-one-field-out cho pre-filter

```powershell
.\evaluation\retrieval_metadata_testset\run_filter_field_ablation.ps1 `
  -EmbeddingProvider openai `
  -Repeats 3 `
  -BootstrapSamples 5000
```

Đọc `FILTER_FIELD_ABLATION_REPORT.md` cùng `filter_field_decision_summary.csv`. Không dùng riêng run này để activate production vì metadata của ablation là gold.

## 19. Bản đồ bằng chứng trong repo

| Câu hỏi | File đối soát |
|---|---|
| Runtime đang bật gì? | `.env`, `app/bootstrap/settings.py`, `app/pipeline/bootstrap/settings.py` |
| Text index được tạo thế nào? | `app/shared/contextual_text.py` |
| Metadata chunk được normalize thế nào? | `app/pipeline/indexing/domain/retrieval_metadata.py` |
| Context prompt và guard ở đâu? | `app/pipeline/indexing/adapters/context_enrichers.py` |
| Gói ngữ cảnh dài được tạo thế nào? | `app/pipeline/indexing/application/pipeline.py` |
| Filter contract là gì? | `app/retrieval/domain/models.py` |
| Filter plan hiển thị ở Langfuse? | `app/retrieval/application/handle_retrieval_request.py` |
| Document resolver telemetry? | `app/chat/application/services.py` |
| Benchmark builder? | `evaluation/retrieval_metadata_testset/build_real_metadata_benchmark.py` |
| Benchmark manifest? | `evaluation/retrieval_metadata_testset/real_benchmark_v3/manifest.json` |
| Approval/fingerprint? | `evaluation/retrieval_metadata_testset/real_benchmark_v3/approval.json` |
| Answer key? | `evaluation/retrieval_metadata_testset/real_benchmark_v3/testset.jsonl` |
| Human-readable answer review? | `evaluation/retrieval_metadata_testset/real_benchmark_v3/queries_for_review.csv` |
| Context run manifest? | `runs/real-benchmark-v3-context-quality-v4-openai/run_manifest.json` |
| Context paired metrics? | `runs/real-benchmark-v3-context-quality-v4-openai/metrics_all_queries/retrieval_metric_comparison.csv` |
| Context quality audit? | `runs/real-benchmark-v3-context-quality-v4-openai/context_quality_audit.summary.json` |
| Giá trị riêng của từng pre-filter field khi gold đúng? | `runs/real-benchmark-v3-filter-field-ablation-openai/FILTER_FIELD_ABLATION_REPORT.md` |
| Số liệu leave-one-field-out dạng máy đọc? | `runs/real-benchmark-v3-filter-field-ablation-openai/filter_field_decision_summary.csv` |
| Live metadata coverage? | `runs/live-retrieval-metadata-audit/field_coverage.csv` |
| Live metadata A/B? | `runs/live-document-scope-ablation/summary.json` |
| Production decision policy? | `configs/retrieval_metadata_policy.json` |

Mọi đường dẫn `runs/...` trong bảng nằm dưới `evaluation/retrieval_metadata_testset/`.

## 20. Kết luận cuối cùng

Phương án tốt nhất có đủ bằng chứng hiện tại là:

1. Dùng deterministic header B để tạo dense/sparse text cho lần ingestion mới.
2. Để contextual enrichment tắt mặc định; giữ code và benchmark để nghiên cứu C-sparse ngoài mẫu.
3. Luôn enforce `owner_id`, `notebook_id`, `document_ids`.
4. Không bật structured business filter trên corpus live hiện tại.
5. Giữ filename resolver ở shadow và dùng Langfuse để chứng minh counterfactual plan.
6. Không backfill field bằng LLM chỉ để tăng coverage. Chỉ mở field khi có nguồn authoritative, agreement, retention và A/B non-regression.
7. Muốn tuyên bố live index hoàn toàn dùng B, phải re-ingest/reindex toàn bộ active/current documents và lưu manifest/checksum của projection.

Đóng góp khoa học/kỹ thuật của phần này không phải “thêm càng nhiều metadata càng tốt”. Đóng góp là xây được quy trình đo tách biệt, tìm ra deterministic context có hiệu quả lớn, phát hiện generated context chưa ổn định, kiểm tra metadata thật thay vì oracle và ngăn field không có nguồn gốc làm giảm retrieval production.
