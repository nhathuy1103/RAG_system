"""Framework-independent contracts for structured business facts.

The generic knowledge-quality subsystem works at document and text-claim level.
These value objects deliberately model the finer-grained identity required for
business tables without coupling extraction to persistence or retrieval.
"""

from __future__ import annotations

import hashlib
import json
import math
import re
import unicodedata
from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import UTC, date, datetime, time
from decimal import Decimal
from enum import StrEnum

type ScalarValue = str | int | float | bool | Decimal | date | datetime
type ConstraintValue = ScalarValue | tuple[ScalarValue, ...]
type TemporalPoint = date | datetime

CLAIM_COMPARABLE_KEY_VERSION = "p3-claim-comparable-key-v1"


class ScopeRelation(StrEnum):
    """Directional set relation between two business scopes."""

    SAME = "same"
    LEFT_CONTAINS_RIGHT = "left_contains_right"
    RIGHT_CONTAINS_LEFT = "right_contains_left"
    OVERLAPS = "overlaps"
    DISJOINT = "disjoint"
    UNKNOWN = "unknown"


class QualifierCompatibility(StrEnum):
    """Whether two sets of claim qualifiers allow value comparison."""

    EQUAL = "equal"
    COMPATIBLE = "compatible"
    DISJOINT = "disjoint"
    UNKNOWN = "unknown"


class TemporalRelation(StrEnum):
    """Directional relation between two effective-time intervals."""

    SAME = "same"
    LEFT_CONTAINS_RIGHT = "left_contains_right"
    RIGHT_CONTAINS_LEFT = "right_contains_left"
    OVERLAPS = "overlaps"
    BEFORE = "before"
    AFTER = "after"
    UNKNOWN = "unknown"


class ClaimRelationType(StrEnum):
    """Row/claim-level outcomes; document relations remain only summaries."""

    UNCHANGED = "unchanged"
    UPDATED = "updated"
    ADDED = "added"
    REMOVED = "removed"
    CONFLICT_CANDIDATE = "conflict_candidate"
    CONDITIONAL_VARIANT = "conditional_variant"
    UNCERTAIN = "uncertain"


class ValueOperator(StrEnum):
    """Canonical semantics of one source-grounded value expression."""

    EXACT = "exact"
    APPROXIMATE = "approximate"
    RANGE = "range"
    LT = "lt"
    LTE = "lte"
    GT = "gt"
    GTE = "gte"
    BOOLEAN = "boolean"
    ENUM = "enum"
    TEXT = "text"
    UNKNOWN = "unknown"


class ValueExpressionRelation(StrEnum):
    """Logical relation between values, before any claim-level decision."""

    EQUIVALENT = "equivalent"
    COMPATIBLE = "compatible"
    DISJOINT = "disjoint"
    UNKNOWN = "unknown"
    INCOMPATIBLE_DIMENSION = "incompatible_dimension"


class EntityEvidenceSource(StrEnum):
    """Ordered provenance classes used by deterministic entity resolution."""

    CLAIM_TEXT = "claim_text"
    TABLE_CELL = "table_cell"
    TABLE_HEADER = "table_header"
    SECTION_HEADING = "section_heading"
    PARENT_CONTEXT = "parent_context"
    DOCUMENT_METADATA = "document_metadata"
    REGISTRY_FALLBACK = "registry_fallback"


class EntityMatchMethod(StrEnum):
    """Auditable registry match method; fuzzy merging is intentionally absent."""

    EXACT_CODE = "exact_code"
    EXACT_ALIAS = "exact_alias"
    CANONICAL_NAME = "canonical_name"
    NORMALIZED_ALIAS = "normalized_alias"
    CONTEXT_FALLBACK = "context_fallback"


@dataclass(frozen=True, slots=True)
class EntityEvidence:
    """One source-backed explanation for a canonical entity assignment."""

    raw_text: str
    match_method: EntityMatchMethod
    source: EntityEvidenceSource
    confidence: float
    registry_version: str
    span_start: int | None = None
    span_end: int | None = None
    source_id: str | None = None

    def __post_init__(self) -> None:
        if not self.raw_text.strip():
            raise ValueError("entity evidence raw_text cannot be blank")
        _validate_confidence(self.confidence, field_name="entity evidence confidence")
        if not self.registry_version.strip():
            raise ValueError("entity evidence registry_version cannot be blank")
        if (self.span_start is None) != (self.span_end is None):
            raise ValueError("entity evidence span requires both start and end")
        if self.span_start is not None and (
            self.span_start < 0 or self.span_end is None or self.span_end < self.span_start
        ):
            raise ValueError("entity evidence span must be ordered and non-negative")

    def to_payload(self) -> dict[str, object]:
        return {
            "raw_text": self.raw_text,
            "match_method": self.match_method.value,
            "source": self.source.value,
            "confidence": self.confidence,
            "registry_version": self.registry_version,
            "span": (
                {"start": self.span_start, "end": self.span_end}
                if self.span_start is not None
                else None
            ),
            "source_id": self.source_id,
        }

    @classmethod
    def from_payload(cls, value: object) -> EntityEvidence:
        payload = _require_mapping(value, field_name="entity_evidence")
        span = payload.get("span")
        parsed_span = _payload_source_span(span) if span is not None else None
        return cls(
            raw_text=_payload_required_text(payload.get("raw_text"), "entity_evidence.raw_text"),
            match_method=EntityMatchMethod(
                _payload_required_text(payload.get("match_method"), "entity_evidence.match_method")
            ),
            source=EntityEvidenceSource(
                _payload_required_text(payload.get("source"), "entity_evidence.source")
            ),
            confidence=_payload_required_float(
                payload.get("confidence"), "entity_evidence.confidence"
            ),
            registry_version=_payload_required_text(
                payload.get("registry_version"), "entity_evidence.registry_version"
            ),
            span_start=parsed_span[0] if parsed_span is not None else None,
            span_end=parsed_span[1] if parsed_span is not None else None,
            source_id=_payload_optional_text(payload.get("source_id"), "entity_evidence.source_id"),
        )


