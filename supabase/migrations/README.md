# database/

SQL tham khảo, đối chiếu 1:1 với schema thật trong `supabase/migrations/` (nguồn
sự thật vẫn là thư mục đó — các file ở đây để đọc/tra cứu riêng từng phần, và
để có 1 script rebuild toàn bộ theo đúng mô tả trong
`research/feature/common_Plan.html`).

## Thứ tự đọc / chạy nếu build từ đầu

1. `01_extensions.sql` — bật extension cần thiết (`pgcrypto`, `vector`).
2. `02_tables.sql` — toàn bộ `CREATE TABLE` (bao gồm `profiles` mới và cột
   `document_chunks.embedding vector(1536)` mới cho pgvector).
3. `03_functions_triggers.sql` — trigger `updated_at`, function hàng đợi
   ingestion (`enqueue/claim/renew/complete/fail_ingestion_job`,
   `prepare_document_deletion`), trigger tự tạo `profiles` khi có user mới.
4. `04_rls_policies.sql` — bật RLS + toàn bộ policy.
5. `05_storage.sql` — bucket `documents` + policy `storage.objects`.
6. `06_pgvector_search.sql` — RPC `match_document_chunks` (dense retrieval qua pgvector, thay `QdrantVectorIndex.query`).
7. `07_admin_stats.sql` — RPC `admin_user_count` / `admin_daily_auth_events` (đọc `auth.users`/`auth.audit_log_entries`, PostgREST không lộ 2 bảng này trực tiếp nên phải qua `SECURITY DEFINER` function, chỉ `service_role` gọi được). **Trước khi tin số liệu**: chạy thử `select payload->>'action', count(*) from auth.audit_log_entries group by 1;` trên project thật để xác nhận đúng tên action GoTrue đang dùng (`login`/`user_signedup`) — comment trong file đã nhắc lại việc này.
8. `08_knowledge_quality.sql` — fingerprint strict/loose, atomic exact dedup,
   canonical/version lineage, relation review queue, append-only audit, fenced
   ingestion completion và guarded resolution RPC.
9. `09_knowledge_quality_hardening.sql` — owner/notebook-scoped dense RPC,
   idempotent enqueue, normalized canonical/version-family concurrency
   constraints, complete resolution snapshots và guarded reversal RPC.
10. `10_chunk_preembedding_dedup.sql` — bounded owner/notebook-scoped
    SHA-256 and 8-band SimHash-LSH candidate lookup for chunk checks before
    embedding. Exact vector reuse is verified and decided in application code.
11. `11_contextual_metadata_fts.sql` — generated weighted `tsvector`, GIN index,
    and owner/notebook-scoped PostgreSQL full-text ranking RPC.
12. `12_llm_contextual_retrieval.sql` - add validated per-chunk LLM context and
    search terms to the weighted PostgreSQL full-text index.
13. `13_template_scope_conflict.sql` - add the persisted `template_variant`
    relation and extend the fenced completion whitelist without replacing its
    existing audit or lease semantics.
14. `14_compact_chunk_metadata.sql` - remove canonical text that exactly
    duplicates chunk content and omit empty provenance/authority objects.
15. `15_structured_retrieval_filters.sql` - backfill/index the approved
    pre-retrieval metadata fields and apply the same fail-closed conditions to
    pgvector and PostgreSQL FTS RPCs.
16. `16_structured_fact_layer.sql` - add owner/notebook-scoped table snapshots,
    row/cell-provenanced structured claims, directional claim relations,
    append-only review audit, atomic worker replacement, exact temporal lookup,
    and indexed candidate loading for deterministic table diff.
17. `17_enterprise_iam.sql` — mở rộng identity thành RBAC doanh nghiệp: user,
    role, functional permission, group, department và access subject.
18. `18_enterprise_knowledge_acl.sql` — thêm logical document, immutable source
    file, version/review/publication history và ACL theo user/role/group/department.
19. `19_enterprise_processing_rag.sql` — thêm hàng đợi xử lý theo version, stage/error
    history, chunk gắn version, conversation, citation, feedback, report và audit.
