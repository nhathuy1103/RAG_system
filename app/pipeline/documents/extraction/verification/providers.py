from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any, Protocol

from app.pipeline.documents.extraction.tables.models import normalize_cell_text, numeric_candidate
from app.pipeline.documents.extraction.verification.models import (
    ProviderCapabilities,
    ProviderCost,
    ProviderDescriptor,
    ProviderRequest,
    ProviderResult,
    VerificationCase,
    VerificationSchemaError,
    _sha256_json,
    stable_id,
)


class ProviderExecutionError(RuntimeError):
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


class ProviderAdapter(Protocol):
    descriptor: ProviderDescriptor

    def execute(self, request: ProviderRequest, case: VerificationCase) -> ProviderResult: ...


@dataclass(frozen=True)
class DeterministicProviderAdapter:
    descriptor: ProviderDescriptor

    def execute(self, request: ProviderRequest, case: VerificationCase) -> ProviderResult:
        override = dict(case.provider_overrides.get(self.descriptor.provider_id) or {})
        status = str(override.get("status") or "succeeded")
        if status == "timeout":
            raise ProviderExecutionError(
                str(override.get("error_code") or "provider_timeout"),
                "deterministic timeout fixture",
                retryable=bool(override.get("retryable", True)),
            )
        if status == "failed":
            raise ProviderExecutionError(
                str(override.get("error_code") or "provider_failure"),
                "deterministic failure fixture",
                retryable=bool(override.get("retryable", False)),
            )
        if status == "malformed":
            raise ProviderExecutionError(
                "malformed_response",
                "provider response failed schema validation",
                retryable=False,
            )
        raw_value = str(override.get("value") if "value" in override else self._default_value(case))
        normalized_value = _normalize_value(case.value_kind, raw_value)
        confidence = float(override.get("confidence", self._default_confidence(case)))
        raw_output = {
            "provider_id": self.descriptor.provider_id,
            "contract_version": self.descriptor.version,
            "value": raw_value,
            "normalized_value": normalized_value,
            "confidence": confidence,
            "source": self.descriptor.adapter_name,
        }
        encoded_size = len(json.dumps(raw_output, ensure_ascii=False).encode("utf-8"))
        if encoded_size > self.descriptor.cost.max_response_bytes:
            raise ProviderExecutionError(
                "provider_response_too_large",
                "provider output exceeded bounded response size",
                retryable=False,
            )
        return ProviderResult(
            result_id=stable_id("result", request.request_id, self.descriptor.provider_id),
            request_id=request.request_id,
            case_id=case.case_id,
            provider_id=self.descriptor.provider_id,
            value_kind=case.value_kind,
            raw_value=raw_value,
            normalized_value=normalized_value,
            confidence=confidence,
            source_refs=tuple(_source_refs(case)),
            raw_output=raw_output,
        )

    def _default_value(self, case: VerificationCase) -> str:
        provider_id = self.descriptor.provider_id
        if provider_id == "native_phase4":
            return str(case.native_value if case.native_value is not None else case.raw_value)
        if provider_id == "local_ocr_evidence":
            return str(case.ocr_value if case.ocr_value is not None else case.raw_value)
        if provider_id == "local_numeric_rules":
            raw = str(case.raw_value)
            numeric_text, parsed, _value_type = numeric_candidate(raw)
            if parsed is None:
                return str(case.normalized_value or raw)
            return numeric_text or raw
        if provider_id == "local_geometry_rules":
            if case.value_kind in {"geometry", "cross_page"}:
                return _stable_geometry_value(case)
            return str(case.normalized_value or case.raw_value)
        raise ProviderExecutionError(
            "unsupported_provider_adapter",
            f"no local adapter for {provider_id}",
            retryable=False,
        )

    def _default_confidence(self, case: VerificationCase) -> float:
        if self.descriptor.provider_id == "local_numeric_rules" and case.value_kind == "numeric":
            return 0.99
        if self.descriptor.provider_id == "local_geometry_rules":
            return 0.97
        if self.descriptor.provider_id == "local_ocr_evidence":
            return 0.90
        return 0.92


@dataclass(frozen=True)
class ProviderRegistry:
    providers: tuple[ProviderDescriptor, ...]
    version: str = "provider_registry_v1"

    def __post_init__(self) -> None:
        provider_ids = [provider.provider_id for provider in self.providers]
        if len(set(provider_ids)) != len(provider_ids):
            raise VerificationSchemaError("provider registry ids must be unique")

    def get(self, provider_id: str) -> ProviderDescriptor | None:
        return next(
            (provider for provider in self.providers if provider.provider_id == provider_id),
            None,
        )

    def enabled(self) -> tuple[ProviderDescriptor, ...]:
        return tuple(provider for provider in self.providers if provider.enabled)

    def adapter(self, provider_id: str) -> ProviderAdapter:
        descriptor = self.get(provider_id)
        if descriptor is None:
            raise VerificationSchemaError(f"unknown provider: {provider_id}")
        return DeterministicProviderAdapter(descriptor)

    def to_dict(self) -> dict[str, Any]:
        payload = {
            "version": self.version,
            "provider_count": len(self.providers),
            "independent_evidence_source_count": len(
                {provider.correlated_group for provider in self.providers if provider.enabled}
            ),
            "providers": [provider.to_dict() for provider in self.providers],
        }
        payload["checksum"] = _sha256_json(
            {
                "version": payload["version"],
                "providers": payload["providers"],
            }
        )
        return payload

    def checksum(self) -> str:
        return str(self.to_dict()["checksum"])


