from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from typing import Any

from app.pipeline.documents.extraction.canonical.geometry import AxisAlignedBoundingBox

TABLE_SCHEMA_NAME = "structured_table"
TABLE_SCHEMA_VERSION = "1.0.0"
TABLE_ENGINE_VERSION = "generic_table_engine_v1"
GRID_STRATEGY_VERSION = "grid_reconstruction_v1"
FINANCIAL_STRATEGY_VERSION = "financial_table_strategy_v1"
TOC_STRATEGY_VERSION = "toc_table_strategy_v1"
SUBSIDIARY_STRATEGY_VERSION = "subsidiary_table_strategy_v1"
CROSS_PAGE_STRATEGY_VERSION = "cross_page_table_linker_v1"
TABLE_VALIDATOR_VERSION = "table_validator_v1"
SUPPORTED_TABLE_MAJOR = "1"

TABLE_TYPES = {
    "BORDERED_TABLE",
    "BORDERLESS_TABLE",
    "FINANCIAL_STATEMENT",
    "FINANCIAL_NOTE",
    "TOC_TABLE",
    "SUBSIDIARY_TABLE",
    "OWNERSHIP_TABLE",
    "FORM_TABLE",
    "KEY_VALUE_TABLE",
    "MATRIX_TABLE",
    "SIMPLE_LIST_TABLE",
    "CROSS_PAGE_TABLE",
    "ROTATED_TABLE",
    "MIXED_CONTENT_TABLE",
    "UNKNOWN_TABLE",
}

ROW_TYPES = {"header", "data", "section", "total", "label", "footer", "unknown"}
VALUE_TYPES = {"text", "numeric", "blank", "hyphen", "date", "period", "unknown"}
SPAN_TYPES = {"row_span", "column_span", "merged_header", "stub_header"}
ISSUE_SEVERITIES = {"info", "warning", "review", "fail_closed"}
TABLE_STATUSES = {"accepted", "failed", "review", "empty"}
LINK_TYPES = {"continuation", "repeated_header", "fragment", "similar_schema"}
LINK_STATUSES = {"accepted", "review", "rejected"}


class TableSchemaError(ValueError):
    """Raised when a Phase 4 table artifact violates its schema contract."""


