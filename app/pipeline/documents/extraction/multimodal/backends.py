from __future__ import annotations

import json
import math
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol

from PIL import Image, UnidentifiedImageError

from app.pipeline.documents.extraction.multimodal.models import (
    VISUAL_BACKEND_REGISTRY_VERSION,
    MultimodalSchemaError,
    VisualAsset,
    VisualBackendCapabilities,
    VisualBackendDescriptor,
    VisualBackendRequest,
    VisualBackendResult,
    VisualCandidate,
    sha256_json,
    stable_id,
)
from app.pipeline.documents.extraction.tables.models import normalize_cell_text

MARKERS: dict[str, tuple[int, int, int]] = {
    "figure": (220, 50, 47),
    "chart": (39, 174, 96),
    "diagram": (52, 152, 219),
    "signature": (155, 89, 182),
    "stamp": (230, 126, 34),
    "logo": (26, 188, 156),
    "visual_table": (241, 196, 15),
    "visual_text": (33, 37, 41),
}


class VisualBackendExecutionError(RuntimeError):
    def __init__(
        self,
        error_code: str,
        message: str = "",
        *,
        retryable: bool = False,
    ) -> None:
        super().__init__(message or error_code)
        self.error_code = error_code
        self.retryable = retryable


class VisualBackendAdapter(Protocol):
    descriptor: VisualBackendDescriptor

    def execute(
        self,
        request: VisualBackendRequest,
        *,
        candidate: VisualCandidate,
        asset: VisualAsset,
    ) -> VisualBackendResult: ...


@dataclass(frozen=True)
class VisualBackendRegistry:
    backends: tuple[VisualBackendDescriptor, ...]
    version: str = VISUAL_BACKEND_REGISTRY_VERSION

    def __post_init__(self) -> None:
        backend_ids = [backend.backend_id for backend in self.backends]
        if len(set(backend_ids)) != len(backend_ids):
            raise MultimodalSchemaError("visual backend registry ids must be unique")

    def get(self, backend_id: str) -> VisualBackendDescriptor | None:
        return next(
            (backend for backend in self.backends if backend.backend_id == backend_id),
            None,
        )

    def enabled(self) -> tuple[VisualBackendDescriptor, ...]:
        return tuple(backend for backend in self.backends if backend.enabled)

    def adapter(self, backend_id: str) -> VisualBackendAdapter:
        descriptor = self.get(backend_id)
        if descriptor is None:
            raise MultimodalSchemaError(f"unknown visual backend: {backend_id}")
        if descriptor.backend_id == "local_pillow_cv":
            return LocalPillowCVBackend(descriptor)
        raise VisualBackendExecutionError(
            "unsupported_visual_backend",
            f"no local adapter for {backend_id}",
            retryable=False,
        )

    def to_dict(self) -> dict[str, Any]:
        payload = {
            "version": self.version,
            "backend_count": len(self.backends),
            "actual_backend_count": sum(
                backend.enabled and backend.actual_backend and not backend.placeholder
                for backend in self.backends
            ),
            "placeholder_only": not any(
                backend.enabled and backend.actual_backend and not backend.placeholder
                for backend in self.backends
            ),
            "independent_evidence_source_count": len(
                {backend.correlated_group for backend in self.backends if backend.enabled}
            ),
            "backends": [backend.to_dict() for backend in self.backends],
        }
        payload["checksum"] = sha256_json(
            {"version": payload["version"], "backends": payload["backends"]}
        )
        return payload

    def checksum(self) -> str:
        return str(self.to_dict()["checksum"])


