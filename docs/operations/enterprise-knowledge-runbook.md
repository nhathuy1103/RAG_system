# Enterprise Knowledge RAG — Runbook triển khai

Runbook này áp dụng cho lớp Enterprise bổ sung trên nền ứng dụng notebook hiện có.
Các bảng legacy được giữ để rollout theo kiểu expand/cutover; logical document mới dùng
`knowledge_documents`, `document_versions`, `source_files` và `knowledge_chunks`.

> Trạng thái xác minh: test tĩnh/contract trong repository không thay thế việc chạy migration,
> RLS và Storage policy trên Supabase thật. Mọi release production phải hoàn thành checklist
> staging clone ở mục 7; tài liệu này không tuyên bố môi trường live đã được kiểm thử.

## 1. Phạm vi triển khai

- IAM/RBAC: user profile, role, functional permission, group, department và membership.
- Document governance: source file bất biến, logical document, version, review, publish,
  archive, ACL và giải thích nguồn quyền hiệu lực theo User/Role/Group/Department.
- Upload khởi tạo: file + `SourceFile + Document + v1 + ProcessingJob`, có bảo vệ trùng
  SHA-256 và cơ chế dọn object Storage khi transaction database thất bại.
- Processing: queue theo document version, lease/claim/retry, danh sách job, stage history
  và error history.
- RAG: search ACL-aware, sufficiency gate, controlled no-answer, citation gắn chính xác
  document/version/chunk và lưu answer + citation trong một transaction tin cậy.
- Operations: audit log, analytics, feedback, answer report và giao diện employee/admin.
- Corporate identity guard: allowlist domain email ở database và cờ bật/tắt self-signup ở UI.

## 2. Triển khai database

Với project mới, chạy migration `01` đến `23` đúng thứ tự. Chỉ dùng
`supabase/migrations/RESET_AND_REBUILD.sql` trên môi trường disposable: script này xóa dữ liệu
ứng dụng rồi dựng lại đủ schema 01–23; `auth.users` và object Storage không bị xóa nhưng có thể
trở thành không còn được tham chiếu.

Với project đang có dữ liệu:

1. Backup database và Storage metadata; tạo clone/staging từ backup.
2. Chạy migration `17_enterprise_iam.sql` đến
   `23_enterprise_workflow_completion.sql` trên clone theo đúng thứ tự.
3. Xác nhận PostgREST đã reload schema, trigger trên `auth.users` tồn tại và bucket private
   `knowledge-source-files` đã được tạo.
4. Chạy toàn bộ kiểm thử live/RLS ở mục 7 bằng các tài khoản độc lập.
5. Ghi lại kết quả, người duyệt và phương án rollback. Chỉ khi tất cả gate đạt mới áp dụng cùng
   chuỗi migration lên production.

Migration 17 seed role `ADMIN`, `EMPLOYEE`, `DOCUMENT_REVIEWER` và các functional permission
nền tảng. User legacy có `profiles.role = 'admin'` được map sang `ADMIN`; user còn lại được map
sang `EMPLOYEE`. Migration 23 bổ sung và gán cho `ADMIN`:

| Permission | Phạm vi |
|---|---|
| `VIEW_AUDIT` | Đọc audit/governance log; đã có từ migration 17 |
| `VIEW_ANALYTICS` | Đọc số liệu tổng hợp Enterprise |
| `MANAGE_REPORT` | Resolve hoặc dismiss answer report |

Ba quyền này độc lập. Không dùng `VIEW_AUDIT` như quyền thay thế cho analytics hoặc mutation
report. Các role tùy chỉnh phải được gán từng permission cần thiết qua `role_permissions`.

### Đồng bộ `RESET_AND_REBUILD.sql`