@dataclass(frozen=True, slots=True)
class EntityRef:
    """Deterministic canonical entity plus all evidence used to resolve it."""

    domain: str
    entity_type: str
    canonical_id: str
    canonical_name: str
    confidence: float
    registry_version: str
    parent_id: str | None = None
    evidence: tuple[EntityEvidence, ...] = ()

    def __post_init__(self) -> None:
        for field_name, value in (
            ("domain", self.domain),
            ("entity_type", self.entity_type),
            ("canonical_id", self.canonical_id),
            ("canonical_name", self.canonical_name),
            ("registry_version", self.registry_version),
        ):
            if not value.strip():
                raise ValueError(f"entity {field_name} cannot be blank")
        _validate_confidence(self.confidence, field_name="entity confidence")

    @property
    def raw_mentions(self) -> tuple[str, ...]:
        return tuple(dict.fromkeys(item.raw_text for item in self.evidence))

    def to_payload(self) -> dict[str, object]:
        return {
            "domain": self.domain,
            "entity_type": self.entity_type,
            "canonical_id": self.canonical_id,
            "canonical_name": self.canonical_name,
            "parent_id": self.parent_id,
            "raw_mentions": list(self.raw_mentions),
            "confidence": self.confidence,
            "registry_version": self.registry_version,
            "evidence": [item.to_payload() for item in self.evidence],
        }

    @classmethod
    def from_payload(cls, value: object) -> EntityRef:
        payload = _require_mapping(value, field_name="entity")
        raw_evidence = payload.get("evidence", [])
        if not isinstance(raw_evidence, list | tuple):
            raise ValueError("entity.evidence must be a list")
        return cls(
            domain=_payload_required_text(payload.get("domain"), "entity.domain"),
            entity_type=_payload_required_text(payload.get("entity_type"), "entity.entity_type"),
            canonical_id=_payload_required_text(payload.get("canonical_id"), "entity.canonical_id"),
            canonical_name=_payload_required_text(
                payload.get("canonical_name"), "entity.canonical_name"
            ),
            parent_id=_payload_optional_text(payload.get("parent_id"), "entity.parent_id"),
            confidence=_payload_required_float(payload.get("confidence"), "entity.confidence"),
            registry_version=_payload_required_text(
                payload.get("registry_version"), "entity.registry_version"
            ),
            evidence=tuple(EntityEvidence.from_payload(item) for item in raw_evidence),
        )


@dataclass(frozen=True, slots=True)
class LocationScope:
    """Hierarchical location constraints, from broadest to narrowest."""

    developer: ConstraintValue | None = None
    project: ConstraintValue | None = None
    phase: ConstraintValue | None = None
    subdivision: ConstraintValue | None = None
    building: ConstraintValue | None = None
    unit: ConstraintValue | None = None

    def to_payload(self) -> dict[str, object]:
        return _dataclass_constraints_payload(self)

    @classmethod
    def from_payload(cls, value: object) -> LocationScope:
        payload = _require_mapping(value, field_name="location")
        return cls(
            developer=_payload_optional_constraint(payload.get("developer"), "developer"),
            project=_payload_optional_constraint(payload.get("project"), "project"),
            phase=_payload_optional_constraint(payload.get("phase"), "phase"),
            subdivision=_payload_optional_constraint(payload.get("subdivision"), "subdivision"),
            building=_payload_optional_constraint(payload.get("building"), "building"),
            unit=_payload_optional_constraint(payload.get("unit"), "unit"),
        )


@dataclass(frozen=True, slots=True)
class ProductScope:
    """Product constraints orthogonal to physical location."""

    property_type: ConstraintValue | None = None
    bedrooms: ConstraintValue | None = None
    area_type: ConstraintValue | None = None
    product_variant: ConstraintValue | None = None

    def to_payload(self) -> dict[str, object]:
        return _dataclass_constraints_payload(self)

    @classmethod
    def from_payload(cls, value: object) -> ProductScope:
        payload = _require_mapping(value, field_name="product")
        return cls(
            property_type=_payload_optional_constraint(
                payload.get("property_type"), "property_type"
            ),
            bedrooms=_payload_optional_constraint(payload.get("bedrooms"), "bedrooms"),
            area_type=_payload_optional_constraint(payload.get("area_type"), "area_type"),
            product_variant=_payload_optional_constraint(
                payload.get("product_variant"), "product_variant"
            ),
        )


@dataclass(frozen=True, slots=True)
class CommercialScope:
    """Commercial applicability constraints for one fact."""

    price_type: ConstraintValue | None = None
    price_basis: ConstraintValue | None = None
    payment_plan: ConstraintValue | None = None
    discount_program: ConstraintValue | None = None
    vat_included: ConstraintValue | None = None
    maintenance_fee_included: ConstraintValue | None = None

    def to_payload(self) -> dict[str, object]:
        return _dataclass_constraints_payload(self)

    @classmethod
    def from_payload(cls, value: object) -> CommercialScope:
        payload = _require_mapping(value, field_name="commercial")
        return cls(
            price_type=_payload_optional_constraint(payload.get("price_type"), "price_type"),
            price_basis=_payload_optional_constraint(payload.get("price_basis"), "price_basis"),
            payment_plan=_payload_optional_constraint(payload.get("payment_plan"), "payment_plan"),
            discount_program=_payload_optional_constraint(
                payload.get("discount_program"), "discount_program"
            ),
            vat_included=_payload_optional_constraint(payload.get("vat_included"), "vat_included"),
            maintenance_fee_included=_payload_optional_constraint(
                payload.get("maintenance_fee_included"), "maintenance_fee_included"
            ),
        )


@dataclass(frozen=True, slots=True)
class VehicleScope:
    """Vehicle applicability facets shared by table and prose claims."""

    manufacturer: ConstraintValue | None = None
    model: ConstraintValue | None = None
    trim: ConstraintValue | None = None
    model_year: ConstraintValue | None = None
    battery_variant: ConstraintValue | None = None
    drivetrain: ConstraintValue | None = None
    market: ConstraintValue | None = None
    test_protocol: ConstraintValue | None = None
    charging_variant: ConstraintValue | None = None

    def to_payload(self) -> dict[str, object]:
        return _dataclass_constraints_payload(self)

    @classmethod
    def from_payload(cls, value: object) -> VehicleScope:
        payload = _require_mapping(value, field_name="vehicle")
        return cls(
            manufacturer=_payload_optional_constraint(payload.get("manufacturer"), "manufacturer"),
            model=_payload_optional_constraint(payload.get("model"), "model"),
            trim=_payload_optional_constraint(payload.get("trim"), "trim"),
            model_year=_payload_optional_constraint(payload.get("model_year"), "model_year"),
            battery_variant=_payload_optional_constraint(
                payload.get("battery_variant"), "battery_variant"
            ),
            drivetrain=_payload_optional_constraint(payload.get("drivetrain"), "drivetrain"),
            market=_payload_optional_constraint(payload.get("market"), "market"),
            test_protocol=_payload_optional_constraint(
                payload.get("test_protocol"), "test_protocol"
            ),
            charging_variant=_payload_optional_constraint(
                payload.get("charging_variant"), "charging_variant"
            ),
        )


