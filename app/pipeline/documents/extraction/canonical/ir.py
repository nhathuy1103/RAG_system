from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

from app.pipeline.documents.extraction.canonical.geometry import (
    AxisAlignedBoundingBox,
    CoordinateSpace,
    CoordinateTransform,
    Polygon,
)

CANONICAL_IR_SCHEMA_NAME = "canonical_document_ir"
CANONICAL_IR_SCHEMA_VERSION = "2.0.0"
SUPPORTED_CANONICAL_IR_MAJOR = "2"


CANONICAL_ELEMENT_TYPES = {
    "text_block",
    "line",
    "token",
    "text_span",
    "heading",
    "paragraph",
    "list",
    "table",
    "table_row",
    "table_cell",
    "figure",
    "caption",
    "header",
    "footer",
    "page_number",
    "unknown",
}


@dataclass(frozen=True)
class CanonicalGeometry:
    bbox: AxisAlignedBoundingBox | None = None
    polygon: Polygon | None = None
    normalized_bbox: AxisAlignedBoundingBox | None = None
    provider_bbox: AxisAlignedBoundingBox | None = None
    provider_polygon: Polygon | None = None
    transform_chain: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        return {
            "bbox": self.bbox.to_dict() if self.bbox is not None else None,
            "polygon": self.polygon.to_dict() if self.polygon is not None else None,
            "normalized_bbox": (
                self.normalized_bbox.to_dict() if self.normalized_bbox is not None else None
            ),
            "provider_bbox": (
                self.provider_bbox.to_dict() if self.provider_bbox is not None else None
            ),
            "provider_polygon": (
                self.provider_polygon.to_dict() if self.provider_polygon is not None else None
            ),
            "transform_chain": list(self.transform_chain),
        }

    @classmethod
    def from_dict(cls, value: dict[str, Any] | None) -> CanonicalGeometry | None:
        if value is None:
            return None
        return cls(
            bbox=(
                AxisAlignedBoundingBox.from_dict(value["bbox"])
                if value.get("bbox") is not None
                else None
            ),
            polygon=(
                Polygon.from_dict(value["polygon"]) if value.get("polygon") is not None else None
            ),
            normalized_bbox=(
                AxisAlignedBoundingBox.from_dict(value["normalized_bbox"])
                if value.get("normalized_bbox") is not None
                else None
            ),
            provider_bbox=(
                AxisAlignedBoundingBox.from_dict(value["provider_bbox"])
                if value.get("provider_bbox") is not None
                else None
            ),
            provider_polygon=(
                Polygon.from_dict(value["provider_polygon"])
                if value.get("provider_polygon") is not None
                else None
            ),
            transform_chain=tuple(str(item) for item in value.get("transform_chain") or ()),
        )


@dataclass(frozen=True)
class CanonicalTableCell:
    row_index: int
    column_index: int
    text: str
    bbox: AxisAlignedBoundingBox | None = None
    polygon: Polygon | None = None
    row_span: int = 1
    column_span: int = 1
    confidence: float | None = None
    source_element_ids: tuple[str, ...] = ()
    attributes: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if self.row_index < 0 or self.column_index < 0:
            raise ValueError("table cell row/column indexes must not be negative")
        if self.row_span < 1 or self.column_span < 1:
            raise ValueError("table cell spans must be >= 1")

    def to_dict(self) -> dict[str, Any]:
        return {
            "row_index": self.row_index,
            "column_index": self.column_index,
            "text": self.text,
            "bbox": self.bbox.to_dict() if self.bbox is not None else None,
            "polygon": self.polygon.to_dict() if self.polygon is not None else None,
            "row_span": self.row_span,
            "column_span": self.column_span,
            "confidence": self.confidence,
            "source_element_ids": list(self.source_element_ids),
            "attributes": dict(self.attributes),
        }

    @classmethod
    def from_dict(cls, value: dict[str, Any]) -> CanonicalTableCell:
        return cls(
            row_index=int(value["row_index"]),
            column_index=int(value["column_index"]),
            text=str(value.get("text") or ""),
            bbox=(
                AxisAlignedBoundingBox.from_dict(value["bbox"])
                if value.get("bbox") is not None
                else None
            ),
            polygon=(
                Polygon.from_dict(value["polygon"]) if value.get("polygon") is not None else None
            ),
            row_span=int(value.get("row_span") or 1),
            column_span=int(value.get("column_span") or 1),
            confidence=_optional_float(value.get("confidence")),
            source_element_ids=tuple(str(item) for item in value.get("source_element_ids") or ()),
            attributes=dict(value.get("attributes") or {}),
        )


