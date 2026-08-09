# Phân tích hệ thống RAG hiện tại

## Phạm vi và mức chắc chắn

Tài liệu này đóng băng **baseline hiện tại**, dựa trên code, migration, cấu hình runtime cục bộ và snapshot read-only ngày 2026-08-03. Không có thay đổi nào đối với production metadata, embedding hay retrieval. Các kết luận về cấu trúc code có độ chắc chắn cao; kết luận về dữ liệu chỉ áp dụng cho snapshot đã export.

Git repository đang ở nhánh `huy_dev` nhưng chưa có `HEAD` hợp lệ (`git rev-parse --verify HEAD` thất bại). Vì vậy không được gán một commit giả cho thí nghiệm. Hai checksum của `uv.lock` và `.env` được lưu trong `experiment_config.yaml`; file `.env` không được sao chép và secret không được ghi ra.

Exporter chỉ dùng HTTP `GET`, không xuất vector embedding và không ghi dữ liệu nguồn. Manifest ghi nhận 24 document, 257 chunk, hoàn tất lúc `2026-08-03T08:16:21.749141+00:00`. Đây là export phân trang best-effort, không phải snapshot transaction của PostgreSQL; vì vậy tính nhất quán liên trang là một giới hạn đã biết.

Snapshot gồm 6 document `ready`, 10 `processing` và 8 `failed`; toàn bộ 257 chunk đều thuộc 6 document `ready`. Exporter cố ý giữ cả document chưa retrievable để audit lifecycle metadata. Production chat chỉ lấy document `ready` qua `ChatService`/`list_by_notebook(status="ready")` tại `app/chat/application/services.py:297-318`.

## Ma trận bằng chứng

| Kết luận | File và symbol | Dòng liên quan | Chắc chắn | Chưa xác định |
|---|---|---:|---|---|
| Runtime settings được đọc từ environment | `app/pipeline/bootstrap/settings.py::_load_settings` | 132-253 | Cao | Giá trị remote secret không được ghi vào baseline |
| Composition thực sự tạo chunker từ settings | `app/pipeline/bootstrap/composition.py::build_ingestion_embedding_pipeline` | 82-114; đặc biệt 93 | Cao | Không |
| Strategy và kích thước được forward trực tiếp | `app/pipeline/indexing/application/chunker.py::Chunker.from_settings` | 174-179 | Cao | Không |
| Boundary contract là structure-aware | `app/pipeline/indexing/application/chunker.py::default_config` | 55-71 | Cao | Chất lượng boundary trên corpus cần audit mẫu |
| LLM context chạy riêng theo chunk | `app/pipeline/indexing/application/pipeline.py::_contextualize_chunks` | 311-381 | Cao | Hosted model revision |
| Dense input prepend structured context | `app/shared/contextual_text.py::build_embedding_text` | 92-110 | Cao | Chất lượng semantic cần human gold |
| Sparse application text có alias/search terms | `app/shared/contextual_text.py::build_search_text` | 113-140 | Cao | Production DB không lưu nguyên rendered string |
| Embedding dùng OpenAI adapter | `app/pipeline/indexing/adapters/embedding_providers.py::OpenAIEmbeddingProvider` | 27-74 | Cao | Hosted model revision; server-side implementation |
| Active vector backend resolve được pgvector | `app/pipeline/bootstrap/composition.py::build_vector_index` | 44-60 | Cao | Remote migration state phải được kiểm tra khi export |
| Dense DB index là HNSW cosine | `supabase/migrations/02_tables.sql` | 203-206 | Cao | Runtime index health/statistics |
| Dense RPC lọc owner/document IDs | `supabase/migrations/06_pgvector_search.sql::match_document_chunks` | 3-49 | Cao | Query planner/runtime latency |
| Sparse adapter gọi PostgreSQL FTS RPC | `app/retrieval/adapters/postgrest_full_text_search.py::PostgrestFullTextRetrievalAdapter` | 19-77 | Cao | Không có BM25 trong path này |
| Sparse rank là `ts_rank_cd`, không phải BM25 | `supabase/migrations/11_contextual_metadata_fts.sql::search_document_chunks_keyword` | 122-195; rank 176/183 | Cao | Không có BM25 parameter để ghi nhận |
| Hybrid fusion là RRF | `app/retrieval/adapters/hybrid_search.py::HybridRetrievalAdapter`; `fusion.py::ReciprocalRankFusion` | 27-105; 10-45 | Cao | Không có static dense/sparse weight |
| Reranker là lexical MMR | `app/retrieval/adapters/mmr_reranker.py::MaximalMarginalRelevanceReranker` | 19-76 | Cao | Không có learned cross-encoder |
| Query context/adaptive là heuristic | `local_contextualizer.py::HeuristicContextualizer`; `local_adaptive.py::HeuristicAdaptiveClassifier` | 28-77; 32-67 | Cao | Không |
| Chat scope current/canonical trước retrieval | `app/chat/application/services.py::_resolve_allowed_document_ids` | 120-146 | Cao | Phụ thuộc completeness của document metadata |
| Confirmed conflict được gắn lên evidence | `app/chat/application/services.py::_annotate_confirmed_conflicts` | 172-194 | Cao | Candidate conflict chưa được coi là confirmed |
| Generation dùng alias citation `SRC-N` | `app/generation/adapters/openai_generator.py::OpenAIAnswerGenerator` | 53-235 | Cao | Prompt chưa có stable version ID |

