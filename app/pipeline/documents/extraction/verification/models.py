from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from typing import Any

VERIFICATION_SCHEMA_NAME = "provider_verification"
VERIFICATION_SCHEMA_VERSION = "1.0.0"
PROVIDER_CONTRACT_VERSION = "provider_contract_v1"
PROVIDER_REGISTRY_VERSION = "provider_registry_v1"
SELECTION_POLICY_VERSION = "provider_selection_policy_v1"
PROVIDER_EXECUTOR_VERSION = "provider_executor_v1"
NORMALIZATION_VERSION = "evidence_normalization_v1"
DISAGREEMENT_POLICY_VERSION = "disagreement_policy_v1"
AGREEMENT_POLICY_VERSION = "agreement_scoring_v1"
CONSENSUS_VERSION = "deterministic_consensus_v1"
ARBITRATION_VERSION = "evidence_arbitration_v1"
ABSTENTION_POLICY_VERSION = "abstention_policy_v1"
PRIVACY_POLICY_VERSION = "provider_privacy_policy_v1"

SUPPORTED_VERIFICATION_MAJOR = "1"
RISK_LEVELS = {"low", "medium", "high"}
TARGET_TYPES = {
    "text_block",
    "table_cell",
    "table_header",
    "table_geometry",
    "cross_page_link",
}
VALUE_KINDS = {"text", "numeric", "geometry", "header", "period", "cross_page"}
REQUEST_STATUSES = {"planned", "skipped", "executed"}
ATTEMPT_STATUSES = {"succeeded", "failed", "timeout", "skipped", "forbidden"}
DECISION_STATUSES = {"accepted", "manual_review", "abstained"}
PRIVACY_CLASSES = {"local_only", "external"}


class VerificationSchemaError(ValueError):
    """Raised when a Phase 5 verification artifact violates its contract."""


def _utc_now() -> str:
    return datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")


@dataclass(frozen=True)
class ProviderCapabilities:
    value_kinds: tuple[str, ...]
    supports_tables: bool = False
    supports_geometry: bool = False
    supports_cross_page: bool = False
    supports_raw_ocr: bool = False
    supports_raw_native: bool = False
    supports_financial_values: bool = False

    def __post_init__(self) -> None:
        unknown = set(self.value_kinds) - VALUE_KINDS
        if unknown:
            raise VerificationSchemaError(
                "unsupported provider value kinds: " + ", ".join(sorted(unknown))
            )

    def to_dict(self) -> dict[str, Any]:
        return {
            "value_kinds": list(self.value_kinds),
            "supports_tables": self.supports_tables,
            "supports_geometry": self.supports_geometry,
            "supports_cross_page": self.supports_cross_page,
            "supports_raw_ocr": self.supports_raw_ocr,
            "supports_raw_native": self.supports_raw_native,
            "supports_financial_values": self.supports_financial_values,
        }

    @classmethod
    def from_mapping(cls, value: Mapping[str, Any]) -> ProviderCapabilities:
        return cls(
            value_kinds=tuple(str(item) for item in value.get("value_kinds") or ()),
            supports_tables=bool(value.get("supports_tables", False)),
            supports_geometry=bool(value.get("supports_geometry", False)),
            supports_cross_page=bool(value.get("supports_cross_page", False)),
            supports_raw_ocr=bool(value.get("supports_raw_ocr", False)),
            supports_raw_native=bool(value.get("supports_raw_native", False)),
            supports_financial_values=bool(value.get("supports_financial_values", False)),
        )


@dataclass(frozen=True)
class ProviderCost:
    fixed_cost_units: int = 1
    per_case_cost_units: int = 1
    timeout_ms: int = 1_000
    max_response_bytes: int = 4_096

    def __post_init__(self) -> None:
        for name in (
            "fixed_cost_units",
            "per_case_cost_units",
            "timeout_ms",
            "max_response_bytes",
        ):
            if int(getattr(self, name)) <= 0:
                raise VerificationSchemaError(f"provider cost {name} must be positive")

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_mapping(cls, value: Mapping[str, Any]) -> ProviderCost:
        return cls(
            fixed_cost_units=int(value.get("fixed_cost_units", 1)),
            per_case_cost_units=int(value.get("per_case_cost_units", 1)),
            timeout_ms=int(value.get("timeout_ms", 1_000)),
            max_response_bytes=int(value.get("max_response_bytes", 4_096)),
        )


