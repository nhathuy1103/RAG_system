from __future__ import annotations

import math
from collections.abc import Iterable
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any

FLOAT_TOLERANCE = 1e-6


class CoordinateSpaceType(StrEnum):
    PDF_PAGE_SPACE = "PDF_PAGE_SPACE"
    RENDERED_IMAGE_SPACE = "RENDERED_IMAGE_SPACE"
    PREPROCESSED_IMAGE_SPACE = "PREPROCESSED_IMAGE_SPACE"
    OCR_INPUT_SPACE = "OCR_INPUT_SPACE"
    NORMALIZED_PAGE_SPACE = "NORMALIZED_PAGE_SPACE"


class TransformType(StrEnum):
    IDENTITY = "identity"
    RENDER = "render"
    SCALE = "scale"
    RESIZE = "resize"
    ROTATE = "rotate"
    TRANSLATE = "translate"
    CROP = "crop"
    DESKEW = "deskew"
    FLIP = "flip"
    NORMALIZE = "normalize"
    DENORMALIZE = "denormalize"
    COMPOSED = "composed"


@dataclass(frozen=True)
class CoordinateSpace:
    space_id: str
    type: str
    width: float | None
    height: float | None
    unit: str
    origin: str
    x_axis_direction: str
    y_axis_direction: str
    page_index: int
    parent_space_id: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.space_id:
            raise ValueError("coordinate space requires a space_id")
        if self.page_index < 0:
            raise ValueError("page_index must not be negative")
        if self.width is not None and (not _finite(self.width) or self.width <= 0):
            raise ValueError("coordinate space width must be positive when present")
        if self.height is not None and (not _finite(self.height) or self.height <= 0):
            raise ValueError("coordinate space height must be positive when present")
        if not self.unit:
            raise ValueError("coordinate space requires a unit")
        CoordinateSpaceType(str(self.type))

    def to_dict(self) -> dict[str, Any]:
        return {
            "space_id": self.space_id,
            "type": str(self.type),
            "width": self.width,
            "height": self.height,
            "unit": self.unit,
            "origin": self.origin,
            "x_axis_direction": self.x_axis_direction,
            "y_axis_direction": self.y_axis_direction,
            "page_index": self.page_index,
            "parent_space_id": self.parent_space_id,
            "metadata": dict(self.metadata),
        }

    @classmethod
    def from_dict(cls, value: dict[str, Any]) -> CoordinateSpace:
        return cls(
            space_id=str(value["space_id"]),
            type=str(value["type"]),
            width=_optional_float(value.get("width")),
            height=_optional_float(value.get("height")),
            unit=str(value["unit"]),
            origin=str(value["origin"]),
            x_axis_direction=str(value["x_axis_direction"]),
            y_axis_direction=str(value["y_axis_direction"]),
            page_index=int(value["page_index"]),
            parent_space_id=(
                str(value["parent_space_id"]) if value.get("parent_space_id") is not None else None
            ),
            metadata=dict(value.get("metadata") or {}),
        )


@dataclass(frozen=True)
class Point:
    x: float
    y: float
    coordinate_space_id: str

    def __post_init__(self) -> None:
        if not _finite(self.x) or not _finite(self.y):
            raise ValueError("point coordinates must be finite")
        if not self.coordinate_space_id:
            raise ValueError("point requires coordinate_space_id")

    def to_dict(self) -> dict[str, Any]:
        return {
            "x": self.x,
            "y": self.y,
            "coordinate_space_id": self.coordinate_space_id,
        }

    @classmethod
    def from_dict(cls, value: dict[str, Any]) -> Point:
        return cls(
            x=float(value["x"]),
            y=float(value["y"]),
            coordinate_space_id=str(value["coordinate_space_id"]),
        )


@dataclass(frozen=True)
class Polygon:
    points: tuple[Point, ...]
    coordinate_space_id: str

    def __post_init__(self) -> None:
        if len(self.points) < 3:
            raise ValueError("polygon requires at least three points")
        if not self.coordinate_space_id:
            raise ValueError("polygon requires coordinate_space_id")
        if any(point.coordinate_space_id != self.coordinate_space_id for point in self.points):
            raise ValueError("polygon points must share one coordinate space")

    def bounds(self) -> AxisAlignedBoundingBox:
        return AxisAlignedBoundingBox(
            x_min=min(point.x for point in self.points),
            y_min=min(point.y for point in self.points),
            x_max=max(point.x for point in self.points),
            y_max=max(point.y for point in self.points),
            coordinate_space_id=self.coordinate_space_id,
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "points": [point.to_dict() for point in self.points],
            "coordinate_space_id": self.coordinate_space_id,
        }

    @classmethod
    def from_dict(cls, value: dict[str, Any]) -> Polygon:
        return cls(
            points=tuple(Point.from_dict(point) for point in value["points"]),
            coordinate_space_id=str(value["coordinate_space_id"]),
        )


