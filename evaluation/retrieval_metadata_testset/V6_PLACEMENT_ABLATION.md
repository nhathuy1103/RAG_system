# Ablation vị trí metadata v6

Thí nghiệm này xác định metadata chuyên ngành nên nằm ở structured filter,
`search_text` hay `embedding_text`. Bộ frozen gold và nội dung query không bị thay đổi.

## Ba cấu hình

Ba mode dùng chung nền `v5_context_terms`. Vì vậy title, section, contextual summary và
contextual search terms giống nhau; chỉ vị trí của domain metadata thay đổi.

| Mode | Structured filter | Domain metadata trong search_text | Domain metadata trong embedding_text |
|---|---:|---:|---:|
| `v6a_filter_only` | Có | Không | Không |
| `v6b_filter_plus_search_text` | Có | Có | Không |
| `v6c_filter_plus_embedding_text` | Có | Không | Có |

Nhóm domain metadata gồm năm, phiên bản, trạng thái hiệu lực, dự án, khu vực, loại thị
trường, nguồn và độ tin cậy. ACL vẫn được áp dụng như nhau cho cả ba mode nhưng không được
tính là domain metadata trong phép so sánh này.

## Tập query chính

`filter_capable` chỉ chọn query có ít nhất một điều kiện tại
`retrieval_filters.metadata_conditions`. Với frozen benchmark hiện tại, tập này có 110 query:

| Slice | Số query |
|---|---:|
| `explicit_filter` | 30 |
| `implicit_filter` | 30 |
| `version_conflict` | 20 |
| `null_insufficient` | 30 |

Trong đó có 80 query answerable dùng cho Recall/MRR và 30 null query dùng cho null rejection.
Các query content-only, table, multi-hop và permission không được dùng để quyết định vị trí
domain metadata, nhưng vẫn được chấm trong báo cáo toàn bộ 300 query để phát hiện regression.

## Chạy miễn phí trước

Từ thư mục gốc repo:

```powershell
.\evaluation\retrieval_metadata_testset\run_v6_placement_ablation.ps1 `
  -EmbeddingProvider hashing `
  -CurrentContextSource base `
  -Repeats 3 `
  -BootstrapSamples 5000
```

Hashing không gọi OpenAI. Kết quả mặc định nằm trong:

```text
evaluation/retrieval_metadata_testset/runs/real-benchmark-v3-v6-placement-hashing
```

## Đọc kết quả

Đọc các file theo thứ tự:

1. `metrics_filter_capable/evaluation_scope.json`: phải có 110 query và đúng bốn slice trên.
2. `metrics_filter_capable/retrieval_metric_summary.csv`: score của từng mode trên cùng tập.
3. `metrics_filter_capable/retrieval_metric_comparison.csv`: delta ghép cặp, CI95 và p-value.
4. `metrics_filter_capable/retrieval_metric_by_slice.csv`: kiểm tra mode thắng ở slice nào.
5. `metrics_all_queries/retrieval_metric_summary.csv`: kiểm tra regression trên toàn bộ 300 query.
6. `metadata_audit.csv`: so sánh token của embedding và search projection.
7. `run_manifest.json`: kiểm tra policy kênh metadata và cấu hình chạy.

Ba comparison chính là:

| Comparison | Ý nghĩa |
|---|---|
| `search_text_minus_filter_only` | Giá trị tăng thêm của lexical search text |
| `embedding_text_minus_filter_only` | Giá trị tăng thêm của semantic embedding text |
| `embedding_text_minus_search_text` | Embedding tốt hơn hay kém hơn search text |

Tất cả mode phải có `filter_preflight_pass_rate = 1.0`. Nếu không đạt, kết quả placement chưa
hợp lệ vì một mode chưa index đủ field để áp dụng cùng filter.

## Quy tắc quyết định

- Nếu ba mode gần bằng nhau và CI95 chứa 0, chọn `v6a_filter_only`.
- Nếu `v6b` tăng Recall/MRR rõ ràng với chi phí search token chấp nhận được, giữ domain metadata
  trong `search_text`.
- Chỉ chọn `v6c` khi nó thắng `v6a` và `v6b` có ý nghĩa, đồng thời mức tăng đủ bù token embedding,
  thời gian index và chi phí re-embed khi metadata thay đổi.
- Nếu mode thắng khác nhau theo slice, tách field policy thay vì đưa toàn bộ domain metadata vào
  một kênh duy nhất.

## Chạy embedding OpenAI

Chỉ chạy sau khi hashing không có lỗi cấu hình:

```powershell
.\evaluation\retrieval_metadata_testset\run_v6_placement_ablation.ps1 `
  -EmbeddingProvider openai `
  -CurrentContextSource base `
  -Repeats 3 `
  -BootstrapSamples 5000
```

Giữ `CurrentContextSource base` để không phát sinh request context enrichment ngoài mục tiêu của
thí nghiệm. OpenAI run được ghi riêng tại `real-benchmark-v3-v6-placement-openai`.