Không sửa bằng tay phần canonical sau marker `-- Extensions required by the schema.`. Sau mọi
thay đổi migration, chạy đúng lệnh sau từ thư mục gốc:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\regenerate_enterprise_reset.ps1
python -m pytest -q tests\contract\test_enterprise_workflow_completion.py
```

Script nối nguyên văn các migration `01_*.sql` đến migration mới nhất theo thứ tự tên file,
giữ preamble phá huỷ và ghi UTF-8 không BOM. Contract test xác nhận phần canonical trong reset
khớp chính xác và đúng thứ tự. File reset không phải rollback và không được chạy trên database
có dữ liệu cần giữ.

## 3. Cấu hình runtime và danh tính doanh nghiệp

Backend cần các biến trong `.env.example`, tối thiểu là Supabase URL/publishable key,
`SUPABASE_SERVICE_ROLE_KEY`, OpenAI API key, `INGESTION_WORKER_ENABLED=true` và
`VECTOR_STORE_BACKEND=pgvector`. Service-role key chỉ được cấp cho backend/worker; không đưa vào
bundle frontend, log, error response hoặc công cụ analytics phía client.

Đặt các biến sau trong `frontend/.env.local` trước khi chạy hoặc build Vite:

```dotenv
VITE_SUPABASE_URL=https://<project-ref>.supabase.co
VITE_SUPABASE_PUBLISHABLE_KEY=<publishable-key>
VITE_API_URL=http://127.0.0.1:8000
VITE_ENTERPRISE_KB_ENABLED=true
VITE_SELF_SIGNUP_ENABLED=false
VITE_COMPANY_EMAIL_DOMAINS=company.example,subsidiary.example
```

- `VITE_ENTERPRISE_KB_ENABLED=false` ẩn/chặn các route Enterprise ở frontend để rollback UI;
  build lại frontend sau khi đổi cờ.
- `VITE_SELF_SIGNUP_ENABLED=false` là mặc định khuyến nghị cho production dùng invite/SSO.
- `VITE_COMPANY_EMAIL_DOMAINS` là danh sách domain chữ thường, phân tách bằng dấu phẩy; nó chỉ
  kiểm tra UX khi self-signup được bật, không phải security boundary.
- Frontend chỉ đọc biến `VITE_*` tại thời điểm build. Phải build/deploy lại sau khi đổi.

Security boundary cho domain nằm ở migration 23. Sau khi migration chạy, cấu hình allowlist bằng
SQL Editor hoặc kênh quản trị giữ service role:

```sql
insert into public.enterprise_allowed_email_domains (domain, status)
values
    ('company.example', 'ACTIVE'),
    ('subsidiary.example', 'ACTIVE')