20. `20_enterprise_operations.sql` — các RPC giao dịch cho lifecycle, ACL, retry,
    conversation và governance analytics.
21. `21_enterprise_security_retrieval.sql` — RLS và retrieval fail-closed: chỉ
    `PUBLISHED + ACTIVE + current version + ASK_KNOWLEDGE + READ` mới được tìm thấy.
22. `22_enterprise_answer_ingestion_bridge.sql` — bucket source riêng, answer +
    citation atomic qua trusted service role, kiểm tra lại actor/lifecycle/ACL khi commit
    và bridge worker ingestion trực tiếp.
23. `23_enterprise_workflow_completion.sql` — hoàn tất workflow production: upload
    khởi tạo atomic `SourceFile + Document + v1 + ProcessingJob`, chặn trùng file theo
    SHA-256, giải thích nguồn ACL hiệu lực, tách quyền `VIEW_ANALYTICS`/
    `MANAGE_REPORT`, và allowlist domain email công ty có trigger trên `auth.users`.
24. `24_legacy_notebook_enterprise_bridge.sql` — tạo mapping Enterprise
    draft/source/version trong cùng transaction enqueue để màn hình Notebook legacy
    tiếp tục upload được sau cutover.
25. `25_canonical_metadata_parent_projection.sql` — tách metadata canonical khỏi
    retrieval projection, lưu parent/child thật, thêm FTS tiếng Việt có dấu/bỏ dấu,
    exact document-number routing, evidence assertions và review RPC cho metadata LLM.
26. `26_temporal_scope_series.sql` — cho phép lưu quan hệ `temporal_series` và
    mở rộng allowlist của completion RPC để detector v4 không biến dữ liệu khác kỳ
    thành conflict candidate.
27. `27_fix_complete_processing_job_v2_digest.sql` — vá an toàn function completion
    đã được cài từ migration 25 để dùng wrapper pgcrypto có schema rõ ràng.
28. `28_guided_document_publish.sql` — gộp phê duyệt và xuất bản thành một thao tác
    atomic “Đưa vào chatbot”, vẫn giữ nguyên kiểm tra quyền và audit hiện có.
29. `29_allow_reupload_after_archive.sql` — tiếp tục chặn checksum trùng với tài liệu
    đang dùng, nhưng cho phép upload lại khi mọi bản cùng nội dung đã được lưu trữ.
30. `30_auto_publish_processed_documents.sql` — worker hoàn tất toàn bộ chunk/projection
    rồi tự động duyệt và xuất bản bằng đúng quyền của người yêu cầu xử lý; nếu người đó
    không còn quyền review/publish thì phiên bản vẫn dừng an toàn ở trạng thái chờ duyệt.
31. `31_retrieval_reliability_hardening.sql` — sửa refresh lexical projection khi
    metadata revision được tăng bởi trigger, thêm sparse recall tự nhiên không bắt mọi
    filler word cùng xuất hiện, suy luận trạng thái hiệu lực tại thời điểm query, cấp
    READ qua role ACL cho tài liệu INTERNAL/PUBLIC đã publish (không mở cho anon), và
    cung cấp RPC chẩn đoán lifecycle/ACL/projection mà không trả nội dung chunk.
32. `32_high_recall_chunk_candidates.sql` — thêm service-role RPC v2 hợp nhất exact,
    binary và FTS ở cấp chunk, generated multi-layout SimHash keys với GIN index,
    đồng thời giữ nguyên RPC v1 để shadow rollout và rollback.
33. `33_domain_entity_scope_metadata.sql` — thêm partial index cho envelope metadata
    `entity_scope` có version trên notebook/Enterprise chunks; dữ liệu cũ không bắt buộc
    backfill và tiếp tục dùng deterministic extraction fallback.
34. `34_p4_relation_replacement.sql` — materialize P4 document relations atomically
    from persisted P3 claim evidence, preserve reviewed rows, enforce tenant scope,
    and record an append-only recomputation audit event.

