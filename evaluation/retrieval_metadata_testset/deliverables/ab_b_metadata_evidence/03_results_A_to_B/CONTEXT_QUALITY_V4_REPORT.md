# Báo cáo đánh giá Contextual Retrieval v4

## 1. Tóm tắt điều hành

Lần chạy `real-benchmark-v3-context-quality-v4-openai` đã hoàn tất hợp lệ trên 300 truy vấn, 277 chunk và 7 biến thể retrieval. Benchmark không có ground truth bị thiếu, không có context fallback và tạo đủ 2.100 dòng kết quả (`7 x 300`). Tập benchmark vẫn là bản `frozen_gold`, SHA-256:

`e0173d337a62060775ceae2833989d5f831f85bd585c6d8d129d925ba2d6e497`

Các kết luận chính:

1. **Deterministic header vẫn là baseline production tốt nhất đã được chứng minh chắc chắn.** So với chunk-only, Recall@5 tăng từ 64,71% lên 96,47%, tương đương `+31,76 điểm %`, CI 95% `[+25,49; +38,04]`, `p=0,0002`.
2. **Context v4 đã sửa phần lớn suy giảm của v3**, nhưng raw context khi đưa vào cả dense và sparse vẫn chưa vượt deterministic header. Recall@5 của C là 95,29%, thấp hơn B `1,18 điểm %`; CI cắt 0 và `p=0,5141`.
3. **Sparse-only là biến thể raw khả quan nhất:** Recall@5 97,25%, MRR@10 82,82%, NDCG@10 87,08%. Các metric đều nhỉnh hơn header nhưng chưa có ý nghĩa thống kê. Đây là ứng viên A/B tiếp theo, chưa phải bằng chứng để đưa thẳng vào production.
4. **Dense-only chưa tạo thêm giá trị rõ ràng:** Recall@5 thấp hơn header 0,39 điểm %, MRR và NDCG gần như không đổi.
5. **Gold/effective context đạt kết quả cao nhất**, nhưng đây là mốc trần chẩn đoán có sử dụng `gold_metadata.contextual_summary`, không phải cấu hình production. Mode này đạt Recall@1 76,86%, Recall@5 97,25%, MRR@10 85,61%, NDCG@10 89,17% và multi-hop all-groups@10 80%.
6. **Context đúng tốt hơn context bị xáo trộn một cách có ý nghĩa:** Recall@5 tăng `4,71 điểm %`, CI `[+1,57; +8,24]`, `p=0,0130`. Điều này chứng minh context mang thông tin theo chunk, không chỉ chứa keyword chung cấp tài liệu.
7. **Điểm yếu còn lại là chất lượng context được sinh.** V4 chỉ sinh summary cho 89/277 chunk, nhưng trong 89 summary này vẫn có 31 summary cần sinh lại và 11 summary bị reject. Có 72/89 summary không đạt điểm “added value”.

Khuyến nghị hiện tại: **giữ deterministic header làm mặc định production và chưa bật full raw context cho cả dense lẫn sparse.** Nếu tiếp tục thử nghiệm, nên ưu tiên `sparse-only` kết hợp quality gate theo từng chunk và đánh giá thêm trên tài liệu ngoài benchmark hiện tại.

## 2. Phạm vi và tính hợp lệ của phép đo

### 2.1. Cấu hình lần chạy

| Thuộc tính | Giá trị |
|---|---:|
| Embedding provider | OpenAI |
| Embedding model | `text-embedding-3-small` |
| Context model | `gpt-4o-mini` |
| Prompt | `chunk-context-v4` |
| Contextual text | `contextual-text-v4` |
| Giới hạn context | 45 từ |
| Số truy vấn | 300 |
| Số chunk | 277 |
| Chunk có gold annotation | 106 |
| Ground truth unresolved | 0 |
| Số mode | 7 |
| Số dòng kết quả | 2.100 |
| Seed | 20260803 |

Manifest đánh dấu lần chạy là `production_comparable=true`. Khác biệt còn lại so với production là BM25/FTS đang chạy local; cách tokenization của PostgreSQL FTS có thể khác.

### 2.2. Cache và cách diễn giải chi phí

- Context cache hit: 271.
- Kết quả context cuối cùng: 89 `generated`, 188 `not_needed`, 0 `fallback`.
- Embedding cache hit: 1.081; embedding mới: 0.
- Estimated new context input tokens: 9.512; embedding input tokens mới: 0.

