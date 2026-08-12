# Duplicate/conflict P0 baseline

> Frozen deterministic baseline. No production algorithm, threshold, or runtime default was changed.

## Dataset

- Valid: `True`; pairs: **600**.
- Domains: `{"vinfast": 300, "vinhomes": 300}`.
- Splits: `{"dev": 421, "test": 179}`.
- Labels: `{"CONDITIONAL_VARIANT": 72, "CONFLICT": 108, "DISTINCT": 54, "EXACT_DUPLICATE": 60, "NEAR_DUPLICATE": 90, "TEMPLATE_VARIANT": 42, "TEMPORAL_VARIANT": 72, "UNCERTAIN": 30, "VERSION_UPDATE": 72}`.
- Difficulty: `{"easy": 60, "hard": 210, "medium": 330}`.
- Source forms: `{"prose_to_prose": 564, "table_to_prose": 18, "table_to_table": 18}`.
- Maximum OCR-noise level per pair: `{"light": 49, "medium": 10, "none": 521, "severe": 20}`.
- All facts and values are synthetic; source DOCX files informed only domain patterns and qualifier coverage.

## Candidate generation

- Population requiring retrieval: **516**.
- Recall@1/5/10/20/50: **30.2% / 46.7% / 48.8% / 49.4% / 49.4%**.
- Admission to current classifier (`top 5`, Hamming <= 24): **45.5%**.
- Returned candidate count mean / p50 / p95: **4.428 / 4 / 11**.

## Classification

- Oracle-pair accuracy / macro-F1: **37.5% / 35.9%**.
- Reached-classifier accuracy / macro-F1: **55.0% / 36.3%**.
- Oracle-pair means the gold pair is supplied directly to the current deterministic classifier; it does not hide candidate misses.

### Per-label oracle-pair metrics

| Label | Precision | Recall | F1 | Support |
| --- | ---: | ---: | ---: | ---: |
| EXACT_DUPLICATE | 100.0% | 100.0% | 100.0% | 60 |
| NEAR_DUPLICATE | 0.0% | 0.0% | 0.0% | 90 |
| VERSION_UPDATE | 0.0% | 0.0% | 0.0% | 72 |
| TEMPORAL_VARIANT | 98.6% | 100.0% | 99.3% | 72 |
| CONDITIONAL_VARIANT | 0.0% | 0.0% | 0.0% | 72 |
| TEMPLATE_VARIANT | 100.0% | 50.0% | 66.7% | 42 |
| CONFLICT | 49.3% | 66.7% | 56.7% | 108 |
| DISTINCT | 0.0% | 0.0% | 0.0% | 54 |
| UNCERTAIN | 0.0% | 0.0% | 0.0% | 30 |

### Source-form oracle-pair metrics (active text path)

| Source form | Pairs | Accuracy | Macro-F1 |
| --- | ---: | ---: | ---: |
| prose_to_prose | 564 | 36.7% | 35.6% |
| table_to_table | 18 | 100.0% | 11.1% |
| table_to_prose | 18 | 0.0% | 0.0% |

The rows above use the active generic text relation path. A separate call to the real structured table analyzer/diff produced:

- Table-to-table structured accuracy / macro-F1: **50.0% / 7.4%** over **18** pairs.

## Safety

- False automatic embedding reuse: **0 (0.0%)**.
- Conflict false negatives / false positives (oracle-pair): **36 / 74** (**33.3% / 15.0%**).
- Conflict pairs eligible for automatic reuse: **0**.
- Strict-exact pairs blocked from reuse because embedding input checksum changed: **40**.

## Failure attribution

Primary end-to-end attribution (candidate miss takes precedence):

- `CANDIDATE_MISS`: **281**
- `ENTITY_RESOLUTION_ERROR`: **45**
- `CLASSIFIER_THRESHOLD_ERROR`: **32**
- `SCOPE_ERROR`: **25**
- `NEGATION_ERROR`: **8**
- `OCR_EXTRACTION_ERROR`: **7**
- `CROSS_CHUNK_CONTEXT_MISSING`: **3**
- `OPERATOR_RANGE_ERROR`: **2**

Oracle-pair classifier attribution (candidate stage bypassed):

- `ENTITY_RESOLUTION_ERROR`: **120**
- `CLASSIFIER_THRESHOLD_ERROR`: **117**
- `SCOPE_ERROR`: **65**
- `OCR_EXTRACTION_ERROR`: **20**
- `NEGATION_ERROR`: **18**
- `TABLE_PROSE_GAP`: **18**
- `CROSS_CHUNK_CONTEXT_MISSING`: **10**
- `OPERATOR_RANGE_ERROR`: **7**