@dataclass(frozen=True)
class ProviderDescriptor:
    provider_id: str
    display_name: str
    adapter_name: str
    version: str
    capabilities: ProviderCapabilities
    cost: ProviderCost = ProviderCost()
    privacy_classification: str = "local_only"
    correlated_group: str = ""
    reliability_weight: float = 0.90
    enabled: bool = True
    deterministic: bool = True
    external: bool = False
    limitations: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if not self.provider_id or not self.adapter_name or not self.version:
            raise VerificationSchemaError("provider descriptor requires stable ids")
        if self.privacy_classification not in PRIVACY_CLASSES:
            raise VerificationSchemaError("unsupported provider privacy classification")
        if not 0.0 <= float(self.reliability_weight) <= 1.0:
            raise VerificationSchemaError("provider reliability_weight must be in [0, 1]")
        if self.external and self.privacy_classification != "external":
            raise VerificationSchemaError("external providers must use external privacy")

    def to_dict(self) -> dict[str, Any]:
        return {
            "provider_id": self.provider_id,
            "display_name": self.display_name,
            "adapter_name": self.adapter_name,
            "version": self.version,
            "capabilities": self.capabilities.to_dict(),
            "cost": self.cost.to_dict(),
            "privacy_classification": self.privacy_classification,
            "correlated_group": self.correlated_group,
            "reliability_weight": self.reliability_weight,
            "enabled": self.enabled,
            "deterministic": self.deterministic,
            "external": self.external,
            "limitations": list(self.limitations),
        }

    @classmethod
    def from_mapping(cls, value: Mapping[str, Any]) -> ProviderDescriptor:
        return cls(
            provider_id=str(value["provider_id"]),
            display_name=str(value.get("display_name") or value["provider_id"]),
            adapter_name=str(value["adapter_name"]),
            version=str(value["version"]),
            capabilities=ProviderCapabilities.from_mapping(dict(value.get("capabilities") or {})),
            cost=ProviderCost.from_mapping(dict(value.get("cost") or {})),
            privacy_classification=str(value.get("privacy_classification") or "local_only"),
            correlated_group=str(value.get("correlated_group") or ""),
            reliability_weight=float(value.get("reliability_weight", 0.90)),
            enabled=bool(value.get("enabled", True)),
            deterministic=bool(value.get("deterministic", True)),
            external=bool(value.get("external", False)),
            limitations=tuple(str(item) for item in value.get("limitations") or ()),
        )

    def checksum(self) -> str:
        return _sha256_json(self.to_dict())


@dataclass(frozen=True)
class VerificationCase:
    case_id: str
    document_id: str
    target_type: str
    page_number: int
    value_kind: str
    risk_level: str
    raw_value: str
    normalized_value: str
    table_id: str | None = None
    cell_id: str | None = None
    bbox: dict[str, Any] | None = None
    native_value: str | None = None
    ocr_value: str | None = None
    expected_verified_value: str | None = None
    expected_status: str | None = None
    expected_provider_ids: tuple[str, ...] = ()
    expected_disagreement: bool = False
    high_value: bool = False
    reason_codes: tuple[str, ...] = ()
    provider_overrides: dict[str, Any] = field(default_factory=dict)
    metadata: dict[str, Any] = field(default_factory=dict)
    created_at: str = field(default_factory=_utc_now)

    def __post_init__(self) -> None:
        if not self.case_id or not self.document_id:
            raise VerificationSchemaError("verification case requires ids")
        if self.target_type not in TARGET_TYPES:
            raise VerificationSchemaError(f"unsupported target type: {self.target_type}")
        if self.value_kind not in VALUE_KINDS:
            raise VerificationSchemaError(f"unsupported value kind: {self.value_kind}")
        if self.risk_level not in RISK_LEVELS:
            raise VerificationSchemaError(f"unsupported risk level: {self.risk_level}")
        if self.page_number <= 0:
            raise VerificationSchemaError("verification case page_number must be positive")

    def to_dict(self) -> dict[str, Any]:
        return {
            "case_id": self.case_id,
            "document_id": self.document_id,
            "target_type": self.target_type,
            "page_number": self.page_number,
            "value_kind": self.value_kind,
            "risk_level": self.risk_level,
            "raw_value": self.raw_value,
            "normalized_value": self.normalized_value,
            "table_id": self.table_id,
            "cell_id": self.cell_id,
            "bbox": dict(self.bbox) if self.bbox is not None else None,
            "native_value": self.native_value,
            "ocr_value": self.ocr_value,
            "expected_verified_value": self.expected_verified_value,
            "expected_status": self.expected_status,
            "expected_provider_ids": list(self.expected_provider_ids),
            "expected_disagreement": self.expected_disagreement,
            "high_value": self.high_value,
            "reason_codes": list(self.reason_codes),
            "provider_overrides": dict(self.provider_overrides),
            "metadata": dict(self.metadata),
            "created_at": self.created_at,
        }

    @classmethod
    def from_mapping(cls, value: Mapping[str, Any]) -> VerificationCase:
        payload = dict(value)
        return cls(
            case_id=str(payload["case_id"]),
            document_id=str(payload["document_id"]),
            target_type=str(payload["target_type"]),
            page_number=int(payload["page_number"]),
            value_kind=str(payload["value_kind"]),
            risk_level=str(payload["risk_level"]),
            raw_value=str(payload.get("raw_value") or ""),
            normalized_value=str(payload.get("normalized_value") or ""),
            table_id=str(payload["table_id"]) if payload.get("table_id") is not None else None,
            cell_id=str(payload["cell_id"]) if payload.get("cell_id") is not None else None,
            bbox=dict(payload["bbox"]) if payload.get("bbox") is not None else None,
            native_value=str(payload["native_value"])
            if payload.get("native_value") is not None
            else None,
            ocr_value=str(payload["ocr_value"]) if payload.get("ocr_value") is not None else None,
            expected_verified_value=(
                str(payload["expected_verified_value"])
                if payload.get("expected_verified_value") is not None
                else None
            ),
            expected_status=(
                str(payload["expected_status"])
                if payload.get("expected_status") is not None
                else None
            ),
            expected_provider_ids=tuple(
                str(item) for item in payload.get("expected_provider_ids") or ()
            ),
            expected_disagreement=bool(payload.get("expected_disagreement", False)),
            high_value=bool(payload.get("high_value", False)),
            reason_codes=tuple(str(item) for item in payload.get("reason_codes") or ()),
            provider_overrides=dict(payload.get("provider_overrides") or {}),
            metadata=dict(payload.get("metadata") or {}),
            created_at=str(payload.get("created_at") or _utc_now()),
        )

    def checksum(self) -> str:
        payload = self.to_dict()
        payload.pop("created_at", None)
        return _sha256_json(payload)


