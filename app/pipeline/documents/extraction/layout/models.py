from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from typing import Any

from app.pipeline.documents.extraction.canonical.geometry import AxisAlignedBoundingBox

LAYOUT_SCHEMA_NAME = "layout_page"
LAYOUT_SCHEMA_VERSION = "1.0.0"
LAYOUT_DETECTOR_VERSION = "rule_layout_detector_v1"
BLOCK_CLASSIFIER_VERSION = "rule_block_classifier_v1"
READING_ORDER_VERSION = "reading_order_graph_v1"
READING_ORDER_POLICY_VERSION = "reading_order_policy_v1"
SUPPORTED_LAYOUT_MAJOR = "1"

LAYOUT_BLOCK_TYPES = {
    "title",
    "heading",
    "paragraph",
    "list",
    "list_item",
    "header",
    "footer",
    "page_number",
    "caption",
    "footnote",
    "table_region",
    "figure_region",
    "image_region",
    "signature",
    "stamp",
    "logo",
    "unknown",
    "noise",
}

LAYOUT_REGION_TYPES = {
    "page",
    "body",
    "column",
    "spanning",
    "header",
    "footer",
    "footnote",
    "sidebar",
    "table_region",
    "figure_region",
    "ambiguous_overlap",
}

EDGE_STATUSES = {"accepted", "rejected", "ambiguous"}
EDGE_RELATIONS = {"before", "contains", "associated_with"}
ISSUE_SEVERITIES = {"info", "warning", "review", "fail_closed"}


class LayoutError(ValueError):
    """Base error for Phase 3 layout contract failures."""


class LayoutSchemaError(LayoutError):
    """Raised when a serialized layout artifact violates the schema contract."""


@dataclass(frozen=True)
class LayoutIssue:
    issue_id: str
    code: str
    severity: str
    message: str
    page_number: int
    block_ids: tuple[str, ...] = ()
    region_ids: tuple[str, ...] = ()
    reason_codes: tuple[str, ...] = ()
    provenance: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.issue_id:
            raise LayoutSchemaError("layout issue requires issue_id")
        if not self.code:
            raise LayoutSchemaError("layout issue requires code")
        if self.severity not in ISSUE_SEVERITIES:
            raise LayoutSchemaError(f"unsupported layout issue severity: {self.severity}")
        if self.page_number <= 0:
            raise LayoutSchemaError("layout issue page_number must be positive")

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["block_ids"] = list(self.block_ids)
        payload["region_ids"] = list(self.region_ids)
        payload["reason_codes"] = list(self.reason_codes)
        return payload

    @classmethod
    def from_mapping(cls, value: Mapping[str, Any]) -> LayoutIssue:
        payload = dict(value)
        return cls(
            issue_id=str(payload["issue_id"]),
            code=str(payload["code"]),
            severity=str(payload["severity"]),
            message=str(payload.get("message") or ""),
            page_number=int(payload["page_number"]),
            block_ids=tuple(str(item) for item in payload.get("block_ids") or ()),
            region_ids=tuple(str(item) for item in payload.get("region_ids") or ()),
            reason_codes=tuple(str(item) for item in payload.get("reason_codes") or ()),
            provenance=dict(payload.get("provenance") or {}),
        )