@dataclass(frozen=True, slots=True)
class BusinessScope:
    """Facet-based business scope.

    ``document_type`` is intentionally routing-only metadata. It is serialized
    for analyzer selection and diagnostics, but is excluded from both scope
    comparison and the stable business-scope identity.
    """

    location: LocationScope = field(default_factory=LocationScope)
    product: ProductScope = field(default_factory=ProductScope)
    commercial: CommercialScope = field(default_factory=CommercialScope)
    vehicle: VehicleScope = field(default_factory=VehicleScope)
    entities: tuple[EntityRef, ...] = ()
    explicit_breadth: tuple[str, ...] = ()
    document_type: str | None = None

    def __post_init__(self) -> None:
        breadth = tuple(sorted({item.strip() for item in self.explicit_breadth if item.strip()}))
        object.__setattr__(self, "explicit_breadth", breadth)

    def stable_identity(self) -> tuple[tuple[str, tuple[str, ...]], ...]:
        facets = tuple(
            (name, _constraint_atoms(value))
            for name, value in _business_scope_items(self)
            if value is not None
        )
        entity_identity = tuple(
            (f"entity.{item.entity_type}", (item.canonical_id,))
            for item in sorted(
                self.entities, key=lambda item: (item.entity_type, item.canonical_id)
            )
        )
        breadth_identity = tuple(("explicit_breadth", (item,)) for item in self.explicit_breadth)
        return (*entity_identity, *facets, *breadth_identity)

    @property
    def scope_identity_hash(self) -> str:
        return _stable_hash(self.stable_identity())

    def to_payload(self) -> dict[str, object]:
        return {
            "location": self.location.to_payload(),
            "product": self.product.to_payload(),
            "commercial": self.commercial.to_payload(),
            "vehicle": self.vehicle.to_payload(),
            "entities": [item.to_payload() for item in self.entities],
            "explicit_breadth": list(self.explicit_breadth),
            "document_type": self.document_type,
            "scope_identity_hash": self.scope_identity_hash,
        }

    @classmethod
    def from_payload(cls, value: object) -> BusinessScope:
        payload = _require_mapping(value, field_name="scope")
        raw_entities = payload.get("entities", [])
        raw_breadth = payload.get("explicit_breadth", [])
        if not isinstance(raw_entities, list | tuple):
            raise ValueError("scope.entities must be a list")
        if not isinstance(raw_breadth, list | tuple) or not all(
            isinstance(item, str) for item in raw_breadth
        ):
            raise ValueError("scope.explicit_breadth must be a list of strings")
        return cls(
            location=LocationScope.from_payload(payload.get("location", {})),
            product=ProductScope.from_payload(payload.get("product", {})),
            commercial=CommercialScope.from_payload(payload.get("commercial", {})),
            vehicle=VehicleScope.from_payload(payload.get("vehicle", {})),
            entities=tuple(EntityRef.from_payload(item) for item in raw_entities),
            explicit_breadth=tuple(raw_breadth),
            document_type=_payload_optional_text(payload.get("document_type"), "document_type"),
        )


@dataclass(frozen=True, slots=True)
class ClaimQualifiers:
    """Normalized qualifiers split by candidate-identity significance.

    Stable qualifiers participate in the indexed candidate key. Optional
    qualifiers never change that key, but are still compared field-by-field
    before values may be declared conflicting.

    A tuple value means an explicit set of allowed alternatives, not an ordered
    list. This lets compatibility distinguish overlapping constraints from
    missing/unknown information.
    """

    stable: tuple[tuple[str, ConstraintValue], ...] = ()
    optional: tuple[tuple[str, ConstraintValue], ...] = ()

    def __post_init__(self) -> None:
        normalized_stable = _normalize_named_constraints(self.stable)
        normalized_optional = _normalize_named_constraints(self.optional)
        overlap = {key for key, _ in normalized_stable} & {key for key, _ in normalized_optional}
        if overlap:
            joined = ", ".join(sorted(overlap))
            raise ValueError(f"qualifier keys cannot be both stable and optional: {joined}")
        object.__setattr__(self, "stable", normalized_stable)
        object.__setattr__(self, "optional", normalized_optional)

    @classmethod
    def from_mappings(
        cls,
        *,
        stable: Mapping[str, ConstraintValue | None] | None = None,
        optional: Mapping[str, ConstraintValue | None] | None = None,
    ) -> ClaimQualifiers:
        return cls(
            stable=tuple(
                (key, value) for key, value in (stable or {}).items() if value is not None
            ),
            optional=tuple(
                (key, value) for key, value in (optional or {}).items() if value is not None
            ),
        )

    def stable_identity(self) -> tuple[tuple[str, tuple[str, ...]], ...]:
        return tuple((key, _constraint_atoms(value)) for key, value in self.stable)

    @property
    def stable_identity_hash(self) -> str:
        return _stable_hash(self.stable_identity())

    def to_payload(self) -> dict[str, object]:
        return {
            "stable": {key: _constraint_payload(value) for key, value in self.stable},
            "optional": {key: _constraint_payload(value) for key, value in self.optional},
            "stable_identity_hash": self.stable_identity_hash,
        }

    @classmethod
    def from_payload(cls, value: object) -> ClaimQualifiers:
        payload = _require_mapping(value, field_name="qualifiers")
        stable = _payload_constraint_mapping(payload.get("stable", {}), "qualifiers.stable")
        optional = _payload_constraint_mapping(payload.get("optional", {}), "qualifiers.optional")
        return cls.from_mappings(stable=stable, optional=optional)


@dataclass(frozen=True, slots=True)
class TemporalContext:
    """Distinct source, validity, observation, and ingestion timestamps."""

    publication_time: TemporalPoint | None = None
    effective_from: TemporalPoint | None = None
    effective_to: TemporalPoint | None = None
    observed_at: TemporalPoint | None = None
    ingested_at: TemporalPoint | None = None
    reference_period: str | None = None
    claim_periods: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if (
            self.effective_from is not None
            and self.effective_to is not None
            and _temporal_sort_key(self.effective_from) > _temporal_sort_key(self.effective_to)
        ):
            raise ValueError("effective_from cannot be after effective_to")

    @property
    def has_effective_interval(self) -> bool:
        return self.effective_from is not None or self.effective_to is not None

    def to_payload(self) -> dict[str, object]:
        payload: dict[str, object] = {
            "publication_time": _temporal_payload(self.publication_time),
            "effective_from": _temporal_payload(self.effective_from),
            "effective_to": _temporal_payload(self.effective_to),
            "observed_at": _temporal_payload(self.observed_at),
            "ingested_at": _temporal_payload(self.ingested_at),
        }
        if self.reference_period is not None:
            payload["reference_period"] = self.reference_period
        if self.claim_periods:
            payload["claim_periods"] = list(self.claim_periods)
        return payload

    @classmethod
    def from_payload(cls, value: object) -> TemporalContext:
        payload = _require_mapping(value, field_name="temporal")
        raw_claim_periods = payload.get("claim_periods", [])
        if not isinstance(raw_claim_periods, list | tuple) or not all(
            isinstance(item, str) for item in raw_claim_periods
        ):
            raise ValueError("temporal.claim_periods must be a list of strings")
        return cls(
            publication_time=_payload_temporal(payload.get("publication_time"), "publication_time"),
            effective_from=_payload_temporal(payload.get("effective_from"), "effective_from"),
            effective_to=_payload_temporal(payload.get("effective_to"), "effective_to"),
            observed_at=_payload_temporal(payload.get("observed_at"), "observed_at"),
            ingested_at=_payload_temporal(payload.get("ingested_at"), "ingested_at"),
            reference_period=_payload_optional_text(
                payload.get("reference_period"), "reference_period"
            ),
            claim_periods=tuple(raw_claim_periods),
        )


