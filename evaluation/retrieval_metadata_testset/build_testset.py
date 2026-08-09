"""Build a retrieval/metadata evaluation test set for the user's three files.

Run from repository root:

    python evaluation/retrieval_metadata_testset/build_testset.py
"""

from __future__ import annotations

import csv
import json
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent
TESTSET_PATH = ROOT / "testset.jsonl"
CSV_PATH = ROOT / "test_queries.csv"
EVALUATION_QUERIES_PATH = ROOT / "evaluation_queries.csv"
MANIFEST_PATH = ROOT / "manifest.json"
ABLATION_PATH = ROOT / "ablation_matrix.json"


SOURCE_FILES = {
    "Vinhomes_TayMo.pdf": {
        "kind": "pdf",
        "expected_document_type": "contract",
        "domain": "real_estate_contract",
        "page_count_observed": 51,
        "local_path": r"C:\Users\Admin\Downloads\Vinhomes_TayMo.pdf",
    },
    "Vinhomes_HaiVan.pdf": {
        "kind": "pdf",
        "expected_document_type": "contract",
        "domain": "real_estate_contract",
        "page_count_observed": 47,
        "local_path": r"C:\Users\Admin\Downloads\Vinhomes_HaiVan.pdf",
    },
    "demo_kb_chinh_sach_doi_tra_cskh - Copy.docx": {
        "kind": "docx",
        "expected_document_type": "policy",
        "domain": "customer_support_policy",
        "page_count_observed": None,
        "local_path": r"C:\Users\Admin\Downloads\demo_kb_chinh_sach_doi_tra_cskh - Copy.docx",
    },
}


def case(
    *,
    case_id: str,
    query: str,
    source_file: str,
    category: str,
    difficulty: str,
    page: int | None,
    must: list[str],
    should: list[str] | None = None,
    forbidden: list[str] | None = None,
    metadata_focus: list[str] | None = None,
    section_hint: str | None = None,
    notes: str | None = None,
) -> dict[str, Any]:
    source = SOURCE_FILES[source_file]
    expected_metadata = {
        "document_type": source["expected_document_type"],
        "domain": source["domain"],
        "source_kind": source["kind"],
        "section_hint": section_hint,
        "page": page,
        "metadata_focus": metadata_focus or [],
    }
    return {
        "id": case_id,
        "query_id": case_id,
        "query": query,
        "query_type": category,
        "source_file": source_file,
        "source_kind": source["kind"],
        "domain": source["domain"],
        "category": category,
        "difficulty": difficulty,
        "metadata_focus": metadata_focus or [],
        "relevant_doc_ids": [],
        "relevant_doc_titles": [source_file],
        "relevant_chunk_ids": [],
        "expected_metadata": expected_metadata,
        "answerable": True,
        "expected": {
            "document_title": source_file,
            "document_type": source["expected_document_type"],
            "page": page,
            "page_tolerance": 1 if page is not None else None,
            "section_hint": section_hint,
            "must_include_terms": must,
            "should_include_terms": should or [],
            "forbidden_document_titles": forbidden
            or [name for name in SOURCE_FILES if name != source_file],
        },
        "notes": notes or "",
    }