Đây là lần chạy trên cache ấm. Các số latency retrieval trong báo cáo không phản ánh chi phí ingest lần đầu và không thể dùng trực tiếp để ước tính chi phí API khi khởi tạo một index mới.

### 2.3. Định nghĩa các mode

| Mode | Text được đưa vào retrieval | Vai trò |
|---|---|---|
| A - `ctx_a_chunk_only` | Chunk gốc | Baseline không context |
| B - `ctx_b_deterministic_header` | Title, document type, section, content/table header + chunk | Baseline có cấu trúc |
| C-dense - `ctx_c_raw_context_dense_only` | B + raw summary chỉ trong embedding text | Cô lập kênh dense |
| C-sparse - `ctx_c_raw_context_sparse_only` | B + raw summary chỉ trong BM25 text | Cô lập kênh sparse |
| C - `ctx_c_raw_context` | B + raw summary trong cả dense và sparse | Phương án full raw context |
| D - `ctx_d_effective_context` | B + gold/effective summary | Mốc trần có annotation |
| E - `ctx_e_shuffled_context` | B + summary của chunk khác trong cùng tài liệu | Negative control |

Structured filter metadata được cố định bằng gold cho mọi mode. `contextual_search_terms` không được đưa vào text. Vì vậy, khác biệt retrieval đến từ text được index, không phải do mode này có filter metadata tốt hơn mode kia.

## 3. Kết quả tổng thể

### 3.1. Các metric chính

| Mode | Recall@1 | Recall@3 | Recall@5 | Recall@10 | MRR@10 | NDCG@10 | MH coverage@10 | MH all-groups@10 |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| A: chunk-only | 38,43% | 59,22% | 64,71% | 73,33% | 50,56% | 56,09% | 54,58% | 30,00% |
| B: deterministic header | 70,20% | 90,98% | 96,47% | 100,00% | 81,83% | 86,34% | 87,08% | 72,50% |
| C-dense: raw dense-only | 69,80% | 90,98% | 96,08% | 99,61% | 81,61% | 86,08% | 85,00% | 67,50% |
| C-sparse: raw sparse-only | 71,76% | 90,98% | **97,25%** | 100,00% | 82,82% | 87,08% | 85,42% | 72,50% |
| C: raw cả hai kênh | 69,41% | 89,41% | 95,29% | 99,61% | 80,89% | 85,50% | 83,33% | 67,50% |
| D: gold/effective | **76,86%** | **93,33%** | **97,25%** | 100,00% | **85,61%** | **89,17%** | **90,00%** | **80,00%** |
| E: shuffled | 64,31% | 85,10% | 90,59% | 99,22% | 76,11% | 81,70% | 80,00% | 65,00% |

Cần phân biệt hai cách đọc kết quả:

- Nếu chỉ xét các mode được sinh hoàn toàn từ pipeline hiện tại, C-sparse có điểm tổng thể cao nhất.
- Nếu xét tất cả mode, D cao nhất nhưng có sử dụng gold/effective summary, nên chỉ đại diện cho tiềm năng khi context được curate hoặc gate tốt.

### 3.2. Kiểm định paired

| So sánh | Metric | Delta | CI 95% | W/T/L | p-value | Diễn giải |
|---|---|---:|---:|---:|---:|---|
| B - A | Recall@5 | +31,76 điểm % | [+25,49; +38,04] | 86/164/5 | 0,0002 | Cải thiện rất rõ |
| C-dense - B | Recall@5 | -0,39 điểm % | [-2,35; +1,18] | 2/250/3 | 1,0000 | Không có lợi ích |
| C-sparse - B | Recall@5 | +0,78 điểm % | [0,00; +1,96] | 2/253/0 | 0,4981 | Hướng dương, chưa có ý nghĩa |
| C - B | Recall@5 | -1,18 điểm % | [-3,53; +1,18] | 3/246/6 | 0,5141 | Không vượt baseline |
| D - C | Recall@5 | +1,96 điểm % | [-0,39; +4,71] | 8/244/3 | 0,2188 | Chưa có ý nghĩa ở Recall@5 |
| C - E | Recall@5 | +4,71 điểm % | [+1,57; +8,24] | 16/235/4 | 0,0130 | Context đúng tốt hơn shuffled |

