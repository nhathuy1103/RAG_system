from __future__ import annotations

import logging
from abc import ABC, abstractmethod
from datetime import UTC, datetime
from typing import Any

from app.pipeline.documents.extraction.canonical.geometry import (
    AxisAlignedBoundingBox,
    CoordinateSpace,
    CoordinateSpaceType,
    CoordinateTransform,
)
from app.pipeline.documents.extraction.canonical.ir import (
    CANONICAL_IR_SCHEMA_NAME,
    CANONICAL_IR_SCHEMA_VERSION,
    CanonicalDocument,
    CanonicalElement,
    CanonicalGeometry,
    CanonicalPage,
    CanonicalTable,
    CanonicalTableCell,
)
from app.pipeline.documents.extraction.canonical.validation import (
    CanonicalIRValidationResult,
    validate_canonical_document,
)
from app.pipeline.documents.extraction.documents.models import BoundingBox
from app.pipeline.documents.extraction.parsing.parsers import (
    ParsedDocument,
    ParsedElement,
    ParsedPage,
    ParsedSection,
    ParsedTable,
)

logger = logging.getLogger(__name__)


class CanonicalIRAdapter(ABC):
    @abstractmethod
    def can_handle(self, value: object) -> bool:
        raise NotImplementedError

    @abstractmethod
    def convert(self, value: object, **kwargs: Any) -> CanonicalDocument:
        raise NotImplementedError

    def validate(self, document: CanonicalDocument) -> CanonicalIRValidationResult:
        return validate_canonical_document(document)

    @abstractmethod
    def capabilities(self) -> dict[str, Any]:
        raise NotImplementedError


class LegacyParsedDocumentAdapter(CanonicalIRAdapter):
    def can_handle(self, value: object) -> bool:
        return isinstance(value, ParsedDocument)

    def convert(self, value: object, **kwargs: Any) -> CanonicalDocument:
        if not isinstance(value, ParsedDocument):
            raise TypeError("LegacyParsedDocumentAdapter requires ParsedDocument")
        return legacy_to_v2(value, **kwargs)

    def capabilities(self) -> dict[str, Any]:
        return {
            "input": "ParsedDocument",
            "geometry": "preserves legacy bbox when present",
            "tables": "preserves parsed rows/cells without reconstruction",
            "legacy_projection": True,
        }


class _ParserNameAdapter(LegacyParsedDocumentAdapter):
    adapter_name = "parser-name"
    parser_names: tuple[str, ...] = ()

    def can_handle(self, value: object) -> bool:
        if not isinstance(value, ParsedDocument):
            return False
        return value.parser_name.lower() in self.parser_names

    def capabilities(self) -> dict[str, Any]:
        return {
            **super().capabilities(),
            "adapter": self.adapter_name,
            "parser_names": self.parser_names,
        }


class NativePdfCanonicalIRAdapter(_ParserNameAdapter):
    adapter_name = "native_pdf"
    parser_names = ("pdf",)


class OcrCanonicalIRAdapter(LegacyParsedDocumentAdapter):
    adapter_name = "ocr"

    def can_handle(self, value: object) -> bool:
        if not isinstance(value, ParsedDocument):
            return False
        return value.ocr_used or value.parser_name.lower() in {
            "paddleocr",
            "hybrid_pdf",
        }

    def capabilities(self) -> dict[str, Any]:
        return {
            **super().capabilities(),
            "adapter": self.adapter_name,
            "geometry": "preserves provider bbox, projected bbox, normalized bbox, and transform chain when present",
            "parser_names": ("paddleocr", "hybrid_pdf"),
        }


class DocxCanonicalIRAdapter(_ParserNameAdapter):
    adapter_name = "docx"
    parser_names = ("docx",)


class PptxCanonicalIRAdapter(_ParserNameAdapter):
    adapter_name = "pptx"
    parser_names = ("pptx",)


class SpreadsheetCanonicalIRAdapter(_ParserNameAdapter):
    adapter_name = "spreadsheet"
    parser_names = ("xlsx", "csv")


class TextLikeCanonicalIRAdapter(_ParserNameAdapter):
    adapter_name = "text_like"
    parser_names = ("txt", "markdown", "html")


