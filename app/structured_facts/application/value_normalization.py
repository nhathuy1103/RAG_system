"""Deterministic, operator-aware normalization for P3 business values."""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation

from app.structured_facts.domain.models import (
    ValueExpression,
    ValueExpressionRelation,
    ValueOperator,
)

VALUE_NORMALIZER_VERSION = "p3-value-expression-v1"
OPERATOR_NORMALIZER_VERSION = "p3-operator-normalization-v1"
DEFAULT_APPROXIMATION_RELATIVE_TOLERANCE = Decimal("0.02")
APPROXIMATION_RELATIVE_TOLERANCES: dict[str, Decimal] = {
    "property_price": Decimal("0.02"),
    "vehicle_price": Decimal("0.02"),
    "driving_range": Decimal("0.02"),
    "battery_capacity": Decimal("0.01"),
    "charging_time": Decimal("0.02"),
    "charging_power": Decimal("0.01"),
    "motor_power": Decimal("0.01"),
    "torque": Decimal("0.01"),
    "property_area": Decimal("0.01"),
}

_NUMBER = r"[+-]?\d(?:[\d\s.,]*\d)?"
_RANGE_RE = re.compile(
    rf"(?P<lower>{_NUMBER})\s*(?:[–—-]|\b(?:den|to|and)\b)\s*(?P<upper>{_NUMBER})",
    re.IGNORECASE,
)
_NUMBER_RE = re.compile(_NUMBER)

_OPERATOR_PATTERNS: tuple[tuple[ValueOperator, tuple[str, ...]], ...] = (
    (
        ValueOperator.LTE,
        ("toi da", "khong qua", "khong vuot qua", "khong lon hon", "at most", "no more than"),
    ),
    (
        ValueOperator.GTE,
        ("it nhat", "khong thap hon", "toi thieu", "tu", "at least", "no less than"),
    ),
    (ValueOperator.GT, ("tren", "lon hon", "more than", "greater than")),
    (ValueOperator.LT, ("duoi", "nho hon", "less than")),
)
_APPROXIMATE_MARKERS = (
    "khoang",
    "xap xi",
    "uoc tinh",
    "gan",
    "approximately",
    "about",
    "around",
    "approx",
)
_NEGATIONS = (
    "khong duoc trang bi",
    "khong ho tro",
    "khong co",
    "without",
    "not available",
    "does not support",
)
_POSITIVE_BOOLEAN = ("co ", "duoc trang bi", "ho tro", "available", "equipped", "supports")


@dataclass(frozen=True, slots=True)
class ValueParseResult:
    expression: ValueExpression
    reason_codes: tuple[str, ...] = ()


def normalize_value_expression(
    text: str,
    *,
    predicate: str | None = None,
    unit_hint: str | None = None,
    currency_hint: str | None = None,
    basis_hint: str | None = None,
) -> ValueParseResult:
    """Parse a bounded value phrase using Decimal and explicit semantics."""
    raw = text.strip()
    folded = _fold(raw)
    canonical_predicate = (predicate or "").casefold()

    if canonical_predicate in {"feature_availability", "availability", "payment_term"}:
        negative = any(marker in folded for marker in _NEGATIONS)
        positive = any(marker in folded for marker in _POSITIVE_BOOLEAN)
        if negative or positive:
            expression = ValueExpression(
                operator=ValueOperator.BOOLEAN,
                value=not negative,
                raw_value=raw,
                confidence=0.99 if negative else 0.96,
            )
            return ValueParseResult(expression, ("boolean_polarity",))

    if _looks_ocr_corrupted(raw):
        return ValueParseResult(
            ValueExpression(
                operator=ValueOperator.UNKNOWN,
                raw_value=raw,
                confidence=0.2,
            ),
            ("ocr_numeric_ambiguity",),
        )

    unit, currency, basis, magnitude = _value_dimensions(
        raw,
        predicate=canonical_predicate,
        unit_hint=unit_hint,
        currency_hint=currency_hint,
        basis_hint=basis_hint,
    )
    range_match = _RANGE_RE.search(folded)
    if range_match is not None:
        lower, lower_confidence = parse_decimal_locale(range_match.group("lower"), context=folded)
        upper, upper_confidence = parse_decimal_locale(range_match.group("upper"), context=folded)
        if lower is not None and upper is not None:
            confidence = min(lower_confidence, upper_confidence)
            return ValueParseResult(
                ValueExpression(
                    operator=ValueOperator.RANGE,
                    lower=lower * magnitude,
                    upper=upper * magnitude,
                    unit=unit,
                    currency=currency,
                    basis=basis,
                    raw_value=raw,
                    confidence=confidence,
                ),
                ("range_expression",),
            )

    numeric_match = _NUMBER_RE.search(folded)
    if numeric_match is None:
        if canonical_predicate in {"amenity", "construction_progress", "payment_term"}:
            return ValueParseResult(
                ValueExpression(
                    operator=ValueOperator.TEXT,
                    value=folded,
                    raw_value=raw,
                    confidence=0.8,
                ),
                ("text_value",),
            )
        return ValueParseResult(
            ValueExpression(
                operator=ValueOperator.UNKNOWN,
                raw_value=raw,
                confidence=0.25,
            ),
            ("missing_numeric_value",),
        )

    number, parse_confidence = parse_decimal_locale(numeric_match.group(0), context=folded)
    if number is None:
        return ValueParseResult(
            ValueExpression(
                operator=ValueOperator.UNKNOWN,
                unit=unit,
                currency=currency,
                basis=basis,
                raw_value=raw,
                confidence=parse_confidence,
            ),
            ("ambiguous_decimal_separator",),
        )
    operator = ValueOperator.EXACT
    for candidate, markers in _OPERATOR_PATTERNS:
        if any(marker in folded for marker in markers):
            operator = candidate
            break
    if operator is ValueOperator.EXACT and any(marker in folded for marker in _APPROXIMATE_MARKERS):
        operator = ValueOperator.APPROXIMATE
    return ValueParseResult(
        ValueExpression(
            operator=operator,
            value=number * magnitude,
            unit=unit,
            currency=currency,
            basis=basis,
            raw_value=raw,
            confidence=parse_confidence,
        ),
        (f"operator:{operator.value}",),
    )


