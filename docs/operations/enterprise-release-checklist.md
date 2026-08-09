# Enterprise Knowledge RAG — Release checklist

Checklist này là mẫu evidence cho một lần release. Dấu `[ ]` có nghĩa là **chưa xác minh**;
không đổi thành `[x]` nếu chỉ đọc code hoặc chạy contract test tĩnh.

## 1. Thông tin release

| Trường | Giá trị |
|---|---|
| Release/commit | |
| Người triển khai | |
| Người phê duyệt | |
| Staging project ref | |
| Backup/snapshot ID | |
| Thời gian bắt đầu/kết thúc | |
| Migration áp dụng | `17`–`23` hoặc `23` tùy baseline đã xác nhận |

## 2. Artifact và cấu hình

- [ ] `supabase/migrations/23_enterprise_workflow_completion.sql` có trong release artifact.
- [ ] `RESET_AND_REBUILD.sql` đã được sinh lại từ canonical migrations bằng:

  ```powershell
  powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\regenerate_enterprise_reset.ps1
  ```

- [ ] Contract exact-order của reset đã pass; không chỉnh phần canonical bằng tay.
- [ ] Backend có `SUPABASE_SERVICE_ROLE_KEY`; key không xuất hiện ở frontend artifact/log.
- [ ] `VITE_ENTERPRISE_KB_ENABLED` được đặt theo quyết định rollout.
- [ ] `VITE_SELF_SIGNUP_ENABLED=false`, trừ khi self-signup đã được security phê duyệt.
- [ ] `VITE_COMPANY_EMAIL_DOMAINS` khớp các dòng domain `ACTIVE` trong
  `enterprise_allowed_email_domains`.
- [ ] Frontend đã được build lại sau mọi thay đổi biến `VITE_*`.

## 3. Quality gate trong repository

Chạy từ thư mục gốc và đính kèm output/CI URL:

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

- [ ] Pytest: kết quả/URL ____________________
- [ ] Ruff: kết quả/URL ____________________
- [ ] Frontend production build: kết quả/URL ____________________
- [ ] OpenAPI diff đã được review: evidence ____________________

Các mục này không thay thế checklist Supabase thật bên dưới.

## 4. Migration và live RLS trên staging clone

- [ ] Restore clone từ backup và xác nhận baseline migration trước khi apply.
- [ ] Migration đến 23 chạy thành công; PostgREST schema cache đã reload.
- [ ] RLS + force RLS và Storage policy được thử bằng JWT thật của admin/reviewer/two employees.
- [ ] Profile `LOCKED`/`DISABLED` không còn functional access.
- [ ] `VIEW_AUDIT`, `VIEW_ANALYTICS`, `MANAGE_REPORT` được kiểm tra độc lập cả allow và deny.
- [ ] Domain allowlist chặn insert/update email ngoài domain khi có domain `ACTIVE`.
- [ ] Bảng domain rỗng chỉ được chấp nhận cho local/IdP flow đã ghi rõ; không vô tình để trống ở
  production email/password.
- [ ] Upload `POST /api/v1/documents/upload` tạo atomic source/document/v1/job.
- [ ] Upload lại byte-identical bị từ chối và không để DB row/object Storage mồ côi.
- [ ] Processing list/detail hiển thị stage/error history; retry tạo attempt mới.
- [ ] Reviewer/publisher mở được đúng source và review context; người không đủ hai lớp quyền bị từ chối.
- [ ] Hai admin sửa cùng document tạo optimistic-concurrency conflict thay vì silent overwrite.
- [ ] IAM UI xem/gán/gỡ role permission và user membership đúng theo từng functional permission.
- [ ] Publish chỉ để một current `ACTIVE` version.
- [ ] Retrieval matrix `ASK_KNOWLEDGE + READ`; source download tách riêng bằng `DOWNLOAD`.
- [ ] Revoke/archive/republish làm retrieval và citation history fail-closed.
- [ ] RPC commit answer từ role `authenticated` bị từ chối.
- [ ] Trusted backend commit dùng service role nhưng audit ghi actor user thực.
- [ ] Race revoke/archive giữa retrieval và commit không lưu answer/citation trái quyền.
- [ ] Audit append-only; report mutation chỉ qua `MANAGE_REPORT`.

Evidence staging clone: ________________________________________________

## 5. Quan sát, rollback và quyết định

- [ ] Dashboard/log không thu thập source text, prompt, token hoặc service-role key ngoài chính sách.
- [ ] Alert cho failed job, orphan cleanup warning, answer commit failure và domain rejection hoạt
  động.
- [ ] Đã rehearsal rollback UI bằng `VITE_ENTERPRISE_KB_ENABLED=false`.
- [ ] Đã xác nhận dừng worker không làm mất job/source/version.
- [ ] Backup restore procedure đã được kiểm tra; không dùng reset script làm rollback.

Quyết định: `[ ] GO` / `[ ] NO-GO`

Lý do và risk được chấp nhận:

________________________________________________________________________

Nếu mục live RLS/staging chưa hoàn tất, quyết định mặc định là **NO-GO / chưa xác minh live**.
