# Hướng dẫn gán nhãn và adjudication

## Thứ tự quyết định

Áp dụng theo thứ tự sau để tránh một cặp rơi vào nhiều nhãn:

1. **Đủ evidence không?** Nếu thiếu entity, qualifier, thời gian hoặc extraction quá kém để kết luận an toàn: `UNCERTAIN`.
2. **Entity/business identity có khác không?** Nếu text/structure giống mạnh do template nhưng entity khác: `TEMPLATE_VARIANT`. Nếu không có template relationship: `DISTINCT`.
3. **Claim có thẳng hàng không?** Nếu khác thuộc tính (ví dụ động lực giá và rủi ro pháp lý): `DISTINCT`.
4. **Temporal scope có không chồng lấn không?** Cùng claim ở hai kỳ khác nhau: `TEMPORAL_VARIANT`, không phải conflict.
5. **Qualifier nghiệp vụ có khác không?** Giá chào với giá giao dịch, căn hộ với thấp tầng, officetel với căn hộ: `CONDITIONAL_VARIANT`.
6. **Text canonical có giống hệt không?** Chỉ khi entity/scope/time/claim/value đều giống: `EXACT_DUPLICATE`.
7. **Ý nghĩa có tương đương không?** Cùng fact nhưng wording khác: `NEAR_DUPLICATE`.
8. **B có mở rộng tương thích A không?** Có addition/supersession rõ và không mâu thuẫn: `VERSION_UPDATE`.
9. **Giá trị/polarity có bất tương thích trong cùng scope không?** `CONFLICT`.

## Các bẫy bắt buộc kiểm tra

- Hai đoạn generic giống từng chữ nhưng context là hai dự án khác nhau không được auto-reuse nghiệp vụ.
- Giá khác nhau ở 2022 và 2026 là temporal series, không tự động là conflict.
- Giá thấp tầng và giá căn hộ không được so conflict dù cùng dự án.
- “Vốn ban đầu từ 1,2 tỷ” không đồng nghĩa giá tài sản 1,2 tỷ.
- “Chưa đủ dữ liệu” không đồng nghĩa “không có giao dịch”.
- Cụm Hà Nội gồm Metropolis, Skylake và West Point; không gộp thành một entity duy nhất.
- Source discrepancy không đủ scope có thể phải `UNCERTAIN`, không ép `CONFLICT`.

## Quy trình reviewer

1. Mỗi reviewer làm việc trên một bản riêng của `review_queue.csv` và không xem nhãn của người kia.
2. Điền label và note ngắn nêu field quyết định: entity, business scope, time, claim, value hoặc reliability.
3. So sánh hai bản; disagreement chuyển cho adjudicator thứ ba.
4. Adjudicator xem `source_evidence_id`, locator và hash trong evidence catalog trước khi quyết định.
5. Không sửa text để “khớp” nhãn. Nếu source sai, tạo issue và version mới.
6. Ghi lại reviewer IDs, ngày, agreement score và mọi thay đổi nhãn trong changelog.

## Tiêu chí auto-reuse

Chỉ `EXACT_DUPLICATE` được phép `expected_auto_reuse=true`. `NEAR_DUPLICATE` vẫn cần policy/review vì normalization, entity hoặc qualifier có thể bị mất. Mọi nhãn còn lại phải fail closed khỏi đường auto-reuse.
