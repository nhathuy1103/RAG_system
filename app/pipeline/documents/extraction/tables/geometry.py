from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass

from app.pipeline.documents.extraction.canonical.geometry import AxisAlignedBoundingBox
from app.pipeline.documents.extraction.canonical.ir import CanonicalPage
from app.pipeline.documents.extraction.layout.geometry import page_bounds, primary_page_space_id


@dataclass(frozen=True)
class TableGeometryValidation:
    valid: bool
    bbox: AxisAlignedBoundingBox
    clipped: bool = False
    reason_codes: tuple[str, ...] = ()


def split_bbox_grid(
    bbox: AxisAlignedBoundingBox,
    *,
    row_count: int,
    column_count: int,
) -> tuple[tuple[AxisAlignedBoundingBox, ...], ...]:
    if row_count <= 0 or column_count <= 0:
        raise ValueError("row_count and column_count must be positive")
    row_height = bbox.height / row_count
    column_width = bbox.width / column_count
    rows: list[tuple[AxisAlignedBoundingBox, ...]] = []
    for row_index in range(row_count):
        cells: list[AxisAlignedBoundingBox] = []
        for column_index in range(column_count):
            cells.append(
                AxisAlignedBoundingBox(
                    bbox.x_min + column_width * column_index,
                    bbox.y_min + row_height * row_index,
                    bbox.x_min + column_width * (column_index + 1),
                    bbox.y_min + row_height * (row_index + 1),
                    bbox.coordinate_space_id,
                )
            )
        rows.append(tuple(cells))
    return tuple(rows)


def row_bbox(cells: Iterable[AxisAlignedBoundingBox]) -> AxisAlignedBoundingBox:
    return union_bboxes(cells)


def column_bbox(cells: Iterable[AxisAlignedBoundingBox]) -> AxisAlignedBoundingBox:
    return union_bboxes(cells)


def union_bboxes(cells: Iterable[AxisAlignedBoundingBox]) -> AxisAlignedBoundingBox:
    values = list(cells)
    if not values:
        raise ValueError("union_bboxes requires at least one bbox")
    space_id = values[0].coordinate_space_id
    if any(value.coordinate_space_id != space_id for value in values):
        raise ValueError("all bboxes must share coordinate_space_id")
    return AxisAlignedBoundingBox(
        min(value.x_min for value in values),
        min(value.y_min for value in values),
        max(value.x_max for value in values),
        max(value.y_max for value in values),
        space_id,
    )


def validate_table_bbox_in_page(
    bbox: AxisAlignedBoundingBox,
    page: CanonicalPage,
) -> TableGeometryValidation:
    target_space_id = primary_page_space_id(page)
    bounds = page_bounds(page, coordinate_space_id=target_space_id)
    if bbox.coordinate_space_id != target_space_id:
        return TableGeometryValidation(
            valid=False,
            bbox=bbox,
            reason_codes=("coordinate_space_mismatch",),
        )
    clipped = AxisAlignedBoundingBox(
        max(bounds.x_min, bbox.x_min),
        max(bounds.y_min, bbox.y_min),
        min(bounds.x_max, bbox.x_max),
        min(bounds.y_max, bbox.y_max),
        bbox.coordinate_space_id,
    )
    if clipped.width <= 0 or clipped.height <= 0:
        return TableGeometryValidation(
            valid=False,
            bbox=bbox,
            reason_codes=("bbox_outside_page_bounds",),
        )
    reason_codes = ("bbox_clipped_to_page_bounds",) if clipped != bbox else ()
    return TableGeometryValidation(
        valid=True,
        bbox=clipped,
        clipped=clipped != bbox,
        reason_codes=reason_codes,
    )


def bbox_contains(parent: AxisAlignedBoundingBox, child: AxisAlignedBoundingBox) -> bool:
    if parent.coordinate_space_id != child.coordinate_space_id:
        return False
    return (
        parent.x_min <= child.x_min
        and parent.y_min <= child.y_min
        and parent.x_max >= child.x_max
        and parent.y_max >= child.y_max
    )


def mean_iou(pairs: Iterable[tuple[AxisAlignedBoundingBox, AxisAlignedBoundingBox]]) -> float:
    values = [
        left.intersection_over_union(right)
        for left, right in pairs
        if left.coordinate_space_id == right.coordinate_space_id
    ]
    return sum(values) / len(values) if values else 1.0


__all__ = [
    "TableGeometryValidation",
    "bbox_contains",
    "column_bbox",
    "mean_iou",
    "row_bbox",
    "split_bbox_grid",
    "union_bboxes",
    "validate_table_bbox_in_page",
]
