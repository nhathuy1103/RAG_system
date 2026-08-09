from __future__ import annotations

from collections.abc import Sequence
from typing import Any

from app.pipeline.shared.table_text import render_markdown_table_text
from app.pipeline.shared.text_utils import normalize_text

MARKDOWN_REPRESENTATION_VERSION = "markdown-v1"


def render_element_markdown(
    element: Any,
    *,
    heading_level: int | None = None,
    table_rows: Sequence[Sequence[object]] | None = None,
) -> str:
    """Render one parser element as a stable Markdown block."""
    text = normalize_text(str(getattr(element, "text", "") or ""))
    block_type = str(getattr(element, "block_type", "paragraph") or "paragraph")
    block_type = block_type.strip().lower().replace("-", "_").replace(" ", "_")
    metadata = dict(getattr(element, "metadata", {}) or {})

    if block_type == "table":
        rendered = str(metadata.get("markdown_text") or "").strip()
        if rendered:
            return normalize_text(rendered)
        if table_rows is not None:
            return normalize_text(render_markdown_table_text(table_rows))
        return text
    if block_type == "heading":
        level = max(1, min(6, int(heading_level or 1)))
        return f"{'#' * level} {text}" if text else ""
    if block_type == "list":
        return _render_list(text)
    if block_type == "code":
        if text.startswith("```") and text.endswith("```"):
            return text
        return f"```\n{text}\n```" if text else ""
    if block_type == "quote":
        return "\n".join(f"> {line}" for line in text.splitlines())
    if block_type == "horizontal_rule":
        return "---"
    if block_type in {"caption", "figure", "image"}:
        return f"*{text}*" if text else ""
    if block_type == "formula":
        return f"$$\n{text}\n$$" if text else ""
    return text


def render_parsed_document_markdown(document: Any) -> str:
    """Project a ParsedDocument-like object into format-neutral Markdown."""
    pages = list(getattr(document, "pages", []) or [])
    sections = list(getattr(document, "sections", []) or [])
    tables = list(getattr(document, "tables", []) or [])
    parser_name = str(getattr(document, "parser_name", "") or "").strip().lower()
    table_by_id = {
        str(getattr(table, "table_id", "")): table
        for table in tables
        if str(getattr(table, "table_id", ""))
    }
    heading_levels = _heading_levels_by_block_id(sections)
    rendered_table_ids: set[str] = set()
    blocks: list[str] = []

    for page in pages:
        page_number = _positive_int(getattr(page, "page_number", None))
        elements = list(getattr(page, "elements", []) or [])
        page_sections = [
            section
            for section in sections
            if _positive_int(getattr(section, "page_number", None)) == page_number
        ]
        has_heading = any(
            str(getattr(element, "block_type", "")).strip().lower() == "heading"
            for element in elements
        )
        synthetic_title = _synthetic_page_title(
            parser_name=parser_name,
            page_number=page_number,
            page_count=len(pages),
            sections=page_sections,
            has_heading=has_heading,
        )
        if synthetic_title:
            blocks.append(f"## {synthetic_title}")

        if elements:
            for element in elements:
                element_id = str(getattr(element, "element_id", "") or "")
                table = table_by_id.get(element_id)
                rendered = render_element_markdown(
                    element,
                    heading_level=heading_levels.get(element_id),
                    table_rows=getattr(table, "rows", None) if table is not None else None,
                )
                if rendered:
                    blocks.append(rendered)
                if table is not None:
                    rendered_table_ids.add(element_id)
            continue

        page_text = normalize_text(str(getattr(page, "text", "") or ""))
        if page_text:
            blocks.append(page_text)

    if not pages:
        for section in sections:
            title = normalize_text(str(getattr(section, "title", "") or ""))
            level = max(1, min(6, int(getattr(section, "level", 1) or 1)))
            if title and not _is_generic_title(title, parser_name):
                blocks.append(f"{'#' * level} {title}")
            section_text = normalize_text(str(getattr(section, "text", "") or ""))
            if section_text:
                blocks.append(section_text)

    for table_id, table in table_by_id.items():
        if table_id in rendered_table_ids:
            continue
        rendered = render_markdown_table_text(list(getattr(table, "rows", []) or []))
        if rendered:
            blocks.append(rendered)

    if not blocks:
        fallback = getattr(document, "content_markdown", None) or getattr(document, "text", "")
        return normalize_text(str(fallback or ""))
    return normalize_text("\n\n".join(blocks))


def _heading_levels_by_block_id(sections: Sequence[Any]) -> dict[str, int]:
    levels: dict[str, int] = {}
    for section in sections:
        level = max(1, min(6, int(getattr(section, "level", 1) or 1)))
        for block_id in list(getattr(section, "block_ids", []) or []):
            levels.setdefault(str(block_id), level)
    return levels


def _synthetic_page_title(
    *,
    parser_name: str,
    page_number: int | None,
    page_count: int,
    sections: Sequence[Any],
    has_heading: bool,
) -> str | None:
    if has_heading:
        return None
    title = next(
        (
            normalize_text(str(getattr(section, "title", "") or ""))
            for section in sections
            if normalize_text(str(getattr(section, "title", "") or ""))
        ),
        "",
    )
    if title and not _is_generic_title(title, parser_name):
        return title
    if page_number is not None and (page_count > 1 or parser_name == "pdf"):
        return f"Page {page_number}"
    return None


def _is_generic_title(title: str, parser_name: str) -> bool:
    normalized = title.casefold()
    return normalized in {
        "document",
        "text",
        "markdown",
        "html",
        "csv",
        parser_name.casefold(),
    }


def _render_list(text: str) -> str:
    rendered: list[str] = []
    for line in text.splitlines():
        value = line.strip()
        if not value:
            continue
        if value.startswith(("- ", "* ", "+ ")):
            rendered.append(value)
        else:
            rendered.append(f"- {value}")
    return "\n".join(rendered)


def _positive_int(value: object) -> int | None:
    if isinstance(value, bool):
        return None
    if not isinstance(value, int | float | str):
        return None
    try:
        parsed = int(value)
    except (OverflowError, ValueError):
        return None
    return parsed if parsed > 0 else None


__all__ = [
    "MARKDOWN_REPRESENTATION_VERSION",
    "render_element_markdown",
    "render_parsed_document_markdown",
]
