"""Framework-independent knowledge-quality value objects."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import datetime
from enum import StrEnum
from uuid import UUID

LEGACY_DOCUMENT_NORMALIZATION_VERSION = "knowledge-identity-v1"
DOCUMENT_NORMALIZATION_VERSION = "knowledge-document-identity-v2"
CHUNK_NORMALIZATION_VERSION = "knowledge-chunk-identity-v1"
# Backwards-compatible import name for callers that mean document identity.
NORMALIZATION_VERSION = DOCUMENT_NORMALIZATION_VERSION
DETECTOR_VERSION = "knowledge-quality-v3"
CHUNK_PREEMBEDDING_DETECTOR_VERSION = "chunk-preembedding-v2"
CLAIM_COMPARISON_VERSION = "claim-comparison-v2"


class RelationType(StrEnum):
    EXACT_CONTENT = "exact_content"
    NEAR_DUPLICATE = "near_duplicate"
    VERSION_CANDIDATE = "version_candidate"
    VERSION = "version"
    CONFLICT_CANDIDATE = "conflict_candidate"
    CONFLICT = "conflict"
    RELATED = "related"
    DISTINCT = "distinct"
    TECHNICAL_DUPLICATE = "technical_duplicate"
    TEMPLATE_VARIANT = "template_variant"


class ScopeComparison(StrEnum):
    SAME_SCOPE = "same_scope"
    DIFFERENT_SCOPE = "different_scope"
    UNKNOWN_SCOPE = "unknown_scope"


class NumericRole(StrEnum):
    STRUCTURAL_REFERENCE = "structural_reference"
    SEMANTIC_QUANTITY = "semantic_quantity"
    IDENTIFIER = "identifier"
    UNKNOWN = "unknown"


class RelationStatus(StrEnum):
    PENDING = "pending"
    AUTO_CONFIRMED = "auto_confirmed"
    CONFIRMED = "confirmed"
    DISMISSED = "dismissed"


class ResolutionAction(StrEnum):
    CONFIRM_DUPLICATE = "confirm_duplicate"
    MARK_VERSION = "mark_version"
    CONFIRM_CONFLICT = "confirm_conflict"
    KEEP_SEPARATE = "keep_separate"
    PREFER_SOURCE = "prefer_source"
    PREFER_TARGET = "prefer_target"
    DISMISS = "dismiss"


class PolicyModality(StrEnum):
    """Normalized force of one policy claim."""

    REQUIRED = "required"
    PERMITTED = "permitted"
    PROHIBITED = "prohibited"


@dataclass(frozen=True, slots=True)
class ClaimScope:
    """Logical document and entity scope used to gate conflict validation."""

    document_id: str | None = None
    canonical_document_id: str | None = None
    project_id: str | None = None
    contract_id: str | None = None
    document_type: str | None = None
    contract_type: str | None = None
    subject_entities: tuple[str, ...] = ()
    effective_date: str | None = None
    version_id: str | None = None

    def to_metadata(self) -> dict[str, object]:
        return {
            "document_id": self.document_id,
            "canonical_document_id": self.canonical_document_id,
            "project_id": self.project_id,
            "contract_id": self.contract_id,
            "document_type": self.document_type,
            "contract_type": self.contract_type,
            "subject_entities": list(self.subject_entities),
            "effective_date": self.effective_date,
            "version_id": self.version_id,
        }

    @classmethod
    def from_metadata(cls, value: object) -> ClaimScope | None:
        if not isinstance(value, Mapping):
            return None

        def optional_text(key: str) -> str | None:
            raw = value.get(key)
            if raw is None:
                return None
            normalized = str(raw).strip()
            return normalized or None

        raw_entities = value.get("subject_entities")
        entities = (
            tuple(str(item).strip() for item in raw_entities if str(item).strip())
            if isinstance(raw_entities, list | tuple)
            else ()
        )
        return cls(
            document_id=optional_text("document_id"),
            canonical_document_id=optional_text("canonical_document_id"),
            project_id=optional_text("project_id"),
            contract_id=optional_text("contract_id"),
            document_type=optional_text("document_type"),
            contract_type=optional_text("contract_type"),
            subject_entities=entities,
            effective_date=optional_text("effective_date"),
            version_id=optional_text("version_id"),
        )


@dataclass(frozen=True, slots=True)
class ClaimKey:
    """Conservative structured key for deciding whether claims are comparable."""

    subject: str | None
    predicate: str | None
    attribute: str | None
    object_type: str | None
    unit_family: str | None
    scope_qualifiers: tuple[str, ...] = ()

    def canonical_evidence_key(self) -> tuple[str, ...]:
        return tuple(
            value or ""
            for value in (
                self.subject,
                self.predicate,
                self.attribute,
                self.object_type,
                self.unit_family,
                *self.scope_qualifiers,
            )
        )


@dataclass(frozen=True, slots=True)
class NumericMention:
    """One classified numeric mention with explainable source context."""

    raw_text: str
    normalized_value: str
    unit: str | None
    role: NumericRole
    span_start: int
    span_end: int
    context: str
    reference_type: str | None = None


@dataclass(frozen=True, slots=True)
class ClaimValue:
    """One normalized value with an absolute source span."""

    kind: str
    raw_text: str
    normalized_value: str
    unit: str | None
    magnitude: str | None
    span_start: int
    span_end: int
    role: NumericRole = NumericRole.SEMANTIC_QUANTITY
    reference_type: str | None = None

    def to_signal(self) -> dict[str, object]:
        return {
            "kind": self.kind,
            "raw_text": self.raw_text,
            "normalized_value": self.normalized_value,
            "unit": self.unit,
            "magnitude": self.magnitude,
            "span": {"start": self.span_start, "end": self.span_end},
            "role": self.role.value,
            "reference_type": self.reference_type,
        }


@dataclass(frozen=True, slots=True)
class ExtractedClaim:
    """Deterministic sentence/clause claim used for conservative alignment."""

    text: str
    alignment_key: str
    span_start: int
    span_end: int
    modality: PolicyModality | None
    negated: bool
    values: tuple[ClaimValue, ...] = ()
    claim_key: ClaimKey | None = None
    comparison_text: str = ""

    def to_signal(self) -> dict[str, object]:
        return {
            "text": self.text,
            "alignment_key": self.alignment_key,
            "span": {"start": self.span_start, "end": self.span_end},
            "modality": self.modality.value if self.modality is not None else None,
            "negated": self.negated,
            "values": [value.to_signal() for value in self.values],
            "claim_key": (
                {
                    "subject": self.claim_key.subject,
                    "predicate": self.claim_key.predicate,
                    "attribute": self.claim_key.attribute,
                    "object_type": self.claim_key.object_type,
                    "unit_family": self.claim_key.unit_family,
                    "scope_qualifiers": list(self.claim_key.scope_qualifiers),
                }
                if self.claim_key is not None
                else None
            ),
            "comparison_text": self.comparison_text,
        }


@dataclass(frozen=True, slots=True)
class ClaimConflict:
    """Explainable differences between two aligned claim spans."""

    left_claim: ExtractedClaim
    right_claim: ExtractedClaim
    alignment_score: float
    reason_codes: tuple[str, ...]

    def to_signal(self) -> dict[str, object]:
        return {
            "alignment_score": round(self.alignment_score, 6),
            "reason_codes": list(self.reason_codes),
            "left": self.left_claim.to_signal(),
            "right": self.right_claim.to_signal(),
        }


@dataclass(frozen=True, slots=True)
class DocumentFingerprint:
    """Strict identity plus a fuzzy, non-authoritative candidate signature."""

    strict_hash: str
    loose_signature: str
    normalization_version: str
    character_count: int
    token_count: int
    numbers: tuple[str, ...] = ()
    dates: tuple[str, ...] = ()
    has_negation: bool = False
    identity_trusted: bool = True
    projection_source: str = "plain_text"
    table_count: int = 0
    fallback_used: bool = False
    unrepresented_visual_count: int = 0
    replacement_character_count: int = 0
    template_structure_signature: str | None = None
    template_structure_version: str | None = None

    def to_metadata(self) -> dict[str, object]:
        return {
            "normalization_version": self.normalization_version,
            "character_count": self.character_count,
            "token_count": self.token_count,
            "numbers": list(self.numbers),
            "dates": list(self.dates),
            "has_negation": self.has_negation,
            "identity_trusted": self.identity_trusted,
            "projection_source": self.projection_source,
            "table_count": self.table_count,
            "fallback_used": self.fallback_used,
            "unrepresented_visual_count": self.unrepresented_visual_count,
            "replacement_character_count": self.replacement_character_count,
            "template_structure_signature": self.template_structure_signature,
            "template_structure_version": self.template_structure_version,
        }


@dataclass(frozen=True, slots=True)
class TextRelationAnalysis:
    relation_type: RelationType
    confidence: float
    lexical_similarity: float
    containment: float
    semantic_similarity: float | None
    number_agreement: bool
    date_agreement: bool
    negation_mismatch: bool
    reason_codes: tuple[str, ...] = ()
    unit_agreement: bool = True
    policy_modality_mismatch: bool = False
    claim_conflicts: tuple[ClaimConflict, ...] = ()
    scope_comparison: ScopeComparison = ScopeComparison.UNKNOWN_SCOPE
    template_similarity: float = 0.0
    validated_conflict_count: int = 0
    confidence_components: dict[str, float] = field(default_factory=dict)
    exact_line_overlap_count: int = 0
    exact_line_overlap_ratio: float = 0.0
    structural_numbers_ignored: int = 0

    def to_signals(self) -> dict[str, object]:
        return {
            "lexical_similarity": round(self.lexical_similarity, 6),
            "containment": round(self.containment, 6),
            "semantic_similarity": (
                round(self.semantic_similarity, 6) if self.semantic_similarity is not None else None
            ),
            "number_agreement": self.number_agreement,
            "date_agreement": self.date_agreement,
            "negation_mismatch": self.negation_mismatch,
            "reason_codes": list(self.reason_codes),
            "unit_agreement": self.unit_agreement,
            "policy_modality_mismatch": self.policy_modality_mismatch,
            "claim_conflicts": [conflict.to_signal() for conflict in self.claim_conflicts],
            "scope_comparison": self.scope_comparison.value,
            "template_similarity": round(self.template_similarity, 6),
            "validated_conflict_count": self.validated_conflict_count,
            "confidence_components": {
                key: round(value, 6) for key, value in self.confidence_components.items()
            },
            "exact_line_overlap_count": self.exact_line_overlap_count,
            "exact_line_overlap_ratio": round(self.exact_line_overlap_ratio, 6),
            "structural_numbers_ignored": self.structural_numbers_ignored,
        }


@dataclass(frozen=True, slots=True)
class ChunkDedupProbe:
    """One chunk fingerprint submitted to pre-embedding candidate lookup."""

    chunk_index: int
    chunk_id: str
    canonical_text: str
    embedding_text_checksum: str
    fingerprint: DocumentFingerprint
    include_fuzzy_candidates: bool = False
    scope: ClaimScope | None = None

    def to_payload(self) -> dict[str, object]:
        return {
            "chunk_index": self.chunk_index,
            "normalized_content_hash": self.fingerprint.strict_hash,
            "normalization_version": self.fingerprint.normalization_version,
            "loose_content_signature": self.fingerprint.loose_signature,
            "include_fuzzy": self.include_fuzzy_candidates,
        }


@dataclass(frozen=True, slots=True)
class ChunkDedupCandidate:
    """A scoped persisted chunk that may match one pre-embedding probe."""

    source_chunk_index: int
    target_chunk_id: str
    target_document_id: UUID
    target_chunk_index: int
    canonical_text: str
    normalized_content_hash: str
    normalization_version: str
    loose_content_signature: str
    embedding_text_checksum: str | None
    embedding: tuple[float, ...]
    embedding_model: str
    lsh_band_matches: int = 0
    scope: ClaimScope | None = None


@dataclass(frozen=True, slots=True)
class QualityRelationCandidate:
    target_document_id: UUID
    relation_type: RelationType
    confidence: float
    signals: dict[str, object] = field(default_factory=dict)
    reason: str | None = None
    detector_version: str = DETECTOR_VERSION

    def to_payload(self) -> dict[str, object]:
        return {
            "target_document_id": str(self.target_document_id),
            "relation_type": self.relation_type.value,
            "confidence": self.confidence,
            "signals": self.signals,
            "reason": self.reason,
            "detector_version": self.detector_version,
        }


@dataclass(frozen=True, slots=True)
class DocumentRelation:
    id: UUID
    owner_id: UUID
    notebook_id: UUID
    source_document_id: UUID
    target_document_id: UUID
    relation_type: RelationType
    status: RelationStatus
    confidence: float
    signals: dict[str, object]
    reason: str | None
    detector_version: str
    preferred_document_id: UUID | None
    resolved_by: UUID | None
    resolved_at: datetime | None
    created_at: datetime
    updated_at: datetime


@dataclass(frozen=True, slots=True)
class KnowledgeQualityAudit:
    """One immutable, user-visible quality decision or reversal."""

    id: int
    owner_id: UUID
    notebook_id: UUID
    relation_id: UUID | None
    actor_id: UUID | None
    action: str
    reason: str | None
    before_state: dict[str, object]
    after_state: dict[str, object]
    created_at: datetime


@dataclass(frozen=True, slots=True)
class RelationEvidenceDocument:
    """Small document summary used by relation evidence review."""

    id: UUID
    original_filename: str
    quality_status: str
    version_number: int
    is_current: bool
    canonical_document_id: UUID | None
    mime_type: str | None = None
    storage_bucket: str | None = None
    storage_object_path: str | None = None


@dataclass(frozen=True, slots=True)
class RelationEvidenceBlock:
    """Original-file review block annotated with relation evidence."""

    id: str
    document_id: UUID
    block_index: int
    block_type: str
    text: str
    page_number: int | None
    cells: tuple[str, ...] = ()
    highlight_type: str | None = None
    matched_pair_index: int | None = None
    confidence: float | None = None
    reason: str | None = None


@dataclass(frozen=True, slots=True)
class RelationEvidenceChunk:
    """Chunk text and provenance used to explain one relation."""

    id: str
    document_id: UUID
    chunk_index: int
    content: str
    page_number: int | None
    section_title: str | None
    normalized_content_hash: str | None
    exact_duplicate_group_id: str | None


@dataclass(frozen=True, slots=True)
class RelationEvidenceChunkPair:
    """Aligned chunk evidence for reviewer-facing highlighting."""

    source_chunk: RelationEvidenceChunk | None
    target_chunk: RelationEvidenceChunk | None
    evidence_type: str
    confidence: float
    signals: dict[str, object]
    reason: str | None


@dataclass(frozen=True, slots=True)
class DocumentRelationEvidence:
    """Reviewer-facing evidence bundle for one relation."""

    relation: DocumentRelation
    source_document: RelationEvidenceDocument | None
    target_document: RelationEvidenceDocument | None
    chunk_pairs: tuple[RelationEvidenceChunkPair, ...]
    source_original_blocks: tuple[RelationEvidenceBlock, ...] = ()
    target_original_blocks: tuple[RelationEvidenceBlock, ...] = ()


__all__ = [
    "CLAIM_COMPARISON_VERSION",
    "CHUNK_PREEMBEDDING_DETECTOR_VERSION",
    "CHUNK_NORMALIZATION_VERSION",
    "DETECTOR_VERSION",
    "DOCUMENT_NORMALIZATION_VERSION",
    "LEGACY_DOCUMENT_NORMALIZATION_VERSION",
    "NORMALIZATION_VERSION",
    "ClaimConflict",
    "ClaimKey",
    "ClaimScope",
    "ClaimValue",
    "ChunkDedupCandidate",
    "ChunkDedupProbe",
    "DocumentFingerprint",
    "DocumentRelation",
    "ExtractedClaim",
    "KnowledgeQualityAudit",
    "NumericMention",
    "NumericRole",
    "PolicyModality",
    "QualityRelationCandidate",
    "RelationStatus",
    "RelationType",
    "ScopeComparison",
    "DocumentRelationEvidence",
    "RelationEvidenceChunk",
    "RelationEvidenceChunkPair",
    "RelationEvidenceDocument",
    "RelationEvidenceBlock",
    "ResolutionAction",
    "TextRelationAnalysis",
]