@dataclass(frozen=True)
class TableRegionInput:
    region_id: str
    document_id: str
    page_number: int
    page_index: int
    bbox: AxisAlignedBoundingBox
    coordinate_space_id: str
    transform_chain_id: str | None = None
    source_table_id: str | None = None
    source_block_ids: tuple[str, ...] = ()
    text: str | None = None
    rows_hint: tuple[tuple[str, ...], ...] = ()
    cells_hint: tuple[dict[str, Any], ...] = ()
    row_count_hint: int | None = None
    column_count_hint: int | None = None
    table_type_hint: str | None = None
    orientation: int = 0
    confidence: float = 1.0
    provenance: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.region_id:
            raise TableSchemaError("table region input requires region_id")
        if self.page_number <= 0 or self.page_index < 0:
            raise TableSchemaError("table region page numbers must be positive")
        if not self.coordinate_space_id:
            raise TableSchemaError("table region requires coordinate_space_id")
        if self.row_count_hint is not None and self.row_count_hint < 0:
            raise TableSchemaError("row_count_hint must not be negative")
        if self.column_count_hint is not None and self.column_count_hint < 0:
            raise TableSchemaError("column_count_hint must not be negative")
        if not 0.0 <= self.confidence <= 1.0:
            raise TableSchemaError("table region confidence must be in [0, 1]")

    def to_dict(self) -> dict[str, Any]:
        return {
            "region_id": self.region_id,
            "document_id": self.document_id,
            "page_number": self.page_number,
            "page_index": self.page_index,
            "bbox": _bbox_to_dict(self.bbox),
            "coordinate_space_id": self.coordinate_space_id,
            "transform_chain_id": self.transform_chain_id,
            "source_table_id": self.source_table_id,
            "source_block_ids": list(self.source_block_ids),
            "text": self.text,
            "rows_hint": [list(row) for row in self.rows_hint],
            "cells_hint": [dict(cell) for cell in self.cells_hint],
            "row_count_hint": self.row_count_hint,
            "column_count_hint": self.column_count_hint,
            "table_type_hint": self.table_type_hint,
            "orientation": self.orientation,
            "confidence": self.confidence,
            "provenance": dict(self.provenance),
        }

    @classmethod
    def from_mapping(cls, value: Mapping[str, Any]) -> TableRegionInput:
        payload = dict(value)
        return cls(
            region_id=str(payload["region_id"]),
            document_id=str(payload["document_id"]),
            page_number=int(payload["page_number"]),
            page_index=int(payload["page_index"]),
            bbox=AxisAlignedBoundingBox.from_dict(dict(payload["bbox"])),
            coordinate_space_id=str(payload["coordinate_space_id"]),
            transform_chain_id=(
                str(payload["transform_chain_id"])
                if payload.get("transform_chain_id") is not None
                else None
            ),
            source_table_id=(
                str(payload["source_table_id"])
                if payload.get("source_table_id") is not None
                else None
            ),
            source_block_ids=tuple(str(item) for item in payload.get("source_block_ids") or ()),
            text=str(payload["text"]) if payload.get("text") is not None else None,
            rows_hint=tuple(
                tuple(str(cell) for cell in row) for row in payload.get("rows_hint") or ()
            ),
            cells_hint=tuple(dict(cell) for cell in payload.get("cells_hint") or ()),
            row_count_hint=(
                int(payload["row_count_hint"])
                if payload.get("row_count_hint") is not None
                else None
            ),
            column_count_hint=(
                int(payload["column_count_hint"])
                if payload.get("column_count_hint") is not None
                else None
            ),
            table_type_hint=(
                str(payload["table_type_hint"])
                if payload.get("table_type_hint") is not None
                else None
            ),
            orientation=int(payload.get("orientation") or 0),
            confidence=float(payload.get("confidence", 1.0)),
            provenance=dict(payload.get("provenance") or {}),
        )

    def checksum(self) -> str:
        return _sha256_json(self.to_dict())


@dataclass(frozen=True)
class TableColumn:
    column_id: str
    table_id: str
    index: int
    logical_index: int
    bbox: AxisAlignedBoundingBox
    header_cell_ids: tuple[str, ...] = ()
    data_type_hint: str | None = None
    period_hint: str | None = None
    semantic_role_hint: str | None = None
    confidence: float = 1.0
    provenance: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.column_id or not self.table_id:
            raise TableSchemaError("table column requires ids")
        if self.index < 0 or self.logical_index < 0:
            raise TableSchemaError("table column indexes must not be negative")
        if not 0.0 <= self.confidence <= 1.0:
            raise TableSchemaError("table column confidence must be in [0, 1]")

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["bbox"] = _bbox_to_dict(self.bbox)
        payload["header_cell_ids"] = list(self.header_cell_ids)
        return payload

    @classmethod
    def from_mapping(cls, value: Mapping[str, Any]) -> TableColumn:
        payload = dict(value)
        return cls(
            column_id=str(payload["column_id"]),
            table_id=str(payload["table_id"]),
            index=int(payload["index"]),
            logical_index=int(payload["logical_index"]),
            header_cell_ids=tuple(str(item) for item in payload.get("header_cell_ids") or ()),
            bbox=AxisAlignedBoundingBox.from_dict(dict(payload["bbox"])),
            data_type_hint=(
                str(payload["data_type_hint"])
                if payload.get("data_type_hint") is not None
                else None
            ),
            period_hint=(
                str(payload["period_hint"]) if payload.get("period_hint") is not None else None
            ),
            semantic_role_hint=(
                str(payload["semantic_role_hint"])
                if payload.get("semantic_role_hint") is not None
                else None
            ),
            confidence=float(payload.get("confidence", 1.0)),
            provenance=dict(payload.get("provenance") or {}),
        )


