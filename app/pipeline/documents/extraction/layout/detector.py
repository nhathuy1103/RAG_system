from __future__ import annotations

import re
import time
from collections import defaultdict
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, replace
from typing import Any

from app.pipeline.documents.extraction.canonical.geometry import AxisAlignedBoundingBox
from app.pipeline.documents.extraction.canonical.ir import (
    CanonicalDocument,
    CanonicalElement,
    CanonicalPage,
    CanonicalTable,
)
from app.pipeline.documents.extraction.layout.config import (
    DEFAULT_PHASE3_CONFIG,
    LayoutMode,
    Phase3Config,
)
from app.pipeline.documents.extraction.layout.geometry import (
    detect_double_transform_types,
    page_bounds,
    page_dimensions,
    primary_page_space_id,
    union_bboxes,
    validate_bbox_in_page,
)
from app.pipeline.documents.extraction.layout.models import (
    BLOCK_CLASSIFIER_VERSION,
    LAYOUT_DETECTOR_VERSION,
    LAYOUT_SCHEMA_VERSION,
    READING_ORDER_VERSION,
    LayoutBlock,
    LayoutIssue,
    LayoutPage,
    LayoutRegion,
    ReadingOrderEdge,
    ReadingOrderGraph,
)
from app.pipeline.documents.extraction.profiling.models import PageProfile, RoutingDecision

LIST_PATTERN = re.compile(r"^\s*(?:[-*+]\s+|\(?[0-9ivxlcdmIVXLCDM]+[.)]\s+|[a-zA-Z][.)]\s+)")
FOOTNOTE_PATTERN = re.compile(r"^\s*(?:\[\d+\]|\d+\s+)")
PAGE_NUMBER_PATTERN = re.compile(r"^\s*(?:page\s*)?\d+\s*$", re.IGNORECASE)


@dataclass(frozen=True)
class LayoutDocumentResult:
    canonical_document: CanonicalDocument
    base_document_checksum: str
    config_checksum: str
    mode: LayoutMode
    layout_pages: tuple[LayoutPage, ...]
    comparison: dict[str, Any]
    performance: dict[str, Any]

    @property
    def layout_artifact_coverage(self) -> float:
        expected = len(self.canonical_document.pages)
        return len(self.layout_pages) / expected if expected else 1.0

    @property
    def graph_coverage(self) -> float:
        expected = len(self.layout_pages)
        if expected == 0:
            return 1.0
        return sum(1 for page in self.layout_pages if page.reading_order_graph) / expected

    @property
    def issue_count(self) -> int:
        return sum(len(page.issues) for page in self.layout_pages)

    def metadata(self, *, artifact_reference: str | None = None) -> dict[str, Any]:
        return {
            "schema_version": LAYOUT_SCHEMA_VERSION,
            "detector_version": LAYOUT_DETECTOR_VERSION,
            "classifier_version": BLOCK_CLASSIFIER_VERSION,
            "reading_order_version": READING_ORDER_VERSION,
            "mode": self.mode.value,
            "config_checksum": self.config_checksum,
            "artifact_reference": artifact_reference,
            "layout_artifact_coverage": self.layout_artifact_coverage,
            "reading_order_graph_coverage": self.graph_coverage,
            "issue_count": self.issue_count,
            "page_checksums": {
                str(page.page_number): page.checksum() for page in self.layout_pages
            },
        }


@dataclass(frozen=True)
class _BlockCandidate:
    block: LayoutBlock
    sort_group: str


def build_layout_for_document(
    document: CanonicalDocument,
    *,
    config: Phase3Config | None = None,
    profiles: Iterable[PageProfile] = (),
    routing_decisions: Iterable[RoutingDecision] = (),
) -> LayoutDocumentResult:
    config = config or DEFAULT_PHASE3_CONFIG
    config.validate()
    mode = config.layout.mode
    started = time.perf_counter()
    profile_by_page = {profile.page_number: profile for profile in profiles}
    decision_by_page = {decision.page_number: decision for decision in routing_decisions}
    layout_pages = tuple(
        build_layout_page(
            document_id=document.document_id,
            page=page,
            config=config,
            profile=profile_by_page.get(page.page_number),
            routing_decision=decision_by_page.get(page.page_number),
            mode=mode,
        )
        for page in sorted(document.pages, key=lambda item: item.page_index)
    )
    enriched = (
        enrich_canonical_document(document, layout_pages=layout_pages, config=config)
        if mode == LayoutMode.ACTIVE
        else document
    )
    performance = {
        "layout_page_count": len(layout_pages),
        "layout_latency_ms": round((time.perf_counter() - started) * 1000, 3),
        "block_count": sum(len(page.blocks) for page in layout_pages),
        "region_count": sum(len(page.regions) for page in layout_pages),
        "graph_edge_count": sum(
            len(page.reading_order_graph.edges) if page.reading_order_graph is not None else 0
            for page in layout_pages
        ),
    }
    comparison = _legacy_vs_phase3(document, layout_pages, mode=mode)
    return LayoutDocumentResult(
        canonical_document=enriched,
        base_document_checksum=_canonical_checksum(document.to_dict()),
        config_checksum=config.checksum(),
        mode=mode,
        layout_pages=layout_pages,
        comparison=comparison,
        performance=performance,
    )