Full raw context C không giảm có ý nghĩa thống kê so với B, nhưng cũng không có bằng chứng cho thấy nó cải thiện retrieval. Kết quả “không có ý nghĩa thống kê” không đồng nghĩa với “đã chứng minh tương đương”; nó chỉ cho biết mẫu hiện tại chưa tách được một delta nhỏ quanh 0.

### 3.3. Chất lượng thứ hạng ngoài Recall@5

So sánh D với C cho thấy chất lượng context tác động mạnh hơn đến thứ tự xếp hạng:

| Metric | C raw | D effective | Delta | CI 95% | p-value |
|---|---:|---:|---:|---:|---:|
| Success@5 | 89,00% | 93,33% | +4,33 điểm % | [+1,33; +7,33] | 0,0084 |
| MRR@10 | 80,89% | 85,61% | +4,73 điểm % | [+1,88; +7,60] | 0,0008 |
| NDCG@10 | 85,50% | 89,17% | +3,66 điểm % | [+1,49; +5,89] | 0,0006 |
| Term hit@5 | 93,53% | 95,98% | +2,45 điểm % | [+0,23; +4,74] | 0,0350 |
| MH coverage@10 | 83,33% | 90,00% | +6,67 điểm % | [+2,08; +11,67] | 0,0304 |
| MH all-groups@10 | 67,50% | 80,00% | +12,50 điểm % | [+2,50; +22,50] | 0,0560 |

Recall@5 của D chưa tách có ý nghĩa khỏi C, nhưng MRR, NDCG, success và multi-hop coverage đều tăng rõ. Context tốt chủ yếu đưa kết quả đúng lên thứ hạng cao hơn, chứ không chỉ thêm một kết quả đúng vào top 5.

## 4. Context tác động lên dense hay sparse?

### 4.1. Kênh dense

C-dense so với B:

- Recall@5: `-0,39 điểm %`.
- MRR@10: `-0,22 điểm %`.
- NDCG@10: `-0,26 điểm %`.
- Multi-hop all-groups@10: `-5,00 điểm %`.

Tất cả CI đều cắt 0. Dữ liệu không cho thấy raw summary giúp embedding semantic. Dấu hiệu hiện tại là summary làm dịch chuyển vector khỏi nội dung gốc, trong khi deterministic header đã mang tín hiệu rất mạnh.

### 4.2. Kênh sparse/BM25

C-sparse so với B:

- Recall@1: `+1,57 điểm %`.
- Recall@5: `+0,78 điểm %`.
- MRR@10: `+0,99 điểm %`.
- NDCG@10: `+0,74 điểm %`.
- Multi-hop all-groups@10: không đổi.

Hướng của các metric chính là tích cực, nhưng p-value Recall@5 bằng 0,4981 và CI chạm 0. Context v4 có vẻ hữu ích hơn dưới dạng lexical expansion ngắn gọn thay vì làm tiền tố cho embedding.

### 4.3. Đưa context vào cả hai kênh

Khi đưa cùng raw summary vào cả dense và sparse, Recall@5 giảm 1,18 điểm %, MRR giảm 0,94 điểm %, NDCG giảm 0,84 điểm % và multi-hop all-groups giảm 5 điểm % so với B.

Kết quả này phù hợp với giả thuyết “double weighting”: cùng một context vừa kéo vector dense, vừa tăng lexical score BM25, sau đó tiếp tục ảnh hưởng đến RRF/MMR. Context tốt có thể được khuếch đại, nhưng context dư thừa hoặc sai entity cũng bị khuếch đại. Đây là suy luận từ ablation, chưa phải phép đo trực tiếp trong scorer.

## 5. Phân tích theo loại truy vấn

Bảng dưới dùng B làm mốc. Delta là thay đổi Recall@5 theo điểm phần trăm.

| Query type | B Recall@5 | C-dense | C-sparse | C raw | D effective | E shuffled |
|---|---:|---:|---:|---:|---:|---:|
| Content only | 86,67% | +6,67 | +6,67 | +3,33 | +3,33 | -10,00 |
| Cross-document confusion | 93,33% | 0,00 | 0,00 | -6,67 | 0,00 | -6,67 |
| Explicit filter | 100,00% | 0,00 | 0,00 | 0,00 | 0,00 | 0,00 |
| Implicit filter | 100,00% | 0,00 | 0,00 | 0,00 | 0,00 | -3,33 |
| Multi-hop | 96,67% | -3,33 | 0,00 | 0,00 | 0,00 | -3,33 |
| Null/insufficient | N/A | 0,00 | 0,00 | 0,00 | 0,00 | 0,00 |
| Permission-sensitive | 93,33% | -6,67 | 0,00 | -13,33 | +6,67 | -26,67 |
| Section localization | 96,67% | 0,00 | 0,00 | +3,33 | 0,00 | -10,00 |
| Table structured | 100,00% | -3,33 | 0,00 | -3,33 | 0,00 | -3,33 |
| Version conflict | 100,00% | 0,00 | 0,00 | 0,00 | 0,00 | 0,00 |

