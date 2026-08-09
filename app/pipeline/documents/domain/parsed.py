from __future__ import annotations

from dataclasses import dataclass, field

from app.pipeline.documents.domain.models import (
    BoundingBox,
    LogicalDocument,
    LogicalDocumentFactory,
)


@dataclass
class ParsedElement:
    element_id: str
    block_type: str
    text: str
    page_number: int | None
    metadata: dict[str, object] = field(default_factory=dict)
    bbox: BoundingBox | None = None
    confidence: float | None = None
    rotation: int = 0
    provenance: dict[str, object] = field(default_factory=dict)


@dataclass
class ParsedPage:
    page_number: int
    text: str
    elements: list[ParsedElement] = field(default_factory=list)
    metadata: dict[str, object] = field(default_factory=dict)
    width: float | None = None
    height: float | None = None
    rotation: int = 0


@dataclass
class ParsedSection:
    text: str
    page_number: int | None
    title: str | None
    level: int = 1
    block_ids: list[str] = field(default_factory=list)


@dataclass
class ParsedTable:
    table_id: str
    location: str
    rows: list[list[str]]
    columns: int
    header: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    cells: list[dict[str, object]] = field(default_factory=list)
    bbox: BoundingBox | None = None
    confidence: float | None = None
    metadata: dict[str, object] = field(default_factory=dict)


@dataclass
class ParsedImageMetadata:
    location: str
    name: str | None = None


@dataclass
class ParsedDocument:
    text: str
    pages: list[ParsedPage] = field(default_factory=list)
    sections: list[ParsedSection] = field(default_factory=list)
    tables: list[ParsedTable] = field(default_factory=list)
    images_metadata: list[ParsedImageMetadata] = field(default_factory=list)
    document_metadata: dict[str, object] = field(default_factory=dict)
    warnings: list[str] = field(default_factory=list)
    parser_name: str = "unknown"
    parser_version: str = "1.0"
    confidence: float | None = None
    ocr_used: bool = False
    detected_language: str = "unknown"
    logical_document: LogicalDocument | None = None
    content_markdown: str | None = None

    def to_logical_document(self) -> LogicalDocument:
        if self.logical_document is None:
            self.logical_document = LogicalDocumentFactory.from_parsed_parts(
                text=self.text,
                title=str(self.document_metadata.get("title") or self.parser_name.upper()),
                pages=self.pages,
                sections=self.sections,
                tables=self.tables,
                images_metadata=self.images_metadata,
                metadata=self.document_metadata,
                parser_name=self.parser_name,
                parser_version=self.parser_version,
                warnings=self.warnings,
                confidence=self.confidence,
                ocr_used=self.ocr_used,
                detected_language=self.detected_language,
            )
        return self.logical_document


__all__ = [
    "ParsedDocument",
    "ParsedElement",
    "ParsedImageMetadata",
    "ParsedPage",
    "ParsedSection",
    "ParsedTable",
]