DEFAULT_CANONICAL_IR_ADAPTERS: tuple[CanonicalIRAdapter, ...] = (
    OcrCanonicalIRAdapter(),
    NativePdfCanonicalIRAdapter(),
    DocxCanonicalIRAdapter(),
    PptxCanonicalIRAdapter(),
    SpreadsheetCanonicalIRAdapter(),
    TextLikeCanonicalIRAdapter(),
    LegacyParsedDocumentAdapter(),
)


def legacy_to_v2(
    parsed: ParsedDocument,
    *,
    document_id: str | None = None,
    source: dict[str, Any] | None = None,
    extraction_attempt_id: str | None = None,
    created_at: str | None = None,
) -> CanonicalDocument:
    pages: list[CanonicalPage] = []
    tables_by_page = _tables_by_page(parsed)
    warnings = list(parsed.warnings)
    if not parsed.pages and parsed.text:
        warnings.append("legacy_projection_materialized_text_page")
    page_values = list(parsed.pages) or [ParsedPage(page_number=1, text=parsed.text)]
    for page in sorted(page_values, key=lambda item: item.page_number):
        page_index = max(int(page.page_number) - 1, 0)
        context = _PageSpaceContext.from_page(page, parsed=parsed)
        page_tables = tuple(
            _table_to_canonical(table, context)
            for table in tables_by_page.get(page.page_number, ())
        )
        table_ids = {table.table_id for table in page_tables}
        # Legacy OCR represents a visual table as both a page element and a
        # ParsedTable. Canonical IR owns the structured representation in tables.
        elements = tuple(
            _element_to_canonical(element, context)
            for element in page.elements
            if not (
                _canonical_element_type(element.block_type) == "table"
                and element.element_id in table_ids
            )
        )
        reading_order = tuple(dict.fromkeys(element.element_id for element in page.elements))
        pages.append(
            CanonicalPage(
                page_index=page_index,
                page_number=page.page_number,
                original_width=context.primary_width,
                original_height=context.primary_height,
                original_unit=context.primary_unit,
                rotation=int(getattr(page, "rotation", 0) or 0),
                coordinate_spaces=context.coordinate_spaces(),
                transforms=context.transforms(),
                elements=elements,
                tables=page_tables,
                reading_order=reading_order,
                page_metadata={
                    **dict(getattr(page, "metadata", {}) or {}),
                    "legacy_page_number": page.page_number,
                    "text_length": len(page.text or ""),
                },
            )
        )
    global_elements = tuple(
        CanonicalElement(
            element_id=table.table_id,
            element_type="table",
            page_index=None,
            text=_table_text(table.rows),
            confidence=table.confidence,
            provenance={
                "source": "legacy_parsed_table",
                "parser_name": parsed.parser_name,
                "parser_version": parsed.parser_version,
            },
            attributes={
                "location": table.location,
                "rows": [list(row) for row in table.rows],
                "columns": table.columns,
                "header": list(table.header),
                "warnings": list(table.warnings),
            },
            source_block_ids=(table.table_id,),
        )
        for table in parsed.tables
        if _page_number_from_location(table.location) is None
    )
    return CanonicalDocument(
        schema_name=CANONICAL_IR_SCHEMA_NAME,
        schema_version=CANONICAL_IR_SCHEMA_VERSION,
        document_id=document_id
        or str(parsed.document_metadata.get("document_id") or "unknown-document"),
        source=dict(source or {}),
        document_metadata=dict(parsed.document_metadata),
        parser_provenance={
            "parser_name": parsed.parser_name,
            "parser_version": parsed.parser_version,
            "ocr_used": parsed.ocr_used,
            "confidence": parsed.confidence,
            "detected_language": parsed.detected_language,
        },
        extraction_provenance={
            "attempt_id": extraction_attempt_id,
            "pipeline": parsed.document_metadata.get("pipeline_selected"),
            "created_from": "legacy_parsed_document",
        },
        pages=tuple(pages),
        global_elements=global_elements,
        warnings=tuple(dict.fromkeys(warnings)),
        created_at=created_at or datetime.now(UTC).isoformat(),
    )