@dataclass(frozen=True)
class TableRow:
    row_id: str
    table_id: str
    index: int
    logical_index: int
    row_type: str
    bbox: AxisAlignedBoundingBox
    label_cell_ids: tuple[str, ...] = ()
    data_cell_ids: tuple[str, ...] = ()
    hierarchy_level: int = 0
    parent_row_id: str | None = None
    continuation_of_row_id: str | None = None
    confidence: float = 1.0
    provenance: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.row_id or not self.table_id:
            raise TableSchemaError("table row requires ids")
        if self.index < 0 or self.logical_index < 0 or self.hierarchy_level < 0:
            raise TableSchemaError("table row indexes must not be negative")
        if self.row_type not in ROW_TYPES:
            raise TableSchemaError(f"unsupported table row type: {self.row_type}")
        if not 0.0 <= self.confidence <= 1.0:
            raise TableSchemaError("table row confidence must be in [0, 1]")

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["bbox"] = _bbox_to_dict(self.bbox)
        payload["label_cell_ids"] = list(self.label_cell_ids)
        payload["data_cell_ids"] = list(self.data_cell_ids)
        return payload

    @classmethod
    def from_mapping(cls, value: Mapping[str, Any]) -> TableRow:
        payload = dict(value)
        return cls(
            row_id=str(payload["row_id"]),
            table_id=str(payload["table_id"]),
            index=int(payload["index"]),
            logical_index=int(payload["logical_index"]),
            row_type=str(payload["row_type"]),
            label_cell_ids=tuple(str(item) for item in payload.get("label_cell_ids") or ()),
            data_cell_ids=tuple(str(item) for item in payload.get("data_cell_ids") or ()),
            bbox=AxisAlignedBoundingBox.from_dict(dict(payload["bbox"])),
            hierarchy_level=int(payload.get("hierarchy_level") or 0),
            parent_row_id=(
                str(payload["parent_row_id"]) if payload.get("parent_row_id") is not None else None
            ),
            continuation_of_row_id=(
                str(payload["continuation_of_row_id"])
                if payload.get("continuation_of_row_id") is not None
                else None
            ),
            confidence=float(payload.get("confidence", 1.0)),
            provenance=dict(payload.get("provenance") or {}),
        )