@dataclass(frozen=True, slots=True)
class NormalizedValue:
    """A normalized fact value while preserving its source representation."""

    value: ScalarValue
    unit: str | None = None
    currency: str | None = None
    basis: str | None = None
    raw_value: str | None = None

    def __post_init__(self) -> None:
        _validate_scalar(self.value)

    def stable_identity(self) -> tuple[object, ...]:
        return (
            _canonical_atom(self.value),
            _normalize_optional_text(self.unit),
            _normalize_optional_text(self.currency),
            _normalize_optional_text(self.basis),
        )

    def to_payload(self) -> dict[str, object]:
        return {
            "value": _scalar_payload(self.value),
            "value_type": _scalar_type(self.value),
            "unit": self.unit,
            "currency": self.currency,
            "basis": self.basis,
            "raw_value": self.raw_value,
        }

    @classmethod
    def from_payload(cls, value: object) -> NormalizedValue:
        payload = _require_mapping(value, field_name="value")
        if "value" not in payload:
            raise ValueError("value.value is required")
        return cls(
            value=_payload_typed_scalar(payload.get("value"), payload.get("value_type")),
            unit=_payload_optional_text(payload.get("unit"), "value.unit"),
            currency=_payload_optional_text(payload.get("currency"), "value.currency"),
            basis=_payload_optional_text(payload.get("basis"), "value.basis"),
            raw_value=_payload_optional_text(payload.get("raw_value"), "value.raw_value"),
        )


@dataclass(frozen=True, slots=True)
class ValueExpression:
    """Operator-aware value used by prose and table claims.

    ``NormalizedValue`` remains as a backwards-compatible persistence adapter.
    New comparison code consumes this contract so ranges and inequalities are
    never flattened into misleading scalar equality.
    """

    operator: ValueOperator
    value: ScalarValue | None = None
    lower: Decimal | None = None
    upper: Decimal | None = None
    unit: str | None = None
    currency: str | None = None
    basis: str | None = None
    raw_value: str | None = None
    confidence: float = 1.0

    def __post_init__(self) -> None:
        _validate_confidence(self.confidence, field_name="value expression confidence")
        if self.value is not None:
            _validate_scalar(self.value)
        for name, bound in (("lower", self.lower), ("upper", self.upper)):
            if bound is not None and not bound.is_finite():
                raise ValueError(f"{name} must be finite")
        if self.operator is ValueOperator.RANGE:
            if self.lower is None or self.upper is None:
                raise ValueError("range expressions require lower and upper bounds")
            if self.lower > self.upper:
                raise ValueError("range lower bound cannot exceed upper bound")
        elif self.operator in {
            ValueOperator.LT,
            ValueOperator.LTE,
            ValueOperator.GT,
            ValueOperator.GTE,
        }:
            if self.value is None:
                raise ValueError("inequality expressions require a scalar value")
        elif (
            self.operator not in {ValueOperator.UNKNOWN, ValueOperator.TEXT} and self.value is None
        ):
            raise ValueError(f"{self.operator.value} expressions require a value")
        if self.operator is ValueOperator.BOOLEAN and not isinstance(self.value, bool):
            raise ValueError("boolean expressions require a boolean value")

    @classmethod
    def from_normalized_value(cls, value: NormalizedValue) -> ValueExpression:
        if isinstance(value.value, bool):
            operator = ValueOperator.BOOLEAN
        elif isinstance(value.value, str) and not _is_decimal_text(value.value):
            operator = ValueOperator.TEXT
        else:
            operator = ValueOperator.EXACT
        return cls(
            operator=operator,
            value=value.value,
            unit=value.unit,
            currency=value.currency,
            basis=value.basis,
            raw_value=value.raw_value,
        )

    def to_normalized_value(self) -> NormalizedValue:
        """Return the legacy scalar adapter without discarding raw evidence."""
        if self.value is not None:
            scalar = self.value
        elif self.operator is ValueOperator.RANGE:
            lower = _decimal_text(self.lower or Decimal(0))
            upper = _decimal_text(self.upper or Decimal(0))
            scalar = f"{lower}..{upper}"
        else:
            scalar = self.raw_value or "unknown"
        return NormalizedValue(
            value=scalar,
            unit=self.unit,
            currency=self.currency,
            basis=self.basis,
            raw_value=self.raw_value,
        )

    def stable_identity(self) -> tuple[object, ...]:
        return (
            self.operator.value,
            _canonical_atom(self.value) if self.value is not None else None,
            _decimal_payload(self.lower),
            _decimal_payload(self.upper),
            _normalize_optional_text(self.unit),
            _normalize_optional_text(self.currency),
            _normalize_optional_text(self.basis),
        )

    def to_payload(self) -> dict[str, object]:
        return {
            "operator": self.operator.value,
            "value": _scalar_payload(self.value) if self.value is not None else None,
            "value_type": _scalar_type(self.value) if self.value is not None else None,
            "lower": _decimal_payload(self.lower),
            "upper": _decimal_payload(self.upper),
            "unit": self.unit,
            "currency": self.currency,
            "basis": self.basis,
            "raw_value": self.raw_value,
            "confidence": self.confidence,
        }

    @classmethod
    def from_payload(cls, value: object) -> ValueExpression:
        payload = _require_mapping(value, field_name="value_expression")
        raw_value = payload.get("value")
        return cls(
            operator=ValueOperator(
                _payload_required_text(payload.get("operator"), "value_expression.operator")
            ),
            value=(
                _payload_typed_scalar(raw_value, payload.get("value_type"))
                if raw_value is not None
                else None
            ),
            lower=_payload_optional_decimal(payload.get("lower"), "value_expression.lower"),
            upper=_payload_optional_decimal(payload.get("upper"), "value_expression.upper"),
            unit=_payload_optional_text(payload.get("unit"), "value_expression.unit"),
            currency=_payload_optional_text(payload.get("currency"), "value_expression.currency"),
            basis=_payload_optional_text(payload.get("basis"), "value_expression.basis"),
            raw_value=_payload_optional_text(
                payload.get("raw_value"), "value_expression.raw_value"
            ),
            confidence=_payload_required_float(
                payload.get("confidence", 1.0), "value_expression.confidence"
            ),
        )


