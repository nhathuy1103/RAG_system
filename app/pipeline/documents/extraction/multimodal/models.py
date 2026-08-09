from __future__ import annotations

import hashlib
import json
import math
from collections.abc import Mapping
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from typing import Any

MULTIMODAL_SCHEMA_NAME = "multimodal_extraction"
MULTIMODAL_SCHEMA_VERSION = "1.0.0"
MULTIMODAL_CONTRACT_VERSION = "multimodal_contract_v1"
VISUAL_ASSET_SCHEMA_VERSION = "visual_asset_v1"
VISUAL_BACKEND_CONTRACT_VERSION = "visual_backend_contract_v1"
VISUAL_BACKEND_REGISTRY_VERSION = "visual_backend_registry_v1"
CANDIDATE_POLICY_VERSION = "visual_candidate_policy_v1"
FIGURE_DETECTOR_VERSION = "rule_figure_detector_v1"
CAPTION_POLICY_VERSION = "caption_association_v1"
VISUAL_OCR_VERSION = "deterministic_visual_text_v1"
CHART_CLASSIFIER_VERSION = "rule_chart_classifier_v1"
CHART_EXTRACTOR_VERSION = "rule_chart_extractor_v1"
DIAGRAM_CLASSIFIER_VERSION = "rule_diagram_classifier_v1"
DIAGRAM_EXTRACTOR_VERSION = "rule_diagram_extractor_v1"
SIGNATURE_STAMP_LOGO_VERSION = "signature_stamp_logo_detector_v1"
VISUAL_VERIFICATION_VERSION = "visual_table_verification_v1"
MULTIMODAL_FUSION_VERSION = "multimodal_fusion_v1"
MULTIMODAL_PRIVACY_POLICY_VERSION = "multimodal_privacy_policy_v1"

SUPPORTED_MULTIMODAL_MAJOR = "1"
PRIVACY_CLASSES = {"local_only", "external"}
VISUAL_CANDIDATE_TYPES = {
    "embedded_image",
    "full_page",
    "figure",
    "chart",
    "diagram",
    "visual_text",
    "signature",
    "stamp",
    "logo",
    "visual_table",
    "corrupt_image",
    "oversized_image",
    "duplicate_image",
    "unknown",
}
VISUAL_REGION_TYPES = {
    "figure",
    "caption",
    "visual_text",
    "chart",
    "chart_axis",
    "chart_legend",
    "chart_series",
    "diagram",
    "diagram_node",
    "diagram_edge",
    "signature",
    "stamp",
    "logo",
    "visual_table",
    "unknown",
}
BACKEND_REQUEST_STATUSES = {"planned", "skipped", "executed"}
BACKEND_ATTEMPT_STATUSES = {
    "succeeded",
    "failed",
    "timeout",
    "skipped",
    "forbidden",
    "malformed",
}
ISSUE_SEVERITIES = {"info", "low", "medium", "high", "critical"}
EVIDENCE_TYPES = {
    "visual_region",
    "visual_text",
    "figure",
    "chart",
    "diagram",
    "signature",
    "stamp",
    "logo",
    "visual_table_verification",
    "abstention",
}


class MultimodalSchemaError(ValueError):
    """Raised when a Phase 6 multimodal artifact violates its contract."""


def utc_now() -> str:
    return datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def stable_id(prefix: str, *parts: Any) -> str:
    body = "|".join(str(part) for part in parts)
    return f"{prefix}-{hashlib.sha256(body.encode('utf-8')).hexdigest()[:16]}"


