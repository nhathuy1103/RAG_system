from __future__ import annotations

import importlib.util
import re
import statistics
from collections import Counter
from dataclasses import dataclass
from typing import Any

from app.pipeline.documents.domain.models import BoundingBox
from app.pipeline.documents.domain.parsed import (
    ParsedElement,
    ParsedImageMetadata,
    ParsedPage,
    ParsedSection,
    ParsedTable,
)
from app.pipeline.shared.table_text import render_markdown_table_text, render_table_text
from app.pipeline.shared.text_utils import normalize_text

NATIVE_PDF_EXTRACTION_VERSION = "native-pdf-structure-v1"

_PAGE_NUMBER_RE = re.compile(r"^\s*(?:page|trang)?\s*-?\s*\d{1,4}\s*-?\s*$", re.IGNORECASE)
_LIST_RE = re.compile(r"^\s*(?:[-*+]\s+|\(?[0-9ivxlcdmIVXLCDM]+[.)]\s+|[a-zA-Z][.)]\s+)")
_CAPTION_RE = re.compile(r"^\s*(?:table|figure|fig\.|bang|bảng|hinh|hình)\b", re.IGNORECASE)
_NUMERIC_RE = re.compile(r"^\(?-?(?:\d{1,3}(?:[.,]\d{3})+|\d+)(?:[.,]\d+)?%?\)?$")


@dataclass(frozen=True)
class NativePdfExtraction:
    text: str
    pages: list[ParsedPage]
    sections: list[ParsedSection]
    tables: list[ParsedTable]
    images_metadata: list[ParsedImageMetadata]
    warnings: list[str]
    metadata: dict[str, object]


@dataclass(frozen=True)
class _Line:
    text: str
    page_number: int
    bbox: BoundingBox
    font_size: float
    max_font_size: float
    font_family: str
    bold: bool
    italic: bool
    block_index: int
    line_index: int
    span_count: int

    @property
    def y_mid(self) -> float:
        return (self.bbox.y0 + self.bbox.y1) / 2.0


@dataclass(frozen=True)
class _Cell:
    text: str
    bbox: BoundingBox


@dataclass(frozen=True)
class _TableCandidate:
    rows: list[list[str]]
    cells: list[dict[str, object]]
    bbox: BoundingBox
    confidence: float
    detection_method: str
    table_type_hint: str


@dataclass(frozen=True)
class _PageScratch:
    page_number: int
    width: float
    height: float
    rotation: int
    lines: list[_Line]
    tables: list[_TableCandidate]
    fallback_text: str
    image_count: int


@dataclass(frozen=True)
class _Block:
    block_id: str
    block_type: str
    text: str
    bbox: BoundingBox
    confidence: float
    metadata: dict[str, object]
    provenance: dict[str, object]
    table: ParsedTable | None = None