@dataclass(frozen=True)
class LayoutBlock:
    block_id: str
    page_number: int
    block_type: str
    bbox: AxisAlignedBoundingBox
    text: str | None = None
    source: str = "native"
    source_block_ids: tuple[str, ...] = ()
    confidence: float = 1.0
    region_id: str | None = None
    rotation: int = 0
    clipped: bool = False
    clipping_reason: str | None = None
    reason_codes: tuple[str, ...] = ()
    provenance: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.block_id:
            raise LayoutSchemaError("layout block requires block_id")
        if self.page_number <= 0:
            raise LayoutSchemaError("layout block page_number must be positive")
        if self.block_type not in LAYOUT_BLOCK_TYPES:
            raise LayoutSchemaError(f"unsupported layout block type: {self.block_type}")
        if not 0.0 <= float(self.confidence) <= 1.0:
            raise LayoutSchemaError("layout block confidence must be in [0, 1]")
        if self.clipped and not self.clipping_reason:
            raise LayoutSchemaError("clipped layout block requires clipping_reason")

    @property
    def coordinate_space_id(self) -> str:
        return self.bbox.coordinate_space_id

    def to_dict(self) -> dict[str, Any]:
        return {
            "block_id": self.block_id,
            "page_number": self.page_number,
            "block_type": self.block_type,
            "bbox": _bbox_to_dict(self.bbox),
            "text": self.text,
            "source": self.source,
            "source_block_ids": list(self.source_block_ids),
            "confidence": self.confidence,
            "region_id": self.region_id,
            "rotation": self.rotation,
            "clipped": self.clipped,
            "clipping_reason": self.clipping_reason,
            "reason_codes": list(self.reason_codes),
            "provenance": dict(self.provenance),
        }

    @classmethod
    def from_mapping(cls, value: Mapping[str, Any]) -> LayoutBlock:
        payload = dict(value)
        return cls(
            block_id=str(payload["block_id"]),
            page_number=int(payload["page_number"]),
            block_type=str(payload["block_type"]),
            bbox=AxisAlignedBoundingBox.from_dict(dict(payload["bbox"])),
            text=str(payload["text"]) if payload.get("text") is not None else None,
            source=str(payload.get("source") or "native"),
            source_block_ids=tuple(str(item) for item in payload.get("source_block_ids") or ()),
            confidence=float(payload.get("confidence", 1.0)),
            region_id=str(payload["region_id"]) if payload.get("region_id") is not None else None,
            rotation=int(payload.get("rotation") or 0),
            clipped=bool(payload.get("clipped", False)),
            clipping_reason=(
                str(payload["clipping_reason"])
                if payload.get("clipping_reason") is not None
                else None
            ),
            reason_codes=tuple(str(item) for item in payload.get("reason_codes") or ()),
            provenance=dict(payload.get("provenance") or {}),
        )


@dataclass(frozen=True)
class LayoutRegion:
    region_id: str
    page_number: int
    region_type: str
    bbox: AxisAlignedBoundingBox
    block_ids: tuple[str, ...] = ()
    parent_region_id: str | None = None
    child_region_ids: tuple[str, ...] = ()
    column_index: int | None = None
    confidence: float = 1.0
    reason_codes: tuple[str, ...] = ()
    provenance: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.region_id:
            raise LayoutSchemaError("layout region requires region_id")
        if self.page_number <= 0:
            raise LayoutSchemaError("layout region page_number must be positive")
        if self.region_type not in LAYOUT_REGION_TYPES:
            raise LayoutSchemaError(f"unsupported layout region type: {self.region_type}")
        if self.column_index is not None and self.column_index < 0:
            raise LayoutSchemaError("layout region column_index must not be negative")
        if not 0.0 <= float(self.confidence) <= 1.0:
            raise LayoutSchemaError("layout region confidence must be in [0, 1]")

    @property
    def coordinate_space_id(self) -> str:
        return self.bbox.coordinate_space_id

    def to_dict(self) -> dict[str, Any]:
        return {
            "region_id": self.region_id,
            "page_number": self.page_number,
            "region_type": self.region_type,
            "bbox": _bbox_to_dict(self.bbox),
            "block_ids": list(self.block_ids),
            "parent_region_id": self.parent_region_id,
            "child_region_ids": list(self.child_region_ids),
            "column_index": self.column_index,
            "confidence": self.confidence,
            "reason_codes": list(self.reason_codes),
            "provenance": dict(self.provenance),
        }

    @classmethod
    def from_mapping(cls, value: Mapping[str, Any]) -> LayoutRegion:
        payload = dict(value)
        return cls(
            region_id=str(payload["region_id"]),
            page_number=int(payload["page_number"]),
            region_type=str(payload["region_type"]),
            bbox=AxisAlignedBoundingBox.from_dict(dict(payload["bbox"])),
            block_ids=tuple(str(item) for item in payload.get("block_ids") or ()),
            parent_region_id=(
                str(payload["parent_region_id"])
                if payload.get("parent_region_id") is not None
                else None
            ),
            child_region_ids=tuple(str(item) for item in payload.get("child_region_ids") or ()),
            column_index=(
                int(payload["column_index"]) if payload.get("column_index") is not None else None
            ),
            confidence=float(payload.get("confidence", 1.0)),
            reason_codes=tuple(str(item) for item in payload.get("reason_codes") or ()),
            provenance=dict(payload.get("provenance") or {}),
        )


