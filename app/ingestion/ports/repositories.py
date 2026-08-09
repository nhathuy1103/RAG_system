"""Persistence contracts for durable ingestion jobs."""

from collections.abc import Sequence
from typing import Literal, Protocol, runtime_checkable
from uuid import UUID

from app.documents.domain.models import Document
from app.ingestion.domain.models import (
    ClaimedIngestionJob,
    IngestionProfile,
    PersistedChunk,
    ProcessingFailure,
    ProcessingStage,
    ProcessingStageStatus,
    QueuedProcessingJob,
)
from app.knowledge_quality.domain.models import (
    ChunkDedupCandidate,
    ChunkDedupProbe,
    ClaimScope,
    DocumentFingerprint,
    QualityRelationCandidate,
)

IngestionCompletionDisposition = Literal[
    "completed",
    "duplicate_suppressed",
]


class IngestionRepositoryError(RuntimeError):
    """Raised when ingestion persistence cannot complete an operation."""


class IngestionRepository(Protocol):
    """User-scoped operation used to enqueue a freshly uploaded document."""

    async def enqueue(
        self,
        document_id: UUID,
        notebook_id: UUID,
        profile: IngestionProfile,
    ) -> Document: ...


class IngestionWorkerRepository(Protocol):
    """Service-role operations used by the durable worker."""

    async def claim(
        self,
        worker_id: str,
        lease_seconds: int,
    ) -> ClaimedIngestionJob | None: ...

    async def renew_lease(
        self,
        job_id: UUID,
        worker_id: str,
        claim_token: UUID,
        lease_seconds: int,
    ) -> bool: ...

    async def complete(
        self,
        job: ClaimedIngestionJob,
        worker_id: str,
        chunks: Sequence[PersistedChunk],
        embedding_model: str,
        embedding_dimensions: int,
        fingerprint: DocumentFingerprint | None = None,
        relations: Sequence[QualityRelationCandidate] = (),
        effective_quality_mode: Literal["off", "shadow", "on"] = "off",
        claim_scope: ClaimScope | None = None,
    ) -> IngestionCompletionDisposition: ...

    async def find_content_duplicate(
        self,
        job: ClaimedIngestionJob,
        fingerprint: DocumentFingerprint,
    ) -> UUID | None: ...

    async def find_chunk_dedup_candidates(
        self,
        job: ClaimedIngestionJob,
        probes: Sequence[ChunkDedupProbe],
        embedding_model: str,
        candidates_per_probe: int,
    ) -> tuple[ChunkDedupCandidate, ...]: ...

    async def complete_duplicate(
        self,
        job: ClaimedIngestionJob,
        worker_id: str,
        canonical_document_id: UUID,
        fingerprint: DocumentFingerprint,
        effective_quality_mode: Literal["off", "shadow", "on"] = "off",
    ) -> None: ...

    async def fail(
        self,
        job: ClaimedIngestionJob,
        worker_id: str,
        error_message: str,
    ) -> bool: ...


@runtime_checkable
class ProcessingProgressReporter(Protocol):
    """Optional version-scoped progress/error sink used by Enterprise workers."""

    async def record_stage(
        self,
        job: ClaimedIngestionJob,
        worker_id: str,
        stage: ProcessingStage,
        status: ProcessingStageStatus,
        *,
        message: str | None = None,
    ) -> bool: ...

    async def record_error(
        self,
        job: ClaimedIngestionJob,
        worker_id: str,
        failure: ProcessingFailure,
    ) -> bool: ...


class EnterpriseProcessingQueue(Protocol):
    """Version-aware queue operations separate from legacy document enqueueing."""

    async def get_job(self, job_id: UUID) -> QueuedProcessingJob | None: ...

    async def reprocess(self, job_id: UUID) -> QueuedProcessingJob: ...
