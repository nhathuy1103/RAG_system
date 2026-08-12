"""P2 domain-aware scope envelopes built on the canonical structured-facts model."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from dataclasses import dataclass
from enum import StrEnum

from app.structured_facts.domain.models import (
    BusinessScope,
    ClaimQualifiers,
    EntityEvidenceSource,
    EntityRef,
    QualifierCompatibility,
    ScopeRelation,
    TemporalContext,
    TemporalRelation,
)

ENTITY_SCOPE_METADATA_VERSION = "p2-entity-scope-metadata-v1"
BUSINESS_SCOPE_VERSION = "p2-business-scope-v1"
CONFLICT_ADMISSION_VERSION = "p2-conflict-admission-v1"


class ConflictAdmissionDisposition(StrEnum):
    ADMIT = "admit"
    DISTINCT_ENTITY = "distinct_entity"
    CONDITIONAL_VARIANT = "conditional_variant"
    TEMPORAL_VARIANT = "temporal_variant"
    UNCERTAIN = "uncertain"


@dataclass(frozen=True, slots=True)
class ScopeFacetEvidence:
    facet: str
    raw_text: str
    source: EntityEvidenceSource
    confidence: float
    span_start: int | None = None
    span_end: int | None = None
    source_id: str | None = None

    def to_payload(self) -> dict[str, object]:
        return {
            "facet": self.facet,
            "raw_text": self.raw_text,
            "source": self.source.value,
            "confidence": self.confidence,
            "span": (
                {"start": self.span_start, "end": self.span_end}
                if self.span_start is not None
                else None
            ),
            "source_id": self.source_id,
        }

    @classmethod
    def from_payload(cls, value: object) -> ScopeFacetEvidence:
        if not isinstance(value, Mapping):
            raise ValueError("scope facet evidence must be an object")
        span = value.get("span")
        start: int | None = None
        end: int | None = None
        if isinstance(span, Mapping):
            raw_start, raw_end = span.get("start"), span.get("end")
            if isinstance(raw_start, int) and isinstance(raw_end, int):
                start, end = raw_start, raw_end
        return cls(
            facet=str(value["facet"]),
            raw_text=str(value["raw_text"]),
            source=EntityEvidenceSource(str(value["source"])),
            confidence=float(value["confidence"]),
            span_start=start,
            span_end=end,
            source_id=(str(value["source_id"]) if value.get("source_id") is not None else None),
        )


@dataclass(frozen=True, slots=True)
class ClaimComparableKey:
    """Value-free identity for deciding whether claims may be compared."""

    entity_ids: tuple[str, ...]
    predicate: str
    business_scope_identity: tuple[tuple[str, tuple[str, ...]], ...]
    stable_qualifiers: tuple[tuple[str, tuple[str, ...]], ...]
    temporal_applicability: tuple[str, ...]

    @property
    def identity_hash(self) -> str:
        payload = json.dumps(
            {
                "entity_ids": self.entity_ids,
                "predicate": self.predicate,
                "business_scope_identity": self.business_scope_identity,
                "stable_qualifiers": self.stable_qualifiers,
                "temporal_applicability": self.temporal_applicability,
            },
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )
        return hashlib.sha256(payload.encode("utf-8")).hexdigest()


@dataclass(frozen=True, slots=True)
class ResolvedBusinessContext:
    entities: tuple[EntityRef, ...]
    business_scope: BusinessScope
    qualifiers: ClaimQualifiers
    temporal: TemporalContext
    predicate: str
    facet_evidence: tuple[ScopeFacetEvidence, ...] = ()
    ambiguous_entity_types: tuple[str, ...] = ()
    metadata_version: str = ENTITY_SCOPE_METADATA_VERSION
    business_scope_version: str = BUSINESS_SCOPE_VERSION

    @property
    def primary_entity(self) -> EntityRef | None:
        priority = {"project": 0, "vehicle_model": 0, "unit": 1, "building": 2}
        return min(
            self.entities,
            key=lambda item: (priority.get(item.entity_type, 10), item.canonical_id),
            default=None,
        )

    @property
    def comparable_key(self) -> ClaimComparableKey:
        temporal_identity = tuple(
            value
            for value in (
                self.temporal.effective_from.isoformat()
                if self.temporal.effective_from is not None
                else None,
                self.temporal.effective_to.isoformat()
                if self.temporal.effective_to is not None
                else None,
                self.temporal.reference_period,
                *self.temporal.claim_periods,
            )
            if value is not None
        )
        return ClaimComparableKey(
            entity_ids=tuple(sorted(item.canonical_id for item in self.entities)),
            predicate=self.predicate,
            business_scope_identity=self.business_scope.stable_identity(),
            stable_qualifiers=self.qualifiers.stable_identity(),
            temporal_applicability=temporal_identity,
        )

    def to_metadata(self) -> dict[str, object]:
        return {
            "version": self.metadata_version,
            "business_scope_version": self.business_scope_version,
            "entities": [item.to_payload() for item in self.entities],
            "business_scope": self.business_scope.to_payload(),
            "qualifiers": self.qualifiers.to_payload(),
            "temporal": self.temporal.to_payload(),
            "predicate": self.predicate,
            "facet_evidence": [item.to_payload() for item in self.facet_evidence],
            "ambiguous_entity_types": list(self.ambiguous_entity_types),
            "comparable_key_hash": self.comparable_key.identity_hash,
        }

    @classmethod
    def from_metadata(cls, value: object) -> ResolvedBusinessContext | None:
        if not isinstance(value, Mapping):
            return None
        if value.get("version") != ENTITY_SCOPE_METADATA_VERSION:
            return None
        raw_entities = value.get("entities", [])
        raw_evidence = value.get("facet_evidence", [])
        raw_ambiguous = value.get("ambiguous_entity_types", [])
        collection_values = (raw_entities, raw_evidence, raw_ambiguous)
        if not all(isinstance(item, list | tuple) for item in collection_values):
            return None
        try:
            return cls(
                entities=tuple(EntityRef.from_payload(item) for item in raw_entities),
                business_scope=BusinessScope.from_payload(value.get("business_scope", {})),
                qualifiers=ClaimQualifiers.from_payload(value.get("qualifiers", {})),
                temporal=TemporalContext.from_payload(value.get("temporal", {})),
                predicate=str(value.get("predicate") or "unknown"),
                facet_evidence=tuple(
                    ScopeFacetEvidence.from_payload(item) for item in raw_evidence
                ),
                ambiguous_entity_types=tuple(str(item) for item in raw_ambiguous),
                metadata_version=str(value["version"]),
                business_scope_version=str(
                    value.get("business_scope_version") or BUSINESS_SCOPE_VERSION
                ),
            )
        except (KeyError, TypeError, ValueError):
            return None


@dataclass(frozen=True, slots=True)
class ConflictAdmissionDecision:
    disposition: ConflictAdmissionDisposition
    allows_conflict_analysis: bool
    entity_compatible: bool | None
    scope_relation: ScopeRelation
    qualifier_compatibility: QualifierCompatibility
    temporal_relation: TemporalRelation
    reason_codes: tuple[str, ...]
    legacy_scope: str | None = None
    version: str = CONFLICT_ADMISSION_VERSION

    def to_payload(self) -> dict[str, object]:
        return {
            "version": self.version,
            "disposition": self.disposition.value,
            "allows_conflict_analysis": self.allows_conflict_analysis,
            "entity_compatible": self.entity_compatible,
            "scope_relation": self.scope_relation.value,
            "qualifier_compatibility": self.qualifier_compatibility.value,
            "temporal_relation": self.temporal_relation.value,
            "reason_codes": list(self.reason_codes),
            "legacy_scope": self.legacy_scope,
            "shadow_disagreement": (
                self.legacy_scope is not None
                and self.legacy_scope not in {self.scope_relation.value, self.disposition.value}
            ),
        }


__all__ = [
    "BUSINESS_SCOPE_VERSION",
    "CONFLICT_ADMISSION_VERSION",
    "ENTITY_SCOPE_METADATA_VERSION",
    "ClaimComparableKey",
    "ConflictAdmissionDecision",
    "ConflictAdmissionDisposition",
    "ResolvedBusinessContext",
    "ScopeFacetEvidence",
]
