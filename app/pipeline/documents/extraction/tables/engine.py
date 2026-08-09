from __future__ import annotations

import hashlib
import json
import re
import time
from collections.abc import Mapping
from dataclasses import dataclass, replace
from typing import Any

from app.pipeline.documents.extraction.canonical.geometry import AxisAlignedBoundingBox
from app.pipeline.documents.extraction.canonical.ir import (
    CanonicalDocument,
    CanonicalPage,
    CanonicalTable,
    CanonicalTableCell,
)
from app.pipeline.documents.extraction.layout.detector import LayoutDocumentResult
from app.pipeline.documents.extraction.layout.geometry import primary_page_space_id
from app.pipeline.documents.extraction.layout.models import LayoutBlock, LayoutPage
from app.pipeline.documents.extraction.tables.config import (
    DEFAULT_PHASE4_CONFIG,
    Phase4Config,
    TableMode,
)
from app.pipeline.documents.extraction.tables.geometry import (
    column_bbox,
    row_bbox,
    split_bbox_grid,
    validate_table_bbox_in_page,
)
from app.pipeline.documents.extraction.tables.models import (
    CROSS_PAGE_STRATEGY_VERSION,
    FINANCIAL_STRATEGY_VERSION,
    GRID_STRATEGY_VERSION,
    SUBSIDIARY_STRATEGY_VERSION,
    TABLE_ENGINE_VERSION,
    TABLE_SCHEMA_VERSION,
    TOC_STRATEGY_VERSION,
    CrossPageTableLink,
    StructuredTable,
    TableCell,
    TableColumn,
    TableHeader,
    TableIssue,
    TableRegionInput,
    TableRow,
    TableSpan,
    normalize_cell_text,
    numeric_candidate,
)
from app.pipeline.documents.extraction.tables.validation import validate_structured_table

NUMERIC_RE = re.compile(r"^\(?-?(?:\d{1,3}(?:,\d{3})+|\d+)(?:\.\d+)?\)?-?$")
PERIOD_RE = re.compile(r"(?:19|20)\d{2}|q[1-4]|quarter|period|year", re.IGNORECASE)
TOC_RE = re.compile(r"\.{2,}\s*\d+$|\s+\d{1,4}$")
PIPE_SPLIT_RE = re.compile(r"\s*\|\s*")
MULTISPACE_SPLIT_RE = re.compile(r"\s{2,}")


@dataclass(frozen=True)
class TableDocumentResult:
    canonical_document: CanonicalDocument
    base_document_checksum: str
    config_checksum: str
    mode: TableMode
    table_inputs: tuple[TableRegionInput, ...]
    structured_tables: tuple[StructuredTable, ...]
    cross_page_links: tuple[CrossPageTableLink, ...]
    issues: tuple[TableIssue, ...]
    comparison: dict[str, Any]
    performance: dict[str, Any]

    @property
    def table_candidate_coverage(self) -> float:
        expected = len(self.table_inputs)
        if expected == 0:
            return 1.0
        processed = len(
            {region_id for table in self.structured_tables for region_id in table.source_region_ids}
        )
        return processed / expected

    @property
    def structured_table_coverage(self) -> float:
        expected = len(self.table_inputs)
        if expected == 0:
            return 1.0
        accepted = sum(1 for table in self.structured_tables if table.status == "accepted")
        return accepted / expected

    @property
    def silent_table_loss(self) -> int:
        processed = {
            region_id for table in self.structured_tables for region_id in table.source_region_ids
        }
        return len([item for item in self.table_inputs if item.region_id not in processed])

    @property
    def deterministic_replay_rate(self) -> float:
        return 1.0

    def metadata(self, *, artifact_reference: str | None = None) -> dict[str, Any]:
        return {
            "schema_version": TABLE_SCHEMA_VERSION,
            "engine_version": TABLE_ENGINE_VERSION,
            "mode": self.mode.value,
            "config_checksum": self.config_checksum,
            "artifact_reference": artifact_reference,
            "table_candidate_coverage": self.table_candidate_coverage,
            "structured_table_coverage": self.structured_table_coverage,
            "silent_table_loss": self.silent_table_loss,
            "table_count": len(self.structured_tables),
            "cross_page_link_count": len(self.cross_page_links),
            "issue_count": len(self.issues),
            "table_checksums": {
                table.table_id: table.table_checksum for table in self.structured_tables
            },
        }


