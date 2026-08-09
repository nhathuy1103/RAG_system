from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from dataclasses import asdict, dataclass
from enum import StrEnum
from typing import Any

from app.pipeline.documents.extraction.verification.models import (
    ABSTENTION_POLICY_VERSION,
    AGREEMENT_POLICY_VERSION,
    ARBITRATION_VERSION,
    CONSENSUS_VERSION,
    DISAGREEMENT_POLICY_VERSION,
    NORMALIZATION_VERSION,
    PRIVACY_POLICY_VERSION,
    PROVIDER_CONTRACT_VERSION,
    PROVIDER_EXECUTOR_VERSION,
    PROVIDER_REGISTRY_VERSION,
    SELECTION_POLICY_VERSION,
    VERIFICATION_SCHEMA_VERSION,
)


class VerificationMode(StrEnum):
    LEGACY = "legacy"
    SHADOW = "shadow"
    ACTIVE = "active"


@dataclass(frozen=True)
class ProviderVerificationConfig:
    enabled: bool = False
    mode: VerificationMode = VerificationMode.LEGACY
    schema_version: str = VERIFICATION_SCHEMA_VERSION
    provider_contract_version: str = PROVIDER_CONTRACT_VERSION
    provider_registry_version: str = PROVIDER_REGISTRY_VERSION
    selection_policy_version: str = SELECTION_POLICY_VERSION
    executor_version: str = PROVIDER_EXECUTOR_VERSION
    normalization_version: str = NORMALIZATION_VERSION
    disagreement_policy_version: str = DISAGREEMENT_POLICY_VERSION
    agreement_policy_version: str = AGREEMENT_POLICY_VERSION
    consensus_version: str = CONSENSUS_VERSION
    arbitration_version: str = ARBITRATION_VERSION
    abstention_policy_version: str = ABSTENTION_POLICY_VERSION
    privacy_policy_version: str = PRIVACY_POLICY_VERSION
    enabled_provider_ids: tuple[str, ...] = (
        "native_phase4",
        "local_ocr_evidence",
        "local_numeric_rules",
        "local_geometry_rules",
    )
    forbidden_provider_ids: tuple[str, ...] = (
        "external_unapproved",
        "network_llm",
        "cloud_ocr",
    )
    allow_external_providers: bool = False
    max_providers_per_case: int = 2
    low_risk_provider_count: int = 1
    medium_risk_provider_count: int = 1
    high_risk_provider_count: int = 2
    max_provider_attempts: int = 2
    provider_timeout_ms: int = 1_000
    max_provider_calls_per_document: int = 200
    max_provider_calls_per_page: int = 48
    max_budget_units_per_document: int = 400
    response_size_limit_bytes: int = 4_096
    circuit_breaker_failure_threshold: int = 2
    min_consensus_confidence: float = 0.78
    min_arbitration_confidence: float = 0.72
    persist_raw_provider_output: bool = True
    static_fallback_enabled: bool = True

    def validate(self) -> None:
        if not isinstance(self.mode, VerificationMode):
            VerificationMode(str(self.mode))
        if self.mode != VerificationMode.LEGACY and not self.enabled:
            raise ValueError(
                "provider_verification.enabled=true is required for shadow or active mode."
            )
        required_strings = (
            "schema_version",
            "provider_contract_version",
            "provider_registry_version",
            "selection_policy_version",
            "executor_version",
            "normalization_version",
            "disagreement_policy_version",
            "agreement_policy_version",
            "consensus_version",
            "arbitration_version",
            "abstention_policy_version",
            "privacy_policy_version",
        )
        for name in required_strings:
            if not str(getattr(self, name) or "").strip():
                raise ValueError(f"provider_verification.{name} is required.")
        positive = (
            "max_providers_per_case",
            "low_risk_provider_count",
            "medium_risk_provider_count",
            "high_risk_provider_count",
            "max_provider_attempts",
            "provider_timeout_ms",
            "max_provider_calls_per_document",
            "max_provider_calls_per_page",
            "max_budget_units_per_document",
            "response_size_limit_bytes",
            "circuit_breaker_failure_threshold",
        )
        for name in positive:
            if int(getattr(self, name)) <= 0:
                raise ValueError(f"provider_verification.{name} must be positive.")
        if self.high_risk_provider_count > self.max_providers_per_case:
            raise ValueError(
                "provider_verification.high_risk_provider_count must fit max_providers_per_case."
            )
        if self.medium_risk_provider_count > self.max_providers_per_case:
            raise ValueError(
                "provider_verification.medium_risk_provider_count must fit max_providers_per_case."
            )
        for name in ("min_consensus_confidence", "min_arbitration_confidence"):
            value = float(getattr(self, name))
            if not 0.0 <= value <= 1.0:
                raise ValueError(f"provider_verification.{name} must be in [0, 1].")
        if self.allow_external_providers and self.forbidden_provider_ids:
            overlap = set(self.enabled_provider_ids) & set(self.forbidden_provider_ids)
            if overlap:
                raise ValueError(
                    "provider_verification enabled and forbidden providers overlap: "
                    + ", ".join(sorted(overlap))
                )


@dataclass(frozen=True)
class Phase5Config:
    provider_verification: ProviderVerificationConfig = ProviderVerificationConfig()

    def validate(self) -> None:
        self.provider_verification.validate()

    def to_dict(self) -> dict[str, Any]:
        payload = {"provider_verification": asdict(self.provider_verification)}
        payload["provider_verification"]["mode"] = self.provider_verification.mode.value
        payload["provider_verification"]["enabled_provider_ids"] = list(
            self.provider_verification.enabled_provider_ids
        )
        payload["provider_verification"]["forbidden_provider_ids"] = list(
            self.provider_verification.forbidden_provider_ids
        )
        return payload

    def checksum(self) -> str:
        return _sha256_json(self.to_dict())

    @classmethod
    def from_mapping(cls, value: Mapping[str, Any] | None) -> Phase5Config:
        value = dict(value or {})
        verification_payload = dict(value.get("provider_verification") or {})
        if "mode" in verification_payload and not isinstance(
            verification_payload["mode"], VerificationMode
        ):
            verification_payload["mode"] = VerificationMode(
                str(verification_payload["mode"]).strip().lower()
            )
        config = cls(
            provider_verification=_dataclass_from_mapping(
                ProviderVerificationConfig,
                verification_payload,
            )
        )
        config.validate()
        return config


DEFAULT_PHASE5_CONFIG = Phase5Config()


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
    "DEFAULT_PHASE5_CONFIG",
    "Phase5Config",
    "ProviderVerificationConfig",
    "VerificationMode",
]