def v2_to_legacy_projection(document: CanonicalDocument) -> ParsedDocument:
    pages: list[ParsedPage] = []
    sections: list[ParsedSection] = []
    tables: list[ParsedTable] = []
    text_parts: list[str] = []
    compatibility_warnings = list(document.warnings)
    for page in sorted(document.pages, key=lambda item: item.page_index):
        elements: list[ParsedElement] = []
        page_text_parts: list[str] = []
        page_elements_by_id = {element.element_id: element for element in page.elements}
        page_tables_by_id = {table.table_id: table for table in page.tables}
        emitted_element_ids: set[str] = set()
        emitted_table_ids: set[str] = set()

        def emit_element(
            element: CanonicalElement,
            *,
            current_page: CanonicalPage = page,
            current_elements: list[ParsedElement] = elements,
            current_page_text_parts: list[str] = page_text_parts,
            current_emitted_ids: set[str] = emitted_element_ids,
        ) -> None:
            if element.element_type == "table":
                return
            text = element.text or ""
            if not text:
                return
            current_page_text_parts.append(text)
            current_elements.append(
                ParsedElement(
                    element_id=element.element_id,
                    block_type=_legacy_block_type(element.element_type),
                    text=text,
                    page_number=current_page.page_number,
                    metadata={
                        **dict(element.attributes),
                        "canonical_ir_schema_version": document.schema_version,
                        "canonical_ir_element_type": element.element_type,
                        "provenance": dict(element.provenance),
                    },
                    bbox=_legacy_bbox(element.geometry.bbox if element.geometry else None),
                    confidence=element.confidence,
                    rotation=current_page.rotation,
                    provenance=dict(element.provenance),
                )
            )
            current_emitted_ids.add(element.element_id)

        def emit_table(
            table: CanonicalTable,
            *,
            current_page: CanonicalPage = page,
            current_elements: list[ParsedElement] = elements,
            current_emitted_ids: set[str] = emitted_table_ids,
        ) -> None:
            parsed_table = _canonical_table_to_parsed(
                table,
                page_number=current_page.page_number,
            )
            tables.append(parsed_table)
            current_elements.append(
                ParsedElement(
                    element_id=table.table_id,
                    block_type="table",
                    text=_table_text(parsed_table.rows),
                    page_number=current_page.page_number,
                    metadata={
                        "location": parsed_table.location,
                        "rows": parsed_table.rows,
                        "canonical_ir_schema_version": document.schema_version,
                    },
                    bbox=_legacy_bbox(table.bbox),
                    confidence=table.confidence,
                )
            )
            current_emitted_ids.add(table.table_id)

        for block_id in page.reading_order:
            if block_id in page_elements_by_id:
                emit_element(page_elements_by_id[block_id])
            elif block_id in page_tables_by_id:
                emit_table(page_tables_by_id[block_id])
        for element in page.elements:
            if element.element_id not in emitted_element_ids:
                emit_element(element)
        for table in page.tables:
            if table.table_id not in emitted_table_ids:
                emit_table(table)
        page_text = "\n".join(page_text_parts)
        text_parts.append(page_text)
        pages.append(
            ParsedPage(
                page_number=page.page_number,
                text=page_text,
                elements=elements,
                metadata={
                    **dict(page.page_metadata),
                    "canonical_ir_schema_version": document.schema_version,
                    "compatibility_projection": "v2_to_legacy",
                },
                width=page.original_width,
                height=page.original_height,
                rotation=page.rotation,
            )
        )
        sections.append(
            ParsedSection(
                text=page_text,
                page_number=page.page_number,
                title=f"Page {page.page_number}",
                block_ids=[element.element_id for element in elements],
            )
        )
    for element in document.global_elements:
        if element.element_type != "table":
            compatibility_warnings.append(f"unmapped_global_element:{element.element_id}")
            continue
        rows = element.attributes.get("rows")
        if not isinstance(rows, list):
            compatibility_warnings.append(f"unmapped_global_table_rows:{element.element_id}")
            continue
        tables.append(
            ParsedTable(
                table_id=element.element_id,
                location=str(element.attributes.get("location") or "document:table"),
                rows=[[str(cell) for cell in row] for row in rows],
                columns=int(element.attributes.get("columns") or 0),
                header=[str(cell) for cell in element.attributes.get("header") or []],
                warnings=[str(item) for item in element.attributes.get("warnings") or []],
                confidence=element.confidence,
                metadata={
                    "canonical_ir_schema_version": document.schema_version,
                    "compatibility_projection": "v2_to_legacy",
                },
            )
        )
    parsed_text = "\n\n".join(part for part in text_parts if part)
    if compatibility_warnings:
        logger.warning(
            "legacy_projection_warning",
            extra={
                "document_id": document.document_id,
                "schema_version": document.schema_version,
                "warning_count": len(compatibility_warnings),
            },
        )
    return ParsedDocument(
        text=parsed_text,
        pages=pages,
        sections=sections,
        tables=tables,
        images_metadata=[],
        document_metadata={
            **dict(document.document_metadata),
            "canonical_ir_schema_name": document.schema_name,
            "canonical_ir_schema_version": document.schema_version,
            "compatibility_projection": "v2_to_legacy",
        },
        warnings=list(dict.fromkeys(compatibility_warnings)),
        parser_name=str(document.parser_provenance.get("parser_name") or "canonical_ir_v2"),
        parser_version=str(
            document.parser_provenance.get("parser_version") or document.schema_version
        ),
        confidence=_optional_float(document.parser_provenance.get("confidence")),
        ocr_used=bool(document.parser_provenance.get("ocr_used", False)),
        detected_language=str(document.parser_provenance.get("detected_language") or "unknown"),
        content_markdown=parsed_text,
    )