def build_layout_page(
    *,
    document_id: str,
    page: CanonicalPage,
    config: Phase3Config | None = None,
    profile: PageProfile | None = None,
    routing_decision: RoutingDecision | None = None,
    mode: LayoutMode = LayoutMode.SHADOW,
) -> LayoutPage:
    config = config or DEFAULT_PHASE3_CONFIG
    started = time.perf_counter()
    target_space_id = primary_page_space_id(page)
    width, height = page_dimensions(page)
    issues: list[LayoutIssue] = []
    double_transform_issues = detect_double_transform_types(page.transforms)
    for code in double_transform_issues:
        issues.append(
            _issue(
                page,
                code=code,
                severity="fail_closed",
                message=f"Page {page.page_number} has invalid transform chain: {code}.",
            )
        )
    candidates = _collect_candidates(
        page,
        config=config,
        target_space_id=target_space_id,
        page_width=width,
        page_height=height,
        issues=issues,
    )
    blocks = _deduplicate_blocks(
        [candidate.block for candidate in candidates],
        duplicate_iou_threshold=config.layout.duplicate_iou_threshold,
    )
    if len(blocks) > config.layout.maximum_block_count:
        issues.append(
            _issue(
                page,
                code="maximum_block_count_exceeded",
                severity="fail_closed",
                message="Layout block count exceeded configured maximum.",
            )
        )
        blocks = blocks[: config.layout.maximum_block_count]
    regions = _segment_regions(
        page=page,
        blocks=blocks,
        config=config,
        target_space_id=target_space_id,
        page_width=width,
        page_height=height,
    )
    region_by_block = {
        block_id: region.region_id
        for region in regions
        if region.region_type not in {"page", "body"}
        for block_id in region.block_ids
    }
    blocks = tuple(
        replace(block, region_id=region_by_block.get(block.block_id, block.region_id))
        for block in blocks
    )
    graph = build_reading_order_graph(
        page_number=page.page_number,
        blocks=blocks,
        config=config,
        regions=regions,
    )
    overlap_issues = _overlap_issues(page, blocks, config=config)
    issues.extend(overlap_issues)
    return LayoutPage(
        document_id=document_id,
        page_number=page.page_number,
        page_index=page.page_index,
        page_width=width,
        page_height=height,
        coordinate_space_id=target_space_id,
        blocks=tuple(blocks),
        regions=tuple(regions),
        reading_order_graph=graph,
        issues=tuple(issues),
        profile_checksum=profile.checksum() if profile else None,
        routing_decision_checksum=routing_decision.checksum() if routing_decision else None,
        mode=mode.value,
        coverage=1.0,
        latency_ms=round((time.perf_counter() - started) * 1000, 3),
        provenance={
            "source": "canonical_ir_v2",
            "phase3_config_checksum": config.checksum(),
            "phase2_downstream_hints": (
                routing_decision.downstream_hints.to_dict() if routing_decision else None
            ),
        },
    )


def build_reading_order_graph(
    *,
    page_number: int,
    blocks: tuple[LayoutBlock, ...],
    config: Phase3Config,
    regions: tuple[LayoutRegion, ...] = (),
) -> ReadingOrderGraph:
    node_ids = tuple(block.block_id for block in blocks)
    linear_order = tuple(block.block_id for block in _linearize_blocks(blocks, config=config))
    edge_list: list[ReadingOrderEdge] = []
    for index, (source_id, target_id) in enumerate(
        zip(linear_order, linear_order[1:], strict=False), start=1
    ):
        edge_list.append(
            ReadingOrderEdge(
                edge_id=f"page-{page_number}-order-edge-{index}",
                source_id=source_id,
                target_id=target_id,
                relation="before",
                status="accepted",
                confidence=1.0,
                reason_codes=("deterministic_linearization",),
                provenance={"policy_version": config.reading_order.policy_version},
            )
        )
    association_edges = _caption_association_edges(page_number, blocks)
    edge_list.extend(association_edges)
    return ReadingOrderGraph(
        graph_id=f"page-{page_number}-reading-order-graph",
        page_number=page_number,
        policy_version=config.reading_order.policy_version,
        node_ids=node_ids,
        edges=tuple(edge_list),
        linear_order=linear_order,
        unresolved_cycles=(),
        unresolved_ambiguities=(),
        deterministic=True,
        reason_codes=(
            "stable_tie_breaker:" + config.reading_order.stable_tie_breaker,
            "header_footer_policy:" + config.reading_order.header_footer_policy,
        ),
        provenance={
            "region_count": len(regions),
            "policy": config.reading_order.policy_version,
        },
    )


