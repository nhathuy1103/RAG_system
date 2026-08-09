from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from app.pipeline.documents.extraction.canonical.geometry import (
    AxisAlignedBoundingBox,
    CoordinateSpace,
    CoordinateSpaceType,
    CoordinateTransform,
    Polygon,
    validate_transform_chain,
)
from app.pipeline.documents.extraction.canonical.ir import CanonicalDocument, CanonicalElement


@dataclass(frozen=True)
class CanonicalIRValidationIssue:
    code: str
    message: str
    severity: str = "error"
    page_index: int | None = None
    element_id: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "code": self.code,
            "message": self.message,
            "severity": self.severity,
            "page_index": self.page_index,
            "element_id": self.element_id,
        }


@dataclass(frozen=True)
class CanonicalIRValidationResult:
    valid: bool
    blocking_issues: tuple[CanonicalIRValidationIssue, ...] = ()
    warnings: tuple[CanonicalIRValidationIssue, ...] = ()
    issue_codes: tuple[str, ...] = ()
    affected_pages: tuple[int, ...] = ()
    affected_elements: tuple[str, ...] = ()
    geometry_error_count: int = 0
    provenance_error_count: int = 0
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "valid": self.valid,
            "blocking_issues": [issue.to_dict() for issue in self.blocking_issues],
            "warnings": [issue.to_dict() for issue in self.warnings],
            "issue_codes": list(self.issue_codes),
            "affected_pages": list(self.affected_pages),
            "affected_elements": list(self.affected_elements),
            "geometry_error_count": self.geometry_error_count,
            "provenance_error_count": self.provenance_error_count,
            "metadata": dict(self.metadata),
        }


