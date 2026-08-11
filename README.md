# RAG Notebook

RAG Notebook là ứng dụng hỏi đáp trên tài liệu, gồm React SPA, FastAPI, Supabase và OpenAI. Dữ liệu
notebook, tài liệu, hội thoại và citation được cô lập theo người dùng bằng Row Level Security (RLS).

Happy path hiện tại:

```text
Native PDF
  -> Supabase Storage
  -> durable ingestion job
  -> Advanced Extraction
  -> evidence-backed metadata enrichment (deterministic first, LLM last)
  -> parent/child chunking
  -> OpenAI text-embedding-3-small
  -> canonical metadata + retrieval projection (PostgreSQL FTS/pgvector)
  -> hybrid retrieval
  -> streamed chat kèm citation
```

README này hướng tới đội kỹ thuật cần dựng môi trường phát triển và chạy demo bằng Supabase cloud.

## Phạm vi hiện tại

| Hạng mục | Trạng thái |
|---|---|
| Authentication và RLS | Đã dùng Supabase Auth; dữ liệu nghiệp vụ được giới hạn theo owner |
| Notebook | Đã có tạo, xem, sửa và archive |
| Document upload | Đã có batch upload 1–20 file, kiểm tra định dạng, Storage và phân trang |
| Durable ingestion | Đã có job, lease, heartbeat, retry/reclaim và trạng thái `processing`/`ready`/`failed` |
| Advanced Extraction | Đã có native parsing, quality gate, layout, table, verification và Canonical IR |
| Knowledge quality | Đã có exact dedup, fingerprint, candidate duplicate/version/conflict, review queue, audited resolution và retrieval-aware policy |
| Structured facts | Đã có table snapshot, row/cell claim, scope/qualifier/time-aware comparison, review audit và exact fact retrieval; mặc định rollout `off` |
| Embedding và vector search | Đã dùng OpenAI `text-embedding-3-small` và pgvector trên Supabase |
| Retrieval | Đã có PostgreSQL FTS + dense search, RRF fusion, MMR và tối đa ba agentic retrieval rounds |
| Chat và citation | Đã có OpenAI generation, SSE streaming, lưu hội thoại và citation |
| PDF preview | Đã có preview cho PDF đã upload |
| Profile và admin stats | Đã có API; quyền admin cần cấu hình Custom Access Token Hook |
| Enterprise IAM và ACL | Đã có RBAC chức năng, group/department và quyền tài liệu theo access subject |
| Enterprise document lifecycle | Đã có upload khởi tạo atomic, source file, logical document, version, processing history, review, publish, archive, retry và audit |
| Enterprise grounded Q&A | Chỉ retrieval `PUBLISHED + ACTIVE + current + ASK_KNOWLEDGE + READ`; trusted backend kiểm tra lại ACL và lưu answer/citation atomic |
| Canonical retrieval metadata | Document/version là nguồn chuẩn; parent/child được lưu thật; LLM chỉ tạo assertion có evidence và phải review trước khi thành hard filter |
| OCR | Có thể bật, nhưng đang là luồng experimental; PDF scan phức tạp có thể bị quality gate chặn |
| Import URL/text | Frontend đã có entry point nhưng backend chưa có API tương ứng; không thuộc demo path |

## Kiến trúc

### Web và quyền truy cập

```text
React SPA
  -> Supabase Auth
  -> FastAPI + user access token
  -> PostgREST / Supabase Storage
  -> PostgreSQL + owner-based RLS
```

CRUD của người dùng đi qua publishable key và JWT của chính người dùng để RLS tiếp tục có hiệu lực.
`SUPABASE_SERVICE_ROLE_KEY` chỉ được dùng ở tiến trình backend tin cậy: ingestion worker và CLI
reconciliation của operator cho maintenance/repair RPC, cùng Enterprise answer commit atomic.
Answer commit luôn truyền actor user rõ ràng và kiểm tra lại lifecycle/ACL trước khi lưu; role
`authenticated` không được gọi RPC commit trực tiếp. Không đưa service-role key vào frontend,
response hoặc log.

### Upload và ingestion

```text
Upload API
  -> document metadata + private Storage object
  -> ingestion_jobs.pending + document.processing
  -> worker claim job bằng lease
  -> tải object, kiểm tra size và SHA-256
  -> Advanced Extraction + quality gate
  -> document fingerprint + exact cross-format duplicate gate
  -> chunking
  -> chunk SHA-256 + bounded 8-band SimHash-LSH candidate lookup
  -> Jaccard/containment/structured-claim verification
  -> reuse compatible exact vectors; embed every remaining chunk
  -> post-embedding semantic relation candidates
  -> stage external vector generation nếu backend là Qdrant
  -> fenced complete_ingestion_job transaction + review queue
  -> durable completion_disposition: completed | duplicate_suppressed
  -> finalize hoặc xóa đúng external generation của attempt
  -> structured table facts + indexed prior-candidate diff (shadow/on)
  -> ingestion_jobs.succeeded + document.ready
```

