from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from dataclasses import asdict, dataclass, field
from enum import StrEnum
from typing import Any

from app.pipeline.documents.extraction.profiling.config import (
    CLASSIFIER_VERSION,
    PROFILE_SCHEMA_VERSION,
    PROFILER_VERSION,
    ROUTING_POLICY_VERSION,
    SIGNAL_VERSION,
)


class ProfileStatus(StrEnum):
    PASS = "PASS"
    WARN = "WARN"
    FAIL_CLOSED = "FAIL_CLOSED"


class PageClass(StrEnum):
    NATIVE = "native"
    SCANNED = "scanned"
    HYBRID = "hybrid"
    ROTATED = "rotated"
    TABLE_LIKELY = "table_likely"
    COMPLEX_LAYOUT = "complex_layout"
    VISUAL_DOMINANT = "visual_dominant"
    EMPTY = "empty"
    LOW_INFORMATION = "low_information"
    UNSUPPORTED = "unsupported"
    UNCERTAIN = "uncertain"


class ExtractionRoute(StrEnum):
    NATIVE_ONLY = "NATIVE_ONLY"
    OCR_ONLY = "OCR_ONLY"
    NATIVE_OCR_HYBRID = "NATIVE_OCR_HYBRID"
    ORIENTATION_RECOVERY_OCR = "ORIENTATION_RECOVERY_OCR"
    STATIC_FALLBACK = "STATIC_FALLBACK"
    MANUAL_REVIEW = "MANUAL_REVIEW"
    EMPTY = "EMPTY"
    UNSUPPORTED = "UNSUPPORTED"


class RouteSource(StrEnum):
    STATIC = "STATIC"
    SHADOW = "SHADOW"
    ADAPTIVE = "ADAPTIVE"


@dataclass(frozen=True)
class SignalFailure:
    signal_name: str
    reason_code: str
    required: bool
    message: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class DownstreamCapabilityHints:
    table_candidate: bool = False
    complex_layout_candidate: bool = False
    visual_extraction_candidate: bool = False
    reading_order_candidate: bool = False
    rotated_layout_candidate: bool = False
    native_ocr_disagreement_review: bool = False
    manual_review: bool = False
    reason_codes: tuple[str, ...] = field(default_factory=tuple)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class PageProfile:
    document_id: str
    page_number: int
    schema_version: str = PROFILE_SCHEMA_VERSION
    profiler_version: str = PROFILER_VERSION
    signal_version: str = SIGNAL_VERSION
    status: ProfileStatus = ProfileStatus.PASS
    input_checksum: str = ""
    native_text_characters: int = 0
    native_word_count: int = 0
    text_density: float = 0.0
    digit_ratio: float = 0.0
    mojibake_ratio: float = 0.0
    replacement_characters: int = 0
    repeated_garbage_ratio: float = 0.0
    image_count: int = 0
    image_coverage: float | None = None
    font_count: int = 0
    width: float | None = None
    height: float | None = None
    rotation_degrees: int = 0
    native_quality_score: float = 0.0
    scan_probability: float = 0.0
    table_probability: float = 0.0
    complex_layout_probability: float = 0.0
    visual_probability: float = 0.0
    orientation_confidence: float = 1.0
    line_count: int = 0
    average_line_length: float = 0.0
    max_line_length: int = 0
    missing_signals: tuple[SignalFailure, ...] = field(default_factory=tuple)
    evidence: dict[str, Any] = field(default_factory=dict)
    reason_codes: tuple[str, ...] = field(default_factory=tuple)
    latency_ms: float = 0.0

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["status"] = self.status.value
        return payload

    @classmethod
    def from_mapping(cls, payload: Mapping[str, Any]) -> PageProfile:
        values = dict(payload)
        values["status"] = ProfileStatus(values.get("status", ProfileStatus.PASS.value))
        values["missing_signals"] = tuple(
            SignalFailure(**item) for item in values.get("missing_signals", ())
        )
        values["reason_codes"] = tuple(values.get("reason_codes", ()))
        return cls(**values)

    def checksum(self) -> str:
        payload = self.to_dict()
        payload.pop("latency_ms", None)
        return _sha256_json(payload)


