"""Strict models shared by dataset generation, validation, and evaluation."""

from __future__ import annotations

from enum import StrEnum
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from evaluation.duplicate_conflict.constants import SCHEMA_VERSION


class Domain(StrEnum):
    VINHOMES = "vinhomes"
    VINFAST = "vinfast"


class GoldRelation(StrEnum):
    EXACT_DUPLICATE = "EXACT_DUPLICATE"
    NEAR_DUPLICATE = "NEAR_DUPLICATE"
    VERSION_UPDATE = "VERSION_UPDATE"
    TEMPORAL_VARIANT = "TEMPORAL_VARIANT"
    CONDITIONAL_VARIANT = "CONDITIONAL_VARIANT"
    TEMPLATE_VARIANT = "TEMPLATE_VARIANT"
    CONFLICT = "CONFLICT"
    DISTINCT = "DISTINCT"
    UNCERTAIN = "UNCERTAIN"


class SourceForm(StrEnum):
    PROSE = "prose"
    TABLE = "table"


class NoiseLevel(StrEnum):
    NONE = "none"
    LIGHT = "light"
    MEDIUM = "medium"
    SEVERE = "severe"


class ExtractionReliability(StrEnum):
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"


class Difficulty(StrEnum):
    EASY = "easy"
    MEDIUM = "medium"
    HARD = "hard"


class FailureCategory(StrEnum):
    CANDIDATE_MISS = "CANDIDATE_MISS"
    ENTITY_RESOLUTION_ERROR = "ENTITY_RESOLUTION_ERROR"
    SCOPE_ERROR = "SCOPE_ERROR"
    TEMPORAL_SCOPE_ERROR = "TEMPORAL_SCOPE_ERROR"
    CLAIM_EXTRACTION_ERROR = "CLAIM_EXTRACTION_ERROR"
    CLAIM_ALIGNMENT_ERROR = "CLAIM_ALIGNMENT_ERROR"
    VALUE_NORMALIZATION_ERROR = "VALUE_NORMALIZATION_ERROR"
    UNIT_NORMALIZATION_ERROR = "UNIT_NORMALIZATION_ERROR"
    OPERATOR_RANGE_ERROR = "OPERATOR_RANGE_ERROR"
    NEGATION_ERROR = "NEGATION_ERROR"
    TABLE_PROSE_GAP = "TABLE_PROSE_GAP"
    CROSS_CHUNK_CONTEXT_MISSING = "CROSS_CHUNK_CONTEXT_MISSING"
    OCR_EXTRACTION_ERROR = "OCR_EXTRACTION_ERROR"
    CLASSIFIER_THRESHOLD_ERROR = "CLASSIFIER_THRESHOLD_ERROR"
    DOCUMENT_AGGREGATION_ERROR = "DOCUMENT_AGGREGATION_ERROR"
    OTHER = "OTHER"


class TablePayload(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    headers: tuple[str, ...] = Field(min_length=1)
    rows: tuple[tuple[str, ...], ...] = Field(min_length=1)


class ExpectedClaimRelation(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    claim: str
    scope: dict[str, object] = Field(default_factory=dict)
    expected_relation: str
    conflict_field: str | None = None


class GoldPair(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: Literal["duplicate-conflict-gold-v1"] = SCHEMA_VERSION
    pair_id: str = Field(pattern=r"^(VH|VF)_[A-Z_]+_[0-9]{4}$")
    split: Literal["dev", "test"]
    domain: Domain
    category: str = Field(min_length=1)
    text_a: str = Field(min_length=1)
    text_b: str = Field(min_length=1)
    expected_relation: GoldRelation
    variation_type: str = Field(min_length=1)
    same_entity: bool
    same_business_scope: bool
    same_temporal_scope: bool
    same_claim: bool
    same_value: bool
    critical_conflict: bool
    entity_a: dict[str, object]
    entity_b: dict[str, object]
    scope_a: dict[str, object]
    scope_b: dict[str, object]
    expected_claims_a: tuple[dict[str, object], ...]
    expected_claims_b: tuple[dict[str, object], ...]
    expected_claim_relations: tuple[ExpectedClaimRelation, ...]
    conflict_fields: tuple[str, ...]
    source_form_a: SourceForm
    source_form_b: SourceForm
    table_a: TablePayload | None = None
    table_b: TablePayload | None = None
    context_a: tuple[str, ...] = ()
    context_b: tuple[str, ...] = ()
    ocr_noise_level_a: NoiseLevel = NoiseLevel.NONE
    ocr_noise_level_b: NoiseLevel = NoiseLevel.NONE
    extraction_reliability_a: ExtractionReliability = ExtractionReliability.HIGH
    extraction_reliability_b: ExtractionReliability = ExtractionReliability.HIGH
    difficulty: Difficulty
    is_synthetic: Literal[True] = True
    annotation_reason: str = Field(min_length=1)
    review_status: Literal["gold"] = "gold"
    diagnostic_hints: tuple[FailureCategory, ...] = ()
    source_documents: tuple[str, ...] = Field(min_length=1)
    candidate_retrieval_required: bool
    expected_auto_reuse: bool
    seed_index: int = Field(ge=0)
    distinct_justification: str | None = None
    temporal_overlap_justification: str | None = None


__all__ = [
    "Difficulty",
    "Domain",
    "ExpectedClaimRelation",
    "ExtractionReliability",
    "FailureCategory",
    "GoldPair",
    "GoldRelation",
    "NoiseLevel",
    "SourceForm",
    "TablePayload",
]