@dataclass(frozen=True)
class TableCell:
    cell_id: str
    table_id: str
    row_start: int
    row_end: int
    column_start: int
    column_end: int
    raw_text: str
    normalized_text: str
    bbox: AxisAlignedBoundingBox
    coordinate_space_id: str
    transform_chain_id: str | None = None
    raw_numeric_text: str | None = None
    parsed_numeric_candidate: float | None = None
    value_type: str = "text"
    source_block_ids: tuple[str, ...] = ()
    source_line_ids: tuple[str, ...] = ()
    native_source_refs: tuple[str, ...] = ()
    ocr_source_refs: tuple[str, ...] = ()
    confidence: float = 1.0
    evidence: dict[str, Any] = field(default_factory=dict)
    quality_issues: tuple[str, ...] = ()
    provenance: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.cell_id or not self.table_id:
            raise TableSchemaError("table cell requires ids")
        if min(self.row_start, self.row_end, self.column_start, self.column_end) < 0:
            raise TableSchemaError("table cell indexes must not be negative")
        if self.row_end < self.row_start or self.column_end < self.column_start:
            raise TableSchemaError("table cell spans must be ordered")
        if self.value_type not in VALUE_TYPES:
            raise TableSchemaError(f"unsupported table cell value type: {self.value_type}")
        if not self.coordinate_space_id:
            raise TableSchemaError("table cell requires coordinate_space_id")
        if not 0.0 <= self.confidence <= 1.0:
            raise TableSchemaError("table cell confidence must be in [0, 1]")

    def to_dict(self) -> dict[str, Any]:
        return {
            "cell_id": self.cell_id,
            "table_id": self.table_id,
            "row_start": self.row_start,
            "row_end": self.row_end,
            "column_start": self.column_start,
            "column_end": self.column_end,
            "raw_text": self.raw_text,
            "normalized_text": self.normalized_text,
            "raw_numeric_text": self.raw_numeric_text,
            "parsed_numeric_candidate": self.parsed_numeric_candidate,
            "value_type": self.value_type,
            "bbox": _bbox_to_dict(self.bbox),
            "coordinate_space_id": self.coordinate_space_id,
            "transform_chain_id": self.transform_chain_id,
            "source_block_ids": list(self.source_block_ids),
            "source_line_ids": list(self.source_line_ids),
            "native_source_refs": list(self.native_source_refs),
            "ocr_source_refs": list(self.ocr_source_refs),
            "confidence": self.confidence,
            "evidence": dict(self.evidence),
            "quality_issues": list(self.quality_issues),
            "provenance": dict(self.provenance),
        }

    @classmethod
    def from_mapping(cls, value: Mapping[str, Any]) -> TableCell:
        payload = dict(value)
        return cls(
            cell_id=str(payload["cell_id"]),
            table_id=str(payload["table_id"]),
            row_start=int(payload["row_start"]),
            row_end=int(payload["row_end"]),
            column_start=int(payload["column_start"]),
            column_end=int(payload["column_end"]),
            raw_text=str(payload.get("raw_text") or ""),
            normalized_text=str(payload.get("normalized_text") or ""),
            raw_numeric_text=(
                str(payload["raw_numeric_text"])
                if payload.get("raw_numeric_text") is not None
                else None
            ),
            parsed_numeric_candidate=_optional_float(payload.get("parsed_numeric_candidate")),
            value_type=str(payload.get("value_type") or "text"),
            bbox=AxisAlignedBoundingBox.from_dict(dict(payload["bbox"])),
            coordinate_space_id=str(payload["coordinate_space_id"]),
            transform_chain_id=(
                str(payload["transform_chain_id"])
                if payload.get("transform_chain_id") is not None
                else None
            ),
            source_block_ids=tuple(str(item) for item in payload.get("source_block_ids") or ()),
            source_line_ids=tuple(str(item) for item in payload.get("source_line_ids") or ()),
            native_source_refs=tuple(str(item) for item in payload.get("native_source_refs") or ()),
            ocr_source_refs=tuple(str(item) for item in payload.get("ocr_source_refs") or ()),
            confidence=float(payload.get("confidence", 1.0)),
            evidence=dict(payload.get("evidence") or {}),
            quality_issues=tuple(str(item) for item in payload.get("quality_issues") or ()),
            provenance=dict(payload.get("provenance") or {}),
        )


@dataclass(frozen=True)
class TableHeader:
    header_id: str
    table_id: str
    level: int
    cell_ids: tuple[str, ...]
    covered_columns: tuple[int, ...]
    parent_header_id: str | None = None
    semantic_role: str | None = None
    period: str | None = None
    confidence: float = 1.0
    provenance: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.header_id or not self.table_id:
            raise TableSchemaError("table header requires ids")
        if self.level < 0:
            raise TableSchemaError("table header level must not be negative")
        if not self.cell_ids:
            raise TableSchemaError("table header requires cell ids")
        if any(index < 0 for index in self.covered_columns):
            raise TableSchemaError("covered columns must not be negative")
        if not 0.0 <= self.confidence <= 1.0:
            raise TableSchemaError("table header confidence must be in [0, 1]")

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["cell_ids"] = list(self.cell_ids)
        payload["covered_columns"] = list(self.covered_columns)
        return payload

    @classmethod
    def from_mapping(cls, value: Mapping[str, Any]) -> TableHeader:
        payload = dict(value)
        return cls(
            header_id=str(payload["header_id"]),
            table_id=str(payload["table_id"]),
            level=int(payload["level"]),
            cell_ids=tuple(str(item) for item in payload.get("cell_ids") or ()),
            parent_header_id=(
                str(payload["parent_header_id"])
                if payload.get("parent_header_id") is not None
                else None
            ),
            covered_columns=tuple(int(item) for item in payload.get("covered_columns") or ()),
            semantic_role=(
                str(payload["semantic_role"]) if payload.get("semantic_role") is not None else None
            ),
            period=str(payload["period"]) if payload.get("period") is not None else None,
            confidence=float(payload.get("confidence", 1.0)),
            provenance=dict(payload.get("provenance") or {}),
        )