def extract_native_pdf_structure(
    content: bytes,
    *,
    fallback_page_texts: dict[int, str] | None = None,
) -> NativePdfExtraction | None:
    """Extract native PDF structure with PyMuPDF when it is installed.

    The result intentionally keeps pypdf text as the plain-text source when the
    caller supplies it. Geometry-rich elements and tables are added as parallel
    structure, so downstream phases can improve without losing the old text
    path immediately.
    """

    if importlib.util.find_spec("fitz") is None:
        return None

    try:
        import fitz  # type: ignore[import-not-found]
    except Exception:
        return None

    try:
        document = fitz.open(stream=content, filetype="pdf")
    except Exception:
        return None

    try:
        if getattr(document, "needs_pass", False) and not document.authenticate(""):
            return None
        fallback_page_texts = dict(fallback_page_texts or {})
        scratches = _extract_page_scratches(document, fallback_page_texts=fallback_page_texts)
        if not scratches:
            return None
        repeated_margin_keys = _repeated_margin_keys(scratches)
        body_font_size = _body_font_size(scratches)
        parsed_pages: list[ParsedPage] = []
        parsed_tables: list[ParsedTable] = []
        all_blocks_by_page: list[list[_Block]] = []
        heading_count = 0

        for scratch in scratches:
            blocks = _build_blocks(
                scratch,
                repeated_margin_keys=repeated_margin_keys,
                body_font_size=body_font_size,
            )
            heading_count += sum(1 for block in blocks if block.block_type == "heading")
            page_tables = [block.table for block in blocks if block.table is not None]
            parsed_tables.extend(table for table in page_tables if table is not None)
            elements = [
                ParsedElement(
                    element_id=block.block_id,
                    block_type=block.block_type,
                    text=block.text,
                    page_number=scratch.page_number,
                    metadata=block.metadata,
                    bbox=block.bbox,
                    confidence=block.confidence,
                    rotation=scratch.rotation,
                    provenance=block.provenance,
                )
                for block in blocks
            ]
            page_text = normalize_text(
                scratch.fallback_text or "\n".join(line.text for line in scratch.lines)
            )
            parsed_pages.append(
                ParsedPage(
                    page_number=scratch.page_number,
                    text=page_text,
                    elements=elements,
                    metadata={
                        "width": scratch.width,
                        "height": scratch.height,
                        "rotation": scratch.rotation,
                        "native_pdf_line_count": len(scratch.lines),
                        "native_pdf_table_count": len(page_tables),
                        "native_pdf_image_count": scratch.image_count,
                    },
                    width=scratch.width,
                    height=scratch.height,
                    rotation=scratch.rotation,
                )
            )
            all_blocks_by_page.append(blocks)

        sections = _sections_from_blocks(parsed_pages, all_blocks_by_page)
        text = normalize_text("\n\n".join(page.text for page in parsed_pages if page.text))
        table_candidate_count = sum(len(scratch.tables) for scratch in scratches)
        line_count = sum(len(scratch.lines) for scratch in scratches)
        element_count = sum(len(page.elements) for page in parsed_pages)
        warnings: list[str] = []
        if table_candidate_count and len(parsed_tables) < table_candidate_count:
            warnings.append("native_pdf_table_candidate_not_materialized")
        images_metadata = [
            ParsedImageMetadata(
                location=f"page:{scratch.page_number}:image:{image_index}",
                name=f"page-{scratch.page_number}-image-{image_index}",
            )
            for scratch in scratches
            for image_index in range(1, scratch.image_count + 1)
        ]
        return NativePdfExtraction(
            text=text,
            pages=parsed_pages,
            sections=sections,
            tables=parsed_tables,
            images_metadata=images_metadata,
            warnings=warnings,
            metadata={
                "native_pdf_extraction": {
                    "provider": "pymupdf",
                    "version": NATIVE_PDF_EXTRACTION_VERSION,
                    "mode": "structured_native",
                    "text_source": "pypdf_compat" if fallback_page_texts else "pymupdf_lines",
                    "page_count": len(parsed_pages),
                    "line_count": line_count,
                    "element_count": element_count,
                    "heading_count": heading_count,
                    "table_candidate_count": table_candidate_count,
                    "table_count": len(parsed_tables),
                    "image_count": len(images_metadata),
                    "body_font_size": round(body_font_size, 3) if body_font_size else None,
                    "header_footer_repeated_key_count": len(repeated_margin_keys),
                    "model_fallback_status": "not_configured",
                }
            },
        )
    finally:
        document.close()


def _extract_page_scratches(
    document: Any,
    *,
    fallback_page_texts: dict[int, str],
) -> list[_PageScratch]:
    scratches: list[_PageScratch] = []
    for page_index in range(len(document)):
        page = document.load_page(page_index)
        page_number = page_index + 1
        rect = page.rect
        width = float(rect.width)
        height = float(rect.height)
        rotation = int(getattr(page, "rotation", 0) or 0)
        lines = _extract_lines(page, page_number=page_number, width=width, height=height)
        tables = _deduplicate_tables(
            [
                *_extract_pymupdf_tables(page, page_number=page_number, width=width, height=height),
                *_detect_borderless_tables(
                    page, page_number=page_number, width=width, height=height
                ),
            ]
        )
        scratches.append(
            _PageScratch(
                page_number=page_number,
                width=width,
                height=height,
                rotation=rotation,
                lines=lines,
                tables=tables,
                fallback_text=normalize_text(fallback_page_texts.get(page_number, "")),
                image_count=_image_count(page),
            )
        )
    return scratches


