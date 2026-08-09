"""Data contracts shared by upload enqueueing and ingestion workers."""

from dataclasses import dataclass, field
from enum import StrEnum
from typing import Literal
from uuid import UUID, uuid4


class ProcessingJobType(StrEnum):
    """Why a version-scoped Enterprise processing job was created."""

    INITIAL_PROCESS = "INITIAL_PROCESS"
    NEW_VERSION = "NEW_VERSION"
    REPROCESS = "REPROCESS"


class ProcessingStage(StrEnum):
    """Stable processing stages persisted for operator-facing progress."""

    FILE_VALIDATION = "FILE_VALIDATION"
    EXTRACTION = "EXTRACTION"
    OCR = "OCR"
    PARSING = "PARSING"
    CHUNKING = "CHUNKING"
    CONTEXTUAL_ENRICHMENT = "CONTEXTUAL_ENRICHMENT"
    EMBEDDING = "EMBEDDING"
    INDEXING = "INDEXING"
    FINALIZING = "FINALIZING"


class ProcessingStageStatus(StrEnum):
    STARTED = "STARTED"
    SUCCEEDED = "SUCCEEDED"
    FAILED = "FAILED"
    SKIPPED = "SKIPPED"


@dataclass(frozen=True, slots=True)
class IngestionProfile:
    """Embedding and pipeline configuration captured when a job is enqueued."""

    embedding_model: str
    embedding_dimensions: int
    configuration: dict[str, object] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class ClaimedIngestionJob:
    """A leased job with all immutable document metadata required by a worker."""

    id: UUID
    owner_id: UUID
    notebook_id: UUID
    document_id: UUID
    attempt_number: int
    configuration: dict[str, object]
    storage_bucket: str
    storage_object_path: str
    original_filename: str
    mime_type: str
    size_bytes: int
    content_hash: str | None
    claim_token: UUID = field(default_factory=uuid4)
    document_version: int = 1
    queue_kind: Literal["legacy", "enterprise"] = "legacy"
    document_version_id: UUID | None = None
    knowledge_document_id: UUID | None = None
    source_file_id: UUID | None = None
    job_type: ProcessingJobType = ProcessingJobType.INITIAL_PROCESS

    def __post_init__(self) -> None:
        if self.attempt_number <= 0:
            raise ValueError("attempt_number must be > 0")
        if self.document_version <= 0:
            raise ValueError("document_version must be > 0")
        if self.queue_kind == "enterprise":
            if self.document_version_id is None or self.knowledge_document_id is None:
                raise ValueError(
                    "Enterprise jobs require document_version_id and knowledge_document_id"
                )
            if self.document_id != self.knowledge_document_id:
                raise ValueError("Enterprise document_id must be the logical document id")

    @property
    def is_enterprise(self) -> bool:
        return self.queue_kind == "enterprise"


@dataclass(frozen=True, slots=True)
class PersistedChunk:
    """Canonical chunk payload persisted transactionally on job completion."""

    id: UUID
    chunk_index: int
    content: str
    token_count: int
    metadata: dict[str, object]
    embedding: tuple[float, ...] = ()


@dataclass(frozen=True, slots=True)
class ProcessingFailure:
    """Sanitised, classifiable error persisted separately from raw exceptions."""

    error_type: str
    error_code: str
    safe_message: str
    retryable: bool
    stage: ProcessingStage | None = None
    internal_reference: str | None = None


@dataclass(frozen=True, slots=True)
class QueuedProcessingJob:
    """Small immutable receipt returned by version/reprocess queue operations."""

    id: UUID
    document_version_id: UUID
    job_type: ProcessingJobType
    attempt_number: int
    previous_job_id: UUID | None = None

    def ensure_reprocess_of(self, previous: "QueuedProcessingJob") -> None:
        """Enforce retry semantics without conflating retry with a new version."""

        if self.id == previous.id:
            raise ValueError("Reprocessing must create a new job")
        if self.document_version_id != previous.document_version_id:
            raise ValueError("Reprocessing must keep the same document version")
        if self.job_type != ProcessingJobType.REPROCESS:
            raise ValueError("Reprocessing jobs must use job_type REPROCESS")
        if self.previous_job_id != previous.id:
            raise ValueError("Reprocessing must link to the previous job")
        if self.attempt_number <= previous.attempt_number:
            raise ValueError("Reprocessing must advance the attempt number")