TEST_CASES: list[dict[str, Any]] = [
    case(
        case_id="tm_001_contract_title",
        query="Tài liệu nào là hợp đồng mua bán diện tích thương mại?",
        source_file="Vinhomes_TayMo.pdf",
        category="document_disambiguation",
        difficulty="easy",
        page=1,
        section_hint="Hợp đồng mua bán diện tích thương mại",
        must=["HỢP ĐỒNG MUA BÁN DIỆN TÍCH THƯƠNG MẠI", "Diện Tích Thương Mại"],
        should=["HĐMBDTTMTT"],
        metadata_focus=["title", "document_type", "section_title"],
    ),
    case(
        case_id="tm_002_project_location",
        query="Dự án Tây Mỗ - Đại Mỗ trong hợp đồng diện tích thương mại nằm ở đâu?",
        source_file="Vinhomes_TayMo.pdf",
        category="semantic_location",
        difficulty="medium",
        page=4,
        section_hint="Dự Án",
        must=["Khu đô thị mới Tây Mỗ - Đại Mỗ - Vinhomes Park", "Phường Tây Mỗ", "Phường Đại Mỗ"],
        should=["Nam Từ Liêm", "Thành phố Hà Nội", "Vinhomes Smart City"],
        metadata_focus=["title", "section_path", "contextual_summary", "contextual_search_terms"],
    ),
    case(
        case_id="tm_003_price_includes",
        query="Giá bán diện tích thương mại đã bao gồm những khoản nào?",
        source_file="Vinhomes_TayMo.pdf",
        category="clause_lookup",
        difficulty="medium",
        page=7,
        section_hint="Giá Bán Diện Tích Thương Mại",
        must=["Giá Bán Diện Tích Thương Mại", "thuế giá trị gia tăng", "Kinh Phí Bảo Trì"],
        should=["Phụ Lục 2"],
        metadata_focus=["section_title", "section_path", "contextual_summary"],
    ),
    case(
        case_id="tm_004_price_excludes_registration_fee",
        query="Trong hợp đồng diện tích thương mại, lệ phí trước bạ có nằm trong giá bán không?",
        source_file="Vinhomes_TayMo.pdf",
        category="negative_clause_lookup",
        difficulty="hard",
        page=7,
        section_hint="Giá Bán Diện Tích Thương Mại",
        must=["không bao gồm", "lệ phí trước bạ", "do Bên Mua chịu trách nhiệm thanh toán"],
        should=["Giấy Chứng Nhận"],
        metadata_focus=["section_path", "contextual_summary", "contextual_search_terms"],
    ),
    case(
        case_id="tm_005_area_difference_payment_deadline",
        query=(
            "Phần diện tích chênh lệch của diện tích thương mại phải thanh toán "
            "trong bao lâu sau biên bản bàn giao?"
        ),
        source_file="Vinhomes_TayMo.pdf",
        category="numeric_deadline",
        difficulty="hard",
        page=8,
        section_hint="Giá Bán Diện Tích Thương Mại",
        must=["30 (ba mươi) ngày", "Biên Bản Bàn Giao Diện Tích Thương Mại"],
        should=["diện tích chênh lệch"],
        metadata_focus=["section_path", "contextual_summary", "contextual_search_terms"],
    ),
    case(
        case_id="tm_006_handover_no_show",
        query=(
            "Nếu Bên Mua không đến nhận bàn giao diện tích thương mại trong 05 ngày "
            "thì xử lý thế nào?"
        ),
        source_file="Vinhomes_TayMo.pdf",
        category="condition_lookup",
        difficulty="hard",
        page=16,
        section_hint="Giao nhận Diện Tích Thương Mại",
        must=["05 (năm) ngày", "được xem như Bên Mua đã đồng ý", "Thông Báo Bàn Giao"],
        should=["không nhận bàn giao"],
        metadata_focus=["section_title", "section_path", "contextual_summary"],
    ),
    case(
        case_id="tm_007_refund_interest",
        query=(
            "Khi Bên Bán phải hoàn trả Giá Bán Diện Tích Thương Mại thì lãi suất "
            "được nêu là bao nhiêu?"
        ),
        source_file="Vinhomes_TayMo.pdf",
        category="numeric_rate",
        difficulty="medium",
        page=12,
        section_hint="Quyền và nghĩa vụ của Bên Mua",
        must=["10%/năm", "Giá Bán Diện Tích Thương Mại"],
        should=["Bên Bán sẽ hoàn trả"],
        metadata_focus=["section_path", "contextual_summary", "contextual_search_terms"],
    ),
    case(
        case_id="tm_008_warranty_article",
        query="Điều nào quy định bảo hành diện tích thương mại?",
        source_file="Vinhomes_TayMo.pdf",
        category="section_lookup",
        difficulty="easy",
        page=18,
        section_hint="Bảo hành",
        must=["Điều 9. Bảo hành", "Diện Tích Thương Mại"],
        should=["Bên Bán", "bảo hành"],
        metadata_focus=["section_title", "section_path"],
    ),
    case(
        case_id="tm_009_force_majeure",
        query=(
            "Trong hợp đồng diện tích thương mại, chiến tranh hoặc thiên tai "
            "có được coi là bất khả kháng không?"
        ),
        source_file="Vinhomes_TayMo.pdf",
        category="semantic_clause",
        difficulty="medium",
        page=23,
        section_hint="Sự kiện bất khả kháng",
        must=["Điều 14. Sự kiện bất khả kháng", "chiến tranh", "thiên tai"],
        should=["thay đổi chính sách pháp luật"],
        metadata_focus=["section_title", "section_path", "contextual_summary"],
    ),
    case(
        case_id="tm_010_dispute_60_days",
        query=(
            "Tranh chấp hợp đồng diện tích thương mại được thương lượng trong bao lâu "
            "trước khi chuyển hướng xử lý?"
        ),
        source_file="Vinhomes_TayMo.pdf",
        category="numeric_deadline",
        difficulty="medium",
        page=27,
        section_hint="Giải quyết tranh chấp",
        must=["Điều 18. Giải quyết tranh chấp", "60 (sáu mươi) ngày", "thương lượng"],
        should=["tranh chấp"],
        metadata_focus=["section_title", "section_path", "contextual_summary"],
    ),
    case(
        case_id="tm_011_maintenance_fund_appendix",
        query="Quỹ bảo trì Khu Thương Mại được quy định ở phụ lục nào?",
        source_file="Vinhomes_TayMo.pdf",
        category="appendix_lookup",
        difficulty="hard",
        page=47,
        section_hint="Quỹ Bảo Trì Khu Thương Mại",
        must=["PHỤ LỤC 4", "QUỸ BẢO TRÌ KHU THƯƠNG MẠI"],
        should=["Nội Quy Khu Thương Mại"],
        metadata_focus=["title", "section_title", "section_path", "contextual_search_terms"],
    ),
    case(
        case_id="tm_012_parking_rule",
        query="Nội quy Khu TM nói gì về việc đỗ xe bừa bãi?",
        source_file="Vinhomes_TayMo.pdf",
        category="keyword_clause",
        difficulty="hard",
        page=37,
        section_hint="Quyền và trách nhiệm của Cư Dân",
        must=["đỗ xe bừa bãi", "Khu TM"],
        should=["gây cản trở lưu thông"],
        metadata_focus=["section_path", "contextual_search_terms", "search_text"],
    ),
    case(
        case_id="hv_001_contract_title",
        query="Tài liệu nào là hợp đồng mua bán nhà ở tại Hải Vân?",
        source_file="Vinhomes_HaiVan.pdf",
        category="document_disambiguation",
        difficulty="easy",
        page=1,
        section_hint="Hợp đồng mua bán nhà ở",
        must=["HỢP ĐỒNG MUA BÁN NHÀ Ở", "VHHVB/HĐMBNO"],
        should=["Đà Nẵng"],
        metadata_focus=["title", "document_type", "section_title"],
    ),
    case(
        case_id="hv_002_house_location",
        query="Nhà ở trong hợp đồng Hải Vân nằm tại phường nào của Đà Nẵng?",
        source_file="Vinhomes_HaiVan.pdf",
        category="semantic_location",
        difficulty="medium",
        page=2,
        section_hint="Các thông tin về Nhà Ở",
        must=["phường Hòa Hiệp Bắc", "phường Hải Vân", "thành phố Đà Nẵng"],
        should=["quận Liên Chiểu"],
        metadata_focus=["section_path", "contextual_summary", "contextual_search_terms"],
    ),
    case(
        case_id="hv_003_project_name",
        query="Dự án Làng Vân xuất hiện trong hợp đồng nào?",
        source_file="Vinhomes_HaiVan.pdf",
        category="document_disambiguation",
        difficulty="medium",
        page=2,
        section_hint="Các thông tin về Nhà Ở",
        must=["Khu phức hợp du lịch và đô thị nghỉ dưỡng Làng Vân", "Đà Nẵng"],
        should=["Nhà Ở"],
        metadata_focus=["title", "contextual_summary", "contextual_search_terms"],
    ),
    case(
        case_id="hv_004_price_includes",
        query="Giá bán Nhà Ở trong hợp đồng Hải Vân đã bao gồm những khoản nào?",
        source_file="Vinhomes_HaiVan.pdf",
        category="clause_lookup",
        difficulty="medium",
        page=3,
        section_hint="Giá Bán Nhà Ở",
        must=[
            "Giá Bán Nhà Ở",
            "giá trị quyền sử dụng đất",
            "thuế giá trị gia tăng",
            "Kinh Phí Bảo Trì",
        ],
        should=["Phụ Lục 2"],
        metadata_focus=["section_title", "section_path", "contextual_summary"],
    ),
    case(
        case_id="hv_005_price_excludes_registration_fee",
        query="Trong hợp đồng nhà ở, lệ phí trước bạ có được tính trong giá bán Nhà Ở không?",
        source_file="Vinhomes_HaiVan.pdf",
        category="negative_clause_lookup",
        difficulty="hard",
        page=3,
        section_hint="Giá Bán Nhà Ở",
        must=["không bao gồm", "lệ phí trước bạ", "trách nhiệm thanh toán"],
        should=["Giấy Chứng Nhận"],
        metadata_focus=["section_path", "contextual_summary", "contextual_search_terms"],
    ),
    case(
        case_id="hv_006_handover_notice",
        query="Trước ngày bàn giao Nhà Ở bao lâu thì Bên Bán phải gửi Thông Báo Bàn Giao?",
        source_file="Vinhomes_HaiVan.pdf",
        category="numeric_deadline",
        difficulty="medium",
        page=5,
        section_hint="Giao nhận Nhà Ở",
        must=["05 (năm) ngày", "Thông Báo Bàn Giao"],
        should=["Trước ngày bàn giao", "thời gian, địa điểm và thủ tục bàn giao"],
        metadata_focus=["section_title", "section_path", "contextual_summary"],
    ),
    case(
        case_id="hv_007_handover_no_show",
        query="Nếu Bên Mua không đến nhận bàn giao Nhà Ở trong 05 ngày thì sao?",
        source_file="Vinhomes_HaiVan.pdf",
        category="condition_lookup",
        difficulty="hard",
        page=6,
        section_hint="Giao nhận Nhà Ở",
        must=["05 (năm) ngày", "được xem như Bên Mua đã đồng ý", "Thông Báo Bàn Giao"],
        should=["chính thức nhận bàn giao"],
        metadata_focus=["section_title", "section_path", "contextual_summary"],
    ),
    case(
        case_id="hv_008_warranty_scope",
        query="Bảo hành Nhà Ở bao gồm sửa chữa những hạng mục nào?",
        source_file="Vinhomes_HaiVan.pdf",
        category="list_lookup",
        difficulty="hard",
        page=7,
        section_hint="Bảo hành",
        must=["Nội dung bảo hành", "khung", "cột", "dầm", "sàn", "tường"],
        should=["Nhà Ở", "trần", "mái", "hệ thống cấp nước sinh hoạt"],
        metadata_focus=["section_title", "section_path", "contextual_summary"],
    ),
    case(
        case_id="hv_009_transfer_conditions",
        query="Bên Mua Nhà Ở được chuyển nhượng hoặc chuyển giao hợp đồng khi nào?",
        source_file="Vinhomes_HaiVan.pdf",
        category="condition_lookup",
        difficulty="hard",
        page=8,
        section_hint="Chuyển giao quyền và nghĩa vụ",
        must=[
            "chỉ được chuyển nhượng/chuyển giao Hợp Đồng",
            "có đủ các điều kiện",
            "đã thanh toán đủ các nghĩa vụ đến hạn",
        ],
        should=["pháp luật về kinh doanh bất động sản"],
        metadata_focus=["section_title", "section_path", "contextual_summary"],
    ),
    case(
        case_id="hv_010_dispute_60_days",
        query="Tranh chấp trong hợp đồng Nhà Ở Hải Vân được thương lượng trong bao lâu?",
        source_file="Vinhomes_HaiVan.pdf",
        category="numeric_deadline",
        difficulty="medium",
        page=19,
        section_hint="Giải quyết tranh chấp",
        must=["Điều 17. Giải quyết tranh chấp", "60 (sáu mươi) ngày", "thương lượng"],
        should=["tranh chấp"],
        metadata_focus=["section_title", "section_path", "contextual_summary"],
    ),
    case(
        case_id="hv_011_force_majeure",
        query="Sự kiện bất khả kháng trong hợp đồng Nhà Ở gồm những trường hợp nào?",
        source_file="Vinhomes_HaiVan.pdf",
        category="semantic_clause",
        difficulty="medium",
        page=16,
        section_hint="Sự kiện bất khả kháng",
        must=["Điều 13. Sự kiện bất khả kháng", "chiến tranh", "thiên tai"],
        should=["quyết định của cơ quan nhà nước"],
        metadata_focus=["section_title", "section_path", "contextual_summary"],
    ),
    case(
        case_id="hv_012_maintenance_fund_appendix",
        query="Quỹ bảo trì Khu Biệt Thự/Khu Nhà Ở được quy định ở đâu?",
        source_file="Vinhomes_HaiVan.pdf",
        category="appendix_lookup",
        difficulty="hard",
        page=42,
        section_hint="Quỹ Bảo Trì Khu Biệt Thự/Khu Nhà Ở",
        must=["PHỤ LỤC 4", "QUỸ BẢO TRÌ KHU BIỆT THỰ/KHU NHÀ Ở"],
        should=["Nội Quy Khu Biệt Thự/Khu Nhà Ở"],
        metadata_focus=["title", "section_title", "section_path", "contextual_search_terms"],
    ),
    case(
        case_id="hv_013_extra_maintenance_fee",
        query="Khi quỹ bảo trì Khu Nhà Ở không đủ thì Bên Mua có nghĩa vụ gì?",
        source_file="Vinhomes_HaiVan.pdf",
        category="condition_lookup",
        difficulty="hard",
        page=12,
        section_hint="Quyền và nghĩa vụ của Bên Mua",
        must=["Nộp bổ sung Kinh Phí Bảo Trì", "quỹ bảo trì Khu Nhà Ở không đủ"],
        should=["Công Ty Quản Lý"],
        metadata_focus=["section_path", "contextual_summary", "contextual_search_terms"],
    ),
    case(
        case_id="hv_014_management_fee_after_handover",
        query="Kể từ ngày bàn giao Nhà Ở, ai phải thanh toán kinh phí quản lý vận hành khu nhà ở?",
        source_file="Vinhomes_HaiVan.pdf",
        category="clause_lookup",
        difficulty="medium",
        page=3,
        section_hint="Giá Bán Nhà Ở",
        must=[
            "kể từ ngày bàn giao Nhà Ở",
            "Bên Mua có trách nhiệm thanh toán",
            "kinh phí quản lý vận hành khu nhà ở",
        ],
        should=["khu đô thị"],
        metadata_focus=["section_path", "contextual_summary"],
    ),
    case(
        case_id="cs_001_document_code",
        query="Mã tài liệu của chính sách đổi trả CSKH là gì?",
        source_file="demo_kb_chinh_sach_doi_tra_cskh - Copy.docx",
        category="table_lookup",
        difficulty="easy",
        page=None,
        section_hint="Thông tin tài liệu",
        must=["Mã tài liệu", "CSKH-RET-01"],
        should=["Bộ phận Chăm sóc khách hàng"],
        metadata_focus=["title", "document_type", "table_header", "search_text"],
    ),
    case(
        case_id="cs_002_issue_date",
        query="Chính sách đổi trả CSKH được ban hành ngày nào?",
        source_file="demo_kb_chinh_sach_doi_tra_cskh - Copy.docx",
        category="table_lookup",
        difficulty="easy",
        page=None,
        section_hint="Thông tin tài liệu",
        must=["Ngày ban hành", "15/03/2027"],
        should=["CSKH-RET-01"],
        metadata_focus=["table_header", "search_text"],
    ),
    case(
        case_id="cs_003_policy_scope",
        query="Phạm vi áp dụng của chính sách đổi trả CSKH là gì?",
        source_file="demo_kb_chinh_sach_doi_tra_cskh - Copy.docx",
        category="table_lookup",
        difficulty="medium",
        page=None,
        section_hint="Chính sách áp dụng",
        must=["Phạm vi", "Tất cả đơn hàng mua trực tuyến tại Việt Nam"],
        should=["Đang áp dụng theo hướng dẫn của CSKH"],
        metadata_focus=["table_header", "section_title", "contextual_summary"],
    ),
    case(
        case_id="cs_004_return_deadline",
        query=(
            "Khách hàng được yêu cầu đổi hoặc trả hàng tối đa trong bao nhiêu ngày "
            "kể từ ngày nhận hàng?"
        ),
        source_file="demo_kb_chinh_sach_doi_tra_cskh - Copy.docx",
        category="numeric_deadline",
        difficulty="hard",
        page=None,
        section_hint="Chính sách áp dụng",
        must=["Thời hạn đổi trả", "tối đa 30 ngày", "kể từ ngày nhận hàng"],
        should=["đổi hoặc trả hàng"],
        metadata_focus=["table_header", "contextual_summary", "contextual_search_terms"],
        notes="Câu này cố tình dễ nhầm với các clause 30 ngày trong hợp đồng Vinhomes.",
    ),
    case(
        case_id="cs_005_opened_product_condition",
        query="Sản phẩm đã mở hộp và dùng thử có được đổi trả không?",
        source_file="demo_kb_chinh_sach_doi_tra_cskh - Copy.docx",
        category="condition_lookup",
        difficulty="medium",
        page=None,
        section_hint="Chính sách áp dụng",
        must=[
            "Sản phẩm có thể đã mở hộp và dùng thử",
            "đầy đủ phụ kiện",
            "không có dấu hiệu hư hỏng do người dùng",
        ],
        should=["quà tặng"],
        metadata_focus=["table_header", "contextual_summary"],
    ),
    case(
        case_id="cs_006_promotion_items",
        query="Hàng khuyến mại hoặc dùng mã khuyến mại có được đổi trả không?",
        source_file="demo_kb_chinh_sach_doi_tra_cskh - Copy.docx",
        category="condition_lookup",
        difficulty="medium",
        page=None,
        section_hint="Chính sách áp dụng",
        must=["Hàng khuyến mại", "giảm giá", "mã khuyến mại", "vẫn được đổi trả"],
        should=["điều kiện chung"],
        metadata_focus=["table_header", "contextual_summary", "search_text"],
    ),
    case(
        case_id="cs_007_shipping_fee_exception",
        query="Ai trả phí gửi hàng về kho và ngoại lệ là gì?",
        source_file="demo_kb_chinh_sach_doi_tra_cskh - Copy.docx",
        category="condition_lookup",
        difficulty="hard",
        page=None,
        section_hint="Chính sách áp dụng",
        must=[
            "Phí vận chuyển",
            "Khách hàng thanh toán phí gửi hàng về kho",
            "giao sai sản phẩm",
            "lỗi kỹ thuật",
        ],
        should=["trừ trường hợp"],
        metadata_focus=["table_header", "contextual_summary", "contextual_search_terms"],
    ),
    case(
        case_id="cs_008_refund_time",
        query="Sau khi kho xác nhận hàng trả đạt điều kiện thì bao lâu được hoàn tiền?",
        source_file="demo_kb_chinh_sach_doi_tra_cskh - Copy.docx",
        category="numeric_deadline",
        difficulty="medium",
        page=None,
        section_hint="Chính sách áp dụng",
        must=["Thời gian hoàn tiền", "5 ngày làm việc", "kho xác nhận hàng trả đạt điều kiện"],
        should=["Hoàn tiền"],
        metadata_focus=["table_header", "contextual_summary", "contextual_search_terms"],
    ),
    case(
        case_id="cs_009_refund_method",
        query="Chính sách CSKH hoàn tiền qua hình thức nào?",
        source_file="demo_kb_chinh_sach_doi_tra_cskh - Copy.docx",
        category="table_lookup",
        difficulty="medium",
        page=None,
        section_hint="Chính sách áp dụng",
        must=["Hình thức hoàn tiền", "phương thức thanh toán ban đầu", "chuyển khoản"],
        should=["yêu cầu của khách hàng"],
        metadata_focus=["table_header", "contextual_summary"],
    ),
    case(
        case_id="cs_010_process_order_code",
        query="Bước đầu tiên trong quy trình xử lý đổi trả yêu cầu khách hàng cung cấp gì?",
        source_file="demo_kb_chinh_sach_doi_tra_cskh - Copy.docx",
        category="process_lookup",
        difficulty="medium",
        page=None,
        section_hint="Quy trình xử lý",
        must=["Khách hàng liên hệ tổng đài hoặc email CSKH", "mã đơn hàng"],
        should=["cung cấp"],
        metadata_focus=["section_title", "section_path", "contextual_summary"],
    ),
    case(
        case_id="cs_011_process_request_code",
        query="CSKH làm gì sau khi xác nhận điều kiện đổi trả?",
        source_file="demo_kb_chinh_sach_doi_tra_cskh - Copy.docx",
        category="process_lookup",
        difficulty="medium",
        page=None,
        section_hint="Quy trình xử lý",
        must=["CSKH xác nhận điều kiện đổi trả", "cấp mã yêu cầu"],
        should=["quy trình xử lý"],
        metadata_focus=["section_title", "section_path", "contextual_summary"],
    ),
    case(
        case_id="cs_012_priority_relation_missing",
        query=(
            "Văn bản chính sách đổi trả CSKH có nêu rõ quan hệ ưu tiên "
            "với quy định của bộ phận khác không?"
        ),
        source_file="demo_kb_chinh_sach_doi_tra_cskh - Copy.docx",
        category="negative_policy_fact",
        difficulty="hard",
        page=None,
        section_hint="Lưu ý",
        must=["không nêu rõ quan hệ ưu tiên", "quy định do bộ phận khác ban hành"],
        should=["Lưu ý"],
        metadata_focus=["section_title", "contextual_summary"],
    ),
    case(
        case_id="cs_013_product_price",
        query="Giá sản phẩm trong chính sách demo đổi trả là bao nhiêu?",
        source_file="demo_kb_chinh_sach_doi_tra_cskh - Copy.docx",
        category="numeric_value",
        difficulty="easy",
        page=None,
        section_hint="Chính sách áp dụng",
        must=["Giá sản phẩm", "3.000.000 VNĐ"],
        should=["Quy định"],
        metadata_focus=["table_header", "search_text"],
    ),
]