def validate_canonical_document(document: CanonicalDocument) -> CanonicalIRValidationResult:
    issues: list[CanonicalIRValidationIssue] = []
    warnings: list[CanonicalIRValidationIssue] = []

    if document.schema_name != "canonical_document_ir":
        issues.append(_issue("unsupported_schema_name", "Unsupported canonical IR schema name."))
    if not str(document.schema_version).startswith("2."):
        issues.append(
            _issue("unsupported_schema_version", "Unsupported canonical IR schema version.")
        )
    if not document.pages:
        warnings.append(
            _issue("empty_pages", "Canonical document contains no pages.", severity="warning")
        )
    if not document.parser_provenance.get("parser_name"):
        issues.append(
            _issue("parser_provenance_missing", "Parser provenance must include parser_name.")
        )
    if not document.parser_provenance.get("parser_version"):
        issues.append(
            _issue("parser_version_missing", "Parser provenance must include parser_version.")
        )
    if not document.extraction_provenance.get("attempt_id"):
        issues.append(
            _issue("attempt_provenance_missing", "Extraction provenance must include attempt_id.")
        )

    element_ids: set[str] = set()
    table_ids: set[str] = set()
    page_indexes = {page.page_index for page in document.pages}
    spaces_by_id: dict[str, CoordinateSpace] = {}
    transforms_by_id: dict[str, CoordinateTransform] = {}
    all_elements: list[CanonicalElement] = []

    for page in document.pages:
        if page.page_index < 0:
            issues.append(
                _issue(
                    "invalid_page_index",
                    "Page index must not be negative.",
                    page_index=page.page_index,
                )
            )
        for space in page.coordinate_spaces:
            if space.space_id in spaces_by_id:
                issues.append(
                    _issue(
                        "duplicate_coordinate_space",
                        f"Duplicate coordinate space {space.space_id}.",
                        page_index=page.page_index,
                    )
                )
            spaces_by_id[space.space_id] = space
            if space.page_index != page.page_index:
                issues.append(
                    _issue(
                        "coordinate_space_page_mismatch",
                        "Coordinate space page_index does not match page.",
                        page_index=page.page_index,
                    )
                )
            if space.width is None or space.height is None:
                warnings.append(
                    _issue(
                        "coordinate_space_dimensions_missing",
                        "Coordinate space width/height are missing.",
                        severity="warning",
                        page_index=page.page_index,
                    )
                )
        for transform in page.transforms:
            if transform.transform_id in transforms_by_id:
                issues.append(
                    _issue(
                        "duplicate_transform_id",
                        f"Duplicate transform {transform.transform_id}.",
                        page_index=page.page_index,
                    )
                )
            transforms_by_id[transform.transform_id] = transform
            if transform.source_space_id not in spaces_by_id:
                issues.append(
                    _issue(
                        "transform_source_missing",
                        f"Transform source space {transform.source_space_id} is missing.",
                        page_index=page.page_index,
                    )
                )
            if transform.target_space_id not in spaces_by_id:
                issues.append(
                    _issue(
                        "transform_target_missing",
                        f"Transform target space {transform.target_space_id} is missing.",
                        page_index=page.page_index,
                    )
                )
        all_elements.extend(page.elements)
        for table in page.tables:
            if table.table_id in table_ids:
                issues.append(
                    _issue(
                        "duplicate_table_id",
                        f"Duplicate table_id {table.table_id}.",
                        page_index=page.page_index,
                        element_id=table.table_id,
                    )
                )
            table_ids.add(table.table_id)
            if table.page_index != page.page_index:
                issues.append(
                    _issue(
                        "table_page_mismatch",
                        f"Table {table.table_id} page mismatch.",
                        page_index=page.page_index,
                        element_id=table.table_id,
                    )
                )
            _validate_geometry_object(
                table.bbox,
                spaces_by_id,
                issues,
                page_index=page.page_index,
                element_id=table.table_id,
            )
            _validate_geometry_object(
                table.polygon,
                spaces_by_id,
                issues,
                page_index=page.page_index,
                element_id=table.table_id,
            )
            for cell in table.cells:
                if cell.row_index < 0 or cell.column_index < 0:
                    issues.append(
                        _issue(
                            "invalid_table_cell_index",
                            "Table cell indexes must not be negative.",
                            page_index=page.page_index,
                            element_id=table.table_id,
                        )
                    )
                if cell.row_span < 1 or cell.column_span < 1:
                    issues.append(
                        _issue(
                            "invalid_table_cell_span",
                            "Table cell spans must be >= 1.",
                            page_index=page.page_index,
                            element_id=table.table_id,
                        )
                    )
                _validate_geometry_object(
                    cell.bbox,
                    spaces_by_id,
                    issues,
                    page_index=page.page_index,
                    element_id=table.table_id,
                )
                _validate_geometry_object(
                    cell.polygon,
                    spaces_by_id,
                    issues,
                    page_index=page.page_index,
                    element_id=table.table_id,
                )

    all_elements.extend(document.global_elements)
    child_refs: set[str] = set()
    for element in all_elements:
        if element.element_id in element_ids:
            issues.append(
                _issue(
                    "duplicate_element_id",
                    f"Duplicate element_id {element.element_id}.",
                    page_index=element.page_index,
                    element_id=element.element_id,
                )
            )
        if element.element_id in table_ids:
            issues.append(
                _issue(
                    "duplicate_canonical_object_id",
                    f"Canonical element and table share ID {element.element_id}.",
                    page_index=element.page_index,
                    element_id=element.element_id,
                )
            )
        element_ids.add(element.element_id)
        if element.page_index is not None and element.page_index not in page_indexes:
            issues.append(
                _issue(
                    "element_page_missing",
                    "Element references a missing page.",
                    page_index=element.page_index,
                    element_id=element.element_id,
                )
            )
        if not element.provenance:
            warnings.append(
                _issue(
                    "element_provenance_missing",
                    "Element provenance is missing.",
                    severity="warning",
                    page_index=element.page_index,
                    element_id=element.element_id,
                )
            )
        for child_id in element.child_ids:
            child_refs.add(child_id)
        if element.geometry is not None:
            geometry = element.geometry
            _validate_geometry_object(
                geometry.bbox,
                spaces_by_id,
                issues,
                page_index=element.page_index,
                element_id=element.element_id,
            )
            _validate_geometry_object(
                geometry.polygon,
                spaces_by_id,
                issues,
                page_index=element.page_index,
                element_id=element.element_id,
            )
            _validate_geometry_object(
                geometry.normalized_bbox,
                spaces_by_id,
                issues,
                page_index=element.page_index,
                element_id=element.element_id,
            )
            _validate_geometry_object(
                geometry.provider_bbox,
                spaces_by_id,
                issues,
                page_index=element.page_index,
                element_id=element.element_id,
            )
            _validate_geometry_object(
                geometry.provider_polygon,
                spaces_by_id,
                issues,
                page_index=element.page_index,
                element_id=element.element_id,
            )
            _validate_geometry_transform_chain(
                geometry.transform_chain,
                transforms_by_id,
                issues,
                page_index=element.page_index,
                element_id=element.element_id,
            )

    for element in all_elements:
        if element.parent_id is not None and element.parent_id not in element_ids:
            issues.append(
                _issue(
                    "parent_reference_missing",
                    "Element parent_id is missing.",
                    page_index=element.page_index,
                    element_id=element.element_id,
                )
            )
    for child_id in child_refs:
        if child_id not in element_ids:
            issues.append(
                _issue("child_reference_missing", f"Child element {child_id} is missing.")
            )

    issue_codes = tuple(dict.fromkeys(issue.code for issue in (*issues, *warnings)))
    affected_pages = tuple(
        sorted({issue.page_index for issue in (*issues, *warnings) if issue.page_index is not None})
    )
    affected_elements = tuple(
        sorted({issue.element_id for issue in (*issues, *warnings) if issue.element_id is not None})
    )
    geometry_error_count = sum(
        1
        for issue in issues
        if "geometry" in issue.code or "bbox" in issue.code or "polygon" in issue.code
    )
    provenance_error_count = sum(1 for issue in issues if "provenance" in issue.code)
    return CanonicalIRValidationResult(
        valid=not issues,
        blocking_issues=tuple(issues),
        warnings=tuple(warnings),
        issue_codes=issue_codes,
        affected_pages=affected_pages,
        affected_elements=affected_elements,
        geometry_error_count=geometry_error_count,
        provenance_error_count=provenance_error_count,
        metadata={
            "page_count": len(document.pages),
            "element_count": len(all_elements),
            "coordinate_space_count": len(spaces_by_id),
            "transform_count": len(transforms_by_id),
        },
    )