@dataclass(frozen=True)
class ReadingOrderEdge:
    edge_id: str
    source_id: str
    target_id: str
    relation: str = "before"
    status: str = "accepted"
    confidence: float = 1.0
    reason_codes: tuple[str, ...] = ()
    provenance: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.edge_id or not self.source_id or not self.target_id:
            raise LayoutSchemaError("reading-order edge requires ids")
        if self.relation not in EDGE_RELATIONS:
            raise LayoutSchemaError(f"unsupported reading-order relation: {self.relation}")
        if self.status not in EDGE_STATUSES:
            raise LayoutSchemaError(f"unsupported reading-order edge status: {self.status}")
        if not 0.0 <= float(self.confidence) <= 1.0:
            raise LayoutSchemaError("reading-order edge confidence must be in [0, 1]")

    def to_dict(self) -> dict[str, Any]:
        return {
            "edge_id": self.edge_id,
            "source_id": self.source_id,
            "target_id": self.target_id,
            "relation": self.relation,
            "status": self.status,
            "confidence": self.confidence,
            "reason_codes": list(self.reason_codes),
            "provenance": dict(self.provenance),
        }

    @classmethod
    def from_mapping(cls, value: Mapping[str, Any]) -> ReadingOrderEdge:
        payload = dict(value)
        return cls(
            edge_id=str(payload["edge_id"]),
            source_id=str(payload["source_id"]),
            target_id=str(payload["target_id"]),
            relation=str(payload.get("relation") or "before"),
            status=str(payload.get("status") or "accepted"),
            confidence=float(payload.get("confidence", 1.0)),
            reason_codes=tuple(str(item) for item in payload.get("reason_codes") or ()),
            provenance=dict(payload.get("provenance") or {}),
        )


@dataclass(frozen=True)
class ReadingOrderGraph:
    graph_id: str
    page_number: int
    policy_version: str = READING_ORDER_POLICY_VERSION
    graph_version: str = READING_ORDER_VERSION
    node_ids: tuple[str, ...] = ()
    edges: tuple[ReadingOrderEdge, ...] = ()
    rejected_edges: tuple[ReadingOrderEdge, ...] = ()
    linear_order: tuple[str, ...] = ()
    unresolved_cycles: tuple[tuple[str, ...], ...] = ()
    unresolved_ambiguities: tuple[str, ...] = ()
    deterministic: bool = True
    reason_codes: tuple[str, ...] = ()
    provenance: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.graph_id:
            raise LayoutSchemaError("reading-order graph requires graph_id")
        if self.page_number <= 0:
            raise LayoutSchemaError("reading-order graph page_number must be positive")
        node_set = set(self.node_ids)
        if len(node_set) != len(self.node_ids):
            raise LayoutSchemaError("reading-order graph node_ids must be unique")
        if any(item not in node_set for item in self.linear_order):
            raise LayoutSchemaError("linear_order contains an unknown node")

    def to_dict(self) -> dict[str, Any]:
        return {
            "graph_id": self.graph_id,
            "page_number": self.page_number,
            "policy_version": self.policy_version,
            "graph_version": self.graph_version,
            "node_ids": list(self.node_ids),
            "edges": [edge.to_dict() for edge in self.edges],
            "rejected_edges": [edge.to_dict() for edge in self.rejected_edges],
            "linear_order": list(self.linear_order),
            "unresolved_cycles": [list(cycle) for cycle in self.unresolved_cycles],
            "unresolved_ambiguities": list(self.unresolved_ambiguities),
            "deterministic": self.deterministic,
            "reason_codes": list(self.reason_codes),
            "provenance": dict(self.provenance),
        }

    @classmethod
    def from_mapping(cls, value: Mapping[str, Any]) -> ReadingOrderGraph:
        payload = dict(value)
        return cls(
            graph_id=str(payload["graph_id"]),
            page_number=int(payload["page_number"]),
            policy_version=str(payload.get("policy_version") or READING_ORDER_POLICY_VERSION),
            graph_version=str(payload.get("graph_version") or READING_ORDER_VERSION),
            node_ids=tuple(str(item) for item in payload.get("node_ids") or ()),
            edges=tuple(ReadingOrderEdge.from_mapping(item) for item in payload.get("edges") or ()),
            rejected_edges=tuple(
                ReadingOrderEdge.from_mapping(item) for item in payload.get("rejected_edges") or ()
            ),
            linear_order=tuple(str(item) for item in payload.get("linear_order") or ()),
            unresolved_cycles=tuple(
                tuple(str(item) for item in cycle)
                for cycle in payload.get("unresolved_cycles") or ()
            ),
            unresolved_ambiguities=tuple(
                str(item) for item in payload.get("unresolved_ambiguities") or ()
            ),
            deterministic=bool(payload.get("deterministic", True)),
            reason_codes=tuple(str(item) for item in payload.get("reason_codes") or ()),
            provenance=dict(payload.get("provenance") or {}),
        )

    def checksum(self) -> str:
        return _sha256_json(self.to_dict())


