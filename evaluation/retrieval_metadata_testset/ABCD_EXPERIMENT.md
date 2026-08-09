# A/B/C/D Metadata Retrieval Experiment

Bạn đang muốn làm đúng thiết kế:

- `A - no_metadata`: không dùng metadata.
- `B - current_metadata`: dùng metadata production hiện tại.
- `C - shuffled_metadata`: tráo metadata để làm placebo.
- `D - gold_metadata`: metadata chuyên gia sửa đúng, làm mức trần.

Bộ test hiện tại đã được chỉnh để phù hợp với thiết kế đó.

## 1. Đóng Băng Thí Nghiệm

File config:

```powershell
notepad evaluation\retrieval_metadata_testset\experiment_config.yaml
```

Trong repo hiện tại, chunking đang là `structure_recursive`, `chunk_size=600`, `chunk_overlap=80`, embedding là `text-embedding-3-small`, retrieval là hybrid PostgreSQL FTS + pgvector + RRF.

## 2. Query Set

```powershell
python evaluation\retrieval_metadata_testset\build_testset.py
```

Output:

- `testset.jsonl`
- `evaluation_queries.csv`
- `test_queries.csv`

Mỗi query có `query_id`, `query_type`, `expected_metadata`, `relevant_doc_titles`, `answerable`.

## 3. Chạy 4 Cấu Hình

Runner offline đã dựng sẵn bốn index độc lập và không ghi vào Supabase:

```powershell
.\evaluation\retrieval_metadata_testset\run_complete_evaluation.ps1
```

Lệnh trên chạy proxy miễn phí. Lượt sát production hơn, có phát sinh phí API:

```powershell
.\evaluation\retrieval_metadata_testset\run_complete_evaluation.ps1 `
  -EmbeddingProvider openai `
  -ContextualizeCurrent
```

Context và embedding được cache theo model cùng checksum input. Đổi nội dung chunk,
metadata, model hoặc prompt sẽ tự tạo cache key mới.

Nếu tự cung cấp kết quả từ một retriever khác, dùng format JSONL dưới đây.

Bạn cần tạo cùng một format result JSONL cho mỗi mode:

```json
{"test_id":"tm_010_dispute_60_days","mode":"current_metadata","latency_ms":410,"results":[{"rank":1,"document_title":"Vinhomes_TayMo.pdf","page_number":27,"section_title":"Điều 18. Giải quyết tranh chấp","excerpt":"...60 (sáu mươi) ngày..."}]}
```

Tên mode chuẩn:

- `no_metadata`
- `current_metadata`
- `shuffled_metadata`
- `gold_metadata`

Quan trọng: A/C/D là thí nghiệm thật thì phải rebuild index hoặc chạy offline harness riêng.

- A không được dùng embedding cũ nếu embedding cũ đã có metadata prefix.
- C phải shuffle metadata rồi rebuild `search_text`, `search_vector`, và embedding.
- D giữ nguyên toàn bộ corpus, ghi đè gold metadata trên chunk đã gán nhãn và giữ metadata
  hiện tại cho phần còn lại; sau đó rebuild toàn bộ projection/index. Cách này giữ corpus
  giống A/B/C và vẫn báo rõ tỷ lệ gold coverage.

Runner trên rebuild mọi projection và dense vector độc lập. Nếu chỉ gọi `/chat` hiện tại
thì bạn mới đo được mode B và latency sẽ bao gồm cả generation.

## 4. Chấm Điểm Một Mode Hoặc Nhiều Mode

```powershell
python evaluation\retrieval_metadata_testset\score_retrieval_results.py `
  --results evaluation\retrieval_metadata_testset\retrieval_results.jsonl `
  --output-dir evaluation\retrieval_metadata_testset\results
```

## 5. So Sánh A/B/C/D

Khi `retrieval_results.jsonl` có đủ nhiều dòng cho các mode, chạy:

```powershell
python evaluation\retrieval_metadata_testset\score_experiment_comparison.py `
  --results evaluation\retrieval_metadata_testset\retrieval_results.jsonl `
  --output-dir evaluation\retrieval_metadata_testset\results\abcd
```

Output:

- `retrieval_metric_summary.csv`
- `retrieval_metric_by_query_type.csv`
- `retrieval_metric_comparison.csv`
- `retrieval_metric_details.csv`

Các so sánh mặc định:

- `B_minus_A`: `current_metadata - no_metadata`
- `D_minus_B`: `gold_metadata - current_metadata`
- `B_minus_C`: `current_metadata - shuffled_metadata`

## 6. Diễn Giải

Nếu `B_minus_A > 0`: metadata hiện tại có ích.

Nếu `D_minus_B > 0`: metadata hiện tại còn thiếu/sai, cải thiện được.

Nếu `B_minus_C` không rõ ràng: lợi ích có thể không đến từ ý nghĩa metadata, hoặc query set chưa đủ nhạy.

Nếu `metadata_neutral` giảm mạnh ở B so với A: metadata/filter đang gây hại cho câu hỏi thường.

Nếu `empty_result_rate` tăng ở B: hard filter đang làm mất tài liệu đúng.