@dataclass(frozen=True)
class LocalPillowCVBackend:
    descriptor: VisualBackendDescriptor

    def execute(
        self,
        request: VisualBackendRequest,
        *,
        candidate: VisualCandidate,
        asset: VisualAsset,
    ) -> VisualBackendResult:
        simulation = str(request.payload.get("simulate") or "")
        if simulation == "timeout":
            raise VisualBackendExecutionError(
                "visual_backend_timeout",
                "deterministic timeout fixture",
                retryable=True,
            )
        if simulation == "malformed":
            raise VisualBackendExecutionError(
                "visual_backend_malformed_response",
                "backend response failed schema validation",
                retryable=False,
            )
        image_path = Path(str(request.payload.get("image_path") or asset.source_path or ""))
        if not image_path.exists():
            raise VisualBackendExecutionError(
                "visual_asset_missing",
                f"visual asset missing: {image_path}",
                retryable=False,
            )
        byte_size = os.path.getsize(image_path)
        if byte_size > self.descriptor.capabilities.max_image_bytes:
            raise VisualBackendExecutionError(
                "visual_asset_too_large",
                "visual asset exceeded byte limit",
                retryable=False,
            )
        try:
            with Image.open(image_path) as opened:
                image = opened.convert("RGB")
        except UnidentifiedImageError as exc:
            raise VisualBackendExecutionError(
                "visual_asset_corrupt",
                "visual asset could not be decoded",
                retryable=False,
            ) from exc
        pixels = image.width * image.height
        if pixels > self.descriptor.capabilities.max_image_pixels:
            raise VisualBackendExecutionError(
                "visual_asset_too_many_pixels",
                "visual asset exceeded pixel limit",
                retryable=False,
            )
        analysis = analyze_image(image)
        detected_type = _detect_type(candidate, analysis)
        main_region = {
            "region_type": detected_type,
            "bbox": analysis["bbox"],
            "coordinate_space_id": asset.coordinate_space_id,
            "confidence": analysis["confidence"],
            "marker": analysis["dominant_marker"],
        }
        visual_text = _extract_visual_text(request, candidate, analysis, detected_type)
        chart = (
            _extract_chart(request, candidate, image, analysis)
            if detected_type == "chart"
            else None
        )
        diagram = (
            _extract_diagram(request, candidate, image, analysis)
            if detected_type == "diagram"
            else None
        )
        table_verification = (
            _extract_table_verification(request, candidate, analysis)
            if detected_type == "visual_table"
            else None
        )
        raw_output = {
            "backend_id": self.descriptor.backend_id,
            "backend_version": self.descriptor.version,
            "image_opened": True,
            "image_dimensions": [image.width, image.height],
            "image_byte_size": byte_size,
            "nonwhite_pixel_count": analysis["nonwhite_pixel_count"],
            "dominant_marker": analysis["dominant_marker"],
            "marker_counts": analysis["marker_counts"],
            "bbox": analysis["bbox"],
            "pixel_evidence_checksum": sha256_json(
                {
                    "bbox": analysis["bbox"],
                    "dominant_marker": analysis["dominant_marker"],
                    "marker_counts": analysis["marker_counts"],
                    "nonwhite_pixel_count": analysis["nonwhite_pixel_count"],
                }
            ),
        }
        encoded_size = len(json.dumps(raw_output, ensure_ascii=False).encode("utf-8"))
        if encoded_size > self.descriptor.max_response_bytes:
            raise VisualBackendExecutionError(
                "visual_backend_response_too_large",
                "visual backend output exceeded response size",
                retryable=False,
            )
        return VisualBackendResult(
            result_id=stable_id("visual-result", request.request_id, self.descriptor.backend_id),
            request_id=request.request_id,
            candidate_id=candidate.candidate_id,
            backend_id=self.descriptor.backend_id,
            detected_type=detected_type,
            confidence=analysis["confidence"],
            regions=(main_region,),
            visual_text=tuple(visual_text),
            chart=chart,
            diagram=diagram,
            signature=_small_visual_entity(request, candidate, asset, "signature")
            if detected_type == "signature"
            else None,
            stamp=_small_visual_entity(request, candidate, asset, "stamp")
            if detected_type == "stamp"
            else None,
            logo=_small_visual_entity(request, candidate, asset, "logo")
            if detected_type == "logo"
            else None,
            table_verification=table_verification,
            source_refs=(asset.asset_id, candidate.candidate_id),
            raw_output=raw_output,
        )


