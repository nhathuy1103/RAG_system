"""Evidence-backed document metadata proposed during ingestion."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

MetadataSource = Literal[
    "user_confirmed",
    "system_record",
    "filename_extracted",
    "content_extracted",
    "rule_inferred",
    "llm_inferred",
]

DOCUMENT_METADATA_FIELDS = (
    "document_number",
    "document_type",
    "category",
    "domain",
    "project_code",
    "project_name",
    "department_code",
    "effective_from",
    "effective_to",
    "year",
    "data_period",
)


@dataclass(frozen=True, slots=True)
class MetadataEvidenceBlock:
    block_id: str
    page_number: int | None
    text: str


@dataclass(frozen=True, slots=True)
class MetadataEvidence:
    block_id: str
    page_number: int | None
    text: str


@dataclass(frozen=True, slots=True)
class DocumentMetadataAssertion:
    field_name: str
    value: str
    normalized_value: str
    source: MetadataSource
    confidence: float
    verified: bool
    evidence: tuple[MetadataEvidence, ...]
    model: str | None = None
    prompt_version: str | None = None
    input_checksum: str | None = None

    def as_dict(self) -> dict[str, object]:
        return {
            "field_name": self.field_name,
            "value": self.value,
            "normalized_value": self.normalized_value,
            "source": self.source,
            "confidence": self.confidence,
            "verified": self.verified,
            "evidence": [
                {
                    "block_id": item.block_id,
                    "page": item.page_number,
                    "text": item.text,
                }
                for item in self.evidence
            ],
            "model": self.model,
            "prompt_version": self.prompt_version,
            "input_checksum": self.input_checksum,
        }


@dataclass(frozen=True, slots=True)
class DocumentMetadataEnrichmentRequest:
    document_title: str
    language: str
    missing_fields: tuple[str, ...]
    evidence_blocks: tuple[MetadataEvidenceBlock, ...]


@dataclass(frozen=True, slots=True)
class DocumentMetadataEnrichment:
    assertions: tuple[DocumentMetadataAssertion, ...]
    status: Literal["generated", "not_needed", "fallback"]
    provider: str
    model: str
    prompt_version: str
    input_checksum: str
    error_code: str | None = None


__all__ = [
    "DOCUMENT_METADATA_FIELDS",
    "DocumentMetadataAssertion",
    "DocumentMetadataEnrichment",
    "DocumentMetadataEnrichmentRequest",
    "MetadataEvidence",
    "MetadataEvidenceBlock",
    "MetadataSource",
]