def parse_decimal_locale(raw: str, *, context: str = "") -> tuple[Decimal | None, float]:
    """Parse Vietnamese/English separators without a global comma replacement."""
    token = re.sub(r"\s+", "", raw.strip())
    sign = ""
    if token[:1] in {"+", "-"}:
        sign, token = token[0], token[1:]
    if not token or not token[0].isdigit():
        return None, 0.0
    commas, dots = token.count(","), token.count(".")
    normalized = token
    confidence = 1.0
    if commas and dots:
        decimal_separator = "," if token.rfind(",") > token.rfind(".") else "."
        grouping_separator = "." if decimal_separator == "," else ","
        normalized = token.replace(grouping_separator, "").replace(decimal_separator, ".")
    elif commas or dots:
        separator = "," if commas else "."
        parts = token.split(separator)
        all_grouped = len(parts) > 2 and all(len(part) == 3 for part in parts[1:])
        one_group = len(parts) == 2 and len(parts[1]) == 3 and len(parts[0]) <= 3
        folded_context = _fold(context)
        english_decimal = bool(re.search(r"\b(?:billion|million|bn|mn)\b", folded_context))
        vietnamese_decimal = separator == "," and len(parts) == 2 and len(parts[1]) <= 2
        if all_grouped or (one_group and not english_decimal and not vietnamese_decimal):
            normalized = "".join(parts)
        else:
            normalized = ".".join(parts)
            if one_group and separator == "." and not english_decimal:
                confidence = 0.75
    try:
        value = Decimal(sign + normalized)
    except InvalidOperation:
        return None, 0.0
    return (value, confidence) if value.is_finite() else (None, 0.0)


