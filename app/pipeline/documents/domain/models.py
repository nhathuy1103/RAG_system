from __future__ import annotations

import re
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import StrEnum
from typing import Any
from uuid import uuid4

from app.pipeline.shared.markdown import render_element_markdown
from app.pipeline.shared.table_text import (
    render_markdown_table_text,
    render_table_text,
)


class Orientation(StrEnum):
    DEGREE_0 = "0"
    DEGREE_90 = "90"
    DEGREE_180 = "180"
    DEGREE_270 = "270"
    UNKNOWN = "unknown"

    @classmethod
    def from_rotation(cls, rotation: int | float | None) -> Orientation:
        normalized = int(rotation or 0) % 360
        mapping = {
            0: cls.DEGREE_0,
            90: cls.DEGREE_90,
            180: cls.DEGREE_180,
            270: cls.DEGREE_270,
        }
        return mapping.get(normalized, cls.UNKNOWN)


class BlockType:
    HEADING = "heading"
    PARAGRAPH = "paragraph"
    SENTENCE = "sentence"
    LIST = "list"
    TABLE = "table"
    IMAGE = "image"
    FIGURE = "figure"
    CAPTION = "caption"
    HEADER = "header"
    FOOTER = "footer"
    CODE = "code"
    QUOTE = "quote"
    FORMULA = "formula"
    PAGE_NUMBER = "page_number"
    HORIZONTAL_RULE = "horizontal_rule"
    UNKNOWN = "unknown"

    REQUIRED_TYPES = (
        HEADING,
        PARAGRAPH,
        SENTENCE,
        LIST,
        TABLE,
        IMAGE,
        FIGURE,
        CAPTION,
        HEADER,
        FOOTER,
        CODE,
        QUOTE,
        FORMULA,
        PAGE_NUMBER,
        HORIZONTAL_RULE,
        UNKNOWN,
    )

    @classmethod
    def normalize(cls, value: str | None) -> str:
        if not value:
            return cls.UNKNOWN
        normalized = value.strip().lower().replace(" ", "_").replace("-", "_")
        return normalized or cls.UNKNOWN


class DocumentType(StrEnum):
    ACADEMIC_PAPER = "academic_paper"
    STRUCTURED_DOCUMENT = "structured_document"
    FINANCIAL_REPORT = "financial_report"
    INVOICE = "invoice"
    CONTRACT = "contract"
    MANUAL = "manual"
    PRESENTATION = "presentation"
    SPREADSHEET = "spreadsheet"
    BOOK = "book"
    POLICY = "policy"
    UNKNOWN = "unknown"


class LayoutType(StrEnum):
    SINGLE_COLUMN = "single_column"
    MULTI_COLUMN = "multi_column"
    NESTED = "nested"
    LANDSCAPE = "landscape"
    PORTRAIT = "portrait"
    TABLE_REGION = "table_region"
    FIGURE_REGION = "figure_region"
    HEADER = "header"
    FOOTER = "footer"
    SIDEBAR = "sidebar"
    UNKNOWN = "unknown"


