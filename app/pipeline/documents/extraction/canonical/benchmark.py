from __future__ import annotations

import argparse
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from app.pipeline.documents.extraction.canonical.geometry import (
    AxisAlignedBoundingBox,
    CoordinateTransform,
    Point,
    Polygon,
    TransformType,
    compose_transforms,
    validate_transform_chain,
)

GEOMETRY_BENCHMARK_VERSION = "1.0.0"
ERROR_TOLERANCE = 1e-6
IOU_TOLERANCE = 1.0 - 1e-9


@dataclass(frozen=True)
class GeometryFixture:
    name: str
    transform: CoordinateTransform
    point: Point
    polygon: Polygon
    bbox: AxisAlignedBoundingBox


def run_geometry_benchmark() -> dict[str, Any]:
    fixtures = _fixtures()
    fixture_results = [_evaluate_fixture(fixture) for fixture in fixtures]
    invalid_transform_chain_count = len(
        validate_transform_chain(
            [
                CoordinateTransform.identity(
                    transform_id="invalid-a-to-b",
                    source_space_id="invalid-a",
                    target_space_id="invalid-b",
                ),
                CoordinateTransform.identity(
                    transform_id="invalid-c-to-d",
                    source_space_id="invalid-c",
                    target_space_id="invalid-d",
                ),
            ]
        )
    )
    max_point_error = max(
        (result["point_round_trip_error"] for result in fixture_results),
        default=0.0,
    )
    max_polygon_error = max(
        (result["polygon_round_trip_error"] for result in fixture_results),
        default=0.0,
    )
    max_bbox_error = max(
        (result["bbox_corner_error"] for result in fixture_results),
        default=0.0,
    )
    min_bbox_iou = min((result["bbox_iou"] for result in fixture_results), default=1.0)
    out_of_bounds_count = sum(result["out_of_bounds"] for result in fixture_results)
    status = (
        "PASS"
        if (
            fixtures
            and max_point_error <= ERROR_TOLERANCE
            and max_polygon_error <= ERROR_TOLERANCE
            and max_bbox_error <= ERROR_TOLERANCE
            and min_bbox_iou >= IOU_TOLERANCE
            and out_of_bounds_count == 0
            and invalid_transform_chain_count > 0
        )
        else "FAIL"
    )
    return {
        "benchmark_name": "phase1_geometry_transform_benchmark",
        "benchmark_version": GEOMETRY_BENCHMARK_VERSION,
        "fixture_count": len(fixtures),
        "fixtures": fixture_results,
        "metrics": {
            "point_round_trip_error": max_point_error,
            "polygon_round_trip_error": max_polygon_error,
            "bbox_corner_error": max_bbox_error,
            "bbox_iou": min_bbox_iou,
            "out_of_bounds_rate": out_of_bounds_count / len(fixtures) if fixtures else 1.0,
            "invalid_transform_chain_count": invalid_transform_chain_count,
            "unmapped_legacy_field_count": 0,
        },
        "status": status,
    }


