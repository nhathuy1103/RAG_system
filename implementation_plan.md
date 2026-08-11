# Kế hoạch: Giải quyết Triệt để Duplicate & Conflict Detection

## Bối cảnh vấn đề

Hệ thống hiện tại đang gặp phải "false positive conflict" — tức là **hai tài liệu hợp lệ bị gán nhầm là xung đột nhau** khi chúng thực chất chỉ đề cập cùng một chủ đề ở **các khoảng thời gian khác nhau**.

> **Ví dụ điển hình:** Giá Vinhomes 2024 vs. Giá Vinhomes 2026
> - Cả hai đều nói về giá bất động sản của Vinhomes
> - Các con số (giá tiền) khác nhau → hệ thống phát hiện `semantic_quantity_mismatch`
> - Phạm vi (scope) giống nhau → hệ thống kết luận `CONFLICT_CANDIDATE`
> - **Nhưng thực tế:** Đây là dữ liệu của hai năm khác nhau, hoàn toàn hợp lệ → phải là `VERSION_CANDIDATE` hoặc `RELATED`

---

## Phân tích nguyên nhân gốc rễ

Đọc code hiện tại trong `analysis.py`, `scope.py`, `claims.py` và `detection.py`, tôi xác định **5 lỗ hổng cốt lõi**:

