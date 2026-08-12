"""Provider-independent semantic evidence contract for P5 generation."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from enum import StrEnum

from app.retrieval.application.query_context import QueryContext
from app.retrieval.domain.metadata import MetadataValue
from app.retrieval.domain.models import RetrievalCandidate

EVIDENCE_CONTRACT_VERSION = "p5-generation-evidence-v1"


class EvidenceBundleType(StrEnum):
    SINGLE_FACT = "SINGLE_FACT"
    DUPLICATE_GROUP = "DUPLICATE_GROUP"
    VERSION_CURRENT = "VERSION_CURRENT"
    HISTORICAL_FACT = "HISTORICAL_FACT"
    TEMPORAL_SERIES = "TEMPORAL_SERIES"
    CONDITIONAL_SET = "CONDITIONAL_SET"
    CONFLICT_SET = "CONFLICT_SET"
    UNCERTAIN_SET = "UNCERTAIN_SET"


class EvidenceStatus(StrEnum):
    CONFIRMED = "confirmed"
    UNCERTAIN = "uncertain"


class NoAnswerReason(StrEnum):
    NO_RELEVANT_EVIDENCE = "NO_RELEVANT_EVIDENCE"
    INSUFFICIENT_SCOPE = "INSUFFICIENT_SCOPE"
    CONFLICT_UNRESOLVED = "CONFLICT_UNRESOLVED"
    CURRENT_VERSION_UNKNOWN = "CURRENT_VERSION_UNKNOWN"
    TEMPORAL_EVIDENCE_MISSING = "TEMPORAL_EVIDENCE_MISSING"
    PERMISSION_FILTERED = "PERMISSION_FILTERED"
    LOW_CONFIDENCE_EVIDENCE = "LOW_CONFIDENCE_EVIDENCE"


@dataclass(frozen=True, slots=True)
class EvidenceAuthority:
    authority_level: int | None = None
    source_type: str | None = None
    approval_status: str | None = None
    authority_reason: str | None = None


@dataclass(frozen=True, slots=True)
class EvidenceProvenance:
    document_ids: tuple[str, ...]
    chunk_ids: tuple[str, ...]
    occurrence_count: int


@dataclass(frozen=True, slots=True)
class GenerationEvidence:
    evidence_id: str
    candidate: RetrievalCandidate
    claim_ids: tuple[str, ...]
    subject: str | None
    predicate: str | None
    value: Mapping[str, MetadataValue]
    qualifiers: Mapping[str, MetadataValue]
    temporal: Mapping[str, MetadataValue]
    provenance: EvidenceProvenance
    authority: EvidenceAuthority
    relation_type: str
    duplicate_group: str | None
    version_family: str | None
    conflict_group: str | None
    current_status: bool | None
    status: EvidenceStatus
    uncertainty_reasons: tuple[str, ...]
    retrieval_score: float
    rerank_score: float | None
    selection_reason: str
    evidence_group_id: str
    independent_source_count: int

    @property
    def text(self) -> str:
        return str(self.candidate.chunk.text)

    @property
    def document_id(self) -> str:
        return str(self.candidate.chunk.document_id)

    @property
    def chunk_id(self) -> str:
        return str(self.candidate.chunk.id)


@dataclass(frozen=True, slots=True)
class EvidenceBundle:
    bundle_id: str
    bundle_type: EvidenceBundleType
    evidence_ids: tuple[str, ...]
    priority: int
    mandatory: bool
    reason: str


@dataclass(frozen=True, slots=True)
class GenerationContextDiagnostics:
    input_count: int
    selected_count: int
    suppressed_ids: tuple[str, ...]
    unauthorized_ids: tuple[str, ...]
    input_characters: int
    selected_characters: int
    estimated_input_tokens: int
    estimated_selected_tokens: int
    duplicate_occurrence_count: int
    independent_evidence_count: int
    conflict_pair_count: int
    conflict_pair_completeness: float
    temporal_completeness: float
    budget_overrun_for_mandatory_evidence: bool
    policy_version: str


@dataclass(frozen=True, slots=True)
class GenerationContext:
    query: QueryContext
    evidence: tuple[GenerationEvidence, ...]
    bundles: tuple[EvidenceBundle, ...]
    no_answer_reason: NoAnswerReason | None
    follow_up: str | None
    diagnostics: GenerationContextDiagnostics
    contract_version: str = EVIDENCE_CONTRACT_VERSION

    @property
    def candidates(self) -> tuple[RetrievalCandidate, ...]:
        return tuple(item.candidate for item in self.evidence)

    @property
    def evidence_by_id(self) -> dict[str, GenerationEvidence]:
        return {item.evidence_id: item for item in self.evidence}


__all__ = [
    "EVIDENCE_CONTRACT_VERSION",
    "EvidenceAuthority",
    "EvidenceBundle",
    "EvidenceBundleType",
    "EvidenceProvenance",
    "EvidenceStatus",
    "GenerationContext",
    "GenerationContextDiagnostics",
    "GenerationEvidence",
    "NoAnswerReason",
]