@dataclass(frozen=True)
class AxisAlignedBoundingBox:
    x_min: float
    y_min: float
    x_max: float
    y_max: float
    coordinate_space_id: str

    def __post_init__(self) -> None:
        values = (self.x_min, self.y_min, self.x_max, self.y_max)
        if not all(_finite(value) for value in values):
            raise ValueError("bbox coordinates must be finite")
        if self.x_min > self.x_max:
            raise ValueError("x_min must be <= x_max")
        if self.y_min > self.y_max:
            raise ValueError("y_min must be <= y_max")
        if not self.coordinate_space_id:
            raise ValueError("bbox requires coordinate_space_id")

    @property
    def width(self) -> float:
        return self.x_max - self.x_min

    @property
    def height(self) -> float:
        return self.y_max - self.y_min

    @property
    def area(self) -> float:
        return self.width * self.height

    def to_polygon(self) -> Polygon:
        return Polygon(
            points=(
                Point(self.x_min, self.y_min, self.coordinate_space_id),
                Point(self.x_max, self.y_min, self.coordinate_space_id),
                Point(self.x_max, self.y_max, self.coordinate_space_id),
                Point(self.x_min, self.y_max, self.coordinate_space_id),
            ),
            coordinate_space_id=self.coordinate_space_id,
        )

    def intersection_over_union(self, other: AxisAlignedBoundingBox) -> float:
        if self.coordinate_space_id != other.coordinate_space_id:
            raise ValueError("bbox IoU requires matching coordinate spaces")
        left = max(self.x_min, other.x_min)
        top = max(self.y_min, other.y_min)
        right = min(self.x_max, other.x_max)
        bottom = min(self.y_max, other.y_max)
        intersection = max(0.0, right - left) * max(0.0, bottom - top)
        union = self.area + other.area - intersection
        return intersection / union if union > 0 else 0.0

    def to_dict(self) -> dict[str, Any]:
        return {
            "x_min": self.x_min,
            "y_min": self.y_min,
            "x_max": self.x_max,
            "y_max": self.y_max,
            "coordinate_space_id": self.coordinate_space_id,
        }

    @classmethod
    def from_dict(cls, value: dict[str, Any]) -> AxisAlignedBoundingBox:
        return cls(
            x_min=float(value["x_min"]),
            y_min=float(value["y_min"]),
            x_max=float(value["x_max"]),
            y_max=float(value["y_max"]),
            coordinate_space_id=str(value["coordinate_space_id"]),
        )