@dataclass(frozen=True)
class ProviderExecutionPlan:
    plan_id: str
    case_id: str
    selected_provider_ids: tuple[str, ...]
    rejected_provider_ids: tuple[str, ...] = ()
    reason_codes: tuple[str, ...] = ()
    budget_units: int = 0
    terminal_without_provider: bool = False

    def to_dict(self) -> dict[str, Any]:
        return {
            "plan_id": self.plan_id,
            "case_id": self.case_id,
            "selected_provider_ids": list(self.selected_provider_ids),
            "rejected_provider_ids": list(self.rejected_provider_ids),
            "reason_codes": list(self.reason_codes),
            "budget_units": self.budget_units,
            "terminal_without_provider": self.terminal_without_provider,
        }


@dataclass(frozen=True)
class ProviderRequest:
    request_id: str
    case_id: str
    provider_id: str
    idempotency_key: str
    status: str
    payload: dict[str, Any]
    timeout_ms: int
    budget_units: int
    created_at: str = field(default_factory=_utc_now)

    def __post_init__(self) -> None:
        if self.status not in REQUEST_STATUSES:
            raise VerificationSchemaError(f"unsupported request status: {self.status}")

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class ProviderAttempt:
    attempt_id: str
    request_id: str
    case_id: str
    provider_id: str
    attempt_index: int
    status: str
    terminal: bool
    latency_ms: float
    retryable: bool = False
    error_code: str | None = None
    reason: str = ""

    def __post_init__(self) -> None:
        if self.status not in ATTEMPT_STATUSES:
            raise VerificationSchemaError(f"unsupported attempt status: {self.status}")
        if self.attempt_index <= 0:
            raise VerificationSchemaError("attempt_index must be positive")

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class ProviderResult:
    result_id: str
    request_id: str
    case_id: str
    provider_id: str
    value_kind: str
    raw_value: str
    normalized_value: str
    confidence: float
    source_refs: tuple[str, ...] = ()
    raw_output: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if self.value_kind not in VALUE_KINDS:
            raise VerificationSchemaError(f"unsupported result value kind: {self.value_kind}")
        if not 0.0 <= self.confidence <= 1.0:
            raise VerificationSchemaError("provider result confidence must be in [0, 1]")

    def to_dict(self) -> dict[str, Any]:
        return {
            "result_id": self.result_id,
            "request_id": self.request_id,
            "case_id": self.case_id,
            "provider_id": self.provider_id,
            "value_kind": self.value_kind,
            "raw_value": self.raw_value,
            "normalized_value": self.normalized_value,
            "confidence": self.confidence,
            "source_refs": list(self.source_refs),
            "raw_output": dict(self.raw_output),
            "checksum": self.checksum(),
        }

    def checksum(self) -> str:
        return _sha256_json(
            {
                "request_id": self.request_id,
                "case_id": self.case_id,
                "provider_id": self.provider_id,
                "value_kind": self.value_kind,
                "raw_value": self.raw_value,
                "normalized_value": self.normalized_value,
                "confidence": self.confidence,
                "source_refs": list(self.source_refs),
                "raw_output": dict(self.raw_output),
            }
        )