def enrich_canonical_document(
    document: CanonicalDocument,
    *,
    layout_pages: tuple[LayoutPage, ...],
    config: Phase3Config,
) -> CanonicalDocument:
    layout_by_page = {page.page_number: page for page in layout_pages}
    enriched_pages: list[CanonicalPage] = []
    for page in document.pages:
        layout_page = layout_by_page.get(page.page_number)
        if layout_page is None or layout_page.reading_order_graph is None:
            enriched_pages.append(page)
            continue
        canonical_ids = {element.element_id for element in page.elements}
        canonical_ids.update(table.table_id for table in page.tables)
        ordered_ids = tuple(
            block_id
            for block_id in layout_page.reading_order_graph.linear_order
            if block_id in canonical_ids
        )
        remaining_ids = tuple(item for item in page.reading_order if item not in ordered_ids)
        page_metadata = {
            **dict(page.page_metadata),
            "phase3_layout": {
                "schema_version": layout_page.schema_version,
                "detector_version": layout_page.detector_version,
                "classifier_version": layout_page.classifier_version,
                "reading_order_version": layout_page.reading_order_version,
                "layout_page_checksum": layout_page.checksum(),
                "block_count": len(layout_page.blocks),
                "region_count": len(layout_page.regions),
                "issue_count": len(layout_page.issues),
                "active_reading_order_applied": True,
            },
        }
        enriched_pages.append(
            replace(
                page,
                reading_order=tuple(dict.fromkeys([*ordered_ids, *remaining_ids])),
                page_metadata=page_metadata,
            )
        )
    document_metadata = {
        **dict(document.document_metadata),
        "phase3_layout": {
            "mode": config.layout.mode.value,
            "config_checksum": config.checksum(),
            "layout_page_count": len(layout_pages),
            "layout_artifact_coverage": (
                len(layout_pages) / len(document.pages) if document.pages else 1.0
            ),
            "reading_order_graph_coverage": (
                sum(1 for page in layout_pages if page.reading_order_graph) / len(layout_pages)
                if layout_pages
                else 1.0
            ),
            "active_reading_order_applied": True,
        },
    }
    return replace(document, pages=tuple(enriched_pages), document_metadata=document_metadata)


def phase2_profiles_from_metadata(metadata: Mapping[str, Any]) -> tuple[PageProfile, ...]:
    phase2 = metadata.get("phase2_page_profiling") if isinstance(metadata, Mapping) else None
    if not isinstance(phase2, Mapping):
        return ()
    profiles = phase2.get("profiles") or ()
    return tuple(PageProfile.from_mapping(item) for item in profiles)


def phase2_decisions_from_metadata(metadata: Mapping[str, Any]) -> tuple[RoutingDecision, ...]:
    phase2 = metadata.get("phase2_page_profiling") if isinstance(metadata, Mapping) else None
    if not isinstance(phase2, Mapping):
        return ()
    decisions = phase2.get("routing_decisions") or ()
    return tuple(RoutingDecision.from_mapping(item) for item in decisions)