@dataclass(frozen=True, init=False)
class BoundingBox:
    """Canonical page-relative rectangle (x0, y0, x1, y1)."""

    x0: float
    y0: float
    x1: float
    y1: float
    unit: str

    def __init__(self, x: float, y: float, width: float, height: float, unit: str = "pt") -> None:
        self._set(float(x), float(y), float(x) + float(width), float(y) + float(height), unit)

    @classmethod
    def from_corners(
        cls,
        x0: float,
        y0: float,
        x1: float,
        y1: float,
        *,
        unit: str = "pt",
    ) -> BoundingBox:
        instance = object.__new__(cls)
        instance._set(float(x0), float(y0), float(x1), float(y1), unit)
        return instance

    def _set(self, x0: float, y0: float, x1: float, y1: float, unit: str) -> None:
        if not all(value == value and abs(value) != float("inf") for value in (x0, y0, x1, y1)):
            raise ValueError("Bounding-box coordinates must be finite.")
        if x0 < 0 or y0 < 0:
            raise ValueError("Bounding-box coordinates cannot be negative.")
        if x1 < x0 or y1 < y0:
            raise ValueError("Bounding-box end coordinates must not precede start coordinates.")
        normalized_unit = str(unit or "").strip().lower()
        if normalized_unit not in {"pt", "pixel", "normalized"}:
            raise ValueError(f"Unsupported bounding-box unit: {unit}")
        if normalized_unit == "normalized" and (x1 > 1 or y1 > 1):
            raise ValueError("Normalized bounding-box coordinates must be within [0, 1].")
        object.__setattr__(self, "x0", x0)
        object.__setattr__(self, "y0", y0)
        object.__setattr__(self, "x1", x1)
        object.__setattr__(self, "y1", y1)
        object.__setattr__(self, "unit", normalized_unit)

    @property
    def x(self) -> float:
        return self.x0

    @property
    def y(self) -> float:
        return self.y0

    @property
    def width(self) -> float:
        return self.x1 - self.x0

    @property
    def height(self) -> float:
        return self.y1 - self.y0

    @property
    def x2(self) -> float:
        return self.x1

    @property
    def y2(self) -> float:
        return self.y1

    @property
    def area(self) -> float:
        return self.width * self.height

    def normalized(self, *, page_width: float, page_height: float) -> BoundingBox:
        if page_width <= 0 or page_height <= 0:
            raise ValueError("Page dimensions must be positive.")
        return BoundingBox.from_corners(
            self.x0 / page_width,
            self.y0 / page_height,
            self.x1 / page_width,
            self.y1 / page_height,
            unit="normalized",
        )

    def intersection_over_union(self, other: BoundingBox) -> float:
        left = max(self.x0, other.x0)
        top = max(self.y0, other.y0)
        right = min(self.x1, other.x1)
        bottom = min(self.y1, other.y1)
        intersection = max(0.0, right - left) * max(0.0, bottom - top)
        union = self.area + other.area - intersection
        return intersection / union if union > 0 else 0.0


@dataclass
class TextStyle:
    font_family: str | None = None
    font_size: float | None = None
    bold: bool = False
    italic: bool = False
    underline: bool = False
    color: str | None = None
    extra: dict[str, Any] = field(default_factory=dict)


@dataclass
class ReadingOrder:
    reading_index: int
    previous_id: str | None = None
    next_id: str | None = None
    parent_id: str | None = None
    children_ids: list[str] = field(default_factory=list)


@dataclass
class DocumentBlock:
    id: str
    block_type: str
    text: str = ""
    page: int | None = None
    parent_id: str | None = None
    children: list[str] = field(default_factory=list)
    bbox: BoundingBox | None = None
    metadata: dict[str, Any] = field(default_factory=dict)
    confidence: float | None = None
    rotation: int = 0
    reading_order: ReadingOrder | None = None
    style: TextStyle | None = None

    def __post_init__(self) -> None:
        self.block_type = BlockType.normalize(self.block_type)


@dataclass(frozen=True)
class TableCell:
    row_index: int
    column_index: int
    text: str
    bbox: BoundingBox | None = None
    row_span: int = 1
    column_span: int = 1
    confidence: float | None = None
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class DocumentPage:
    page_number: int
    width: float | None = None
    height: float | None = None
    rotation: int = 0
    blocks: list[DocumentBlock] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)
    reading_order: list[str] = field(default_factory=list)
    orientation: Orientation = Orientation.DEGREE_0

    def __post_init__(self) -> None:
        self.orientation = Orientation.from_rotation(self.rotation)
        if not self.reading_order:
            self.reading_order = [block.id for block in self.blocks]


