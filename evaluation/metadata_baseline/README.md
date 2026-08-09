# Current Metadata Baseline Toolkit

Bộ công cụ này đo metadata **đang tồn tại** trong RAG repository. Nó không tạo metadata production mới, không gọi LLM, không tạo lại embedding và không thay đổi retrieval. Exporter chỉ phát HTTP `GET`; các tool còn lại chỉ đọc JSONL/CSV cục bộ.

## Yêu cầu

- Chạy từ repository root.
- Toolkit tương thích Python `>=3.11`; baseline này được kiểm thử bằng Python 3.12 theo project lock. Code không phụ thuộc package ngoài standard library.
- Muốn export corpus thật: `.env` có `SUPABASE_URL` và `SUPABASE_SERVICE_ROLE_KEY`; key không được ghi vào output/log.
- Mặc định mọi CLI từ chối ghi đè. Chỉ dùng `--overwrite` khi chủ động thay kết quả đã sinh.

## Cấu trúc

| File | Vai trò |
|---|---|
| `experiment_config.yaml` | Frozen runtime/corpus config và unresolved facts |
| `system_analysis.md` | Pipeline, bằng chứng file/symbol/line/certainty |
| `metadata_schema.csv` | Inventory schema-driven của field hiện tại |
| `metadata_usage_map.md` | Field được tạo/lưu/dùng ở đâu |
| `export_metadata.py` | Best-effort read-only PostgREST export, không xuất vector |
| `audit_metadata.py` | Coverage, validity, consistency, uniqueness, reference, date, version, conflict, outlier, distribution |
| `create_gold_sample.py` | Deterministic stratified record sample, mở rộng thành field rows |
| `metadata_annotation_guide.md` | Quy tắc A/B annotation và adjudication |
| `score_metadata_accuracy.py` | Accuracy/F1/multilabel metrics/agreement/report |
| `sample_data/metadata_export.jsonl` | Fixture nhỏ có lỗi chủ đích; không phải corpus result |
| `results/sample/` | Smoke-test outputs từ fixture |

## Input JSONL

Mỗi dòng là một JSON object:

```json
{"record_type":"document","record_id":"<uuid>","document_id":"<uuid>","...":"..."}
{"record_type":"chunk","record_id":"<uuid>","chunk_id":"<uuid>","document_id":"<uuid>","content":"...","metadata":{}}
```

`record_type` chỉ nhận `document` hoặc `chunk`. Field có thể ở top-level hoặc trong `metadata`; resolver dùng canonical path và aliases trong schema. Empty string/list/object, null và placeholder (`unknown`, `N/A`, `none`, ...) được phân biệt.

Trong inventory, `mutable_over_time` có ba giá trị: `false` cho field ổn định trên record hiện hữu, `true` cho state có thể đổi bởi lifecycle/workflow, và `recomputed_on_reingestion` cho field được tạo lại khi parse, chunk hoặc index lại. Đây là đặc tính của field hiện tại, không phải đề xuất schema production.

## Chạy theo thứ tự

### 1. Unit test

```powershell
.\.venv\Scripts\python.exe -m pytest -q evaluation\metadata_baseline\tests --no-cov
```

### 2. Smoke test trên fixture

```powershell
.\.venv\Scripts\python.exe evaluation\metadata_baseline\audit_metadata.py `
  --input evaluation\metadata_baseline\sample_data\metadata_export.jsonl `
  --schema evaluation\metadata_baseline\metadata_schema.csv `
  --output-dir evaluation\metadata_baseline\results\sample `
  --overwrite
```

Các lỗi trong fixture là cố ý để test detector. Không trích các tỷ lệ đó thành kết luận về production.

### 3. Export corpus thật (read-only)

```powershell
.\.venv\Scripts\python.exe evaluation\metadata_baseline\export_metadata.py `
  --env-file .env `
  --output data\metadata_export.jsonl
```

Exporter chỉ chọn document/chunk columns và JSONB metadata, không chọn embedding. File manifest đi kèm ghi count, thời gian, hash của REST origin và xác nhận method `GET`. Pagination không nằm trong một database transaction; nếu ingestion vẫn chạy trong lúc export, snapshot chỉ là best effort. Muốn snapshot chặt, dừng writer hoặc export từ database snapshot do operator cấp.

`data/` đã được `.gitignore`; chunk content có thể nhạy cảm. Dùng `--exclude-content` chỉ khi không làm human annotation.

`metadata_gold_sample.csv` và actual-corpus outputs trong `results/` cũng có thể chứa excerpt, identifier, parent context hoặc storage source. `.gitignore` cục bộ chặn các artifact này khỏi commit mặc định. Hãy coi chúng là dữ liệu nội bộ nhạy cảm và không chia sẻ ra ngoài phạm vi đánh giá nếu chưa có phê duyệt dữ liệu.