@dataclass(frozen=True)
class LayoutPage:
    document_id: str
    page_number: int
    page_index: int
    page_width: float
    page_height: float
    coordinate_space_id: str
    schema_name: str = LAYOUT_SCHEMA_NAME
    schema_version: str = LAYOUT_SCHEMA_VERSION
    detector_version: str = LAYOUT_DETECTOR_VERSION
    classifier_version: str = BLOCK_CLASSIFIER_VERSION
    reading_order_version: str = READING_ORDER_VERSION
    blocks: tuple[LayoutBlock, ...] = ()
    regions: tuple[LayoutRegion, ...] = ()
    reading_order_graph: ReadingOrderGraph | None = None
    issues: tuple[LayoutIssue, ...] = ()
    profile_checksum: str | None = None
    routing_decision_checksum: str | None = None
    mode: str = "shadow"
    artifact_version: int = 1
    coverage: float = 1.0
    created_at: str = field(default_factory=lambda: utc_now_iso())
    latency_ms: float = 0.0
    provenance: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if self.schema_name != LAYOUT_SCHEMA_NAME:
            raise LayoutSchemaError(f"unsupported layout schema name: {self.schema_name}")
        if not is_supported_layout_version(self.schema_version):
            raise LayoutSchemaError(f"unsupported layout schema version: {self.schema_version}")
        if not self.document_id:
            raise LayoutSchemaError("layout page requires document_id")
        if self.page_number <= 0 or self.page_index < 0:
            raise LayoutSchemaError("layout page indexes are invalid")
        if self.page_width <= 0 or self.page_height <= 0:
            raise LayoutSchemaError("layout page dimensions must be positive")
        block_ids = [block.block_id for block in self.blocks]
        if len(block_ids) != len(set(block_ids)):
            raise LayoutSchemaError("layout page block ids must be unique")
        region_ids = [region.region_id for region in self.regions]
        if len(region_ids) != len(set(region_ids)):
            raise LayoutSchemaError("layout page region ids must be unique")
        if not 0.0 <= float(self.coverage) <= 1.0:
            raise LayoutSchemaError("layout page coverage must be in [0, 1]")

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_name": self.schema_name,
            "schema_version": self.schema_version,
            "detector_version": self.detector_version,
            "classifier_version": self.classifier_version,
            "reading_order_version": self.reading_order_version,
            "document_id": self.document_id,
            "page_number": self.page_number,
            "page_index": self.page_index,
            "page_width": self.page_width,
            "page_height": self.page_height,
            "coordinate_space_id": self.coordinate_space_id,
            "blocks": [block.to_dict() for block in self.blocks],
            "regions": [region.to_dict() for region in self.regions],
            "reading_order_graph": (
                self.reading_order_graph.to_dict() if self.reading_order_graph is not None else None
            ),
            "issues": [issue.to_dict() for issue in self.issues],
            "profile_checksum": self.profile_checksum,
            "routing_decision_checksum": self.routing_decision_checksum,
            "mode": self.mode,
            "artifact_version": self.artifact_version,
            "coverage": self.coverage,
            "created_at": self.created_at,
            "latency_ms": self.latency_ms,
            "provenance": dict(self.provenance),
        }

    @classmethod
    def from_mapping(cls, value: Mapping[str, Any]) -> LayoutPage:
        payload = dict(value)
        _reject_unknown_keys(
            payload,
            {
                "schema_name",
                "schema_version",
                "detector_version",
                "classifier_version",
                "reading_order_version",
                "document_id",
                "page_number",
                "page_index",
                "page_width",
                "page_height",
                "coordinate_space_id",
                "blocks",
                "regions",
                "reading_order_graph",
                "issues",
                "profile_checksum",
                "routing_decision_checksum",
                "mode",
                "artifact_version",
                "coverage",
                "created_at",
                "latency_ms",
                "provenance",
            },
        )
        return cls(
            schema_name=str(payload["schema_name"]),
            schema_version=str(payload["schema_version"]),
            detector_version=str(payload.get("detector_version") or LAYOUT_DETECTOR_VERSION),
            classifier_version=str(payload.get("classifier_version") or BLOCK_CLASSIFIER_VERSION),
            reading_order_version=str(
                payload.get("reading_order_version") or READING_ORDER_VERSION
            ),
            document_id=str(payload["document_id"]),
            page_number=int(payload["page_number"]),
            page_index=int(payload["page_index"]),
            page_width=float(payload["page_width"]),
            page_height=float(payload["page_height"]),
            coordinate_space_id=str(payload["coordinate_space_id"]),
            blocks=tuple(LayoutBlock.from_mapping(item) for item in payload.get("blocks") or ()),
            regions=tuple(LayoutRegion.from_mapping(item) for item in payload.get("regions") or ()),
            reading_order_graph=(
                ReadingOrderGraph.from_mapping(payload["reading_order_graph"])
                if payload.get("reading_order_graph") is not None
                else None
            ),
            issues=tuple(LayoutIssue.from_mapping(item) for item in payload.get("issues") or ()),
            profile_checksum=(
                str(payload["profile_checksum"])
                if payload.get("profile_checksum") is not None
                else None
            ),
            routing_decision_checksum=(
                str(payload["routing_decision_checksum"])
                if payload.get("routing_decision_checksum") is not None
                else None
            ),
            mode=str(payload.get("mode") or "shadow"),
            artifact_version=int(payload.get("artifact_version") or 1),
            coverage=float(payload.get("coverage", 1.0)),
            created_at=str(payload.get("created_at") or utc_now_iso()),
            latency_ms=float(payload.get("latency_ms") or 0.0),
            provenance=dict(payload.get("provenance") or {}),
        )

    def checksum(self) -> str:
        payload = self.to_dict()
        payload.pop("latency_ms", None)
        payload.pop("created_at", None)
        return _sha256_json(payload)