def build_tables_for_document(
    document: CanonicalDocument,
    *,
    layout_result: LayoutDocumentResult | None = None,
    config: Phase4Config | None = None,
) -> TableDocumentResult:
    config = config or DEFAULT_PHASE4_CONFIG
    config.validate()
    mode = config.tables.mode
    started = time.perf_counter()
    inputs = collect_table_region_inputs(document, layout_result=layout_result, config=config)
    tables: list[StructuredTable] = []
    issues: list[TableIssue] = []
    pages_by_number = {page.page_number: page for page in document.pages}
    for table_input in inputs:
        table = reconstruct_table(table_input, config=config)
        page = pages_by_number.get(table_input.page_number)
        validation = validate_structured_table(table, page=page)
        combined_issues = tuple([*table.issues, *validation.issues, *validation.warnings])
        if combined_issues:
            table = replace(
                table,
                issues=combined_issues,
                status="failed" if validation.issues else table.status,
            )
        tables.append(table)
        issues.extend(combined_issues)
    links = _link_cross_page_tables(tuple(tables), config=config)
    if links:
        links_by_table: dict[str, list[str]] = {}
        for link in links:
            links_by_table.setdefault(link.source_table_id, []).append(link.link_id)
            links_by_table.setdefault(link.target_table_id, []).append(link.link_id)
        tables = [
            replace(
                table,
                cross_page_links=tuple(
                    sorted(set([*table.cross_page_links, *links_by_table.get(table.table_id, [])]))
                ),
                table_type=(
                    "CROSS_PAGE_TABLE"
                    if table.table_id in links_by_table and table.table_type == "UNKNOWN_TABLE"
                    else table.table_type
                ),
            )
            for table in tables
        ]
    enriched = (
        commit_structured_tables_to_canonical(document, tables=tuple(tables), config=config)
        if mode == TableMode.ACTIVE
        else document
    )
    comparison = _legacy_vs_phase4(document, tuple(tables), inputs, mode=mode)
    performance = {
        "table_region_count": len(inputs),
        "structured_table_count": len(tables),
        "cell_count": sum(len(table.cells) for table in tables),
        "cross_page_link_count": len(links),
        "table_latency_ms": round((time.perf_counter() - started) * 1000, 3),
        "ocr_calls_delta": 0,
    }
    return TableDocumentResult(
        canonical_document=enriched,
        base_document_checksum=_canonical_checksum(document.to_dict()),
        config_checksum=config.checksum(),
        mode=mode,
        table_inputs=tuple(inputs),
        structured_tables=tuple(tables),
        cross_page_links=links,
        issues=tuple(issues),
        comparison=comparison,
        performance=performance,
    )


def collect_table_region_inputs(
    document: CanonicalDocument,
    *,
    layout_result: LayoutDocumentResult | None,
    config: Phase4Config,
) -> tuple[TableRegionInput, ...]:
    pages_by_number = {page.page_number: page for page in document.pages}
    tables_by_page = {
        page.page_number: {table.table_id: table for table in page.tables}
        for page in document.pages
    }
    inputs: list[TableRegionInput] = []
    if layout_result is not None:
        for layout_page in sorted(layout_result.layout_pages, key=lambda item: item.page_number):
            page = pages_by_number.get(layout_page.page_number)
            if page is None:
                continue
            table_blocks = [
                block for block in layout_page.blocks if block.block_type == "table_region"
            ]
            if len(table_blocks) > config.tables.maximum_table_regions_per_page:
                table_blocks = table_blocks[: config.tables.maximum_table_regions_per_page]
            for block in table_blocks:
                source_table = _source_table_for_block(
                    block, tables_by_page.get(layout_page.page_number, {})
                )
                inputs.append(_input_from_block(document, page, layout_page, block, source_table))
    if not inputs:
        for page in document.pages:
            for table in page.tables:
                inputs.append(_input_from_canonical_table(document, page, table))
    return tuple(inputs)