class _PageSpaceContext:
    def __init__(
        self,
        *,
        page_index: int,
        primary_width: float | None,
        primary_height: float | None,
        primary_unit: str,
        parser_name: str,
        ocr_used: bool,
        page_metadata: dict[str, Any] | None = None,
    ) -> None:
        self.page_index = page_index
        self.primary_width = primary_width
        self.primary_height = primary_height
        self.primary_unit = primary_unit
        self.parser_name = parser_name
        self.ocr_used = ocr_used
        self.page_metadata = dict(page_metadata or {})
        self.ocr_input_width = _positive_optional_float(self.page_metadata.get("width"))
        self.ocr_input_height = _positive_optional_float(self.page_metadata.get("height"))
        self._rendered_space_id = str(
            self.page_metadata.get("projected_coordinate_space_id")
            or f"page-{self.page_index}-rendered-image"
        )
        self._ocr_space_id = str(
            self.page_metadata.get("input_coordinate_space_id")
            or f"page-{self.page_index}-ocr-input"
        )

    @classmethod
    def from_page(cls, page: ParsedPage, *, parsed: ParsedDocument) -> _PageSpaceContext:
        page_index = max(int(page.page_number) - 1, 0)
        width = _positive_optional_float(getattr(page, "width", None))
        height = _positive_optional_float(getattr(page, "height", None))
        unit = (
            "pixel"
            if parsed.ocr_used or parsed.parser_name.lower() in {"paddleocr", "hybrid_pdf"}
            else "pt"
        )
        return cls(
            page_index=page_index,
            primary_width=width,
            primary_height=height,
            primary_unit=unit,
            parser_name=parsed.parser_name,
            ocr_used=parsed.ocr_used,
            page_metadata=dict(getattr(page, "metadata", {}) or {}),
        )

    @property
    def pdf_space_id(self) -> str:
        return f"page-{self.page_index}-pdf-page"

    @property
    def rendered_space_id(self) -> str:
        return self._rendered_space_id

    @property
    def ocr_space_id(self) -> str:
        return self._ocr_space_id

    @property
    def normalized_space_id(self) -> str:
        return f"page-{self.page_index}-normalized"

    def coordinate_spaces(self) -> tuple[CoordinateSpace, ...]:
        spaces: list[CoordinateSpace] = []
        primary_id = self.primary_space_id_for_unit(self.primary_unit)
        primary_type = self.primary_space_type_for_unit(self.primary_unit)
        spaces.append(self._space(primary_id, primary_type, self.primary_unit))
        if (
            self.ocr_used or self.parser_name.lower() in {"paddleocr", "hybrid_pdf"}
        ) and self.ocr_space_id != primary_id:
            spaces.append(
                CoordinateSpace(
                    space_id=self.ocr_space_id,
                    type=CoordinateSpaceType.OCR_INPUT_SPACE.value,
                    width=self.ocr_input_width or self.primary_width,
                    height=self.ocr_input_height or self.primary_height,
                    unit="pixel",
                    origin="top-left",
                    x_axis_direction="right",
                    y_axis_direction="down",
                    page_index=self.page_index,
                    parent_space_id=self.rendered_space_id,
                    metadata={
                        "parser_name": self.parser_name,
                        "provider_space": True,
                    },
                )
            )
        if self.primary_width is not None and self.primary_height is not None:
            spaces.append(
                CoordinateSpace(
                    space_id=self.normalized_space_id,
                    type=CoordinateSpaceType.NORMALIZED_PAGE_SPACE.value,
                    width=1.0,
                    height=1.0,
                    unit="ratio",
                    origin="top-left",
                    x_axis_direction="right",
                    y_axis_direction="down",
                    page_index=self.page_index,
                    parent_space_id=spaces[0].space_id,
                    metadata={"normalized_from": spaces[0].space_id},
                )
            )
        return tuple(spaces)

    def transforms(self) -> tuple[CoordinateTransform, ...]:
        if self.primary_width is None or self.primary_height is None:
            return ()
        primary = self.primary_space_id_for_unit(self.primary_unit)
        transforms = [
            CoordinateTransform.normalize(
                transform_id=f"{primary}-to-normalized",
                source_space_id=primary,
                target_space_id=self.normalized_space_id,
                source_width=self.primary_width,
                source_height=self.primary_height,
            ),
        ]
        rotation_applied = int(self.page_metadata.get("rotation_applied") or 0)
        if (
            self.ocr_used or self.parser_name.lower() in {"paddleocr", "hybrid_pdf"}
        ) and self.ocr_space_id != primary:
            transforms.insert(
                0,
                CoordinateTransform.rotate_right_angle(
                    transform_id=f"page-{self.page_index + 1}-ocr-rotation-{rotation_applied}",
                    source_space_id=primary,
                    target_space_id=self.ocr_space_id,
                    degrees=rotation_applied,
                    source_width=self.primary_width,
                    source_height=self.primary_height,
                ),
            )
        return tuple(transforms)

    def primary_space_id_for_unit(self, unit: str) -> str:
        normalized = str(unit or self.primary_unit).lower()
        if normalized == "normalized":
            return self.normalized_space_id
        if normalized == "pt":
            return self.pdf_space_id
        return self.rendered_space_id

    def primary_space_type_for_unit(self, unit: str) -> str:
        normalized = str(unit or self.primary_unit).lower()
        if normalized == "normalized":
            return CoordinateSpaceType.NORMALIZED_PAGE_SPACE.value
        if normalized == "pt":
            return CoordinateSpaceType.PDF_PAGE_SPACE.value
        return CoordinateSpaceType.RENDERED_IMAGE_SPACE.value

    def _space(self, space_id: str, space_type: str, unit: str) -> CoordinateSpace:
        return CoordinateSpace(
            space_id=space_id,
            type=space_type,
            width=(1.0 if unit == "normalized" else self.primary_width),
            height=(1.0 if unit == "normalized" else self.primary_height),
            unit=("ratio" if unit == "normalized" else unit),
            origin="top-left",
            x_axis_direction="right",
            y_axis_direction="down",
            page_index=self.page_index,
            metadata={"parser_name": self.parser_name},
        )


