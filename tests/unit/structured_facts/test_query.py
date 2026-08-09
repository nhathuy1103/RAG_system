import pytest

from app.structured_facts.application.query import parse_structured_fact_query


def test_routes_exact_vietnamese_price_question_with_historical_month() -> None:
    intent = parse_structured_fact_query("Giá căn A101 tháng 3/2025 là bao nhiêu?")

    assert intent is not None
    assert intent.predicate == "sale_price"
    assert intent.subject_query == "a101"
    assert intent.valid_time is not None
    assert intent.valid_time.start.isoformat().startswith("2025-03-01")


def test_broad_price_question_fails_closed_to_vector_retrieval() -> None:
    assert parse_structured_fact_query("Bảng giá hiện tại thế nào?") is None


def test_non_structured_question_is_not_routed() -> None:
    assert parse_structured_fact_query("Tóm tắt chính sách bán hàng") is None


@pytest.mark.parametrize(
    ("question", "expected"),
    [
        (
            "Giá niêm yết căn A101 là bao nhiêu?",
            {"stable": {"price_type": "list_price"}},
        ),
        (
            "Giá sau chiết khấu căn A101 là bao nhiêu?",
            {"stable": {"price_type": "discounted_price"}},
        ),
        (
            "Đơn giá đã bao gồm VAT theo thanh toán sớm căn A101?",
            {
                "stable": {
                    "price_basis": "per_sqm",
                    "payment_plan": "early_payment",
                },
                "optional": {"vat_included": True},
            },
        ),
        (
            "Tổng giá chưa VAT căn A101?",
            {
                "stable": {"price_basis": "total_unit"},
                "optional": {"vat_included": False},
            },
        ),
        (
            "Giá căn A101 theo phương án thanh toán tiêu chuẩn?",
            {"stable": {"payment_plan": "tieu chuan"}},
        ),
    ],
)
def test_extracts_price_qualifiers_fail_closed(
    question: str,
    expected: dict[str, object],
) -> None:
    intent = parse_structured_fact_query(question)

    assert intent is not None
    assert intent.predicate == "sale_price"
    assert intent.subject_query == "a101"
    assert intent.qualifiers == expected


def test_multiple_price_variants_fail_closed_to_hybrid_retrieval() -> None:
    assert (
        parse_structured_fact_query("So sánh giá niêm yết và giá sau chiết khấu căn A101") is None
    )


def test_explicit_unit_code_wins_over_bedroom_dimension() -> None:
    intent = parse_structured_fact_query("Giá căn hộ 2PN mã A101 là bao nhiêu?")

    assert intent is not None
    assert intent.subject_query == "a101"


def test_measurement_unit_is_not_mistaken_for_a_subject() -> None:
    assert parse_structured_fact_query("Đơn giá theo m² là bao nhiêu?") is None


def test_vat_status_question_does_not_assume_yes_or_no() -> None:
    intent = parse_structured_fact_query("Giá căn A101 có bao gồm VAT không?")

    assert intent is not None
    assert intent.qualifiers == {}


def test_inventory_code_starting_with_m_is_not_rejected_as_square_metre() -> None:
    intent = parse_structured_fact_query("Giá căn M12 là bao nhiêu?")

    assert intent is not None
    assert intent.subject_query == "m12"


def test_building_code_is_not_mistaken_for_a_unit_subject() -> None:
    assert parse_structured_fact_query("Giá tại tòa S12 là bao nhiêu?") is None
