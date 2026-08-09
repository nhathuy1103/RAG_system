# Báo cáo ablation field lọc trước retrieval

## 1. Kết luận điều hành

Trên 110 query có structured filter, full domain filter đạt:

- Recall@5: **100%** trên 80 query answerable.
- MRR@10: **90,625%**.
- NDCG@10: **93,041%**.
- Null rejection@10: **100%** trên 30 query null.
- Forbidden top-1 rate: **0%**.

Bỏ toàn bộ năm domain filter làm:

- Recall@5 giảm từ 100% xuống **93,75%**: -6,25 điểm phần trăm,
  CI95 theo query [-12,50; -1,25], p=0,0624; CI95 theo 53 cụm scenario
  [-13,415; -1,190], p=0,1268, W/T/L=0/75/5.
- MRR@10 giảm từ 90,625% xuống **73,121%**: -17,504 điểm,
  CI95 theo query [-24,041; -11,270], p=0,0002; CI95 theo scenario
  [-22,533; -12,447], p=0,0002.
- NDCG@10 giảm từ 93,041% xuống **79,173%**: -13,867 điểm,
  CI95 theo query [-19,109; -8,981], p=0,0002; CI95 theo scenario
  [-18,141; -9,865], p=0,0002.
- Null rejection giảm từ 100% xuống **0%**: 30/30 case null thất bại,
  CI95 theo query và scenario đều [-100; -100], p=0,0002.
- Forbidden top-1 tăng từ 0% lên **10%**; CI95 theo scenario [3,75; 17,333],
  p=0,0166.
- Local retrieval p50 tăng từ 5,139 ms lên 37,807 ms. Đây là latency in-memory,
  không thay thế benchmark PostgreSQL/Qdrant production.

Kết luận: structured metadata filter là cần thiết. Giá trị mạnh nhất trong benchmark hiện tại
nằm ở **project identity**, **temporal validity** và tổ hợp nhiều điều kiện.

## 2. Thiết kế thí nghiệm

Bảy mode dùng cùng:

- Frozen testset SHA-256 `e0173d337a62060775ceae2833989d5f831f85bd585c6d8d129d925ba2d6e497`.
- Snapshot 277 chunk từ 9 tài liệu thật của run context-quality v4.
- Deterministic header B cho embedding và BM25.
- OpenAI `text-embedding-3-small`; 562 cache hit, 0 embedding mới.
- Candidate K=20, top K=10, RRF K=60, MMR lambda=0,7, 3 lượt retrieval.
- 5.000 mẫu paired bootstrap và sign-flip permutation ở hai cấp: từng query và cụm
  `scenario_id`, để các biến thể của cùng một kịch bản không bị coi là quan sát độc lập.

`filter_full` giữ đủ năm field. Mỗi leave-one-field-out mode chỉ bỏ điều kiện của đúng một
field; `filter_drop_all_domain` bỏ cả năm. Frozen testset và gold không bị sửa.

## 3. Kết quả theo field

### `project_name`: field tạo giá trị xếp hạng rõ nhất

Trên đúng 80 query dùng project, gồm 50 answerable và 30 null:

| Metric | Full | Bỏ project | Delta | CI95 scenario | p scenario |
|---|---:|---:|---:|---:|---:|
| Recall@5 | 100% | 96% | -4,00 điểm | [-10,417; 0,00] | 0,5083 |
| MRR@10 | 95,00% | 78,002% | **-16,998 điểm** | [-25,885; -9,518] | **0,0002** |
| NDCG@10 | 96,309% | 83,448% | **-12,861 điểm** | [-19,569; -7,206] | **0,0002** |
| Null rejection@10 | 100% | 100% | 0 | [0; 0] | 1,0 |

`project_name` chủ yếu đẩy đúng project lên sớm hơn. Recall@5 chỉ mất 2/50 answerable nên chưa
có ý nghĩa theo permutation, nhưng MRR/NDCG giảm mạnh và nhất quán.

Production không nên equality trực tiếp trên tên tự do. Benchmark có 34 cách gọi project,
gồm tên có/không có tiền tố `Vinhomes`. Nên dùng `project_code` canonical làm filter key và
`project_name`/aliases cho query resolution.

### `year`: field quyết định null rejection

Trên 70 query dùng year, gồm 40 answerable và 30 null:

| Metric | Full | Bỏ year | Delta | CI95 scenario | p scenario |
|---|---:|---:|---:|---:|---:|
| Recall@5 | 100% | 100% | 0 | [0; 0] | 1,0 |
| MRR@10 | 97,50% | 96,25% | -1,25 điểm | [-3,846; 0] | 1,0 |
| Null rejection@10 | 100% | **0%** | **-100 điểm** | [-100; -100] | **0,0002** |