def _element_to_canonical(
    element: ParsedElement,
    context: _PageSpaceContext,
) -> CanonicalElement:
    geometry = _element_geometry(
        bbox=getattr(element, "bbox", None),
        metadata=dict(getattr(element, "metadata", {}) or {}),
        context=context,
    )
    return CanonicalElement(
        element_id=element.element_id,
        element_type=_canonical_element_type(element.block_type),
        page_index=context.page_index,
        text=element.text,
        confidence=element.confidence,
        provenance={
            "source": "legacy_parsed_element",
            "source_block_id": element.element_id,
            **dict(getattr(element, "provenance", {}) or {}),
        },
        geometry=geometry,
        attributes=dict(getattr(element, "metadata", {}) or {}),
        source_block_ids=(element.element_id,),
    )


def _element_geometry(
    *,
    bbox: BoundingBox | None,
    metadata: dict[str, Any],
    context: _PageSpaceContext,
) -> CanonicalGeometry | None:
    canonical_bbox = _bbox_from_mapping(metadata.get("projected_bbox"), context)
    if canonical_bbox is None:
        canonical_bbox = _canonical_bbox(bbox, context)
    provider_bbox = _bbox_from_mapping(metadata.get("provider_bbox"), context)
    if provider_bbox is None:
        provider_bbox = _bbox_from_mapping(metadata.get("raw_provider_bbox"), context)
    normalized = _bbox_from_mapping(metadata.get("normalized_bbox"), context)
    if canonical_bbox is not None and context.primary_width and context.primary_height:
        if canonical_bbox.coordinate_space_id == context.normalized_space_id:
            normalized = canonical_bbox
        elif (
            normalized is None
            and canonical_bbox.coordinate_space_id
            == context.primary_space_id_for_unit(context.primary_unit)
        ):
            normalized = AxisAlignedBoundingBox(
                canonical_bbox.x_min / context.primary_width,
                canonical_bbox.y_min / context.primary_height,
                canonical_bbox.x_max / context.primary_width,
                canonical_bbox.y_max / context.primary_height,
                context.normalized_space_id,
            )
    if canonical_bbox is None and provider_bbox is None and normalized is None:
        return None
    return CanonicalGeometry(
        bbox=canonical_bbox,
        normalized_bbox=normalized,
        provider_bbox=provider_bbox,
        transform_chain=_transform_chain_ids(metadata.get("transform_chain")),
    )