Nhận xét:

- **Content-only** được lợi từ context, phù hợp với mục tiêu bổ sung định danh khi chunk tự thân thiếu ngữ cảnh.
- **Cross-document confusion** và **permission-sensitive** là điểm yếu của full raw context. Summary có thể thêm entity hoặc khái niệm chung, đẩy chunk gần nhưng sai lên trên.
- **Structured filter** đã bão hòa ở Recall@5=100% với B, nên context không còn headroom tại K=5.
- **Table structured** không cần full context khi deterministic table/section header đã đủ. C-sparse giữ nguyên kết quả, trong khi C-dense và C raw làm mất một truy vấn.
- **Multi-hop** không tăng Recall@5, nhưng D tăng MRR và coverage. Chất lượng/curation quan trọng hơn việc chỉ có summary.

Mỗi nhóm chỉ có 30 truy vấn và bảng này không kèm CI riêng theo nhóm, vì vậy không nên xem mỗi delta là một kết luận thống kê độc lập.

## 6. Tập structured-filter-capable

Tập này có 110 truy vấn, gồm 80 truy vấn answerable và 30 truy vấn null.

| Mode | Recall@1 | Recall@3 | Recall@5 | MRR@10 | NDCG@10 |
|---|---:|---:|---:|---:|---:|
| A: chunk-only | 48,75% | 78,75% | 80,00% | 64,66% | 69,76% |
| B: deterministic header | 82,50% | 97,50% | 100,00% | 90,62% | 93,04% |
| C-dense | 83,75% | 97,50% | 100,00% | 91,25% | 93,50% |
| C-sparse | 82,50% | 97,50% | 100,00% | 90,42% | 92,88% |
| C raw | 80,00% | 97,50% | 100,00% | 89,10% | 91,90% |
| D effective | **86,25%** | **98,75%** | 100,00% | **92,40%** | **94,35%** |
| E shuffled | 78,75% | 96,25% | 98,75% | 87,58% | 90,70% |

Recall@5 bị bão hòa nên không phân biệt được B/C/D. MRR và NDCG vẫn cho thấy full raw context làm xếp hạng kém hơn B, còn effective context tốt hơn. D - C có MRR `+3,29 điểm %`, CI `[+0,27; +6,67]`, nhưng permutation `p=0,0592`, sát ngưỡng 0,05 nhưng chưa đạt ngưỡng quy ước.

## 7. Safety và độ ổn định

Tất cả mode đạt:

- Null rejection@10: 100%.
- Permission safe@10: 100%.
- Permission leak@10: 0%.
- Sensitive term leak@10: 0%.
- Empty result rate: 0%.
- Top-1 mojibake rate: 0%.

Từ B đến E, forbidden top-1 rate bằng 0%. Chunk-only A có 0,78%. Context v4 không tạo regression safety trong benchmark này.

Retrieval latency p50 nằm trong khoảng 30,77-33,14 ms và p95 trong khoảng 37,34-42,52 ms. Chênh lệch nhỏ, không có xu hướng tăng rõ theo context. Đây là latency truy vấn local trên cache ấm, không bao gồm context generation hoặc embedding ingestion.

## 8. Chất lượng context v4

### 8.1. Context selection

| Trạng thái | Số chunk | Tỷ lệ |
|---|---:|---:|
| `generated` | 89 | 32,13% |
| `not_needed` | 188 | 67,87% |
| `fallback` | 0 | 0,00% |

Theo source scope:

- Bounded context package: 84 generated, 134 not-needed.
- Whole document: 5 generated, 54 not-needed.

V4 đã thực hiện đúng thay đổi quan trọng: không ép mọi chunk phải có summary. Điều này làm giảm nhiễu và giảm kích thước index so với v3.

### 8.2. Quality gate trên 89 summary đã sinh