def _extract_lines(page: Any, *, page_number: int, width: float, height: float) -> list[_Line]:
    try:
        payload = page.get_text("dict", sort=True)
    except Exception:
        return []
    lines: list[_Line] = []
    for block_index, block in enumerate(payload.get("blocks") or (), start=1):
        if int(block.get("type", 0) or 0) != 0:
            continue
        for line_index, line in enumerate(block.get("lines") or (), start=1):
            spans = list(line.get("spans") or ())
            text = normalize_text("".join(str(span.get("text") or "") for span in spans))
            if not text:
                continue
            bbox = _bbox_from_any(line.get("bbox"), width=width, height=height)
            if bbox is None:
                bbox = _union_bboxes(
                    [
                        span_bbox
                        for span in spans
                        if (
                            span_bbox := _bbox_from_any(
                                span.get("bbox"), width=width, height=height
                            )
                        )
                        is not None
                    ]
                )
            if bbox is None:
                continue
            sizes = [_positive_float(span.get("size")) for span in spans]
            sizes = [value for value in sizes if value is not None]
            flags = [int(span.get("flags") or 0) for span in spans]
            lines.append(
                _Line(
                    text=text,
                    page_number=page_number,
                    bbox=bbox,
                    font_size=statistics.median(sizes) if sizes else 0.0,
                    max_font_size=max(sizes) if sizes else 0.0,
                    font_family=str(spans[0].get("font") or "") if spans else "",
                    bold=any(flag & 16 for flag in flags),
                    italic=any(flag & 2 for flag in flags),
                    block_index=block_index,
                    line_index=line_index,
                    span_count=len(spans),
                )
            )
    return sorted(lines, key=lambda item: (item.bbox.y0, item.bbox.x0, item.block_index))


def _extract_pymupdf_tables(
    page: Any,
    *,
    page_number: int,
    width: float,
    height: float,
) -> list[_TableCandidate]:
    find_tables = getattr(page, "find_tables", None)
    if not callable(find_tables):
        return []
    try:
        finder = find_tables()
    except Exception:
        return []
    values: list[_TableCandidate] = []
    for table in list(getattr(finder, "tables", []) or []):
        rows = _clean_rows(_safe_extract_table_rows(table))
        if not _valid_table_rows(rows):
            continue
        bbox = _bbox_from_any(getattr(table, "bbox", None), width=width, height=height)
        if bbox is None:
            bbox = _bbox_from_table_cells(table, width=width, height=height)
        if bbox is None:
            continue
        cells = _cells_from_native_table(table, rows=rows, table_bbox=bbox)
        values.append(
            _TableCandidate(
                rows=rows,
                cells=cells,
                bbox=bbox,
                confidence=0.92,
                detection_method="pymupdf_find_tables",
                table_type_hint="BORDERED_TABLE",
            )
        )
    return values


def _detect_borderless_tables(
    page: Any,
    *,
    page_number: int,
    width: float,
    height: float,
) -> list[_TableCandidate]:
    try:
        raw_words = page.get_text("words", sort=True)
    except Exception:
        return []
    words = [
        _Cell(
            text=normalize_text(str(item[4] or "")),
            bbox=_bounded_bbox(
                float(item[0]), float(item[1]), float(item[2]), float(item[3]), width, height
            ),
        )
        for item in raw_words
        if len(item) >= 5 and normalize_text(str(item[4] or ""))
    ]
    if not words:
        return []
    rows = _group_words_into_rows(words)
    split_rows = [_split_word_row(row) for row in rows]
    candidate_flags = [
        len(row) >= 2 and _row_has_table_spacing(row) and _row_cells_are_compact(row)
        for row in split_rows
    ]
    groups: list[list[list[_Cell]]] = []
    current: list[list[_Cell]] = []
    for row, is_candidate in zip(split_rows, candidate_flags, strict=False):
        if is_candidate:
            current.append(row)
            continue
        if current:
            groups.append(current)
            current = []
    if current:
        groups.append(current)

    tables: list[_TableCandidate] = []
    for group in groups:
        if len(group) < 2:
            continue
        column_count = _stable_column_count(group)
        if column_count < 2:
            continue
        rows_text = [
            _normalize_table_row([cell.text for cell in row], column_count) for row in group
        ]
        if not _valid_borderless_group(rows_text):
            continue
        table_bbox = _union_bboxes([cell.bbox for row in group for cell in row])
        if table_bbox is None:
            continue
        cells = []
        grid = _even_grid(table_bbox, row_count=len(rows_text), column_count=column_count)
        for row_index, row in enumerate(rows_text):
            source_cells = group[row_index]
            for column_index, text in enumerate(row):
                cell_bbox = (
                    source_cells[column_index].bbox
                    if column_index < len(source_cells)
                    else grid[row_index][column_index]
                )
                cells.append(
                    _cell_mapping(row_index, column_index, text, cell_bbox, confidence=0.78)
                )
        tables.append(
            _TableCandidate(
                rows=rows_text,
                cells=cells,
                bbox=table_bbox,
                confidence=0.78,
                detection_method="borderless_word_alignment",
                table_type_hint="BORDERLESS_TABLE",
            )
        )
    return tables


