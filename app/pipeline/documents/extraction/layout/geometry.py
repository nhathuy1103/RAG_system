from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass

from app.pipeline.documents.extraction.canonical.geometry import (
    AxisAlignedBoundingBox,
    CoordinateTransform,
)
from app.pipeline.documents.extraction.canonical.ir import CanonicalPage


@dataclass(frozen=True)
class GeometryValidationResult:
    bbox: AxisAlignedBoundingBox
    valid: bool
    clipped: bool = False
    clipping_reason: str | None = None
    reason_codes: tuple[str, ...] = ()


def primary_page_space_id(page: CanonicalPage) -> str:
    for space in page.coordinate_spaces:
        if space.width and space.height and space.page_index == page.page_index:
            return space.space_id
    for element in page.elements:
        if element.geometry and element.geometry.bbox:
            return element.geometry.bbox.coordinate_space_id
    for table in page.tables:
        if table.bbox:
            return table.bbox.coordinate_space_id
    return f"page-{page.page_index}-pdf-page"


def page_dimensions(page: CanonicalPage) -> tuple[float, float]:
    width = page.original_width
    height = page.original_height
    if width and height:
        return float(width), float(height)
    max_x = 0.0
    max_y = 0.0
    for bbox in _page_bboxes(page):
        max_x = max(max_x, bbox.x_max)
        max_y = max(max_y, bbox.y_max)
    return max(max_x, 612.0), max(max_y, 792.0)


def page_bounds(
    page: CanonicalPage, *, coordinate_space_id: str | None = None
) -> AxisAlignedBoundingBox:
    width, height = page_dimensions(page)
    return AxisAlignedBoundingBox(
        0.0,
        0.0,
        width,
        height,
        coordinate_space_id or primary_page_space_id(page),
    )


def project_bbox_to_page_space(
    bbox: AxisAlignedBoundingBox,
    page: CanonicalPage,
    *,
    target_space_id: str | None = None,
) -> AxisAlignedBoundingBox:
    target = target_space_id or primary_page_space_id(page)
    if bbox.coordinate_space_id == target:
        return bbox
    for transformed in _walk_transforms(bbox, page.transforms, target):
        return transformed
    if _is_normalized_space(bbox):
        width, height = page_dimensions(page)
        return AxisAlignedBoundingBox(
            bbox.x_min * width,
            bbox.y_min * height,
            bbox.x_max * width,
            bbox.y_max * height,
            target,
        )
    raise ValueError(
        f"no transform from {bbox.coordinate_space_id} to {target} on page {page.page_number}"
    )


def validate_bbox_in_page(
    bbox: AxisAlignedBoundingBox,
    page: CanonicalPage,
    *,
    target_space_id: str | None = None,
) -> GeometryValidationResult:
    target = target_space_id or primary_page_space_id(page)
    projected = project_bbox_to_page_space(bbox, page, target_space_id=target)
    bounds = page_bounds(page, coordinate_space_id=target)
    if projected.area <= 0:
        return GeometryValidationResult(
            bbox=projected,
            valid=False,
            reason_codes=("invalid_zero_area_bbox",),
        )
    if _contains(bounds, projected):
        return GeometryValidationResult(
            bbox=projected,
            valid=True,
            reason_codes=("geometry_within_page_bounds",),
        )
    clipped = AxisAlignedBoundingBox(
        max(bounds.x_min, min(bounds.x_max, projected.x_min)),
        max(bounds.y_min, min(bounds.y_max, projected.y_min)),
        max(bounds.x_min, min(bounds.x_max, projected.x_max)),
        max(bounds.y_min, min(bounds.y_max, projected.y_max)),
        target,
    )
    if clipped.area <= 0:
        return GeometryValidationResult(
            bbox=clipped,
            valid=False,
            clipped=True,
            clipping_reason="bbox_outside_page_bounds",
            reason_codes=("bbox_outside_page_bounds", "invalid_zero_area_after_clip"),
        )
    return GeometryValidationResult(
        bbox=clipped,
        valid=True,
        clipped=True,
        clipping_reason="bbox_clipped_to_page_bounds",
        reason_codes=("bbox_out_of_bounds_clipped",),
    )