### Representative failures

#### CANDIDATE_MISS

- `VF_CONDITIONAL_VARIANT_0003` (test_protocol): expected `CONDITIONAL_VARIANT`, oracle `DISTINCT`, runtime `None`; A: 'VF 8 Eco có tầm 450 km theo WLTP.'; B: 'VF 8 Eco có tầm 420 km theo EPA.'.
- `VF_CONDITIONAL_VARIANT_0007` (trim_variant): expected `CONDITIONAL_VARIANT`, oracle `DISTINCT`, runtime `None`; A: 'VF 8 với điều kiện trim_variant A có giá trị tham chiếu 439.'; B: 'VF 8 với điều kiện trim_variant B có giá trị tham chiếu 469.'.
- `VF_CONDITIONAL_VARIANT_0008` (market_variant): expected `CONDITIONAL_VARIANT`, oracle `DISTINCT`, runtime `None`; A: 'VF 9 với điều kiện market_variant A có giá trị tham chiếu 452.'; B: 'VF 9 với điều kiện market_variant B có giá trị tham chiếu 482.'.
- `VF_CONDITIONAL_VARIANT_0009` (test_protocol): expected `CONDITIONAL_VARIANT`, oracle `DISTINCT`, runtime `None`; A: 'VF 6 Base có tầm 450 km theo WLTP.'; B: 'VF 6 Base có tầm 420 km theo EPA.'.
- `VF_CONDITIONAL_VARIANT_0012` (price_type): expected `CONDITIONAL_VARIANT`, oracle `DISTINCT`, runtime `None`; A: 'VF 9 với điều kiện price_type A có giá trị tham chiếu 505.'; B: 'VF 9 với điều kiện price_type B có giá trị tham chiếu 535.'.

#### ENTITY_RESOLUTION_ERROR

- `VF_DISTINCT_0001` (same_value_different_model): expected `DISTINCT`, oracle `CONFLICT`, runtime `CONFLICT`; A: 'VF 6 Eco có tầm tham chiếu 360 km theo WLTP.'; B: 'VF 7 Eco có tầm tham chiếu 360 km theo WLTP.'.
- `VF_DISTINCT_0002` (same_value_different_model): expected `DISTINCT`, oracle `CONFLICT`, runtime `CONFLICT`; A: 'VF 7 Eco có tầm tham chiếu 373 km theo WLTP.'; B: 'VF 8 Eco có tầm tham chiếu 373 km theo WLTP.'.
- `VF_DISTINCT_0003` (same_value_different_model): expected `DISTINCT`, oracle `CONFLICT`, runtime `CONFLICT`; A: 'VF 8 Eco có tầm tham chiếu 386 km theo WLTP.'; B: 'VF 9 Eco có tầm tham chiếu 386 km theo WLTP.'.
- `VF_DISTINCT_0004` (same_value_different_model): expected `DISTINCT`, oracle `CONFLICT`, runtime `CONFLICT`; A: 'VF 9 Eco có tầm tham chiếu 399 km theo WLTP.'; B: 'VF 6 Eco có tầm tham chiếu 399 km theo WLTP.'.
- `VF_DISTINCT_0005` (same_value_different_model): expected `DISTINCT`, oracle `CONFLICT`, runtime `None`; A: 'VF 6 Plus có tầm tham chiếu 413 km theo WLTP.'; B: 'VF 7 Plus có tầm tham chiếu 413 km theo WLTP.'.

#### CLASSIFIER_THRESHOLD_ERROR