def _build_blocks(
    scratch: _PageScratch,
    *,
    repeated_margin_keys: set[str],
    body_font_size: float,
) -> list[_Block]:
    table_bboxes = [table.bbox for table in scratch.tables]
    line_blocks: list[_Block] = []
    line_index = 0
    paragraph_buffer: list[_Line] = []

    def flush_paragraph() -> None:
        nonlocal line_index
        if not paragraph_buffer:
            return
        line_index += 1
        bbox = _union_bboxes([line.bbox for line in paragraph_buffer])
        text = normalize_text(" ".join(line.text for line in paragraph_buffer))
        if bbox is not None and text:
            line_blocks.append(
                _Block(
                    block_id=f"pdf-page-{scratch.page_number}-paragraph-{line_index}",
                    block_type="paragraph",
                    text=text,
                    bbox=bbox,
                    confidence=0.86,
                    metadata={
                        "native_pdf_extraction": NATIVE_PDF_EXTRACTION_VERSION,
                        "line_count": len(paragraph_buffer),
                        "font_size": _rounded_median(line.font_size for line in paragraph_buffer),
                        "source_line_ids": [
                            f"block-{line.block_index}-line-{line.line_index}"
                            for line in paragraph_buffer
                        ],
                    },
                    provenance={"source": "native_pdf_line_group", "provider": "pymupdf"},
                )
            )
        paragraph_buffer.clear()

    for line in scratch.lines:
        if any(_bbox_contains(table_bbox, line.bbox, tolerance=2.0) for table_bbox in table_bboxes):
            continue
        block_type, confidence, level = _classify_line(
            line,
            page_width=scratch.width,
            page_height=scratch.height,
            body_font_size=body_font_size,
            repeated_margin_keys=repeated_margin_keys,
        )
        if block_type == "paragraph":
            paragraph_buffer.append(line)
            continue
        flush_paragraph()
        line_index += 1
        metadata: dict[str, object] = {
            "native_pdf_extraction": NATIVE_PDF_EXTRACTION_VERSION,
            "font_family": line.font_family,
            "font_size": round(line.font_size, 3) if line.font_size else None,
            "max_font_size": round(line.max_font_size, 3) if line.max_font_size else None,
            "bold": line.bold,
            "italic": line.italic,
            "span_count": line.span_count,
        }
        if level is not None:
            metadata["heading_level"] = level
        line_blocks.append(
            _Block(
                block_id=f"pdf-page-{scratch.page_number}-{block_type}-{line_index}",
                block_type=block_type,
                text=line.text,
                bbox=line.bbox,
                confidence=confidence,
                metadata=metadata,
                provenance={
                    "source": "native_pdf_line",
                    "provider": "pymupdf",
                    "block_index": line.block_index,
                    "line_index": line.line_index,
                },
            )
        )
    flush_paragraph()

    table_blocks = [
        _table_block(scratch.page_number, table_index, table)
        for table_index, table in enumerate(scratch.tables, start=1)
    ]
    return sorted(
        [*line_blocks, *table_blocks], key=lambda item: (item.bbox.y0, item.bbox.x0, item.block_id)
    )