on conflict (domain) do update set status = excluded.status;
```

Khi bảng có ít nhất một domain `ACTIVE`, trigger `auth_users_enforce_enterprise_email_domain`
fail-closed cho cả insert và đổi email trong `auth.users`. Khi bảng không có domain `ACTIVE`,
trigger cố ý không chặn để local development hoặc IdP bên ngoài tiếp tục hoạt động. Vì vậy:

1. Production dùng email/password phải cấu hình ít nhất một domain `ACTIVE` trước khi mở signup.
2. Domain ở database và `VITE_COMPANY_EMAIL_DOMAINS` phải đồng nhất.
3. Với SAML/OIDC/SSO, vẫn phải cấu hình IdP và đồng bộ trạng thái account ở Supabase/IdP; allowlist
   domain không chứng minh tài khoản đang hoạt động và không thay thế IdP.
4. Kiểm tra cả email ngoài domain, email đổi từ hợp lệ sang không hợp lệ, và luồng invite/admin.

Khởi động backend bằng `uv run python main.py`, sau đó chạy `npm run dev` trong `frontend`.
Swagger ở `/docs`; contract Enterprise dùng prefix `/api/v1` và lỗi chuẩn
`{"error":{"code","message","trace_id"}}`.

## 4. Workflow tài liệu và processing

### Upload khởi tạo atomic

Happy path tạo tài liệu đầu tiên là `POST /api/v1/documents/upload` với multipart form gồm `file`,
`title` và các field tùy chọn `description`, `document_type`, `category`, `metadata_json`,
`change_summary`, `effective_date`. Response trả cùng lúc:

- `source_file`;
- logical `document`;
- `version` số 1;
- `processing_job` trạng thái `PENDING`.

API upload object vào private Storage trước, sau đó gọi RPC
`create_enterprise_document_upload`. RPC đăng ký `SourceFile + Document + v1 + ProcessingJob`
trong một transaction database, tự cấp ACL khởi tạo cho người upload và dùng advisory lock theo
SHA-256 để từ chối file byte-identical đã được đăng ký. Nếu RPC rollback, backend thực hiện
compensating delete object vừa upload. Cần giám sát cảnh báo cleanup vì lỗi Storage lúc dọn có thể
để lại orphan object cần xử lý thủ công.

`POST /api/v1/source-files` và `POST /api/v1/documents/{document_id}/versions` vẫn phục vụ luồng
tạo version tiếp theo/điều tra kỹ thuật; portal phải ưu tiên endpoint atomic cho v1.

### Theo dõi và retry processing

- `GET /api/v1/processing-jobs?document_id=<uuid>&document_version_id=<uuid>&status=<status>`:
  phân trang và lọc job theo document/version/status.
- `GET /api/v1/processing-jobs/{job_id}`: trả job cùng `stage_history` và `errors` đã lọc thông
  tin an toàn.
- `POST /api/v1/processing-jobs/{job_id}/retry`: tạo attempt `REPROCESS` mới theo invariant
  quyền/lifecycle; không ghi đè attempt cũ.

Worker phải đưa job qua `PENDING → RUNNING → SUCCEEDED` hoặc terminal failure, cập nhật heartbeat,
lease và stage history. Khi job lỗi, dùng detail endpoint để xác định `error_code`, `safe_message`
và `retryable`; không yêu cầu quản trị viên nhập job UUID thủ công nếu đã chọn document/version.

Reviewer/publisher dùng `GET /api/v1/document-versions/{version_id}/review-context` để mở đúng
candidate source, extracted chunks, latest processing job, stage history và lỗi an toàn trước khi ra
quyết định. Endpoint này vẫn kiểm tra đồng thời functional permission và document ACL; không mở raw
chunk table trực tiếp cho client.

Khi sửa metadata, `PATCH /api/v1/documents/{document_id}` bắt buộc gửi `expected_updated_at` lấy từ
bản đọc gần nhất. Một stale write trả conflict và client phải tải lại document trước khi thử lại;
không tự động ghi đè thay đổi của quản trị viên khác.

`POST /api/v1/documents/{document_id}/permissions/test` trả cả `allowed` và `sources`. Nguồn có
dạng `USER:<id>:<permission>`, `ROLE:<code>:<permission>`, `GROUP:<code>:<permission>` hoặc
`DEPARTMENT:<code>:<permission>`; xem quyền của người khác yêu cầu đồng thời functional permission
`MANAGE_ACCESS_POLICY` và ACL `MANAGE_PERMISSION` trên đúng document.

## 5. Invariant bảo mật bắt buộc

Một chunk chỉ được retrieval khi đồng thời thỏa:

```text
document.status = PUBLISHED
AND version.status = ACTIVE
AND document.current_version_id = version.id
AND actor có functional permission ASK_KNOWLEDGE
AND actor có document permission READ còn hiệu lực
```

Download file gốc yêu cầu `DOWNLOAD`; quản trị source lịch sử yêu cầu functional/resource
permission tương ứng. User/profile/role bị `DISABLED` hoặc `LOCKED` phải mất quyền hiệu lực qua
kiểm tra RBAC hiện tại, không dựa vào claim role legacy.

Commit answer là trusted backend operation:

- RPC `complete_enterprise_answer` chỉ grant cho `service_role`, không grant cho `authenticated`;
- backend truyền `p_actor_user_id` là user thực, không giả actor service role;
- RPC kiểm tra lại conversation ownership, `ASK_KNOWLEDGE`, lifecycle và ACL hiện tại ngay trước
  khi lưu answer/citation để đóng race archive/republish/revoke;
- audit được ghi với actor user thực;
- thiếu `SUPABASE_SERVICE_ROLE_KEY` phải fail với lỗi cấu hình, không fallback sang client JWT hoặc
  lưu answer không có citation.

Citation sai document/version/chunk/quote, trùng thứ tự hoặc nằm ngoài evidence được phép phải bị
từ chối và transaction không lưu một phần. Khi quyền nguồn bị thu hồi hoặc document bị archive,
search không trả nguồn đó và conversation lịch sử phải lọc/redact evidence không còn được phép.

## 6. Kiểm thử tại repository

Từ thư mục gốc:

```powershell
New-Item -ItemType Directory -Force .tmp\pytest | Out-Null
$env:LANGFUSE_ENABLED='false'
$env:TEMP=(Resolve-Path '.tmp\pytest')
$env:TMP=$env:TEMP
python -m pytest -q
python -m ruff check app tests