def compare_value_expressions(
    left: ValueExpression,
    right: ValueExpression,
    *,
    predicate: str | None = None,
    approximation_tolerance: Decimal | None = None,
) -> ValueExpressionRelation:
    """Compare logical value sets; this never returns a document relation."""
    tolerance = (
        approximation_tolerance
        if approximation_tolerance is not None
        else APPROXIMATION_RELATIVE_TOLERANCES.get(
            (predicate or "").casefold(),
            DEFAULT_APPROXIMATION_RELATIVE_TOLERANCE,
        )
    )
    if tolerance < 0:
        raise ValueError("approximation_tolerance cannot be negative")
    if left.operator is ValueOperator.UNKNOWN or right.operator is ValueOperator.UNKNOWN:
        return ValueExpressionRelation.UNKNOWN
    if not _dimensions_compatible(left, right):
        return ValueExpressionRelation.INCOMPATIBLE_DIMENSION
    if left.operator is ValueOperator.BOOLEAN or right.operator is ValueOperator.BOOLEAN:
        if left.operator is not right.operator:
            return ValueExpressionRelation.UNKNOWN
        return (
            ValueExpressionRelation.EQUIVALENT
            if left.value == right.value
            else ValueExpressionRelation.DISJOINT
        )
    if left.operator in {ValueOperator.TEXT, ValueOperator.ENUM} or right.operator in {
        ValueOperator.TEXT,
        ValueOperator.ENUM,
    }:
        if left.operator is not right.operator:
            return ValueExpressionRelation.UNKNOWN
        return (
            ValueExpressionRelation.EQUIVALENT
            if _fold(str(left.value)) == _fold(str(right.value))
            else ValueExpressionRelation.DISJOINT
        )
    left_interval = _numeric_interval(left, tolerance)
    right_interval = _numeric_interval(right, tolerance)
    if left_interval is None or right_interval is None:
        return ValueExpressionRelation.UNKNOWN
    left_low, left_high, left_low_closed, left_high_closed = left_interval
    right_low, right_high, right_low_closed, right_high_closed = right_interval
    if left_interval == right_interval:
        return ValueExpressionRelation.EQUIVALENT
    if _intervals_disjoint(
        left_low,
        left_high,
        left_low_closed,
        left_high_closed,
        right_low,
        right_high,
        right_low_closed,
        right_high_closed,
    ):
        return ValueExpressionRelation.DISJOINT
    return ValueExpressionRelation.COMPATIBLE


def canonical_unit(value: str | None) -> str | None:
    if value is None:
        return None
    folded = _fold(value).replace(" ", "")
    aliases = {
        "money": "money",
        "vnd": "money",
        "vnd/can": "money",
        "km": "km",
        "kilometer": "km",
        "kilometre": "km",
        "kilomet": "km",
        "m": "m",
        "meter": "m",
        "metre": "m",
        "m2": "m2",
        "sqm": "m2",
        "kwh": "kWh",
        "wh": "Wh",
        "kw": "kW",
        "w": "W",
        "nm": "Nm",
        "minute": "minute",
        "minutes": "minute",
        "phut": "minute",
        "second": "second",
        "seconds": "second",
        "giay": "second",
        "%": "percent",
        "percent": "percent",
        "percentage": "percent",
        "month": "month",
        "months": "month",
        "thang": "month",
        "year": "year",
        "years": "year",
        "nam": "year",
    }
    return aliases.get(folded, value.strip())


def _value_dimensions(
    text: str,
    *,
    predicate: str,
    unit_hint: str | None,
    currency_hint: str | None,
    basis_hint: str | None,
) -> tuple[str | None, str | None, str | None, Decimal]:
    folded = _fold(text)
    unit = canonical_unit(unit_hint)
    currency = currency_hint.upper() if currency_hint else None
    basis = basis_hint
    magnitude = Decimal(1)
    if re.search(r"\b(?:ty|billion|bn)\b", folded) or re.search(r"\d\s*b\b", folded):
        magnitude = Decimal("1000000000")
    elif re.search(r"\b(?:trieu|million|mn)\b", folded) or (
        predicate in {"property_price", "vehicle_price", "management_fee", "maintenance_fee"}
        and re.search(r"\d\s*m\b", folded)
    ):
        magnitude = Decimal("1000000")
    elif re.search(r"\b(?:nghin|ngan|thousand)\b", folded):
        magnitude = Decimal("1000")
    if predicate in {
        "property_price",
        "vehicle_price",
        "management_fee",
        "maintenance_fee",
    } or re.search(r"\b(?:vnd|usd|eur|dong)\b|[$€]", folded):
        unit = "money"
        if currency is None:
            currency = (
                "USD"
                if "usd" in folded or "$" in text
                else "EUR"
                if "eur" in folded or "€" in text
                else "VND"
            )
        if basis is None:
            basis = (
                "per_sqm" if re.search(r"/(?:m2|sqm)|per\s+(?:m2|square)", folded) else "total_unit"
            )
    elif re.search(r"\bkwh\b", folded):
        unit = "kWh"
    elif re.search(r"\bwh\b", folded):
        unit = "Wh"
    elif re.search(r"\bkw\b", folded):
        unit = "kW"
    elif re.search(r"\bw\b", folded):
        unit = "W"
    elif re.search(r"\bnm\b", folded):
        unit = "Nm"
    elif re.search(r"\b(?:km|kilomet(?:er|re)?s?)\b", folded):
        unit = "km"
    elif re.search(r"\bm(?:2|²)\b|\bsqm\b", folded):
        unit = "m2"
    elif re.search(r"\b(?:minutes?|phut)\b", folded):
        unit = "minute"
    elif re.search(r"\b(?:seconds?|giay)\b", folded):
        unit = "second"
    elif "%" in text or "percent" in folded:
        unit = "percent"
    elif re.search(r"\b(?:months?|thang)\b", folded):
        unit = "month"
    elif re.search(r"\b(?:years?|nam)\b", folded):
        unit = "year"
    elif re.search(r"\bm\b", folded):
        unit = "m"
    return unit, currency, basis, magnitude


