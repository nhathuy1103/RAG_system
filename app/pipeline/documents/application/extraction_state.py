from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import StrEnum
from typing import Any


class DocumentStatus(StrEnum):
    UPLOADED = "uploaded"
    QUEUED = "queued"
    PROCESSING = "processing"
    DOWNLOADING = "downloading"
    VALIDATING = "validating"
    PARSING = "parsing"
    OCR = "ocr"
    SANITIZING = "sanitizing"
    EXTRACTED = "extracted"
    DEGRADED = "degraded"
    REVIEW_REQUIRED = "review_required"
    HUMAN_REVIEWED = "human_reviewed"
    HUMAN_VALIDATED = "human_validated"
    CHUNKING = "chunking"
    EMBEDDING = "embedding"
    EMBEDDED = "embedded"
    INDEXING = "indexing"
    INDEXED = "indexed"
    FAILED = "failed"
    CANCELLED = "cancelled"


@dataclass
class DocumentStateTransition:
    document_id: str
    from_status: str | None
    to_status: str
    reason_code: str
    actor: str = "system"
    source: str = "worker"
    processing_job_id: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)
    created_at: str = field(default_factory=lambda: datetime.now(UTC).isoformat())


TERMINAL_DOCUMENT_STATUSES = {
    DocumentStatus.EMBEDDED,
    DocumentStatus.INDEXED,
    DocumentStatus.FAILED,
    DocumentStatus.CANCELLED,
}


ALLOWED_DOCUMENT_TRANSITIONS: dict[DocumentStatus, set[DocumentStatus]] = {
    DocumentStatus.UPLOADED: {
        DocumentStatus.QUEUED,
        DocumentStatus.PROCESSING,
        DocumentStatus.DOWNLOADING,
        DocumentStatus.FAILED,
        DocumentStatus.CANCELLED,
    },
    DocumentStatus.QUEUED: {
        DocumentStatus.PROCESSING,
        DocumentStatus.DOWNLOADING,
        DocumentStatus.FAILED,
        DocumentStatus.CANCELLED,
    },
    DocumentStatus.PROCESSING: {
        DocumentStatus.DOWNLOADING,
        DocumentStatus.VALIDATING,
        DocumentStatus.PARSING,
        DocumentStatus.OCR,
        DocumentStatus.SANITIZING,
        DocumentStatus.EXTRACTED,
        DocumentStatus.FAILED,
        DocumentStatus.CANCELLED,
    },
    DocumentStatus.DOWNLOADING: {
        DocumentStatus.VALIDATING,
        DocumentStatus.FAILED,
        DocumentStatus.CANCELLED,
    },
    DocumentStatus.VALIDATING: {
        DocumentStatus.QUEUED,
        DocumentStatus.PARSING,
        DocumentStatus.SANITIZING,
        DocumentStatus.EXTRACTED,
        DocumentStatus.DEGRADED,
        DocumentStatus.CHUNKING,
        DocumentStatus.REVIEW_REQUIRED,
        DocumentStatus.FAILED,
        DocumentStatus.CANCELLED,
    },
    DocumentStatus.PARSING: {
        DocumentStatus.OCR,
        DocumentStatus.SANITIZING,
        DocumentStatus.EXTRACTED,
        DocumentStatus.REVIEW_REQUIRED,
        DocumentStatus.FAILED,
        DocumentStatus.CANCELLED,
    },
    DocumentStatus.OCR: {
        DocumentStatus.SANITIZING,
        DocumentStatus.EXTRACTED,
        DocumentStatus.REVIEW_REQUIRED,
        DocumentStatus.FAILED,
        DocumentStatus.CANCELLED,
    },
    DocumentStatus.SANITIZING: {
        DocumentStatus.VALIDATING,
        DocumentStatus.EXTRACTED,
        DocumentStatus.DEGRADED,
        DocumentStatus.REVIEW_REQUIRED,
        DocumentStatus.CHUNKING,
        DocumentStatus.FAILED,
        DocumentStatus.CANCELLED,
    },
    DocumentStatus.EXTRACTED: {
        DocumentStatus.DEGRADED,
        DocumentStatus.REVIEW_REQUIRED,
        DocumentStatus.CHUNKING,
        DocumentStatus.FAILED,
        DocumentStatus.CANCELLED,
    },
    DocumentStatus.DEGRADED: {
        DocumentStatus.CHUNKING,
        DocumentStatus.REVIEW_REQUIRED,
        DocumentStatus.FAILED,
        DocumentStatus.CANCELLED,
    },
    DocumentStatus.REVIEW_REQUIRED: {
        DocumentStatus.HUMAN_REVIEWED,
        DocumentStatus.HUMAN_VALIDATED,
        DocumentStatus.FAILED,
        DocumentStatus.CANCELLED,
    },
    DocumentStatus.HUMAN_REVIEWED: {
        DocumentStatus.HUMAN_VALIDATED,
        DocumentStatus.QUEUED,
        DocumentStatus.FAILED,
        DocumentStatus.CANCELLED,
    },
    DocumentStatus.HUMAN_VALIDATED: {
        DocumentStatus.QUEUED,
        DocumentStatus.PROCESSING,
        DocumentStatus.DOWNLOADING,
        DocumentStatus.VALIDATING,
        DocumentStatus.EXTRACTED,
        DocumentStatus.CHUNKING,
        DocumentStatus.FAILED,
        DocumentStatus.CANCELLED,
    },
    DocumentStatus.CHUNKING: {
        DocumentStatus.EMBEDDING,
        DocumentStatus.FAILED,
        DocumentStatus.CANCELLED,
    },
    DocumentStatus.EMBEDDING: {
        DocumentStatus.EMBEDDED,
        DocumentStatus.FAILED,
        DocumentStatus.CANCELLED,
    },
    DocumentStatus.EMBEDDED: {
        DocumentStatus.QUEUED,
        DocumentStatus.CANCELLED,
    },
    DocumentStatus.INDEXING: {
        DocumentStatus.INDEXED,
        DocumentStatus.FAILED,
        DocumentStatus.CANCELLED,
    },
    DocumentStatus.INDEXED: {
        DocumentStatus.QUEUED,
        DocumentStatus.CANCELLED,
    },
    DocumentStatus.FAILED: {
        DocumentStatus.QUEUED,
        DocumentStatus.CANCELLED,
    },
    DocumentStatus.CANCELLED: {
        DocumentStatus.QUEUED,
    },
}