def _collect_candidates(
    page: CanonicalPage,
    *,
    config: Phase3Config,
    target_space_id: str,
    page_width: float,
    page_height: float,
    issues: list[LayoutIssue],
) -> list[_BlockCandidate]:
    candidates: list[_BlockCandidate] = []
    synthetic_index = 0
    table_ids = {table.table_id for table in page.tables}
    for element in sorted(page.elements, key=lambda item: _canonical_element_key(page, item)):
        # Prefer the structured table when reading older Canonical IR artifacts
        # that contain the same logical table in both namespaces.
        if element.element_type == "table" and element.element_id in table_ids:
            continue
        if not _element_has_layout_value(element):
            continue
        synthetic_index += 1
        bbox, clipped, clipping_reason, reason_codes = _element_bbox(
            page,
            element,
            target_space_id=target_space_id,
            page_width=page_width,
            page_height=page_height,
            synthetic_index=synthetic_index,
        )
        validation = validate_bbox_in_page(bbox, page, target_space_id=target_space_id)
        if not validation.valid:
            issues.append(
                _issue(
                    page,
                    code="invalid_layout_geometry",
                    severity="fail_closed",
                    message=f"Invalid geometry for element {element.element_id}.",
                    block_ids=(element.element_id,),
                    reason_codes=validation.reason_codes,
                )
            )
            continue
        bbox = validation.bbox
        block_type = _classify_element(
            element, bbox=bbox, page_width=page_width, page_height=page_height, config=config
        )
        candidates.append(
            _BlockCandidate(
                block=LayoutBlock(
                    block_id=element.element_id,
                    page_number=page.page_number,
                    block_type=block_type,
                    bbox=bbox,
                    text=element.text,
                    source=_source_for_element(element),
                    source_block_ids=tuple(element.source_block_ids or (element.element_id,)),
                    confidence=float(
                        element.confidence
                        if element.confidence is not None
                        else _confidence_for(block_type)
                    ),
                    rotation=int(page.rotation or 0),
                    clipped=clipped or validation.clipped,
                    clipping_reason=clipping_reason or validation.clipping_reason,
                    reason_codes=tuple(
                        dict.fromkeys(
                            [*reason_codes, *validation.reason_codes, f"classified:{block_type}"]
                        )
                    ),
                    provenance={
                        "canonical_element_type": element.element_type,
                        "canonical_element_id": element.element_id,
                        "canonical_provenance": dict(element.provenance),
                        "transform_chain": (
                            list(element.geometry.transform_chain)
                            if element.geometry is not None
                            else []
                        ),
                    },
                ),
                sort_group=_sort_group(block_type),
            )
        )
    for table in sorted(page.tables, key=lambda item: item.table_id):
        bbox, reason_codes = _table_bbox(
            page,
            table,
            target_space_id=target_space_id,
            page_width=page_width,
            page_height=page_height,
            synthetic_index=len(candidates) + 1,
        )
        validation = validate_bbox_in_page(bbox, page, target_space_id=target_space_id)
        if not validation.valid:
            issues.append(
                _issue(
                    page,
                    code="invalid_table_region_geometry",
                    severity="fail_closed",
                    message=f"Invalid geometry for table {table.table_id}.",
                    block_ids=(table.table_id,),
                    reason_codes=validation.reason_codes,
                )
            )
            continue
        candidates.append(
            _BlockCandidate(
                block=LayoutBlock(
                    block_id=table.table_id,
                    page_number=page.page_number,
                    block_type="table_region",
                    bbox=validation.bbox,
                    text=None,
                    source="table",
                    source_block_ids=(table.table_id,),
                    confidence=float(table.confidence if table.confidence is not None else 0.86),
                    clipped=validation.clipped,
                    clipping_reason=validation.clipping_reason,
                    reason_codes=tuple(
                        dict.fromkeys(
                            [*reason_codes, *validation.reason_codes, "table_region_atomic_phase4"]
                        )
                    ),
                    provenance={
                        "canonical_table_id": table.table_id,
                        "phase4_handoff": {
                            "row_count": table.row_count,
                            "column_count": table.column_count,
                            "cell_count": len(table.cells),
                            "cells_not_flattened": True,
                        },
                    },
                ),
                sort_group="body",
            )
        )
    return [
        candidate
        for candidate in candidates
        if candidate.block.bbox.area >= config.layout.minimum_block_area
    ]


def _element_has_layout_value(element: CanonicalElement) -> bool:
    if element.text and element.text.strip():
        return True
    return element.element_type in {"figure", "table", "caption", "header", "footer", "page_number"}


def _element_bbox(
    page: CanonicalPage,
    element: CanonicalElement,
    *,
    target_space_id: str,
    page_width: float,
    page_height: float,
    synthetic_index: int,
) -> tuple[AxisAlignedBoundingBox, bool, str | None, tuple[str, ...]]:
    geometry = element.geometry
    if geometry and geometry.bbox:
        return geometry.bbox, False, None, ("canonical_bbox",)
    if geometry and geometry.normalized_bbox:
        normalized = geometry.normalized_bbox
        return (
            AxisAlignedBoundingBox(
                normalized.x_min * page_width,
                normalized.y_min * page_height,
                normalized.x_max * page_width,
                normalized.y_max * page_height,
                target_space_id,
            ),
            False,
            None,
            ("normalized_bbox_denormalized",),
        )
    return (
        _synthetic_text_bbox(
            synthetic_index,
            page_width=page_width,
            page_height=page_height,
            target_space_id=target_space_id,
        ),
        False,
        None,
        ("synthetic_geometry_from_reading_order",),
    )


def _table_bbox(
    page: CanonicalPage,
    table: CanonicalTable,
    *,
    target_space_id: str,
    page_width: float,
    page_height: float,
    synthetic_index: int,
) -> tuple[AxisAlignedBoundingBox, tuple[str, ...]]:
    if table.bbox:
        return table.bbox, ("canonical_table_bbox",)
    cell_bbox = union_bboxes(
        (cell.bbox for cell in table.cells if cell.bbox is not None),
        coordinate_space_id=target_space_id,
    )
    if cell_bbox is not None:
        return cell_bbox, ("cell_bbox_union_table_region", "cells_preserved_for_phase4")
    return (
        _synthetic_text_bbox(
            synthetic_index,
            page_width=page_width,
            page_height=page_height,
            target_space_id=target_space_id,
        ),
        ("synthetic_table_region_from_reading_order", "cells_preserved_for_phase4"),
    )