def _transform_chain_ids(value: Any) -> tuple[str, ...]:
    if not isinstance(value, (list, tuple)):
        return ()
    ids: list[str] = []
    for item in value:
        if isinstance(item, str):
            transform_id = item
        elif isinstance(item, dict):
            transform_id = str(item.get("transform_id") or "")
        else:
            transform_id = ""
        if transform_id:
            ids.append(transform_id)
    return tuple(ids)


def _table_to_canonical(
    table: ParsedTable,
    context: _PageSpaceContext | None,
) -> CanonicalTable:
    page_index = (
        context.page_index
        if context is not None
        else max((_page_number_from_location(table.location) or 1) - 1, 0)
    )
    cells: list[CanonicalTableCell] = []
    if table.cells:
        for raw_cell in table.cells:
            cell = dict(raw_cell)
            cells.append(
                CanonicalTableCell(
                    row_index=int(cell.get("row_index", cell.get("row", 0)) or 0),
                    column_index=int(cell.get("column_index", cell.get("column", 0)) or 0),
                    text=str(cell.get("text") or ""),
                    bbox=_bbox_from_mapping(cell.get("bbox"), context),
                    row_span=int(cell.get("row_span") or 1),
                    column_span=int(cell.get("column_span") or 1),
                    confidence=_optional_float(cell.get("confidence")),
                    source_element_ids=(table.table_id,),
                    attributes={
                        key: value
                        for key, value in cell.items()
                        if key
                        not in {
                            "row_index",
                            "row",
                            "column_index",
                            "column",
                            "text",
                            "bbox",
                            "row_span",
                            "column_span",
                            "confidence",
                        }
                    },
                )
            )
    else:
        for row_index, row in enumerate(table.rows):
            for column_index, value in enumerate(row):
                cells.append(
                    CanonicalTableCell(
                        row_index=row_index,
                        column_index=column_index,
                        text=value,
                        source_element_ids=(table.table_id,),
                    )
                )
    return CanonicalTable(
        table_id=table.table_id,
        page_index=page_index,
        bbox=_canonical_bbox(table.bbox, context),
        row_count=len(table.rows) if table.rows else None,
        column_count=table.columns if table.columns else None,
        cells=tuple(cells),
        source_element_ids=(table.table_id,),
        confidence=table.confidence,
        attributes={
            "location": table.location,
            "header": list(table.header),
            "rows": [list(row) for row in table.rows],
            "warnings": list(table.warnings),
            **dict(table.metadata),
        },
    )


def _canonical_bbox(
    bbox: BoundingBox | None,
    context: _PageSpaceContext | None,
) -> AxisAlignedBoundingBox | None:
    if bbox is None:
        return None
    if context is None:
        return None
    return AxisAlignedBoundingBox(
        bbox.x0,
        bbox.y0,
        bbox.x1,
        bbox.y1,
        context.primary_space_id_for_unit(bbox.unit),
    )


def _bbox_from_mapping(
    value: Any,
    context: _PageSpaceContext | None,
) -> AxisAlignedBoundingBox | None:
    if not isinstance(value, dict) or context is None:
        return None
    unit = str(value.get("unit") or context.primary_unit)
    try:
        if all(key in value for key in ("x_min", "y_min", "x_max", "y_max")):
            return AxisAlignedBoundingBox(
                float(value["x_min"]),
                float(value["y_min"]),
                float(value["x_max"]),
                float(value["y_max"]),
                str(value.get("coordinate_space_id") or context.primary_space_id_for_unit(unit)),
            )
        if all(key in value for key in ("x0", "y0", "x1", "y1")):
            return AxisAlignedBoundingBox(
                float(value["x0"]),
                float(value["y0"]),
                float(value["x1"]),
                float(value["y1"]),
                str(value.get("coordinate_space_id") or context.primary_space_id_for_unit(unit)),
            )
        if all(key in value for key in ("x", "y", "width", "height")):
            return AxisAlignedBoundingBox(
                float(value["x"]),
                float(value["y"]),
                float(value["x"]) + float(value["width"]),
                float(value["y"]) + float(value["height"]),
                str(value.get("coordinate_space_id") or context.primary_space_id_for_unit(unit)),
            )
    except (TypeError, ValueError):
        return None
    return None