@dataclass
class DocumentSection:
    id: str
    title: str | None = None
    level: int = 1
    section_type: str = "section"
    parent_id: str | None = None
    children: list[DocumentSection] = field(default_factory=list)
    block_ids: list[str] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)

    def add_child(self, child: DocumentSection) -> None:
        child.parent_id = self.id
        self.children.append(child)


@dataclass
class DocumentAttachment:
    id: str
    filename: str
    mime_type: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class ParserInfo:
    parser_name: str
    parser_version: str
    source_mime_type: str | None = None
    warnings: list[str] = field(default_factory=list)
    confidence: float | None = None
    ocr_used: bool = False


@dataclass
class ProcessingInfo:
    status: str = "parsed"
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    stages: list[str] = field(default_factory=list)
    normalized: bool = True
    sanitization_warnings: list[str] = field(default_factory=list)
    extra: dict[str, Any] = field(default_factory=dict)


@dataclass
class DocumentMetadata:
    author: str | None = None
    title: str | None = None
    subject: str | None = None
    language: str = "unknown"
    keywords: list[str] = field(default_factory=list)
    creation_date: str | None = None
    modification_date: str | None = None
    producer: str | None = None
    source: str | None = None
    file_hash: str | None = None
    mime_type: str | None = None
    page_count: int = 0
    parser_version: str | None = None
    extra: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_mapping(cls, values: dict[str, Any] | None) -> DocumentMetadata:
        values = dict(values or {})
        known = {
            "author",
            "title",
            "subject",
            "language",
            "keywords",
            "creation_date",
            "modification_date",
            "producer",
            "source",
            "file_hash",
            "mime_type",
            "page_count",
            "parser_version",
        }
        kwargs: dict[str, Any] = {}
        for key in known:
            if key in values:
                kwargs[key] = values.pop(key)
        if "keywords" in kwargs and isinstance(kwargs["keywords"], str):
            kwargs["keywords"] = [
                item.strip() for item in kwargs["keywords"].split(",") if item.strip()
            ]
        metadata = cls(**kwargs)
        metadata.extra.update(values)
        return metadata


@dataclass
class LayoutRegion:
    id: str
    layout_type: LayoutType
    page_number: int | None = None
    bbox: BoundingBox | None = None
    block_ids: list[str] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class LayoutDescriptor:
    layout_type: LayoutType = LayoutType.UNKNOWN
    regions: list[LayoutRegion] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class LogicalDocument:
    id: str
    title: str
    metadata: DocumentMetadata
    language: str
    document_type: DocumentType
    pages: list[DocumentPage] = field(default_factory=list)
    sections: list[DocumentSection] = field(default_factory=list)
    blocks: list[DocumentBlock] = field(default_factory=list)
    attachments: list[DocumentAttachment] = field(default_factory=list)
    parser_info: ParserInfo = field(
        default_factory=lambda: ParserInfo(parser_name="unknown", parser_version="1.0")
    )
    processing_info: ProcessingInfo = field(default_factory=ProcessingInfo)
    version: int = 1
    status: str = "parsed"
    layout: LayoutDescriptor = field(default_factory=LayoutDescriptor)

    def __post_init__(self) -> None:
        self.language = self.language or self.metadata.language or "unknown"
        self.metadata.language = self.language
        declared_page_count = _positive_page_count(self.metadata.page_count) or 0
        highest_materialized_page = max(
            (
                page.page_number
                for page in self.pages
                if _positive_page_count(page.page_number) is not None
            ),
            default=0,
        )
        highest_citation_page = max(
            (block.page for block in self.blocks if _positive_page_count(block.page) is not None),
            default=0,
        )
        self.metadata.page_count = max(
            declared_page_count,
            highest_materialized_page,
            highest_citation_page,
        )
        self.metadata.parser_version = self.parser_info.parser_version
        self._link_reading_order()

    @property
    def text(self) -> str:
        return self.to_plain_text()

    def to_plain_text(self) -> str:
        return "\n\n".join(block.text for block in self._ordered_blocks() if block.text)

    def _ordered_blocks(self) -> list[DocumentBlock]:
        ordered: list[DocumentBlock] = []
        seen: set[str] = set()

        def emit(block: DocumentBlock | None) -> None:
            if block is None or block.id in seen:
                return
            seen.add(block.id)
            ordered.append(block)

        for page in sorted(self.pages, key=lambda item: item.page_number):
            page_blocks_by_id = {block.id: block for block in page.blocks}
            for block_id in page.reading_order:
                emit(page_blocks_by_id.get(block_id))
            remaining = sorted(
                (block for block in page.blocks if block.id not in seen),
                key=lambda block: (
                    block.reading_order.reading_index
                    if block.reading_order is not None
                    else len(page.blocks),
                    block.id,
                ),
            )
            for block in remaining:
                emit(block)

        for block in self.blocks:
            emit(block)
        return ordered

    def get_block(self, block_id: str) -> DocumentBlock | None:
        return next((block for block in self.blocks if block.id == block_id), None)

    def _link_reading_order(self) -> None:
        for index, block in enumerate(self.blocks):
            previous_id = self.blocks[index - 1].id if index > 0 else None
            next_id = self.blocks[index + 1].id if index < len(self.blocks) - 1 else None
            block.reading_order = ReadingOrder(
                reading_index=index,
                previous_id=previous_id,
                next_id=next_id,
                parent_id=block.parent_id,
                children_ids=list(block.children),
            )
        for page in self.pages:
            page_block_ids = [block.id for block in page.blocks]
            page.reading_order = page.reading_order or page_block_ids