Nếu worker dừng giữa chừng, job có thể được claim lại sau khi lease hết hạn. Việc hoàn tất chunks,
job và document status diễn ra trong một transaction Postgres. Nếu response hoàn tất bị mất hoặc
mơ hồ, adapter đọc `ingestion_jobs.completion_disposition`; không phát lại side effect. Khi một
exact-identity race được phát hiện trong transaction, database trả `duplicate_suppressed` và worker
chỉ xóa Qdrant generation mang claim token của attempt đó.

### Retrieval và chat

```text
User question
  -> canonical/current document policy theo KNOWLEDGE_QUALITY_MODE
  -> PostgreSQL full-text ranking trên chunks thuộc notebook
  +  pgvector dense search
  -> Reciprocal Rank Fusion (RRF)
  -> MMR reranking
  -> agentic sufficiency/reformulation khi cần
  -> conflict-aware OpenAI chat completion
  -> SSE answer + persisted citations
```

Generation mặc định là closed-book: câu trả lời dựa trên context được retrieval, trừ khi chủ động bật
`GENERATION_ALLOW_OUTSIDE_KNOWLEDGE`.

Quy tắc canonical metadata, evidence gate và review LLM được chốt tại
[`docs/architecture/document-metadata-policy.md`](docs/architecture/document-metadata-policy.md).

## Chạy demo

Demo path dùng API và frontend chạy local, còn Auth, Storage, Postgres/pgvector chạy trên Supabase
cloud và embedding/chat chạy qua OpenAI.

### 1. Yêu cầu