@dataclass(frozen=True, slots=True)
class ClaimProvenance:
    """Cell-level lineage back to the original extracted artifact."""

    document_id: str
    table_id: str | None = None
    row_index: int | None = None
    data_row_ordinal: int | None = None
    column_name: str | None = None
    cell_id: str | None = None
    page_number: int | None = None
    source_span: tuple[int, int] | None = None
    sheet_name: str | None = None
    block_id: str | None = None
    chunk_id: str | None = None

    def __post_init__(self) -> None:
        if not self.document_id.strip():
            raise ValueError("provenance document_id cannot be blank")
        if self.row_index is not None and self.row_index < 0:
            raise ValueError("row_index cannot be negative")
        if self.data_row_ordinal is not None and self.data_row_ordinal < 0:
            raise ValueError("data_row_ordinal cannot be negative")
        if self.page_number is not None and self.page_number < 1:
            raise ValueError("page_number must be positive")
        if self.source_span is not None:
            start, end = self.source_span
            if start < 0 or end < start:
                raise ValueError("source_span must be an ordered non-negative range")

    def to_payload(self) -> dict[str, object]:
        return {
            "document_id": self.document_id,
            "table_id": self.table_id,
            "row_index": self.row_index,
            "data_row_ordinal": self.data_row_ordinal,
            "column_name": self.column_name,
            "cell_id": self.cell_id,
            "page_number": self.page_number,
            "source_span": (
                {"start": self.source_span[0], "end": self.source_span[1]}
                if self.source_span is not None
                else None
            ),
            "sheet_name": self.sheet_name,
            "block_id": self.block_id,
            "chunk_id": self.chunk_id,
        }

    @classmethod
    def from_payload(cls, value: object) -> ClaimProvenance:
        payload = _require_mapping(value, field_name="provenance")
        return cls(
            document_id=_payload_required_text(
                payload.get("document_id"), "provenance.document_id"
            ),
            table_id=_payload_optional_text(payload.get("table_id"), "provenance.table_id"),
            row_index=_payload_optional_int(payload.get("row_index"), "provenance.row_index"),
            data_row_ordinal=_payload_optional_int(
                payload.get("data_row_ordinal"), "provenance.data_row_ordinal"
            ),
            column_name=_payload_optional_text(
                payload.get("column_name"), "provenance.column_name"
            ),
            cell_id=_payload_optional_text(payload.get("cell_id"), "provenance.cell_id"),
            page_number=_payload_optional_int(payload.get("page_number"), "provenance.page_number"),
            source_span=_payload_source_span(payload.get("source_span")),
            sheet_name=_payload_optional_text(payload.get("sheet_name"), "provenance.sheet_name"),
            block_id=_payload_optional_text(payload.get("block_id"), "provenance.block_id"),
            chunk_id=_payload_optional_text(payload.get("chunk_id"), "provenance.chunk_id"),
        )


@dataclass(frozen=True, slots=True)
class ClaimDerivation:
    """Auditable computation metadata for a value derived from other claims."""

    formula: str
    input_claim_ids: tuple[str, ...] = ()
    absolute_tolerance: Decimal | None = None
    relative_tolerance: Decimal | None = None

    def __post_init__(self) -> None:
        if not self.formula.strip():
            raise ValueError("derivation formula cannot be blank")
        if self.absolute_tolerance is not None and self.absolute_tolerance < 0:
            raise ValueError("absolute_tolerance cannot be negative")
        if self.relative_tolerance is not None and self.relative_tolerance < 0:
            raise ValueError("relative_tolerance cannot be negative")

    def to_payload(self) -> dict[str, object]:
        return {
            "formula": self.formula,
            "input_claim_ids": list(self.input_claim_ids),
            "absolute_tolerance": _decimal_payload(self.absolute_tolerance),
            "relative_tolerance": _decimal_payload(self.relative_tolerance),
        }

    @classmethod
    def from_payload(cls, value: object) -> ClaimDerivation:
        payload = _require_mapping(value, field_name="derivation")
        raw_inputs = payload.get("input_claim_ids", [])
        if not isinstance(raw_inputs, list | tuple):
            raise ValueError("derivation.input_claim_ids must be a list")
        input_claim_ids = tuple(
            _payload_required_text(item, "derivation.input_claim_ids") for item in raw_inputs
        )
        return cls(
            formula=_payload_required_text(payload.get("formula"), "derivation.formula"),
            input_claim_ids=input_claim_ids,
            absolute_tolerance=_payload_optional_decimal(
                payload.get("absolute_tolerance"), "derivation.absolute_tolerance"
            ),
            relative_tolerance=_payload_optional_decimal(
                payload.get("relative_tolerance"), "derivation.relative_tolerance"
            ),
        )


@dataclass(frozen=True, slots=True)
class SourceAuthority:
    """Source-ranking evidence applied only after claims are comparable.

    Authority is deliberately descriptive rather than a hard-coded winner
    policy. A repository can retain publisher-specific metadata while ranking
    remains configurable at query/review time.
    """

    source_type: str | None = None
    publisher: str | None = None
    approval_status: str | None = None
    officiality: str | bool | None = None
    authority_level: int | None = None
    metadata: tuple[tuple[str, ScalarValue], ...] = ()

    def __post_init__(self) -> None:
        if self.authority_level is not None and not 0 <= self.authority_level <= 100:
            raise ValueError("authority_level must be between 0 and 100")
        normalized_metadata: dict[str, ScalarValue] = {}
        for raw_key, raw_value in self.metadata:
            key = _normalize_key(raw_key)
            if not key:
                raise ValueError("authority metadata key cannot be blank")
            if key in normalized_metadata:
                raise ValueError(f"duplicate authority metadata key: {key}")
            _validate_scalar(raw_value)
            normalized_metadata[key] = _normalized_scalar(raw_value)
        object.__setattr__(self, "metadata", tuple(sorted(normalized_metadata.items())))

    @classmethod
    def from_mapping(
        cls,
        *,
        source_type: str | None = None,
        publisher: str | None = None,
        approval_status: str | None = None,
        officiality: str | bool | None = None,
        authority_level: int | None = None,
        metadata: Mapping[str, ScalarValue | None] | None = None,
    ) -> SourceAuthority:
        return cls(
            source_type=source_type,
            publisher=publisher,
            approval_status=approval_status,
            officiality=officiality,
            authority_level=authority_level,
            metadata=tuple(
                (key, value) for key, value in (metadata or {}).items() if value is not None
            ),
        )

    def to_payload(self) -> dict[str, object]:
        return {
            "source_type": self.source_type,
            "publisher": self.publisher,
            "approval_status": self.approval_status,
            "officiality": self.officiality,
            "authority_level": self.authority_level,
            "metadata": {key: _scalar_payload(value) for key, value in self.metadata},
        }

    @classmethod
    def from_payload(cls, value: object) -> SourceAuthority:
        payload = _require_mapping(value, field_name="authority")
        raw_officiality = payload.get("officiality")
        if raw_officiality is not None and not isinstance(raw_officiality, str | bool):
            raise ValueError("authority.officiality must be text, boolean, or null")
        raw_metadata = _require_mapping(
            payload.get("metadata", {}), field_name="authority.metadata"
        )
        metadata: dict[str, ScalarValue | None] = {}
        for raw_key, raw_value in raw_metadata.items():
            if not isinstance(raw_key, str):
                raise ValueError("authority.metadata keys must be text")
            metadata[raw_key] = _payload_scalar(raw_value, f"authority.metadata.{raw_key}")
        return cls.from_mapping(
            source_type=_payload_optional_text(payload.get("source_type"), "authority.source_type"),
            publisher=_payload_optional_text(payload.get("publisher"), "authority.publisher"),
            approval_status=_payload_optional_text(
                payload.get("approval_status"), "authority.approval_status"
            ),
            officiality=raw_officiality,
            authority_level=_payload_optional_int(
                payload.get("authority_level"), "authority.authority_level"
            ),
            metadata=metadata,
        )