- `VF_VERSION_UPDATE_0001` (added_information): expected `VERSION_UPDATE`, oracle `DISTINCT`, runtime `DISTINCT`; A: 'VF 6 Eco đời 2023 tại Việt Nam có tầm tham chiếu 360 km theo WLTP.'; B: 'VF 6 Eco đời 2023 tại Việt Nam có tầm tham chiếu 360 km theo WLTP. Bản cập nhật bổ sung mô tả cổng sạc thử nghiệm và gói hỗ trợ dịch vụ số 1.'.
- `VF_VERSION_UPDATE_0002` (added_information): expected `VERSION_UPDATE`, oracle `DISTINCT`, runtime `None`; A: 'VF 7 Eco đời 2023 tại Việt Nam có tầm tham chiếu 373 km theo WLTP.'; B: 'VF 7 Eco đời 2023 tại Việt Nam có tầm tham chiếu 373 km theo WLTP. Bản cập nhật bổ sung mô tả cổng sạc thử nghiệm và gói hỗ trợ dịch vụ số 2.'.
- `VF_VERSION_UPDATE_0003` (added_information): expected `VERSION_UPDATE`, oracle `DISTINCT`, runtime `DISTINCT`; A: 'VF 8 Eco đời 2023 tại Việt Nam có tầm tham chiếu 386 km theo WLTP.'; B: 'VF 8 Eco đời 2023 tại Việt Nam có tầm tham chiếu 386 km theo WLTP. Bản cập nhật bổ sung mô tả cổng sạc thử nghiệm và gói hỗ trợ dịch vụ số 3.'.
- `VF_VERSION_UPDATE_0004` (added_information): expected `VERSION_UPDATE`, oracle `DISTINCT`, runtime `None`; A: 'VF 9 Eco đời 2023 tại Mỹ có tầm tham chiếu 399 km theo WLTP.'; B: 'VF 9 Eco đời 2023 tại Mỹ có tầm tham chiếu 399 km theo WLTP. Bản cập nhật bổ sung mô tả cổng sạc thử nghiệm và gói hỗ trợ dịch vụ số 4.'.
- `VF_VERSION_UPDATE_0005` (added_information): expected `VERSION_UPDATE`, oracle `DISTINCT`, runtime `None`; A: 'VF 6 Plus đời 2023 tại Mỹ có tầm tham chiếu 413 km theo WLTP.'; B: 'VF 6 Plus đời 2023 tại Mỹ có tầm tham chiếu 413 km theo WLTP. Bản cập nhật bổ sung mô tả cổng sạc thử nghiệm và gói hỗ trợ dịch vụ số 5.'.

#### SCOPE_ERROR

- `VF_CONDITIONAL_VARIANT_0001` (trim_variant): expected `CONDITIONAL_VARIANT`, oracle `DISTINCT`, runtime `DISTINCT`; A: 'VF 6 với điều kiện trim_variant A có giá trị tham chiếu 360.'; B: 'VF 6 với điều kiện trim_variant B có giá trị tham chiếu 390.'.
- `VF_CONDITIONAL_VARIANT_0002` (market_variant): expected `CONDITIONAL_VARIANT`, oracle `DISTINCT`, runtime `DISTINCT`; A: 'VF 7 với điều kiện market_variant A có giá trị tham chiếu 373.'; B: 'VF 7 với điều kiện market_variant B có giá trị tham chiếu 403.'.
- `VF_CONDITIONAL_VARIANT_0003` (test_protocol): expected `CONDITIONAL_VARIANT`, oracle `DISTINCT`, runtime `None`; A: 'VF 8 Eco có tầm 450 km theo WLTP.'; B: 'VF 8 Eco có tầm 420 km theo EPA.'.
- `VF_CONDITIONAL_VARIANT_0004` (charging_condition): expected `CONDITIONAL_VARIANT`, oracle `CONFLICT`, runtime `CONFLICT`; A: 'VF 9 Eco sạc từ 10% lên 70% trong khoảng 25 phút.'; B: 'VF 9 Eco sạc từ 10% lên 80% trong khoảng 25 phút.'.
- `VF_CONDITIONAL_VARIANT_0005` (battery_variant): expected `CONDITIONAL_VARIANT`, oracle `DISTINCT`, runtime `DISTINCT`; A: 'VF 6 với điều kiện battery_variant A có giá trị tham chiếu 413.'; B: 'VF 6 với điều kiện battery_variant B có giá trị tham chiếu 443.'.

#### OCR_EXTRACTION_ERROR

- `VF_UNCERTAIN_0001` (ocr_year_and_value_corruption): expected `UNCERTAIN`, oracle `DISTINCT`, runtime `None`; A: 'VF 6 Eco đời 2023 có tầm 360 km theo WLTP.'; B: 'VF 6 Eco đời 2O26 có tầm 36O km theo WLTP.'.
- `VF_UNCERTAIN_0003` (ocr_decimal_loss): expected `UNCERTAIN`, oracle `DISTINCT`, runtime `None`; A: 'VF 8 Eco có dung lượng pin 87,7 kWh.'; B: 'VF 8 Eco có dung lượng pin 877 kWh do OCR không chắc chắn.'.
- `VF_UNCERTAIN_0004` (ocr_year_and_value_corruption): expected `UNCERTAIN`, oracle `DISTINCT`, runtime `None`; A: 'VF 9 Eco đời 2023 có tầm 399 km theo WLTP.'; B: 'VF 9 Eco đời 2O26 có tầm 39O km theo WLTP.'.
- `VF_UNCERTAIN_0006` (ocr_decimal_loss): expected `UNCERTAIN`, oracle `DISTINCT`, runtime `DISTINCT`; A: 'VF 7 Plus có dung lượng pin 87,7 kWh.'; B: 'VF 7 Plus có dung lượng pin 877 kWh do OCR không chắc chắn.'.
- `VF_UNCERTAIN_0007` (ocr_year_and_value_corruption): expected `UNCERTAIN`, oracle `DISTINCT`, runtime `None`; A: 'VF 8 Plus đời 2023 có tầm 439 km theo EPA.'; B: 'VF 8 Plus đời 2O26 có tầm 43O km theo EPA.'.