ABLATION_MATRIX = [
    {
        "variant": "v0_raw_text",
        "embedding_text": "chunk text only",
        "search_text": "chunk text only",
        "purpose": "Baseline thấp nhất, dùng để biết metadata có giúp gì không.",
    },
    {
        "variant": "v1_document_identity",
        "embedding_text": "title + document_type + chunk text",
        "search_text": "title + document_type + chunk text",
        "purpose": "Đo title/document_type có giảm nhầm giữa DOCX CSKH và PDF hợp đồng không.",
    },
    {
        "variant": "v2_section_structure",
        "embedding_text": "v1 + section_title + section_path",
        "search_text": "v1 + section_title + section_path",
        "purpose": "Đo heading/section_path có kéo đúng điều/phụ lục không.",
    },
    {
        "variant": "v3_block_aware",
        "embedding_text": "v2 + content_kind + table_header when available",
        "search_text": "v2 + content_kind + table_header",
        "purpose": "Đo table_header có cải thiện câu hỏi bảng trong DOCX không.",
    },
    {
        "variant": "v4_context_summary",
        "embedding_text": "v3 + contextual_summary",
        "search_text": "v3 + contextual_summary",
        "purpose": "Đo contextual_summary có cải thiện câu hỏi diễn giải/ngữ nghĩa không.",
    },
    {
        "variant": "v5_context_terms",
        "embedding_text": "v4",
        "search_text": "v4 + contextual_search_terms",
        "purpose": (
            "Đo contextual_search_terms có cải thiện hybrid/BM25 "
            "cho keyword chính xác không."
        ),
    },
    {
        "variant": "v6_domain_metadata",
        "embedding_text": "v5 + domain-specific fields where useful",
        "search_text": "v5 + domain-specific identifiers",
        "purpose": (
            "Đo metadata chuyên ngành như policy_field, clause_type, "
            "fee_type, deadline_type."
        ),
    },
]


