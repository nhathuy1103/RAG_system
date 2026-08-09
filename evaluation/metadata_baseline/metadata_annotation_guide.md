# Hướng dẫn gán nhãn độ chính xác metadata hiện tại

## Mục tiêu

Đánh giá field **đang tồn tại** có phản ánh đúng source hay không. Không đề xuất field mới, không “sửa cho hợp lý” bằng suy đoán, và không dùng output LLM khác làm ground truth.

## Đơn vị và bằng chứng

- Document-level: xem file gốc, record document và lịch sử/version từ hệ thống nguồn.
- Chunk-level: luôn xem `content_excerpt`, title, section cha, chunk trước/sau và document cha.
- Security/lifecycle/version: chỉ dùng dữ liệu authoritative từ database, API nguồn hoặc quyết định đã được duyệt. Không suy từ nội dung.
- Parser field: đối chiếu file render/text và cấu trúc thật.
- Rule/hash field: đối chiếu code/version và input canonical; không đánh giá bằng cảm giác semantic.
- LLM field: chỉ đúng khi được nội dung chunk + context tài liệu hỗ trợ, không thêm fact mới và giúp mô tả đúng phạm vi.

Nếu bằng chứng cần thiết không có trong annotation package, để `is_correct` trống, chọn `error_type=ambiguous`, `confidence=low`, giải thích bằng chứng còn thiếu. Không ép nhãn 0/1.

## Quy trình A/B và adjudication

1. Annotator A điền riêng các cột `annotator_a_*`; Annotator B không xem kết quả A và điền `annotator_b_*`.
2. Giá trị nhiều nhãn phải ghi JSON array, ví dụ `["CTP-2026","công tác phí"]`. Thứ tự không có ý nghĩa; không lặp nhãn.
3. Khi A/B xong, reviewer ghi `agreement`. Nếu khác nhau, reviewer kiểm tra source rồi điền `adjudicated_value`, `adjudicated_is_correct`, `adjudicator`, `adjudication_notes`.
4. Chỉ chuyển `review_status` từ `pending` sang `reviewed` hoặc `adjudicated` khi bằng chứng đã được lưu/ghi rõ.
5. Cột `gold_value`/`is_correct` dùng cho quy trình một annotator hoặc giá trị tổng hợp tương thích cũ; ưu tiên adjudication khi chấm.

## Nhãn chuẩn

`is_correct`: `1` đúng; `0` sai; trống khi chưa/không thể kết luận.

`error_type`:

| Giá trị | Dùng khi |
|---|---|
| `missing` | Source có giá trị xác định nhưng current value thiếu/placeholder |
| `incorrect` | Có giá trị nhưng không khớp bằng chứng |
| `ambiguous` | Bằng chứng không đủ hoặc source tự mâu thuẫn |
| `inconsistent` | Các chunk/record cùng scope dùng nhiều giá trị không hợp lý |
| `outdated` | Giá trị từng đúng nhưng không còn hiệu lực |
| `wrong_version` | Lấy metadata từ phiên bản khác |
| `wrong_scope` | Gắn tenant/notebook/document/source không thuộc record |
| `other` | Lỗi có mô tả nhưng không thuộc nhóm trên |

`confidence`: `high` khi source authoritative rõ; `medium` khi cần diễn giải cấu trúc; `low` khi context thiếu hoặc source mơ hồ.

## Quy tắc field-by-field: document

| Field | Định nghĩa và gold evidence | Đúng / sai / biên |
|---|---|---|
| `original_filename` | Tên file tại upload record | Đúng khi khớp source upload; đổi tên hiển thị về sau không tự làm field sai |
| `mime_type` | MIME đã validate | Đúng theo bytes/validator; extension một mình không đủ |
| `status` | Trạng thái ingestion DB | Chỉ dùng state machine; file đọc được không chứng minh `ready` nếu job chưa hoàn tất |
| `updated_at` | Server timestamp lần cập nhật record | Đối chiếu DB/audit log; không thay bằng ngày sửa nội dung trong file |
| `canonical_document_id` | Canonical của exact duplicate đã xác nhận | Đúng khi link cùng owner/notebook và quyết định quality; near-duplicate không đủ |
| `version_group_id` | ID family phiên bản authoritative | Các file cùng chủ đề chưa chắc cùng family; cần relation/action nguồn |
| `version_number` | Thứ tự version trong family | Số trong filename chỉ là gợi ý; quyết định lifecycle là gold |
| `effective_from` | Ngày business bắt đầu hiệu lực | Dùng điều khoản/source system; ngày upload không thay thế được |
| `effective_to` | Ngày hết hiệu lực | Trống là đúng nếu source không quy định; phải không trước `effective_from` |
| `supersedes_document_id` | Version bị thay thế trực tiếp | Không gắn mọi version cũ; cần predecessor được xác nhận |
| `is_current` | Head hiện hành của family/canonical | Tối đa một current canonical; future version có thể chưa current theo workflow |
| `quality_status` | Trạng thái quality workflow | Candidate detector không tự bằng `duplicate`/`conflict` đã xác nhận |
| `quality_metadata` | Evidence của fingerprint/quality action | Đúng khi key/value tái lập được từ detector version; object trống không luôn là lỗi |
| `quality_metadata.numbers` | Các literal số đã chuẩn hóa | Tái lập từ canonical text; không coi đây là business value authoritative |
| `quality_metadata.dates` | Các date mention đã chuẩn hóa | Tái lập từ canonical text; không thay thế `effective_from/effective_to` |
| `quality_metadata.has_negation` | Có token phủ định theo lexicon rule | Chấm theo detector/tokenization, không kết luận cả tài liệu phủ định một claim cụ thể |
| `quality_metadata.identity_trusted` | Guard cho phép xét auto identity | Chỉ true khi các invariant OCR/confidence/table/visual/replacement character đều đạt |
| `quality_metadata.table_count` | Số bảng được biểu diễn trong canonical sequence | So với projection, không chỉ đếm bảng parser phát hiện |
| `quality_metadata.fallback_used` | Projection đã dùng fallback | Đúng theo ordered elements/table representation path |
| `quality_metadata.unrepresented_visual_count` | Visual chưa được biểu diễn trong identity text | Số dương phải chặn auto identity; đối chiếu parser blocks/images |

