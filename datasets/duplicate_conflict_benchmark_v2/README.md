# Duplicate & Conflict Benchmark V2

Bộ benchmark này được dựng từ 11 tài liệu DOCX do người dùng cung cấp để đánh giá phân loại quan hệ giữa hai chunk trong hệ thống RAG. Nó giữ nguyên taxonomy 9 nhãn của repository `nhathuy1103/RAG_system`, nhưng sửa ba điểm yếu lớn của bộ V1: provenance không kiểm chứng được, tất cả case bị ép là synthetic, và split ngẫu nhiên có thể làm rò rỉ template.

## Tóm tắt

| Thuộc tính | Giá trị |
| --- | ---: |
| Tổng số cặp | 164 |
| DEV / TEST | 96 / 68 |
| Bằng chứng quan sát thật | 94 |
| Mutation có kiểm soát | 70 |
| Tài liệu nguồn | 11 |
| Source-family overlap DEV/TEST | 0 |
| Full-input overlap DEV/TEST | 0 |

Phân bố nhãn:

| Nhãn | Số cặp |
| --- | ---: |
| `EXACT_DUPLICATE` | 40 |
| `NEAR_DUPLICATE` | 30 |
| `CONFLICT` | 20 |
| `TEMPORAL_VARIANT` | 18 |
| `DISTINCT` | 14 |
| `VERSION_UPDATE` | 10 |
| `CONDITIONAL_VARIANT` | 12 |
| `TEMPLATE_VARIANT` | 10 |
| `UNCERTAIN` | 10 |

## Vì sao đáng tin cậy hơn V1

- Mỗi excerpt quan sát có `filename`, SHA-256 tài liệu, locator paragraph/table/cell và SHA-256 của text trong `sources/evidence_catalog.jsonl`.
- Dữ liệu thật và dữ liệu can thiệp được báo riêng qua `provenance_kind`, `is_synthetic` và `mutation`.
- DEV/TEST được chia theo tài liệu nguồn. Một tài liệu không bao giờ đóng góp vào cả hai split.
- Input chính thức là `context + text`, không chỉ riêng `text`. Điều này bắt buộc với các đoạn template giống hệt nhưng thuộc dự án khác nhau.
- Validator kiểm tra schema, provenance, invariants nhãn, split leakage, SHA-256, partition DEV/TEST và tỷ lệ coverage.
- Bộ chấm báo riêng `observed` và `controlled_mutation`; không gộp hai strata thành một con số headline duy nhất.
- Có `review_queue.csv` để hai reviewer độc lập gán nhãn và một người thứ ba adjudicate.

## Trạng thái nhãn

Các nhãn hiện là `provisional_gold`, không phải gold đã được tổ chức phê duyệt. Chúng được tạo bằng rule minh bạch, kiểm tra máy và kiểm tra mẫu; chưa có hai reviewer con người độc lập. Chỉ đổi trạng thái thành `gold` sau khi hoàn thành quy trình trong `ADJUDICATION_GUIDE.md`.

## Cấu trúc

```text
duplicate_conflict_benchmark_v2/
├── README.md
├── DATASET_CARD.md
├── ADJUDICATION_GUIDE.md
├── REPO_INTEGRATION.md
├── manifest.json
├── schema.json
├── review_queue.csv
├── SHA256SUMS
├── data/
│   ├── benchmark_all.jsonl
│   ├── benchmark_dev.jsonl
│   └── benchmark_test.jsonl
├── sources/
│   └── evidence_catalog.jsonl
├── scripts/
│   ├── validate_benchmark.py
│   ├── naive_surface_baseline.py
│   └── evaluate_predictions.py
└── reports/
    ├── validation_report.json
    ├── naive_test_predictions.jsonl
    └── naive_test_report.json
```

Các DOCX gốc không được đóng gói lại. `manifest.json` chứa hash để đối chiếu với bản gốc.

## Chạy validation

Không yêu cầu dependency ngoài Python standard library. Nếu có `jsonschema`, validator sẽ dùng Draft 2020-12; nếu không, nó vẫn chạy fail-closed với kiểm tra cấu trúc nội bộ.

```bash
python scripts/validate_benchmark.py --write-report
```

Kết quả hợp lệ phải có:

- `valid: true`
- `source_family_overlap: []`
- `cross_split_full_input_overlap: 0`
- `errors: []`

## Format prediction và chấm điểm

Tạo JSONL gồm đúng một prediction cho mỗi `pair_id`:

```json
{"pair_id":"DCV2_TEST_0001","predicted_relation":"EXACT_DUPLICATE"}
```

Sau đó chạy:

```bash
python scripts/evaluate_predictions.py predictions.jsonl \
  --gold data/benchmark_test.jsonl \
  --output reports/my_test_report.json
```

Report gồm macro-F1 theo các nhãn có support, confusion matrix, strata theo provenance/difficulty/source form, và safety metrics:

- precision của đường `auto_reuse`;
- số/rate auto-reuse không an toàn;
- conflict recall và khoảng tin cậy Wilson 95%;
- số conflict bị bỏ sót và false conflict.

## Baseline không dùng context

Baseline đi kèm cố tình chỉ nhìn text bề mặt. Nó minh họa vì sao similarity cao không đủ để giải quyết template, thời gian, qualifier và conflict:

```bash
python scripts/naive_surface_baseline.py
python scripts/evaluate_predictions.py reports/naive_test_predictions.jsonl \
  --output reports/naive_test_report.json
```

Không dùng baseline này trong production.

## Nguyên tắc sử dụng TEST

- Dùng DEV để chỉnh threshold/rule/prompt/mapping.
- Không đọc nhãn TEST trong quá trình tuning.
- Chỉ chạy TEST sau khi chốt trước version code và tiêu chí đánh giá.
- Khi thay source, taxonomy hoặc annotation, tạo version mới; không sửa lặng benchmark đã báo cáo.