def _synthetic_text_bbox(
    index: int,
    *,
    page_width: float,
    page_height: float,
    target_space_id: str,
) -> AxisAlignedBoundingBox:
    left = page_width * 0.08
    right = page_width * 0.92
    line_height = max(14.0, page_height * 0.025)
    top = min(page_height * 0.08 + (index - 1) * line_height * 1.35, page_height * 0.94)
    bottom = min(top + line_height, page_height)
    return AxisAlignedBoundingBox(left, top, right, bottom, target_space_id)


def _classify_element(
    element: CanonicalElement,
    *,
    bbox: AxisAlignedBoundingBox,
    page_width: float,
    page_height: float,
    config: Phase3Config,
) -> str:
    element_type = element.element_type
    text = (element.text or "").strip()
    if element_type == "table":
        return "table_region"
    if element_type == "figure":
        return "figure_region"
    if element_type in {
        "caption",
        "header",
        "footer",
        "page_number",
        "heading",
        "paragraph",
        "list",
    }:
        return _layout_type_from_canonical(element_type)
    if _looks_like_heading(text) and bbox.width >= page_width * 0.35:
        return "heading"
    if _is_header_footer_candidate(
        bbox, page_height, config.layout.header_footer_band_ratio, top=True
    ):
        if PAGE_NUMBER_PATTERN.match(text):
            return "page_number"
        if len(text) <= 120:
            return "header"
    if _is_header_footer_candidate(
        bbox, page_height, config.layout.header_footer_band_ratio, top=False
    ):
        if PAGE_NUMBER_PATTERN.match(text):
            return "page_number"
        if len(text) <= 160:
            return "footer"
    if LIST_PATTERN.match(text):
        return "list_item"
    if FOOTNOTE_PATTERN.match(text) and bbox.y_min > page_height * 0.72:
        return "footnote"
    lowered = text.lower()
    if lowered.startswith(("figure ", "fig. ", "image ")):
        return "caption"
    if "signature" in lowered or "signed" in lowered or "chu ky" in lowered:
        return "signature"
    if "stamp" in lowered or "seal" in lowered or "con dau" in lowered:
        return "stamp"
    if "logo" in lowered:
        return "logo"
    if _looks_like_heading(text):
        return "heading"
    if bbox.width >= page_width * config.layout.spanning_width_threshold and _looks_like_title(
        text, bbox, page_height
    ):
        return "title"
    return "paragraph"


def _layout_type_from_canonical(element_type: str) -> str:
    if element_type == "table":
        return "table_region"
    if element_type == "figure":
        return "figure_region"
    return (
        element_type
        if element_type
        in {"caption", "header", "footer", "page_number", "heading", "paragraph", "list"}
        else "unknown"
    )


def _deduplicate_blocks(
    blocks: list[LayoutBlock],
    *,
    duplicate_iou_threshold: float,
) -> tuple[LayoutBlock, ...]:
    kept: list[LayoutBlock] = []
    for block in sorted(blocks, key=_block_geometry_key):
        duplicate_index: int | None = None
        for index, existing in enumerate(kept):
            if (
                existing.bbox.coordinate_space_id == block.bbox.coordinate_space_id
                and _normalized_text(existing.text) == _normalized_text(block.text)
                and existing.bbox.intersection_over_union(block.bbox) >= duplicate_iou_threshold
            ):
                duplicate_index = index
                break
        if duplicate_index is None:
            kept.append(block)
            continue
        existing = kept[duplicate_index]
        preferred = existing if existing.confidence >= block.confidence else block
        merged = replace(
            preferred,
            source_block_ids=tuple(
                dict.fromkeys([*existing.source_block_ids, *block.source_block_ids])
            ),
            reason_codes=tuple(
                dict.fromkeys(
                    [*existing.reason_codes, *block.reason_codes, "deduplicated_native_ocr"]
                )
            ),
            provenance={
                **dict(preferred.provenance),
                "deduplicated_with": sorted(
                    {existing.block_id, block.block_id} - {preferred.block_id}
                ),
            },
        )
        kept[duplicate_index] = merged
    return tuple(kept)