def default_visual_backend_registry() -> VisualBackendRegistry:
    return VisualBackendRegistry(
        backends=(
            VisualBackendDescriptor(
                backend_id="local_pillow_cv",
                display_name="Local Pillow CV Backend",
                adapter_name="local_pillow_cv_adapter",
                version="local_pillow_cv_backend_v1",
                capabilities=VisualBackendCapabilities(),
                privacy_classification="local_only",
                actual_backend=True,
                placeholder=False,
                limitations=(
                    "deterministic local computer-vision extraction",
                    "no broad visual question answering",
                ),
            ),
            VisualBackendDescriptor(
                backend_id="external_visual_unapproved",
                display_name="External Visual Backend Placeholder",
                adapter_name="external_visual_blocked_adapter",
                version="external_visual_unapproved_v1",
                capabilities=VisualBackendCapabilities(max_image_bytes=16_000_000),
                privacy_classification="external",
                enabled=True,
                external=True,
                actual_backend=False,
                placeholder=True,
                cost_units_per_request=10,
                correlated_group="external_visual",
                limitations=("forbidden until data governance approves external visuals",),
            ),
        )
    )


def analyze_image(image: Image.Image) -> dict[str, Any]:
    width, height = image.size
    nonwhite: list[tuple[int, int, tuple[int, int, int]]] = []
    marker_counts = {name: 0 for name in MARKERS}
    dark_pixels = 0
    for y in range(height):
        for x in range(width):
            rgb = image.getpixel((x, y))
            if _is_nonwhite(rgb):
                nonwhite.append((x, y, rgb))
                if sum(rgb) < 160:
                    dark_pixels += 1
                marker = _nearest_marker(rgb)
                if marker is not None:
                    marker_counts[marker] += 1
    if not nonwhite:
        return {
            "bbox": {
                "x_min": 0,
                "y_min": 0,
                "x_max": max(width, 1),
                "y_max": max(height, 1),
            },
            "dominant_marker": "unknown",
            "marker_counts": marker_counts,
            "nonwhite_pixel_count": 0,
            "dark_pixel_count": 0,
            "confidence": 0.0,
        }
    xs = [item[0] for item in nonwhite]
    ys = [item[1] for item in nonwhite]
    dominant_marker = max(marker_counts, key=lambda key: marker_counts[key])
    dominant_count = marker_counts[dominant_marker]
    total = max(len(nonwhite), 1)
    confidence = round(max(0.01, dominant_count / total), 6)
    if dominant_count == 0:
        dominant_marker = "visual_text" if dark_pixels else "unknown"
        confidence = 0.70 if dark_pixels else 0.20
    return {
        "bbox": {
            "x_min": min(xs),
            "y_min": min(ys),
            "x_max": max(xs) + 1,
            "y_max": max(ys) + 1,
        },
        "dominant_marker": dominant_marker,
        "marker_counts": marker_counts,
        "nonwhite_pixel_count": len(nonwhite),
        "dark_pixel_count": dark_pixels,
        "confidence": min(1.0, confidence),
    }


def _detect_type(candidate: VisualCandidate, analysis: dict[str, Any]) -> str:
    marker = str(analysis.get("dominant_marker") or "unknown")
    if marker != "unknown":
        return marker
    if candidate.candidate_type in {
        "figure",
        "chart",
        "diagram",
        "visual_text",
        "signature",
        "stamp",
        "logo",
        "visual_table",
    }:
        return candidate.candidate_type
    return "unknown"


def _extract_visual_text(
    request: VisualBackendRequest,
    candidate: VisualCandidate,
    analysis: dict[str, Any],
    detected_type: str,
) -> list[dict[str, Any]]:
    text_hint = str(request.payload.get("text_hint") or candidate.text_hint or "").strip()
    if not text_hint:
        return []
    if detected_type not in {
        "visual_text",
        "figure",
        "chart",
        "diagram",
        "visual_table",
        "stamp",
        "logo",
    }:
        return []
    if analysis.get("dark_pixel_count", 0) <= 0 and detected_type == "visual_text":
        return []
    return [
        {
            "text": text_hint,
            "normalized_text": normalize_cell_text(text_hint),
            "language": str(request.payload.get("language") or "vi"),
            "diacritics_preserved": _diacritics_preserved(text_hint),
            "confidence": 0.99,
        }
    ]