def default_provider_registry() -> ProviderRegistry:
    return ProviderRegistry(
        providers=(
            ProviderDescriptor(
                provider_id="native_phase4",
                display_name="Native Phase 4 Structured Evidence",
                adapter_name="native_phase4_adapter",
                version="native_phase4_provider_v1",
                capabilities=ProviderCapabilities(
                    value_kinds=(
                        "text",
                        "numeric",
                        "geometry",
                        "header",
                        "period",
                        "cross_page",
                    ),
                    supports_tables=True,
                    supports_geometry=True,
                    supports_cross_page=True,
                    supports_raw_native=True,
                    supports_financial_values=True,
                ),
                cost=ProviderCost(fixed_cost_units=1, per_case_cost_units=1),
                correlated_group="phase4_native",
                reliability_weight=0.90,
                limitations=("single-source extraction evidence",),
            ),
            ProviderDescriptor(
                provider_id="local_ocr_evidence",
                display_name="Local OCR Evidence Replay",
                adapter_name="local_ocr_evidence_adapter",
                version="local_ocr_evidence_provider_v1",
                capabilities=ProviderCapabilities(
                    value_kinds=("text", "numeric", "header", "period"),
                    supports_tables=True,
                    supports_raw_ocr=True,
                ),
                cost=ProviderCost(fixed_cost_units=1, per_case_cost_units=1),
                correlated_group="local_ocr",
                reliability_weight=0.86,
                limitations=("uses persisted OCR/native text evidence only",),
            ),
            ProviderDescriptor(
                provider_id="local_numeric_rules",
                display_name="Local Numeric Verification Rules",
                adapter_name="local_numeric_rules_adapter",
                version="local_numeric_rules_provider_v1",
                capabilities=ProviderCapabilities(
                    value_kinds=("numeric", "period"),
                    supports_tables=True,
                    supports_financial_values=True,
                ),
                cost=ProviderCost(fixed_cost_units=1, per_case_cost_units=1),
                correlated_group="local_numeric_rules",
                reliability_weight=0.98,
                limitations=("does not perform visual OCR",),
            ),
            ProviderDescriptor(
                provider_id="local_geometry_rules",
                display_name="Local Geometry Verification Rules",
                adapter_name="local_geometry_rules_adapter",
                version="local_geometry_rules_provider_v1",
                capabilities=ProviderCapabilities(
                    value_kinds=("geometry", "cross_page", "text"),
                    supports_tables=True,
                    supports_geometry=True,
                    supports_cross_page=True,
                ),
                cost=ProviderCost(fixed_cost_units=1, per_case_cost_units=1),
                correlated_group="local_geometry_rules",
                reliability_weight=0.95,
                limitations=("does not run multimodal visual extraction",),
            ),
            ProviderDescriptor(
                provider_id="external_unapproved",
                display_name="External Provider Placeholder",
                adapter_name="external_blocked_adapter",
                version="external_unapproved_provider_v1",
                capabilities=ProviderCapabilities(
                    value_kinds=(
                        "text",
                        "numeric",
                        "geometry",
                        "header",
                        "period",
                        "cross_page",
                    ),
                    supports_tables=True,
                    supports_geometry=True,
                    supports_cross_page=True,
                    supports_raw_ocr=True,
                    supports_raw_native=True,
                    supports_financial_values=True,
                ),
                cost=ProviderCost(fixed_cost_units=10, per_case_cost_units=5),
                privacy_classification="external",
                correlated_group="external_unapproved",
                reliability_weight=0.80,
                enabled=True,
                external=True,
                limitations=("forbidden until data governance explicitly approves it",),
            ),
        )
    )


def _normalize_value(value_kind: str, raw_value: str) -> str:
    if value_kind == "numeric":
        numeric_text, parsed, _value_type = numeric_candidate(raw_value)
        if parsed is None:
            return normalize_cell_text(raw_value)
        if float(parsed).is_integer():
            return str(int(parsed))
        return str(parsed)
    if value_kind in {"geometry", "cross_page"}:
        return raw_value.strip()
    return normalize_cell_text(raw_value)


def _stable_geometry_value(case: VerificationCase) -> str:
    payload = {
        "bbox": case.bbox or {},
        "target_type": case.target_type,
        "table_id": case.table_id,
        "cell_id": case.cell_id,
    }
    return "geometry:" + _sha256_json(payload)[:16]


def _source_refs(case: VerificationCase) -> list[str]:
    refs = [case.case_id]
    if case.table_id:
        refs.append(case.table_id)
    if case.cell_id:
        refs.append(case.cell_id)
    return refs


__all__ = [
    "DeterministicProviderAdapter",
    "ProviderAdapter",
    "ProviderExecutionError",
    "ProviderRegistry",
    "default_provider_registry",
]
