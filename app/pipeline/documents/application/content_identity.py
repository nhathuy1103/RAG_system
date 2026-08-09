"""Format-neutral, conservative document identity projection."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from hashlib import sha256

from app.knowledge_quality.application.analysis import (
    build_document_fingerprint,
    strict_normalize_text,
)
from app.knowledge_quality.domain.models import (
    DOCUMENT_NORMALIZATION_VERSION,
    DocumentFingerprint,
)
from app.pipeline.documents.domain.parsed import ParsedDocument, ParsedTable

_MARKDOWN_IMAGE = re.compile(r"!\[([^\]]*)\]\([^)]*\)")
_MARKDOWN_LINK = re.compile(r"(?<!!)\[([^\]]+)\]\([^)]*\)")
_MARKDOWN_CODE = re.compile(r"(?<!\\)`+([^`]+?)`+")
_MARKDOWN_STRONG = re.compile(r"(?<!\\)(\*\*|__|~~)(.+?)(?<!\\)\1")
_MARKDOWN_EMPHASIS = re.compile(r"(?<!\\)([*_])([^*_\n]+?)(?<!\\)\1")
_MARKDOWN_LIST_MARKER = re.compile(
    r"^\s*(?:[-+*]\s+|\d{1,6}[.)]\s+|>\s*)",
)
_MARKDOWN_ESCAPE = re.compile(r"\\([\\`*{}\[\]()#+\-.!_>~|])")
_VISUAL_BLOCK_TYPES = frozenset({"figure", "image", "picture", "chart", "diagram"})
TEMPLATE_STRUCTURE_VERSION = "template-structure-v1"


@dataclass(frozen=True, slots=True)
class ContentIdentityProjection:
    canonical_payload: str
    linear_text: str
    projection_source: str
    table_count: int
    fallback_used: bool
    identity_trusted: bool
    unrepresented_visual_count: int


def project_document_identity(parsed: ParsedDocument) -> ContentIdentityProjection:
    """Project parser-specific output into a versioned semantic sequence."""
    sequence: list[dict[str, object]] = []
    linear_parts: list[str] = []
    table_by_id = {table.table_id: table for table in parsed.tables}
    represented_tables: set[str] = set()
    sources: set[str] = set()
    fallback_used = False
    unrepresented_visual_count = len(parsed.images_metadata)
    identity_trusted = not parsed.ocr_used

    def append_text(raw_text: str) -> None:
        nonlocal unrepresented_visual_count
        visible_text = raw_text
        if parsed.parser_name == "markdown":
            visible_text, markdown_visuals = _markdown_visible_text(visible_text)
            unrepresented_visual_count += markdown_visuals
        value = strict_normalize_text(visible_text)
        if not value:
            return
        if sequence and sequence[-1]["kind"] == "text":
            previous = str(sequence[-1]["value"])
            sequence[-1]["value"] = f"{previous} {value}"
        else:
            sequence.append({"kind": "text", "value": value})
        linear_parts.append(value)

    def append_table(table: ParsedTable) -> None:
        rows = _canonical_table_rows(table.rows)
        if not rows:
            return
        sequence.append({"kind": "table", "rows": rows})
        represented_tables.add(table.table_id)
        linear_parts.extend(cell for row in rows for cell in row if cell)

    for page in parsed.pages:
        elements = list(page.elements)
        if not elements:
            fallback_used = True
            sources.add("page_text")
            append_text(page.text)
            continue
        sources.add("elements")
        for element in elements:
            block_type = element.block_type.casefold().strip()
            if block_type == "table":
                table = table_by_id.get(element.element_id)
                if table is None:
                    # Preserve the text but do not auto-merge when cell boundaries
                    # cannot be proven from the parser contract.
                    fallback_used = True
                    identity_trusted = False
                    sequence.append(
                        {
                            "kind": "unstructured_table",
                            "value": strict_normalize_text(element.text),
                        }
                    )
                    linear_parts.append(strict_normalize_text(element.text))
                else:
                    append_table(table)
                continue
            if block_type in _VISUAL_BLOCK_TYPES:
                unrepresented_visual_count += 1
            append_text(element.text)

    if not sequence:
        fallback_used = True
        sources.add("document_text")
        if parsed.tables and not parsed.text.strip():
            for table in parsed.tables:
                append_table(table)
        else:
            append_text(parsed.text)

    missing_tables = [table for table in parsed.tables if table.table_id not in represented_tables]
    if missing_tables:
        # Their location relative to prose is unknown, so retain them for a stable
        # candidate signature but prohibit authoritative automatic aliasing.
        identity_trusted = False
        fallback_used = True
        for table in missing_tables:
            append_table(table)

    if parsed.confidence is not None and parsed.confidence < 0.9:
        identity_trusted = False
    if any("replacement" in warning.casefold() for warning in parsed.warnings):
        identity_trusted = False
    if unrepresented_visual_count:
        identity_trusted = False

    profile = DOCUMENT_NORMALIZATION_VERSION
    canonical_payload = json.dumps(
        {"profile": profile, "sequence": sequence},
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    projection_source = "+".join(sorted(sources)) or "document_text"
    return ContentIdentityProjection(
        canonical_payload=canonical_payload,
        linear_text=strict_normalize_text(" ".join(linear_parts)),
        projection_source=projection_source,
        table_count=sum(item["kind"] == "table" for item in sequence),
        fallback_used=fallback_used,
        identity_trusted=identity_trusted,
        unrepresented_visual_count=unrepresented_visual_count,
    )


def build_parsed_document_fingerprint(parsed: ParsedDocument) -> DocumentFingerprint:
    projection = project_document_identity(parsed)
    template_signature = build_template_structure_signature(parsed)
    return build_document_fingerprint(
        projection.linear_text,
        identity_payload=projection.canonical_payload,
        normalization_version=DOCUMENT_NORMALIZATION_VERSION,
        identity_trusted=projection.identity_trusted,
        projection_source=projection.projection_source,
        table_count=projection.table_count,
        fallback_used=projection.fallback_used,
        unrepresented_visual_count=projection.unrepresented_visual_count,
        template_structure_signature=template_signature,
        template_structure_version=TEMPLATE_STRUCTURE_VERSION,
    )


def build_template_structure_signature(parsed: ParsedDocument) -> str:
    """Fingerprint document shape for routing only, never identity suppression.

    The projection intentionally excludes table values and body text.  It
    preserves ordered section labels, block kinds and normalized table column
    labels, so value-only revisions remain in the same structural family.
    """

    sections = [
        {
            "level": section.level,
            "title": _mask_template_value(strict_normalize_text(section.title or "")),
        }
        for section in parsed.sections
    ]
    block_types = [
        element.block_type.casefold().strip()
        for page in parsed.pages
        for element in page.elements
        if element.block_type.strip()
    ]
    table_schemas: list[list[str]] = []
    for table in parsed.tables:
        header = list(table.header)
        if not header and table.rows:
            header = list(table.rows[0])
        table_schemas.append(
            [_mask_template_value(strict_normalize_text(str(value))) for value in header]
        )
    payload = json.dumps(
        {
            "version": TEMPLATE_STRUCTURE_VERSION,
            "sections": sections,
            "block_types": block_types,
            "table_schemas": table_schemas,
        },
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    return sha256(payload.encode("utf-8")).hexdigest()


def _mask_template_value(value: str) -> str:
    masked = re.sub(r"\b\d{1,2}[/-]\d{1,2}(?:[/-]\d{2,4})?\b", "<date>", value)
    masked = re.sub(
        r"\b\d+(?:[.,]\d+)?\s*(?:tỷ|ty|triệu|trieu|million|billion|vnd|usd)\b",
        "<money>",
        masked,
        flags=re.IGNORECASE,
    )
    masked = re.sub(r"\b\d+(?:[.,]\d+)?\s*(?:m2|m²|sqm)\b", "<area>", masked)
    return masked.casefold()


def _canonical_table_rows(rows: list[list[str]]) -> list[list[str]]:
    normalized = [[strict_normalize_text(str(cell)) for cell in row] for row in rows]
    while normalized and not any(normalized[0]):
        normalized.pop(0)
    while normalized and not any(normalized[-1]):
        normalized.pop()
    if not normalized:
        return []
    last_content_column = max(
        (index for row in normalized for index, value in enumerate(row) if value),
        default=-1,
    )
    if last_content_column < 0:
        return []
    width = last_content_column + 1
    return [row[:width] + [""] * max(0, width - len(row)) for row in normalized]


def _markdown_visible_text(text: str) -> tuple[str, int]:
    visual_count = len(_MARKDOWN_IMAGE.findall(text))
    visible = _MARKDOWN_IMAGE.sub(r"\1", text)
    visible = _MARKDOWN_LINK.sub(r"\1", visible)
    visible = _MARKDOWN_CODE.sub(r"\1", visible)
    for _ in range(2):
        visible = _MARKDOWN_STRONG.sub(r"\2", visible)
        visible = _MARKDOWN_EMPHASIS.sub(r"\2", visible)
    visible = _MARKDOWN_LIST_MARKER.sub("", visible)
    visible = _MARKDOWN_ESCAPE.sub(r"\1", visible)
    return visible, visual_count


__all__ = [
    "ContentIdentityProjection",
    "TEMPLATE_STRUCTURE_VERSION",
    "build_parsed_document_fingerprint",
    "build_template_structure_signature",
    "project_document_identity",
]