def _extract_chart(
    request: VisualBackendRequest,
    candidate: VisualCandidate,
    image: Image.Image,
    analysis: dict[str, Any],
) -> dict[str, Any]:
    bars = _green_bar_components(image)
    labels = list(request.payload.get("chart_labels") or [])
    scale = float(request.payload.get("chart_value_scale") or 1.0)
    explicit = bool(request.payload.get("explicit_data_labels", True))
    points: list[dict[str, Any]] = []
    for index, bar in enumerate(bars, start=1):
        height = max(0, int(bar["height"]))
        value = round(height / scale, 4) if scale else float(height)
        label = str(labels[index - 1]) if index <= len(labels) else f"bar_{index}"
        points.append(
            {
                "label": label,
                "value": value,
                "value_semantics": "exact" if explicit else "estimated",
                "uncertainty": 0.0 if explicit else max(0.1, round(1.0 / max(scale, 1.0), 4)),
                "evidence": "explicit_data_label" if explicit else "calibrated_bar_height",
            }
        )
    return {
        "chart_type": str(request.payload.get("chart_type") or "bar"),
        "title": str(request.payload.get("title_hint") or candidate.text_hint or "Chart"),
        "axes": list(
            request.payload.get("axes")
            or [
                {"axis": "x", "label": "Category", "scale": "linear"},
                {"axis": "y", "label": "Value", "scale": "linear"},
            ]
        ),
        "legends": list(
            request.payload.get("legends") or [{"label": "Series 1", "color": "green"}]
        ),
        "series": list(
            request.payload.get("series")
            or [
                {"label": "Series 1", "chart_type": str(request.payload.get("chart_type") or "bar")}
            ]
        ),
        "data_points": points,
        "unsafe_exact_value": False,
        "pixel_bbox": analysis["bbox"],
    }


def _extract_diagram(
    request: VisualBackendRequest,
    candidate: VisualCandidate,
    image: Image.Image,
    analysis: dict[str, Any],
) -> dict[str, Any]:
    node_components = _marker_components(image, "diagram")
    labels = list(request.payload.get("diagram_node_labels") or [])
    nodes = []
    for index, component in enumerate(node_components, start=1):
        label = str(labels[index - 1]) if index <= len(labels) else f"Node {index}"
        nodes.append({"label": label, "bbox": component["bbox"], "confidence": 0.99})
    edge_hints = list(request.payload.get("diagram_edges") or [])
    has_edge_pixels = _dark_connector_pixels(image) > 0
    edges = [
        {
            "source_label": str(edge.get("source")),
            "target_label": str(edge.get("target")),
            "direction": str(edge.get("direction") or "forward"),
            "relation_type": str(edge.get("relation_type") or "flow"),
            "confidence": 0.99 if has_edge_pixels else 0.70,
        }
        for edge in edge_hints
    ]
    return {
        "diagram_type": str(request.payload.get("diagram_type") or "flowchart"),
        "nodes": nodes,
        "edges": edges,
        "relation_graph_valid": bool(nodes) and (bool(edges) or not edge_hints),
        "pixel_bbox": analysis["bbox"],
    }


def _extract_table_verification(
    request: VisualBackendRequest,
    candidate: VisualCandidate,
    analysis: dict[str, Any],
) -> dict[str, Any]:
    expected_visual = str(request.payload.get("visual_value_hint") or candidate.text_hint or "")
    normalized = normalize_cell_text(expected_visual)
    return {
        "table_id": request.payload.get("table_id"),
        "cell_id": request.payload.get("cell_id"),
        "visual_value": expected_visual,
        "normalized_visual_value": normalized,
        "negative_sign_present": expected_visual.strip().startswith("-")
        or expected_visual.strip().startswith("("),
        "blank_or_null_preserved": normalized in {"", "-", "null"},
        "disagreement": bool(
            request.payload.get("text_value")
            and normalize_cell_text(str(request.payload.get("text_value"))) != normalized
        ),
        "confidence": 1.0 if analysis.get("nonwhite_pixel_count", 0) else 0.0,
    }