def _table_block(page_number: int, table_index: int, candidate: _TableCandidate) -> _Block:
    table_id = f"pdf-page-{page_number}-table-{table_index}"
    table = ParsedTable(
        table_id=table_id,
        location=f"page:{page_number}:table:{table_index}",
        rows=candidate.rows,
        columns=max((len(row) for row in candidate.rows), default=0),
        header=candidate.rows[0] if candidate.rows else [],
        cells=candidate.cells,
        bbox=candidate.bbox,
        confidence=candidate.confidence,
        metadata={
            "native_pdf_extraction": NATIVE_PDF_EXTRACTION_VERSION,
            "detection_method": candidate.detection_method,
            "table_type_hint": candidate.table_type_hint,
        },
    )
    return _Block(
        block_id=table_id,
        block_type="table",
        text=render_table_text(candidate.rows),
        bbox=candidate.bbox,
        confidence=candidate.confidence,
        metadata={
            "location": table.location,
            "columns": table.columns,
            "header": list(table.header),
            "canonical_text": render_table_text(candidate.rows),
            "markdown_text": render_markdown_table_text(candidate.rows),
            "cells": [dict(cell) for cell in candidate.cells],
            "native_pdf_extraction": NATIVE_PDF_EXTRACTION_VERSION,
            "detection_method": candidate.detection_method,
            "table_type_hint": candidate.table_type_hint,
        },
        provenance={"source": "native_pdf_table", "provider": "pymupdf"},
        table=table,
    )


def _sections_from_blocks(
    pages: list[ParsedPage],
    blocks_by_page: list[list[_Block]],
) -> list[ParsedSection]:
    sections: list[ParsedSection] = []
    for page, blocks in zip(pages, blocks_by_page, strict=False):
        current_title = f"Page {page.page_number}"
        current_level = 1
        current_text: list[str] = []
        current_ids: list[str] = []
        saw_heading = False

        for block in blocks:
            if block.block_type == "heading":
                _append_section(
                    sections,
                    text_parts=current_text,
                    page_number=page.page_number,
                    title=current_title,
                    level=current_level,
                    block_ids=current_ids,
                )
                current_text = [block.text]
                current_ids = [block.block_id]
                current_title = block.text
                current_level = int(block.metadata.get("heading_level") or 1)
                saw_heading = True
                continue
            current_text.append(block.text)
            current_ids.append(block.block_id)
        _append_section(
            sections,
            text_parts=current_text,
            page_number=page.page_number,
            title=current_title,
            level=current_level,
            block_ids=current_ids,
        )
        if not saw_heading and not any(
            section.page_number == page.page_number for section in sections
        ):
            sections.append(
                ParsedSection(
                    text=page.text,
                    page_number=page.page_number,
                    title=f"Page {page.page_number}",
                    block_ids=[block.block_id for block in blocks],
                )
            )
    return sections


def _append_section(
    sections: list[ParsedSection],
    *,
    text_parts: list[str],
    page_number: int,
    title: str,
    level: int,
    block_ids: list[str],
) -> None:
    if not block_ids:
        return
    sections.append(
        ParsedSection(
            text=normalize_text("\n\n".join(text_parts)),
            page_number=page_number,
            title=title,
            level=level,
            block_ids=list(block_ids),
        )
    )


def _classify_line(
    line: _Line,
    *,
    page_width: float,
    page_height: float,
    body_font_size: float,
    repeated_margin_keys: set[str],
) -> tuple[str, float, int | None]:
    key = _recurrence_key(line.text)
    top = line.bbox.y0 <= page_height * 0.10
    bottom = line.bbox.y1 >= page_height * 0.90
    if _PAGE_NUMBER_RE.match(line.text) and (top or bottom):
        return "page_number", 0.88, None
    if key in repeated_margin_keys and top:
        return "header", 0.84, None
    if key in repeated_margin_keys and bottom:
        return "footer", 0.84, None
    if _CAPTION_RE.match(line.text):
        return "caption", 0.78, None
    if _LIST_RE.match(line.text):
        return "list", 0.82, None

    heading_level = _heading_level(
        line,
        page_width=page_width,
        page_height=page_height,
        body_font_size=body_font_size,
    )
    if heading_level is not None:
        return "heading", 0.9 if heading_level == 1 else 0.86, heading_level
    return "paragraph", 0.84, None


