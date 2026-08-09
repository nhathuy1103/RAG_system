from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from dataclasses import asdict, dataclass
from enum import StrEnum
from typing import Any

PROFILE_SCHEMA_VERSION = "page_profile_v1"
PROFILER_VERSION = "cheap_pdf_signals_v1"
SIGNAL_VERSION = "cheap_signal_v1"
CLASSIFIER_VERSION = "page_classifier_v1"
ROUTING_POLICY_VERSION = "adaptive_routing_policy_v1"


class RoutingMode(StrEnum):
    STATIC = "STATIC"
    SHADOW = "SHADOW"
    ADAPTIVE = "ADAPTIVE"


@dataclass(frozen=True)
class ProfilingConfig:
    enabled: bool = False
    schema_version: str = PROFILE_SCHEMA_VERSION
    profiler_version: str = PROFILER_VERSION
    signal_version: str = SIGNAL_VERSION
    cheap_signal_timeout_ms: int = 250
    image_signal_enabled: bool = True
    maximum_render_dimension: int = 1800
    maximum_image_pixels: int = 6_000_000
    maximum_embedded_images: int = 64
    cache_enabled: bool = True
    max_parallel_profiles: int = 4

    def validate(self) -> None:
        if not self.schema_version:
            raise ValueError("profiling.schema_version is required.")
        if not self.profiler_version:
            raise ValueError("profiling.profiler_version is required.")
        if not self.signal_version:
            raise ValueError("profiling.signal_version is required.")
        for name in (
            "cheap_signal_timeout_ms",
            "maximum_render_dimension",
            "maximum_image_pixels",
            "maximum_embedded_images",
            "max_parallel_profiles",
        ):
            if int(getattr(self, name)) <= 0:
                raise ValueError(f"profiling.{name} must be positive.")


@dataclass(frozen=True)
class RoutingConfig:
    mode: RoutingMode = RoutingMode.STATIC
    policy_version: str = ROUTING_POLICY_VERSION
    classifier_version: str = CLASSIFIER_VERSION
    native_quality_threshold: float = 0.72
    scan_probability_threshold: float = 0.68
    hybrid_threshold: float = 0.45
    table_probability_threshold: float = 0.62
    complex_layout_threshold: float = 0.62
    orientation_confidence_threshold: float = 0.70
    maximum_orientation_candidates: int = 2
    maximum_attempts: int = 2
    maximum_page_deadline_ms: int = 60_000
    static_fallback_enabled: bool = True
    manual_review_threshold: float = 0.38

    def validate(self) -> None:
        if not self.policy_version:
            raise ValueError("routing.policy_version is required.")
        if not self.classifier_version:
            raise ValueError("routing.classifier_version is required.")
        for name in (
            "native_quality_threshold",
            "scan_probability_threshold",
            "hybrid_threshold",
            "table_probability_threshold",
            "complex_layout_threshold",
            "orientation_confidence_threshold",
            "manual_review_threshold",
        ):
            value = float(getattr(self, name))
            if not 0.0 <= value <= 1.0:
                raise ValueError(f"routing.{name} must be in [0, 1].")
        for name in (
            "maximum_orientation_candidates",
            "maximum_attempts",
            "maximum_page_deadline_ms",
        ):
            if int(getattr(self, name)) <= 0:
                raise ValueError(f"routing.{name} must be positive.")


@dataclass(frozen=True)
class PerformanceConfig:
    max_parallel_ocr: int = 1
    artifact_retention: str = "metadata_and_jsonl"
    profile_artifact_size_limit: int = 2_000_000
    route_trace_enabled: bool = True

    def validate(self) -> None:
        if self.max_parallel_ocr <= 0:
            raise ValueError("performance.max_parallel_ocr must be positive.")
        if self.profile_artifact_size_limit <= 0:
            raise ValueError("performance.profile_artifact_size_limit must be positive.")
        if not self.artifact_retention:
            raise ValueError("performance.artifact_retention is required.")


@dataclass(frozen=True)
class Phase2Config:
    profiling: ProfilingConfig = ProfilingConfig()
    routing: RoutingConfig = RoutingConfig()
    performance: PerformanceConfig = PerformanceConfig()

    def validate(self) -> None:
        self.profiling.validate()
        self.routing.validate()
        self.performance.validate()
        if self.routing.mode != RoutingMode.STATIC and not self.profiling.enabled:
            raise ValueError("profiling.enabled must be true for SHADOW or ADAPTIVE routing.")

    def to_dict(self) -> dict[str, Any]:
        payload = {
            "profiling": asdict(self.profiling),
            "routing": asdict(self.routing),
            "performance": asdict(self.performance),
        }
        payload["routing"]["mode"] = self.routing.mode.value
        return payload

    def checksum(self) -> str:
        return _sha256_json(self.to_dict())

    @classmethod
    def from_mapping(cls, value: Mapping[str, Any] | None) -> Phase2Config:
        value = dict(value or {})
        profiling = _dataclass_from_mapping(
            ProfilingConfig,
            value.get("profiling") or {},
        )
        routing_payload = dict(value.get("routing") or {})
        if "mode" in routing_payload and not isinstance(
            routing_payload["mode"],
            RoutingMode,
        ):
            routing_payload["mode"] = RoutingMode(str(routing_payload["mode"]).upper())
        routing = _dataclass_from_mapping(RoutingConfig, routing_payload)
        performance = _dataclass_from_mapping(
            PerformanceConfig,
            value.get("performance") or {},
        )
        config = cls(
            profiling=profiling,
            routing=routing,
            performance=performance,
        )
        config.validate()
        return config


DEFAULT_PHASE2_CONFIG = Phase2Config()


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
    "CLASSIFIER_VERSION",
    "DEFAULT_PHASE2_CONFIG",
    "PROFILE_SCHEMA_VERSION",
    "PROFILER_VERSION",
    "ROUTING_POLICY_VERSION",
    "SIGNAL_VERSION",
    "PerformanceConfig",
    "Phase2Config",
    "ProfilingConfig",
    "RoutingConfig",
    "RoutingMode",
]