@dataclass(frozen=True, slots=True, kw_only=True)
class StructuredClaim:
    """One comparable business fact with stable identity and full provenance."""

    document_id: str
    subject_key: str
    predicate: str
    value: NormalizedValue
    provenance: ClaimProvenance
    extractor_version: str
    id: str | None = None
    owner_id: str | None = None
    notebook_id: str | None = None
    scope: BusinessScope = field(default_factory=BusinessScope)
    qualifiers: ClaimQualifiers = field(default_factory=ClaimQualifiers)
    temporal: TemporalContext = field(default_factory=TemporalContext)
    extraction_confidence: float = 1.0
    derivation: ClaimDerivation | None = None
    authority: SourceAuthority = field(default_factory=SourceAuthority)
    value_expression: ValueExpression | None = None
    evidence: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        for field_name, value in (
            ("document_id", self.document_id),
            ("subject_key", self.subject_key),
            ("predicate", self.predicate),
            ("extractor_version", self.extractor_version),
        ):
            if not value.strip():
                raise ValueError(f"{field_name} cannot be blank")
        if self.provenance.document_id != self.document_id:
            raise ValueError("claim and provenance document_id must match")
        _validate_confidence(self.extraction_confidence, field_name="extraction_confidence")
        if self.value_expression is None:
            object.__setattr__(
                self,
                "value_expression",
                ValueExpression.from_normalized_value(self.value),
            )
        object.__setattr__(
            self,
            "evidence",
            tuple(dict.fromkeys(item.strip() for item in self.evidence if item.strip())),
        )

    def candidate_identity(self) -> tuple[object, ...]:
        """Value-free identity used for cross-document claim lookup."""
        return (
            CLAIM_COMPARABLE_KEY_VERSION,
            _normalize_text(self.subject_key),
            _normalize_text(self.predicate),
            self.scope.stable_identity(),
            self.qualifiers.stable_identity(),
            _claim_temporal_identity(self.temporal),
        )

    @property
    def candidate_identity_hash(self) -> str:
        return _stable_hash(self.candidate_identity())

    @property
    def claim_identity_hash(self) -> str:
        """Idempotency fingerprint for one extracted claim occurrence."""
        expression = self.value_expression
        if expression is None:  # pragma: no cover - guaranteed by __post_init__
            raise RuntimeError("StructuredClaim value expression invariant was violated")
        return _stable_hash(
            {
                "document_id": self.document_id,
                "candidate_identity_hash": self.candidate_identity_hash,
                "value_expression": expression.stable_identity(),
                "scope_identity_hash": self.scope.scope_identity_hash,
                "qualifiers": self.qualifiers.to_payload(),
                "temporal": self.temporal.to_payload(),
                "provenance": self.provenance.to_payload(),
                "derivation": self.derivation.to_payload() if self.derivation else None,
                "extractor_version": self.extractor_version,
            }
        )

    def to_payload(self) -> dict[str, object]:
        expression = self.value_expression
        if expression is None:  # pragma: no cover - guaranteed by __post_init__
            raise RuntimeError("StructuredClaim value expression invariant was violated")
        return {
            "id": self.id,
            "owner_id": self.owner_id,
            "notebook_id": self.notebook_id,
            "document_id": self.document_id,
            "subject_key": self.subject_key,
            "predicate": self.predicate,
            "value": self.value.to_payload(),
            "value_expression": expression.to_payload(),
            "scope": self.scope.to_payload(),
            "qualifiers": self.qualifiers.to_payload(),
            "temporal": self.temporal.to_payload(),
            "provenance": self.provenance.to_payload(),
            "extraction_confidence": self.extraction_confidence,
            "extractor_version": self.extractor_version,
            "derivation": self.derivation.to_payload() if self.derivation else None,
            "authority": self.authority.to_payload(),
            "evidence": list(self.evidence),
            "candidate_identity_hash": self.candidate_identity_hash,
            "claim_identity_hash": self.claim_identity_hash,
        }

    @classmethod
    def from_payload(cls, value: object) -> StructuredClaim:
        """Rehydrate a persisted claim while rejecting incomplete evidence."""
        payload = _require_mapping(value, field_name="claim")
        derivation_payload = payload.get("derivation")
        if isinstance(derivation_payload, Mapping) and not derivation_payload:
            # Migration 16 stores the non-derived representation as an empty
            # JSON object. Treat that wire value as the domain-level ``None``.
            derivation_payload = None
        scope_payload = payload.get("scope")
        qualifiers_payload = payload.get("qualifiers")
        temporal_payload = payload.get("temporal")
        authority_payload = payload.get("authority")
        expression_payload = payload.get("value_expression")
        provenance_payload = payload.get("provenance")
        if isinstance(provenance_payload, Mapping):
            persisted_temporal = provenance_payload.get("claim_temporal")
            if isinstance(persisted_temporal, Mapping):
                temporal_payload = persisted_temporal
            persisted_expression = payload.get("value")
            if (
                expression_payload is None
                and isinstance(persisted_expression, Mapping)
                and persisted_expression.get("operator") is not None
            ):
                expression_payload = persisted_expression
        raw_evidence = payload.get("evidence", [])
        if not isinstance(raw_evidence, list | tuple) or not all(
            isinstance(item, str) for item in raw_evidence
        ):
            raise ValueError("claim.evidence must be a list of strings")
        persisted_evidence = (
            provenance_payload.get("claim_evidence", [])
            if isinstance(provenance_payload, Mapping)
            else []
        )
        if not isinstance(persisted_evidence, list | tuple) or not all(
            isinstance(item, str) for item in persisted_evidence
        ):
            raise ValueError("claim provenance claim_evidence must be a list of strings")
        persisted_extractor = (
            provenance_payload.get("claim_extractor_version")
            if isinstance(provenance_payload, Mapping)
            else None
        )
        return cls(
            id=_payload_optional_text(payload.get("id"), "claim.id"),
            owner_id=_payload_optional_text(payload.get("owner_id"), "claim.owner_id"),
            notebook_id=_payload_optional_text(payload.get("notebook_id"), "claim.notebook_id"),
            document_id=_payload_required_text(payload.get("document_id"), "claim.document_id"),
            subject_key=_payload_required_text(payload.get("subject_key"), "claim.subject_key"),
            predicate=_payload_required_text(payload.get("predicate"), "claim.predicate"),
            value=NormalizedValue.from_payload(payload.get("value")),
            scope=(
                BusinessScope.from_payload(scope_payload)
                if scope_payload is not None
                else BusinessScope()
            ),
            qualifiers=(
                ClaimQualifiers.from_payload(qualifiers_payload)
                if qualifiers_payload is not None
                else ClaimQualifiers()
            ),
            temporal=(
                TemporalContext.from_payload(temporal_payload)
                if temporal_payload is not None
                else TemporalContext()
            ),
            provenance=ClaimProvenance.from_payload(payload.get("provenance")),
            extraction_confidence=_payload_required_float(
                payload.get("extraction_confidence"), "claim.extraction_confidence"
            ),
            extractor_version=_payload_required_text(
                persisted_extractor or payload.get("extractor_version"),
                "claim.extractor_version",
            ),
            derivation=(
                ClaimDerivation.from_payload(derivation_payload)
                if derivation_payload is not None
                else None
            ),
            authority=(
                SourceAuthority.from_payload(authority_payload)
                if authority_payload is not None
                else SourceAuthority()
            ),
            value_expression=(
                ValueExpression.from_payload(expression_payload)
                if expression_payload is not None
                else None
            ),
            evidence=tuple((*raw_evidence, *persisted_evidence)),
        )