Không có `year`, cả 30 câu hỏi về năm không tồn tại vẫn nhận candidate. Vì vậy `year` không
chỉ tối ưu ranking; nó là correctness gate để hệ thống biết “không có dữ liệu”. Field phải là
integer typed và phải phân biệt `year`, `data_period`, `as_of_date`.

### `lifecycle_status`: tín hiệu rủi ro, chưa đủ chốt độc lập

Trên 40 query answerable dùng lifecycle:

| Metric | Full | Bỏ lifecycle | Delta | CI95 scenario | p scenario |
|---|---:|---:|---:|---:|---:|
| Recall@5 | 100% | 100% | 0 | [0; 0] | 1,0 |
| MRR@10 | 83,75% | 80,417% | -3,333 điểm | [-6,838; -0,427] | 0,1226 |
| NDCG@10 | 87,927% | 85,427% | -2,50 điểm | [-5,087; -0,336] | 0,1226 |

Chỉ 4 query giảm hạng nên cả query-level và scenario-clustered CI đều âm, nhưng permutation
vẫn chưa dưới 0,05. Giữ field này trong P1 nghiên cứu; cần thêm version-conflict scenarios
trước khi chốt.
`latest` phải được derive lại khi có version mới, không nên lấy từ output LLM tự do.

### `document_type`: chưa có giá trị tăng thêm trong bộ query hiện tại

Trên 90 query dùng document type:

- Recall@5 và null rejection không đổi, đều 100%.
- MRR@10 tăng nhẹ 0,972 điểm khi bỏ field, CI [0; 2,778], p=0,4863.

Field này đang đồng xuất hiện với project/year/source hoặc lifecycle, và deterministic header B
đã chứa document type. Kết quả chỉ chứng minh filter này **dư thừa trong frozen test hiện tại**,
không chứng minh document type vô dụng cho routing hay corpus khác.

### `source`: benchmark hiện không đủ sức phân biệt

Trên 30 query source, mọi metric giữ nguyên 100%. Cả 30 condition chỉ dùng một giá trị
`Vinhomes Market và nguồn công khai` và luôn đi cùng document type, project và year. Do đó không
được kết luận source là không cần; cần thêm nhiều source value và conflict cases.

## 4. Quyết định field

| Mức | Field | Quyết định |
|---|---|---|
| P0 | `owner_id`, `notebook_id`, `document_ids` | Giữ fail-closed như production hiện tại |
| P1 | `project_code` + alias resolution | Ưu tiên extractor/index đầu tiên; bằng chứng ranking mạnh |
| P1 | `year`, `data_period`, `as_of_date` | Ưu tiên; year bắt buộc cho null rejection |
| P1 nghiên cứu | `document_version`, `lifecycle_status`, `effective_status` | Mở rộng scenario trước khi promote |
| P2 | `document_type` structured filter | Chưa có incremental value; vẫn giữ trong header B |
| P2 | `source_code`, `source` | Mở rộng benchmark trước khi tạo production index |

## 5. Giới hạn phải giữ khi diễn giải

- Ablation dùng gold metadata. Nó chứng minh giá trị của field **khi field đúng**, chưa chứng minh
  current extractor tạo field đúng. Current metadata hiện chỉ có `document_type` 277/277; bốn
  field nghiệp vụ còn lại là 0/277.
- 300 query chỉ thuộc 121 scenario/123 evidence fact. Scorer đã resample theo `scenario_id`;
  chưa có lớp resampling thứ hai theo `evidence_fact_id`, nên các kết luận biên vẫn phải thận trọng.
- Corpus snapshot là tài liệu thật và embedding OpenAI thật, nhưng BM25/RRF/MMR chạy local;
  PostgreSQL FTS tokenization và latency production có thể khác.
- `source` có một distinct query value; `lifecycle_status` chỉ có `latest`. Hai field này cần tập
  test đa dạng hơn.

## 6. Bước triển khai tiếp theo

1. Xây typed extractor cho project identity và temporal metadata.
2. Audit current-vs-gold với precision >=98%, coverage >=95% trên phạm vi áp dụng.
3. Bổ sung clustered robustness check theo `evidence_fact_id` cho các kết luận biên.
4. Mở rộng source/version scenarios.
5. Sau khi extraction đạt gate, mở rộng `RetrievalFilters`, PostgreSQL RPC và Qdrant payload
   indexes; chạy lại cùng ablation bằng current metadata thay cho gold.