@dataclass(frozen=True)
class ProviderError:
    error_id: str
    request_id: str
    case_id: str
    provider_id: str
    error_code: str
    retryable: bool
    terminal: bool
    message: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class NormalizedEvidence:
    evidence_id: str
    case_id: str
    provider_id: str
    value_kind: str
    raw_value: str
    normalized_value: str
    numeric_value: float | None
    confidence: float
    reliability_weight: float
    correlated_group: str
    source_type: str
    checksum: str
    reason_codes: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        return {
            "evidence_id": self.evidence_id,
            "case_id": self.case_id,
            "provider_id": self.provider_id,
            "value_kind": self.value_kind,
            "raw_value": self.raw_value,
            "normalized_value": self.normalized_value,
            "numeric_value": self.numeric_value,
            "confidence": self.confidence,
            "reliability_weight": self.reliability_weight,
            "correlated_group": self.correlated_group,
            "source_type": self.source_type,
            "checksum": self.checksum,
            "reason_codes": list(self.reason_codes),
        }


@dataclass(frozen=True)
class Disagreement:
    disagreement_id: str
    case_id: str
    disagreement_type: str
    severity: str
    provider_ids: tuple[str, ...]
    normalized_values: tuple[str, ...]
    reason_codes: tuple[str, ...]

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["provider_ids"] = list(self.provider_ids)
        payload["normalized_values"] = list(self.normalized_values)
        payload["reason_codes"] = list(self.reason_codes)
        return payload


@dataclass(frozen=True)
class ConsensusResult:
    consensus_id: str
    case_id: str
    status: str
    normalized_value: str | None
    confidence: float
    support_provider_ids: tuple[str, ...]
    conflicting_provider_ids: tuple[str, ...]
    rule: str
    reason_codes: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["support_provider_ids"] = list(self.support_provider_ids)
        payload["conflicting_provider_ids"] = list(self.conflicting_provider_ids)
        payload["reason_codes"] = list(self.reason_codes)
        return payload


@dataclass(frozen=True)
class ArbitrationDecision:
    decision_id: str
    case_id: str
    status: str
    verified_value: str | None
    raw_value_preserved: str
    confidence: float
    provider_ids: tuple[str, ...]
    evidence_ids: tuple[str, ...]
    decision_reason: str
    review_required: bool = False
    unsafe_acceptance: bool = False
    reason_codes: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if self.status not in DECISION_STATUSES:
            raise VerificationSchemaError(f"unsupported decision status: {self.status}")

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["provider_ids"] = list(self.provider_ids)
        payload["evidence_ids"] = list(self.evidence_ids)
        payload["reason_codes"] = list(self.reason_codes)
        return payload


@dataclass(frozen=True)
class Abstention:
    abstention_id: str
    case_id: str
    reason_code: str
    severity: str
    review_package_id: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def stable_id(prefix: str, *parts: Any) -> str:
    body = "|".join(str(part) for part in parts)
    return f"{prefix}-{hashlib.sha256(body.encode('utf-8')).hexdigest()[:16]}"


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
    "ABSTENTION_POLICY_VERSION",
    "AGREEMENT_POLICY_VERSION",
    "ARBITRATION_VERSION",
    "CONSENSUS_VERSION",
    "DISAGREEMENT_POLICY_VERSION",
    "NORMALIZATION_VERSION",
    "PRIVACY_POLICY_VERSION",
    "PROVIDER_CONTRACT_VERSION",
    "PROVIDER_EXECUTOR_VERSION",
    "PROVIDER_REGISTRY_VERSION",
    "SELECTION_POLICY_VERSION",
    "VERIFICATION_SCHEMA_NAME",
    "VERIFICATION_SCHEMA_VERSION",
    "Abstention",
    "ArbitrationDecision",
    "ConsensusResult",
    "Disagreement",
    "NormalizedEvidence",
    "ProviderCapabilities",
    "ProviderCost",
    "ProviderDescriptor",
    "ProviderError",
    "ProviderExecutionPlan",
    "ProviderRequest",
    "ProviderResult",
    "VerificationCase",
    "VerificationSchemaError",
    "stable_id",
    "_sha256_json",
]