@dataclass(frozen=True)
class CoordinateTransform:
    transform_id: str
    source_space_id: str
    target_space_id: str
    transform_type: str
    matrix: tuple[
        tuple[float, float, float], tuple[float, float, float], tuple[float, float, float]
    ]
    inverse_matrix: tuple[
        tuple[float, float, float], tuple[float, float, float], tuple[float, float, float]
    ]
    parameters: dict[str, Any] = field(default_factory=dict)
    applied_at_stage: str | None = None
    provider: str | None = None
    version: str = "1.0"
    invertible: bool = True
    numerical_tolerance: float = FLOAT_TOLERANCE

    def __post_init__(self) -> None:
        if not self.transform_id:
            raise ValueError("transform requires transform_id")
        if not self.source_space_id or not self.target_space_id:
            raise ValueError("transform requires source and target spaces")
        TransformType(str(self.transform_type))
        _validate_matrix(self.matrix)
        _validate_matrix(self.inverse_matrix)
        if self.numerical_tolerance <= 0:
            raise ValueError("numerical_tolerance must be positive")

    @classmethod
    def identity(
        cls,
        *,
        transform_id: str,
        source_space_id: str,
        target_space_id: str | None = None,
    ) -> CoordinateTransform:
        matrix = _identity_matrix()
        return cls(
            transform_id=transform_id,
            source_space_id=source_space_id,
            target_space_id=target_space_id or source_space_id,
            transform_type=TransformType.IDENTITY.value,
            matrix=matrix,
            inverse_matrix=matrix,
        )

    @classmethod
    def scale(
        cls,
        *,
        transform_id: str,
        source_space_id: str,
        target_space_id: str,
        scale_x: float,
        scale_y: float,
        transform_type: str = TransformType.SCALE.value,
    ) -> CoordinateTransform:
        if scale_x == 0 or scale_y == 0:
            raise ValueError("scale transform must be invertible")
        matrix = ((scale_x, 0.0, 0.0), (0.0, scale_y, 0.0), (0.0, 0.0, 1.0))
        inverse = ((1.0 / scale_x, 0.0, 0.0), (0.0, 1.0 / scale_y, 0.0), (0.0, 0.0, 1.0))
        return cls(
            transform_id=transform_id,
            source_space_id=source_space_id,
            target_space_id=target_space_id,
            transform_type=transform_type,
            matrix=matrix,
            inverse_matrix=inverse,
            parameters={"scale_x": scale_x, "scale_y": scale_y},
        )

    @classmethod
    def translate(
        cls,
        *,
        transform_id: str,
        source_space_id: str,
        target_space_id: str,
        offset_x: float,
        offset_y: float,
        transform_type: str = TransformType.TRANSLATE.value,
    ) -> CoordinateTransform:
        matrix = ((1.0, 0.0, offset_x), (0.0, 1.0, offset_y), (0.0, 0.0, 1.0))
        inverse = ((1.0, 0.0, -offset_x), (0.0, 1.0, -offset_y), (0.0, 0.0, 1.0))
        return cls(
            transform_id=transform_id,
            source_space_id=source_space_id,
            target_space_id=target_space_id,
            transform_type=transform_type,
            matrix=matrix,
            inverse_matrix=inverse,
            parameters={"offset_x": offset_x, "offset_y": offset_y},
        )

    @classmethod
    def rotate_right_angle(
        cls,
        *,
        transform_id: str,
        source_space_id: str,
        target_space_id: str,
        degrees: int,
        source_width: float,
        source_height: float,
    ) -> CoordinateTransform:
        normalized = degrees % 360
        if normalized not in {0, 90, 180, 270}:
            raise ValueError("right-angle rotation supports only 0/90/180/270")
        if normalized == 0:
            matrix = _identity_matrix()
        elif normalized == 90:
            matrix = ((0.0, -1.0, source_height), (1.0, 0.0, 0.0), (0.0, 0.0, 1.0))
        elif normalized == 180:
            matrix = ((-1.0, 0.0, source_width), (0.0, -1.0, source_height), (0.0, 0.0, 1.0))
        else:
            matrix = ((0.0, 1.0, 0.0), (-1.0, 0.0, source_width), (0.0, 0.0, 1.0))
        return cls(
            transform_id=transform_id,
            source_space_id=source_space_id,
            target_space_id=target_space_id,
            transform_type=TransformType.ROTATE.value,
            matrix=matrix,
            inverse_matrix=_invert_affine_matrix(matrix),
            parameters={
                "degrees": normalized,
                "source_width": source_width,
                "source_height": source_height,
            },
        )

    @classmethod
    def normalize(
        cls,
        *,
        transform_id: str,
        source_space_id: str,
        target_space_id: str,
        source_width: float,
        source_height: float,
    ) -> CoordinateTransform:
        return cls.scale(
            transform_id=transform_id,
            source_space_id=source_space_id,
            target_space_id=target_space_id,
            scale_x=1.0 / source_width,
            scale_y=1.0 / source_height,
            transform_type=TransformType.NORMALIZE.value,
        )

    @classmethod
    def denormalize(
        cls,
        *,
        transform_id: str,
        source_space_id: str,
        target_space_id: str,
        target_width: float,
        target_height: float,
    ) -> CoordinateTransform:
        return cls.scale(
            transform_id=transform_id,
            source_space_id=source_space_id,
            target_space_id=target_space_id,
            scale_x=target_width,
            scale_y=target_height,
            transform_type=TransformType.DENORMALIZE.value,
        )

    def transform_point(self, point: Point) -> Point:
        if point.coordinate_space_id != self.source_space_id:
            raise ValueError("point coordinate space does not match transform source")
        x, y = _apply_matrix(self.matrix, point.x, point.y)
        return Point(x, y, self.target_space_id)

    def inverse_transform_point(self, point: Point) -> Point:
        if point.coordinate_space_id != self.target_space_id:
            raise ValueError("point coordinate space does not match transform target")
        x, y = _apply_matrix(self.inverse_matrix, point.x, point.y)
        return Point(x, y, self.source_space_id)

    def transform_polygon(self, polygon: Polygon) -> Polygon:
        return Polygon(
            points=tuple(self.transform_point(point) for point in polygon.points),
            coordinate_space_id=self.target_space_id,
        )

    def inverse_transform_polygon(self, polygon: Polygon) -> Polygon:
        return Polygon(
            points=tuple(self.inverse_transform_point(point) for point in polygon.points),
            coordinate_space_id=self.source_space_id,
        )

    def transform_bbox(self, bbox: AxisAlignedBoundingBox) -> AxisAlignedBoundingBox:
        return self.transform_polygon(bbox.to_polygon()).bounds()

    def inverse_transform_bbox(self, bbox: AxisAlignedBoundingBox) -> AxisAlignedBoundingBox:
        return self.inverse_transform_polygon(bbox.to_polygon()).bounds()

    def to_dict(self) -> dict[str, Any]:
        return {
            "transform_id": self.transform_id,
            "source_space_id": self.source_space_id,
            "target_space_id": self.target_space_id,
            "transform_type": self.transform_type,
            "matrix": [list(row) for row in self.matrix],
            "inverse_matrix": [list(row) for row in self.inverse_matrix],
            "parameters": dict(self.parameters),
            "applied_at_stage": self.applied_at_stage,
            "provider": self.provider,
            "version": self.version,
            "invertible": self.invertible,
            "numerical_tolerance": self.numerical_tolerance,
        }

    @classmethod
    def from_dict(cls, value: dict[str, Any]) -> CoordinateTransform:
        return cls(
            transform_id=str(value["transform_id"]),
            source_space_id=str(value["source_space_id"]),
            target_space_id=str(value["target_space_id"]),
            transform_type=str(value["transform_type"]),
            matrix=_matrix_from_any(value["matrix"]),
            inverse_matrix=_matrix_from_any(value["inverse_matrix"]),
            parameters=dict(value.get("parameters") or {}),
            applied_at_stage=(
                str(value["applied_at_stage"])
                if value.get("applied_at_stage") is not None
                else None
            ),
            provider=str(value["provider"]) if value.get("provider") is not None else None,
            version=str(value.get("version") or "1.0"),
            invertible=bool(value.get("invertible", True)),
            numerical_tolerance=float(value.get("numerical_tolerance") or FLOAT_TOLERANCE),
        )