- Python `3.12`
- [uv](https://docs.astral.sh/uv/)
- Node.js `>=22` và npm (đúng với engine của Supabase JS hiện tại)
- Một Supabase project
- Một OpenAI API key

### 2. Khởi tạo Supabase

Trong SQL Editor của một Supabase project mới, chạy lần lượt các file sau:

1. `supabase/migrations/01_extensions.sql`
2. `supabase/migrations/02_tables.sql`
3. `supabase/migrations/03_functions_triggers.sql`
4. `supabase/migrations/04_rls_policies.sql`
5. `supabase/migrations/05_storage.sql`
6. `supabase/migrations/06_pgvector_search.sql`
7. `supabase/migrations/07_admin_stats.sql`
8. `supabase/migrations/08_knowledge_quality.sql`
9. `supabase/migrations/09_knowledge_quality_hardening.sql`
10. `supabase/migrations/10_chunk_preembedding_dedup.sql`
11. `supabase/migrations/11_contextual_metadata_fts.sql`
12. `supabase/migrations/12_llm_contextual_retrieval.sql`
13. `supabase/migrations/13_template_scope_conflict.sql`
14. `supabase/migrations/14_compact_chunk_metadata.sql`
15. `supabase/migrations/15_structured_retrieval_filters.sql`
16. `supabase/migrations/16_structured_fact_layer.sql`
17. `supabase/migrations/17_enterprise_iam.sql`
18. `supabase/migrations/18_enterprise_knowledge_acl.sql`
19. `supabase/migrations/19_enterprise_processing_rag.sql`
20. `supabase/migrations/20_enterprise_operations.sql`
21. `supabase/migrations/21_enterprise_security_retrieval.sql`
22. `supabase/migrations/22_enterprise_answer_ingestion_bridge.sql`
23. `supabase/migrations/23_enterprise_workflow_completion.sql`
24. `supabase/migrations/24_legacy_notebook_enterprise_bridge.sql`
25. `supabase/migrations/25_canonical_metadata_parent_projection.sql`
26. `supabase/migrations/26_temporal_scope_series.sql`
27. `supabase/migrations/27_fix_complete_processing_job_v2_digest.sql`
28. `supabase/migrations/28_guided_document_publish.sql`
29. `supabase/migrations/29_allow_reupload_after_archive.sql`

Các migration tạo schema ứng dụng, RLS, hai private bucket `documents` và
`knowledge-source-files`, pgvector search RPC, Enterprise IAM/ACL/lifecycle,
document identity/version/conflict, audit và guarded reversal. Đọc
[hướng dẫn migration 08/09](docs/migrations/08-09-knowledge-quality.md) trước khi cập nhật một
project đang có dữ liệu và [runbook Enterprise](docs/operations/enterprise-knowledge-runbook.md)
trước khi rollout. Không chạy `RESET_AND_REBUILD.sql` trên project có dữ liệu cần giữ: script đó
xóa dữ liệu ứng dụng trước khi dựng lại schema 01–29. Sau khi đổi migration, sinh lại file reset
bằng lệnh dưới đây; phần canonical phải khớp nguyên văn, đúng thứ tự với các migration 01–29.

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\regenerate_enterprise_reset.ps1
```

Bật Email provider trong Supabase Auth để người dùng có thể đăng ký hoặc đăng nhập. Demo thông
thường không cần quyền admin. Nếu cần màn hình admin, vào **Authentication → Hooks → Custom Access
Token** và chọn `public.custom_access_token_hook`.

### 3. Cấu hình backend

Từ thư mục gốc:

```powershell
Copy-Item .env.example .env
uv sync
```

Điền ít nhất các giá trị sau trong `.env`:

```dotenv
APP_ENV=development

SUPABASE_URL=https://<project-ref>.supabase.co
SUPABASE_PUBLISHABLE_KEY=<publishable-key>
SUPABASE_SERVICE_ROLE_KEY=<service-role-key>

INGESTION_WORKER_ENABLED=true

EMBEDDING_PROVIDER=openai
OPENAI_API_KEY=<openai-api-key>
OPENAI_EMBEDDING_MODEL=text-embedding-3-small
OPENAI_CHAT_MODEL=gpt-4o-mini
VECTOR_STORE_BACKEND=pgvector

OCR_ENABLED=false
```

`APP_ENV=development` phù hợp khi chạy local và giữ debug route. Khi deploy, đổi thành `production`;
OpenAI embedding và pgvector vẫn giữ nguyên.

### 4. Cấu hình frontend

```powershell
Set-Location frontend
npm install
Copy-Item .env.example .env.local
```

Điền `frontend/.env.local`:

```dotenv
VITE_SUPABASE_URL=https://<project-ref>.supabase.co
VITE_SUPABASE_PUBLISHABLE_KEY=<publishable-key>
VITE_API_URL=http://127.0.0.1:8000
VITE_ENTERPRISE_KB_ENABLED=true
VITE_SELF_SIGNUP_ENABLED=false
VITE_COMPANY_EMAIL_DOMAINS=company.example
```

`VITE_ENTERPRISE_KB_ENABLED` là kill switch giao diện và cần build lại sau khi đổi.
`VITE_SELF_SIGNUP_ENABLED=false` là mặc định khuyến nghị cho production dùng invite/SSO.
`VITE_COMPANY_EMAIL_DOMAINS` chỉ kiểm tra UX; security boundary nằm ở trigger migration 23 và
bảng `enterprise_allowed_email_domains`. Production dùng email/password phải cấu hình ít nhất một
domain `ACTIVE`; xem runbook trước khi mở signup.

### 5. Khởi động

Terminal 1, tại thư mục gốc:

```powershell
uv run python main.py
```

Terminal 2:

```powershell
Set-Location frontend
npm run dev
```

Địa chỉ mặc định:

- Frontend: `http://localhost:5173`
- Swagger UI: `http://127.0.0.1:8000/docs`
- Liveness: `http://127.0.0.1:8000/health/live`
- Readiness: `http://127.0.0.1:8000/health/ready`

### 6. Kịch bản demo

1. Đăng ký hoặc đăng nhập.
2. Tạo một notebook.
3. Upload một native PDF dưới 10 MiB.
4. Chờ trạng thái chuyển từ `processing` sang `ready`.
5. Chọn tài liệu và đặt câu hỏi có đáp án nằm trong PDF.
6. Quan sát câu trả lời streaming, mở citation và đối chiếu trong PDF preview.

Không dùng PDF scan/OCR cho happy path. OCR có hướng dẫn riêng ở phần dưới.

### 7. Kịch bản Enterprise Knowledge

1. Đăng nhập bằng tài khoản có role `ADMIN`.
2. Trong portal quản trị, upload bằng luồng atomic `POST /api/v1/documents/upload`; response phải
   trả `source_file`, logical document, v1 và processing job.
3. Theo dõi job bằng `/api/v1/processing-jobs` và detail stage/error history, chờ thành công,
   review version rồi publish.
4. Cấp `READ` và, nếu cần tải file gốc, `DOWNLOAD` cho user/role/group/department.
5. Đăng nhập bằng tài khoản `EMPLOYEE`, tìm kiếm hoặc đặt câu hỏi và mở citation.
6. Thu hồi `READ` hoặc archive document; kết quả retrieval và citation lịch sử phải biến mất ngay.

Chi tiết rollout, smoke test và rollback tại
[Enterprise Knowledge runbook](docs/operations/enterprise-knowledge-runbook.md). Khi chuẩn bị phát
hành, dùng [Enterprise release checklist](docs/operations/enterprise-release-checklist.md); chưa
chạy migration/RLS/Storage test trên Supabase staging clone thì chưa được coi là đã xác minh live.

## Cấu hình chính

`.env.example` là cấu hình chuẩn cho demo bằng OpenAI + pgvector. pgvector nằm trong cùng Supabase
Postgres nên không cần URL hoặc service riêng.

### API, Supabase và worker

| Biến | Giá trị mẫu | Ý nghĩa |
|---|---|---|
| `APP_ENV` | `development` | `development`, `test` hoặc `production` |
| `SUPABASE_URL` | bắt buộc | URL của Supabase project |
| `SUPABASE_PUBLISHABLE_KEY` | bắt buộc | Key dùng cùng user JWT cho API nghiệp vụ |
| `SUPABASE_SERVICE_ROLE_KEY` | bắt buộc cho worker/reconciliation/Enterprise answer commit | Server-only key để claim job, đọc Storage, ghi kết quả, gọi maintenance/repair RPC và commit answer/citation với actor user rõ ràng |
| `SUPABASE_JWT_AUDIENCE` | `authenticated` | Audience cần có trong access token |
| `CORS_ORIGINS` | localhost `5173` | Danh sách JSON các frontend origin |
| `INGESTION_WORKER_ENABLED` | `true` | Chạy worker nền cùng process FastAPI |
| `INGESTION_WORKER_CONCURRENCY` | `2` | Số worker lease job song song; tăng thận trọng theo quota OpenAI/DB |
| `INGESTION_WORKER_POLL_SECONDS` | `2` | Chu kỳ tìm job đang chờ |
| `INGESTION_WORKER_LEASE_SECONDS` | `1800` | Thời gian lease; worker gia hạn khi đang xử lý |

### Ingestion và extraction

| Biến | Giá trị mẫu | Ý nghĩa |
|---|---|---|
| `MAX_FILE_SIZE_BYTES` | `10485760` | Giới hạn cố định 10 MiB, khớp API, pipeline và Storage |
| `CHUNK_SIZE` | `600` | Kích thước chunk mục tiêu |
| `CHUNK_OVERLAP` | `0` | Không lặp nội dung giữa các child chunk |
| `CHUNKING_STRATEGY` | `parent_child_structure` | Child theo cấu trúc, parent giữ trọn section và dừng đúng ranh giới heading |
| `ADVANCED_EXTRACTION_ENABLED` | `true` | Bật Advanced Extraction |
| `EXTRACTION_QUALITY_MODE` | `rag` | Quality policy dành cho retrieval; `structured` nghiêm hơn |
| `MAX_EXTRACTION_PROVIDER_ATTEMPTS` | `1` | Số lần thử extraction provider |
| `OCR_ENABLED` | `false` | Tắt OCR trong happy path |

Các định dạng được nhận: PDF, DOCX, TXT, PPTX, XLSX, CSV, Markdown và HTML. PDF được kiểm tra
signature, Office file được kiểm tra cấu trúc ZIP và text file phải dùng UTF-8.

### Knowledge quality

| Biến | Giá trị mẫu | Ý nghĩa |
|---|---|---|
| `KNOWLEDGE_QUALITY_MODE` | `on` | `off`: legacy; `shadow`: detect/đo nhưng không đổi retrieval; `on`: safe exact reuse và policy canonical/version |
| `KNOWLEDGE_QUALITY_MAX_PROBE_CHUNKS` | `8` | Số chunk đại diện tối đa dùng để tìm candidate |
| `KNOWLEDGE_QUALITY_CANDIDATES_PER_PROBE` | `5` | Số neighbor tối đa cho mỗi probe |
| `KNOWLEDGE_QUALITY_CONFLICT_PROMPT_ENABLED` | `true` | Đưa structured conflict notice vào generation; không xóa phía nào |
| `STRUCTURED_FACT_MODE` | `off` | `off`: tắt; `shadow`: trích xuất/lưu/đo nhưng không dùng trong câu trả lời; `on`: ưu tiên exact fact evidence có scope/thời gian trước vector retrieval |

Fuzzy duplicate/version/conflict luôn cần review. `shadow` phải có cùng retrieval behavior với
`off`; chỉ chuyển sang `on` sau khi benchmark, migration, concurrency và RLS gates đều đạt.
Mode lúc enqueue được lưu bền trong job. Worker lấy mode an toàn hơn giữa enqueue-time và runtime
(`off < shadow < on`), nên rollback runtime có thể hạ cấp job đang chờ nhưng không bao giờ nâng cấp
job cũ. Database kiểm tra lại quy tắc này; exact reuse tự động chỉ chạy khi cả hai phía đều là `on`.
Repair attempt luôn chạy decision logic như `off`, bỏ qua duplicate/relation detection và
suppression; fingerprint sẵn có chỉ được tính lại để làm bằng chứng compare-and-set khi hoàn tất.

Dedup khác định dạng diễn ra bất đồng bộ sau extraction, không phải tại response upload ban đầu:
worker tạo `knowledge-document-identity-v2` từ prose và bảng có cấu trúc, rồi đánh dấu file sau là
bản trùng trước khi embedding khi identity đủ tin cậy. File có OCR/visual chưa biểu diễn hoặc bảng
PDF bị mất ranh giới ô chỉ được đưa vào hàng đợi review. Dữ liệu fingerprint v1 cần re-ingest để
tham gia so sánh v2; hai version không được so trực tiếp.

Sau chunking, worker tạo `knowledge-chunk-identity-v1` trước khi gọi embedding. SHA-256 strict
phát hiện exact chunk; SimHash-LSH chỉ lấy candidate gần giống, sau đó lexical Jaccard,
containment và structured claim checks mới phân loại near duplicate/version/conflict. Vector chỉ
được tái sử dụng khi strict text, embedding-text checksum và embedding model đều khớp. Near
duplicate và conflict không dùng chung vector: cả hai vẫn được embedding và lưu evidence để review.

`STRUCTURED_FACT_MODE` là rollout độc lập dành cho bảng nghiệp vụ lớn. Worker chuẩn hóa scope,
qualifier, effective time và provenance dòng/ô; tải candidate cũ theo identity/schema index; rồi diff
theo row key với độ phức tạp `O(n + m)`. `conflict_candidate`/`uncertain` cần review, còn nguồn ở hai
phía luôn được giữ. Nếu phân tích, ghi fact hoặc exact lookup lỗi, hệ thống ghi log và tiếp tục ingestion
hay hybrid/vector retrieval hiện có. Xem [kiến trúc structured facts](docs/architecture/structured-facts.md)
và chạy migration 16 sau migration 15 trước khi bật `shadow` hoặc `on`.

### OpenAI, pgvector và retrieval

| Biến | Giá trị mẫu | Ý nghĩa |
|---|---|---|
| `EMBEDDING_PROVIDER` | `openai` | Provider dùng cho web ingestion |
| `OPENAI_API_KEY` | bắt buộc | Dùng cho embedding và chat |
| `OPENAI_EMBEDDING_MODEL` | `text-embedding-3-small` | Tạo embedding 1536 chiều |
| `OPENAI_CHAT_MODEL` | `gpt-4o-mini` | Model generation |
| `OPENAI_TIMEOUT_SECONDS` | `60` | Timeout cho OpenAI embedding request |
| `CONTEXTUAL_ENRICHMENT_ENABLED` | `false` | Mac dinh dung deterministic document/section header; bat `true` chi cho thi nghiem LLM context |
| `CONTEXTUAL_ENRICHMENT_MODEL` | `gpt-4o-mini` | Model quyet dinh chunk co can bo sung retrieval context hay khong |
| `CONTEXTUAL_ENRICHMENT_DOCUMENT_MAX_CHARS` | `12000` | Gui whole document khi vua gioi han; neu khong, gui bounded global/local context package |
| `CONTEXTUAL_ENRICHMENT_MAX_CONTEXT_CHARS` | `600` | Gioi han context duoc prepend vao dense embedding |
| `CONTEXTUAL_ENRICHMENT_MAX_SEARCH_TERMS` | `0` | Bien tuong thich cu; v4 khong sinh generated search terms |
| `CONTEXTUAL_ENRICHMENT_STRICT` | `false` | `false` giu deterministic context khi LLM loi; `true` fail ingestion |
| `VECTOR_STORE_BACKEND` | `pgvector` | Lưu embedding trong `document_chunks` |
| `LLM_TIMEOUT_SECONDS` | `120` | Timeout cho generation |
| `GENERATION_ALLOW_OUTSIDE_KNOWLEDGE` | `false` | Giữ câu trả lời trong retrieved context |
| `RETRIEVAL_SPARSE_TOP_K` | `20` | Số candidate từ PostgreSQL FTS |
| `RETRIEVAL_DENSE_TOP_K` | `20` | Số candidate từ pgvector |
| `RETRIEVAL_FINAL_TOP_K` | `6` | Số chunk cuối đưa vào generation |
| `RETRIEVAL_RRF_K` | `60` | Hằng số RRF |
| `RETRIEVAL_MMR_LAMBDA` | `0.7` | Cân bằng relevance và diversity |

## OCR và quality gate

OCR là dependency tùy chọn:

```powershell
uv sync --extra ocr
```

Sau đó bật:

```dotenv
OCR_ENABLED=true
```

OCR chỉ được chọn trong Advanced Extraction khi đầu vào là PDF. Pipeline dùng page profiling
để quyết định từng trang nên parse native, OCR hay kết hợp hai cách.

### Langfuse observability

Backend có tracing Langfuse cho cả ingestion và chat RAG. Mặc định tracing bị tắt và toàn bộ
ứng dụng tiếp tục hoạt động bằng telemetry no-op. Để bật Langfuse Cloud hoặc một instance
self-hosted, cấu hình:

```dotenv
LANGFUSE_ENABLED=true
LANGFUSE_PUBLIC_KEY=pk-lf-...
LANGFUSE_SECRET_KEY=sk-lf-...
LANGFUSE_BASE_URL=https://cloud.langfuse.com
LANGFUSE_ENVIRONMENT=development
LANGFUSE_RELEASE=local
LANGFUSE_SAMPLE_RATE=1.0
LANGFUSE_CAPTURE_CONTENT=false
```

`LANGFUSE_CAPTURE_CONTENT=false` là mặc định an toàn: hệ thống vẫn gửi latency, model, token
usage, số lượng chunk, chunk/document id, retrieval score, số vòng agentic retrieval và lỗi,
nhưng che câu hỏi, nội dung tài liệu, prompt và câu trả lời. Chỉ bật giá trị này sau khi đã đánh
giá yêu cầu bảo mật dữ liệu.

When Langfuse is enabled, backend OpenAI clients are created through the Langfuse OpenAI wrapper
so provider calls capture model, streaming usage, latency and errors automatically. The telemetry
facade also configures export-time masking for those native spans, so prompt and response content
remain redacted unless `LANGFUSE_CAPTURE_CONTENT=true`.

Mỗi lượt chat dùng một trace xuyên suốt với `user_id` là Supabase user id và `session_id` là
conversation id. Trace chứa các observation cho chuẩn bị hội thoại, contextualization, adaptive
decision, từng retrieval round, sparse FTS, query embedding, Qdrant, RRF, MMR, sufficiency,
reformulation, OpenAI generation streaming, citation và ghi kết quả về Supabase. Ingestion dùng
trace riêng theo job/attempt, từ Storage download, checksum, extraction, chunking, embedding,
Qdrant đến transaction hoàn tất trong Supabase.

## Kiến trúc

### Luồng web hiện tại

```text
React SPA
  -> Supabase Auth
  -> FastAPI + user access token
  -> PostgREST / Supabase Storage
  -> PostgreSQL + owner RLS
```

API không dùng service-role key cho CRUD. PostgREST và Storage nhận publishable key cùng JWT
của user, vì vậy RLS vẫn là lớp kiểm soát quyền chính.

### Luồng Advanced Extraction

```text
DocumentSource
  -> validate file
  -> parser thường hoặc adaptive OCR
  -> quality gate
  -> Canonical IR v2
  -> layout và reading order
  -> structured tables
  -> provider verification
  -> multimodal artifact
  -> chunking
  -> embedding
  -> configured vector backend (pgvector hoặc Qdrant)
```

Nếu quality gate không cho index, pipeline dừng trước embedding với lỗi
`embedding_blocked_by_extraction_quality`. Cách xử lý này tránh đưa dữ liệu parse kém chất
lượng vào vector store.

Các phase layout, table và verification hỗ trợ các mode `LEGACY`, `SHADOW`, `ACTIVE`.
Multimodal mặc định ở mode `DISABLED`; pipeline vẫn tạo artifact rỗng an toàn thay vì tự động
gọi một visual provider bên ngoài.

### Luồng upload và ingestion

```text
API upload
  -> DocumentService
  -> Supabase metadata + object storage
  -> ingestion_jobs.pending + document.processing
  -> worker claim bằng service-role lease
  -> tải object và xác minh size/SHA-256
  -> Advanced Extraction
  -> embedding + stage generation nếu dùng Qdrant
  -> fenced completion transaction
  -> persisted completion_disposition
  -> publish hoặc xóa đúng external generation
  -> document_chunks + ingestion_jobs.succeeded + document.ready
```

Nếu worker dừng giữa chừng, job `running` được claim lại sau khi lease hết hạn. Việc hoàn tất
chunk, job và trạng thái document diễn ra trong cùng transaction Postgres. Qdrant point dùng
cùng UUID xác định với hàng chunk tương ứng và được fence thêm bằng ingestion generation.

## API đã có

Tất cả API nghiệp vụ bên dưới yêu cầu Bearer access token của Supabase:

| Method | Endpoint | Chức năng |
|---|---|---|
| `GET` | `/health/live` | Kiểm tra process |
| `GET` | `/health/ready` | Kiểm tra readiness |
| `GET` | `/debug/supabase-user` | Xem các claim an toàn trong development |
| `GET` | `/notebooks` | Liệt kê notebook |
| `POST` | `/notebooks` | Tạo notebook |
| `PATCH` | `/notebooks/{notebook_id}` | Sửa notebook |
| `DELETE` | `/notebooks/{notebook_id}` | Archive notebook |
| `GET` | `/notebooks/{notebook_id}/documents` | Liệt kê, lọc và phân trang document |
| `POST` | `/notebooks/{notebook_id}/documents` | Upload batch 1–20 file |
| `GET` | `/notebooks/{notebook_id}/documents/{document_id}/preview` | Preview PDF |
| `DELETE` | `/notebooks/{notebook_id}/documents/{document_id}` | Hủy xử lý và xóa document |
| `GET` | `/notebooks/{notebook_id}/quality/relations` | Hàng đợi/lịch sử duplicate, version và conflict |
| `GET` | `/notebooks/{notebook_id}/quality/relations/audit` | Audit bất biến, có thể lọc theo relation ID |
| `POST` | `/notebooks/{notebook_id}/quality/relations/{relation_id}/resolve` | Quyết định relation có optimistic concurrency và audit |
| `POST` | `/notebooks/{notebook_id}/quality/relations/{relation_id}/revert` | Revert decision mới nhất bằng `expected_updated_at` và `reason` |
| `GET` | `/notebooks/{notebook_id}/structured-facts/relations` | Hàng đợi conflict/uncertain cấp claim-row |
| `GET` | `/notebooks/{notebook_id}/structured-facts/relations/{relation_id}/evidence` | Bằng chứng snapshot, claim và row/cell cả hai phía |
| `POST` | `/notebooks/{notebook_id}/structured-facts/relations/{relation_id}/resolve` | Resolve claim relation với reason, audit và optimistic concurrency |
| `POST` | `/chat` | Chat response không streaming |
| `POST` | `/chat/stream` | Chat qua SSE kèm citation |
| `GET` | `/profile` | Lấy profile |
| `PATCH` | `/profile` | Cập nhật profile |
| `GET` | `/admin/stats/users` | User stats dành cho admin |
| `GET` | `/admin/stats/auth-events` | Auth-event stats dành cho admin |
| `GET` | `/admin/audit-log` | Audit log dành cho admin |
| `GET` | `/admin/users/{user_id}/notebooks` | Notebook của user dành cho admin |

Batch upload trả kết quả riêng cho từng file, vì vậy một file lỗi không làm hỏng toàn bộ batch.
Revert được định danh bằng `relation_id` trên path; backend tự tìm audit event mới nhất còn hiệu
lực. Audit ID không phải input của API/RPC.

## Reconciliation vận hành

Dry-run inventory là mặc định:

```powershell
python -m scripts.reconcile_knowledge_quality
```

Hai hành động mutate phải chạy riêng, dùng service-role key, `--reason` không rỗng và một
`--output` JSON audit artifact mới:

```powershell
python -m scripts.reconcile_knowledge_quality --delete-orphans `
  --reason "Verified Postgres-authoritative orphan cleanup" `
  --output artifacts\knowledge-quality-orphan-cleanup.json

python -m scripts.reconcile_knowledge_quality --requeue-repairs `
  --reason "Restore derived vectors from verified source objects" `
  --output artifacts\knowledge-quality-repairs.json
```

`--delete-orphans` chỉ áp dụng cho Qdrant: CLI giữ database maintenance lease bằng heartbeat,
rescan dưới lease, recheck Postgres và dùng point ID + payload CAS trước khi xóa. Điểm thiếu
identity/generation hoặc đã thay đổi chỉ được báo cáo. `--requeue-repairs` dùng RPC service-role
idempotent, fence theo timestamp/content/fingerprint/lineage và đưa việc sửa qua worker bình
thường; không ghi vector hoặc lineage trực tiếp. Xem quy trình đầy đủ trong
[runbook knowledge quality](docs/operations/knowledge-quality-runbook.md).

## Cấu trúc repo

```text
.
|-- frontend/                  React 19, Vite, Tailwind CSS, Zustand
|-- app/
|   |-- api/                   FastAPI routers và dependencies
|   |-- auth/                  Supabase JWT authentication
|   |-- notebooks/             Notebook domain/application/adapters
|   |-- documents/             Upload, Storage và document lifecycle
|   |-- ingestion/             Durable job worker
|   |-- knowledge_quality/     Identity, duplicate/version/conflict và review
|   |-- retrieval/             Sparse FTS, dense, fusion và reranking
|   |-- chat/                  Generation, streaming và citations
|   `-- pipeline/              Extraction, chunking, embedding, vector store
|-- supabase/migrations/       Schema, RLS, Storage và pgvector RPC
|-- tests/                     Unit, integration, contract, end-to-end
|-- docs/architecture/         Tài liệu kiến trúc chi tiết
`-- main.py                    Uvicorn entry point
```

Các entry point nên đọc trước:

- API composition: `app/api/main.py`
- Upload service: `app/documents/application/services.py`
- Worker runtime: `app/ingestion/application/runtime.py`
- Ingestion composition: `app/pipeline/bootstrap/composition.py`
- Indexing pipeline: `app/pipeline/indexing/application/pipeline.py`
- Advanced Extraction: `app/pipeline/documents/application/extraction_pipeline.py`

Tài liệu chi tiết:

- [Advanced Extraction](docs/architecture/advanced-extraction.md)
- [Ingestion đến embedding](docs/architecture/ingestion-to-embedding.md)
- [Kiến trúc knowledge quality](docs/architecture/knowledge-quality.md)
- [Runbook knowledge quality](docs/operations/knowledge-quality-runbook.md)
- [Migration 08/09](docs/migrations/08-09-knowledge-quality.md)
- [Contextual retrieval](docs/architecture/contextual-retrieval.md)
- [Rollback và reversal](docs/operations/knowledge-quality-rollback.md)
- [Enterprise Knowledge runbook](docs/operations/enterprise-knowledge-runbook.md)
- [Enterprise release checklist](docs/operations/enterprise-release-checklist.md)

## Kiểm tra chất lượng

Backend:

```powershell
uv run pytest
uv run ruff check .
uv run mypy
uv run python -m tests.evaluation.knowledge_quality_benchmark
```

Frontend:

```powershell
Set-Location frontend
npm run build
npm audit --omit=dev
```

Lệnh benchmark tạo report JSON/Markdown versioned trong `tests/evaluation/reports/` và trả exit
code khác `0` nếu một safety/quality gate không đạt. Dataset v1 là regression set tiếng Việt đã
gắn nhãn; vẫn cần benchmark bổ sung trên tài liệu thật được dự án adjudicate trước production.

Frontend chưa có `npm test` script; `npm run build` và toàn bộ backend gates phải chạy lại từ đúng
source revision trước mỗi release.

## Giới hạn đã biết

- Import URL/text có lời gọi từ frontend nhưng backend chưa cung cấp endpoint tương ứng.
- OCR là experimental và PDF scan phức tạp có thể bị quality gate chặn sau thời gian xử lý dài.
- `ruff` và strict `mypy` vẫn còn technical debt cần xử lý trước khi dùng làm release gate.
- Frontend production build có cảnh báo main JavaScript chunk lớn hơn 500 kB.
- `react-router-dom` được ghim ở bản phát hành mới nhất `7.18.2`. `npm audit` hiện vẫn gắn cờ
  GHSA-qwww-vcr4-c8h2 cho chế độ React Server Components; frontend này chỉ dùng
  `BrowserRouter` phía client và không có RSC/action server nên đường khai thác đó không được bật.
  Vẫn phải nâng ngay khi npm phát hành bản vá (advisory hiện yêu cầu `8.3.0`, nhưng phiên bản đó
  chưa tồn tại trên npm tại lần kiểm tra ngày 2026-07-30).
- Worker đang chạy trong cùng process FastAPI; chưa tách thành deployment riêng.
- Dataset knowledge-quality v1 là deterministic regression set, chưa thay thế benchmark trên dữ
  liệu dự án có human adjudication.

## Troubleshooting

### Frontend báo thiếu Supabase variables

Kiểm tra `frontend/.env.local` có `VITE_SUPABASE_URL`,
`VITE_SUPABASE_PUBLISHABLE_KEY` và `VITE_API_URL`, rồi khởi động lại Vite.

### API trả `502` hoặc `503`

Kiểm tra Supabase URL/key, các migration, network và user access token. Backend phải được chạy từ thư
mục gốc để đọc đúng `.env`.

### Document đứng ở `processing`

Kiểm tra:

```dotenv
INGESTION_WORKER_ENABLED=true
SUPABASE_SERVICE_ROLE_KEY=<non-empty>
EMBEDDING_PROVIDER=openai
OPENAI_API_KEY=<non-empty>
OPENAI_EMBEDDING_MODEL=text-embedding-3-small
VECTOR_STORE_BACKEND=pgvector
```

Sau đó xem backend log và trạng thái `ingestion_jobs`. Worker cần đọc private Storage, claim lease,
gọi OpenAI và ghi chunks vào Supabase.

### Document chuyển sang `failed`

Xem `ingestion_jobs.error_code` và backend log. Nếu lỗi là
`embedding_blocked_by_extraction_quality`, extraction đã chạy nhưng quality gate không cho index;
thử native PDF rõ chữ trước khi điều chỉnh quality policy hoặc OCR.

### Chat không trả lời hoặc hết timeout

Kiểm tra document đã ở `ready`, OpenAI key/model, pgvector migration `06_pgvector_search.sql` và
`LLM_TIMEOUT_SECONDS`. Giữ câu hỏi demo ngắn, cụ thể và có đáp án trong tài liệu.