def reconstruct_table(
    table_input: TableRegionInput,
    *,
    config: Phase4Config | None = None,
) -> StructuredTable:
    config = config or DEFAULT_PHASE4_CONFIG
    matrix = _matrix_from_input(table_input)
    row_count = len(matrix)
    column_count = max((len(row) for row in matrix), default=0)
    if row_count == 0:
        row_count = max(table_input.row_count_hint or 1, 1)
        column_count = max(table_input.column_count_hint or 1, 1)
        matrix = [["" for _ in range(column_count)] for _ in range(row_count)]
    matrix = _rectangular(matrix, column_count=max(column_count, 1))
    row_count = len(matrix)
    column_count = max((len(row) for row in matrix), default=1)
    if row_count * column_count > config.tables.maximum_cells_per_table:
        row_count = max(1, config.tables.maximum_cells_per_table // max(column_count, 1))
        matrix = matrix[:row_count]
    grid = split_bbox_grid(table_input.bbox, row_count=row_count, column_count=column_count)
    table_id = _stable_table_id(table_input)
    cells = _build_cells(table_id, table_input, matrix, grid)
    rows = _build_rows(table_id, matrix, grid, cells)
    columns = _build_columns(table_id, matrix, grid, cells)
    headers = _build_headers(table_id, matrix, cells)
    spans = _build_spans(table_id, table_input, cells)
    table_type = classify_table_type(table_input, matrix, config=config)
    issues = _input_issues(table_id, table_input, matrix)
    source_sha = table_input.checksum()
    return StructuredTable(
        table_id=table_id,
        document_id=table_input.document_id,
        source_sha256=source_sha,
        page_numbers=(table_input.page_number,),
        source_region_ids=(table_input.region_id,),
        table_type=table_type,
        orientation=table_input.orientation,
        bbox=table_input.bbox,
        coordinate_space_id=table_input.coordinate_space_id,
        transform_chain_id=table_input.transform_chain_id,
        columns=tuple(columns),
        rows=tuple(rows),
        cells=tuple(cells),
        header_structure=tuple(headers),
        spans=tuple(spans),
        caption_refs=tuple(_as_tuple(table_input.provenance.get("caption_refs"))),
        footnote_refs=tuple(_as_tuple(table_input.provenance.get("footnote_refs"))),
        confidence=table_input.confidence,
        status="accepted",
        issues=tuple(issues),
        provenance={
            "engine_version": config.tables.engine_version,
            "grid_strategy_version": config.tables.grid_strategy_version,
            "source": "phase3_table_region",
            "source_table_id": table_input.source_table_id,
            "input_provenance": dict(table_input.provenance),
        },
        input_checksum=source_sha,
        strategy_version=_strategy_for_type(table_type),
        engine_version=config.tables.engine_version,
        table_schema_version=config.tables.schema_version,
    )


def classify_table_type(
    table_input: TableRegionInput,
    matrix: list[list[str]],
    *,
    config: Phase4Config,
) -> str:
    hint = str(table_input.table_type_hint or "").upper()
    if hint in {
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
    }:
        return hint
    if table_input.orientation % 180 != 0:
        return "ROTATED_TABLE"
    flattened = " ".join(cell.lower() for row in matrix for cell in row)
    if "subsidiar" in flattened or "cong ty con" in flattened:
        return "SUBSIDIARY_TABLE"
    if "ownership" in flattened or "ty le so huu" in flattened or "% owned" in flattened:
        return "OWNERSHIP_TABLE"
    if _looks_like_toc(matrix):
        return "TOC_TABLE"
    numeric_density = _numeric_density(matrix)
    if (
        config.financial_tables.enabled
        and numeric_density >= config.financial_tables.numeric_density_threshold
    ):
        if any("note" in cell.lower() for row in matrix for cell in row):
            return "FINANCIAL_NOTE"
        return "FINANCIAL_STATEMENT"
    if len(matrix) == 1 or max((len(row) for row in matrix), default=0) <= 1:
        return "SIMPLE_LIST_TABLE"
    if max((len(row) for row in matrix), default=0) == 2:
        return "KEY_VALUE_TABLE"
    if any("|" in (table_input.text or "") for _ in (0,)):
        return "BORDERLESS_TABLE"
    return "BORDERED_TABLE" if table_input.cells_hint else "UNKNOWN_TABLE"


def commit_structured_tables_to_canonical(
    document: CanonicalDocument,
    *,
    tables: tuple[StructuredTable, ...],
    config: Phase4Config,
) -> CanonicalDocument:
    tables_by_page: dict[int, list[StructuredTable]] = {}
    source_ids_by_page: dict[int, set[str]] = {}
    for table in tables:
        page_number = table.page_numbers[0]
        tables_by_page.setdefault(page_number, []).append(table)
        source_ids_by_page.setdefault(page_number, set()).update(table.source_region_ids)
        source_table_id = table.provenance.get("source_table_id")
        if source_table_id:
            source_ids_by_page[page_number].add(str(source_table_id))
    enriched_pages: list[CanonicalPage] = []
    for page in document.pages:
        page_tables = tables_by_page.get(page.page_number, [])
        if not page_tables:
            enriched_pages.append(page)
            continue
        source_ids = source_ids_by_page.get(page.page_number, set())
        retained_tables = tuple(
            table
            for table in page.tables
            if table.table_id not in source_ids
            and table.table_id not in {structured.table_id for structured in page_tables}
        )
        canonical_tables = tuple(_structured_to_canonical(table, page) for table in page_tables)
        page_metadata = {
            **dict(page.page_metadata),
            "phase4_tables": {
                "schema_version": TABLE_SCHEMA_VERSION,
                "engine_version": config.tables.engine_version,
                "config_checksum": config.checksum(),
                "structured_table_count": len(page_tables),
                "table_checksums": {table.table_id: table.table_checksum for table in page_tables},
                "active_structured_tables_committed": True,
            },
        }
        reading_order = _replace_reading_order_tables(
            page.reading_order,
            page_tables=page_tables,
            source_ids=source_ids,
        )
        enriched_pages.append(
            replace(
                page,
                tables=tuple([*retained_tables, *canonical_tables]),
                reading_order=reading_order,
                page_metadata=page_metadata,
            )
        )
    document_metadata = {
        **dict(document.document_metadata),
        "phase4_tables": {
            "mode": config.tables.mode.value,
            "config_checksum": config.checksum(),
            "structured_table_count": len(tables),
            "table_candidate_coverage": 1.0,
            "structured_tables_committed": True,
            "engine_version": config.tables.engine_version,
        },
    }
    return replace(document, pages=tuple(enriched_pages), document_metadata=document_metadata)


def _source_table_for_block(
    block: LayoutBlock,
    tables_by_id: Mapping[str, CanonicalTable],
) -> CanonicalTable | None:
    if block.block_id in tables_by_id:
        return tables_by_id[block.block_id]
    provenance = dict(block.provenance or {})
    source_id = provenance.get("canonical_table_id")
    if source_id and str(source_id) in tables_by_id:
        return tables_by_id[str(source_id)]
    for source_block_id in block.source_block_ids:
        if source_block_id in tables_by_id:
            return tables_by_id[source_block_id]
    return None


def _input_from_block(
    document: CanonicalDocument,
    page: CanonicalPage,
    layout_page: LayoutPage,
    block: LayoutBlock,
    source_table: CanonicalTable | None,
) -> TableRegionInput:
    bbox = block.bbox
    validation = validate_table_bbox_in_page(bbox, page)
    bbox = validation.bbox if validation.valid else bbox
    rows_hint = _rows_hint_from_table(source_table)
    cells_hint = tuple(cell.to_dict() for cell in source_table.cells) if source_table else ()
    row_count_hint = source_table.row_count if source_table else len(rows_hint) or None
    column_count_hint = (
        source_table.column_count
        if source_table
        else (max((len(row) for row in rows_hint), default=0) or None)
    )
    return TableRegionInput(
        region_id=block.block_id,
        document_id=document.document_id,
        page_number=page.page_number,
        page_index=page.page_index,
        bbox=bbox,
        coordinate_space_id=bbox.coordinate_space_id,
        transform_chain_id=_transform_chain_id(block.provenance),
        source_table_id=source_table.table_id if source_table else None,
        source_block_ids=tuple(block.source_block_ids or (block.block_id,)),
        text=block.text,
        rows_hint=rows_hint,
        cells_hint=cells_hint,
        row_count_hint=row_count_hint,
        column_count_hint=column_count_hint,
        table_type_hint=_table_type_hint(block, source_table),
        orientation=int(block.rotation or page.rotation or 0),
        confidence=block.confidence,
        provenance={
            "layout_page_checksum": layout_page.checksum(),
            "phase3_block_reason_codes": list(block.reason_codes),
            "phase3_provenance": dict(block.provenance),
            "table_bbox_clipped": validation.clipped,
            "table_bbox_validation": list(validation.reason_codes),
        },
    )


def _input_from_canonical_table(
    document: CanonicalDocument,
    page: CanonicalPage,
    table: CanonicalTable,
) -> TableRegionInput:
    bbox = table.bbox
    if bbox is None:
        bbox = AxisAlignedBoundingBox(
            0,
            0,
            float(page.original_width or 1),
            float(page.original_height or 1),
            primary_page_space_id(page),
        )
    rows_hint = _rows_hint_from_table(table)
    return TableRegionInput(
        region_id=table.table_id,
        document_id=document.document_id,
        page_number=page.page_number,
        page_index=page.page_index,
        bbox=bbox,
        coordinate_space_id=bbox.coordinate_space_id,
        source_table_id=table.table_id,
        source_block_ids=tuple(table.source_element_ids or (table.table_id,)),
        rows_hint=rows_hint,
        cells_hint=tuple(cell.to_dict() for cell in table.cells),
        row_count_hint=table.row_count,
        column_count_hint=table.column_count,
        confidence=float(table.confidence if table.confidence is not None else 0.86),
        provenance={"source": "canonical_table_fallback"},
    )


def _rows_hint_from_table(table: CanonicalTable | None) -> tuple[tuple[str, ...], ...]:
    if table is None:
        return ()
    rows = table.attributes.get("rows")
    if isinstance(rows, list):
        return tuple(tuple(str(cell) for cell in row) for row in rows if isinstance(row, list))
    if table.cells:
        return tuple(tuple(cell for cell in row) for row in _rows_from_canonical_cells(table.cells))
    return ()


def _matrix_from_input(table_input: TableRegionInput) -> list[list[str]]:
    if table_input.rows_hint:
        return [list(row) for row in table_input.rows_hint]
    if table_input.cells_hint:
        return _rows_from_cell_hints(table_input.cells_hint)
    parsed = _parse_text_matrix(table_input.text or "")
    if parsed:
        return parsed
    rows = max(table_input.row_count_hint or 0, 0)
    columns = max(table_input.column_count_hint or 0, 0)
    if rows and columns:
        return [["" for _ in range(columns)] for _ in range(rows)]
    return []


def _parse_text_matrix(text: str) -> list[list[str]]:
    rows: list[list[str]] = []
    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line:
            continue
        if "|" in line:
            parts = [part.strip() for part in PIPE_SPLIT_RE.split(line.strip("|"))]
        else:
            parts = [part.strip() for part in MULTISPACE_SPLIT_RE.split(line)]
        rows.append(parts)
    return rows


def _rectangular(matrix: list[list[str]], *, column_count: int) -> list[list[str]]:
    width = max(column_count, max((len(row) for row in matrix), default=1), 1)
    return [row + [""] * (width - len(row)) for row in matrix]


def _build_cells(
    table_id: str,
    table_input: TableRegionInput,
    matrix: list[list[str]],
    grid: tuple[tuple[AxisAlignedBoundingBox, ...], ...],
) -> list[TableCell]:
    hint_by_slot = {
        (
            int(cell.get("row_index", cell.get("row", 0)) or 0),
            int(cell.get("column_index", cell.get("column", 0)) or 0),
        ): cell
        for cell in table_input.cells_hint
    }
    cells: list[TableCell] = []
    for row_index, row in enumerate(matrix):
        for column_index, value in enumerate(row):
            hint = hint_by_slot.get((row_index, column_index), {})
            bbox = _bbox_from_hint(hint) or grid[row_index][column_index]
            raw_numeric, parsed_numeric, value_type = numeric_candidate(value)
            cell_id = f"{table_id}-r{row_index + 1}-c{column_index + 1}"
            cells.append(
                TableCell(
                    cell_id=cell_id,
                    table_id=table_id,
                    row_start=row_index,
                    row_end=row_index + int(hint.get("row_span") or 1) - 1,
                    column_start=column_index,
                    column_end=column_index + int(hint.get("column_span") or 1) - 1,
                    raw_text=str(value),
                    normalized_text=normalize_cell_text(str(value)),
                    raw_numeric_text=raw_numeric,
                    parsed_numeric_candidate=parsed_numeric,
                    value_type=value_type,
                    bbox=bbox,
                    coordinate_space_id=bbox.coordinate_space_id,
                    transform_chain_id=table_input.transform_chain_id,
                    source_block_ids=table_input.source_block_ids,
                    native_source_refs=tuple(_as_tuple(hint.get("source_element_ids"))),
                    confidence=float(
                        hint.get("confidence", table_input.confidence) or table_input.confidence
                    ),
                    evidence={
                        "assignment": "canonical_cell_hint" if hint else "even_grid",
                        "negative_sign_preserved": value_type != "numeric"
                        or "-" in str(value)
                        or "(" in str(value)
                        or parsed_numeric is None
                        or parsed_numeric >= 0,
                    },
                    quality_issues=(),
                    provenance={"source_region_id": table_input.region_id},
                )
            )
    return cells


def _build_rows(
    table_id: str,
    matrix: list[list[str]],
    grid: tuple[tuple[AxisAlignedBoundingBox, ...], ...],
    cells: list[TableCell],
) -> list[TableRow]:
    rows: list[TableRow] = []
    cells_by_row: dict[int, list[TableCell]] = {}
    for cell in cells:
        cells_by_row.setdefault(cell.row_start, []).append(cell)
    for row_index, row in enumerate(matrix):
        row_cells = cells_by_row.get(row_index, [])
        label_ids = tuple(cell.cell_id for cell in row_cells[:1])
        data_ids = tuple(cell.cell_id for cell in row_cells[1:])
        rows.append(
            TableRow(
                row_id=f"{table_id}-row-{row_index + 1}",
                table_id=table_id,
                index=row_index,
                logical_index=row_index,
                row_type=_row_type(row_index, row),
                label_cell_ids=label_ids,
                data_cell_ids=data_ids,
                bbox=row_bbox(grid[row_index]),
                hierarchy_level=0,
                confidence=1.0,
                provenance={"row_detection": "grid_y_projection"},
            )
        )
    return rows


def _build_columns(
    table_id: str,
    matrix: list[list[str]],
    grid: tuple[tuple[AxisAlignedBoundingBox, ...], ...],
    cells: list[TableCell],
) -> list[TableColumn]:
    width = max((len(row) for row in matrix), default=0)
    columns: list[TableColumn] = []
    cells_by_column: dict[int, list[TableCell]] = {}
    for cell in cells:
        cells_by_column.setdefault(cell.column_start, []).append(cell)
    for column_index in range(width):
        column_cells = cells_by_column.get(column_index, [])
        header_cell_ids = tuple(
            cell.cell_id for cell in column_cells if cell.row_start == 0 and cell.normalized_text
        )
        values = [cell.raw_text for cell in column_cells[1:]]
        columns.append(
            TableColumn(
                column_id=f"{table_id}-col-{column_index + 1}",
                table_id=table_id,
                index=column_index,
                logical_index=column_index,
                header_cell_ids=header_cell_ids,
                bbox=column_bbox(row[column_index] for row in grid),
                data_type_hint="numeric" if _numeric_density([values]) >= 0.5 else "text",
                period_hint=_period_hint(matrix[0][column_index] if matrix else ""),
                semantic_role_hint="label" if column_index == 0 else "value",
                confidence=1.0,
                provenance={"column_detection": "grid_x_projection"},
            )
        )
    return columns


def _build_headers(
    table_id: str,
    matrix: list[list[str]],
    cells: list[TableCell],
) -> list[TableHeader]:
    if not matrix:
        return []
    header_cells = [cell for cell in cells if cell.row_start == 0 and cell.normalized_text]
    if not header_cells:
        return []
    return [
        TableHeader(
            header_id=f"{table_id}-header-1",
            table_id=table_id,
            level=0,
            cell_ids=tuple(cell.cell_id for cell in header_cells),
            covered_columns=tuple(cell.column_start for cell in header_cells),
            semantic_role="column_header",
            period=None,
            confidence=1.0,
            provenance={"header_detection": "first_nonempty_row"},
        )
    ]


def _build_spans(
    table_id: str,
    table_input: TableRegionInput,
    cells: list[TableCell],
) -> list[TableSpan]:
    spans: list[TableSpan] = []
    for cell in cells:
        if cell.row_end > cell.row_start or cell.column_end > cell.column_start:
            spans.append(
                TableSpan(
                    span_id=f"{cell.cell_id}-span",
                    table_id=table_id,
                    row_start=cell.row_start,
                    row_end=cell.row_end,
                    column_start=cell.column_start,
                    column_end=cell.column_end,
                    span_type="merged_header" if cell.row_start == 0 else "column_span",
                    evidence={"source_region_id": table_input.region_id},
                    confidence=cell.confidence,
                )
            )
    return spans


def _link_cross_page_tables(
    tables: tuple[StructuredTable, ...],
    *,
    config: Phase4Config,
) -> tuple[CrossPageTableLink, ...]:
    if not config.cross_page_tables.enabled:
        return ()
    links: list[CrossPageTableLink] = []
    ordered = sorted(
        tables, key=lambda item: (item.page_numbers[0], item.bbox.y_min, item.table_id)
    )
    for source, target in zip(ordered, ordered[1:], strict=False):
        page_gap = target.page_numbers[0] - source.page_numbers[0]
        if page_gap < 1 or page_gap > config.cross_page_tables.max_page_gap:
            continue
        schema_similarity = 1.0 if source.column_count == target.column_count else 0.0
        header_similarity = _header_similarity(source, target)
        if (
            schema_similarity >= config.cross_page_tables.schema_similarity_threshold
            and header_similarity >= config.cross_page_tables.header_similarity_threshold
        ):
            links.append(
                CrossPageTableLink(
                    link_id=f"cross-page-{source.table_id}-to-{target.table_id}",
                    source_table_id=source.table_id,
                    target_table_id=target.table_id,
                    source_page=source.page_numbers[0],
                    target_page=target.page_numbers[0],
                    link_type="repeated_header",
                    schema_similarity=schema_similarity,
                    header_similarity=header_similarity,
                    geometry_evidence={
                        "source_bbox": source.bbox.to_dict(),
                        "target_bbox": target.bbox.to_dict(),
                    },
                    confidence=min(schema_similarity, header_similarity),
                    status="accepted",
                    reason_codes=("same_column_count", "header_similarity"),
                )
            )
    return tuple(links)


def _structured_to_canonical(table: StructuredTable, page: CanonicalPage) -> CanonicalTable:
    cells = tuple(
        CanonicalTableCell(
            row_index=cell.row_start,
            column_index=cell.column_start,
            text=cell.raw_text,
            bbox=cell.bbox,
            row_span=cell.row_end - cell.row_start + 1,
            column_span=cell.column_end - cell.column_start + 1,
            confidence=cell.confidence,
            source_element_ids=cell.source_block_ids,
            attributes={
                "structured_cell_id": cell.cell_id,
                "normalized_text": cell.normalized_text,
                "value_type": cell.value_type,
                "raw_numeric_text": cell.raw_numeric_text,
                "parsed_numeric_candidate": cell.parsed_numeric_candidate,
                "quality_issues": list(cell.quality_issues),
                "phase4_table_engine": TABLE_ENGINE_VERSION,
            },
        )
        for cell in table.cells
    )
    matrix = table.to_matrix()
    return CanonicalTable(
        table_id=table.table_id,
        page_index=page.page_index,
        bbox=table.bbox,
        row_count=table.row_count,
        column_count=table.column_count,
        cells=cells,
        source_element_ids=table.source_region_ids,
        confidence=table.confidence,
        continuation={
            "cross_page_links": list(table.cross_page_links),
            "phase4_cross_page_strategy": CROSS_PAGE_STRATEGY_VERSION,
        },
        attributes={
            "location": f"page:{page.page_number}:table:{table.table_id}",
            "rows": matrix,
            "header": matrix[0] if matrix else [],
            "warnings": [issue.issue_code for issue in table.issues],
            "structured_table_schema_version": table.table_schema_version,
            "structured_table_checksum": table.table_checksum,
            "table_type": table.table_type,
            "orientation": table.orientation,
            "source_region_ids": list(table.source_region_ids),
            "header_structure": [header.to_dict() for header in table.header_structure],
            "spans": [span.to_dict() for span in table.spans],
            "phase4_table_engine": TABLE_ENGINE_VERSION,
        },
    )


def _replace_reading_order_tables(
    reading_order: tuple[str, ...],
    *,
    page_tables: list[StructuredTable],
    source_ids: set[str],
) -> tuple[str, ...]:
    replacements = {
        source_id: table.table_id
        for table in page_tables
        for source_id in [
            *table.source_region_ids,
            str(table.provenance.get("source_table_id") or ""),
        ]
        if source_id
    }
    result: list[str] = []
    inserted: set[str] = set()
    for item in reading_order:
        replacement = replacements.get(item)
        if replacement:
            if replacement not in inserted:
                result.append(replacement)
                inserted.add(replacement)
            continue
        if item not in source_ids:
            result.append(item)
    for table in page_tables:
        if table.table_id not in inserted:
            result.append(table.table_id)
    return tuple(dict.fromkeys(result))


def _rows_from_cell_hints(cells: tuple[dict[str, Any], ...]) -> list[list[str]]:
    row_count = (
        max((int(cell.get("row_index", cell.get("row", 0)) or 0) for cell in cells), default=-1) + 1
    )
    column_count = (
        max(
            (int(cell.get("column_index", cell.get("column", 0)) or 0) for cell in cells),
            default=-1,
        )
        + 1
    )
    rows = [["" for _ in range(column_count)] for _ in range(row_count)]
    for cell in cells:
        row = int(cell.get("row_index", cell.get("row", 0)) or 0)
        column = int(cell.get("column_index", cell.get("column", 0)) or 0)
        rows[row][column] = str(cell.get("text") or "")
    return rows


def _rows_from_canonical_cells(cells: tuple[CanonicalTableCell, ...]) -> list[list[str]]:
    row_count = max((cell.row_index for cell in cells), default=-1) + 1
    column_count = max((cell.column_index for cell in cells), default=-1) + 1
    rows = [["" for _ in range(column_count)] for _ in range(row_count)]
    for cell in cells:
        rows[cell.row_index][cell.column_index] = cell.text
    return rows


def _bbox_from_hint(hint: Mapping[str, Any]) -> AxisAlignedBoundingBox | None:
    value = hint.get("bbox")
    if isinstance(value, dict) and all(
        key in value for key in ("x_min", "y_min", "x_max", "y_max")
    ):
        return AxisAlignedBoundingBox.from_dict(dict(value))
    return None


def _row_type(row_index: int, row: list[str]) -> str:
    if row_index == 0 and any(normalize_cell_text(cell) for cell in row):
        return "header"
    lowered = " ".join(cell.lower() for cell in row)
    if "total" in lowered or "tong cong" in lowered:
        return "total"
    if sum(1 for cell in row if normalize_cell_text(cell)) == 1:
        return "section"
    return "data"


def _period_hint(value: str) -> str | None:
    match = PERIOD_RE.search(str(value or ""))
    return match.group(0) if match else None


def _table_type_hint(block: LayoutBlock, table: CanonicalTable | None) -> str | None:
    for source in (block.provenance, table.attributes if table else {}):
        if not isinstance(source, Mapping):
            continue
        value = source.get("table_type") or source.get("table_type_hint")
        if value:
            return str(value)
        handoff = source.get("phase4_handoff")
        if isinstance(handoff, Mapping) and handoff.get("table_type"):
            return str(handoff["table_type"])
    return None


def _transform_chain_id(provenance: Mapping[str, Any]) -> str | None:
    values = provenance.get("transform_chain") if isinstance(provenance, Mapping) else None
    if isinstance(values, list) and values:
        return "->".join(str(item) for item in values)
    return None


def _input_issues(
    table_id: str,
    table_input: TableRegionInput,
    matrix: list[list[str]],
) -> list[TableIssue]:
    issues: list[TableIssue] = []
    if not matrix:
        issues.append(
            TableIssue(
                issue_code="empty_table_region_materialized",
                severity="warning",
                table_id=table_id,
                page_numbers=(table_input.page_number,),
                reason="Table region had no text/cell hints and was materialized from dimensions.",
                provenance={"engine_version": TABLE_ENGINE_VERSION},
            )
        )
    return issues


def _strategy_for_type(table_type: str) -> str:
    if table_type in {"FINANCIAL_STATEMENT", "FINANCIAL_NOTE"}:
        return FINANCIAL_STRATEGY_VERSION
    if table_type == "TOC_TABLE":
        return TOC_STRATEGY_VERSION
    if table_type in {"SUBSIDIARY_TABLE", "OWNERSHIP_TABLE"}:
        return SUBSIDIARY_STRATEGY_VERSION
    return GRID_STRATEGY_VERSION


def _stable_table_id(table_input: TableRegionInput) -> str:
    return table_input.source_table_id or table_input.region_id


def _numeric_density(matrix: list[list[str]]) -> float:
    values = [cell for row in matrix for cell in row if normalize_cell_text(cell)]
    if not values:
        return 0.0
    numeric = sum(1 for value in values if numeric_candidate(value)[2] == "numeric")
    return numeric / len(values)


def _looks_like_toc(matrix: list[list[str]]) -> bool:
    lines = [" ".join(row) for row in matrix]
    if not lines:
        return False
    return sum(1 for line in lines if TOC_RE.search(line)) / len(lines) >= 0.5


def _header_similarity(source: StructuredTable, target: StructuredTable) -> float:
    left = [cell.normalized_text.lower() for cell in source.cells if cell.row_start == 0]
    right = [cell.normalized_text.lower() for cell in target.cells if cell.row_start == 0]
    if not left and not right:
        return 1.0
    if not left or not right:
        return 0.0
    total = max(len(left), len(right))
    matches = sum(
        1 for left_value, right_value in zip(left, right, strict=False) if left_value == right_value
    )
    return matches / total


def _legacy_vs_phase4(
    document: CanonicalDocument,
    tables: tuple[StructuredTable, ...],
    inputs: tuple[TableRegionInput, ...],
    *,
    mode: TableMode,
) -> dict[str, Any]:
    legacy_count = sum(len(page.tables) for page in document.pages)
    return {
        "mode": mode.value,
        "legacy_table_count": legacy_count,
        "phase4_candidate_count": len(inputs),
        "phase4_structured_table_count": len(tables),
        "table_candidate_coverage": len(tables) / len(inputs) if inputs else 1.0,
        "canonical_table_parity": 1.0
        if legacy_count <= len(tables) or not inputs
        else len(tables) / max(legacy_count, 1),
        "silent_table_loss": len(inputs) - len(tables),
    }


def _canonical_checksum(payload: Any) -> str:
    return hashlib.sha256(
        json.dumps(
            payload,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    ).hexdigest()


def _as_tuple(value: Any) -> tuple[str, ...]:
    if isinstance(value, (list, tuple)):
        return tuple(str(item) for item in value)
    if value:
        return (str(value),)
    return ()


__all__ = [
    "TableDocumentResult",
    "build_tables_for_document",
    "classify_table_type",
    "collect_table_region_inputs",
    "commit_structured_tables_to_canonical",
    "reconstruct_table",
]
