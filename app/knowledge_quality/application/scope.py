"""Deterministic document-scope extraction and conservative comparison."""

from __future__ import annotations

import re
import unicodedata
from dataclasses import replace
from pathlib import PurePath

from app.knowledge_quality.domain.models import ClaimScope, ScopeComparison

_PROJECT_PATTERNS = (
    re.compile(
        r"\b(?:dự\s*án|du\s*an|project(?:\s+name)?)\s*[:\-]?\s*"
        r"(?P<value>[\wÀ-ỹ]+(?:[\s\-]+[\wÀ-ỹ]+){0,11}?)"
        r"(?=\s+(?:có\s+nghĩa|có|áp\s+dụng|thuộc|tại|do|has|is|applies|located)\b|"
        r"[,.;\n]|$)",
        re.IGNORECASE | re.UNICODE,
    ),
    re.compile(
        r"\b(?:project)\s*[:\-]\s*(?P<value>[^,.;\n]{3,100})",
        re.IGNORECASE | re.UNICODE,
    ),
)
_PROJECT_DEFINITION_PATTERN = re.compile(
    r"\b(?:dự\s*án|du\s*an)\s*(?:[\"”']?\s*)?(?:có\s+nghĩa\s+là|nghĩa\s+là)\s*"
    r"(?P<value>[^.;\n]{4,140})",
    re.IGNORECASE | re.UNICODE,
)
_CONTRACT_PATTERN = re.compile(
    r"\b(?:s\u1ed1\s+h\u1ee3p\s+\u0111\u1ed3ng|so\s+hop\s+dong|"
    r"contract(?:\s+(?:id|number|no\.?))?|agreement\s+no\.?)\s*[:#\-]\s*"
    r"(?P<value>[A-Z0-9][A-Z0-9./\-]{4,79})\b",
    re.IGNORECASE | re.UNICODE,
)
_PLACEHOLDER_PATTERN = re.compile(r"^[.\-_/\s]+$")
_DOCUMENT_TYPES = (
    ("housing_sale_contract", re.compile(r"hợp\s+đồng\s+mua\s+bán\s+nhà\s+ở", re.IGNORECASE)),
    (
        "commercial_area_sale_contract",
        re.compile(r"hợp\s+đồng\s+mua\s+bán\s+diện\s+tích\s+thương\s+mại", re.IGNORECASE),
    ),
    ("sale_contract", re.compile(r"\b(?:hợp\s+đồng\s+mua\s+bán|sale\s+contract)\b", re.IGNORECASE)),
    ("contract", re.compile(r"\b(?:hợp\s+đồng|contract)\b", re.IGNORECASE)),
)
_FILENAME_NOISE = frozenset(
    {
        "document",
        "contract",
        "hop",
        "dong",
        "mua",
        "ban",
        "vinhomes",
        "pdf",
        "doc",
        "docx",
        "final",
        "signed",
        "copy",
    }
)


def normalize_scope_value(value: str) -> str:
    """Normalize an identifier for comparison without changing source text."""
    decomposed = unicodedata.normalize("NFKD", value.casefold())
    ascii_like = "".join(
        character for character in decomposed if not unicodedata.combining(character)
    )
    return " ".join(re.findall(r"[^\W_]+", ascii_like, re.UNICODE))


def extract_claim_scope(
    text: str,
    *,
    document_id: str | None = None,
    canonical_document_id: str | None = None,
    filename: str | None = None,
    version_id: str | None = None,
) -> ClaimScope:
    """Extract stable project/contract scope, using filename only as fallback."""
    project_id = _extract_project_id(text)
    if project_id is None and filename:
        project_id = _filename_scope_hint(filename)
    contract_id = _extract_contract_id(text)
    document_type = _extract_document_type(text)
    entities = tuple(
        value
        for value in (
            f"project:{project_id}" if project_id else None,
            f"contract:{contract_id}" if contract_id else None,
            f"document_type:{document_type}" if document_type else None,
        )
        if value is not None
    )
    return ClaimScope(
        document_id=document_id,
        canonical_document_id=canonical_document_id,
        project_id=project_id,
        contract_id=contract_id,
        document_type=document_type,
        contract_type=document_type,
        subject_entities=entities,
        version_id=version_id,
    )