def transform_point(point: Point, transform: CoordinateTransform) -> Point:
    return transform.transform_point(point)


def transform_polygon(polygon: Polygon, transform: CoordinateTransform) -> Polygon:
    return transform.transform_polygon(polygon)


def transform_bbox(
    bbox: AxisAlignedBoundingBox,
    transform: CoordinateTransform,
) -> AxisAlignedBoundingBox:
    return transform.transform_bbox(bbox)


def inverse_transform_point(point: Point, transform: CoordinateTransform) -> Point:
    return transform.inverse_transform_point(point)


def inverse_transform_polygon(polygon: Polygon, transform: CoordinateTransform) -> Polygon:
    return transform.inverse_transform_polygon(polygon)


def inverse_transform_bbox(
    bbox: AxisAlignedBoundingBox,
    transform: CoordinateTransform,
) -> AxisAlignedBoundingBox:
    return transform.inverse_transform_bbox(bbox)


def compose_transforms(
    transforms: Iterable[CoordinateTransform],
    *,
    transform_id: str = "composed-transform",
) -> CoordinateTransform:
    ordered = list(transforms)
    if not ordered:
        raise ValueError("compose_transforms requires at least one transform")
    for left, right in zip(ordered, ordered[1:], strict=False):
        if left.target_space_id != right.source_space_id:
            raise ValueError("cannot compose transforms with non-contiguous spaces")
    matrix = _identity_matrix()
    for transform in ordered:
        matrix = _matrix_multiply(transform.matrix, matrix)
    inverse = _identity_matrix()
    for transform in reversed(ordered):
        inverse = _matrix_multiply(transform.inverse_matrix, inverse)
    return CoordinateTransform(
        transform_id=transform_id,
        source_space_id=ordered[0].source_space_id,
        target_space_id=ordered[-1].target_space_id,
        transform_type=TransformType.COMPOSED.value,
        matrix=matrix,
        inverse_matrix=inverse,
        parameters={"component_transform_ids": [item.transform_id for item in ordered]},
    )