def is_supported_layout_version(version: str) -> bool:
    parts = str(version).split(".")
    return bool(parts and parts[0] == SUPPORTED_LAYOUT_MAJOR)


def utc_now_iso() -> str:
    return datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _sha256_json(payload: Any) -> str:
    return hashlib.sha256(
        json.dumps(
            payload,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    ).hexdigest()


def _reject_unknown_keys(value: dict[str, Any], allowed: set[str]) -> None:
    unknown = sorted(set(value) - allowed)
    if unknown:
        raise LayoutSchemaError("unsupported layout fields: " + ", ".join(unknown))


def _bbox_to_dict(bbox: AxisAlignedBoundingBox) -> dict[str, Any]:
    return {
        "x_min": float(bbox.x_min),
        "y_min": float(bbox.y_min),
        "x_max": float(bbox.x_max),
        "y_max": float(bbox.y_max),
        "coordinate_space_id": bbox.coordinate_space_id,
    }


__all__ = [
    "BLOCK_CLASSIFIER_VERSION",
    "LAYOUT_BLOCK_TYPES",
    "LAYOUT_DETECTOR_VERSION",
    "LAYOUT_REGION_TYPES",
    "LAYOUT_SCHEMA_NAME",
    "LAYOUT_SCHEMA_VERSION",
    "READING_ORDER_POLICY_VERSION",
    "READING_ORDER_VERSION",
    "LayoutBlock",
    "LayoutError",
    "LayoutIssue",
    "LayoutPage",
    "LayoutRegion",
    "LayoutSchemaError",
    "ReadingOrderEdge",
    "ReadingOrderGraph",
    "is_supported_layout_version",
    "utc_now_iso",
]
