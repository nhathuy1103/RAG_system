from __future__ import annotations

import re
import unicodedata
from dataclasses import asdict, dataclass
from typing import Any

POLICY_VERSION = "scoring_normalization_v1"
_HORIZONTAL_WHITESPACE = re.compile(r"[ \t\f\v]+")
_LINE_JOIN_SAFE_BREAK = re.compile(r"\n+")


@dataclass(frozen=True)
class NormalizationResult:
    raw: str
    normalized: str
    operations: tuple[str, ...]

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def normalize_for_scoring(value: Any, *, join_lines: bool = False) -> NormalizationResult:
    raw = "" if value is None else str(value)
    operations: list[str] = []
    normalized = raw
    nfc = unicodedata.normalize("NFC", normalized)
    if nfc != normalized:
        operations.append("unicode_nfc")
        normalized = nfc
    line_normalized = normalized.replace("\r\n", "\n").replace("\r", "\n")
    if line_normalized != normalized:
        operations.append("crlf_lf")
        normalized = line_normalized
    space_normalized = normalized.replace("\u00a0", " ")
    if space_normalized != normalized:
        operations.append("nbsp_to_space")
        normalized = space_normalized
    if join_lines:
        joined = _LINE_JOIN_SAFE_BREAK.sub(" ", normalized)
        if joined != normalized:
            operations.append("safe_line_join")
            normalized = joined
    collapsed = _HORIZONTAL_WHITESPACE.sub(" ", normalized)
    if collapsed != normalized:
        operations.append("collapse_horizontal_whitespace")
        normalized = collapsed
    stripped = normalized.strip()
    if stripped != normalized:
        operations.append("trim")
        normalized = stripped
    return NormalizationResult(
        raw=raw,
        normalized=normalized,
        operations=tuple(operations),
    )


def exact_match_trace(expected: Any, actual: Any, *, join_lines: bool = False) -> dict[str, Any]:
    expected_result = normalize_for_scoring(expected, join_lines=join_lines)
    actual_result = normalize_for_scoring(actual, join_lines=join_lines)
    matched = expected_result.normalized == actual_result.normalized
    return {
        "policy_version": POLICY_VERSION,
        "raw_expected": expected_result.raw,
        "raw_actual": actual_result.raw,
        "normalized_expected": expected_result.normalized,
        "normalized_actual": actual_result.normalized,
        "normalization_operations": {
            "expected": list(expected_result.operations),
            "actual": list(actual_result.operations),
        },
        "matched": matched,
        "mismatch_reason": None
        if matched
        else _mismatch_reason(expected_result.normalized, actual_result.normalized),
    }


def normalized_text(value: Any, *, join_lines: bool = False) -> str:
    return normalize_for_scoring(value, join_lines=join_lines).normalized


def _mismatch_reason(expected: str, actual: str) -> str:
    if expected.lower() == actual.lower():
        return "case_difference"
    if expected.replace(" ", "") == actual.replace(" ", ""):
        return "token_spacing_difference"
    if _contains_digit(expected) or _contains_digit(actual):
        return "exact_numeric_or_period_sensitive_mismatch"
    return "exact_text_mismatch"


def _contains_digit(value: str) -> bool:
    return any(char.isdigit() for char in value)
