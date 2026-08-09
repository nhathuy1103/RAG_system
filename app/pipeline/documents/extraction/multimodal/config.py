from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from dataclasses import asdict, dataclass
from enum import StrEnum
from typing import Any

from app.pipeline.documents.extraction.multimodal.models import (
    CANDIDATE_POLICY_VERSION,
    FIGURE_DETECTOR_VERSION,
    MULTIMODAL_CONTRACT_VERSION,
    MULTIMODAL_PRIVACY_POLICY_VERSION,
    MULTIMODAL_SCHEMA_VERSION,
    VISUAL_ASSET_SCHEMA_VERSION,
    VISUAL_BACKEND_CONTRACT_VERSION,
    VISUAL_BACKEND_REGISTRY_VERSION,
    VISUAL_OCR_VERSION,
)


class MultimodalMode(StrEnum):
    DISABLED = "disabled"
    SHADOW = "shadow"
    ACTIVE = "active"


@dataclass(frozen=True)
class VisualBackendConfig:
    enabled_backend_ids: tuple[str, ...] = ("local_pillow_cv",)
    forbidden_backend_ids: tuple[str, ...] = (
        "external_visual_unapproved",
        "network_vision",
        "cloud_visual_ocr",
    )
    allow_external_backends: bool = False
    max_backend_calls_per_document: int = 200
    max_backend_calls_per_page: int = 48
    max_backend_attempts: int = 2
    backend_timeout_ms: int = 1_000
    max_budget_units_per_document: int = 400
    response_size_limit_bytes: int = 32_768

    def validate(self) -> None:
        positive = (
            "max_backend_calls_per_document",
            "max_backend_calls_per_page",
            "max_backend_attempts",
            "backend_timeout_ms",
            "max_budget_units_per_document",
            "response_size_limit_bytes",
        )
        for name in positive:
            if int(getattr(self, name)) <= 0:
                raise ValueError(f"visual_backend.{name} must be positive.")
        if self.allow_external_backends:
            overlap = set(self.enabled_backend_ids) & set(self.forbidden_backend_ids)
            if overlap:
                raise ValueError(
                    "visual backend enabled and forbidden lists overlap: "
                    + ", ".join(sorted(overlap))
                )


@dataclass(frozen=True)
class VisualAssetConfig:
    max_image_pixels: int = 6_000_000
    max_image_bytes: int = 8_000_000
    max_candidates_per_document: int = 256
    minimum_candidate_area: float = 1.0
    geometry_valid_rate_required: float = 1.0
    dedupe_enabled: bool = True
    persist_raw_assets: bool = True

    def validate(self) -> None:
        for name in (
            "max_image_pixels",
            "max_image_bytes",
            "max_candidates_per_document",
        ):
            if int(getattr(self, name)) <= 0:
                raise ValueError(f"visual_asset.{name} must be positive.")
        if self.minimum_candidate_area <= 0:
            raise ValueError("visual_asset.minimum_candidate_area must be positive.")
        if not 0.0 <= self.geometry_valid_rate_required <= 1.0:
            raise ValueError("visual_asset.geometry_valid_rate_required must be in [0, 1].")