| Quyết định | Số summary | Tỷ lệ trên generated |
|---|---:|---:|
| Keep | 9 | 10,11% |
| Keep and monitor | 38 | 42,70% |
| Regenerate | 31 | 34,83% |
| Reject | 11 | 12,36% |

Chỉ 47/89, tương đương 52,81%, được keep hoặc keep-and-monitor. Có 42/89 summary vẫn cần regenerate/reject. Nếu tính trên toàn corpus, hard reject đã giảm còn 11/277 = 3,97%, nhưng tỷ lệ này vẫn chưa phù hợp để tự động index production mà không có gate.

Điểm trung bình trên 89 summary:

| Tiêu chí (0-2) | Điểm trung bình | Số summary điểm 0 |
|---|---:|---:|
| Groundedness | 1,75 | 11/89 |
| Chunk specificity | 1,93 | 2/89 |
| Added value | 0,27 | 72/89 |
| Non-redundancy | 0,85 | 33/89 |
| Completeness | 2,00 | 0/89 |
| Tổng điểm (0-10) | 6,81 | - |

Summary dài trung bình 24,52 từ; P95 của toàn corpus là 30 từ. Không có summary vượt 45 từ, thiếu dấu kết thúc, chứa filename/page locator hoặc boilerplate.

Nút thắt lớn nhất vẫn là **added value**: 80,90% summary đã sinh không thêm được lexical information mà audit coi là mới so với chunk/header. Điều này giải thích vì sao B đã rất mạnh và C không vượt B, dù context đúng vẫn tốt hơn shuffled.

### 8.3. Phân bố theo tài liệu

| Tài liệu | Chunk | Generated | Not-needed | Keep/monitor | Regenerate/reject |
|---|---:|---:|---:|---:|---:|
| Chính sách đổi trả CSKH | 7 | 3 | 4 | 3 | 0 |
| Giá nhà 2023 | 13 | 1 | 12 | 1 | 0 |
| Giá nhà 2024 | 13 | 1 | 12 | 0 | 1 |
| Giá nhà 2025 | 13 | 0 | 13 | 0 | 0 |
| Giá nhà 2026 | 13 | 0 | 13 | 0 | 0 |
| Vinhomes Hải Vân PDF | 69 | 27 | 42 | 12 | 15 |
| Kế hoạch xây dựng | 21 | 8 | 13 | 7 | 1 |
| Vinhomes Tây Mỗ PDF | 76 | 30 | 46 | 10 | 20 |
| Tiện ích toàn quốc | 52 | 19 | 33 | 14 | 5 |

Hai hợp đồng PDF chiếm 57/89 context được sinh, nhưng không có summary nào đạt `keep`; 35 summary cần regenerate/reject. Chunk hợp đồng thường đã chứa đầy đủ nội dung điều khoản, nên summary dễ lặp lại hơn là bổ sung định danh.

Catalog tiện ích có chất lượng tương đối tốt hơn vì summary có thể nối tên dự án/địa bàn vào table chunk. Tuy nhiên, đây cũng là nơi dễ xảy ra lỗi gán nhầm thuộc tính giữa các dự án gần nhau.

### 8.4. Ví dụ định tính và false negative của audit

Ví dụ bị reject hợp lý:

- Chunk `P14 - Vinhomes Ocean Park 3` được tóm tắt thành “Hưng Yên, 458 ha, Royal Wave Park...”. Quy mô 458 ha gắn với Ocean Park 2, không phải P14; audit cho groundedness 0 và reject.
- Một số context hợp đồng dẫn chiếu sai hoặc không đủ căn cứ sang Điều 11/Điều 12 bị groundedness 0 và reject.

Tuy nhiên, audit heuristic vẫn có false negative:

- Chunk `P16 - Vinhomes Smart City` có summary ghi dự án tại “Gia Lâm, Hà Nội”, trong khi metadata/chunk xác định “Nam Từ Liêm, Hà Nội”; audit vẫn chấm 10/10 và `keep`.
- Chunk `P06 - Vinhomes Green Paradise` có summary ghi “đô thị cửa ngõ phía Tây TP.HCM”, một mô tả có dấu hiệu được mượn từ Vinhomes Green City, nhưng vẫn được `keep`.

Nguyên nhân là scorer lexical có thể thấy các token tồn tại đâu đó trong tài liệu/context package, nhưng không kiểm tra ràng buộc `entity -> attribute`. Vì vậy, 9 dòng `keep` không đồng nghĩa với 100% chính xác về ngữ nghĩa.