def _dimensions_compatible(left: ValueExpression, right: ValueExpression) -> bool:
    if left.currency and right.currency and left.currency.upper() != right.currency.upper():
        return False
    if left.basis and right.basis and _fold(left.basis) != _fold(right.basis):
        return False
    left_unit = canonical_unit(left.unit)
    right_unit = canonical_unit(right.unit)
    if left_unit == right_unit:
        return True
    dimensions = (
        {"km", "m"},
        {"kWh", "Wh"},
        {"kW", "W"},
        {"minute", "second"},
        {"year", "month"},
    )
    return any({left_unit, right_unit} <= dimension for dimension in dimensions)


def _numeric_interval(
    expression: ValueExpression,
    tolerance: Decimal,
) -> tuple[Decimal | None, Decimal | None, bool, bool] | None:
    factor = _unit_factor(canonical_unit(expression.unit))
    if expression.operator is ValueOperator.RANGE:
        if expression.lower is None or expression.upper is None:
            return None
        return expression.lower * factor, expression.upper * factor, True, True
    number = _as_decimal(expression.value)
    if number is None:
        return None
    number *= factor
    if expression.operator is ValueOperator.EXACT:
        return number, number, True, True
    if expression.operator is ValueOperator.APPROXIMATE:
        delta = abs(number) * tolerance
        return number - delta, number + delta, True, True
    if expression.operator is ValueOperator.LT:
        return None, number, False, False
    if expression.operator is ValueOperator.LTE:
        return None, number, False, True
    if expression.operator is ValueOperator.GT:
        return number, None, False, False
    if expression.operator is ValueOperator.GTE:
        return number, None, True, False
    return None


def _intervals_disjoint(
    left_low: Decimal | None,
    left_high: Decimal | None,
    left_low_closed: bool,
    left_high_closed: bool,
    right_low: Decimal | None,
    right_high: Decimal | None,
    right_low_closed: bool,
    right_high_closed: bool,
) -> bool:
    if (
        left_high is not None
        and right_low is not None
        and (
            left_high < right_low
            or (left_high == right_low and not (left_high_closed and right_low_closed))
        )
    ):
        return True
    return bool(
        right_high is not None
        and left_low is not None
        and (
            right_high < left_low
            or (right_high == left_low and not (right_high_closed and left_low_closed))
        )
    )


def _unit_factor(unit: str | None) -> Decimal:
    return {
        "km": Decimal("1000"),
        "m": Decimal(1),
        "kWh": Decimal("1000"),
        "Wh": Decimal(1),
        "kW": Decimal("1000"),
        "W": Decimal(1),
        "minute": Decimal("60"),
        "second": Decimal(1),
        "year": Decimal("12"),
        "month": Decimal(1),
    }.get(unit or "", Decimal(1))


def _as_decimal(value: object) -> Decimal | None:
    if isinstance(value, bool) or value is None:
        return None
    try:
        parsed = Decimal(str(value))
    except (InvalidOperation, ValueError):
        return None
    return parsed if parsed.is_finite() else None


def _looks_ocr_corrupted(value: str) -> bool:
    return bool(
        re.search(r"(?<=\d)[oO](?=\d)|(?<=\d)[oO]\b|\b[oO](?=\d)", value)
        or re.search(r"\b(?:ocr|khong chac chan|uncertain)\b", _fold(value))
    )


def _fold(value: str) -> str:
    normalized = unicodedata.normalize("NFKD", value.casefold()).replace("đ", "d")
    plain = "".join(character for character in normalized if not unicodedata.combining(character))
    return " ".join(re.sub(r"[^a-z0-9%$€.,/²+–—-]+", " ", plain).split())


__all__ = [
    "APPROXIMATION_RELATIVE_TOLERANCES",
    "DEFAULT_APPROXIMATION_RELATIVE_TOLERANCE",
    "OPERATOR_NORMALIZER_VERSION",
    "VALUE_NORMALIZER_VERSION",
    "ValueParseResult",
    "canonical_unit",
    "compare_value_expressions",
    "normalize_value_expression",
    "parse_decimal_locale",
]