def write_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    with path.open("w", encoding="utf-8", newline="\n") as handle:
        for row in rows:
            handle.write(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n")


def write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    fieldnames = [
        "query_id",
        "id",
        "query",
        "query_type",
        "source_file",
        "relevant_doc_titles",
        "category",
        "difficulty",
        "answerable",
        "expected_page",
        "section_hint",
        "must_include_terms",
        "should_include_terms",
        "metadata_focus",
        "expected_metadata",
    ]
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        for row in rows:
            expected = row["expected"]
            writer.writerow(
                {
                    "id": row["id"],
                    "query_id": row["query_id"],
                    "query": row["query"],
                    "query_type": row["query_type"],
                    "source_file": row["source_file"],
                    "relevant_doc_titles": " | ".join(row["relevant_doc_titles"]),
                    "category": row["category"],
                    "difficulty": row["difficulty"],
                    "answerable": row["answerable"],
                    "expected_page": expected.get("page") or "",
                    "section_hint": expected.get("section_hint") or "",
                    "must_include_terms": " | ".join(expected["must_include_terms"]),
                    "should_include_terms": " | ".join(expected["should_include_terms"]),
                    "metadata_focus": " | ".join(row["metadata_focus"]),
                    "expected_metadata": json.dumps(row["expected_metadata"], ensure_ascii=False),
                }
            )


def main() -> None:
    write_jsonl(TESTSET_PATH, TEST_CASES)
    write_csv(CSV_PATH, TEST_CASES)
    write_csv(EVALUATION_QUERIES_PATH, TEST_CASES)
    ABLATION_PATH.write_text(
        json.dumps(ABLATION_MATRIX, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    manifest = {
        "name": "retrieval_metadata_testset",
        "version": "2026-08-03.v1",
        "case_count": len(TEST_CASES),
        "source_files": SOURCE_FILES,
        "categories": sorted({case["category"] for case in TEST_CASES}),
        "recommended_k_values": [1, 3, 5, 10],
        "pass_thresholds": {
            "recall_at_5": 0.85,
            "mrr_at_10": 0.65,
            "term_hit_rate_at_5": 0.90,
            "forbidden_top1_rate": 0.10,
            "top1_mojibake_rate": 0.0,
            "p95_latency_ms_without_generation": 1000,
        },
        "outputs": {
            "testset_jsonl": TESTSET_PATH.name,
            "manual_csv": CSV_PATH.name,
            "evaluation_queries_csv": EVALUATION_QUERIES_PATH.name,
            "ablation_matrix": ABLATION_PATH.name,
        },
    }
    MANIFEST_PATH.write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(f"Wrote {len(TEST_CASES)} cases to {TESTSET_PATH}")
    print(f"Wrote manual CSV to {CSV_PATH}")
    print(f"Wrote evaluation queries CSV to {EVALUATION_QUERIES_PATH}")
    print(f"Wrote manifest to {MANIFEST_PATH}")
    print(f"Wrote ablation matrix to {ABLATION_PATH}")


if __name__ == "__main__":
    main()