## 9. Đối chiếu v3 và v4

Đây là so sánh mô tả trên cùng frozen benchmark. Chưa có paired-comparison riêng giữa hai lần chạy, vì vậy không gắn CI/p-value cho delta v3 -> v4.

| Mode | Metric | v3 | v4 | Thay đổi |
|---|---|---:|---:|---:|
| Raw C | Recall@5 | 91,37% | 95,29% | +3,92 điểm % |
| Raw C | MRR@10 | 77,18% | 80,89% | +3,71 điểm % |
| Raw C | NDCG@10 | 81,96% | 85,50% | +3,55 điểm % |
| Raw C | MH all-groups@10 | 52,50% | 67,50% | +15,00 điểm % |
| Effective D | Recall@5 | 96,47% | 97,25% | +0,78 điểm % |
| Effective D | MRR@10 | 84,78% | 85,61% | +0,83 điểm % |
| Effective D | NDCG@10 | 88,36% | 89,17% | +0,80 điểm % |
| Effective D | MH all-groups@10 | 75,00% | 80,00% | +5,00 điểm % |

A và B không đổi trên cả bốn metric, xác nhận benchmark và baseline ổn định. V4 cải thiện raw C rõ nhất ở multi-hop và đưa Recall@5 từ mức suy giảm có ý nghĩa của v3 (`-5,10 điểm %` so với B) về một delta nhỏ, không có ý nghĩa (`-1,18 điểm %`).

Chất lượng summary cũng thay đổi:

| Chỉ báo raw context | v3 | v4 |
|---|---:|---:|
| Summary được sinh | 277 | 89 |
| Not-needed | 0 | 188 |
| Keep + monitor | 78/277 (28,16%) | 47/89 (52,81%) |
| Regenerate + reject | 199/277 (71,84%) | 42/89 (47,19%) |
| Reject | 34/277 (12,27%) | 11/277 (3,97% toàn corpus) |
| Trung bình số từ | 30,69 | 24,52 trên generated |
| Added-value score 0 | 253/277 (91,34%) | 72/89 (80,90%) |
| Non-redundancy score 0 | 173/277 (62,45%) | 33/89 (37,08%) |

Cơ chế `needs_context=false` là thay đổi quan trọng nhất của v4. Nó loại 188 context không cần thiết, giảm dilution và đưa C lại gần B. Tuy nhiên, prompt/validator vẫn chưa giải quyết triệt để redundancy và entity-attribute binding.

## 10. Vì sao context đúng tốt hơn shuffled nhưng vẫn kém header?

Hai kết quả này không mâu thuẫn:

1. B đã đưa title, document type, section và table header vào text, nên phần lớn context hữu ích đã có sẵn.
2. Raw summary đúng chunk vẫn có tín hiệu thật, nên C tốt hơn E shuffled.
3. Summary thường lặp lại chunk/header, thêm rất ít thông tin mới hoặc chèn một thuộc tính có nguy cơ sai entity.
4. Trong dense, phần chèn thêm làm thay đổi hướng embedding; trong sparse, nó thay đổi tần suất và score từ khóa.
5. Khi dùng cả hai kênh, sai số nhỏ có thể bị RRF/MMR khuếch đại và đẩy một chunk đúng khỏi top K.

Nói ngắn gọn: **context v4 có thông tin, nhưng marginal value so với deterministic header chưa đủ lớn và đủ ổn định.**

## 11. Quyết định production đề xuất

### 11.1. Cấu hình mặc định

Đề xuất giữ:

- Deterministic document/section/table header trong dense và sparse.
- Structured metadata làm filter channel riêng.
- `CONTEXTUAL_ENRICHMENT_ENABLED=false` cho đường production mặc định.
- Không đưa raw summary vào cả dense và sparse trên toàn corpus.

Lý do: B đạt Recall@5 96,47%, Recall@10 100%, MRR 81,83%, NDCG 86,34% và multi-hop all-groups 72,5%, với bằng chứng paired rất mạnh so với A. Full C không cải thiện B và có regression cục bộ ở cross-document, permission và table query.

### 11.2. Ứng viên canary

Nếu tiếp tục thử nghiệm, nên dùng `sparse-only` với các điều kiện:

1. Chỉ index summary khi `needs_context=true`.
2. Reject khi quality gate phát hiện sai số, reference không được hỗ trợ hoặc entity mismatch.
3. Không index summary trên hợp đồng nếu nó chỉ paraphrase điều khoản.
4. Cân nhắc chỉ bật cho table/list chunk thiếu project/entity identity.
5. Theo dõi Recall@1, MRR, cross-document confusion và permission-sensitive, không chỉ Recall@5.

C-sparse hiện tăng Recall@5 0,78 điểm %, nhưng CI chạm 0 và `p=0,4981`. Đây là candidate cho benchmark lặp lại/out-of-sample, không phải kết luận production.

### 11.3. Không dùng D như một mode production

D đọc `gold_metadata.contextual_summary`; nó có thông tin annotation/effective mà pipeline raw chưa tự tạo được một cách bảo đảm. D nên được dùng làm:

- Upper bound cho chất lượng context.
- Tập mẫu để học rule hoặc cải tiến prompt.
- Mục tiêu cho human review và quality gate.
- Bằng chứng rằng context được curate có thể tăng chất lượng xếp hạng.

## 12. Thử nghiệm tiếp theo

Thứ tự ưu tiên:

1. **Entity-binding validator:** rút trích cặp `entity -> attribute` từ summary và đối chiếu với chunk/section hiện tại, đặc biệt với project name, region, scale, article number và party.
2. **Quyết định theo content kind:** mặc định not-needed cho prose/hợp đồng đã self-contained; ưu tiên table/list/caption thiếu định danh.
3. **Quality-gated sparse-only:** chỉ đưa 47 summary keep/monitor vào BM25 và so với B, C-sparse-all và shuffled.
4. **Tách keep và monitor:** đo riêng B + keep-only, B + keep/monitor và B + regenerate/reject để xác định quality gate có thực sự dự báo retrieval hay không.
5. **Paired v3-v4 scorer:** tạo comparison trực tiếp trên từng query để có CI và p-value cho mức cải thiện của v4.
6. **Out-of-sample documents:** thêm tài liệu không nằm trong bộ prompt/gold hiện tại để giảm nguy cơ overfit vào 9 tài liệu.
7. **Cold-cache cost run:** đo API call, token, wall time và embedding/index size khi cache rỗng.
8. **PostgreSQL production parity:** lặp lại ứng viên cuối trên PostgreSQL FTS/RRF/MMR thực tế.

Gate promote đề xuất:

- Correct-vs-shuffled dương và CI 95% không cắt 0 cho Recall/MRR.
- Candidate so với B không âm ở Recall@5, MRR, NDCG và multi-hop.
- Không regression ở cross-document confusion, permission-sensitive, null và table.
- Hard reject sau validator bằng 0 trên tập review.
- Lỗi entity-attribute bằng 0 trong human audit với cỡ mẫu đủ lớn.

## 13. Kết luận

V4 là một bước tiến rõ ràng so với v3: hệ thống biết bỏ qua 67,87% chunk không cần context, cắt giảm context dư thừa và khôi phục 3,92 điểm Recall@5 cùng 15 điểm multi-hop all-groups cho raw C. Negative control chứng minh context đúng có giá trị thực.

Tuy nhiên, raw contextual summary vẫn chưa vượt deterministic header một cách đáng tin cậy. Cấu hình tốt nhất có thể triển khai hiện tại vẫn là deterministic header; sparse-only là hướng nghiên cứu tiếp theo. Giá trị lớn nhất của v4 lúc này là xác định đúng bài toán còn lại: không phải sinh summary dài hơn, mà là **chỉ sinh khi thực sự cần, buộc đúng entity và chỉ index summary vượt quality gate**.

## 14. Tệp nguồn

- `run_manifest.json`: cấu hình và tính toàn vẹn của lần chạy.
- `context_quality_audit.csv`: 554 dòng audit raw/effective.
- `context_quality_audit.summary.json`: tổng hợp quality gate.
- `metadata_audit.csv`: độ dài text và coverage metadata.
- `metrics_all_queries/retrieval_metric_summary.csv`: metric tổng theo mode.
- `metrics_all_queries/retrieval_metric_comparison.csv`: paired delta, CI, W/T/L và p-value.
- `metrics_all_queries/retrieval_metric_by_query_type.csv`: metric theo query type.
- `metrics_filter_capable/`: metric của tập structured-filter-capable.