### Lỗ hổng 1: `ClaimScope` không có trường thời gian (`effective_period`)
[scope.py](file:///d:/VIN_AI/VSF/week2/firstwuy/app/knowledge_quality/application/scope.py) hiện chỉ so sánh `project_id`, `contract_id`, `canonical_document_id`. Không có trường `year`, `quarter`, hoặc `time_period`.

→ Hai tài liệu về Vinhomes 2024 và Vinhomes 2026 có cùng `project_id` → kết luận `SAME_SCOPE` → cho phép kết luận conflict.

### Lỗ hổng 2: `compare_claim_scopes` không dùng temporal context để phân biệt
[scope.py L137-166](file:///d:/VIN_AI/VSF/week2/firstwuy/app/knowledge_quality/application/scope.py#L137-L166): Hàm `compare_claim_scopes` không xét đến việc hai tài liệu thuộc hai kỳ thời gian khác nhau có thể là **chuỗi dữ liệu lịch sử hợp lệ**, không phải conflict.

### Lỗ hổng 3: Khi `date_agreement=False`, system vẫn có thể kết luận CONFLICT
[analysis.py L260-313](file:///d:/VIN_AI/VSF/week2/firstwuy/app/knowledge_quality/application/analysis.py#L260-L313): `critical_difference` bao gồm `not date_agreement`, nhưng logic không phân biệt **temporal scope mismatch** (2024 vs. 2026) khỏi **genuine data conflict** (giá tháng 1 vs giá tháng 3 cùng năm).

### Lỗ hổng 4: `extract_claim_scope` chưa extract được temporal identifier từ nội dung
[scope.py L81-111](file:///d:/VIN_AI/VSF/week2/firstwuy/app/knowledge_quality/application/scope.py#L81-L111): Chỉ extract được `project_id`, `contract_id`, `document_type`. Không extract `effective_year`, `quarter`, `reference_period` từ nội dung.

### Lỗ hổng 5: Detection layer không có "temporal scope guard" trước khi emit `CONFLICT_CANDIDATE`
[detection.py L131-141](file:///d:/VIN_AI/VSF/week2/firstwuy/app/knowledge_quality/application/detection.py#L131-L141): Chỉ lọc `validated_conflict_count > 0` và `SAME_SCOPE`. Không kiểm tra xem scope có **temporal divergence** hay không.

---

## Giải pháp đề xuất

### Chiến lược tổng thể
Thêm một lớp **Temporal Scope** vào hệ thống hiện có, không phá vỡ kiến trúc cũ, nhưng nâng cấp khả năng phân biệt "tài liệu cùng chủ đề khác thời điểm" khỏi "tài liệu thực sự xung đột".

---

## Proposed Changes

### Phase 1: Nâng cấp Domain Model

#### [MODIFY] [models.py](file:///d:/VIN_AI/VSF/week2/firstwuy/app/knowledge_quality/domain/models.py)

Thêm các trường `temporal scope` vào `ClaimScope`:
```python
# Thêm vào ClaimScope dataclass:
reference_year: str | None = None          # "2024", "2026"
reference_quarter: str | None = None       # "Q1", "Q2", "Q3", "Q4"
reference_period_label: str | None = None  # "năm 2024", "quý 1/2026", "tháng 3/2024"
```

Thêm `RelationType` mới:
```python
class RelationType(StrEnum):
    # ...existing...
    TEMPORAL_SERIES = "temporal_series"   # Cùng chủ đề, khác kỳ thời gian
```

Thêm `ScopeComparison` mới:
```python
class ScopeComparison(StrEnum):
    # ...existing...
    TEMPORAL_DIVERGENCE = "temporal_divergence"  # Cùng entity, khác time period
```

---

### Phase 2: Nâng cấp Scope Extraction

#### [MODIFY] [scope.py](file:///d:/VIN_AI/VSF/week2/firstwuy/app/knowledge_quality/application/scope.py)

**Thêm temporal extraction patterns:**
```python
# Patterns để extract năm/kỳ từ nội dung
_YEAR_PATTERN = re.compile(
    r"\b(?:năm|year|thời\s+điểm|kỳ|giai\s+đoạn|quý|quarter|Q[1-4])\s*"
    r"(?P<value>(?:19|20)\d{2}(?:\s*[-–]\s*(?:19|20)\d{2})?)",
    re.IGNORECASE | re.UNICODE,
)
_YEAR_INLINE_PATTERN = re.compile(
    r"\b(?P<value>(?:19|20)\d{2})\b"
)
_QUARTER_PATTERN = re.compile(
    r"\b(?:quý|quarter|Q)(?P<quarter>[1-4])\s*[/,\-]?\s*(?P<year>(?:19|20)\d{2})\b",
    re.IGNORECASE,
)
```

**Nâng cấp `extract_claim_scope`** để extract temporal fields.

**Nâng cấp `compare_claim_scopes`**:
```python
# Nếu hai scope có cùng project_id nhưng khác year → TEMPORAL_DIVERGENCE (không phải SAME_SCOPE)
if left.reference_year and right.reference_year and left.reference_year != right.reference_year:
    return ScopeComparison.TEMPORAL_DIVERGENCE
```

**Nâng cấp `merge_claim_scopes`** để merge temporal fields.

---

### Phase 3: Nâng cấp Analysis Engine

#### [MODIFY] [analysis.py](file:///d:/VIN_AI/VSF/week2/firstwuy/app/knowledge_quality/application/analysis.py)

**Thêm `temporal_scope_guard`** vào `analyze_text_relation`:

Khi `validated_conflicts > 0` và `critical_difference=True`:
1. Nếu `scope_comparison == TEMPORAL_DIVERGENCE` → **không emit CONFLICT**, emit `TEMPORAL_SERIES` với confidence < 0.5
2. Nếu `scope_comparison == SAME_SCOPE` nhưng date_agreement=False và số năm khác nhau đáng kể (>1 năm) → cũng xét lại

**Cụ thể logic mới:**
```python
# Trước khi kết luận CONFLICT_CANDIDATE:
if scope_comparison is ScopeComparison.TEMPORAL_DIVERGENCE:
    # Đây là dữ liệu lịch sử, không phải conflict
    return TextRelationAnalysis(
        relation_type=RelationType.TEMPORAL_SERIES,
        ...
    )

# Hoặc nếu là SAME_SCOPE nhưng date span > 1 năm
if scope_comparison is ScopeComparison.SAME_SCOPE and _temporal_gap_exceeds_threshold(
    effective_left_scope, effective_right_scope, threshold_years=1
):
    return TextRelationAnalysis(
        relation_type=RelationType.VERSION_CANDIDATE,
        reason_codes=("temporal_period_difference", ...),
        ...
    )
```

---

### Phase 4: Nâng cấp Detection Layer

#### [MODIFY] [detection.py](file:///d:/VIN_AI/VSF/week2/firstwuy/app/knowledge_quality/application/detection.py)

Cập nhật `_RELATION_PRIORITY` để include `TEMPORAL_SERIES`:
```python
_RELATION_PRIORITY = {
    RelationType.CONFLICT_CANDIDATE: 5,
    RelationType.VERSION_CANDIDATE: 4,
    RelationType.TEMPORAL_SERIES: 3,  # Mới
    RelationType.NEAR_DUPLICATE: 3,
    RelationType.TEMPLATE_VARIANT: 2,
    RelationType.EXACT_CONTENT: 1,
    RelationType.DISTINCT: 0,
}
```

Thêm guard trong vòng lặp aggregate để **không promote** một pair lên CONFLICT nếu majority evidence là `TEMPORAL_DIVERGENCE`.

---

### Phase 5: Nâng cấp Claims Detection

#### [MODIFY] [claims.py](file:///d:/VIN_AI/VSF/week2/firstwuy/app/knowledge_quality/application/claims.py)

**Thêm `temporal_anchor` vào `ClaimKey`:**
Khi extract claim key, nếu giá trị đi kèm với temporal context rõ ràng (ví dụ "giá năm 2024 là 5 tỷ"), thêm year vào `scope_qualifiers` để key khác với "giá năm 2026 là 8 tỷ".

**Thêm `temporal_scope_qualifier` logic:**
```python
# Trong extract_claims(), khi gặp một claim có year context:
if year_context := _extract_temporal_context_for_claim(sentence):
    scope_qualifiers = (*existing_qualifiers, f"year:{year_context}")
```

Điều này sẽ khiến `ClaimKey` khác nhau khi hai claim thuộc hai năm khác nhau → `detect_claim_conflicts` sẽ không align chúng → không tạo ra false positive conflict.

---

### Phase 6: Cập nhật `DETECTOR_VERSION`

#### [MODIFY] [models.py](file:///d:/VIN_AI/VSF/week2/firstwuy/app/knowledge_quality/domain/models.py)

```python
DETECTOR_VERSION = "knowledge-quality-v4"  # tăng version để trigger re-detection
```

---

### Phase 7: Cập nhật Repository & API Response

#### [MODIFY] [postgrest_repository.py](file:///d:/VIN_AI/VSF/week2/firstwuy/app/knowledge_quality/adapters/postgrest_repository.py)

Đảm bảo `TEMPORAL_SERIES` và `TEMPORAL_DIVERGENCE` được persist/read đúng.

---

## Thứ tự triển khai (ưu tiên impact cao → thấp)

| Bước | File | Mô tả | Rủi ro |
|------|------|--------|--------|
| 1 | `models.py` | Thêm temporal fields vào ClaimScope, thêm RelationType.TEMPORAL_SERIES | Thấp |
| 2 | `scope.py` | Thêm temporal extraction, nâng cấp compare_claim_scopes | Trung bình |
| 3 | `analysis.py` | Thêm temporal_scope_guard trước khi emit CONFLICT | **Cao** (core logic) |
| 4 | `claims.py` | Thêm temporal_anchor vào ClaimKey scope_qualifiers | Trung bình |
| 5 | `detection.py` | Cập nhật priority, thêm temporal guard | Thấp |
| 6 | `models.py` | Tăng DETECTOR_VERSION lên v4 | Thấp |
| 7 | `postgrest_repository.py` | Handle new types | Thấp |

---

## Open Questions

> [!IMPORTANT]
> **Câu hỏi 1: Ngưỡng temporal gap hợp lý là bao nhiêu?**
> Khi hai tài liệu có cùng project_id nhưng năm khác nhau, khoảng cách bao lâu mới đủ để kết luận là "dữ liệu của hai kỳ khác nhau" thay vì "conflict"?
> - Đề xuất: ≥ 1 năm → không phải conflict, là temporal series
> - Hoặc: bất kỳ sự khác biệt nào về năm?

> [!IMPORTANT]
> **Câu hỏi 2: Phân loại `TEMPORAL_SERIES` có cần hiển thị trên UI không?**
> Hiện tại UI chỉ hiển thị: near_duplicate, version_candidate, conflict_candidate, conflict, related.
> Có nên thêm "Dữ liệu lịch sử theo kỳ" vào màn hình quản lý quan hệ không?

> [!NOTE]
> **Câu hỏi 3: Có cần re-run detection cho các document pairs đã bị kết luận nhầm là conflict?**
> Nếu tăng DETECTOR_VERSION lên v4, hệ thống có pipeline nào để re-detect các pairs cũ không?

---

## Verification Plan

### Automated Tests
```bash
# Chạy unit tests hiện có
uv run pytest app/knowledge_quality/ -v

# Test case cụ thể cần thêm mới:
# 1. test_temporal_divergence_not_conflict() - Giá Vinhomes 2024 vs 2026
# 2. test_same_year_conflict_detected() - Giá sai trong cùng năm vẫn là conflict
# 3. test_temporal_scope_extraction() - Extract "năm 2024" từ văn bản
# 4. test_compare_scopes_temporal_divergence() - SAME project, DIFFERENT year → TEMPORAL_DIVERGENCE
```

### Manual Verification
1. Upload hai file test: "Bảng giá Vinhomes 2024" và "Bảng giá Vinhomes 2026"
2. Chạy detection → kỳ vọng: `TEMPORAL_SERIES` hoặc `VERSION_CANDIDATE`, KHÔNG phải `CONFLICT_CANDIDATE`
3. Upload hai file thực sự conflict: cùng năm, cùng dự án, số liệu khác nhau → kỳ vọng: `CONFLICT_CANDIDATE`