## Pipeline được chứng minh từ runtime

```text
Upload -> documents + ingestion_job -> download/validate/parse/OCR/sanitize
       -> normalized document fingerprint / knowledge-quality decision
       -> structure_recursive chunking
       -> exact/SimHash-LSH pre-embedding candidate analysis
       -> per-chunk contextual enrichment (LLM, fallback nếu lỗi)
       -> build content + metadata + embedding_text + search_text
       -> OpenAI embedding -> pgvector document_chunks
       -> PostgreSQL FTS + pgvector dense retrieval
       -> RRF -> exact-duplicate collapse -> lexical-shingle MMR
       -> top-k context -> closed-book generation + SRC-N citation
```

### Bằng chứng `structure_recursive` thực sự chạy

1. `.env` cục bộ resolve `CHUNKING_STRATEGY=structure_recursive`, `CHUNK_SIZE=600`, `CHUNK_OVERLAP=80` qua `_load_settings()` tại `app/pipeline/bootstrap/settings.py`.
2. `build_ingestion_pipeline()` tại `app/pipeline/bootstrap/composition.py` khởi tạo `Chunker.from_settings(settings)`; đây là composition path của worker, không phải config chết.
3. `Chunker.from_settings()` tại `app/pipeline/indexing/application/chunker.py` truyền trực tiếp `settings.chunking_strategy` vào constructor.
4. Strategy contract dùng whitespace token, ưu tiên paragraph/sentence/token, giữ table atomic, section là hard boundary và lấy page từ source token đầu tiên. `parent_chunk` hiện không được xây thành cây thực tế.

Kết luận: runtime hiện tại là `structure_recursive`; không có semantic chunker trong đường chạy này.

## Trích xuất và metadata trước embedding

Parser tạo `Document`, `Page`, `Block` và parser metadata. Chunker kế thừa metadata từ document/block rồi thêm identity, vị trí, strategy, checksum và `retrieval_metadata`. `IngestionEmbeddingPipeline._enrich_chunk_contexts()` gọi enricher theo từng chunk. Kết quả LLM chỉ được phép tạo contextual summary/search terms; `ChunkContextEnrichment` tự mô tả đây là semantic additions, **không phải authoritative business metadata**.

Trước embedding, contract logic là:

```json
{
  "content": "văn bản gốc của chunk",
  "metadata": {
    "retrieval_metadata": {
      "title": "...",
      "document_type": "...",
      "section_path": ["..."],
      "contextual_summary": "LLM sinh riêng cho chunk",
      "contextual_search_terms": ["..."]
    },
    "context_enrichment": {
      "status": "generated hoặc fallback",
      "model": "...",
      "prompt_version": "...",
      "input_checksum": "..."
    }
  },
  "embedding_text": "context ngắn + content",
  "search_text": "metadata/search terms + content"
}
```

`content` được giữ riêng để trả lời, citation và fingerprint. `embedding_text` là đầu vào dense embedding. `search_text` tồn tại trong application contract, nhưng production PostgreSQL không lưu nguyên field đó: migration 12 dựng generated `search_vector` trực tiếp từ `content` và các key trong `metadata`.

### Tài liệu lỗi và tài liệu trùng

Worker chỉ commit chunk sau khi embedding hoàn tất và phải có ít nhất một chunk; exception được chuyển sang repository `fail()` tại `app/ingestion/application/worker.py:438-513`. Vì vậy document lỗi vẫn tồn tại để audit nhưng không đi vào tập chunk retrievable trong snapshot này.

Với quality mode `on`, document fingerprint đủ điều kiện auto identity được lookup trong cùng `owner_id` + `notebook_id`, chỉ so với document `ready`/active. Exact normalized-content match gọi `complete_duplicate()` và return trước contextualization/embedding (`app/ingestion/application/worker.py:317-347`; `app/ingestion/adapters/postgrest_repository.py:210-238`). Near-duplicate, version và conflict vẫn là candidate/review evidence; chúng không bị tự động xóa chỉ vì SimHash/LSH giống.

## Kết quả audit snapshot hiện tại

- Toàn bộ 257 chunk có `content`, `page_number`, `section_title`, chunk fingerprint và `exact_duplicate_group_id` hợp lệ.
- Cả 257 chunk đều chứa object `retrieval_metadata`, nhưng object này rỗng; do đó `title`, `document_type`, `language`, `section_path`, `content_kind`, `table_header`, alias và contextual fields có coverage 0% trong snapshot.
- `context_enrichment`, `contextual_summary` và `contextual_search_terms` đều vắng 100%. Code có đường chạy enrichment, nhưng snapshot không chứng minh các chunk hiện hữu đã đi qua hoặc đã được re-index bằng đường chạy đó.
- Document fingerprint v2 (`normalized_content_hash`, `loose_content_signature` và quality evidence tương ứng) chỉ có ở 4/24 document, trong khi chunk fingerprint có ở 257/257 chunk.
- `pre_embedding_quality` có ở 14/257 chunk (5,45%): 5 `exact_content`, 1 `near_duplicate` và 8 `conflict_candidate`. Tám conflict candidate nằm trên 3 source document, với reason code gồm number/unit/negation/date mismatch. Đây là evidence cần review, không phải conflict đã xác nhận.
- Sau khi inventory đủ 125 field, audit không còn field ngoài schema, enum sai, duplicate ID, dangling reference, lỗi temporal, lỗi version hay conflict cấu trúc.
- Kết quả 0 conflict chỉ có nghĩa là không phát hiện xung đột theo các invariant có cấu trúc trong snapshot. Nó không chứng minh 257 nội dung chunk không mâu thuẫn về ngữ nghĩa; việc đó cần gold set và human annotation.

## Embedding và vector index

Runtime dùng OpenAI `text-embedding-3-small`, batch 64, lưu vào `public.document_chunks.embedding vector(1536)`. Adapter không thực hiện bước normalize vector rõ ràng. PostgreSQL tạo HNSW với `vector_cosine_ops`. Revision/checkpoint cụ thể của hosted model không được pin, nên chỉ model name có thể tái lập.

## Sparse retrieval: không phải BM25

Tên adapter cũ `postgrest_bm25_search.py` có thể gây hiểu nhầm, nhưng production composition dùng `PostgrestFullTextRetrievalAdapter`. Migration 11 tạo RPC và xếp hạng `ts_rank_cd(..., 32)`; migration 12 dựng lại generated `tsvector`/GIN để thêm contextual fields. Không có công thức Okapi BM25 trong đường chạy active.