@dataclass(frozen=True)
class CanonicalTable:
    table_id: str
    page_index: int
    bbox: AxisAlignedBoundingBox | None = None
    polygon: Polygon | None = None
    row_count: int | None = None
    column_count: int | None = None
    cells: tuple[CanonicalTableCell, ...] = ()
    source_element_ids: tuple[str, ...] = ()
    confidence: float | None = None
    continuation: dict[str, Any] = field(default_factory=dict)
    attributes: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.table_id:
            raise ValueError("table requires table_id")
        if self.page_index < 0:
            raise ValueError("table page_index must not be negative")
        if self.row_count is not None and self.row_count < 0:
            raise ValueError("row_count must not be negative")
        if self.column_count is not None and self.column_count < 0:
            raise ValueError("column_count must not be negative")

    def to_dict(self) -> dict[str, Any]:
        return {
            "table_id": self.table_id,
            "page_index": self.page_index,
            "bbox": self.bbox.to_dict() if self.bbox is not None else None,
            "polygon": self.polygon.to_dict() if self.polygon is not None else None,
            "row_count": self.row_count,
            "column_count": self.column_count,
            "cells": [cell.to_dict() for cell in self.cells],
            "source_element_ids": list(self.source_element_ids),
            "confidence": self.confidence,
            "continuation": dict(self.continuation),
            "attributes": dict(self.attributes),
        }

    @classmethod
    def from_dict(cls, value: dict[str, Any]) -> CanonicalTable:
        return cls(
            table_id=str(value["table_id"]),
            page_index=int(value["page_index"]),
            bbox=(
                AxisAlignedBoundingBox.from_dict(value["bbox"])
                if value.get("bbox") is not None
                else None
            ),
            polygon=(
                Polygon.from_dict(value["polygon"]) if value.get("polygon") is not None else None
            ),
            row_count=(int(value["row_count"]) if value.get("row_count") is not None else None),
            column_count=(
                int(value["column_count"]) if value.get("column_count") is not None else None
            ),
            cells=tuple(CanonicalTableCell.from_dict(item) for item in value.get("cells") or ()),
            source_element_ids=tuple(str(item) for item in value.get("source_element_ids") or ()),
            confidence=_optional_float(value.get("confidence")),
            continuation=dict(value.get("continuation") or {}),
            attributes=dict(value.get("attributes") or {}),
        )


@dataclass(frozen=True)
class CanonicalElement:
    element_id: str
    element_type: str
    page_index: int | None
    parent_id: str | None = None
    child_ids: tuple[str, ...] = ()
    text: str | None = None
    confidence: float | None = None
    provenance: dict[str, Any] = field(default_factory=dict)
    geometry: CanonicalGeometry | None = None
    attributes: dict[str, Any] = field(default_factory=dict)
    source_block_ids: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if not self.element_id:
            raise ValueError("element requires element_id")
        if self.element_type not in CANONICAL_ELEMENT_TYPES:
            raise ValueError(f"unsupported element type: {self.element_type}")
        if self.page_index is not None and self.page_index < 0:
            raise ValueError("element page_index must not be negative")

    def to_dict(self) -> dict[str, Any]:
        return {
            "element_id": self.element_id,
            "element_type": self.element_type,
            "page_index": self.page_index,
            "parent_id": self.parent_id,
            "child_ids": list(self.child_ids),
            "text": self.text,
            "confidence": self.confidence,
            "provenance": dict(self.provenance),
            "geometry": self.geometry.to_dict() if self.geometry is not None else None,
            "attributes": dict(self.attributes),
            "source_block_ids": list(self.source_block_ids),
        }

    @classmethod
    def from_dict(cls, value: dict[str, Any]) -> CanonicalElement:
        return cls(
            element_id=str(value["element_id"]),
            element_type=str(value["element_type"]),
            page_index=(int(value["page_index"]) if value.get("page_index") is not None else None),
            parent_id=str(value["parent_id"]) if value.get("parent_id") is not None else None,
            child_ids=tuple(str(item) for item in value.get("child_ids") or ()),
            text=str(value["text"]) if value.get("text") is not None else None,
            confidence=_optional_float(value.get("confidence")),
            provenance=dict(value.get("provenance") or {}),
            geometry=CanonicalGeometry.from_dict(value.get("geometry")),
            attributes=dict(value.get("attributes") or {}),
            source_block_ids=tuple(str(item) for item in value.get("source_block_ids") or ()),
        )