#### NEGATION_ERROR

- `VF_CONFLICT_0003` (feature_negation): expected `CONFLICT`, oracle `DISTINCT`, runtime `DISTINCT`; A: 'VF 8 Eco đời 2023 có tính năng hỗ trợ giữ làn thử nghiệm.'; B: 'VF 8 Eco đời 2023 không được trang bị hỗ trợ giữ làn thử nghiệm.'.
- `VF_CONFLICT_0009` (feature_negation): expected `CONFLICT`, oracle `DISTINCT`, runtime `None`; A: 'VF 6 Base đời 2024 có tính năng hỗ trợ giữ làn thử nghiệm.'; B: 'VF 6 Base đời 2024 không được trang bị hỗ trợ giữ làn thử nghiệm.'.
- `VF_CONFLICT_0015` (feature_negation): expected `CONFLICT`, oracle `DISTINCT`, runtime `None`; A: 'VF 8 Premium đời 2025 có tính năng hỗ trợ giữ làn thử nghiệm.'; B: 'VF 8 Premium đời 2025 không được trang bị hỗ trợ giữ làn thử nghiệm.'.
- `VF_CONFLICT_0021` (feature_negation): expected `CONFLICT`, oracle `DISTINCT`, runtime `None`; A: 'VF 6 Plus đời 2025 có tính năng hỗ trợ giữ làn thử nghiệm.'; B: 'VF 6 Plus đời 2025 không được trang bị hỗ trợ giữ làn thử nghiệm.'.
- `VF_CONFLICT_0027` (feature_negation): expected `CONFLICT`, oracle `DISTINCT`, runtime `None`; A: 'VF 8 Base đời 2026 có tính năng hỗ trợ giữ làn thử nghiệm.'; B: 'VF 8 Base đời 2026 không được trang bị hỗ trợ giữ làn thử nghiệm.'.

#### TABLE_PROSE_GAP

- `VF_CONFLICT_0004` (table_to_prose_conflict): expected `CONFLICT`, oracle `DISTINCT`, runtime `None`; A: 'Mã | Biến thể | Ngày hiệu lực | Tầm hoạt động\nVF 9 | Eco | 2023-01-01 | 399 km WLTP'; B: 'VF 9 Eco đời 2023 tại Mỹ có tầm 429 km theo WLTP.'.
- `VF_CONFLICT_0010` (table_to_prose_conflict): expected `CONFLICT`, oracle `DISTINCT`, runtime `None`; A: 'Mã | Biến thể | Ngày hiệu lực | Tầm hoạt động\nVF 7 | Base | 2024-01-01 | 479 km EPA'; B: 'VF 7 Base đời 2024 tại Canada có tầm 509 km theo EPA.'.
- `VF_CONFLICT_0016` (table_to_prose_conflict): expected `CONFLICT`, oracle `DISTINCT`, runtime `None`; A: 'Mã | Biến thể | Ngày hiệu lực | Tầm hoạt động\nVF 9 | Premium | 2025-01-01 | 368 km WLTP'; B: 'VF 9 Premium đời 2025 tại Mỹ có tầm 398 km theo WLTP.'.
- `VF_CONFLICT_0022` (table_to_prose_conflict): expected `CONFLICT`, oracle `DISTINCT`, runtime `None`; A: 'Mã | Biến thể | Ngày hiệu lực | Tầm hoạt động\nVF 7 | Plus | 2026-01-01 | 448 km EPA'; B: 'VF 7 Plus đời 2026 tại Canada có tầm 478 km theo EPA.'.
- `VF_CONFLICT_0028` (table_to_prose_conflict): expected `CONFLICT`, oracle `DISTINCT`, runtime `None`; A: 'Mã | Biến thể | Ngày hiệu lực | Tầm hoạt động\nVF 9 | Base | 2026-01-01 | 527 km NEDC'; B: 'VF 9 Base đời 2026 tại Mỹ có tầm 557 km theo NEDC.'.

#### CROSS_CHUNK_CONTEXT_MISSING