@dataclass(frozen=True)
class TableSpan:
    span_id: str
    table_id: str
    row_start: int
    row_end: int
    column_start: int
    column_end: int
    span_type: str
    evidence: dict[str, Any] = field(default_factory=dict)
    confidence: float = 1.0

    def __post_init__(self) -> None:
        if not self.span_id or not self.table_id:
            raise TableSchemaError("table span requires ids")
        if min(self.row_start, self.row_end, self.column_start, self.column_end) < 0:
            raise TableSchemaError("table span indexes must not be negative")
        if self.row_end < self.row_start or self.column_end < self.column_start:
            raise TableSchemaError("table span ranges must be ordered")
        if self.span_type not in SPAN_TYPES:
            raise TableSchemaError(f"unsupported table span type: {self.span_type}")
        if not 0.0 <= self.confidence <= 1.0:
            raise TableSchemaError("table span confidence must be in [0, 1]")

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_mapping(cls, value: Mapping[str, Any]) -> TableSpan:
        payload = dict(value)
        return cls(
            span_id=str(payload["span_id"]),
            table_id=str(payload["table_id"]),
            row_start=int(payload["row_start"]),
            row_end=int(payload["row_end"]),
            column_start=int(payload["column_start"]),
            column_end=int(payload["column_end"]),
            span_type=str(payload["span_type"]),
            evidence=dict(payload.get("evidence") or {}),
            confidence=float(payload.get("confidence", 1.0)),
        )


@dataclass(frozen=True)
class TableIssue:
    issue_code: str
    severity: str
    table_id: str
    page_numbers: tuple[int, ...] = ()
    row_ids: tuple[str, ...] = ()
    column_ids: tuple[str, ...] = ()
    cell_ids: tuple[str, ...] = ()
    evidence: dict[str, Any] = field(default_factory=dict)
    reason: str = ""
    provenance: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.issue_code or not self.table_id:
            raise TableSchemaError("table issue requires issue_code and table_id")
        if self.severity not in ISSUE_SEVERITIES:
            raise TableSchemaError(f"unsupported table issue severity: {self.severity}")
        if any(page <= 0 for page in self.page_numbers):
            raise TableSchemaError("table issue page numbers must be positive")

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["page_numbers"] = list(self.page_numbers)
        payload["row_ids"] = list(self.row_ids)
        payload["column_ids"] = list(self.column_ids)
        payload["cell_ids"] = list(self.cell_ids)
        return payload

    @classmethod
    def from_mapping(cls, value: Mapping[str, Any]) -> TableIssue:
        payload = dict(value)
        return cls(
            issue_code=str(payload["issue_code"]),
            severity=str(payload["severity"]),
            table_id=str(payload["table_id"]),
            page_numbers=tuple(int(item) for item in payload.get("page_numbers") or ()),
            row_ids=tuple(str(item) for item in payload.get("row_ids") or ()),
            column_ids=tuple(str(item) for item in payload.get("column_ids") or ()),
            cell_ids=tuple(str(item) for item in payload.get("cell_ids") or ()),
            evidence=dict(payload.get("evidence") or {}),
            reason=str(payload.get("reason") or ""),
            provenance=dict(payload.get("provenance") or {}),
        )