@dataclass(frozen=True, slots=True, kw_only=True)
class ClaimRelation:
    """One explainable comparison result between structured claims."""

    relation_type: ClaimRelationType
    source_claim_id: str | None
    target_claim_id: str | None
    subject_key: str
    predicate: str
    confidence: float
    reason_codes: tuple[str, ...] = ()
    scope_relation: ScopeRelation | None = None
    qualifier_compatibility: QualifierCompatibility | None = None
    temporal_relation: TemporalRelation | None = None

    def __post_init__(self) -> None:
        _validate_confidence(self.confidence, field_name="confidence")

    def to_payload(self) -> dict[str, object]:
        return {
            "relation_type": self.relation_type.value,
            "source_claim_id": self.source_claim_id,
            "target_claim_id": self.target_claim_id,
            "subject_key": self.subject_key,
            "predicate": self.predicate,
            "confidence": self.confidence,
            "reason_codes": list(self.reason_codes),
            "scope_relation": self.scope_relation.value if self.scope_relation else None,
            "qualifier_compatibility": (
                self.qualifier_compatibility.value if self.qualifier_compatibility else None
            ),
            "temporal_relation": self.temporal_relation.value if self.temporal_relation else None,
        }


def _business_scope_items(scope: BusinessScope) -> tuple[tuple[str, ConstraintValue | None], ...]:
    return (
        ("location.developer", scope.location.developer),
        ("location.project", scope.location.project),
        ("location.phase", scope.location.phase),
        ("location.subdivision", scope.location.subdivision),
        ("location.building", scope.location.building),
        ("location.unit", scope.location.unit),
        ("product.property_type", scope.product.property_type),
        ("product.bedrooms", scope.product.bedrooms),
        ("product.area_type", scope.product.area_type),
        ("product.product_variant", scope.product.product_variant),
        ("commercial.price_type", scope.commercial.price_type),
        ("commercial.price_basis", scope.commercial.price_basis),
        ("commercial.payment_plan", scope.commercial.payment_plan),
        ("commercial.discount_program", scope.commercial.discount_program),
        ("commercial.vat_included", scope.commercial.vat_included),
        ("commercial.maintenance_fee_included", scope.commercial.maintenance_fee_included),
        ("vehicle.manufacturer", scope.vehicle.manufacturer),
        ("vehicle.model", scope.vehicle.model),
        ("vehicle.trim", scope.vehicle.trim),
        ("vehicle.model_year", scope.vehicle.model_year),
        ("vehicle.battery_variant", scope.vehicle.battery_variant),
        ("vehicle.drivetrain", scope.vehicle.drivetrain),
        ("vehicle.market", scope.vehicle.market),
        ("vehicle.test_protocol", scope.vehicle.test_protocol),
        ("vehicle.charging_variant", scope.vehicle.charging_variant),
    )


def _claim_temporal_identity(temporal: TemporalContext) -> tuple[str, ...]:
    """Applicability identity; publication and ingestion times are provenance."""
    if temporal.claim_periods:
        return tuple(sorted({_normalize_text(value) for value in temporal.claim_periods}))
    if temporal.reference_period is not None:
        return (_normalize_text(temporal.reference_period),)
    return tuple(
        value
        for value in (
            _temporal_payload(temporal.effective_from),
            _temporal_payload(temporal.effective_to),
        )
        if value is not None
    )


def _normalize_named_constraints(
    values: tuple[tuple[str, ConstraintValue], ...],
) -> tuple[tuple[str, ConstraintValue], ...]:
    normalized: dict[str, ConstraintValue] = {}
    for raw_key, raw_value in values:
        key = _normalize_key(raw_key)
        if not key:
            raise ValueError("qualifier key cannot be blank")
        if key in normalized:
            raise ValueError(f"duplicate qualifier key: {key}")
        normalized[key] = _normalized_constraint(raw_value)
    return tuple(sorted(normalized.items()))


def _normalized_constraint(value: ConstraintValue) -> ConstraintValue:
    raw_values = value if isinstance(value, tuple) else (value,)
    if not raw_values:
        raise ValueError("constraint alternatives cannot be empty")
    normalized_by_key: dict[str, ScalarValue] = {}
    for item in raw_values:
        _validate_scalar(item)
        canonical = _canonical_atom(item)
        normalized_by_key[canonical] = _normalized_scalar(item)
    ordered = tuple(normalized_by_key[key] for key in sorted(normalized_by_key))
    return ordered[0] if len(ordered) == 1 else ordered


def _constraint_atoms(value: ConstraintValue) -> tuple[str, ...]:
    raw_values = value if isinstance(value, tuple) else (value,)
    return tuple(sorted({_canonical_atom(item) for item in raw_values}))


def _constraint_payload(value: ConstraintValue) -> object:
    raw_values = value if isinstance(value, tuple) else (value,)
    ordered = sorted(raw_values, key=_canonical_atom)
    serialized = [_scalar_payload(item) for item in ordered]
    return serialized[0] if len(serialized) == 1 else serialized


def _dataclass_constraints_payload(value: object) -> dict[str, object]:
    result: dict[str, object] = {}
    for name in value.__dataclass_fields__:  # type: ignore[attr-defined]
        constraint = getattr(value, name)
        result[name] = _constraint_payload(constraint) if constraint is not None else None
    return result


def _require_mapping(value: object, *, field_name: str) -> dict[str, object]:
    if not isinstance(value, Mapping):
        raise ValueError(f"{field_name} must be an object")
    result: dict[str, object] = {}
    for raw_key, raw_value in value.items():
        if not isinstance(raw_key, str):
            raise ValueError(f"{field_name} keys must be text")
        result[raw_key] = raw_value
    return result


def _payload_constraint_mapping(
    value: object,
    field_name: str,
) -> dict[str, ConstraintValue | None]:
    payload = _require_mapping(value, field_name=field_name)
    return {
        key: _payload_optional_constraint(raw_value, f"{field_name}.{key}")
        for key, raw_value in payload.items()
    }


def _payload_optional_constraint(value: object, field_name: str) -> ConstraintValue | None:
    if value is None:
        return None
    if isinstance(value, list | tuple):
        if not value:
            raise ValueError(f"{field_name} alternatives cannot be empty")
        return tuple(_payload_scalar(item, field_name) for item in value)
    return _payload_scalar(value, field_name)


def _payload_scalar(value: object, field_name: str) -> ScalarValue:
    if isinstance(value, str | int | float | bool | Decimal | date | datetime):
        _validate_scalar(value)
        return value
    raise ValueError(f"{field_name} must be a scalar value")


