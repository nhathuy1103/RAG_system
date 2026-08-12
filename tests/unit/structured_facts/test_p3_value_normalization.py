from __future__ import annotations

from decimal import Decimal

import pytest

from app.structured_facts.application.value_normalization import (
    compare_value_expressions,
    normalize_value_expression,
    parse_decimal_locale,
)
from app.structured_facts.domain.models import ValueExpressionRelation, ValueOperator


@pytest.mark.parametrize(
    ("raw", "expected"),
    (
        ("6,2", Decimal("6.2")),
        ("6.2", Decimal("6.2")),
        ("6.200", Decimal("6200")),
        ("6,200,000,000", Decimal("6200000000")),
        ("6.200.000.000", Decimal("6200000000")),
    ),
)
def test_locale_decimal_parser(raw: str, expected: Decimal) -> None:
    value, confidence = parse_decimal_locale(raw)

    assert value == expected
    assert confidence >= 0.75


def test_money_magnitudes_are_equivalent() -> None:
    billion = normalize_value_expression("6.2 billion VND/unit", predicate="property_price")
    million = normalize_value_expression("6200 million VND/unit", predicate="property_price")
    absolute = normalize_value_expression("6,200,000,000 VND/unit", predicate="property_price")

    assert billion.expression.value == Decimal("6200000000")
    assert (
        compare_value_expressions(billion.expression, million.expression)
        is ValueExpressionRelation.EQUIVALENT
    )
    assert (
        compare_value_expressions(billion.expression, absolute.expression)
        is ValueExpressionRelation.EQUIVALENT
    )


@pytest.mark.parametrize(
    ("raw", "operator"),
    (
        ("khoảng 6,2 tỷ VND", ValueOperator.APPROXIMATE),
        ("không quá 6,5 tỷ VND", ValueOperator.LTE),
        ("ít nhất 5,8 tỷ VND", ValueOperator.GTE),
        ("trên 450 km", ValueOperator.GT),
        ("dưới 450 km", ValueOperator.LT),
        ("5,8–6,4 tỷ VND", ValueOperator.RANGE),
    ),
)
def test_operator_normalization(raw: str, operator: ValueOperator) -> None:
    assert normalize_value_expression(raw).expression.operator is operator


def test_range_and_approximate_overlap_without_false_conflict() -> None:
    value_range = normalize_value_expression("5,8–6,4 tỷ VND", predicate="property_price")
    approximate = normalize_value_expression("xấp xỉ 6,2 tỷ VND", predicate="property_price")
    too_low = normalize_value_expression("không quá 5 tỷ VND", predicate="property_price")
    seven = normalize_value_expression("7 tỷ VND", predicate="property_price")

    assert (
        compare_value_expressions(value_range.expression, approximate.expression)
        is ValueExpressionRelation.COMPATIBLE
    )
    assert (
        compare_value_expressions(too_low.expression, seven.expression)
        is ValueExpressionRelation.DISJOINT
    )


@pytest.mark.parametrize(
    ("left", "right", "expected"),
    (
        ("5,8–6,4 tỷ VND", "6,2 tỷ VND", ValueExpressionRelation.COMPATIBLE),
        ("5,8–6,4 tỷ VND", "7 tỷ VND", ValueExpressionRelation.DISJOINT),
        ("không quá 6,5 tỷ VND", "6,2 tỷ VND", ValueExpressionRelation.COMPATIBLE),
        ("không quá 5 tỷ VND", "7 tỷ VND", ValueExpressionRelation.DISJOINT),
        ("ít nhất 5 tỷ VND", "6 tỷ VND", ValueExpressionRelation.COMPATIBLE),
        ("ít nhất 8 tỷ VND", "6 tỷ VND", ValueExpressionRelation.DISJOINT),
    ),
)
def test_required_range_operator_matrix(
    left: str,
    right: str,
    expected: ValueExpressionRelation,
) -> None:
    left_value = normalize_value_expression(left, predicate="property_price").expression
    right_value = normalize_value_expression(right, predicate="property_price").expression

    assert compare_value_expressions(left_value, right_value) is expected


@pytest.mark.parametrize(
    ("left", "right"),
    (
        ("450 km", "450000 m"),
        ("87.7 kWh", "87700 Wh"),
        ("30 minutes", "1800 seconds"),
    ),
)
def test_safe_unit_equivalence(left: str, right: str) -> None:
    assert (
        compare_value_expressions(
            normalize_value_expression(left).expression,
            normalize_value_expression(right).expression,
        )
        is ValueExpressionRelation.EQUIVALENT
    )


def test_price_basis_and_currency_are_not_converted() -> None:
    per_unit = normalize_value_expression("6,2 tỷ VND/căn", predicate="property_price")
    per_sqm = normalize_value_expression("100 triệu VND/m²", predicate="property_price")
    usd = normalize_value_expression("6,2 tỷ USD/căn", predicate="property_price")

    assert (
        compare_value_expressions(per_unit.expression, per_sqm.expression)
        is ValueExpressionRelation.INCOMPATIBLE_DIMENSION
    )
    assert (
        compare_value_expressions(per_unit.expression, usd.expression)
        is ValueExpressionRelation.INCOMPATIBLE_DIMENSION
    )


def test_boolean_polarity_and_ocr_uncertainty() -> None:
    positive = normalize_value_expression("có hỗ trợ giữ làn", predicate="feature_availability")
    negative = normalize_value_expression(
        "không được trang bị hỗ trợ giữ làn", predicate="feature_availability"
    )
    corrupted = normalize_value_expression("45O km", predicate="driving_range")

    assert positive.expression.operator is ValueOperator.BOOLEAN
    assert positive.expression.value is True
    assert negative.expression.value is False
    assert (
        compare_value_expressions(positive.expression, negative.expression)
        is ValueExpressionRelation.DISJOINT
    )
    assert corrupted.expression.operator is ValueOperator.UNKNOWN


@pytest.mark.parametrize(
    ("raw", "predicate", "unit", "value"),
    (
        ("70 m²", "property_area", "m2", Decimal("70")),
        ("150 kW", "motor_power", "kW", Decimal("150")),
        ("350 Nm", "torque", "Nm", Decimal("350")),
        ("31 phút", "charging_time", "minute", Decimal("31")),
        ("80%", "discount_rate", "percent", Decimal("80")),
    ),
)
def test_required_domain_units(
    raw: str,
    predicate: str,
    unit: str,
    value: Decimal,
) -> None:
    expression = normalize_value_expression(raw, predicate=predicate).expression

    assert expression.unit == unit
    assert expression.value == value


def test_unit_dimension_mismatch_is_not_equivalent() -> None:
    distance = normalize_value_expression("450 km", predicate="driving_range").expression
    energy = normalize_value_expression("450 kWh", predicate="battery_capacity").expression

    assert (
        compare_value_expressions(distance, energy)
        is ValueExpressionRelation.INCOMPATIBLE_DIMENSION
    )