@dataclass(frozen=True)
class CrossPageTableLink:
    link_id: str
    source_table_id: str
    target_table_id: str
    source_page: int
    target_page: int
    link_type: str
    schema_similarity: float
    header_similarity: float
    geometry_evidence: dict[str, Any] = field(default_factory=dict)
    confidence: float = 1.0
    status: str = "accepted"
    reason_codes: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if not self.link_id or not self.source_table_id or not self.target_table_id:
            raise TableSchemaError("cross-page table link requires ids")
        if self.source_page <= 0 or self.target_page <= 0:
            raise TableSchemaError("cross-page table link pages must be positive")
        if self.link_type not in LINK_TYPES:
            raise TableSchemaError(f"unsupported cross-page link type: {self.link_type}")
        if self.status not in LINK_STATUSES:
            raise TableSchemaError(f"unsupported cross-page link status: {self.status}")
        for name in ("schema_similarity", "header_similarity", "confidence"):
            value = float(getattr(self, name))
            if not 0.0 <= value <= 1.0:
                raise TableSchemaError(f"{name} must be in [0, 1]")

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["reason_codes"] = list(self.reason_codes)
        return payload

    @classmethod
    def from_mapping(cls, value: Mapping[str, Any]) -> CrossPageTableLink:
        payload = dict(value)
        return cls(
            link_id=str(payload["link_id"]),
            source_table_id=str(payload["source_table_id"]),
            target_table_id=str(payload["target_table_id"]),
            source_page=int(payload["source_page"]),
            target_page=int(payload["target_page"]),
            link_type=str(payload["link_type"]),
            schema_similarity=float(payload["schema_similarity"]),
            header_similarity=float(payload["header_similarity"]),
            geometry_evidence=dict(payload.get("geometry_evidence") or {}),
            confidence=float(payload.get("confidence", 1.0)),
            status=str(payload.get("status") or "accepted"),
            reason_codes=tuple(str(item) for item in payload.get("reason_codes") or ()),
        )


