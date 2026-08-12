# Tích hợp với `nhathuy1103/RAG_system`

Benchmark được đối chiếu với commit `0ad16adb577bf52c7ff5396ef55f1bacd6eae5c7`.

## Taxonomy

Chín `expected_relation` giữ nguyên tên của `configs/evaluation/duplicate_conflict_taxonomy.json`, nên mapping sang `GoldRelation` hiện tại không đổi.

## Khác biệt schema cần xử lý

Schema V1 của repo ép `is_synthetic` là literal `true`, domain chỉ gồm `vinhomes|vinfast`, và không có locator/hash theo từng side. Vì vậy không nên đổi tên V2 thành `gold_v1` hoặc ép 94 observed pair thành synthetic.

Hướng tích hợp an toàn:

1. Thêm model `GoldPairV2` riêng hoặc mở rộng model với version discriminator.
2. Cho phép domain `real_estate`, `mobility_safety`, `cross_domain`.
3. Giữ `side_a/side_b` cùng context; truyền context vào classifier thay vì chỉ `text_a/text_b`.
4. Báo metrics riêng theo `provenance_kind`.
5. Chỉ map `expected_auto_reuse=true` sang đường strict identity.
6. Không dùng TEST để chỉnh threshold.

## Adapter tối thiểu cho classifier hiện tại

Với mỗi pair, dựng input classifier như sau:

```python
left = "\n".join([*pair["side_a"]["context"], pair["side_a"]["text"]])
right = "\n".join([*pair["side_b"]["context"], pair["side_b"]["text"]])
```

Nếu muốn đo gap của isolated-chunk classifier hiện tại, chạy thêm một ablation bỏ context, nhưng phải báo riêng và không dùng nó làm official score.

## Test gate đề xuất

- Validator V2 phải xanh.
- Không có unsafe auto-reuse trên TEST; nếu có, build fail.
- Báo conflict recall cùng Wilson 95% CI và liệt kê mọi missed conflict.
- Báo observed và controlled mutation riêng.
- Mọi cải thiện phải so cùng frozen TEST/build ID.