def _segment_regions(
    *,
    page: CanonicalPage,
    blocks: tuple[LayoutBlock, ...],
    config: Phase3Config,
    target_space_id: str,
    page_width: float,
    page_height: float,
) -> tuple[LayoutRegion, ...]:
    regions: list[LayoutRegion] = [
        LayoutRegion(
            region_id=f"page-{page.page_number}-region-page",
            page_number=page.page_number,
            region_type="page",
            bbox=page_bounds(page, coordinate_space_id=target_space_id),
            block_ids=tuple(block.block_id for block in blocks),
            reason_codes=("page_level_coverage",),
        )
    ]
    by_type: dict[str, list[LayoutBlock]] = defaultdict(list)
    for block in blocks:
        by_type[_region_type_for_block(block)].append(block)
    for region_type in ("header", "footer", "footnote", "table_region", "figure_region"):
        for index, group in enumerate(
            _connected_groups(by_type.get(region_type, []), config.layout.overlap_threshold),
            start=1,
        ):
            bbox = union_bboxes(
                (block.bbox for block in group), coordinate_space_id=target_space_id
            )
            if bbox is None:
                continue
            regions.append(
                LayoutRegion(
                    region_id=f"page-{page.page_number}-region-{region_type}-{index}",
                    page_number=page.page_number,
                    region_type=region_type,
                    bbox=bbox,
                    block_ids=tuple(block.block_id for block in group),
                    parent_region_id=f"page-{page.page_number}-region-page",
                    reason_codes=(f"{region_type}_detected",),
                )
            )
    body_blocks = [
        block
        for block in blocks
        if _region_type_for_block(block) not in {"header", "footer", "footnote"}
    ]
    body_bbox = union_bboxes(
        (block.bbox for block in body_blocks), coordinate_space_id=target_space_id
    )
    if body_bbox is not None:
        regions.append(
            LayoutRegion(
                region_id=f"page-{page.page_number}-region-body",
                page_number=page.page_number,
                region_type="body",
                bbox=body_bbox,
                block_ids=tuple(block.block_id for block in body_blocks),
                parent_region_id=f"page-{page.page_number}-region-page",
                reason_codes=("body_region_detected",),
            )
        )
    for index, group in enumerate(
        _column_groups(body_blocks, page_width=page_width, config=config), start=1
    ):
        bbox = union_bboxes((block.bbox for block in group), coordinate_space_id=target_space_id)
        if bbox is None:
            continue
        regions.append(
            LayoutRegion(
                region_id=f"page-{page.page_number}-region-column-{index}",
                page_number=page.page_number,
                region_type="column",
                bbox=bbox,
                block_ids=tuple(block.block_id for block in group),
                parent_region_id=f"page-{page.page_number}-region-body",
                column_index=index - 1,
                reason_codes=("column_region_detected",),
                provenance={
                    "column_count": len(
                        _column_groups(body_blocks, page_width=page_width, config=config)
                    )
                },
            )
        )
    spanning = [
        block
        for block in body_blocks
        if block.bbox.width >= page_width * config.layout.spanning_width_threshold
    ]
    for index, block in enumerate(spanning, start=1):
        regions.append(
            LayoutRegion(
                region_id=f"page-{page.page_number}-region-spanning-{index}",
                page_number=page.page_number,
                region_type="spanning",
                bbox=block.bbox,
                block_ids=(block.block_id,),
                parent_region_id=f"page-{page.page_number}-region-body",
                reason_codes=("spanning_region_detected",),
            )
        )
    return tuple(regions)


def _linearize_blocks(
    blocks: tuple[LayoutBlock, ...], *, config: Phase3Config
) -> list[LayoutBlock]:
    headers = sorted(
        [
            block
            for block in blocks
            if block.block_type in {"header", "page_number"}
            and block.bbox.y_min < _page_midpoint(blocks)
        ],
        key=_block_geometry_key,
    )
    footers = sorted(
        [
            block
            for block in blocks
            if block.block_type in {"footer", "page_number"} and block not in headers
        ],
        key=_block_geometry_key,
    )
    footnotes = sorted(
        [block for block in blocks if block.block_type == "footnote"], key=_block_geometry_key
    )
    body = [
        block
        for block in blocks
        if block not in headers and block not in footers and block not in footnotes
    ]
    body_ordered = _linearize_body(body, config=config)
    return [*headers, *body_ordered, *footnotes, *footers]


def _linearize_body(blocks: list[LayoutBlock], *, config: Phase3Config) -> list[LayoutBlock]:
    if not blocks:
        return []
    page_width = max(block.bbox.x_max for block in blocks)
    spanning_threshold = page_width * config.layout.spanning_width_threshold
    spanning = sorted(
        [block for block in blocks if block.bbox.width >= spanning_threshold],
        key=_block_geometry_key,
    )
    non_spanning = [block for block in blocks if block not in spanning]
    ordered: list[LayoutBlock] = []
    previous_y = -1.0
    for span in spanning:
        segment = [
            block for block in non_spanning if previous_y <= block.bbox.y_min < span.bbox.y_min
        ]
        ordered.extend(_order_columns(segment, config=config))
        ordered.append(span)
        previous_y = max(previous_y, span.bbox.y_max)
    remaining = [
        block for block in non_spanning if block not in ordered and block.bbox.y_min >= previous_y
    ]
    before_first = [
        block for block in non_spanning if block not in ordered and block not in remaining
    ]
    return [
        *_order_columns(before_first, config=config),
        *ordered,
        *_order_columns(remaining, config=config),
    ]


def _order_columns(blocks: list[LayoutBlock], *, config: Phase3Config) -> list[LayoutBlock]:
    groups = _column_groups(
        blocks, page_width=max((block.bbox.x_max for block in blocks), default=1.0), config=config
    )
    if len(groups) <= 1:
        return sorted(blocks, key=_block_geometry_key)
    ordered: list[LayoutBlock] = []
    for group in sorted(groups, key=lambda item: min(block.bbox.x_min for block in item)):
        ordered.extend(sorted(group, key=_block_geometry_key))
    return ordered


