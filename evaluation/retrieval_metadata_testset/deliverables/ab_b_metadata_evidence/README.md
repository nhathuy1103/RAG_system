# Gói bằng chứng A → B và B + metadata

Gói này gom các artifact cần để kiểm tra hai quyết định độc lập:

1. **A → B:** từ `chunk-only` sang `deterministic header + chunk`.
2. **B + metadata:** giữ nguyên text projection B và đo tác động của structured metadata pre-filter.

Không dùng kết quả A → B để kết luận hard filter có hiệu quả, vì A và B chỉ khác text được index. Không dùng riêng kết quả B + metadata để bật production, vì field ablation dùng gold metadata.

## 1. Cấu trúc thư mục

```text
ab_b_metadata_evidence/
├── 01_testset/                  Câu hỏi test và chứng nhận frozen benchmark
├── 02_answer_key/               Đáp án retrieval/evidence và bản review
├── 03_results_A_to_B/           Kết quả chunk-only so với deterministic header
├── 04_B_pre_embedding/          Metadata, embedding_text, search_text của B trước embedding
├── 05_results_B_plus_metadata/  Full filter và leave-one-field-out
├── 06_shared_evidence/          Corpus, snapshot, policy và báo cáo tổng
├── PACKAGE_MANIFEST.csv         Kích thước và SHA-256 của từng file
└── README.md                    File này
```

## 2. Tập test

File nên mở đầu tiên: `01_testset/test_queries.csv`.

File này có đúng 300 query và chỉ giữ phần input/phân loại, không để đáp án cạnh câu hỏi. Benchmark gồm 10 primary slice, mỗi slice 30 query; 255 query answerable và 45 case null/permission-denied.

Các file đi kèm:

- `benchmark_manifest.json`: quy mô, distribution, source fingerprint và giới hạn benchmark;
- `approval.json`: xác nhận 300 case đã human-review và SHA-256 của frozen gold;
- `slice_distribution.csv`: kiểm tra mỗi capability slice đủ số lượng tối thiểu.

## 3. Tập đáp án

Answer key chính là `02_answer_key/answer_key.jsonl`. Mỗi dòng ghép bằng `query_id` với tập test và chứa:

- relevant chunk/document IDs;
- evidence groups cho multi-hop;
- expected terms;
- citation bắt buộc/cấm;
- metadata conditions;
- response class, null và permission target.

`answer_key_review.csv` là cùng đáp án ở dạng bảng dễ đọc. `ground_truth_audit.csv` chứng minh toàn bộ 300 case resolve được sang corpus của run, không có unresolved case.

`gold_metadata_oracle.json` **không phải đáp án câu hỏi**. Đây là metadata chuẩn dùng để đo mức trần và field ablation.

## 4. Kết quả A → B

Đọc theo thứ tự:

1. `03_results_A_to_B/metric_summary_A_B.csv`;
2. `03_results_A_to_B/metric_comparison_A_B.csv`;
3. `03_results_A_to_B/metric_by_slice_A_B.csv`;
4. `03_results_A_to_B/metric_details_A_B.csv` nếu cần truy một query;
5. `03_results_A_to_B/retrieval_results_A_B.jsonl` nếu cần xem top-10 chunk thô.

Hai mode:

| Mode | Input retrieval |
|---|---|
| `ctx_a_chunk_only` | Chỉ chunk text |
| `ctx_b_deterministic_header` | Title, document type, semantic section, content kind/table header + chunk |

Kết quả chính:

| Metric | A | B | Delta |
|---|---:|---:|---:|
| Recall@5 | 64,71% | 96,47% | +31,76 điểm % |
| MRR@10 | 50,56% | 81,83% | +31,27 điểm % |
| NDCG@10 | 56,09% | 86,34% | +30,25 điểm % |
| Multi-hop đủ nhóm@10 | 30,00% | 72,50% | +42,50 điểm % |
| Table success@10 | 53,33% | 100% | +46,67 điểm % |

Paired Recall@5 của B - A có CI95% `[+25,49; +38,04]`, permutation `p=0,0002`.

## 5. B trước embedding

`04_B_pre_embedding/pre_embedding_metadata.html` là bản xem tương tác dễ nhất. Có thể lọc theo tài liệu/content kind và chuyển giữa:

- metadata payload;
- `embedding_text`;
- `search_text`;
- chunk text gốc.

`pre_embedding_metadata.jsonl` chứa đủ 277 row để audit máy; `pre_embedding_metadata.summary.json` chứa coverage tổng hợp. Export này chủ động loại `contextual_summary`, `contextual_search_terms` và `context_enrichment`, nên thể hiện B deterministic thay vì generated context.

## 6. Kết quả B + metadata

Mọi mode trong `05_results_B_plus_metadata` giữ projection B và chỉ thay metadata filter:

- `filter_full`;
- `filter_drop_document_type`;
- `filter_drop_project_name`;
- `filter_drop_year`;
- `filter_drop_lifecycle_status`;
- `filter_drop_source`;
- `filter_drop_all_domain`.

Đọc `FILTER_FIELD_ABLATION_REPORT.md` trước, sau đó dùng `filter_field_decision_summary.csv` để xem delta và kiểm định từng field. `retrieval_results_all_filter_modes.jsonl` là top-10 thô cho 2.100 cặp query × mode.

Trên 110 query filter-capable, full filter đạt Recall@5 100%, MRR@10 90,625%, NDCG@10 93,041% và null rejection 100%. Bỏ toàn bộ domain filter làm Recall@5 còn 93,75%, MRR còn 73,121%, NDCG còn 79,173% và null rejection còn 0%.

Kết luận field:

- project identity có giá trị ranking mạnh khi metadata đúng;
- `year` quyết định null rejection;
- `lifecycle_status` mới có tín hiệu, chưa đủ chốt độc lập;
- `document_type` chưa có incremental value trong tập hiện tại;
- `source` chưa đủ variation để đánh giá.

Đây là gold-metadata ablation. Quyết định production cuối cùng phải đọc thêm `06_shared_evidence/retrieval_metadata_policy.json`: hiện `hard_filter_fields=[]` vì coverage/current-metadata retention chưa qua gate.

## 7. Cách truy một case từ đầu đến cuối

1. Chọn `query_id` trong `01_testset/test_queries.csv`.
2. Tìm cùng ID trong `02_answer_key/answer_key_review.csv`.
3. Xem A và B trong `03_results_A_to_B/metric_details_A_B.csv`.
4. Nếu cần evidence thô, tìm `query_id + mode` trong `retrieval_results_A_B.jsonl`.
5. Tra relevant chunk trong `06_shared_evidence/corpus.jsonl`.
6. Với query có filter, xem các mode tương ứng trong `05_results_B_plus_metadata/metric_details_filter_capable.csv` và raw result.

## 8. Nguồn và tính toàn vẹn

- Frozen testset SHA-256: `e0173d337a62060775ceae2833989d5f831f85bd585c6d8d129d925ba2d6e497`.
- Context run: OpenAI `text-embedding-3-small`, prompt `chunk-context-v4`, seed `20260803`.
- Field ablation: OpenAI embedding, B deterministic header, gold filter metadata.
- `PACKAGE_MANIFEST.csv` cho phép kiểm tra file trong gói có bị thay đổi sau khi đóng gói hay không.