def _payload_typed_scalar(value: object, value_type: object) -> ScalarValue:
    if value_type is None:
        return _payload_scalar(value, "value.value")
    kind = _payload_required_text(value_type, "value.value_type")
    try:
        if kind == "decimal":
            if isinstance(value, bool) or not isinstance(value, str | int | float | Decimal):
                raise ValueError
            return Decimal(str(value))
        if kind == "date":
            if not isinstance(value, str):
                raise ValueError
            return date.fromisoformat(value)
        if kind == "datetime":
            if not isinstance(value, str):
                raise ValueError
            return datetime.fromisoformat(value)
        if kind == "bool":
            if not isinstance(value, bool):
                raise ValueError
            return value
        if kind == "int":
            if isinstance(value, bool) or not isinstance(value, int):
                raise ValueError
            return value
        if kind == "float":
            if isinstance(value, bool) or not isinstance(value, int | float):
                raise ValueError
            parsed_float = float(value)
            _validate_scalar(parsed_float)
            return parsed_float
        if kind == "text":
            if not isinstance(value, str):
                raise ValueError
            return value
    except (ArithmeticError, ValueError) as exc:
        raise ValueError(f"value.value is not a valid {kind}") from exc
    raise ValueError(f"unsupported value.value_type: {kind}")


def _payload_required_text(value: object, field_name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{field_name} must be non-blank text")
    return value.strip()


def _payload_optional_text(value: object, field_name: str) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str):
        raise ValueError(f"{field_name} must be text or null")
    return value.strip() or None


def _payload_optional_int(value: object, field_name: str) -> int | None:
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, int):
        raise ValueError(f"{field_name} must be an integer or null")
    return value


def _payload_required_float(value: object, field_name: str) -> float:
    if isinstance(value, bool) or not isinstance(value, int | float):
        raise ValueError(f"{field_name} must be numeric")
    parsed = float(value)
    if not math.isfinite(parsed):
        raise ValueError(f"{field_name} must be finite")
    return parsed


def _payload_optional_decimal(value: object, field_name: str) -> Decimal | None:
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, str | int | float | Decimal):
        raise ValueError(f"{field_name} must be numeric or null")
    try:
        parsed = Decimal(str(value))
    except ArithmeticError as exc:
        raise ValueError(f"{field_name} must be numeric or null") from exc
    if not parsed.is_finite():
        raise ValueError(f"{field_name} must be finite")
    return parsed


def _payload_source_span(value: object) -> tuple[int, int] | None:
    if value is None:
        return None
    if isinstance(value, Mapping):
        payload = _require_mapping(value, field_name="provenance.source_span")
        start = _payload_optional_int(payload.get("start"), "provenance.source_span.start")
        end = _payload_optional_int(payload.get("end"), "provenance.source_span.end")
    elif isinstance(value, list | tuple) and len(value) == 2:
        start = _payload_optional_int(value[0], "provenance.source_span.start")
        end = _payload_optional_int(value[1], "provenance.source_span.end")
    else:
        raise ValueError("provenance.source_span must be a start/end object")
    if start is None or end is None:
        raise ValueError("provenance.source_span requires start and end")
    return (start, end)


def _payload_temporal(value: object, field_name: str) -> TemporalPoint | None:
    if value is None:
        return None
    if isinstance(value, datetime | date):
        return value
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"temporal.{field_name} must be an ISO date/datetime or null")
    normalized = value.strip()
    try:
        if "T" in normalized or " " in normalized:
            return datetime.fromisoformat(normalized)
        return date.fromisoformat(normalized)
    except ValueError as exc:
        raise ValueError(f"temporal.{field_name} must be an ISO date/datetime or null") from exc


def _normalize_key(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", _normalize_text(value)).strip("_")


def _normalize_text(value: str) -> str:
    normalized = unicodedata.normalize("NFKC", value).casefold().strip()
    return " ".join(normalized.split())


def _normalize_optional_text(value: str | None) -> str | None:
    return _normalize_text(value) if value is not None else None


def _normalized_scalar(value: ScalarValue) -> ScalarValue:
    if isinstance(value, str):
        return _normalize_text(value)
    return value


def _canonical_atom(value: ScalarValue) -> str:
    _validate_scalar(value)
    if isinstance(value, bool):
        return f"bool:{str(value).lower()}"
    if isinstance(value, datetime):
        return f"datetime:{_temporal_sort_key(value).isoformat()}"
    if isinstance(value, date):
        return f"date:{value.isoformat()}"
    if isinstance(value, Decimal):
        return f"number:{_decimal_text(value)}"
    if isinstance(value, int):
        return f"number:{value}"
    if isinstance(value, float):
        return f"number:{_decimal_text(Decimal(str(value)))}"
    return f"text:{_normalize_text(value)}"


def _validate_scalar(value: ScalarValue) -> None:
    if isinstance(value, float) and not math.isfinite(value):
        raise ValueError("scalar floats must be finite")
    if isinstance(value, Decimal) and not value.is_finite():
        raise ValueError("scalar decimals must be finite")


def _scalar_payload(value: ScalarValue) -> object:
    if isinstance(value, Decimal):
        return _decimal_text(value)
    if isinstance(value, datetime | date):
        return value.isoformat()
    return value


def _scalar_type(value: ScalarValue) -> str:
    if isinstance(value, bool):
        return "bool"
    if isinstance(value, datetime):
        return "datetime"
    if isinstance(value, date):
        return "date"
    if isinstance(value, Decimal):
        return "decimal"
    if isinstance(value, int):
        return "int"
    if isinstance(value, float):
        return "float"
    return "text"


def _decimal_text(value: Decimal) -> str:
    if value == 0:
        return "0"
    return format(value.normalize(), "f")


def _is_decimal_text(value: str) -> bool:
    try:
        return Decimal(value).is_finite()
    except ArithmeticError:
        return False


def _decimal_payload(value: Decimal | None) -> str | None:
    return _decimal_text(value) if value is not None else None


def _temporal_payload(value: TemporalPoint | None) -> str | None:
    return value.isoformat() if value is not None else None


def _temporal_sort_key(value: TemporalPoint) -> datetime:
    if isinstance(value, datetime):
        if value.tzinfo is not None:
            return value.astimezone(UTC).replace(tzinfo=None)
        return value
    return datetime.combine(value, time.min)


def _stable_hash(value: object) -> str:
    canonical = json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        default=str,
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _validate_confidence(value: float, *, field_name: str) -> None:
    if not math.isfinite(value) or not 0.0 <= value <= 1.0:
        raise ValueError(f"{field_name} must be between 0 and 1")


__all__ = [
    "BusinessScope",
    "ClaimDerivation",
    "ClaimProvenance",
    "ClaimQualifiers",
    "ClaimRelation",
    "ClaimRelationType",
    "CommercialScope",
    "ConstraintValue",
    "EntityEvidence",
    "EntityEvidenceSource",
    "EntityMatchMethod",
    "EntityRef",
    "LocationScope",
    "NormalizedValue",
    "ProductScope",
    "QualifierCompatibility",
    "ScalarValue",
    "ScopeRelation",
    "SourceAuthority",
    "StructuredClaim",
    "TemporalContext",
    "TemporalPoint",
    "TemporalRelation",
    "ValueExpression",
    "ValueExpressionRelation",
    "ValueOperator",
    "VehicleScope",
]
