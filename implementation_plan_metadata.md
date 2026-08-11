# Kiểm tra & Tinh chỉnh Metadata cho Retrieval

## Tổng quan

Qua khảo sát toàn bộ pipeline từ ingestion → indexing → retrieval, tôi đã lập bản đồ đầy đủ về metadata: metadata được sinh ra như thế nào, gắn vào đâu, và dùng để làm gì trong bước retrieval. Dưới đây là **phân tích chi tiết các điểm tốt, các điểm yếu, và kế hoạch tinh chỉnh**.

---

## Phần 1: Metadata gồm những gì?

### 1.1 – Các lớp metadata (theo thứ tự ưu tiên)

Hệ thống có **5 lớp metadata** xếp chồng nhau:

| Lớp | Nguồn | Ưu tiên |
|---|---|---|
| `source.metadata` | `ClaimedIngestionJob` (job-level: notebook_id, storage_object_path...) | thấp nhất |
| `parsed.document_metadata` | Parser trích từ file (title, language, OCR info...) | thấp |
| `chunk.metadata` (chunk-level) | Chunker gán: section_title, page_number, table_header... | trung bình |
| `retrieval_metadata` (normalized) | `normalize_chunk_retrieval_metadata()` gộp 3 lớp trên | **cao – dùng để filter** |
| `inferred_metadata` | LLM-enriched (document_type, project_code, domain...) | bổ sung, **chưa được promote vào retrieval_metadata** |

### 1.2 – Các trường trong `retrieval_metadata` (filter fields)

```
document_type, content_kind, project_id, project_code, project_name,
project_aliases, year, data_period, effective_status, domain,
clause_type, region, region_code, source, source_code
```

Và các trường hiển thị/ranking:
```
title, section_title, section_path, table_header,
keyword_aliases, contextual_summary, contextual_search_terms
```

### 1.3 – Trường nào LLM enrichment trích ra?

`DOCUMENT_METADATA_FIELDS` = `document_number, document_type, category, domain, project_code, department_code, effective_from, effective_to`

---

## Phần 2: Flow hoạt động như thế nào?

```
Ingestion Worker
  |
  +- pipeline.prepare()
  |    +- Parser -> parsed.document_metadata (title, language, parser info)
  |    +- source.metadata <- job fields (notebook_id, ingestion_job_id...)
  |    +- [Optional] LLM Metadata Enrichment
  |         +- Ket qua -> parsed.document_metadata["inferred_metadata"]
  |              (nhung KHONG tu dong merge vao retrieval_metadata!)
  |
  +- pipeline.contextualize()
  |    +- LLM Context Enrichment per-chunk
  |         +- Ket qua -> chunk.metadata["retrieval_metadata"]["contextual_summary"]
  |
  +- pipeline.embed()
       +- build_embedded_chunk()
            +- normalize_chunk_retrieval_metadata()
                 +- Gop: document_metadata + source_metadata + chunk_metadata
                 +- Sinh ra: embedded_chunk.retrieval_metadata <- dung de filter

Retrieval
  +- DeterministicMetadataFilterPlanner.plan()
  |    +- Trich tu query text: project_code, year, data_period, effective_status, content_kind
  |
  +- Dense (Qdrant): filters.metadata.as_dict() -> metadata_filters
  +- Sparse (PostgresFTS): p_{field_name} -> RPC params
  +- BM25: metadata->retrieval_metadata->>{field_name} -> PostgREST params
```

---

## Phần 3: Các vấn đề phát hiện

### Vấn đề 1: `inferred_metadata` không tự động merge vào `retrieval_metadata`