## Quy tắc field-by-field: structure, parser và citation

| Field | Định nghĩa và gold evidence | Đúng / sai / biên |
|---|---|---|
| `source` | Locator/label parser của chunk | Phải trỏ đúng file/source; cùng tên không chứng minh cùng source ID |
| `page_number` | Trang của source token đầu tiên | Đúng theo policy hiện tại; chunk qua nhiều trang vẫn có thể chỉ ghi trang đầu |
| `section_title` | Heading gần nhất áp dụng cho chunk | Heading trang/header lặp không phải section nếu parser đã loại |
| `section_id` | ID cấu trúc nguồn | Phải truy ngược được block/section; không tự đặt ID semantic |
| `source_block_ids` | Các parser block tạo chunk | Multi-label; đúng khi union block lineage đầy đủ, thứ tự không quan trọng |
| `table_identity` | ID bảng chứa chunk | Row-group cùng bảng phải cùng identity; hai bảng giống header vẫn khác ID |
| `table_row_group_index` | Thứ tự group trong bảng | Zero-based theo chunker; không dùng số dòng hiển thị thay thế |
| `table_row_group` | Marker chunk bảng đã chia group | Chỉ true khi table grouping path tạo chunk |
| `document_version` | Version cha copy vào chunk | Phải bằng `version_number` của document cha trong snapshot |
| `parser_name` | Adapter thực sự tạo output | OCR/hybrid path phải ghi adapter active, không suy từ MIME |
| `page_count` | Tổng trang authoritative | Đối chiếu render/PDF/OCR; sheet/slide count không gọi là page nếu parser contract không vậy |
| `pdf_type` | `text_native/scanned/hybrid/encrypted/corrupted/unknown` | Dựa trên analyzer/page facts; một trang ảnh không tự biến cả PDF thành scanned |
| `extraction_strategy` | Route native/OCR/hybrid/reject/... | Đối chiếu router log; expected OCR không chứng minh OCR đã chạy |
| `estimated_ocr_required` | Analyzer dự báo cần OCR | Đúng theo page facts tại thời điểm route; không phải kết quả OCR |
| `analysis_confidence` | Confidence rule trong `[0,1]` | Đúng khi tái lập từ analyzer; không chấm semantic bằng cảm giác |
| `sheet_count` | Số sheet workbook | Tính cả sheet rỗng/ẩn theo parser contract hiện hành |
| `title` | Title đưa vào retrieval | Đúng khi là title tài liệu hoặc fallback filename hợp lệ; không nhận một heading con |
| `document_type` | Class heuristic hiện tại | Đúng theo nội dung/chức năng toàn tài liệu; `unknown` đúng nếu evidence không đủ |
| `language` | Ngôn ngữ chính của tài liệu/chunk | Dùng mã chuẩn; chunk chứa mã/tên riêng không tự đổi language |
| `section_path` | Chuỗi heading từ cha đến section hiện tại | Multi-label có thứ tự; phải chứa đúng hierarchy, không thêm category suy đoán |
| `content_kind` | Loại block hiện tại | Table/list/code phải dựa cấu trúc; text có dấu `|` chưa chắc là table |
| `table_header` | Header làm rõ nghĩa row chunk | Phải đúng cột và đúng bảng; header từ bảng trước là `incorrect` |
| `keyword_aliases` | Alias trusted hiện có | Multi-label; chỉ giữ alias có nguồn/hỗ trợ rõ, không thêm từ liên tưởng rộng |

## Quy tắc field-by-field: contextual retrieval LLM

