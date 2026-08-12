# Dataset Card

## Mục tiêu

Đánh giá phân loại quan hệ chunk-level cho duplicate, version, temporal/conditional/template variant, conflict, distinct và uncertain trong pipeline RAG tiếng Việt. Bộ này ưu tiên lỗi có hậu quả nghiệp vụ: auto-reuse sai, báo conflict giả, bỏ sót conflict và gộp nhầm các dự án dùng chung template.

## Nguồn

- 10 hồ sơ thị trường Vinhomes, cùng ngày cập nhật công khai 11/08/2026.
- 1 hồ sơ Xanh SM/S2S ngày 15/04/2025 làm hard negative ngoài miền bất động sản.
- Tổng cộng 61 trang đã được render và kiểm tra trực quan.
- SHA-256 và locator chi tiết nằm trong `manifest.json` và `sources/evidence_catalog.jsonl`.

Các tài liệu gốc do người dùng cung cấp. Gói benchmark không tái phân phối DOCX gốc và không khẳng định quyền cấp phép ngoài phạm vi sử dụng nội bộ của người sở hữu tài liệu.

## Phương pháp tạo

`observed` gồm các repetition thật giữa cover/detail, table/prose projection, time-series row, shared template, distinct claim, missing-context và cross-domain pair. `controlled_mutation` giữ một parent evidence có hash và chỉ thay đổi một chiều theo operator được ghi rõ: formatting, paraphrase, compatible addition, numeric substitution, polarity flip, qualifier substitution hoặc reference-period shift.

Không có LLM hay external model tham gia tạo nhãn. Nhãn được sinh từ rule và invariants explicit; vì chưa double-reviewed nên vẫn là `provisional_gold`.

## Split

Split theo source document family, không theo từng pair. DEV có 6 tài liệu Vinhomes; TEST có 4 tài liệu Vinhomes và tài liệu S2S. Template pair chỉ ghép các tài liệu trong cùng split. Official model input là context cha cộng text chunk.

## Điểm mạnh

- Provenance truy ngược tới hash và locator.
- Có natural/controlled strata.
- Có hard cases về template, temporal scope, price basis, negation, numeric conflict, table/prose và context loss.
- Có validator và evaluator dependency-light.
- Honest labeling: không tự gọi là organization-grade gold trước human review.

## Hạn chế

- Chỉ 11 tài liệu, chủ yếu cùng một template và một ngành; chưa đại diện cho mọi corpus doanh nghiệp.
- `VERSION_UPDATE` và conflict chính xác cần version/source độc lập thật; trong bản này các nhãn đó chủ yếu đến từ mutation có kiểm soát.
- 164 cặp chưa đủ để ước lượng tỷ lệ lỗi production hiếm với khoảng tin cậy hẹp.
- Không đo candidate retrieval/ANN recall, document-level clustering, database tenancy hay race condition ingestion.
- Giá trong tài liệu nguồn là giá chào/giới thiệu hoặc tổng hợp công khai, không phải dữ liệu giao dịch chuẩn hóa.
- Một số hồ sơ chứa ba dự án trong một tài liệu; entity resolution cần xử lý nested entity thay vì coi toàn bộ tài liệu là một dự án.

## Không nên dùng để

- Huấn luyện rồi báo điểm trên cùng split TEST.
- Đánh giá chất lượng factual của dữ liệu bất động sản.
- Thay thế human review cho quyết định merge/xóa dữ liệu.
- Suy luận performance production chỉ từ accuracy tổng hợp.

## Điều kiện promotion thành Gold V2

1. Hai reviewer độc lập gán nhãn toàn bộ TEST và ít nhất mọi case hard/synthetic trong DEV.
2. Cohen's kappa hoặc Krippendorff's alpha được báo cáo; mục tiêu tối thiểu 0,80.
3. Mọi disagreement được adjudicate với rationale và reviewer ID.
4. `annotation.independent_human_reviews` được cập nhật; mọi thay đổi tạo version/build ID mới.
5. Validator chạy xanh và SHA256SUMS được tái tạo.