@dataclass(frozen=True)
class PageClassification:
    page_number: int
    classifier_version: str = CLASSIFIER_VERSION
    primary_class: PageClass = PageClass.UNCERTAIN
    secondary_classes: tuple[PageClass, ...] = field(default_factory=tuple)
    confidence: float = 0.0
    evidence: dict[str, Any] = field(default_factory=dict)
    reason_codes: tuple[str, ...] = field(default_factory=tuple)

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["primary_class"] = self.primary_class.value
        payload["secondary_classes"] = [item.value for item in self.secondary_classes]
        return payload

    @classmethod
    def from_mapping(cls, payload: Mapping[str, Any]) -> PageClassification:
        values = dict(payload)
        values["primary_class"] = PageClass(values.get("primary_class", PageClass.UNCERTAIN.value))
        values["secondary_classes"] = tuple(
            PageClass(item) for item in values.get("secondary_classes", ())
        )
        values["reason_codes"] = tuple(values.get("reason_codes", ()))
        return cls(**values)

    def checksum(self) -> str:
        return _sha256_json(self.to_dict())


@dataclass(frozen=True)
class RoutingDecision:
    document_id: str
    page_number: int
    route: ExtractionRoute
    route_source: RouteSource
    policy_version: str = ROUTING_POLICY_VERSION
    input_checksum: str = ""
    profile_checksum: str = ""
    classification_checksum: str = ""
    confidence: float = 0.0
    maximum_attempts: int = 1
    maximum_orientation_candidates: int = 1
    maximum_page_deadline_ms: int = 60_000
    static_fallback_enabled: bool = True
    fallback_route: ExtractionRoute | None = None
    review_required: bool = False
    terminal: bool = False
    reason_codes: tuple[str, ...] = field(default_factory=tuple)
    evidence: dict[str, Any] = field(default_factory=dict)
    downstream_hints: DownstreamCapabilityHints = DownstreamCapabilityHints()
    explanation: str = ""
    latency_ms: float = 0.0

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["route"] = self.route.value
        payload["route_source"] = self.route_source.value
        payload["fallback_route"] = self.fallback_route.value if self.fallback_route else None
        return payload

    @classmethod
    def from_mapping(cls, payload: Mapping[str, Any]) -> RoutingDecision:
        values = dict(payload)
        values["route"] = ExtractionRoute(values["route"])
        values["route_source"] = RouteSource(values["route_source"])
        fallback = values.get("fallback_route")
        values["fallback_route"] = ExtractionRoute(fallback) if fallback else None
        values["reason_codes"] = tuple(values.get("reason_codes", ()))
        hints = values.get("downstream_hints") or {}
        values["downstream_hints"] = (
            hints
            if isinstance(hints, DownstreamCapabilityHints)
            else DownstreamCapabilityHints(**hints)
        )
        return cls(**values)

    def checksum(self) -> str:
        payload = self.to_dict()
        payload.pop("latency_ms", None)
        return _sha256_json(payload)


@dataclass(frozen=True)
class RouteAttempt:
    document_id: str
    page_number: int
    attempt_id: int
    route: ExtractionRoute
    status: str
    reason_codes: tuple[str, ...] = field(default_factory=tuple)
    latency_ms: float = 0.0
    provider: str | None = None

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["route"] = self.route.value
        return payload


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
    "DownstreamCapabilityHints",
    "ExtractionRoute",
    "PageClassification",
    "PageClass",
    "PageProfile",
    "ProfileStatus",
    "RouteAttempt",
    "RouteSource",
    "RoutingDecision",
    "SignalFailure",
]