def coerce_document_status(value: DocumentStatus | str | None) -> DocumentStatus | None:
    if value is None:
        return None
    if isinstance(value, DocumentStatus):
        return value
    return DocumentStatus(str(value))


def is_valid_document_transition(
    from_status: DocumentStatus | str | None,
    to_status: DocumentStatus | str,
) -> bool:
    current = coerce_document_status(from_status)
    target = coerce_document_status(to_status)
    if target is None:
        return False
    if current is None or current == target:
        return True
    return target in ALLOWED_DOCUMENT_TRANSITIONS.get(current, set())


def transition_document_status(
    document_id: str,
    from_status: DocumentStatus | str | None,
    to_status: DocumentStatus | str,
    *,
    reason_code: str,
    actor: str = "system",
    source: str = "worker",
    processing_job_id: str | None = None,
    metadata: dict[str, Any] | None = None,
) -> DocumentStateTransition:
    current = coerce_document_status(from_status)
    target = coerce_document_status(to_status)
    if target is None:
        raise ValueError("to_status is required")
    if not is_valid_document_transition(current, target):
        from_value = current.value if current is not None else None
        raise ValueError(f"Invalid document status transition: {from_value} -> {target.value}")
    return DocumentStateTransition(
        document_id=document_id,
        processing_job_id=processing_job_id,
        from_status=current.value if current is not None else None,
        to_status=target.value,
        reason_code=reason_code,
        actor=actor,
        source=source,
        metadata=dict(metadata or {}),
    )


def transition_document(
    document: object,
    to_status: DocumentStatus | str,
    *,
    reason_code: str,
    actor: str = "system",
    source: str = "worker",
    processing_job_id: str | None = None,
    metadata: dict[str, Any] | None = None,
) -> DocumentStateTransition:
    current_status = coerce_document_status(
        getattr(document, "status", None) or getattr(document, "extraction_state", None)
    )
    document_id = str(
        getattr(document, "id", None)
        or getattr(document, "document_id", None)
        or "unknown-document"
    )
    transition = transition_document_status(
        document_id=document_id,
        from_status=current_status,
        to_status=to_status,
        reason_code=reason_code,
        actor=actor,
        source=source,
        processing_job_id=processing_job_id,
        metadata=metadata,
    )
    target_status = coerce_document_status(to_status)
    if target_status is not None:
        if hasattr(document, "status"):
            document.status = target_status
        if hasattr(document, "extraction_state"):
            document.extraction_state = target_status.value
    return transition