class DocumentClassifier(ABC):
    @abstractmethod
    def classify(self, document: LogicalDocument) -> DocumentType:
        raise NotImplementedError


class RuleBasedDocumentClassifier(DocumentClassifier):
    def classify(self, document: LogicalDocument) -> DocumentType:
        parser_name = document.parser_info.parser_name.lower()
        title = document.title.lower()
        source = str(document.metadata.source or "").lower()
        haystack = " ".join([parser_name, title, source, document.text[:500].lower()])
        if parser_name == "pptx":
            return DocumentType.PRESENTATION
        if parser_name in {"xlsx", "csv"}:
            return DocumentType.SPREADSHEET
        if "invoice" in haystack or "hoa don" in haystack:
            return DocumentType.INVOICE
        if "contract" in haystack or "hop dong" in haystack:
            return DocumentType.CONTRACT
        if "policy" in haystack or "chinh sach" in haystack:
            return DocumentType.POLICY
        if "manual" in haystack or "huong dan" in haystack:
            return DocumentType.MANUAL
        if "financial" in haystack or "bao cao tai chinh" in haystack or "structured" in haystack:
            return DocumentType.STRUCTURED_DOCUMENT
        return DocumentType.UNKNOWN


class DocumentClassifierFactory:
    @staticmethod
    def create(strategy: str = "rule_based") -> DocumentClassifier:
        normalized = strategy.strip().lower()
        if normalized == "rule_based":
            return RuleBasedDocumentClassifier()
        raise ValueError(f"Unsupported document classifier strategy: {strategy}")