FTS dùng dictionary `simple` và trọng số:

| Weight | Trường |
|---|---|
| A | title |
| B | section title/path, table header, contextual summary |
| C | document type, content kind, keyword aliases, contextual search terms |
| D | chunk content |

Điểm cần lưu ý: dictionary `simple` không stemming tiếng Việt; chất lượng phụ thuộc mạnh vào token bề mặt, alias và contextual search terms.

## Hybrid retrieval và reranking

Candidate mặc định từ runtime là 20 sparse + 20 dense. Hai danh sách được hợp nhất bằng Reciprocal Rank Fusion với `k=60`, sau đó collapse exact duplicate và chạy lexical-shingle MMR (`lambda=0.7`, tối đa 2 chunks/document), trả `top_k=5`.

Hard filter thực sự truyền xuống hai nhánh là `owner_id`, `notebook_id`, và tùy ngữ cảnh `document_ids`. Chat service khi knowledge quality bật chỉ scope tài liệu current/canonical. `document_type`, status và version không phải filter trực tiếp trong RPC retrieval hiện tại. Vì vậy metadata đó có thể ảnh hưởng FTS/rerank/display nhưng không được mô tả sai là hard-filter production.

Query contextualization, rewrite, sufficiency và adaptive retrieval trong code hiện là heuristic. Không có query expansion song song: `FallbackQueryReformulator` chỉ retry bằng phần evidence còn thiếu, hoặc giữ nguyên câu hỏi. Không có bằng chứng các bước này gọi LLM. Agentic loop tối đa ba vòng.

## Generation, citation và conflict

Generator dùng `gpt-4o`, temperature 0, tối đa 1200 output tokens, closed-book. Prompt yêu cầu citation dạng `SRC-N`, abstain khi thiếu bằng chứng và nêu các nguồn xung đột khi conflict prompting bật. Prompt nằm inline và chưa có stable prompt version. Giới hạn token dành riêng cho context không được cấu hình, nên ghi `null`, không suy đoán.

## Rủi ro baseline quan trọng

- Snapshot là export PostgREST phân trang best-effort, không phải database transaction.
- `retrieval_metadata` rỗng trên toàn bộ snapshot, nên các weight A/B/C của FTS và contextual text không nhận được tín hiệu metadata dự kiến.
- Document fingerprint v2 mới phủ 4/24 document; baseline dedup ở cấp document chưa đồng nhất giữa các thế hệ ingestion.
- Model revision cho embedding/context/generation không được pin.
- LLM contextual fields có provenance nhưng độ chính xác chưa có human gold baseline.
- Parser metadata nằm trong JSONB và có thể khác nhau theo parser/file type; database không ép schema cho từng key.
- `title`, `document_type`, `language` có nhiều nguồn/fallback, dễ tạo surface inconsistency trong cùng document.
- `page_number` theo first-source-token chỉ là locator, không chứng minh chunk chỉ thuộc một trang.
- `parent_chunk`/children có trong domain model nhưng pipeline hiện không tạo hierarchy hữu dụng.
- Exact dedup có DB invariant mạnh; near-duplicate/conflict vẫn là candidate/quality decision, không phải chân lý đã human validate.
- PostgreSQL FTS metadata weight có tác động retrieval nhưng thiếu offline relevance benchmark trước/sau.
- Các field security là authoritative từ DB; tuyệt đối không dùng LLM để đoán hoặc sửa.

## Baseline hợp lệ là gì

Một baseline chỉ hợp lệ khi kèm: frozen config, export manifest, schema inventory, 13 audit outputs, sample seed, annotation guide, double annotation/adjudication và accuracy report. Snapshot production đã được audit; sample fixture đi kèm chỉ dùng để kiểm thử công cụ. Accuracy ngữ nghĩa vẫn ở trạng thái chưa kết luận cho tới khi hai annotator và adjudicator hoàn tất nhãn.