Set-Location frontend
npm run build
```

Nếu Windows sandbox chặn Node truy cập profile cha, chạy build trong terminal được cấp quyền phù
hợp. Không bỏ qua build chỉ vì lỗi sandbox. SQL contract test chỉ kiểm tra cấu trúc và invariant
tĩnh; kết quả pass không chứng minh migration compile/chạy đúng trên Supabase, không chứng minh
RLS theo JWT thật và không chứng minh Storage policy.

## 7. Checklist bắt buộc trên Supabase staging clone

Tạo ít nhất bốn danh tính độc lập: `ADMIN`, reviewer, employee được cấp ACL và employee không có
ACL. Dùng user JWT thật khi gọi REST/API; chỉ backend/worker giữ service-role key.

- [ ] Restore clone từ backup gần production; ghi lại project ref, thời gian và snapshot ID.
- [ ] Chạy migration 17–23 theo thứ tự, không dùng reset; kiểm tra không có warning/error bị bỏ qua.
- [ ] Xác nhận function, trigger, RLS/force-RLS và private bucket/policy đã reload qua PostgREST.
- [ ] Với từng profile `ACTIVE`, `LOCKED`, `DISABLED`, xác nhận `/api/v1/me` và route chức năng
  allow/deny đúng; không dựa vào `profiles.role = admin` legacy.
- [ ] Xác nhận `VIEW_AUDIT`, `VIEW_ANALYTICS`, `MANAGE_REPORT` độc lập bằng ba negative test.
- [ ] Cấu hình domain `ACTIVE`; thử signup/invite/đổi email với domain hợp lệ và không hợp lệ.
- [ ] Gọi upload atomic; xác nhận đúng một source/document/v1/job và ACL khởi tạo. Upload lại cùng
  bytes phải bị từ chối, không tạo document/version/job mới và không để object mồ côi.
- [ ] Quan sát job qua list/detail API; xác nhận stage/error history, lease, terminal state và retry
  tạo attempt mới có liên kết lịch sử.
- [ ] Review/publish; xác nhận chỉ một version `ACTIVE` và `current_version_id` trỏ đúng version.
- [ ] Không `READ`: list/search/raw table/RPC/chat đều fail-closed hoặc controlled no-answer.
- [ ] Có `READ` nhưng không `DOWNLOAD`: retrieval được, signed source URL bị từ chối.
- [ ] Có `READ + DOWNLOAD`: retrieval và signed source URL đúng document/version.
- [ ] Thu hồi `READ`, republish hoặc archive giữa retrieval và commit answer; trusted commit phải
  rollback/fail-closed, không lưu answer/citation trái quyền.
- [ ] Thu hồi `READ`/archive sau khi đã trả lời; search và conversation lịch sử không làm lộ nguồn.
- [ ] Thử gọi `complete_enterprise_answer` bằng role `authenticated`: phải bị từ chối. Gọi qua
  backend trusted path phải lưu actor user thực trong audit.
- [ ] Gửi feedback/report; xác nhận chỉ `MANAGE_REPORT` mutation report, chỉ `VIEW_ANALYTICS` đọc
  analytics, và audit append-only.
- [ ] Kiểm thử truy cập trực tiếp các bảng/RPC/Storage bằng JWT của từng user, không chỉ qua UI.
- [ ] Chạy worker thật với một file hỗ trợ; xác nhận chunks gắn đúng version và retrieval chỉ lấy
  current published version.
- [ ] Lưu evidence đã redacted: request/response, query kiểm tra, log migration, log worker và người
  phê duyệt. Không lưu token hoặc service-role key.

Chỉ đánh dấu gate này hoàn tất khi đã thực sự chạy trên clone. Nếu chưa có Supabase staging/live,
trạng thái release phải là **chưa xác minh live**, dù toàn bộ test trong repository đã pass.

## 8. Rollback và go/no-go

- Không dùng `RESET_AND_REBUILD.sql` để rollback.
- Nếu lỗi UI, đặt `VITE_ENTERPRISE_KB_ENABLED=false`, build và deploy lại frontend; API legacy giữ
  nguyên. Cờ này không rollback database.
- Nếu lỗi self-signup, đặt `VITE_SELF_SIGNUP_ENABLED=false`, build lại và tắt signup provider nếu
  chính sách yêu cầu; không xóa allowlist để “sửa nhanh” trên production.
- Nếu lỗi worker Enterprise, dừng worker, giữ job/source/version để điều tra và retry; không xóa
  source file đã được version tham chiếu.
- Nếu lỗi retrieval/generation, chặn route Enterprise ở gateway hoặc thu hồi `ASK_KNOWLEDGE`;
  không nới RLS và không chuyển sang closed-book answer.
- Nếu migration production thất bại, dừng rollout và phục hồi từ backup theo runbook hạ tầng.
  Kiểm tra lại trên clone mới trước lần thử tiếp theo.

Quyết định go chỉ hợp lệ khi test repository, build frontend, migration clone, live RLS/Storage
matrix, duplicate/cleanup, trusted answer commit và rollback rehearsal đều có evidence đạt.