@dataclass(frozen=True)
class StructuredTable:
    table_id: str
    document_id: str
    source_sha256: str
    page_numbers: tuple[int, ...]
    source_region_ids: tuple[str, ...]
    table_type: str
    orientation: int
    bbox: AxisAlignedBoundingBox
    coordinate_space_id: str
    transform_chain_id: str | None
    columns: tuple[TableColumn, ...]
    rows: tuple[TableRow, ...]
    cells: tuple[TableCell, ...]
    header_structure: tuple[TableHeader, ...] = ()
    spans: tuple[TableSpan, ...] = ()
    cross_page_links: tuple[str, ...] = ()
    caption_refs: tuple[str, ...] = ()
    footnote_refs: tuple[str, ...] = ()
    confidence: float = 1.0
    status: str = "accepted"
    issues: tuple[TableIssue, ...] = ()
    provenance: dict[str, Any] = field(default_factory=dict)
    input_checksum: str = ""
    created_at: str = field(
        default_factory=lambda: (
            datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")
        )
    )
    table_schema_version: str = TABLE_SCHEMA_VERSION
    engine_version: str = TABLE_ENGINE_VERSION
    strategy_version: str = GRID_STRATEGY_VERSION

    def __post_init__(self) -> None:
        if not self.table_id:
            raise TableSchemaError("structured table requires table_id")
        if not self.document_id:
            raise TableSchemaError("structured table requires document_id")
        if not str(self.table_schema_version).startswith(f"{SUPPORTED_TABLE_MAJOR}."):
            raise TableSchemaError("unsupported structured table schema version")
        if not self.page_numbers or any(page <= 0 for page in self.page_numbers):
            raise TableSchemaError("structured table requires positive page numbers")
        if self.table_type not in TABLE_TYPES:
            raise TableSchemaError(f"unsupported table type: {self.table_type}")
        if not self.coordinate_space_id:
            raise TableSchemaError("structured table requires coordinate_space_id")
        if self.status not in TABLE_STATUSES:
            raise TableSchemaError(f"unsupported table status: {self.status}")
        if not 0.0 <= self.confidence <= 1.0:
            raise TableSchemaError("structured table confidence must be in [0, 1]")
        cell_ids = {cell.cell_id for cell in self.cells}
        if len(cell_ids) != len(self.cells):
            raise TableSchemaError("structured table cell ids must be unique")
        row_ids = {row.row_id for row in self.rows}
        if len(row_ids) != len(self.rows):
            raise TableSchemaError("structured table row ids must be unique")
        column_ids = {column.column_id for column in self.columns}
        if len(column_ids) != len(self.columns):
            raise TableSchemaError("structured table column ids must be unique")

    @property
    def table_checksum(self) -> str:
        payload = self.to_dict(include_checksum=False)
        payload.pop("created_at", None)
        return _sha256_json(payload)

    @property
    def row_count(self) -> int:
        return len(self.rows)

    @property
    def column_count(self) -> int:
        return len(self.columns)

    def to_matrix(self) -> list[list[str]]:
        values = [["" for _ in self.columns] for _ in self.rows]
        for cell in self.cells:
            if cell.row_start < len(values) and cell.column_start < len(self.columns):
                values[cell.row_start][cell.column_start] = cell.raw_text
        return values

    def to_dict(self, *, include_checksum: bool = True) -> dict[str, Any]:
        payload = {
            "table_id": self.table_id,
            "table_schema_version": self.table_schema_version,
            "engine_version": self.engine_version,
            "strategy_version": self.strategy_version,
            "document_id": self.document_id,
            "source_sha256": self.source_sha256,
            "page_numbers": list(self.page_numbers),
            "source_region_ids": list(self.source_region_ids),
            "table_type": self.table_type,
            "orientation": self.orientation,
            "bbox": _bbox_to_dict(self.bbox),
            "coordinate_space_id": self.coordinate_space_id,
            "transform_chain_id": self.transform_chain_id,
            "columns": [column.to_dict() for column in self.columns],
            "rows": [row.to_dict() for row in self.rows],
            "cells": [cell.to_dict() for cell in self.cells],
            "header_structure": [header.to_dict() for header in self.header_structure],
            "spans": [span.to_dict() for span in self.spans],
            "cross_page_links": list(self.cross_page_links),
            "caption_refs": list(self.caption_refs),
            "footnote_refs": list(self.footnote_refs),
            "confidence": self.confidence,
            "status": self.status,
            "issues": [issue.to_dict() for issue in self.issues],
            "provenance": dict(self.provenance),
            "input_checksum": self.input_checksum,
            "created_at": self.created_at,
        }
        if include_checksum:
            payload["table_checksum"] = self.table_checksum
        return payload

    @classmethod
    def from_mapping(cls, value: Mapping[str, Any]) -> StructuredTable:
        payload = dict(value)
        table = cls(
            table_id=str(payload["table_id"]),
            table_schema_version=str(payload.get("table_schema_version") or TABLE_SCHEMA_VERSION),
            engine_version=str(payload.get("engine_version") or TABLE_ENGINE_VERSION),
            strategy_version=str(payload.get("strategy_version") or GRID_STRATEGY_VERSION),
            document_id=str(payload["document_id"]),
            source_sha256=str(payload.get("source_sha256") or ""),
            page_numbers=tuple(int(item) for item in payload.get("page_numbers") or ()),
            source_region_ids=tuple(str(item) for item in payload.get("source_region_ids") or ()),
            table_type=str(payload.get("table_type") or "UNKNOWN_TABLE"),
            orientation=int(payload.get("orientation") or 0),
            bbox=AxisAlignedBoundingBox.from_dict(dict(payload["bbox"])),
            coordinate_space_id=str(payload["coordinate_space_id"]),
            transform_chain_id=(
                str(payload["transform_chain_id"])
                if payload.get("transform_chain_id") is not None
                else None
            ),
            columns=tuple(TableColumn.from_mapping(item) for item in payload.get("columns") or ()),
            rows=tuple(TableRow.from_mapping(item) for item in payload.get("rows") or ()),
            cells=tuple(TableCell.from_mapping(item) for item in payload.get("cells") or ()),
            header_structure=tuple(
                TableHeader.from_mapping(item) for item in payload.get("header_structure") or ()
            ),
            spans=tuple(TableSpan.from_mapping(item) for item in payload.get("spans") or ()),
            cross_page_links=tuple(str(item) for item in payload.get("cross_page_links") or ()),
            caption_refs=tuple(str(item) for item in payload.get("caption_refs") or ()),
            footnote_refs=tuple(str(item) for item in payload.get("footnote_refs") or ()),
            confidence=float(payload.get("confidence", 1.0)),
            status=str(payload.get("status") or "accepted"),
            issues=tuple(TableIssue.from_mapping(item) for item in payload.get("issues") or ()),
            provenance=dict(payload.get("provenance") or {}),
            input_checksum=str(payload.get("input_checksum") or ""),
            created_at=str(payload.get("created_at") or ""),
        )
        checksum = payload.get("table_checksum")
        if checksum is not None and str(checksum) != table.table_checksum:
            raise TableSchemaError("structured table checksum mismatch")
        return table