def _validate_geometry_object(
    value: AxisAlignedBoundingBox | Polygon | None,
    spaces_by_id: dict[str, CoordinateSpace],
    issues: list[CanonicalIRValidationIssue],
    *,
    page_index: int | None,
    element_id: str | None,
) -> None:
    if value is None:
        return
    space_id = value.coordinate_space_id
    space = spaces_by_id.get(space_id)
    if space is None:
        issues.append(
            _issue(
                "geometry_coordinate_space_missing",
                f"Geometry references missing coordinate space {space_id}.",
                page_index=page_index,
                element_id=element_id,
            )
        )
        return
    if isinstance(value, AxisAlignedBoundingBox):
        _validate_bbox_bounds(value, space, issues, page_index=page_index, element_id=element_id)
    else:
        _validate_polygon_bounds(value, space, issues, page_index=page_index, element_id=element_id)


def _validate_geometry_transform_chain(
    transform_ids: tuple[str, ...],
    transforms_by_id: dict[str, CoordinateTransform],
    issues: list[CanonicalIRValidationIssue],
    *,
    page_index: int | None,
    element_id: str | None,
) -> None:
    if not transform_ids:
        return
    ordered: list[CoordinateTransform] = []
    for transform_id in transform_ids:
        transform = transforms_by_id.get(transform_id)
        if transform is None:
            issues.append(
                _issue(
                    "geometry_transform_missing",
                    f"Geometry transform {transform_id} is missing.",
                    page_index=page_index,
                    element_id=element_id,
                )
            )
            continue
        ordered.append(transform)
    if not ordered:
        return
    for chain_issue in validate_transform_chain(ordered):
        issues.append(
            _issue(
                "invalid_transform_chain",
                chain_issue,
                page_index=page_index,
                element_id=element_id,
            )
        )


