"""Deterministic routing for exact structured-fact questions."""

from __future__ import annotations

import re
import unicodedata
from collections.abc import Mapping
from dataclasses import dataclass, field

from app.retrieval.application.temporal_query import (
    QueryTimeRange,
    extract_query_time_range,
)


@dataclass(frozen=True, slots=True)
class StructuredFactQueryIntent:
    predicate: str
    subject_query: str
    valid_time: QueryTimeRange | None = None
    confidence: float = 1.0
    qualifiers: Mapping[str, object] = field(default_factory=dict)


def parse_structured_fact_query(query: str) -> StructuredFactQueryIntent | None:
    """Route only questions with both an explicit fact type and subject key.

    Fail-closed routing is intentional: broad questions still use the existing
    hybrid retriever instead of accidentally filtering to an incomplete fact
    set.
    """

    folded = _fold(query)
    predicate = _predicate(folded)
    if predicate is None:
        return None
    subject = _subject_key(folded)
    if subject is None:
        return None
    qualifiers = _qualifier_filters(folded, predicate=predicate)
    if qualifiers is None:
        # A question asking for multiple mutually-exclusive variants cannot be
        # represented by one exact structured lookup. Keep it on the hybrid
        # path instead of silently selecting one variant.
        return None
    return StructuredFactQueryIntent(
        predicate=predicate,
        subject_query=subject,
        valid_time=extract_query_time_range(query),
        qualifiers=qualifiers,
    )


def _predicate(folded: str) -> str | None:
    if re.search(r"\b(?:gia|price|don gia|tong gia)\b", folded):
        return "sale_price"
    if re.search(r"\b(?:dien tich|area|sqm|m2)\b", folded):
        return "property_area"
    if re.search(r"\b(?:so luong|quantity)\b", folded):
        return "quantity"
    return None


def _subject_key(folded: str) -> str | None:
    # An explicit code label is more reliable than a nearby product dimension
    # (for example ``căn hộ 2PN mã A101``).
    explicit_code = re.search(
        r"\b(?:ma\s+can(?:\s+ho)?|unit\s+(?:code|id)|ma)\s*[:#-]?\s*"
        r"([a-z]{0,6}\d[a-z0-9.-]{0,12})\b",
        folded,
    )
    if explicit_code and _is_subject_token(explicit_code.group(1)):
        return explicit_code.group(1)
    labelled = re.search(
        r"\b(?:can(?:\s+ho)?|unit)\s*(?:so|ma)?\s*[:#-]?\s*"
        r"([a-z]{0,6}\d[a-z0-9.-]{0,12})\b",
        folded,
    )
    if labelled and _is_subject_token(labelled.group(1)):
        return labelled.group(1)
    # Conservative fallback for common inventory identifiers such as A101 or
    # S1-A101. A token must contain both a letter and a digit.
    broad_scope_tokens = {
        match.group(1)
        for match in re.finditer(
            r"\b(?:toa|thap|building|block|du an|project|phan khu|subdivision)"
            r"\s*[:#-]?\s*([a-z]{0,6}\d[a-z0-9.-]{0,12})\b",
            folded,
        )
    }
    for match in re.finditer(r"\b[a-z0-9][a-z0-9.-]{2,20}\b", folded):
        token = match.group(0)
        if token not in broad_scope_tokens and _is_subject_token(token):
            return token
    return None


def _is_subject_token(token: str) -> bool:
    if not any(character.isalpha() for character in token) or not any(
        character.isdigit() for character in token
    ):
        return False
    # Product dimensions and measurement units are not inventory identifiers.
    return re.fullmatch(r"(?:\d+pn|pn\d+|m2|\d+m2|sqm)", token) is None


def _qualifier_filters(
    folded: str,
    *,
    predicate: str,
) -> dict[str, object] | None:
    if predicate != "sale_price":
        return {}

    stable: dict[str, object] = {}
    optional: dict[str, object] = {}

    price_types = {
        value
        for value, pattern in (
            ("list_price", r"\b(?:gia (?:niem yet|ny)|list price)\b"),
            (
                "discounted_price",
                r"\b(?:gia (?:sau )?(?:chiet khau|ck)|discounted price|net price)\b",
            ),
        )
        if re.search(pattern, folded)
    }
    if len(price_types) > 1:
        return None
    if price_types:
        stable["price_type"] = next(iter(price_types))

    price_bases = {
        value
        for value, pattern in (
            (
                "per_sqm",
                r"\b(?:don gia|gia\s*(?:/|tren)\s*(?:m2|m 2|sqm)|gia m2|"
                r"price per (?:sqm|m2)|unit price)\b",
            ),
            ("total_unit", r"\b(?:tong gia|gia (?:toan|ca) can|total price)\b"),
        )
        if re.search(pattern, folded)
    }
    if len(price_bases) > 1:
        return None
    if price_bases:
        stable["price_basis"] = next(iter(price_bases))

    asks_vat_state = re.search(
        r"\b(?:da vat|(?:co |da )?(?:bao )?gom vat|vat included)\s+(?:khong|chua)\b",
        folded,
    )
    vat_states = (
        set()
        if asks_vat_state
        else {
            value
            for value, pattern in (
                (
                    True,
                    r"\b(?:da (?:bao gom )?vat|bao gom vat|(?<!khong )co vat|"
                    r"(?:including|included|incl) vat|vat included)\b",
                ),
                (
                    False,
                    r"\b(?:chua (?:(?:bao )?gom )?vat|"
                    r"khong (?:(?:bao )?gom |co )?vat|"
                    r"(?:excluding|excluded|excl) vat|vat excluded)\b",
                ),
            )
            if re.search(pattern, folded)
        }
    )
    if len(vat_states) > 1:
        return None
    if vat_states:
        optional["vat_included"] = next(iter(vat_states))

    payment_plan = _payment_plan_filter(folded)
    if payment_plan is not None:
        stable["payment_plan"] = payment_plan

    filters: dict[str, object] = {}
    if stable:
        filters["stable"] = stable
    if optional:
        filters["optional"] = optional
    return filters


def _payment_plan_filter(folded: str) -> str | None:
    if re.search(r"\b(?:thanh toan som|tt som|early payment)\b", folded):
        return "early_payment"
    labelled = re.search(
        r"\b(?:theo\s+|under\s+)?(?:phuong an thanh toan|tien do thanh toan|payment plan)"
        r"\s*[:#-]?\s+([a-z0-9][a-z0-9 _.-]{0,40}?)"
        r"(?=\s+(?:cho\s+)?(?:can|unit|thang|ngay|nam)\b|"
        r"\s+(?:la\s+)?bao nhieu\b|[?;,.]|$)",
        folded,
    )
    if labelled is None:
        return None
    value = " ".join(labelled.group(1).split())
    if not value or re.match(r"^(?:nao|gi|what)\b", value):
        return None
    return value


def _fold(value: str) -> str:
    normalized = unicodedata.normalize("NFKD", value).casefold().replace("đ", "d")
    return " ".join(
        "".join(
            character for character in normalized if not unicodedata.combining(character)
        ).split()
    )


__all__ = ["StructuredFactQueryIntent", "parse_structured_fact_query"]