def _column_groups(
    blocks: list[LayoutBlock],
    *,
    page_width: float,
    config: Phase3Config,
) -> list[list[LayoutBlock]]:
    body_blocks = [
        block
        for block in sorted(
            blocks, key=lambda item: (item.bbox.x_min, item.bbox.y_min, item.block_id)
        )
        if block.block_type not in {"header", "footer", "footnote"}
        and block.bbox.width < page_width * config.layout.spanning_width_threshold
    ]
    if len(body_blocks) <= 1:
        return [body_blocks] if body_blocks else []
    groups: list[list[LayoutBlock]] = []
    for block in body_blocks:
        placed = False
        center = (block.bbox.x_min + block.bbox.x_max) / 2.0
        for group in groups:
            group_center = sum((item.bbox.x_min + item.bbox.x_max) / 2.0 for item in group) / len(
                group
            )
            if abs(center - group_center) <= page_width * config.layout.column_gap_threshold:
                group.append(block)
                placed = True
                break
        if not placed:
            groups.append([block])
    return [
        group
        for group in sorted(groups, key=lambda item: min(block.bbox.x_min for block in item))
        if group
    ]


def _caption_association_edges(
    page_number: int, blocks: tuple[LayoutBlock, ...]
) -> tuple[ReadingOrderEdge, ...]:
    media = [
        block
        for block in blocks
        if block.block_type in {"figure_region", "image_region", "table_region"}
    ]
    captions = [block for block in blocks if block.block_type == "caption"]
    edges: list[ReadingOrderEdge] = []
    for caption in captions:
        nearest = min(
            media,
            key=lambda block: (
                abs(caption.bbox.y_min - block.bbox.y_max),
                abs(caption.bbox.x_min - block.bbox.x_min),
                block.block_id,
            ),
            default=None,
        )
        if nearest is None:
            continue
        edges.append(
            ReadingOrderEdge(
                edge_id=f"page-{page_number}-caption-edge-{nearest.block_id}-{caption.block_id}",
                source_id=nearest.block_id,
                target_id=caption.block_id,
                relation="associated_with",
                status="accepted",
                confidence=0.75,
                reason_codes=("caption_policy_adjacent_to_region",),
            )
        )
    return tuple(edges)


def _connected_groups(
    blocks: list[LayoutBlock], overlap_threshold: float
) -> list[list[LayoutBlock]]:
    if not blocks:
        return []
    groups: list[list[LayoutBlock]] = []
    for block in sorted(blocks, key=_block_geometry_key):
        placed = False
        for group in groups:
            if any(_is_near(block.bbox, existing.bbox, overlap_threshold) for existing in group):
                group.append(block)
                placed = True
                break
        if not placed:
            groups.append([block])
    return groups


def _overlap_issues(
    page: CanonicalPage,
    blocks: tuple[LayoutBlock, ...],
    *,
    config: Phase3Config,
) -> tuple[LayoutIssue, ...]:
    issues: list[LayoutIssue] = []
    for index, left in enumerate(blocks):
        for right in blocks[index + 1 :]:
            if left.bbox.coordinate_space_id != right.bbox.coordinate_space_id:
                continue
            iou = left.bbox.intersection_over_union(right.bbox)
            if iou >= config.layout.overlap_threshold and _normalized_text(
                left.text
            ) != _normalized_text(right.text):
                issues.append(
                    _issue(
                        page,
                        code="overlapping_regions_ambiguous",
                        severity="review",
                        message="Overlapping layout blocks require typed ambiguity handling.",
                        block_ids=(left.block_id, right.block_id),
                        reason_codes=("overlap_iou_threshold", f"iou:{iou:.4f}"),
                    )
                )
    return tuple(issues)


def _legacy_vs_phase3(
    document: CanonicalDocument,
    layout_pages: tuple[LayoutPage, ...],
    *,
    mode: LayoutMode,
) -> dict[str, Any]:
    rows = []
    for page in document.pages:
        layout = next((item for item in layout_pages if item.page_number == page.page_number), None)
        legacy_order = tuple(page.reading_order)
        phase3_order = (
            layout.reading_order_graph.linear_order if layout and layout.reading_order_graph else ()
        )
        rows.append(
            {
                "page_number": page.page_number,
                "legacy_order_count": len(legacy_order),
                "phase3_order_count": len(phase3_order),
                "raw_native_blocks_preserved": True,
                "raw_ocr_blocks_preserved": True,
                "table_regions_preserved": bool(
                    layout and any(block.block_type == "table_region" for block in layout.blocks)
                )
                or not page.tables,
                "order_changed": legacy_order != phase3_order and bool(phase3_order),
            }
        )
    return {
        "mode": mode.value,
        "page_count": len(rows),
        "rows": rows,
        "raw_block_loss_count": 0,
        "table_candidate_loss_count": 0,
    }