def _heading_level(
    line: _Line,
    *,
    page_width: float,
    page_height: float,
    body_font_size: float,
) -> int | None:
    text = line.text.strip()
    if not text or len(text) > 180:
        return None
    words = text.split()
    if len(words) > 20:
        return None
    font_ratio = (line.max_font_size or line.font_size or body_font_size) / max(body_font_size, 1.0)
    centered = abs(((line.bbox.x0 + line.bbox.x1) / 2.0) - (page_width / 2.0)) <= page_width * 0.12
    near_top = line.bbox.y0 <= page_height * 0.28
    punctuated_sentence = text.endswith((".", ",", ";")) and len(words) > 5
    uppercaseish = _uppercaseish_ratio(words) >= 0.55
    if punctuated_sentence and font_ratio < 1.35:
        return None
    if font_ratio >= 1.45 or (near_top and centered and font_ratio >= 1.18):
        return 1
    if font_ratio >= 1.25 or (line.bold and font_ratio >= 1.08):
        return 2
    if line.bold and uppercaseish and len(words) <= 12:
        return 3
    return None


def _repeated_margin_keys(scratches: list[_PageScratch]) -> set[str]:
    if len(scratches) < 2:
        return set()
    counts: Counter[str] = Counter()
    for scratch in scratches:
        seen_on_page: set[str] = set()
        for line in scratch.lines:
            if not (line.bbox.y0 <= scratch.height * 0.12 or line.bbox.y1 >= scratch.height * 0.88):
                continue
            key = _recurrence_key(line.text)
            if key:
                seen_on_page.add(key)
        counts.update(seen_on_page)
    threshold = max(2, round(len(scratches) * 0.5))
    return {key for key, count in counts.items() if count >= threshold}


def _body_font_size(scratches: list[_PageScratch]) -> float:
    sizes = [
        line.font_size
        for scratch in scratches
        for line in scratch.lines
        if line.font_size > 0 and len(line.text.strip()) > 3
    ]
    if not sizes:
        return 12.0
    return float(statistics.median(sizes))


def _safe_extract_table_rows(table: Any) -> list[list[str]]:
    try:
        extracted = table.extract()
    except Exception:
        extracted = []
    rows: list[list[str]] = []
    for row in extracted or []:
        if row is None:
            continue
        rows.append([normalize_text(str(cell or "")) for cell in row])
    return rows


def _clean_rows(rows: list[list[str]]) -> list[list[str]]:
    cleaned = [[normalize_text(str(cell or "")) for cell in row] for row in rows]
    while cleaned and not any(cleaned[0]):
        cleaned.pop(0)
    while cleaned and not any(cleaned[-1]):
        cleaned.pop()
    width = max((len(row) for row in cleaned), default=0)
    return [row + [""] * (width - len(row)) for row in cleaned]


def _valid_table_rows(rows: list[list[str]]) -> bool:
    if len(rows) < 2:
        return False
    width = max((len(row) for row in rows), default=0)
    if width < 2:
        return False
    nonempty = sum(1 for row in rows for cell in row if cell.strip())
    return nonempty >= max(2, len(rows))


def _cells_from_native_table(
    table: Any,
    *,
    rows: list[list[str]],
    table_bbox: BoundingBox,
) -> list[dict[str, object]]:
    row_count = len(rows)
    column_count = max((len(row) for row in rows), default=0)
    raw_cells = list(getattr(table, "cells", []) or [])
    grid = _even_grid(table_bbox, row_count=row_count, column_count=column_count)
    cells: list[dict[str, object]] = []
    for row_index, row in enumerate(rows):
        for column_index in range(column_count):
            raw_index = row_index * column_count + column_index
            bbox = (
                _bbox_from_any(raw_cells[raw_index], width=table_bbox.x1, height=table_bbox.y1)
                if raw_index < len(raw_cells)
                else None
            )
            cells.append(
                _cell_mapping(
                    row_index,
                    column_index,
                    row[column_index] if column_index < len(row) else "",
                    bbox or grid[row_index][column_index],
                    confidence=0.9 if bbox is not None else 0.76,
                )
            )
    return cells


def _bbox_from_table_cells(table: Any, *, width: float, height: float) -> BoundingBox | None:
    boxes = [
        bbox
        for raw in list(getattr(table, "cells", []) or [])
        if (bbox := _bbox_from_any(raw, width=width, height=height)) is not None
    ]
    return _union_bboxes(boxes)