### 4. Audit toàn corpus

```powershell
.\.venv\Scripts\python.exe evaluation\metadata_baseline\audit_metadata.py `
  --input data\metadata_export.jsonl `
  --schema evaluation\metadata_baseline\metadata_schema.csv `
  --output-dir evaluation\metadata_baseline\results
```

Audit tạo đúng các file:

```text
metadata_field_summary.csv
metadata_coverage.csv
metadata_validity.csv
metadata_consistency_issues.csv
metadata_duplicate_ids.csv
metadata_referential_errors.csv
metadata_temporal_errors.csv
metadata_version_errors.csv
metadata_conflicts.csv
metadata_outliers.csv
metadata_distributions.json
metadata_audit_summary.json
metadata_audit_report.md
```

`metadata_distributions.json.__schema_inventory__` liệt kê nested leaf paths quan sát được nhưng chưa có trong inventory, đặc biệt hữu ích với JSONB mở.

Snapshot đã chạy ngày 2026-08-03 có 24 document và 257 chunk. Inventory cuối có 125 field và không còn observed leaf path ngoài schema. Kết quả nổi bật: 257 `retrieval_metadata` đều là object rỗng; context enrichment phủ 0/257; document fingerprint v2 phủ 4/24; chunk fingerprint phủ 257/257. Có 8 `conflict_candidate` trên 3 source document nhưng chưa có conflict được xác nhận; hai con số này không được đánh đồng. Xem `results/metadata_audit_report.md` và luôn đọc kèm manifest vì export không phải database transaction.

### 5. Tạo gold sample

Pilot hiện tại lấy toàn bộ 281 record vì corpus nhỏ hơn mục tiêu 300:

```powershell
.\.venv\Scripts\python.exe evaluation\metadata_baseline\create_gold_sample.py `
  --input data\metadata_export.jsonl `
  --schema evaluation\metadata_baseline\metadata_schema.csv `
  --audit-dir evaluation\metadata_baseline\results `
  --sample-size 281 `
  --fields-per-record 8 `
  --random-seed 20260803 `
  --output evaluation\metadata_baseline\metadata_gold_sample.csv
```

Full evaluation nên dùng `--sample-size 500` trở lên khi corpus đủ lớn. Không lặp record để tạo cảm giác đạt cỡ mẫu: snapshot này chỉ có 281 record nên pilot bao phủ toàn corpus. `sample-size` là số record duy nhất; output có nhiều field rows trên mỗi record. Sampler ưu tiên tối đa 50% flagged records, sau đó round-robin theo record type, document type, source, department nếu có, year, version, status, parser/rule/LLM, low coverage, confidence, multi-version, rare value và audit issue. Ở cấp field, sampler oversample `status`, `quality_status`, version group/number, `is_current`, `effective_from`, `effective_to` và canonical identity. Access-control ID hiện là source-authoritative và không bị ép annotator đoán. Manifest cạnh CSV ghi seed, count và checksum để tái lập.

### 6. Double annotation và chấm điểm

Hai annotator điền độc lập các cột A/B theo `metadata_annotation_guide.md`; reviewer adjudicate disagreement. Sau đó chạy:

```powershell
.\.venv\Scripts\python.exe evaluation\metadata_baseline\score_metadata_accuracy.py `
  --annotations evaluation\metadata_baseline\metadata_gold_sample.csv `
  --schema evaluation\metadata_baseline\metadata_schema.csv `
  --output-dir evaluation\metadata_baseline\results\accuracy
```

Output:

```text
metadata_field_accuracy.csv
metadata_confusion_matrices.json
metadata_inter_annotator_agreement.csv
metadata_accuracy_report.md
```

Nếu annotation còn pending, scorer vẫn sinh artifact nhưng báo “chưa thể kết luận”; nó không biến ô trống thành lỗi.

## Diễn giải an toàn

- `coverage` là populated/total; `valid_coverage` mới là valid/total; `validity` là valid/non-empty.
- Automatic audit đo cấu trúc và quan hệ, không chứng minh semantic truth của title/type/LLM context.
- Acronym/singular-plural detector chỉ sinh candidate consistency; synonym đa ngôn ngữ cần vocabulary được duyệt hoặc human annotation.
- `conflict_candidate` và text heuristic không phải confirmed business conflict.
- Referential error có thể là export thiếu record, nên phải kiểm tra completeness trước khi sửa source.
- Không phê duyệt hard filter chỉ từ coverage. Cần human accuracy theo scope, đủ sample và không có `wrong_scope`.