def _legacy_bbox(value: AxisAlignedBoundingBox | None) -> BoundingBox | None:
    if value is None:
        return None
    unit = "normalized" if value.coordinate_space_id.endswith("normalized") else "pixel"
    return BoundingBox.from_corners(
        value.x_min,
        value.y_min,
        value.x_max,
        value.y_max,
        unit=unit,
    )


def _tables_by_page(parsed: ParsedDocument) -> dict[int, list[ParsedTable]]:
    values: dict[int, list[ParsedTable]] = {}
    for table in parsed.tables:
        page_number = _page_number_from_location(table.location)
        if page_number is None:
            continue
        values.setdefault(page_number, []).append(table)
    return values


def _page_number_from_location(location: str | None) -> int | None:
    if not isinstance(location, str):
        return None
    import re

    match = re.search(r"(?:^|:)page:(\d+)(?:$|:)", location)
    if match is None:
        match = re.search(r"(?:^|:)page-(\d+)(?:$|:)", location)
    if match is None:
        return None
    page_number = int(match.group(1))
    return page_number if page_number > 0 else None


def _canonical_element_type(value: str) -> str:
    normalized = str(value or "").lower()
    mapping = {
        "text": "text_block",
        "sentence": "text_span",
        "image": "figure",
        "code": "paragraph",
        "quote": "paragraph",
        "formula": "unknown",
        "horizontal_rule": "unknown",
    }
    direct = {
        "heading",
        "paragraph",
        "list",
        "table",
        "figure",
        "caption",
        "header",
        "footer",
        "page_number",
    }
    if normalized in direct:
        return normalized
    return mapping.get(normalized, "unknown")


def _legacy_block_type(value: str) -> str:
    mapping = {
        "text_block": "paragraph",
        "line": "paragraph",
        "token": "sentence",
        "text_span": "sentence",
        "table_row": "table",
        "table_cell": "table",
        "page_number": "page_number",
    }
    return mapping.get(value, value if value != "unknown" else "paragraph")


def _canonical_table_to_parsed(table: CanonicalTable, *, page_number: int) -> ParsedTable:
    rows = table.attributes.get("rows")
    if not isinstance(rows, list):
        rows = _rows_from_cells(table.cells)
    parsed_rows = [[str(cell) for cell in row] for row in rows]
    return ParsedTable(
        table_id=table.table_id,
        location=str(
            table.attributes.get("location") or f"page:{page_number}:table:{table.table_id}"
        ),
        rows=parsed_rows,
        columns=table.column_count or max((len(row) for row in parsed_rows), default=0),
        header=[
            str(cell)
            for cell in table.attributes.get("header") or (parsed_rows[0] if parsed_rows else [])
        ],
        warnings=[str(item) for item in table.attributes.get("warnings") or []],
        cells=[cell.to_dict() for cell in table.cells],
        bbox=_legacy_bbox(table.bbox),
        confidence=table.confidence,
        metadata={
            "canonical_ir_schema_version": CANONICAL_IR_SCHEMA_VERSION,
            "compatibility_projection": "v2_to_legacy",
        },
    )


def _rows_from_cells(cells: tuple[CanonicalTableCell, ...]) -> list[list[str]]:
    row_count = max((cell.row_index for cell in cells), default=-1) + 1
    column_count = max((cell.column_index for cell in cells), default=-1) + 1
    rows = [["" for _ in range(column_count)] for _ in range(row_count)]
    for cell in cells:
        rows[cell.row_index][cell.column_index] = cell.text
    return rows


def _table_text(rows: list[list[str]]) -> str:
    return "\n".join(" | ".join(str(cell) for cell in row) for row in rows)


def _optional_float(value: Any) -> float | None:
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _positive_optional_float(value: Any) -> float | None:
    parsed = _optional_float(value)
    if parsed is None or parsed <= 0:
        return None
    return parsed