def _group_words_into_rows(words: list[_Cell]) -> list[list[_Cell]]:
    sorted_words = sorted(words, key=lambda item: (item.bbox.y0, item.bbox.x0))
    heights = [word.bbox.height for word in sorted_words if word.bbox.height > 0]
    tolerance = max(3.0, (statistics.median(heights) if heights else 10.0) * 0.45)
    rows: list[list[_Cell]] = []
    for word in sorted_words:
        center = (word.bbox.y0 + word.bbox.y1) / 2.0
        placed = False
        for row in rows:
            row_center = statistics.median((item.bbox.y0 + item.bbox.y1) / 2.0 for item in row)
            if abs(center - row_center) <= tolerance:
                row.append(word)
                placed = True
                break
        if not placed:
            rows.append([word])
    return [sorted(row, key=lambda item: item.bbox.x0) for row in rows]


def _split_word_row(words: list[_Cell]) -> list[_Cell]:
    if not words:
        return []
    heights = [word.bbox.height for word in words if word.bbox.height > 0]
    gap_threshold = max(18.0, (statistics.median(heights) if heights else 10.0) * 1.8)
    cells: list[list[_Cell]] = [[words[0]]]
    for word in words[1:]:
        previous = cells[-1][-1]
        if word.bbox.x0 - previous.bbox.x1 >= gap_threshold:
            cells.append([word])
        else:
            cells[-1].append(word)
    return [
        _Cell(
            text=normalize_text(" ".join(word.text for word in cell_words)),
            bbox=_union_bboxes([word.bbox for word in cell_words]) or cell_words[0].bbox,
        )
        for cell_words in cells
        if normalize_text(" ".join(word.text for word in cell_words))
    ]


def _row_has_table_spacing(row: list[_Cell]) -> bool:
    if len(row) < 2:
        return False
    gaps = [right.bbox.x0 - left.bbox.x1 for left, right in zip(row, row[1:], strict=False)]
    return max(gaps, default=0.0) >= 18.0


def _row_cells_are_compact(row: list[_Cell]) -> bool:
    values = [cell.text for cell in row if cell.text]
    if not values:
        return False
    return statistics.mean(len(value) for value in values) <= 48


def _stable_column_count(group: list[list[_Cell]]) -> int:
    counts = [len(row) for row in group if len(row) >= 2]
    if not counts:
        return 0
    return Counter(counts).most_common(1)[0][0]


def _normalize_table_row(values: list[str], column_count: int) -> list[str]:
    row = [normalize_text(value) for value in values]
    if len(row) <= column_count:
        return row + [""] * (column_count - len(row))
    return [*row[: column_count - 1], " ".join(row[column_count - 1 :])]


def _valid_borderless_group(rows: list[list[str]]) -> bool:
    if not _valid_table_rows(rows):
        return False
    values = [cell for row in rows for cell in row if cell]
    numeric_density = sum(1 for value in values if _NUMERIC_RE.match(value)) / max(len(values), 1)
    short_header = all(len(cell) <= 40 for cell in rows[0] if cell)
    return numeric_density >= 0.15 or (len(rows) >= 3 and short_header)


def _deduplicate_tables(tables: list[_TableCandidate]) -> list[_TableCandidate]:
    kept: list[_TableCandidate] = []
    for table in sorted(tables, key=lambda item: (-item.confidence, item.bbox.y0, item.bbox.x0)):
        if any(_bbox_iou(table.bbox, existing.bbox) >= 0.72 for existing in kept):
            continue
        kept.append(table)
    return sorted(kept, key=lambda item: (item.bbox.y0, item.bbox.x0))


def _even_grid(
    bbox: BoundingBox,
    *,
    row_count: int,
    column_count: int,
) -> list[list[BoundingBox]]:
    row_count = max(row_count, 1)
    column_count = max(column_count, 1)
    cell_width = bbox.width / column_count
    cell_height = bbox.height / row_count
    return [
        [
            BoundingBox.from_corners(
                bbox.x0 + column_index * cell_width,
                bbox.y0 + row_index * cell_height,
                bbox.x0 + (column_index + 1) * cell_width,
                bbox.y0 + (row_index + 1) * cell_height,
                unit=bbox.unit,
            )
            for column_index in range(column_count)
        ]
        for row_index in range(row_count)
    ]