def sha256_json(payload: Any) -> str:
    return hashlib.sha256(
        json.dumps(
            payload,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    ).hexdigest()


def validate_schema_version(value: str) -> None:
    major = str(value).split(".", 1)[0]
    if major != SUPPORTED_MULTIMODAL_MAJOR:
        raise MultimodalSchemaError(f"unsupported multimodal schema version: {value}")


def validate_bbox(bbox: Mapping[str, Any] | None) -> None:
    if bbox is None:
        return
    required = ("x_min", "y_min", "x_max", "y_max")
    missing = [key for key in required if key not in bbox]
    if missing:
        raise MultimodalSchemaError("bbox missing fields: " + ", ".join(missing))
    values = {key: float(bbox[key]) for key in required}
    if any(math.isnan(value) or math.isinf(value) for value in values.values()):
        raise MultimodalSchemaError("bbox coordinates must be finite")
    if min(values.values()) < 0:
        raise MultimodalSchemaError("bbox coordinates must be non-negative")
    if values["x_max"] <= values["x_min"] or values["y_max"] <= values["y_min"]:
        raise MultimodalSchemaError("bbox must have positive area")


def _json_ready(value: Any) -> Any:
    if isinstance(value, tuple):
        return [_json_ready(item) for item in value]
    if isinstance(value, list):
        return [_json_ready(item) for item in value]
    if isinstance(value, dict):
        return {str(key): _json_ready(item) for key, item in value.items()}
    if hasattr(value, "to_dict"):
        return value.to_dict()
    return value


def _copy_bbox(value: Mapping[str, Any] | None) -> dict[str, Any] | None:
    return dict(value) if value is not None else None


def _checksum_payload(payload: dict[str, Any]) -> dict[str, Any]:
    payload = dict(payload)
    payload.pop("created_at", None)
    payload.pop("updated_at", None)
    return payload


@dataclass(frozen=True)
class VisualCandidate:
    candidate_id: str
    document_id: str
    page_number: int
    candidate_type: str
    bbox: dict[str, Any]
    source_refs: tuple[str, ...] = ()
    reason_codes: tuple[str, ...] = ()
    image_path: str | None = None
    text_hint: str | None = None
    required: bool = True
    metadata: dict[str, Any] = field(default_factory=dict)
    schema_version: str = MULTIMODAL_SCHEMA_VERSION
    created_at: str = field(default_factory=utc_now)

    def __post_init__(self) -> None:
        validate_schema_version(self.schema_version)
        if not self.candidate_id or not self.document_id:
            raise MultimodalSchemaError("visual candidate requires ids")
        if self.page_number <= 0:
            raise MultimodalSchemaError("visual candidate page_number must be positive")
        if self.candidate_type not in VISUAL_CANDIDATE_TYPES:
            raise MultimodalSchemaError(f"unsupported visual candidate type: {self.candidate_type}")
        validate_bbox(self.bbox)

    def to_dict(self) -> dict[str, Any]:
        return _json_ready(asdict(self))

    @classmethod
    def from_mapping(cls, value: Mapping[str, Any]) -> VisualCandidate:
        return cls(
            candidate_id=str(value["candidate_id"]),
            document_id=str(value["document_id"]),
            page_number=int(value["page_number"]),
            candidate_type=str(value["candidate_type"]),
            bbox=dict(value["bbox"]),
            source_refs=tuple(str(item) for item in value.get("source_refs") or ()),
            reason_codes=tuple(str(item) for item in value.get("reason_codes") or ()),
            image_path=str(value["image_path"]) if value.get("image_path") is not None else None,
            text_hint=str(value["text_hint"]) if value.get("text_hint") is not None else None,
            required=bool(value.get("required", True)),
            metadata=dict(value.get("metadata") or {}),
            schema_version=str(value.get("schema_version") or MULTIMODAL_SCHEMA_VERSION),
            created_at=str(value.get("created_at") or utc_now()),
        )

    def checksum(self) -> str:
        return sha256_json(_checksum_payload(self.to_dict()))


@dataclass(frozen=True)
class VisualRegion:
    region_id: str
    candidate_id: str
    document_id: str
    page_number: int
    region_type: str
    bbox: dict[str, Any]
    coordinate_space_id: str
    transform_chain: tuple[str, ...] = ()
    confidence: float = 1.0
    source_refs: tuple[str, ...] = ()
    provenance: dict[str, Any] = field(default_factory=dict)
    schema_version: str = MULTIMODAL_SCHEMA_VERSION
    created_at: str = field(default_factory=utc_now)

    def __post_init__(self) -> None:
        validate_schema_version(self.schema_version)
        if self.region_type not in VISUAL_REGION_TYPES:
            raise MultimodalSchemaError(f"unsupported visual region type: {self.region_type}")
        if self.page_number <= 0:
            raise MultimodalSchemaError("visual region page_number must be positive")
        if not 0.0 <= float(self.confidence) <= 1.0:
            raise MultimodalSchemaError("visual region confidence must be in [0, 1]")
        validate_bbox(self.bbox)
        if not self.coordinate_space_id:
            raise MultimodalSchemaError("visual region coordinate_space_id is required")

    def to_dict(self) -> dict[str, Any]:
        return _json_ready(asdict(self))

    @classmethod
    def from_mapping(cls, value: Mapping[str, Any]) -> VisualRegion:
        return cls(
            region_id=str(value["region_id"]),
            candidate_id=str(value["candidate_id"]),
            document_id=str(value["document_id"]),
            page_number=int(value["page_number"]),
            region_type=str(value["region_type"]),
            bbox=dict(value["bbox"]),
            coordinate_space_id=str(value["coordinate_space_id"]),
            transform_chain=tuple(str(item) for item in value.get("transform_chain") or ()),
            confidence=float(value.get("confidence", 1.0)),
            source_refs=tuple(str(item) for item in value.get("source_refs") or ()),
            provenance=dict(value.get("provenance") or {}),
            schema_version=str(value.get("schema_version") or MULTIMODAL_SCHEMA_VERSION),
            created_at=str(value.get("created_at") or utc_now()),
        )

    def checksum(self) -> str:
        return sha256_json(_checksum_payload(self.to_dict()))


@dataclass(frozen=True)
class VisualAsset:
    asset_id: str
    candidate_id: str
    region_id: str
    document_id: str
    page_number: int
    asset_kind: str
    source_path: str | None
    storage_reference: str
    image_checksum: str
    width: int
    height: int
    bbox: dict[str, Any]
    coordinate_space_id: str
    transform_chain: tuple[str, ...] = ()
    duplicate_of: str | None = None
    terminal_status: str = "available"
    raw_asset_reference_preserved: bool = True
    schema_version: str = VISUAL_ASSET_SCHEMA_VERSION
    created_at: str = field(default_factory=utc_now)

    def __post_init__(self) -> None:
        if not self.schema_version.startswith("visual_asset_"):
            raise MultimodalSchemaError("unsupported visual asset schema version")
        if self.page_number <= 0 or self.width <= 0 or self.height <= 0:
            raise MultimodalSchemaError("visual asset dimensions/page must be positive")
        if not self.asset_id or not self.storage_reference or not self.image_checksum:
            raise MultimodalSchemaError("visual asset requires stable ids and checksum")
        validate_bbox(self.bbox)

    def to_dict(self) -> dict[str, Any]:
        return _json_ready(asdict(self))

    @classmethod
    def from_mapping(cls, value: Mapping[str, Any]) -> VisualAsset:
        return cls(
            asset_id=str(value["asset_id"]),
            candidate_id=str(value["candidate_id"]),
            region_id=str(value["region_id"]),
            document_id=str(value["document_id"]),
            page_number=int(value["page_number"]),
            asset_kind=str(value["asset_kind"]),
            source_path=str(value["source_path"]) if value.get("source_path") is not None else None,
            storage_reference=str(value["storage_reference"]),
            image_checksum=str(value["image_checksum"]),
            width=int(value["width"]),
            height=int(value["height"]),
            bbox=dict(value["bbox"]),
            coordinate_space_id=str(value["coordinate_space_id"]),
            transform_chain=tuple(str(item) for item in value.get("transform_chain") or ()),
            duplicate_of=str(value["duplicate_of"]) if value.get("duplicate_of") else None,
            terminal_status=str(value.get("terminal_status") or "available"),
            raw_asset_reference_preserved=bool(value.get("raw_asset_reference_preserved", True)),
            schema_version=str(value.get("schema_version") or VISUAL_ASSET_SCHEMA_VERSION),
            created_at=str(value.get("created_at") or utc_now()),
        )

    def checksum(self) -> str:
        return sha256_json(_checksum_payload(self.to_dict()))


@dataclass(frozen=True)
class VisualBackendCapabilities:
    supports_region_detection: bool = True
    supports_visual_ocr: bool = True
    supports_charts: bool = True
    supports_diagrams: bool = True
    supports_signatures: bool = True
    supports_stamps: bool = True
    supports_logos: bool = True
    supports_visual_table_verification: bool = True
    max_image_pixels: int = 6_000_000
    max_image_bytes: int = 8_000_000
    value_kinds: tuple[str, ...] = ("text", "geometry", "structure", "numeric")

    def __post_init__(self) -> None:
        if self.max_image_pixels <= 0 or self.max_image_bytes <= 0:
            raise MultimodalSchemaError("visual backend limits must be positive")

    def to_dict(self) -> dict[str, Any]:
        return _json_ready(asdict(self))

    @classmethod
    def from_mapping(cls, value: Mapping[str, Any]) -> VisualBackendCapabilities:
        payload = dict(value)
        if "value_kinds" in payload:
            payload["value_kinds"] = tuple(str(item) for item in payload["value_kinds"])
        return cls(**{key: payload[key] for key in cls.__dataclass_fields__ if key in payload})


@dataclass(frozen=True)
class VisualBackendDescriptor:
    backend_id: str
    display_name: str
    adapter_name: str
    version: str
    capabilities: VisualBackendCapabilities
    privacy_classification: str = "local_only"
    enabled: bool = True
    deterministic: bool = True
    external: bool = False
    actual_backend: bool = True
    placeholder: bool = False
    timeout_ms: int = 1_000
    max_attempts: int = 2
    max_response_bytes: int = 32_768
    cost_units_per_request: int = 1
    correlated_group: str = "local_cv"
    limitations: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if not self.backend_id or not self.adapter_name or not self.version:
            raise MultimodalSchemaError("visual backend descriptor requires stable ids")
        if self.privacy_classification not in PRIVACY_CLASSES:
            raise MultimodalSchemaError("unsupported visual backend privacy classification")
        if self.external and self.privacy_classification != "external":
            raise MultimodalSchemaError("external backend must use external privacy")
        for name in ("timeout_ms", "max_attempts", "max_response_bytes", "cost_units_per_request"):
            if int(getattr(self, name)) <= 0:
                raise MultimodalSchemaError(f"visual backend {name} must be positive")
        if self.placeholder and self.actual_backend:
            raise MultimodalSchemaError("placeholder backend cannot be actual")

    def to_dict(self) -> dict[str, Any]:
        return _json_ready(asdict(self))

    @classmethod
    def from_mapping(cls, value: Mapping[str, Any]) -> VisualBackendDescriptor:
        payload = dict(value)
        payload["capabilities"] = VisualBackendCapabilities.from_mapping(
            dict(payload.get("capabilities") or {})
        )
        if "limitations" in payload:
            payload["limitations"] = tuple(str(item) for item in payload["limitations"])
        return cls(**{key: payload[key] for key in cls.__dataclass_fields__ if key in payload})

    def checksum(self) -> str:
        return sha256_json(self.to_dict())


@dataclass(frozen=True)
class VisualBackendRequest:
    request_id: str
    candidate_id: str
    backend_id: str
    idempotency_key: str
    status: str
    payload: dict[str, Any]
    timeout_ms: int
    budget_units: int
    created_at: str = field(default_factory=utc_now)

    def __post_init__(self) -> None:
        if self.status not in BACKEND_REQUEST_STATUSES:
            raise MultimodalSchemaError(f"unsupported visual backend request status: {self.status}")
        if self.timeout_ms <= 0 or self.budget_units <= 0:
            raise MultimodalSchemaError("visual backend request timeout/budget must be positive")

    def to_dict(self) -> dict[str, Any]:
        return _json_ready(asdict(self))

    def checksum(self) -> str:
        return sha256_json(_checksum_payload(self.to_dict()))


@dataclass(frozen=True)
class VisualBackendAttempt:
    attempt_id: str
    request_id: str
    candidate_id: str
    backend_id: str
    attempt_index: int
    status: str
    terminal: bool
    latency_ms: float
    retryable: bool = False
    error_code: str | None = None
    reason: str = ""

    def __post_init__(self) -> None:
        if self.status not in BACKEND_ATTEMPT_STATUSES:
            raise MultimodalSchemaError(f"unsupported visual backend attempt status: {self.status}")
        if self.attempt_index <= 0:
            raise MultimodalSchemaError("visual backend attempt_index must be positive")
        if self.latency_ms < 0:
            raise MultimodalSchemaError("visual backend latency must be non-negative")

    def to_dict(self) -> dict[str, Any]:
        return _json_ready(asdict(self))


@dataclass(frozen=True)
class VisualBackendResult:
    result_id: str
    request_id: str
    candidate_id: str
    backend_id: str
    detected_type: str
    confidence: float
    regions: tuple[dict[str, Any], ...] = ()
    visual_text: tuple[dict[str, Any], ...] = ()
    chart: dict[str, Any] | None = None
    diagram: dict[str, Any] | None = None
    signature: dict[str, Any] | None = None
    stamp: dict[str, Any] | None = None
    logo: dict[str, Any] | None = None
    table_verification: dict[str, Any] | None = None
    source_refs: tuple[str, ...] = ()
    raw_output: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if (
            self.detected_type not in VISUAL_REGION_TYPES
            and self.detected_type not in VISUAL_CANDIDATE_TYPES
        ):
            raise MultimodalSchemaError(f"unsupported detected visual type: {self.detected_type}")
        if not 0.0 <= float(self.confidence) <= 1.0:
            raise MultimodalSchemaError("visual backend result confidence must be in [0, 1]")

    def to_dict(self) -> dict[str, Any]:
        payload = _json_ready(asdict(self))
        payload["checksum"] = self.checksum()
        return payload

    @classmethod
    def from_mapping(cls, value: Mapping[str, Any]) -> VisualBackendResult:
        payload = dict(value)
        payload.pop("checksum", None)
        payload["regions"] = tuple(dict(item) for item in payload.get("regions") or ())
        payload["visual_text"] = tuple(dict(item) for item in payload.get("visual_text") or ())
        payload["source_refs"] = tuple(str(item) for item in payload.get("source_refs") or ())
        payload["raw_output"] = dict(payload.get("raw_output") or {})
        return cls(**{key: payload[key] for key in cls.__dataclass_fields__ if key in payload})

    def checksum(self) -> str:
        return sha256_json(
            {
                "request_id": self.request_id,
                "candidate_id": self.candidate_id,
                "backend_id": self.backend_id,
                "detected_type": self.detected_type,
                "confidence": self.confidence,
                "regions": _json_ready(self.regions),
                "visual_text": _json_ready(self.visual_text),
                "chart": _json_ready(self.chart),
                "diagram": _json_ready(self.diagram),
                "signature": _json_ready(self.signature),
                "stamp": _json_ready(self.stamp),
                "logo": _json_ready(self.logo),
                "table_verification": _json_ready(self.table_verification),
                "source_refs": list(self.source_refs),
                "raw_output": _json_ready(self.raw_output),
            }
        )


@dataclass(frozen=True)
class Figure:
    figure_id: str
    candidate_id: str
    asset_id: str
    region_id: str
    document_id: str
    page_number: int
    figure_type: str
    caption_text: str | None = None
    confidence: float = 1.0
    provenance: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return _json_ready(asdict(self))


@dataclass(frozen=True)
class FigureCaptionLink:
    link_id: str
    figure_id: str
    caption_region_id: str
    caption_text: str
    confidence: float
    rule: str = CAPTION_POLICY_VERSION

    def to_dict(self) -> dict[str, Any]:
        return _json_ready(asdict(self))


@dataclass(frozen=True)
class VisualTextBlock:
    text_block_id: str
    candidate_id: str
    region_id: str
    document_id: str
    page_number: int
    text: str
    normalized_text: str
    language: str = "vi"
    confidence: float = 1.0
    diacritics_preserved: bool = True
    source_refs: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        return _json_ready(asdict(self))


@dataclass(frozen=True)
class Chart:
    chart_id: str
    candidate_id: str
    asset_id: str
    region_id: str
    document_id: str
    page_number: int
    chart_type: str
    title: str
    confidence: float = 1.0
    exact_value_count: int = 0
    estimated_value_count: int = 0
    unsafe_exact_value: bool = False

    def to_dict(self) -> dict[str, Any]:
        return _json_ready(asdict(self))


@dataclass(frozen=True)
class ChartAxis:
    axis_id: str
    chart_id: str
    axis: str
    label: str
    scale: str = "linear"
    confidence: float = 1.0

    def to_dict(self) -> dict[str, Any]:
        return _json_ready(asdict(self))


@dataclass(frozen=True)
class ChartLegend:
    legend_id: str
    chart_id: str
    label: str
    color: str
    confidence: float = 1.0

    def to_dict(self) -> dict[str, Any]:
        return _json_ready(asdict(self))


@dataclass(frozen=True)
class ChartSeries:
    series_id: str
    chart_id: str
    label: str
    chart_type: str
    confidence: float = 1.0

    def to_dict(self) -> dict[str, Any]:
        return _json_ready(asdict(self))


@dataclass(frozen=True)
class ChartDataPoint:
    point_id: str
    chart_id: str
    series_id: str
    label: str
    value: float
    value_semantics: str
    uncertainty: float
    evidence: str
    confidence: float = 1.0

    def __post_init__(self) -> None:
        if self.value_semantics not in {"exact", "estimated"}:
            raise MultimodalSchemaError("chart point value_semantics must be exact or estimated")
        if self.value_semantics == "estimated" and self.uncertainty <= 0:
            raise MultimodalSchemaError("estimated chart values require uncertainty")

    def to_dict(self) -> dict[str, Any]:
        return _json_ready(asdict(self))


@dataclass(frozen=True)
class Diagram:
    diagram_id: str
    candidate_id: str
    asset_id: str
    region_id: str
    document_id: str
    page_number: int
    diagram_type: str
    confidence: float = 1.0
    relation_graph_valid: bool = True

    def to_dict(self) -> dict[str, Any]:
        return _json_ready(asdict(self))


@dataclass(frozen=True)
class DiagramNode:
    node_id: str
    diagram_id: str
    label: str
    bbox: dict[str, Any]
    confidence: float = 1.0

    def __post_init__(self) -> None:
        validate_bbox(self.bbox)

    def to_dict(self) -> dict[str, Any]:
        return _json_ready(asdict(self))


@dataclass(frozen=True)
class DiagramEdge:
    edge_id: str
    diagram_id: str
    source_node_id: str
    target_node_id: str
    direction: str
    relation_type: str = "flow"
    confidence: float = 1.0

    def __post_init__(self) -> None:
        if self.direction not in {"forward", "backward", "bidirectional", "undirected"}:
            raise MultimodalSchemaError("unsupported diagram edge direction")

    def to_dict(self) -> dict[str, Any]:
        return _json_ready(asdict(self))


@dataclass(frozen=True)
class SignatureRegion:
    signature_id: str
    candidate_id: str
    asset_id: str
    region_id: str
    document_id: str
    page_number: int
    linked_text: str | None = None
    confidence: float = 1.0
    identity_inferred: bool = False

    def to_dict(self) -> dict[str, Any]:
        return _json_ready(asdict(self))


@dataclass(frozen=True)
class StampRegion:
    stamp_id: str
    candidate_id: str
    asset_id: str
    region_id: str
    document_id: str
    page_number: int
    linked_text: str | None = None
    confidence: float = 1.0

    def to_dict(self) -> dict[str, Any]:
        return _json_ready(asdict(self))


@dataclass(frozen=True)
class LogoRegion:
    logo_id: str
    candidate_id: str
    asset_id: str
    region_id: str
    document_id: str
    page_number: int
    brand_text: str | None = None
    confidence: float = 1.0

    def to_dict(self) -> dict[str, Any]:
        return _json_ready(asdict(self))


@dataclass(frozen=True)
class MultimodalEvidence:
    evidence_id: str
    candidate_id: str
    evidence_type: str
    value: dict[str, Any]
    confidence: float
    source_refs: tuple[str, ...] = ()
    checksum: str | None = None

    def __post_init__(self) -> None:
        if self.evidence_type not in EVIDENCE_TYPES:
            raise MultimodalSchemaError(
                f"unsupported multimodal evidence type: {self.evidence_type}"
            )
        if not 0.0 <= self.confidence <= 1.0:
            raise MultimodalSchemaError("multimodal evidence confidence must be in [0, 1]")
        if self.checksum is None:
            object.__setattr__(
                self,
                "checksum",
                sha256_json(
                    {
                        "candidate_id": self.candidate_id,
                        "evidence_type": self.evidence_type,
                        "value": self.value,
                        "source_refs": list(self.source_refs),
                    }
                ),
            )

    def to_dict(self) -> dict[str, Any]:
        return _json_ready(asdict(self))


@dataclass(frozen=True)
class MultimodalIssue:
    issue_id: str
    candidate_id: str
    issue_type: str
    severity: str
    terminal: bool
    message: str = ""
    review_required: bool = False
    source_refs: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if self.severity not in ISSUE_SEVERITIES:
            raise MultimodalSchemaError(f"unsupported multimodal issue severity: {self.severity}")

    def to_dict(self) -> dict[str, Any]:
        return _json_ready(asdict(self))


@dataclass(frozen=True)
class VisualRelationGraph:
    graph_id: str
    candidate_id: str
    node_ids: tuple[str, ...]
    edge_ids: tuple[str, ...]
    valid: bool = True
    reason_codes: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        return _json_ready(asdict(self))


@dataclass(frozen=True)
class MultimodalExtractionResult:
    canonical_document: Any
    base_document_checksum: str
    config_checksum: str
    mode: str
    registry_checksum: str
    candidates: tuple[VisualCandidate, ...] = ()
    assets: tuple[VisualAsset, ...] = ()
    regions: tuple[VisualRegion, ...] = ()
    requests: tuple[VisualBackendRequest, ...] = ()
    attempts: tuple[VisualBackendAttempt, ...] = ()
    backend_results: tuple[VisualBackendResult, ...] = ()
    figures: tuple[Figure, ...] = ()
    caption_links: tuple[FigureCaptionLink, ...] = ()
    visual_text_blocks: tuple[VisualTextBlock, ...] = ()
    charts: tuple[Chart, ...] = ()
    chart_axes: tuple[ChartAxis, ...] = ()
    chart_legends: tuple[ChartLegend, ...] = ()
    chart_series: tuple[ChartSeries, ...] = ()
    chart_data_points: tuple[ChartDataPoint, ...] = ()
    diagrams: tuple[Diagram, ...] = ()
    diagram_nodes: tuple[DiagramNode, ...] = ()
    diagram_edges: tuple[DiagramEdge, ...] = ()
    signatures: tuple[SignatureRegion, ...] = ()
    stamps: tuple[StampRegion, ...] = ()
    logos: tuple[LogoRegion, ...] = ()
    relation_graphs: tuple[VisualRelationGraph, ...] = ()
    evidence: tuple[MultimodalEvidence, ...] = ()
    issues: tuple[MultimodalIssue, ...] = ()
    review_packages: tuple[dict[str, Any], ...] = ()
    performance: dict[str, Any] = field(default_factory=dict)
    security: dict[str, Any] = field(default_factory=dict)
    comparison: dict[str, Any] = field(default_factory=dict)

    @property
    def terminal_visual_coverage(self) -> float:
        if not self.candidates:
            return 1.0
        terminal_ids = {issue.candidate_id for issue in self.issues if issue.terminal} | {
            result.candidate_id for result in self.backend_results
        }
        return len(terminal_ids) / len({candidate.candidate_id for candidate in self.candidates})

    @property
    def duplicate_backend_call_count(self) -> int:
        keys = [request.idempotency_key for request in self.requests]
        return len(keys) - len(set(keys))

    def metadata(self, *, artifact_reference: str | None = None) -> dict[str, Any]:
        return {
            "schema_name": MULTIMODAL_SCHEMA_NAME,
            "schema_version": MULTIMODAL_SCHEMA_VERSION,
            "multimodal_contract_version": MULTIMODAL_CONTRACT_VERSION,
            "visual_backend_contract_version": VISUAL_BACKEND_CONTRACT_VERSION,
            "visual_backend_registry_version": VISUAL_BACKEND_REGISTRY_VERSION,
            "mode": self.mode,
            "config_checksum": self.config_checksum,
            "registry_checksum": self.registry_checksum,
            "artifact_reference": artifact_reference,
            "candidate_count": len(self.candidates),
            "asset_count": len(self.assets),
            "backend_result_count": len(self.backend_results),
            "figure_count": len(self.figures),
            "chart_count": len(self.charts),
            "diagram_count": len(self.diagrams),
            "visual_text_block_count": len(self.visual_text_blocks),
            "issue_count": len(self.issues),
            "review_package_count": len(self.review_packages),
            "terminal_visual_coverage": self.terminal_visual_coverage,
            "duplicate_backend_call_count": self.duplicate_backend_call_count,
            "retrieval_ready": self.retrieval_ready_representation(),
        }

    def retrieval_ready_representation(self) -> dict[str, Any]:
        return {
            "figures": [
                {
                    "figure_id": item.figure_id,
                    "caption_text": item.caption_text,
                    "page_number": item.page_number,
                }
                for item in self.figures
            ],
            "charts": [
                {"chart_id": item.chart_id, "title": item.title, "chart_type": item.chart_type}
                for item in self.charts
            ],
            "diagrams": [
                {"diagram_id": item.diagram_id, "diagram_type": item.diagram_type}
                for item in self.diagrams
            ],
            "visual_text": [
                {
                    "text_block_id": item.text_block_id,
                    "text": item.text,
                    "page_number": item.page_number,
                }
                for item in self.visual_text_blocks
            ],
            "asset_refs_only": True,
        }

    def to_artifact_dict(self) -> dict[str, Any]:
        return {
            "artifact_type": "phase6_multimodal_extraction",
            "schema_version": MULTIMODAL_SCHEMA_VERSION,
            "mode": self.mode,
            "base_document_checksum": self.base_document_checksum,
            "config_checksum": self.config_checksum,
            "registry_checksum": self.registry_checksum,
            "candidates": [item.to_dict() for item in self.candidates],
            "assets": [item.to_dict() for item in self.assets],
            "regions": [item.to_dict() for item in self.regions],
            "requests": [item.to_dict() for item in self.requests],
            "attempts": [item.to_dict() for item in self.attempts],
            "backend_results": [item.to_dict() for item in self.backend_results],
            "figures": [item.to_dict() for item in self.figures],
            "caption_links": [item.to_dict() for item in self.caption_links],
            "visual_text_blocks": [item.to_dict() for item in self.visual_text_blocks],
            "charts": [item.to_dict() for item in self.charts],
            "chart_axes": [item.to_dict() for item in self.chart_axes],
            "chart_legends": [item.to_dict() for item in self.chart_legends],
            "chart_series": [item.to_dict() for item in self.chart_series],
            "chart_data_points": [item.to_dict() for item in self.chart_data_points],
            "diagrams": [item.to_dict() for item in self.diagrams],
            "diagram_nodes": [item.to_dict() for item in self.diagram_nodes],
            "diagram_edges": [item.to_dict() for item in self.diagram_edges],
            "signatures": [item.to_dict() for item in self.signatures],
            "stamps": [item.to_dict() for item in self.stamps],
            "logos": [item.to_dict() for item in self.logos],
            "relation_graphs": [item.to_dict() for item in self.relation_graphs],
            "evidence": [item.to_dict() for item in self.evidence],
            "issues": [item.to_dict() for item in self.issues],
            "review_packages": list(self.review_packages),
            "performance": dict(self.performance),
            "security": dict(self.security),
            "comparison": dict(self.comparison),
        }


__all__ = [
    "CAPTION_POLICY_VERSION",
    "CANDIDATE_POLICY_VERSION",
    "CHART_CLASSIFIER_VERSION",
    "CHART_EXTRACTOR_VERSION",
    "DIAGRAM_CLASSIFIER_VERSION",
    "DIAGRAM_EXTRACTOR_VERSION",
    "FIGURE_DETECTOR_VERSION",
    "MULTIMODAL_CONTRACT_VERSION",
    "MULTIMODAL_FUSION_VERSION",
    "MULTIMODAL_PRIVACY_POLICY_VERSION",
    "MULTIMODAL_SCHEMA_NAME",
    "MULTIMODAL_SCHEMA_VERSION",
    "SIGNATURE_STAMP_LOGO_VERSION",
    "VISUAL_ASSET_SCHEMA_VERSION",
    "VISUAL_BACKEND_CONTRACT_VERSION",
    "VISUAL_BACKEND_REGISTRY_VERSION",
    "VISUAL_OCR_VERSION",
    "VISUAL_VERIFICATION_VERSION",
    "Chart",
    "ChartAxis",
    "ChartDataPoint",
    "ChartLegend",
    "ChartSeries",
    "Diagram",
    "DiagramEdge",
    "DiagramNode",
    "Figure",
    "FigureCaptionLink",
    "LogoRegion",
    "MultimodalEvidence",
    "MultimodalExtractionResult",
    "MultimodalIssue",
    "MultimodalSchemaError",
    "SignatureRegion",
    "StampRegion",
    "VisualAsset",
    "VisualBackendAttempt",
    "VisualBackendCapabilities",
    "VisualBackendDescriptor",
    "VisualBackendRequest",
    "VisualBackendResult",
    "VisualCandidate",
    "VisualRegion",
    "VisualRelationGraph",
    "sha256_json",
    "stable_id",
]