def detect_double_transform_types(transforms: Iterable[CoordinateTransform]) -> tuple[str, ...]:
    issues: list[str] = []
    seen_by_type: dict[str, int] = {}
    for transform in transforms:
        transform_type = str(transform.transform_type)
        seen_by_type[transform_type] = seen_by_type.get(transform_type, 0) + 1
    if seen_by_type.get("rotate", 0) > 1:
        issues.append("double_rotation_detected")
    scale_count = seen_by_type.get("scale", 0) + seen_by_type.get("resize", 0)
    if scale_count > 1:
        issues.append("double_scaling_detected")
    return tuple(issues)


def union_bboxes(
    bboxes: Iterable[AxisAlignedBoundingBox],
    *,
    coordinate_space_id: str | None = None,
) -> AxisAlignedBoundingBox | None:
    values = list(bboxes)
    if not values:
        return None
    target = coordinate_space_id or values[0].coordinate_space_id
    if any(item.coordinate_space_id != target for item in values):
        raise ValueError("bbox union requires one coordinate space")
    return AxisAlignedBoundingBox(
        min(item.x_min for item in values),
        min(item.y_min for item in values),
        max(item.x_max for item in values),
        max(item.y_max for item in values),
        target,
    )


def _contains(bounds: AxisAlignedBoundingBox, bbox: AxisAlignedBoundingBox) -> bool:
    return (
        bounds.coordinate_space_id == bbox.coordinate_space_id
        and bounds.x_min <= bbox.x_min
        and bounds.y_min <= bbox.y_min
        and bounds.x_max >= bbox.x_max
        and bounds.y_max >= bbox.y_max
    )


def _walk_transforms(
    bbox: AxisAlignedBoundingBox,
    transforms: tuple[CoordinateTransform, ...],
    target_space_id: str,
) -> Iterable[AxisAlignedBoundingBox]:
    queue: list[AxisAlignedBoundingBox] = [bbox]
    seen: set[str] = {bbox.coordinate_space_id}
    while queue:
        current = queue.pop(0)
        for transform in transforms:
            candidate: AxisAlignedBoundingBox | None = None
            if current.coordinate_space_id == transform.source_space_id:
                candidate = transform.transform_bbox(current)
            elif current.coordinate_space_id == transform.target_space_id:
                candidate = transform.inverse_transform_bbox(current)
            if candidate is None or candidate.coordinate_space_id in seen:
                continue
            if candidate.coordinate_space_id == target_space_id:
                yield candidate
                return
            seen.add(candidate.coordinate_space_id)
            queue.append(candidate)


def _is_normalized_space(bbox: AxisAlignedBoundingBox) -> bool:
    return bbox.coordinate_space_id.endswith("-normalized") or (
        0.0 <= bbox.x_min <= 1.0
        and 0.0 <= bbox.x_max <= 1.0
        and 0.0 <= bbox.y_min <= 1.0
        and 0.0 <= bbox.y_max <= 1.0
    )


def _page_bboxes(page: CanonicalPage) -> Iterable[AxisAlignedBoundingBox]:
    for element in page.elements:
        if element.geometry and element.geometry.bbox:
            yield element.geometry.bbox
    for table in page.tables:
        if table.bbox:
            yield table.bbox
        for cell in table.cells:
            if cell.bbox:
                yield cell.bbox


__all__ = [
    "GeometryValidationResult",
    "detect_double_transform_types",
    "page_bounds",
    "page_dimensions",
    "primary_page_space_id",
    "project_bbox_to_page_space",
    "union_bboxes",
    "validate_bbox_in_page",
]