def _cell_mapping(
    row_index: int,
    column_index: int,
    text: str,
    bbox: BoundingBox,
    *,
    confidence: float,
) -> dict[str, object]:
    return {
        "row_index": row_index,
        "column_index": column_index,
        "text": normalize_text(text),
        "bbox": _bbox_dict(bbox),
        "row_span": 1,
        "column_span": 1,
        "confidence": confidence,
        "source_element_ids": (),
    }


def _bbox_from_any(value: Any, *, width: float, height: float) -> BoundingBox | None:
    if value is None:
        return None
    try:
        if all(hasattr(value, key) for key in ("x0", "y0", "x1", "y1")):
            return _bounded_bbox(
                float(value.x0), float(value.y0), float(value.x1), float(value.y1), width, height
            )
        if isinstance(value, (list, tuple)) and len(value) >= 4:
            return _bounded_bbox(
                float(value[0]), float(value[1]), float(value[2]), float(value[3]), width, height
            )
    except (TypeError, ValueError):
        return None
    return None


def _bounded_bbox(
    x0: float,
    y0: float,
    x1: float,
    y1: float,
    width: float,
    height: float,
) -> BoundingBox:
    left = min(max(0.0, x0), max(width, 0.0))
    top = min(max(0.0, y0), max(height, 0.0))
    right = min(max(left, x1), max(width, left))
    bottom = min(max(top, y1), max(height, top))
    return BoundingBox.from_corners(left, top, right, bottom, unit="pt")


def _union_bboxes(boxes: list[BoundingBox]) -> BoundingBox | None:
    values = [box for box in boxes if box is not None]
    if not values:
        return None
    return BoundingBox.from_corners(
        min(box.x0 for box in values),
        min(box.y0 for box in values),
        max(box.x1 for box in values),
        max(box.y1 for box in values),
        unit=values[0].unit,
    )


def _bbox_contains(outer: BoundingBox, inner: BoundingBox, *, tolerance: float = 0.0) -> bool:
    return (
        inner.x0 >= outer.x0 - tolerance
        and inner.y0 >= outer.y0 - tolerance
        and inner.x1 <= outer.x1 + tolerance
        and inner.y1 <= outer.y1 + tolerance
    )


def _bbox_iou(left: BoundingBox, right: BoundingBox) -> float:
    intersection_x0 = max(left.x0, right.x0)
    intersection_y0 = max(left.y0, right.y0)
    intersection_x1 = min(left.x1, right.x1)
    intersection_y1 = min(left.y1, right.y1)
    intersection = max(0.0, intersection_x1 - intersection_x0) * max(
        0.0, intersection_y1 - intersection_y0
    )
    union = left.area + right.area - intersection
    return intersection / union if union > 0 else 0.0


def _bbox_dict(bbox: BoundingBox) -> dict[str, object]:
    return {
        "x0": bbox.x0,
        "y0": bbox.y0,
        "x1": bbox.x1,
        "y1": bbox.y1,
        "unit": bbox.unit,
    }


def _rounded_median(values: Any) -> float | None:
    filtered = [float(value) for value in values if value]
    if not filtered:
        return None
    return round(float(statistics.median(filtered)), 3)


def _positive_float(value: object) -> float | None:
    if isinstance(value, bool):
        return None
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return None
    return parsed if parsed > 0 else None


def _uppercaseish_ratio(words: list[str]) -> float:
    if not words:
        return 0.0
    upperish = sum(1 for word in words if word.isupper() or word[:1].isupper())
    return upperish / len(words)


def _recurrence_key(text: str) -> str:
    normalized = re.sub(r"\d+", "#", " ".join(text.casefold().split()))
    return normalized if len(normalized) >= 4 else ""


def _image_count(page: Any) -> int:
    try:
        return len(page.get_images(full=True))
    except Exception:
        return 0


__all__ = [
    "NATIVE_PDF_EXTRACTION_VERSION",
    "NativePdfExtraction",
    "extract_native_pdf_structure",
]