@dataclass(frozen=True)
class CanonicalPage:
    page_index: int
    page_number: int
    original_width: float | None
    original_height: float | None
    original_unit: str | None
    rotation: int = 0
    coordinate_spaces: tuple[CoordinateSpace, ...] = ()
    transforms: tuple[CoordinateTransform, ...] = ()
    elements: tuple[CanonicalElement, ...] = ()
    tables: tuple[CanonicalTable, ...] = ()
    reading_order: tuple[str, ...] = ()
    page_metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if self.page_index < 0:
            raise ValueError("page_index must not be negative")
        if self.page_number <= 0:
            raise ValueError("page_number must be positive")
        if self.original_width is not None and self.original_width <= 0:
            raise ValueError("original_width must be positive when present")
        if self.original_height is not None and self.original_height <= 0:
            raise ValueError("original_height must be positive when present")

    def to_dict(self) -> dict[str, Any]:
        return {
            "page_index": self.page_index,
            "page_number": self.page_number,
            "original_width": self.original_width,
            "original_height": self.original_height,
            "original_unit": self.original_unit,
            "rotation": self.rotation,
            "coordinate_spaces": [space.to_dict() for space in self.coordinate_spaces],
            "transforms": [transform.to_dict() for transform in self.transforms],
            "elements": [element.to_dict() for element in self.elements],
            "tables": [table.to_dict() for table in self.tables],
            "reading_order": list(self.reading_order),
            "page_metadata": dict(self.page_metadata),
        }

    @classmethod
    def from_dict(cls, value: dict[str, Any]) -> CanonicalPage:
        return cls(
            page_index=int(value["page_index"]),
            page_number=int(value["page_number"]),
            original_width=_optional_float(value.get("original_width")),
            original_height=_optional_float(value.get("original_height")),
            original_unit=(
                str(value["original_unit"]) if value.get("original_unit") is not None else None
            ),
            rotation=int(value.get("rotation") or 0),
            coordinate_spaces=tuple(
                CoordinateSpace.from_dict(item) for item in value.get("coordinate_spaces") or ()
            ),
            transforms=tuple(
                CoordinateTransform.from_dict(item) for item in value.get("transforms") or ()
            ),
            elements=tuple(
                CanonicalElement.from_dict(item) for item in value.get("elements") or ()
            ),
            tables=tuple(CanonicalTable.from_dict(item) for item in value.get("tables") or ()),
            reading_order=tuple(str(item) for item in value.get("reading_order") or ()),
            page_metadata=dict(value.get("page_metadata") or {}),
        )


@dataclass(frozen=True)
class CanonicalDocument:
    document_id: str
    source: dict[str, Any]
    document_metadata: dict[str, Any]
    parser_provenance: dict[str, Any]
    extraction_provenance: dict[str, Any]
    pages: tuple[CanonicalPage, ...]
    global_elements: tuple[CanonicalElement, ...] = ()
    warnings: tuple[str, ...] = ()
    created_at: str = field(default_factory=lambda: datetime.now(UTC).isoformat())
    schema_name: str = CANONICAL_IR_SCHEMA_NAME
    schema_version: str = CANONICAL_IR_SCHEMA_VERSION

    def __post_init__(self) -> None:
        if self.schema_name != CANONICAL_IR_SCHEMA_NAME:
            raise ValueError("unsupported canonical IR schema name")
        if not is_supported_schema_version(self.schema_version):
            raise ValueError(f"unsupported canonical IR schema version: {self.schema_version}")
        if not self.document_id:
            raise ValueError("document_id is required")

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_name": self.schema_name,
            "schema_version": self.schema_version,
            "document_id": self.document_id,
            "source": dict(self.source),
            "document_metadata": dict(self.document_metadata),
            "parser_provenance": dict(self.parser_provenance),
            "extraction_provenance": dict(self.extraction_provenance),
            "pages": [page.to_dict() for page in self.pages],
            "global_elements": [element.to_dict() for element in self.global_elements],
            "warnings": list(self.warnings),
            "created_at": self.created_at,
        }

    @classmethod
    def from_dict(cls, value: dict[str, Any]) -> CanonicalDocument:
        _reject_unknown_keys(
            value,
            {
                "schema_name",
                "schema_version",
                "document_id",
                "source",
                "document_metadata",
                "parser_provenance",
                "extraction_provenance",
                "pages",
                "global_elements",
                "warnings",
                "created_at",
            },
        )
        return cls(
            schema_name=str(value["schema_name"]),
            schema_version=str(value["schema_version"]),
            document_id=str(value["document_id"]),
            source=dict(value.get("source") or {}),
            document_metadata=dict(value.get("document_metadata") or {}),
            parser_provenance=dict(value.get("parser_provenance") or {}),
            extraction_provenance=dict(value.get("extraction_provenance") or {}),
            pages=tuple(CanonicalPage.from_dict(item) for item in value.get("pages") or ()),
            global_elements=tuple(
                CanonicalElement.from_dict(item) for item in value.get("global_elements") or ()
            ),
            warnings=tuple(str(item) for item in value.get("warnings") or ()),
            created_at=str(value["created_at"]),
        )


def is_supported_schema_version(version: str) -> bool:
    parts = str(version).split(".")
    return bool(parts and parts[0] == SUPPORTED_CANONICAL_IR_MAJOR)


def _optional_float(value: Any) -> float | None:
    if value is None:
        return None
    return float(value)


def _reject_unknown_keys(value: dict[str, Any], allowed: set[str]) -> None:
    unknown = sorted(set(value) - allowed)
    if unknown:
        raise ValueError("unsupported canonical IR fields: " + ", ".join(unknown))