def validate_transform_chain(transforms: Iterable[CoordinateTransform]) -> tuple[str, ...]:
    issues: list[str] = []
    ordered = list(transforms)
    seen = set()
    for transform in ordered:
        if transform.transform_id in seen:
            issues.append(f"duplicate_transform_id:{transform.transform_id}")
        seen.add(transform.transform_id)
        if not transform.invertible:
            issues.append(f"non_invertible_transform:{transform.transform_id}")
    for left, right in zip(ordered, ordered[1:], strict=False):
        if left.target_space_id != right.source_space_id:
            issues.append(f"transform_chain_break:{left.transform_id}->{right.transform_id}")
    return tuple(issues)


def _finite(value: float) -> bool:
    return math.isfinite(float(value))


def _optional_float(value: Any) -> float | None:
    if value is None:
        return None
    return float(value)


def _validate_matrix(
    matrix: tuple[
        tuple[float, float, float], tuple[float, float, float], tuple[float, float, float]
    ],
) -> None:
    if len(matrix) != 3 or any(len(row) != 3 for row in matrix):
        raise ValueError("affine matrix must be 3x3")
    if not all(_finite(value) for row in matrix for value in row):
        raise ValueError("affine matrix values must be finite")


def _identity_matrix() -> tuple[
    tuple[float, float, float], tuple[float, float, float], tuple[float, float, float]
]:
    return ((1.0, 0.0, 0.0), (0.0, 1.0, 0.0), (0.0, 0.0, 1.0))


def _matrix_from_any(
    value: Any,
) -> tuple[tuple[float, float, float], tuple[float, float, float], tuple[float, float, float]]:
    rows = tuple(tuple(float(item) for item in row) for row in value)
    if len(rows) != 3 or any(len(row) != 3 for row in rows):
        raise ValueError("affine matrix must be 3x3")
    return rows  # type: ignore[return-value]


def _matrix_multiply(
    left: tuple[tuple[float, float, float], tuple[float, float, float], tuple[float, float, float]],
    right: tuple[
        tuple[float, float, float], tuple[float, float, float], tuple[float, float, float]
    ],
) -> tuple[tuple[float, float, float], tuple[float, float, float], tuple[float, float, float]]:
    return tuple(
        tuple(
            sum(left[row][index] * right[index][column] for index in range(3))
            for column in range(3)
        )
        for row in range(3)
    )  # type: ignore[return-value]


def _apply_matrix(
    matrix: tuple[
        tuple[float, float, float], tuple[float, float, float], tuple[float, float, float]
    ],
    x: float,
    y: float,
) -> tuple[float, float]:
    target_x = matrix[0][0] * x + matrix[0][1] * y + matrix[0][2]
    target_y = matrix[1][0] * x + matrix[1][1] * y + matrix[1][2]
    weight = matrix[2][0] * x + matrix[2][1] * y + matrix[2][2]
    if abs(weight) <= FLOAT_TOLERANCE:
        raise ValueError("homogeneous transform produced zero weight")
    return target_x / weight, target_y / weight


def _invert_affine_matrix(
    matrix: tuple[
        tuple[float, float, float], tuple[float, float, float], tuple[float, float, float]
    ],
) -> tuple[tuple[float, float, float], tuple[float, float, float], tuple[float, float, float]]:
    a, b, c = matrix[0]
    d, e, f = matrix[1]
    determinant = a * e - b * d
    if abs(determinant) <= FLOAT_TOLERANCE:
        raise ValueError("affine transform is not invertible")
    inverse_a = e / determinant
    inverse_b = -b / determinant
    inverse_d = -d / determinant
    inverse_e = a / determinant
    inverse_c = -(inverse_a * c + inverse_b * f)
    inverse_f = -(inverse_d * c + inverse_e * f)
    return (
        (inverse_a, inverse_b, inverse_c),
        (inverse_d, inverse_e, inverse_f),
        (0.0, 0.0, 1.0),
    )
