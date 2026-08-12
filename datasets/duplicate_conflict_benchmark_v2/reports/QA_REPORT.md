# QA Report

## Kết quả validation

- `valid`: `true`
- Pairs: 164
- Evidence units: 165
- Errors / warnings: 0 / 0
- DEV / TEST: 96 / 68
- Observed / controlled mutation: 94 / 70
- Source-family overlap: 0
- Exact full-input overlap giữa DEV và TEST: 0
- Hard cases: 64

Validator đã kiểm tra partition split, SHA-256 text và tài liệu, evidence locator, mutation parent, label invariants, auto-reuse policy, duplicate pair và schema structure.

## Kiểm tra nhãn thủ công theo slice

Đã kiểm tra đại diện của cả chín nhãn và toàn bộ 10 cặp time-series. Hai cặp ban đầu có qualifier quyết định đã được sửa theo precedence rule:

- Golden Avenue 2025 “vốn ban đầu” so với giá tài sản 08/2026 → `CONDITIONAL_VARIANT`, không phải temporal/conflict.
- Star City giá thấp tầng 2024 so với căn hộ thương mại 08/2026 → `CONDITIONAL_VARIANT`, không phải temporal/conflict.

## Sanity baseline

Baseline surface-only trên TEST (68 cặp):

| Metric | Giá trị |
| --- | ---: |
| Accuracy | 0.5882 |
| Macro-F1 (supported labels) | 0.3036 |
| Auto-reuse precision | 0.8000 |
| Unsafe auto-reuse | 4 |
| Conflict recall | 0.5000 |
| Missed conflicts | 4 |
| False conflicts | 4 |

Kết quả này cho thấy benchmark không bị giải quyết chỉ bằng equality/fuzzy similarity. Bốn template pairs bị surface-only baseline đẩy sai vào `EXACT_DUPLICATE`, trực tiếp tạo unsafe auto-reuse.

## Rủi ro còn lại

- Nhãn vẫn là provisional gold vì chưa có hai human reviews độc lập.
- Natural conflict/version coverage còn hạn chế; các nhãn này chủ yếu dùng controlled mutation.
- Cần mở rộng bằng các phiên bản tài liệu thật và nguồn độc lập trước khi dùng làm release gate toàn tổ chức.