def _validate_bbox_bounds(
    bbox: AxisAlignedBoundingBox,
    space: CoordinateSpace,
    issues: list[CanonicalIRValidationIssue],
    *,
    page_index: int | None,
    element_id: str | None,
) -> None:
    if bbox.x_min > bbox.x_max or bbox.y_min > bbox.y_max:
        issues.append(
            _issue(
                "invalid_bbox_extent",
                "Bounding box extents are invalid.",
                page_index=page_index,
                element_id=element_id,
            )
        )
    if space.type == CoordinateSpaceType.NORMALIZED_PAGE_SPACE.value:
        tolerance = 1e-6
        if (
            bbox.x_min < -tolerance
            or bbox.y_min < -tolerance
            or bbox.x_max > 1 + tolerance
            or bbox.y_max > 1 + tolerance
        ):
            issues.append(
                _issue(
                    "normalized_geometry_out_of_bounds",
                    "Normalized bbox must be within [0, 1].",
                    page_index=page_index,
                    element_id=element_id,
                )
            )
    if space.width is not None and (bbox.x_min < -1e-6 or bbox.x_max > space.width + 1e-6):
        issues.append(
            _issue(
                "geometry_x_out_of_bounds",
                "Geometry x coordinates exceed coordinate space bounds.",
                page_index=page_index,
                element_id=element_id,
            )
        )
    if space.height is not None and (bbox.y_min < -1e-6 or bbox.y_max > space.height + 1e-6):
        issues.append(
            _issue(
                "geometry_y_out_of_bounds",
                "Geometry y coordinates exceed coordinate space bounds.",
                page_index=page_index,
                element_id=element_id,
            )
        )


def _validate_polygon_bounds(
    polygon: Polygon,
    space: CoordinateSpace,
    issues: list[CanonicalIRValidationIssue],
    *,
    page_index: int | None,
    element_id: str | None,
) -> None:
    if len(polygon.points) < 3:
        issues.append(
            _issue(
                "invalid_polygon_point_count",
                "Polygon requires at least three points.",
                page_index=page_index,
                element_id=element_id,
            )
        )
    for point in polygon.points:
        if point.coordinate_space_id != polygon.coordinate_space_id:
            issues.append(
                _issue(
                    "mixed_polygon_coordinate_spaces",
                    "Polygon mixes coordinate spaces.",
                    page_index=page_index,
                    element_id=element_id,
                )
            )
        if space.width is not None and (point.x < -1e-6 or point.x > space.width + 1e-6):
            issues.append(
                _issue(
                    "geometry_x_out_of_bounds",
                    "Polygon x coordinates exceed coordinate space bounds.",
                    page_index=page_index,
                    element_id=element_id,
                )
            )
        if space.height is not None and (point.y < -1e-6 or point.y > space.height + 1e-6):
            issues.append(
                _issue(
                    "geometry_y_out_of_bounds",
                    "Polygon y coordinates exceed coordinate space bounds.",
                    page_index=page_index,
                    element_id=element_id,
                )
            )


def _issue(
    code: str,
    message: str,
    *,
    severity: str = "error",
    page_index: int | None = None,
    element_id: str | None = None,
) -> CanonicalIRValidationIssue:
    return CanonicalIRValidationIssue(
        code=code,
        message=message,
        severity=severity,
        page_index=page_index,
        element_id=element_id,
    )