class LogicalDocumentFactory:
    @staticmethod
    def from_plain_text(
        *,
        text: str,
        title: str = "Document",
        parser_name: str = "text",
        parser_version: str = "1.0",
        language: str = "unknown",
        metadata: dict[str, Any] | None = None,
        warnings: list[str] | None = None,
        confidence: float | None = None,
        ocr_used: bool = False,
    ) -> LogicalDocument:
        return LogicalDocumentFactory.from_parsed_parts(
            text=text,
            title=title,
            pages=[],
            sections=[],
            tables=[],
            images_metadata=[],
            metadata=metadata or {},
            parser_name=parser_name,
            parser_version=parser_version,
            warnings=warnings or [],
            confidence=confidence,
            ocr_used=ocr_used,
            detected_language=language,
        )

    @staticmethod
    def from_parsed_parts(
        *,
        text: str,
        title: str,
        pages: list[Any],
        sections: list[Any],
        tables: list[Any],
        images_metadata: list[Any],
        metadata: dict[str, Any],
        parser_name: str,
        parser_version: str,
        warnings: list[str],
        confidence: float | None,
        ocr_used: bool,
        detected_language: str,
    ) -> LogicalDocument:
        blocks: list[DocumentBlock] = []
        document_pages: list[DocumentPage] = []
        authoritative_page_count = _authoritative_page_count(metadata)
        factory_warnings = list(warnings)

        page_values = list(pages) or [type("LegacyPage", (), {"page_number": 1, "text": text})()]
        heading_levels: dict[str, int] = {}
        for section in sections:
            level = max(1, min(6, int(getattr(section, "level", 1) or 1)))
            for block_id in list(getattr(section, "block_ids", []) or []):
                heading_levels.setdefault(str(block_id), level)
        table_by_id = {
            str(getattr(table, "table_id", "")): table
            for table in tables
            if str(getattr(table, "table_id", ""))
        }
        materialized_table_ids: set[str] = set()
        for page in page_values:
            page_number = int(
                getattr(page, "page_number", len(document_pages) + 1) or len(document_pages) + 1
            )
            page_text = str(getattr(page, "text", "") or "")
            elements = list(getattr(page, "elements", []) or [])
            if elements:
                page_blocks = []
                for element in elements:
                    element_text = str(getattr(element, "text", "") or "")
                    if not element_text.strip():
                        continue
                    element_metadata = dict(getattr(element, "metadata", {}) or {})
                    element_id = str(element.element_id)
                    source_table = table_by_id.get(element_id)
                    block_text = render_element_markdown(
                        element,
                        heading_level=heading_levels.get(element_id),
                        table_rows=(
                            getattr(source_table, "rows", None)
                            if source_table is not None
                            else None
                        ),
                    )
                    element_metadata.setdefault("canonical_text", element_text)
                    element_bbox = _bbox_from_any(
                        getattr(element, "bbox", None)
                        or element_metadata.get("bbox")
                        or element_metadata.get("bounding_box")
                    )
                    element_confidence = (
                        _float_or_none(getattr(element, "confidence", None))
                        or _float_or_none(element_metadata.get("ocr_confidence"))
                        or _float_or_none(element_metadata.get("confidence"))
                    )
                    element_rotation = int(
                        getattr(element, "rotation", None)
                        or element_metadata.get("rotation_applied")
                        or 0
                    )
                    provenance = dict(getattr(element, "provenance", {}) or {})
                    if provenance:
                        element_metadata.setdefault("provenance", provenance)
                    page_blocks.append(
                        DocumentBlock(
                            id=element_id,
                            block_type=str(getattr(element, "block_type", BlockType.PARAGRAPH)),
                            text=block_text,
                            page=getattr(element, "page_number", page_number),
                            metadata=element_metadata,
                            bbox=element_bbox,
                            confidence=element_confidence,
                            rotation=element_rotation,
                        )
                    )
                materialized_table_ids.update(
                    block.id for block in page_blocks if block.block_type == BlockType.TABLE
                )
            else:
                page_blocks = LogicalDocumentFactory._blocks_from_text(
                    page_text, page_number=page_number, prefix=f"page-{page_number}"
                )
            document_pages.append(
                DocumentPage(
                    page_number=page_number,
                    width=_float_or_none(getattr(page, "width", None))
                    or _float_or_none(
                        getattr(page, "metadata", {}).get("width")
                        if isinstance(getattr(page, "metadata", None), dict)
                        else None
                    ),
                    height=_float_or_none(getattr(page, "height", None))
                    or _float_or_none(
                        getattr(page, "metadata", {}).get("height")
                        if isinstance(getattr(page, "metadata", None), dict)
                        else None
                    ),
                    rotation=int(
                        getattr(page, "rotation", None)
                        or (getattr(page, "metadata", {}) or {}).get("rotation_applied", 0)
                        if isinstance(getattr(page, "metadata", None), dict)
                        else 0
                    ),
                    blocks=page_blocks,
                    metadata=dict(getattr(page, "metadata", {}) or {}),
                )
            )
            blocks.extend(page_blocks)
        pages_by_number = {page.page_number: page for page in document_pages}

        table_blocks = []
        for index, table in enumerate(tables, start=1):
            table_id = str(getattr(table, "table_id", f"table-{index}"))
            if table_id in materialized_table_ids:
                continue
            location = getattr(table, "location", None)
            table_rows = getattr(table, "rows", [])
            table_text = render_markdown_table_text(table_rows)
            canonical_text = render_table_text(table_rows)
            table_page = _page_number_from_table_location(location)
            page_warning: str | None = None
            if (
                table_page is not None
                and authoritative_page_count is not None
                and table_page > authoritative_page_count
                and table_page not in pages_by_number
            ):
                table_page = None
                page_warning = "table_page_out_of_range"
                if page_warning not in factory_warnings:
                    factory_warnings.append(page_warning)
            table_metadata = {
                "location": location,
                "columns": getattr(table, "columns", None),
                "header": list(getattr(table, "header", []) or []),
                "canonical_text": canonical_text,
                "markdown_text": table_text,
                "cells": [dict(cell) for cell in list(getattr(table, "cells", []) or [])],
                **dict(getattr(table, "metadata", {}) or {}),
            }
            if page_warning is not None:
                table_metadata["page_warning"] = page_warning
            table_block = DocumentBlock(
                id=table_id,
                block_type=BlockType.TABLE,
                text=table_text,
                page=table_page,
                metadata=table_metadata,
                bbox=_bbox_from_any(getattr(table, "bbox", None) or table_metadata.get("bbox")),
                confidence=_float_or_none(getattr(table, "confidence", None)),
            )
            table_blocks.append(table_block)
            if table_block.page is not None:
                document_page = pages_by_number.get(table_block.page)
                if document_page is None:
                    document_page = DocumentPage(page_number=table_block.page)
                    pages_by_number[table_block.page] = document_page
                    document_pages.append(document_page)
                document_page.blocks.append(table_block)
                if table_block.id not in document_page.reading_order:
                    document_page.reading_order.append(table_block.id)
        blocks.extend(table_blocks)
        document_pages.sort(key=lambda page: page.page_number)

        attachments = [
            DocumentAttachment(
                id=f"attachment-{index}",
                filename=str(getattr(image, "name", None) or f"image-{index}"),
                metadata={"location": getattr(image, "location", None), "kind": "image_metadata"},
            )
            for index, image in enumerate(images_metadata, start=1)
        ]

        document_sections = LogicalDocumentFactory._sections_from_parsed_parts(
            sections,
            blocks,
        )
        document_metadata = DocumentMetadata.from_mapping(metadata)
        if authoritative_page_count is not None:
            document_metadata.page_count = authoritative_page_count
        document_metadata.title = document_metadata.title or title
        document_metadata.language = detected_language or document_metadata.language
        parser_info = ParserInfo(
            parser_name=parser_name,
            parser_version=parser_version,
            warnings=factory_warnings,
            confidence=confidence,
            ocr_used=ocr_used,
        )
        logical_document = LogicalDocument(
            id=str(uuid4()),
            title=title,
            metadata=document_metadata,
            language=document_metadata.language,
            document_type=DocumentType.UNKNOWN,
            pages=document_pages,
            sections=document_sections,
            blocks=blocks,
            attachments=attachments,
            parser_info=parser_info,
            processing_info=ProcessingInfo(stages=["parse", "normalize"]),
            version=1,
            status="parsed",
        )
        logical_document.document_type = DocumentClassifierFactory.create().classify(
            logical_document
        )
        return logical_document

    @staticmethod
    def _blocks_from_text(text: str, *, page_number: int, prefix: str) -> list[DocumentBlock]:
        paragraphs = [line.strip() for line in text.splitlines() if line.strip()]
        if not paragraphs and text.strip():
            paragraphs = [text.strip()]
        blocks: list[DocumentBlock] = []
        for index, paragraph in enumerate(paragraphs, start=1):
            blocks.append(
                DocumentBlock(
                    id=f"{prefix}-block-{index}",
                    block_type=BlockType.PARAGRAPH,
                    text=paragraph,
                    page=page_number,
                )
            )
        return blocks

    @staticmethod
    def _sections_from_parsed_parts(
        sections: list[Any],
        blocks: list[DocumentBlock],
    ) -> list[DocumentSection]:
        if not sections:
            return [
                DocumentSection(
                    id="section-root",
                    title="Document",
                    level=1,
                    block_ids=[block.id for block in blocks],
                )
            ]
        document_sections: list[DocumentSection] = []
        known_block_ids = {block.id for block in blocks}
        for index, section in enumerate(sections, start=1):
            page_number = getattr(section, "page_number", None)
            explicit_block_ids = list(getattr(section, "block_ids", []) or [])
            if explicit_block_ids:
                block_ids = list(
                    dict.fromkeys(
                        block_id for block_id in explicit_block_ids if block_id in known_block_ids
                    )
                )
            else:
                block_ids = (
                    [block.id for block in blocks if block.page == page_number]
                    if page_number is not None
                    else [block.id for block in blocks]
                )
            document_sections.append(
                DocumentSection(
                    id=f"section-{index}",
                    title=getattr(section, "title", None),
                    level=int(getattr(section, "level", 1) or 1),
                    section_type="section",
                    block_ids=block_ids,
                    metadata={"page_number": page_number},
                )
            )
        return document_sections