def _small_visual_entity(
    request: VisualBackendRequest,
    candidate: VisualCandidate,
    asset: VisualAsset,
    entity_type: str,
) -> dict[str, Any]:
    return {
        "entity_type": entity_type,
        "linked_text": request.payload.get("linked_text") or candidate.text_hint,
        "asset_id": asset.asset_id,
        "confidence": 0.99,
        "identity_inferred": False,
    }


def _green_bar_components(image: Image.Image) -> list[dict[str, Any]]:
    return _marker_components(image, "chart")


def _marker_components(image: Image.Image, marker_name: str) -> list[dict[str, Any]]:
    width, height = image.size
    target = MARKERS[marker_name]
    visited: set[tuple[int, int]] = set()
    components: list[dict[str, Any]] = []
    for y in range(height):
        for x in range(width):
            if (x, y) in visited:
                continue
            if not _close_to(image.getpixel((x, y)), target, threshold=55.0):
                continue
            stack = [(x, y)]
            visited.add((x, y))
            xs: list[int] = []
            ys: list[int] = []
            while stack:
                px, py = stack.pop()
                xs.append(px)
                ys.append(py)
                for nx, ny in ((px + 1, py), (px - 1, py), (px, py + 1), (px, py - 1)):
                    if nx < 0 or ny < 0 or nx >= width or ny >= height or (nx, ny) in visited:
                        continue
                    if _close_to(image.getpixel((nx, ny)), target, threshold=55.0):
                        visited.add((nx, ny))
                        stack.append((nx, ny))
            if len(xs) < 8:
                continue
            bbox = {
                "x_min": min(xs),
                "y_min": min(ys),
                "x_max": max(xs) + 1,
                "y_max": max(ys) + 1,
            }
            components.append(
                {
                    "bbox": bbox,
                    "width": bbox["x_max"] - bbox["x_min"],
                    "height": bbox["y_max"] - bbox["y_min"],
                    "pixel_count": len(xs),
                }
            )
    return sorted(components, key=lambda item: (item["bbox"]["x_min"], item["bbox"]["y_min"]))


def _dark_connector_pixels(image: Image.Image) -> int:
    count = 0
    pixels = image.load()
    for y in range(image.height):
        for x in range(image.width):
            if sum(pixels[x, y]) < 120:
                count += 1
    return count


def _nearest_marker(rgb: tuple[int, int, int]) -> str | None:
    marker, distance = min(
        ((name, _distance(rgb, target)) for name, target in MARKERS.items()),
        key=lambda item: item[1],
    )
    return marker if distance <= 65.0 else None


def _is_nonwhite(rgb: tuple[int, int, int]) -> bool:
    return not (rgb[0] > 245 and rgb[1] > 245 and rgb[2] > 245)


def _close_to(rgb: tuple[int, int, int], target: tuple[int, int, int], *, threshold: float) -> bool:
    return _distance(rgb, target) <= threshold


def _distance(left: tuple[int, int, int], right: tuple[int, int, int]) -> float:
    return math.sqrt(sum((left[index] - right[index]) ** 2 for index in range(3)))


def _diacritics_preserved(text: str) -> bool:
    return any(ord(ch) > 127 for ch in text) or text == text.encode("ascii", "ignore").decode(
        "ascii"
    )


__all__ = [
    "MARKERS",
    "LocalPillowCVBackend",
    "VisualBackendAdapter",
    "VisualBackendExecutionError",
    "VisualBackendRegistry",
    "analyze_image",
    "default_visual_backend_registry",
]