| Field | Định nghĩa và gold evidence | Đúng / sai / biên |
|---|---|---|
| `contextual_summary` | Mô tả ngắn riêng cho chunk | Đúng khi grounded, đúng version/section và không thêm mức tiền/chủ thể/điều kiện mới |
| `contextual_search_terms` | Cụm truy vấn/alias giúp tìm chunk | Multi-label; mỗi term phải liên quan trực tiếp, không chứa fact không có bằng chứng |
| `embedding_context` | Context đã render trước content | Đúng khi chỉ phản ánh trusted structure + validated LLM context của chính chunk |
| `context_enrichment.status` | `generated` hoặc `fallback` | `generated` chỉ khi output LLM validate thành công; lỗi/empty phải là fallback |
| `context_enrichment.model` | Model runtime đã gọi | Đối chiếu job profile/telemetry, không suy từ văn phong |
| `context_enrichment.error_code` | Mã lỗi fallback đã sanitize | Trống đúng với generated; fallback cần mã nếu implementation tạo được |

Ví dụ đúng: chunk `Hạng A | Hà Nội | 1.500.000 VND/đêm`, summary “Mức trần lưu trú cho hạng A tại Hà Nội.”

Ví dụ sai: “Mọi nhân viên được hoàn 1.500.000 VND mỗi ngày” vì thêm phạm vi chủ thể và đổi điều kiện.

Biên: summary paraphrase khác từ nhưng giữ nguyên fact vẫn đúng. Một term rộng như “chi phí” có thể hữu ích nhưng confidence chỉ `medium`; term không liên quan trực tiếp là sai.

## Quy tắc field-by-field: canonicalization và pre-embedding quality

| Field | Định nghĩa và gold evidence | Đúng / sai / biên |
|---|---|---|
| `canonical_text` | Text sau sanitizer dùng fingerprint | Phải tái lập đúng normalizer version; không tự sửa nội dung nghiệp vụ |
| `pre_embedding_quality` | Object evidence quyết định | Đúng khi nested values nhất quán và detector version có thể tái lập |
| `pre_embedding_quality.action` | Embed hay reuse vector | Reuse chỉ đúng khi strict identity và embedding input/model tương thích |
| `pre_embedding_quality.relation_type` | Exact/near/version/conflict candidate | `candidate` không được chấm như conflict/version đã xác nhận |
| `pre_embedding_quality.confidence` | Score rule `[0,1]` | So với detector output; không chuyển thành xác suất human truth |
| `pre_embedding_quality.embedding_reused` | Vector có được reuse | Đối chiếu plan/write log và checksum |
| `pre_embedding_quality.match_source` | Candidate từ `database` hay `current_batch` | Đúng theo lookup path, không theo vị trí record hiện tại |
| `pre_embedding_quality.target_document_id` | Document target của match | Phải tồn tại cùng scope và là target thực sự được verifier chọn |
| `pre_embedding_quality.target_chunk_id` | Chunk target của match | UUID hợp lệ với database match; `source_chunk_id` composite hợp lệ với current-batch match |
| `pre_embedding_quality.target_chunk_index` | Vị trí zero-based của target | Phải khớp target document/current batch và target ID |
| `pre_embedding_quality.simhash_hamming_distance` | Hamming distance 0..64 | Tái tính từ loose signatures; không quyết định identity một mình |
| `pre_embedding_quality.lsh_band_matches` | Số band 8-bit trùng, 0..8 | Tái tính từ 16 hex chars; không có cột bucket riêng trong DB |
| `pre_embedding_quality.lexical_similarity` | Score lexical verifier | Tái lập cùng detector/tokenization/version |
| `pre_embedding_quality.containment` | Mức text này chứa text kia | Đúng chiều và đúng normalized input |
| `pre_embedding_quality.reason_codes` | Lý do deterministic | Multi-label; phải khớp signal thật, không viết giải thích tự do |
| `provenance_metadata` | Open object truy nguồn parser | Chỉ chấm key có source evidence; key không xác định để ambiguous |
| `authority_metadata` | Open object về authority | Chỉ dữ liệu hệ thống nguồn/được duyệt; LLM suy đoán là `wrong_scope`/`incorrect` |

## Field không đưa vào human semantic sample

UUID tự sinh, raw/normalized hash, checksum, storage path, timestamps tạo tự động, config/parser version và operational lease chủ yếu được kiểm bằng audit tự động/recomputation. Chúng vẫn nằm đầy đủ trong `metadata_schema.csv`; không ép annotator xác nhận semantic khi annotation package không chứa bytes, log hoặc algorithm input.

## Kiểm tra trước khi nộp

- Không dùng `unknown`, `N/A`, `none` làm gold nếu source có giá trị xác định.
- `gold_value` đúng kiểu và enum trong schema; array ghi JSON.
- `is_correct=0` phải có `error_type` và notes ngắn.
- `is_correct=1` nhưng current/gold khác bề mặt phải giải thích normalization tương đương.
- A/B độc lập; disagreement phải adjudicate, không tự sửa cột người kia.
- Version, status, canonical và security không bao giờ được “đoán hợp lý”.