def _fixtures() -> list[GeometryFixture]:
    source = "page-0-rendered-image"
    normalized = "page-0-normalized"
    bbox = AxisAlignedBoundingBox(10, 20, 40, 60, source)
    polygon = Polygon(
        (
            Point(10, 20, source),
            Point(40, 20, source),
            Point(40, 60, source),
            Point(10, 60, source),
        ),
        source,
    )
    point = Point(25, 35, source)
    scale_up = CoordinateTransform.scale(
        transform_id="scale-up",
        source_space_id=source,
        target_space_id="scale-up-space",
        scale_x=2.0,
        scale_y=2.0,
    )
    scale_down = CoordinateTransform.scale(
        transform_id="scale-down",
        source_space_id=source,
        target_space_id="scale-down-space",
        scale_x=0.5,
        scale_y=0.5,
    )
    scale_for_composed = CoordinateTransform.scale(
        transform_id="composed-scale",
        source_space_id=source,
        target_space_id="composed-scaled",
        scale_x=2.0,
        scale_y=2.0,
    )
    rotate_for_composed = CoordinateTransform.rotate_right_angle(
        transform_id="composed-rotate-90",
        source_space_id="composed-scaled",
        target_space_id="composed-rotated",
        degrees=90,
        source_width=200,
        source_height=100,
    )
    normalize = CoordinateTransform.normalize(
        transform_id="normalize",
        source_space_id=source,
        target_space_id=normalized,
        source_width=100,
        source_height=50,
    )
    multi_scale = CoordinateTransform.scale(
        transform_id="multi-scale",
        source_space_id=source,
        target_space_id="multi-scaled",
        scale_x=1.5,
        scale_y=1.5,
    )
    multi_translate = CoordinateTransform.translate(
        transform_id="multi-translate",
        source_space_id="multi-scaled",
        target_space_id="multi-translated",
        offset_x=7,
        offset_y=11,
    )
    multi_rotate = CoordinateTransform.rotate_right_angle(
        transform_id="multi-rotate-270",
        source_space_id="multi-translated",
        target_space_id="multi-rotated",
        degrees=270,
        source_width=160,
        source_height=90,
    )
    return [
        GeometryFixture(
            "no_rotation_identity",
            CoordinateTransform.identity(
                transform_id="identity",
                source_space_id=source,
                target_space_id=source,
            ),
            point,
            polygon,
            bbox,
        ),
        GeometryFixture(
            "rotation_90",
            CoordinateTransform.rotate_right_angle(
                transform_id="rotate-90",
                source_space_id=source,
                target_space_id="rotated-90",
                degrees=90,
                source_width=100,
                source_height=50,
            ),
            point,
            polygon,
            bbox,
        ),
        GeometryFixture(
            "rotation_180",
            CoordinateTransform.rotate_right_angle(
                transform_id="rotate-180",
                source_space_id=source,
                target_space_id="rotated-180",
                degrees=180,
                source_width=100,
                source_height=50,
            ),
            point,
            polygon,
            bbox,
        ),
        GeometryFixture(
            "rotation_270",
            CoordinateTransform.rotate_right_angle(
                transform_id="rotate-270",
                source_space_id=source,
                target_space_id="rotated-270",
                degrees=270,
                source_width=100,
                source_height=50,
            ),
            point,
            polygon,
            bbox,
        ),
        GeometryFixture("scale_up", scale_up, point, polygon, bbox),
        GeometryFixture("scale_down", scale_down, point, polygon, bbox),
        GeometryFixture(
            "crop_translation",
            CoordinateTransform.translate(
                transform_id="crop-translation",
                source_space_id=source,
                target_space_id="cropped-space",
                offset_x=-5,
                offset_y=-10,
                transform_type=TransformType.CROP.value,
            ),
            point,
            polygon,
            bbox,
        ),
        GeometryFixture(
            "composed_scale_rotation",
            compose_transforms(
                [scale_for_composed, rotate_for_composed],
                transform_id="composed-scale-rotation",
            ),
            point,
            polygon,
            bbox,
        ),
        GeometryFixture(
            "normalized_conversion",
            normalize,
            point,
            polygon,
            bbox,
        ),
        GeometryFixture(
            "multi_step_inverse",
            compose_transforms(
                [multi_scale, multi_translate, multi_rotate],
                transform_id="multi-step-inverse",
            ),
            point,
            polygon,
            bbox,
        ),
    ]


def _evaluate_fixture(fixture: GeometryFixture) -> dict[str, Any]:
    target_point = fixture.transform.transform_point(fixture.point)
    round_trip_point = fixture.transform.inverse_transform_point(target_point)
    target_polygon = fixture.transform.transform_polygon(fixture.polygon)
    round_trip_polygon = fixture.transform.inverse_transform_polygon(target_polygon)
    target_bbox = fixture.transform.transform_bbox(fixture.bbox)
    round_trip_bbox = fixture.transform.inverse_transform_bbox(target_bbox)
    point_error = _point_error(fixture.point, round_trip_point)
    polygon_error = max(
        (
            _point_error(expected, actual)
            for expected, actual in zip(
                fixture.polygon.points,
                round_trip_polygon.points,
                strict=True,
            )
        ),
        default=0.0,
    )
    bbox_error = _bbox_error(fixture.bbox, round_trip_bbox)
    return {
        "name": fixture.name,
        "transform_id": fixture.transform.transform_id,
        "transform_type": fixture.transform.transform_type,
        "point_round_trip_error": point_error,
        "polygon_round_trip_error": polygon_error,
        "bbox_corner_error": bbox_error,
        "bbox_iou": fixture.bbox.intersection_over_union(round_trip_bbox),
        "out_of_bounds": int(
            any(
                not _is_finite(value)
                for value in (
                    target_bbox.x_min,
                    target_bbox.y_min,
                    target_bbox.x_max,
                    target_bbox.y_max,
                )
            )
        ),
    }


def _point_error(left: Point, right: Point) -> float:
    return max(abs(left.x - right.x), abs(left.y - right.y))


def _bbox_error(
    left: AxisAlignedBoundingBox,
    right: AxisAlignedBoundingBox,
) -> float:
    return max(
        abs(left.x_min - right.x_min),
        abs(left.y_min - right.y_min),
        abs(left.x_max - right.x_max),
        abs(left.y_max - right.y_max),
    )


def _is_finite(value: float) -> bool:
    return value == value and abs(value) != float("inf")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run Phase 1 geometry benchmark.")
    parser.add_argument("--output", required=True, help="Path to write benchmark JSON.")
    args = parser.parse_args(argv)
    result = run_geometry_benchmark()
    output_path = Path(args.output)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(
        json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True),
        encoding="utf-8",
    )
    return 0 if result["status"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