def merge_claim_scopes(
    primary: ClaimScope | None,
    fallback: ClaimScope | None,
) -> ClaimScope | None:
    """Fill missing persisted fields from content-derived fallback evidence."""
    if primary is None:
        return fallback
    if fallback is None:
        return primary
    return replace(
        primary,
        document_id=primary.document_id or fallback.document_id,
        canonical_document_id=primary.canonical_document_id or fallback.canonical_document_id,
        project_id=primary.project_id or fallback.project_id,
        contract_id=primary.contract_id or fallback.contract_id,
        document_type=primary.document_type or fallback.document_type,
        contract_type=primary.contract_type or fallback.contract_type,
        subject_entities=primary.subject_entities or fallback.subject_entities,
        effective_date=primary.effective_date or fallback.effective_date,
        version_id=primary.version_id or fallback.version_id,
    )


def compare_claim_scopes(
    left: ClaimScope | None,
    right: ClaimScope | None,
) -> ScopeComparison:
    """Compare only explicit logical identifiers; upload IDs alone are neutral."""
    if left is None or right is None:
        return ScopeComparison.UNKNOWN_SCOPE
    for left_value, right_value in (
        (left.canonical_document_id, right.canonical_document_id),
        (left.project_id, right.project_id),
        (left.contract_id, right.contract_id),
    ):
        if (
            left_value
            and right_value
            and normalize_scope_value(left_value) != normalize_scope_value(right_value)
        ):
            return ScopeComparison.DIFFERENT_SCOPE

    same_evidence = any(
        left_value
        and right_value
        and normalize_scope_value(left_value) == normalize_scope_value(right_value)
        for left_value, right_value in (
            (left.canonical_document_id, right.canonical_document_id),
            (left.project_id, right.project_id),
            (left.contract_id, right.contract_id),
        )
    )
    return ScopeComparison.SAME_SCOPE if same_evidence else ScopeComparison.UNKNOWN_SCOPE


def scope_reason_codes(
    left: ClaimScope | None,
    right: ClaimScope | None,
) -> tuple[str, ...]:
    """Explain which explicit identifiers caused a different-scope decision."""
    if compare_claim_scopes(left, right) is not ScopeComparison.DIFFERENT_SCOPE:
        return ()
    reasons = ["different_claim_scope"]
    if left and right and _different(left.project_id, right.project_id):
        reasons.append("different_project_entity")
    if left and right and _different(left.contract_id, right.contract_id):
        reasons.append("different_contract_entity")
    return tuple(reasons)


def _different(left: str | None, right: str | None) -> bool:
    return bool(left and right and normalize_scope_value(left) != normalize_scope_value(right))


def _extract_project_id(text: str) -> str | None:
    definition = _PROJECT_DEFINITION_PATTERN.search(text)
    if definition is not None:
        return _clean_identifier(definition.group("value"))
    for pattern in _PROJECT_PATTERNS:
        match = pattern.search(text)
        if match is not None:
            value = _clean_identifier(match.group("value"))
            if value:
                return value
    return None


def _extract_contract_id(text: str) -> str | None:
    for match in _CONTRACT_PATTERN.finditer(text[:12000]):
        value = match.group("value").strip()
        if not _PLACEHOLDER_PATTERN.fullmatch(value) and any(
            character.isdigit() for character in value
        ):
            return normalize_scope_value(value)
    return None


def _extract_document_type(text: str) -> str | None:
    header = text[:4000]
    for name, pattern in _DOCUMENT_TYPES:
        if pattern.search(header):
            return name
    return None


def _filename_scope_hint(filename: str) -> str | None:
    stem = PurePath(filename.replace("\\", "/")).stem
    tokens = [
        token
        for token in normalize_scope_value(stem).split()
        if token not in _FILENAME_NOISE and not token.isdigit()
    ]
    return " ".join(tokens) or None


def _clean_identifier(value: str) -> str | None:
    normalized = normalize_scope_value(value)
    return normalized[:160] or None


__all__ = [
    "compare_claim_scopes",
    "extract_claim_scope",
    "merge_claim_scopes",
    "normalize_scope_value",
    "scope_reason_codes",
]