@dataclass(frozen=True)
class MultimodalExtractionConfig:
    enabled: bool = False
    mode: MultimodalMode = MultimodalMode.DISABLED
    schema_version: str = MULTIMODAL_SCHEMA_VERSION
    multimodal_contract_version: str = MULTIMODAL_CONTRACT_VERSION
    visual_asset_schema_version: str = VISUAL_ASSET_SCHEMA_VERSION
    visual_backend_contract_version: str = VISUAL_BACKEND_CONTRACT_VERSION
    visual_backend_registry_version: str = VISUAL_BACKEND_REGISTRY_VERSION
    candidate_policy_version: str = CANDIDATE_POLICY_VERSION
    figure_detector_version: str = FIGURE_DETECTOR_VERSION
    caption_policy_version: str = "caption_association_v1"
    visual_ocr_version: str = VISUAL_OCR_VERSION
    chart_classifier_version: str = "rule_chart_classifier_v1"
    chart_extractor_version: str = "rule_chart_extractor_v1"
    diagram_classifier_version: str = "rule_diagram_classifier_v1"
    diagram_extractor_version: str = "rule_diagram_extractor_v1"
    signature_stamp_logo_version: str = "signature_stamp_logo_detector_v1"
    visual_verification_version: str = "visual_table_verification_v1"
    multimodal_fusion_version: str = "multimodal_fusion_v1"
    privacy_policy_version: str = MULTIMODAL_PRIVACY_POLICY_VERSION
    candidate_type_confidence_threshold: float = 0.70
    figure_confidence_threshold: float = 0.70
    chart_confidence_threshold: float = 0.75
    diagram_confidence_threshold: float = 0.75
    visual_text_confidence_threshold: float = 0.70
    visual_table_verification_threshold: float = 0.80
    review_low_confidence_threshold: float = 0.60
    backend: VisualBackendConfig = VisualBackendConfig()
    assets: VisualAssetConfig = VisualAssetConfig()

    def validate(self) -> None:
        if not isinstance(self.mode, MultimodalMode):
            MultimodalMode(str(self.mode).strip().lower())
        if self.mode != MultimodalMode.DISABLED and not self.enabled:
            raise ValueError("multimodal.enabled=true is required for shadow or active mode.")
        required_strings = (
            "schema_version",
            "multimodal_contract_version",
            "visual_asset_schema_version",
            "visual_backend_contract_version",
            "visual_backend_registry_version",
            "candidate_policy_version",
            "figure_detector_version",
            "caption_policy_version",
            "visual_ocr_version",
            "chart_classifier_version",
            "chart_extractor_version",
            "diagram_classifier_version",
            "diagram_extractor_version",
            "signature_stamp_logo_version",
            "visual_verification_version",
            "multimodal_fusion_version",
            "privacy_policy_version",
        )
        for name in required_strings:
            if not str(getattr(self, name) or "").strip():
                raise ValueError(f"multimodal.{name} is required.")
        for name in (
            "candidate_type_confidence_threshold",
            "figure_confidence_threshold",
            "chart_confidence_threshold",
            "diagram_confidence_threshold",
            "visual_text_confidence_threshold",
            "visual_table_verification_threshold",
            "review_low_confidence_threshold",
        ):
            value = float(getattr(self, name))
            if not 0.0 <= value <= 1.0:
                raise ValueError(f"multimodal.{name} must be in [0, 1].")
        self.backend.validate()
        self.assets.validate()


@dataclass(frozen=True)
class Phase6Config:
    multimodal: MultimodalExtractionConfig = MultimodalExtractionConfig()

    def validate(self) -> None:
        self.multimodal.validate()

    def to_dict(self) -> dict[str, Any]:
        payload = {"multimodal": asdict(self.multimodal)}
        payload["multimodal"]["mode"] = self.multimodal.mode.value
        payload["multimodal"]["backend"]["enabled_backend_ids"] = list(
            self.multimodal.backend.enabled_backend_ids
        )
        payload["multimodal"]["backend"]["forbidden_backend_ids"] = list(
            self.multimodal.backend.forbidden_backend_ids
        )
        return payload

    def checksum(self) -> str:
        return _sha256_json(self.to_dict())

    @classmethod
    def from_mapping(cls, value: Mapping[str, Any] | None) -> Phase6Config:
        value = dict(value or {})
        multimodal_payload = dict(value.get("multimodal") or {})
        backend_payload = dict(multimodal_payload.get("backend") or {})
        assets_payload = dict(multimodal_payload.get("assets") or {})
        if "mode" in multimodal_payload and not isinstance(
            multimodal_payload["mode"], MultimodalMode
        ):
            multimodal_payload["mode"] = MultimodalMode(
                str(multimodal_payload["mode"]).strip().lower()
            )
        for key in ("enabled_backend_ids", "forbidden_backend_ids"):
            if key in backend_payload:
                backend_payload[key] = tuple(str(item) for item in backend_payload[key])
        multimodal_payload["backend"] = _dataclass_from_mapping(
            VisualBackendConfig,
            backend_payload,
        )
        multimodal_payload["assets"] = _dataclass_from_mapping(
            VisualAssetConfig,
            assets_payload,
        )
        config = cls(
            multimodal=_dataclass_from_mapping(
                MultimodalExtractionConfig,
                multimodal_payload,
            )
        )
        config.validate()
        return config


DEFAULT_PHASE6_CONFIG = Phase6Config()


def _dataclass_from_mapping(cls: type[Any], payload: Mapping[str, Any]) -> Any:
    allowed = set(cls.__dataclass_fields__)  # type: ignore[attr-defined]
    return cls(**{key: value for key, value in dict(payload).items() if key in allowed})


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
    "DEFAULT_PHASE6_CONFIG",
    "MultimodalExtractionConfig",
    "MultimodalMode",
    "Phase6Config",
    "VisualAssetConfig",
    "VisualBackendConfig",
]