- `VF_UNCERTAIN_0002` (cross_chunk_reference): expected `UNCERTAIN`, oracle `CONFLICT`, runtime `CONFLICT`; A: 'Đối với phiên bản Eco của mẫu xe này, tầm hoạt động là 373 km.'; B: 'Đối với phiên bản Eco của mẫu xe này, tầm hoạt động là 403 km.'.
- `VF_UNCERTAIN_0005` (cross_chunk_reference): expected `UNCERTAIN`, oracle `CONFLICT`, runtime `CONFLICT`; A: 'Đối với phiên bản Plus của mẫu xe này, tầm hoạt động là 413 km.'; B: 'Đối với phiên bản Plus của mẫu xe này, tầm hoạt động là 443 km.'.
- `VF_UNCERTAIN_0008` (cross_chunk_reference): expected `UNCERTAIN`, oracle `CONFLICT`, runtime `None`; A: 'Đối với phiên bản Plus của mẫu xe này, tầm hoạt động là 452 km.'; B: 'Đối với phiên bản Plus của mẫu xe này, tầm hoạt động là 482 km.'.
- `VF_UNCERTAIN_0011` (cross_chunk_reference): expected `UNCERTAIN`, oracle `CONFLICT`, runtime `CONFLICT`; A: 'Đối với phiên bản Base của mẫu xe này, tầm hoạt động là 492 km.'; B: 'Đối với phiên bản Base của mẫu xe này, tầm hoạt động là 522 km.'.
- `VF_UNCERTAIN_0014` (cross_chunk_reference): expected `UNCERTAIN`, oracle `CONFLICT`, runtime `None`; A: 'Đối với phiên bản Premium của mẫu xe này, tầm hoạt động là 532 km.'; B: 'Đối với phiên bản Premium của mẫu xe này, tầm hoạt động là 562 km.'.

#### OPERATOR_RANGE_ERROR

- `VH_CONDITIONAL_VARIANT_0010` (operator_range_approx): expected `CONDITIONAL_VARIANT`, oracle `DISTINCT`, runtime `None`; A: 'Giá căn shophouse tại Vinhomes Project Epsilon năm 2024 là trong khoảng 5,8–6,4 tỷ.'; B: 'Giá căn shophouse tại Vinhomes Project Epsilon năm 2024 là xấp xỉ 6,2 tỷ.'.
- `VH_CONDITIONAL_VARIANT_0011` (operator_from_at_most): expected `CONDITIONAL_VARIANT`, oracle `DISTINCT`, runtime `DISTINCT`; A: 'Giá căn biệt thự tại Vinhomes Project Alpha năm 2024 là từ 5,8 tỷ.'; B: 'Giá căn biệt thự tại Vinhomes Project Alpha năm 2024 là không quá 6,5 tỷ.'.
- `VH_CONDITIONAL_VARIANT_0012` (operator_at_least_range): expected `CONDITIONAL_VARIANT`, oracle `DISTINCT`, runtime `None`; A: 'Giá căn biệt thự tại Vinhomes Project Beta năm 2024 là ít nhất 5,5 tỷ.'; B: 'Giá căn biệt thự tại Vinhomes Project Beta năm 2024 là trong khoảng 5,8–6,4 tỷ.'.
- `VH_CONDITIONAL_VARIANT_0023` (operator_range_approx): expected `CONDITIONAL_VARIANT`, oracle `DISTINCT`, runtime `None`; A: 'Giá căn shophouse tại Vinhomes Project Gamma năm 2026 là trong khoảng 5,8–6,4 tỷ.'; B: 'Giá căn shophouse tại Vinhomes Project Gamma năm 2026 là xấp xỉ 6,2 tỷ.'.
- `VH_CONDITIONAL_VARIANT_0024` (operator_from_at_most): expected `CONDITIONAL_VARIANT`, oracle `DISTINCT`, runtime `None`; A: 'Giá căn shophouse tại Vinhomes Project Delta năm 2026 là từ 5,8 tỷ.'; B: 'Giá căn shophouse tại Vinhomes Project Delta năm 2026 là không quá 6,5 tỷ.'.

## Stress tests

- Long-document meaningful-position recall: **20.0%**; sampled positions: `[1, 15, 29, 43, 58, 72, 86, 100]`.
- SimHash counterexample: Hamming **21** <= 24, aligned-band overlap **0**, candidate generated: **False**.

## Explicit limits

- ANN candidate quality is unmeasured because the production path requires external OpenAI embeddings and this run is offline.
- The code default for structured facts is `off`; a separate deterministic table-to-table capability diagnostic is reported, while table-to-prose has no structured bridge.
- See the JSON report for the full confusion matrix and all 600 pair-level diagnostics.