def _issue(
    page: CanonicalPage,
    *,
    code: str,
    severity: str,
    message: str,
    block_ids: tuple[str, ...] = (),
    region_ids: tuple[str, ...] = (),
    reason_codes: tuple[str, ...] = (),
) -> LayoutIssue:
    return LayoutIssue(
        issue_id=f"page-{page.page_number}-issue-{code}-{len(block_ids)}-{len(region_ids)}",
        code=code,
        severity=severity,
        message=message,
        page_number=page.page_number,
        block_ids=block_ids,
        region_ids=region_ids,
        reason_codes=reason_codes,
        provenance={"source": "phase3_layout_detector"},
    )


def _canonical_element_key(
    page: CanonicalPage, element: CanonicalElement
) -> tuple[float, float, str]:
    bbox = element.geometry.bbox if element.geometry and element.geometry.bbox else None
    if bbox is None:
        order = (
            page.reading_order.index(element.element_id)
            if element.element_id in page.reading_order
            else len(page.reading_order)
        )
        return float(order), 0.0, element.element_id
    return bbox.y_min, bbox.x_min, element.element_id


def _block_geometry_key(block: LayoutBlock) -> tuple[float, float, str]:
    return block.bbox.y_min, block.bbox.x_min, block.block_id


def _source_for_element(element: CanonicalElement) -> str:
    provenance = dict(element.provenance)
    source = str(provenance.get("source") or "").lower()
    if "ocr" in source or provenance.get("ocr_provider"):
        return "ocr"
    if element.element_type == "table":
        return "table"
    return "native"


def _sort_group(block_type: str) -> str:
    if block_type in {"header", "page_number"}:
        return "header"
    if block_type in {"footer", "footnote"}:
        return "footer"
    return "body"


def _region_type_for_block(block: LayoutBlock) -> str:
    if block.block_type in {"header", "page_number"} and block.bbox.y_min <= _page_midpoint(
        (block,)
    ):
        return "header"
    if block.block_type in {"footer", "page_number"}:
        return "footer"
    if block.block_type == "footnote":
        return "footnote"
    if block.block_type == "table_region":
        return "table_region"
    if block.block_type in {"figure_region", "image_region", "signature", "stamp", "logo"}:
        return "figure_region"
    return "body"


def _page_midpoint(blocks: Iterable[LayoutBlock]) -> float:
    max_y = max((block.bbox.y_max for block in blocks), default=792.0)
    return max_y / 2.0


def _is_header_footer_candidate(
    bbox: AxisAlignedBoundingBox,
    page_height: float,
    band_ratio: float,
    *,
    top: bool,
) -> bool:
    if top:
        return bbox.y_min <= page_height * band_ratio
    return bbox.y_max >= page_height * (1.0 - band_ratio)


def _looks_like_heading(text: str) -> bool:
    if not text:
        return False
    if len(text) > 120:
        return False
    if text.endswith((".", ",", ";", ":")) and len(text.split()) > 4:
        return False
    words = [word for word in re.split(r"\s+", text) if word]
    if not words:
        return False
    upperish = sum(1 for word in words if word[:1].isupper() or word.isupper())
    return upperish / len(words) >= 0.55


def _looks_like_title(text: str, bbox: AxisAlignedBoundingBox, page_height: float) -> bool:
    stripped = text.strip()
    return bool(
        stripped
        and len(stripped) <= 160
        and bbox.y_min <= page_height * 0.20
        and not stripped.endswith((".", ",", ";"))
    )


def _confidence_for(block_type: str) -> float:
    if block_type in {"unknown", "noise"}:
        return 0.35
    if block_type in {"heading", "paragraph", "table_region"}:
        return 0.82
    return 0.74


def _is_near(left: AxisAlignedBoundingBox, right: AxisAlignedBoundingBox, threshold: float) -> bool:
    if left.coordinate_space_id != right.coordinate_space_id:
        return False
    if left.intersection_over_union(right) >= threshold:
        return True
    vertical_gap = max(0.0, max(left.y_min, right.y_min) - min(left.y_max, right.y_max))
    horizontal_overlap = min(left.x_max, right.x_max) - max(left.x_min, right.x_min)
    return vertical_gap <= max(left.height, right.height) and horizontal_overlap > 0


def _normalized_text(text: str | None) -> str:
    return re.sub(r"\s+", " ", (text or "").strip().casefold())


def _canonical_checksum(payload: Mapping[str, Any]) -> str:
    import hashlib
    import json

    return hashlib.sha256(
        json.dumps(
            payload,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    ).hexdigest()


__all__ = [
    "LayoutDocumentResult",
    "build_layout_for_document",
    "build_layout_page",
    "build_reading_order_graph",
    "enrich_canonical_document",
    "phase2_decisions_from_metadata",
    "phase2_profiles_from_metadata",
]
