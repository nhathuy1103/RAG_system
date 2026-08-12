"""Versioned, domain-aware predicate taxonomy for canonical P3 claims."""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass

PREDICATE_REGISTRY_VERSION = "p3-predicate-registry-v1"

VINHOMES_PREDICATES = (
    "property_price",
    "property_area",
    "management_fee",
    "maintenance_fee",
    "discount_rate",
    "payment_term",
    "handover_time",
    "availability",
    "amenity",
    "construction_progress",
)
VINFAST_PREDICATES = (
    "vehicle_price",
    "driving_range",
    "battery_capacity",
    "charging_time",
    "charging_power",
    "motor_power",
    "torque",
    "acceleration",
    "feature_availability",
    "warranty_duration",
    "vehicle_dimensions",
    "service_feature",
)

_ALIASES: dict[str, tuple[tuple[str, ...], ...]] = {
    "vinhomes": (
        ("management_fee", "phi quan ly", "management fee"),
        ("maintenance_fee", "phi bao tri", "maintenance fee"),
        ("discount_rate", "muc chiet khau", "chiet khau", "discount rate", "discount"),
        (
            "payment_term",
            "thoi han thanh toan",
            "phuong thuc thanh toan",
            "ho tro tra gop",
            "ho tro thanh toan tra gop",
            "payment term",
            "payment support",
        ),
        ("handover_time", "thoi gian ban giao", "ngay ban giao", "ban giao", "handover"),
        ("property_area", "dien tich", "area", "square metres", "square meters"),
        ("construction_progress", "tien do xay dung", "tien do thi cong", "construction progress"),
        ("availability", "con hang", "con can", "available", "availability"),
        ("amenity", "tien ich", "khu sinh hoat cong dong", "amenity"),
        (
            "property_price",
            "gia ban",
            "muc gia",
            "gia can ho",
            "gia can",
            "gia niem yet",
            "gia tham khao",
            "gia tham chieu",
            "duoc tham chieu o muc",
            "gia",
            "price",
            "list price",
        ),
    ),
    "vinfast": (
        ("battery_capacity", "dung luong pin", "battery capacity", "pin"),
        ("charging_time", "thoi gian sac", "charging time", "sac nhanh trong"),
        ("charging_power", "cong suat sac", "charging power"),
        ("motor_power", "cong suat dong co", "motor power"),
        ("torque", "mo men xoan", "torque"),
        ("acceleration", "tang toc", "acceleration"),
        ("warranty_duration", "thoi han bao hanh", "bao hanh", "warranty"),
        ("vehicle_dimensions", "kich thuoc xe", "kich thuoc", "dimensions"),
        (
            "driving_range",
            "tam hoat dong",
            "pham vi hoat dong",
            "quang duong di chuyen",
            "tam tham chieu",
            "tam",
            "driving range",
            "range",
        ),
        ("vehicle_price", "gia ban", "gia niem yet", "gia xe", "vehicle price", "list price"),
        ("feature_availability", "tinh nang", "duoc trang bi", "khong ho tro", "feature"),
        ("service_feature", "goi ho tro dich vu", "cong sac thu nghiem", "service package"),
    ),
}

_LEGACY_CANONICAL = {
    "sale_price": "property_price",
    "list_price": "property_price",
    "discounted_price": "property_price",
    "price_per_sqm": "property_price",
    "vehicle_range": "driving_range",
    "range": "driving_range",
    "vehicle_battery_capacity": "battery_capacity",
    "feature": "feature_availability",
    "price": "property_price",
}


@dataclass(frozen=True, slots=True)
class PredicateMatch:
    predicate: str
    alias: str
    start: int
    end: int
    confidence: float = 0.99


def canonicalize_predicate(predicate: str, *, domain: str | None = None) -> str:
    normalized = predicate.strip().casefold()
    if normalized == "property_price" and domain == "vinfast":
        return "vehicle_price"
    return _LEGACY_CANONICAL.get(normalized, normalized)


def find_predicate_matches(text: str, *, domain: str | None) -> tuple[PredicateMatch, ...]:
    """Return non-overlapping business predicates; generic verbs are ignored."""
    if domain not in _ALIASES:
        return ()
    folded, offsets = _fold_with_offsets(text)
    candidates: list[PredicateMatch] = []
    for entry in _ALIASES[domain]:
        predicate, *aliases = entry
        for alias in aliases:
            for match in re.finditer(rf"(?<![a-z0-9]){re.escape(alias)}(?![a-z0-9])", folded):
                start = offsets[match.start()]
                end = offsets[match.end() - 1] + 1
                candidates.append(
                    PredicateMatch(
                        predicate=predicate,
                        alias=text[start:end],
                        start=start,
                        end=end,
                    )
                )
    selected: list[PredicateMatch] = []
    for candidate in sorted(candidates, key=lambda item: (item.start, -(item.end - item.start))):
        if any(candidate.start < item.end and item.start < candidate.end for item in selected):
            continue
        selected.append(candidate)
    by_predicate: dict[str, PredicateMatch] = {}
    for item in sorted(selected, key=lambda candidate: candidate.start):
        by_predicate.setdefault(item.predicate, item)
    return tuple(sorted(by_predicate.values(), key=lambda item: item.start))


def _fold_with_offsets(value: str) -> tuple[str, tuple[int, ...]]:
    """Fold accents while retaining a map back to the original source span.

    NFD OCR/text variants contain standalone combining marks. Treating those
    marks as spaces breaks otherwise exact aliases; dropping them without an
    offset map makes provenance spans incorrect.
    """
    result: list[str] = []
    offsets: list[int] = []
    for index, character in enumerate(value.casefold()):
        if unicodedata.combining(character):
            continue
        if character == "đ":
            result.append("d")
            offsets.append(index)
            continue
        decomposed = unicodedata.normalize("NFKD", character)
        base = next((part for part in decomposed if not unicodedata.combining(part)), character)
        result.append(base if base.isalnum() else " ")
        offsets.append(index)
    return "".join(result), tuple(offsets)


__all__ = [
    "PREDICATE_REGISTRY_VERSION",
    "PredicateMatch",
    "VINFAST_PREDICATES",
    "VINHOMES_PREDICATES",
    "canonicalize_predicate",
    "find_predicate_matches",
]