def _page_number_from_table_location(location: Any) -> int | None:
    if not isinstance(location, str):
        return None
    match = re.search(r"(?:^|:)page:(\d+)(?:$|:)", location)
    if not match:
        match = re.search(r"(?:^|:)page-(\d+)(?:$|:)", location)
    if not match:
        return None
    page_number = int(match.group(1))
    return page_number if page_number > 0 else None


def _positive_page_count(value: Any) -> int | None:
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        return None
    return value


def _float_or_none(value: Any) -> float | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return float(value)
    return None


def _bbox_from_any(value: Any) -> BoundingBox | None:
    if isinstance(value, BoundingBox):
        return value
    if not isinstance(value, dict):
        return None
    unit = str(value.get("unit") or "pixel")
    try:
        if all(key in value for key in ("x0", "y0", "x1", "y1")):
            return BoundingBox.from_corners(
                float(value["x0"]),
                float(value["y0"]),
                float(value["x1"]),
                float(value["y1"]),
                unit=unit,
            )
        if all(key in value for key in ("x", "y", "width", "height")):
            return BoundingBox(
                float(value["x"]),
                float(value["y"]),
                float(value["width"]),
                float(value["height"]),
                unit=unit,
            )
    except (TypeError, ValueError):
        return None
    return None


def _authoritative_page_count(metadata: dict[str, Any]) -> int | None:
    document_analysis = metadata.get("document_analysis")
    if isinstance(document_analysis, dict):
        analysis_count = _positive_page_count(document_analysis.get("page_count"))
        if analysis_count is not None:
            return analysis_count
    ocr_page_count = _positive_page_count(metadata.get("ocr_page_count"))
    if ocr_page_count is not None:
        return ocr_page_count
    return _positive_page_count(metadata.get("page_count"))