**File:** [pipeline.py L534-539](file:///d:/VIN_AI/VSF/week2/firstwuy/app/pipeline/indexing/application/pipeline.py#L534-L539)

LLM enrichment sinh ra `document_type`, `project_code`, `domain`, `effective_from/to`... và lưu vào:
```python
parsed.document_metadata["inferred_metadata"] = {"document_type": "bao_cao", ...}
```

Nhưng hàm [normalize_chunk_retrieval_metadata()](file:///d:/VIN_AI/VSF/week2/firstwuy/app/pipeline/indexing/domain/retrieval_metadata.py#L32-L93) chỉ đọc các key **trực tiếp** từ `document_metadata`, **không đọc nested `inferred_metadata`**.

> [!CAUTION]
> **Đây là bug nghiêm trọng nhất**: toàn bộ công sức LLM enrichment bị bỏ phí. `document_type`, `project_code` LLM trích ra **không được index vào filter metadata**. Các query filter theo `document_type` sẽ miss chunk dù LLM đã biết document type.

---

### Vấn đề 2: Bất đối xứng schema giữa LLM fields và filter fields

**DOCUMENT_METADATA_FIELDS** (LLM trích):
```python
("document_number", "document_type", "category", "domain",
 "project_code", "department_code", "effective_from", "effective_to")
```

**_FILTER_FIELDS** (normalize_chunk dùng để filter):
```python
("document_type", "content_kind", "project_id", "project_code",
 "project_name", "project_aliases", "year", "data_period",
 "effective_status", "domain", "clause_type", "region", "region_code",
 "source", "source_code")
```

> [!WARNING]
> **Gap quan trọng:**
> - `effective_from`, `effective_to` → LLM biết nhưng **không có trong filter fields**
> - `category`, `department_code`, `document_number` → LLM biết nhưng **bị bỏ qua**
> - `content_kind`, `year`, `data_period` → có trong filter fields nhưng **LLM không trích**

---

### Vấn đề 3: `effective_status` không được suy luận từ date

**StructuredMetadataFilters** có `effective_status` để filter "current/expired", nhưng:
- LLM enrichment không trích `effective_status` — chỉ trích `effective_from/to`
- `normalize_chunk_retrieval_metadata()` normalize `effective_status` chỉ khi đã có giá trị trong metadata nguồn
- `DeterministicMetadataFilterPlanner` chỉ nhận diện keywords đơn giản: `" hien hanh "`, `" moi nhat "`
- **Không có logic** suy luận `effective_status = "current"` từ `effective_from/to` + ngày hiện tại

---

### Vấn đề 4: `year` — nguồn dữ liệu không nhất quán

`year` được derive theo 3 cách không phối hợp:
1. `normalize_chunk_retrieval_metadata()` → trích từ title nếu có **chính xác 1 năm**
2. `DeterministicMetadataFilterPlanner` → regex `(19|20)\d{2}` trong query
3. LLM enrichment → **không trích `year`**

**Rủi ro:** Title có nhiều năm ("Báo cáo 2022-2023") → `year` bị bỏ qua hoàn toàn.

---

### Vấn đề 5: BM25 filter path không nhất quán với các adapters khác

**File:** [postgrest_bm25_search.py L67](file:///d:/VIN_AI/VSF/week2/firstwuy/app/retrieval/adapters/postgrest_bm25_search.py#L67)

```python
# BM25 dùng nested JSON path
params[f"metadata->retrieval_metadata->>{field_name}"] = f"eq.{value}"

# Nhung matches_metadata_filters() kiem tra ca flat lẫn nested
nested = metadata.get("retrieval_metadata")
retrieval_metadata = nested if isinstance(nested, Mapping) else metadata
```

> [!NOTE]
> Nếu chunk lưu metadata flat (không nested) → BM25 filter miss nhưng dense filter match → kết quả hybrid không nhất quán.

---

### Vấn đề 6: Không có visibility cho metadata fill rate

Không có cơ chế nào để biết:
- Bao nhiêu % chunks có `document_type`? `project_code`? `year`?
- Bao nhiêu % LLM assertions được generate vs fallback?
- Filter nào bị fired nhưng kết quả 0 chunk (over-filtering)?

---

## Phần 4: Những gì đang hoạt động đúng

- [normalize_chunk_retrieval_metadata()](file:///d:/VIN_AI/VSF/week2/firstwuy/app/pipeline/indexing/domain/retrieval_metadata.py) gộp 3 lớp metadata đúng theo thứ tự ưu tiên
- [EvidenceMetadata.from_mapping()](file:///d:/VIN_AI/VSF/week2/firstwuy/app/retrieval/domain/metadata.py) xử lý đúng nested `retrieval_metadata` + flatten cho typed access
- [DeterministicMetadataFilterPlanner](file:///d:/VIN_AI/VSF/week2/firstwuy/app/retrieval/application/metadata_filter_planner.py) hoạt động đúng với regex project_code và quarter parsing
- [StructuredMetadataFilters](file:///d:/VIN_AI/VSF/week2/firstwuy/app/retrieval/domain/models.py) normalize đúng (casefold cho document_type, UPPER cho project_code)
- Section path normalization (`"A > B > C"` → `["A", "B", "C"]`) đúng
- [candidate_metadata_audit()](file:///d:/VIN_AI/VSF/week2/firstwuy/app/retrieval/domain/audit.py) ghi lại filter match per-candidate trong telemetry
- **Fail-closed design**: chunk không có metadata filter field → bị loại (security correct)

---

## Open Questions

> [!IMPORTANT]
> **Q1: LLM metadata enrichment có đang bật không?**
> `document_metadata_enrichment_enabled` trong `.env` là `true` hay `false`? Nếu `false`, Vấn đề 1 không ảnh hưởng production nhưng cần fix trước khi bật.

> [!IMPORTANT]
> **Q2: Ưu tiên tinh chỉnh?**
> Vấn đề nào muốn fix trước: (a) inferred_metadata không được promote → filter miss, (b) year/effective_status inference yếu, (c) observability fill rate?

> [!NOTE]
> **Q3: `effective_status` derive tự động từ date?**
> Có muốn hệ thống tự suy luận `effective_status = "current"` khi `effective_from <= today <= effective_to` không? Hay để manual?

---

## Proposed Changes

### Fix 1 (Critical): Promote `inferred_metadata` vào `retrieval_metadata`

#### [MODIFY] [retrieval_metadata.py](file:///d:/VIN_AI/VSF/week2/firstwuy/app/pipeline/indexing/domain/retrieval_metadata.py)

Trong `normalize_chunk_retrieval_metadata()`, thêm layer đọc `inferred_metadata` từ `document_metadata` với ưu tiên **thấp hơn explicit fields nhưng cao hơn default**:

```python
# Sau khi gop 3 layer baseline, promote inferred_metadata neu chua co
inferred = document_metadata.get("inferred_metadata")
if isinstance(inferred, Mapping):
    for field_name in _FILTER_FIELDS:
        if result.get(field_name) in (None, "") and inferred.get(field_name) not in (None, ""):
            result[field_name] = inferred[field_name]
```

---

### Fix 2 (Medium): `effective_status` tự suy luận từ effective_from/to

#### [MODIFY] [retrieval_metadata.py](file:///d:/VIN_AI/VSF/week2/firstwuy/app/pipeline/indexing/domain/retrieval_metadata.py)

Sau khi gộp metadata, nếu không có `effective_status` nhưng có date fields:

```python
from datetime import date
today = date.today().isoformat()
if not result.get("effective_status"):
    eff_from = str(result.get("effective_from") or "").strip()
    eff_to = str(result.get("effective_to") or "").strip()
    if eff_from and eff_from <= today and (not eff_to or today <= eff_to):
        result["effective_status"] = "current"
    elif eff_to and today > eff_to:
        result["effective_status"] = "expired"
```

---

### Fix 3 (Medium): Mở rộng LLM enrichment để trích thêm `year`, `content_kind`

#### [MODIFY] [document_metadata.py](file:///d:/VIN_AI/VSF/week2/firstwuy/app/pipeline/indexing/domain/document_metadata.py)

Thêm `year`, `data_period`, `content_kind` vào `DOCUMENT_METADATA_FIELDS`.

#### [MODIFY] [document_metadata_enrichers.py](file:///d:/VIN_AI/VSF/week2/firstwuy/app/pipeline/indexing/adapters/document_metadata_enrichers.py)

Cập nhật validation/normalize cho các field mới (year: integer 1900-2100, content_kind: snake_case).

---

### Fix 4 (Low): Metadata fill rate logging

#### [MODIFY] [worker.py](file:///d:/VIN_AI/VSF/week2/firstwuy/app/ingestion/application/worker.py)

Sau `_to_persisted_chunks()`, tính fill rate và emit vào telemetry:

```python
_KEY_FILTER_FIELDS = ("document_type", "project_code", "year", "data_period", "effective_status")
fill_rates = {
    field: sum(
        1 for c in chunks
        if c.metadata.get("retrieval_metadata", {}).get(field) not in (None, "")
    )
    for field in _KEY_FILTER_FIELDS
}
# Emit vào root_observation output dict
```

---

## Verification Plan

### Automated Tests
```bash
pytest tests/ -k "metadata" -v
pytest tests/ -k "retrieval_metadata" -v
```
- Viết unit test cho `normalize_chunk_retrieval_metadata()` với case `inferred_metadata` present
- Viết unit test cho `effective_status` derive từ `effective_from/to` + frozen date

### Manual Verification
1. Upload 1 document có document type rõ ràng → kiểm tra Qdrant metadata của chunk có `document_type` trong `retrieval_metadata` không
2. Chạy query filter `document_type=bao_cao` → kiểm tra có kết quả không
3. Kiểm tra Langfuse trace → xem `candidate_metadata_audit` để biết filter có match không

---

## Độ ưu tiên tóm tắt

| # | Vấn đề | Mức độ | Effort |
|---|---|---|---|
| 1 | `inferred_metadata` không được promote vào filter | Critical | Thấp (15 dòng) |
| 2 | `effective_status` không được suy luận từ date | Medium | Thấp (20 dòng) |
| 3 | LLM enrichment thiếu `year`, `content_kind` | Medium | Trung bình |
| 4 | Metadata fill rate observability | Low | Thấp |
| 5 | BM25 filter path inconsistency | Low | Thấp |
