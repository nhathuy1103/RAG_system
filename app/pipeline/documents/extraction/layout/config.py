from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from dataclasses import asdict, dataclass
from enum import StrEnum
from typing import Any

from app.pipeline.documents.extraction.layout.models import (
    BLOCK_CLASSIFIER_VERSION,
    LAYOUT_DETECTOR_VERSION,
    LAYOUT_SCHEMA_VERSION,
    READING_ORDER_POLICY_VERSION,
)


class LayoutMode(StrEnum):
    LEGACY = "legacy"
    SHADOW = "shadow"
    ACTIVE = "active"


@dataclass(frozen=True)
class LayoutConfig:
    enabled: bool = False
    mode: LayoutMode = LayoutMode.LEGACY
    schema_version: str = LAYOUT_SCHEMA_VERSION
    detector_version: str = LAYOUT_DETECTOR_VERSION
    classifier_version: str = BLOCK_CLASSIFIER_VERSION
    minimum_block_area: float = 1.0
    maximum_block_count: int = 2000
    overlap_threshold: float = 0.20
    duplicate_iou_threshold: float = 0.92
    column_gap_threshold: float = 0.12
    spanning_width_threshold: float = 0.72
    header_footer_band_ratio: float = 0.08
    repeated_header_footer_threshold: float = 0.67
    table_region_threshold: float = 0.55
    figure_region_threshold: float = 0.55
    maximum_page_deadline_ms: int = 60_000
    static_fallback_enabled: bool = True

    def validate(self) -> None:
        if not self.schema_version:
            raise ValueError("layout.schema_version is required.")
        if not self.detector_version:
            raise ValueError("layout.detector_version is required.")
        if not self.classifier_version:
            raise ValueError("layout.classifier_version is required.")
        if not isinstance(self.mode, LayoutMode):
            LayoutMode(str(self.mode))
        if self.mode != LayoutMode.LEGACY and not self.enabled:
            raise ValueError("layout.enabled=true is required for shadow or active mode.")
        for name in (
            "minimum_block_area",
            "maximum_block_count",
            "maximum_page_deadline_ms",
        ):
            if float(getattr(self, name)) <= 0:
                raise ValueError(f"layout.{name} must be positive.")
        for name in (
            "overlap_threshold",
            "duplicate_iou_threshold",
            "column_gap_threshold",
            "spanning_width_threshold",
            "header_footer_band_ratio",
            "repeated_header_footer_threshold",
            "table_region_threshold",
            "figure_region_threshold",
        ):
            value = float(getattr(self, name))
            if not 0.0 <= value <= 1.0:
                raise ValueError(f"layout.{name} must be in [0, 1].")


@dataclass(frozen=True)
class ReadingOrderConfig:
    policy_version: str = READING_ORDER_POLICY_VERSION
    edge_confidence_threshold: float = 0.50
    cycle_resolution_enabled: bool = True
    maximum_cycle_resolution_steps: int = 100
    unresolved_policy: str = "typed_review"
    footnote_policy: str = "after_body_before_footer"
    header_footer_policy: str = "separate_from_body"
    caption_policy: str = "adjacent_to_region"
    rotated_region_policy: str = "preserve_atomic_region"
    stable_tie_breaker: str = "page_y_x_id"

    def validate(self) -> None:
        if not self.policy_version:
            raise ValueError("reading_order.policy_version is required.")
        if not 0.0 <= self.edge_confidence_threshold <= 1.0:
            raise ValueError("reading_order.edge_confidence_threshold must be in [0, 1].")
        if self.maximum_cycle_resolution_steps <= 0:
            raise ValueError("reading_order.maximum_cycle_resolution_steps must be positive.")
        for name in (
            "unresolved_policy",
            "footnote_policy",
            "header_footer_policy",
            "caption_policy",
            "rotated_region_policy",
            "stable_tie_breaker",
        ):
            if not str(getattr(self, name) or "").strip():
                raise ValueError(f"reading_order.{name} is required.")


@dataclass(frozen=True)
class LayoutPerformanceConfig:
    maximum_render_dimension: int = 1800
    maximum_image_pixels: int = 6_000_000
    max_parallel_layout_tasks: int = 4
    cache_enabled: bool = True
    overlay_enabled: bool = True
    artifact_size_limit: int = 10_000_000

    def validate(self) -> None:
        for name in (
            "maximum_render_dimension",
            "maximum_image_pixels",
            "max_parallel_layout_tasks",
            "artifact_size_limit",
        ):
            if int(getattr(self, name)) <= 0:
                raise ValueError(f"performance.{name} must be positive.")


@dataclass(frozen=True)
class Phase3Config:
    layout: LayoutConfig = LayoutConfig()
    reading_order: ReadingOrderConfig = ReadingOrderConfig()
    performance: LayoutPerformanceConfig = LayoutPerformanceConfig()

    def validate(self) -> None:
        self.layout.validate()
        self.reading_order.validate()
        self.performance.validate()

    def to_dict(self) -> dict[str, Any]:
        payload = {
            "layout": asdict(self.layout),
            "reading_order": asdict(self.reading_order),
            "performance": asdict(self.performance),
        }
        payload["layout"]["mode"] = self.layout.mode.value
        return payload

    def checksum(self) -> str:
        return _sha256_json(self.to_dict())

    @classmethod
    def from_mapping(cls, value: Mapping[str, Any] | None) -> Phase3Config:
        value = dict(value or {})
        layout_payload = dict(value.get("layout") or {})
        if "mode" in layout_payload and not isinstance(layout_payload["mode"], LayoutMode):
            layout_payload["mode"] = LayoutMode(str(layout_payload["mode"]).strip().lower())
        layout = _dataclass_from_mapping(LayoutConfig, layout_payload)
        reading_order = _dataclass_from_mapping(
            ReadingOrderConfig,
            value.get("reading_order") or {},
        )
        performance = _dataclass_from_mapping(
            LayoutPerformanceConfig,
            value.get("performance") or {},
        )
        config = cls(layout=layout, reading_order=reading_order, performance=performance)
        config.validate()
        return config


DEFAULT_PHASE3_CONFIG = Phase3Config()


def _dataclass_from_mapping(cls: type[Any], payload: Mapping[str, Any]) -> Any:
    allowed = set(cls.__dataclass_fields__)  # type: ignore[attr-defined]
    values = {key: value for key, value in dict(payload).items() if key in allowed}
    return cls(**values)


def _sha256_json(payload: Any) -> str:
    return hashlib.sha256(
        json.dumps(
            payload,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    ).hexdigest()


__all__ = [
    "DEFAULT_PHASE3_CONFIG",
    "LayoutConfig",
    "LayoutMode",
    "LayoutPerformanceConfig",
    "Phase3Config",
    "ReadingOrderConfig",
]