def normalize_cell_text(value: str) -> str:
    return " ".join(str(value or "").strip().split())


def numeric_candidate(value: str) -> tuple[str | None, float | None, str]:
    raw = normalize_cell_text(value)
    if raw == "":
        return None, None, "blank"
    if raw in {"-", "–", "—"}:
        return raw, None, "hyphen"
    cleaned = raw.replace(",", "").replace(" ", "")
    negative = False
    if cleaned.startswith("(") and cleaned.endswith(")"):
        negative = True
        cleaned = cleaned[1:-1]
    if cleaned.endswith("-") and cleaned[:-1]:
        negative = True
        cleaned = cleaned[:-1]
    if cleaned.startswith("-"):
        negative = True
        cleaned = cleaned[1:]
    try:
        number = float(cleaned)
    except ValueError:
        return None, None, "text"
    return raw, -number if negative else number, "numeric"


def _sha256_json(payload: Any) -> str:
    return hashlib.sha256(
        json.dumps(
            payload,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    ).hexdigest()


def _bbox_to_dict(bbox: AxisAlignedBoundingBox) -> dict[str, Any]:
    return {
        "x_min": float(bbox.x_min),
        "y_min": float(bbox.y_min),
        "x_max": float(bbox.x_max),
        "y_max": float(bbox.y_max),
        "coordinate_space_id": bbox.coordinate_space_id,
    }


def _optional_float(value: Any) -> float | None:
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


__all__ = [
    "CROSS_PAGE_STRATEGY_VERSION",
    "CrossPageTableLink",
    "FINANCIAL_STRATEGY_VERSION",
    "GRID_STRATEGY_VERSION",
    "StructuredTable",
    "SUBSIDIARY_STRATEGY_VERSION",
    "TABLE_ENGINE_VERSION",
    "TABLE_SCHEMA_NAME",
    "TABLE_SCHEMA_VERSION",
    "TABLE_VALIDATOR_VERSION",
    "TOC_STRATEGY_VERSION",
    "TableCell",
    "TableColumn",
    "TableHeader",
    "TableIssue",
    "TableRegionInput",
    "TableRow",
    "TableSchemaError",
    "TableSpan",
    "normalize_cell_text",
    "numeric_candidate",
]