Migration phải chạy đúng thứ tự; 09 phụ thuộc 08 và chuỗi Enterprise 17–31 phụ
thuộc toàn bộ nền tảng 01–16; migration 32 bổ sung trên candidate path cũ và migration
33 chỉ lập chỉ mục metadata scope tùy chọn. Với
project đã có dữ liệu, đọc
[`docs/migrations/08-09-knowledge-quality.md`](../../docs/migrations/08-09-knowledge-quality.md),
backup và thử trên clone trước khi chạy. Hướng dẫn rollout Enterprise nằm tại
[`docs/operations/enterprise-knowledge-runbook.md`](../../docs/operations/enterprise-knowledge-runbook.md);
mẫu evidence phát hành nằm tại
[`docs/operations/enterprise-release-checklist.md`](../../docs/operations/enterprise-release-checklist.md).

## Reset toàn bộ

**`RESET_AND_REBUILD.sql`** — 1 file duy nhất, tự chứa (không cần các file
trên), **XOÁ SẠCH** rồi tạo lại toàn bộ theo đúng thứ tự trên, bao gồm
knowledge-quality 08/09/13/26, pre-embedding chunk dedup 10, contextual retrieval
11/12, chunk metadata compaction 14, structured retrieval filters 15, and the
structured-fact layer 16, cùng toàn bộ Enterprise IAM/ACL/lifecycle/RAG 17–31.
Đọc kỹ cảnh báo
ở đầu file trước khi chạy — thao tác này **mất toàn bộ dữ liệu hiện có**
(notebooks, documents, chat...), user (`auth.users`) không bị xoá.

`RESET_AND_REBUILD.sql` không phải rollback. Khi có sự cố, dùng
`KNOWLEDGE_QUALITY_MODE=off`/`shadow` và guarded reversal theo
[`docs/operations/knowledge-quality-rollback.md`](../../docs/operations/knowledge-quality-rollback.md).
`STRUCTURED_FACT_MODE=off` is the independent kill switch for structured-table
extraction and reads; disabling it does not disable the document/chunk quality
pipeline.

### Đồng bộ chính xác file reset

Phần schema sau marker `-- Extensions required by the schema.` trong
`RESET_AND_REBUILD.sql` phải là bản nối **nguyên văn, đúng thứ tự** của mọi migration
canonical `01_*.sql` đến migration mới nhất (`34_*.sql` hiện tại). Không sửa phần này
bằng tay. Sau khi đổi hoặc
thêm migration, chạy từ thư mục gốc:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\regenerate_enterprise_reset.ps1
python -m pytest -q tests\contract\test_enterprise_workflow_completion.py
```

Script giữ nguyên phần preamble phá huỷ, tự phát hiện migration mới nhất và ghi UTF-8
không BOM. Contract test xác nhận mọi migration canonical xuất hiện nguyên văn, đúng
thứ tự trong file reset.

## Việc KHÔNG thể làm chỉ bằng SQL

- **Custom Access Token Hook** (để JWT có claim `user_role` cho phân quyền
  Admin) — function được tạo sẵn trong `03_functions_triggers.sql`
  (`public.custom_access_token_hook`), nhưng phải **bật thủ công** ở Supabase
  Dashboard → Authentication → Hooks → Custom Access Token → chọn function
  này. Không có API/SQL nào bật được từ xa.
- **Bật/tắt xác nhận email khi đăng ký** — Dashboard → Authentication →
  Providers → Email → "Confirm email".
- **Kết nối IdP doanh nghiệp** — cấu hình SAML/OIDC/SSO và đồng bộ trạng thái tài
  khoản vẫn là công việc ở Supabase/IdP, không được hoàn tất chỉ bằng migration.
  Migration 23 chỉ cưỡng chế domain khi bảng
  `public.enterprise_allowed_email_domains` có ít nhất một dòng `ACTIVE`; bảng rỗng
  cố ý không chặn để hỗ trợ local development hoặc IdP bên ngoài.
