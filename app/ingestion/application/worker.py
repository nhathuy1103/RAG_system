"""Durable background worker connecting Storage to Advanced Extraction."""

from __future__ import annotations

import asyncio
import logging
from collections import Counter
from collections.abc import Mapping, Sequence
from contextlib import suppress
from dataclasses import replace
from datetime import UTC, date, datetime
from enum import Enum
from hashlib import sha256
from typing import Any, Literal, cast
from uuid import NAMESPACE_URL, UUID, uuid4, uuid5

from app.documents.ports.storage import DocumentObjectStorage
from app.infrastructure.telemetry import Observation, Telemetry
from app.ingestion.domain.models import (
    ClaimedIngestionJob,
    IngestionProfile,
    PersistedChunk,
    ProcessingStage,
    ProcessingStageStatus,
)
from app.ingestion.ports.repositories import (
    IngestionWorkerRepository,
    ProcessingProgressReporter,
)
from app.knowledge_quality.application.analysis import (
    build_legacy_document_fingerprint,
    is_auto_identity_eligible,
)
from app.knowledge_quality.application.business_scope import (
    ScopeTextContext,
    resolve_business_context,
)
from app.knowledge_quality.application.chunk_preembedding import (
    build_chunk_dedup_probes,
    plan_chunk_deduplication,
)
from app.knowledge_quality.application.detection import (
    FusedCandidateDetectionResult,
    detect_document_relation_candidates,
    detect_fused_document_relation_candidates,
)
from app.knowledge_quality.application.persisted_relation_aggregation import (
    aggregate_persisted_claim_relations,
)
from app.knowledge_quality.application.scope import extract_claim_scope
from app.knowledge_quality.domain.models import (
    LEGACY_DOCUMENT_NORMALIZATION_VERSION,
    ChunkDedupCandidate,
    ChunkDedupProbe,
    ClaimScope,
    DocumentFingerprint,
    QualityRelationCandidate,
    RelationType,
)
from app.knowledge_quality.domain.relation_models import AGGREGATION_POLICY_VERSION
from app.knowledge_quality.ports.repositories import KnowledgeRelationWriter
from app.pipeline.bootstrap.settings import Settings as IngestionSettings
from app.pipeline.documents.application.content_identity import (
    build_parsed_document_fingerprint,
)
from app.pipeline.documents.domain.parsed import ParsedTable
from app.pipeline.documents.domain.source import DocumentSource
from app.pipeline.indexing.adapters.context_enrichers import (
    build_context_enrichment_profile,
)
from app.pipeline.indexing.adapters.document_metadata_enrichers import (
    DOCUMENT_METADATA_PROMPT_VERSION,
)
from app.pipeline.indexing.application.pipeline import (
    ChunkEmbeddingPlan,
    IngestionEmbeddingPipeline,
    IngestionEmbeddingResult,
)
from app.pipeline.indexing.domain.embedded_chunk import EmbeddedChunk
from app.pipeline.shared.text_utils import compute_checksum_text
from app.shared.contextual_text import CONTEXTUAL_TEXT_VERSION
from app.structured_facts.application.claim_extraction import (
    CLAIM_EXTRACTOR_VERSION,
    extract_structured_claims,
)
from app.structured_facts.application.comparison import (
    build_structured_relation_payloads,
    build_unified_claim_relation_payloads,
)
from app.structured_facts.application.persistence import (
    build_structured_fact_persistence_batch,
)
from app.structured_facts.application.table_analyzer import (
    TABLE_FACT_EXTRACTOR_VERSION,
    TableAnalysis,
    analyze_table,
)
from app.structured_facts.domain.models import (
    BusinessScope,
    EntityEvidenceSource,
    LocationScope,
    StructuredClaim,
)
from app.structured_facts.ports.repositories import (
    StructuredClaimCandidate,
    StructuredFactStore,
    StructuredFactWriteResult,
)

LOGGER = logging.getLogger(__name__)
REQUIRED_EMBEDDING_PROVIDER = "openai"
REQUIRED_EMBEDDING_MODEL = "text-embedding-3-small"
REQUIRED_EMBEDDING_DIMENSIONS = 1536
REQUIRED_VECTOR_STORES = {"qdrant", "pgvector"}
KnowledgeQualityMode = Literal["off", "shadow", "on"]
StructuredFactMode = Literal["off", "shadow", "on"]
CandidateGenerationMode = Literal["legacy", "shadow", "on"]
_KEY_RETRIEVAL_METADATA_FIELDS = (
    "document_number",
    "document_type",
    "domain",
    "project_code",
    "year",
    "data_period",
    "effective_status",
)


class IngestionLeaseLostError(RuntimeError):
    """Raised before a stale worker can commit externally visible state."""


def build_ingestion_profile(
    settings: IngestionSettings,
    *,
    knowledge_quality_mode: KnowledgeQualityMode = "off",
    structured_fact_mode: StructuredFactMode = "off",
) -> IngestionProfile:
    """Capture the settings that materially affect one ingestion attempt."""
    if settings.embedding_provider != REQUIRED_EMBEDDING_PROVIDER:
        raise ValueError("EMBEDDING_PROVIDER=openai is required for document ingestion.")
    if settings.openai_embedding_model != REQUIRED_EMBEDDING_MODEL:
        raise ValueError("OPENAI_EMBEDDING_MODEL=text-embedding-3-small is required.")
    if settings.vector_store_backend not in REQUIRED_VECTOR_STORES:
        raise ValueError("VECTOR_STORE_BACKEND must be qdrant or pgvector for document ingestion.")
    if not settings.openai_api_key:
        raise ValueError("OPENAI_API_KEY is required for document ingestion.")
    if knowledge_quality_mode not in {"off", "shadow", "on"}:
        raise ValueError("Knowledge quality mode must be off, shadow, or on")
    if structured_fact_mode not in {"off", "shadow", "on"}:
        raise ValueError("Structured fact mode must be off, shadow, or on")
    contextual_profile = build_context_enrichment_profile(settings.context_enrichment_config)
    return IngestionProfile(
        embedding_model=REQUIRED_EMBEDDING_MODEL,
        embedding_dimensions=REQUIRED_EMBEDDING_DIMENSIONS,
        configuration={
            "advanced_extraction_enabled": settings.advanced_extraction_enabled,
            "extraction_quality_mode": settings.extraction_quality_mode,
            "ocr_enabled": settings.ocr_enabled,
            "chunk_size": settings.chunk_size,
            "chunk_overlap": settings.chunk_overlap,
            "chunking_strategy": settings.chunking_strategy,
            "contextual_enrichment_enabled": settings.contextual_enrichment_enabled,
            **contextual_profile,
            "contextual_text_version": CONTEXTUAL_TEXT_VERSION,
            "document_metadata_enrichment_enabled": (
                settings.document_metadata_enrichment_enabled
            ),
            "document_metadata_enrichment_model": (
                settings.document_metadata_enrichment_model
            ),
            "document_metadata_enrichment_prompt_version": (
                DOCUMENT_METADATA_PROMPT_VERSION
            ),
            "document_metadata_enrichment_max_chars": (
                settings.document_metadata_enrichment_max_chars
            ),
            "document_metadata_enrichment_max_output_tokens": (
                settings.document_metadata_enrichment_max_output_tokens
            ),
            "document_metadata_enrichment_strict": (
                settings.document_metadata_enrichment_strict
            ),
            "document_metadata_enrichment_verification_policy": (
                "exact_evidence_unverified"
            ),
            "embedding_provider": settings.embedding_provider,
            "vector_store_backend": settings.vector_store_backend,
            "knowledge_quality_mode": knowledge_quality_mode,
            "structured_fact_mode": structured_fact_mode,
        },
    )


class IngestionWorker:
    """Claim, process, and complete one durable ingestion job at a time."""

    def __init__(
        self,
        *,
        repository: IngestionWorkerRepository,
        object_storage: DocumentObjectStorage,
        pipeline: IngestionEmbeddingPipeline,
        poll_interval_seconds: float = 2.0,
        lease_seconds: int = 1800,
        worker_id: str | None = None,
        knowledge_quality_mode: KnowledgeQualityMode = "off",
        structured_fact_mode: StructuredFactMode = "off",
        structured_fact_store: StructuredFactStore | None = None,
        quality_max_probe_chunks: int = 8,
        quality_candidates_per_probe: int = 5,
        candidate_generation_mode: CandidateGenerationMode = "legacy",
        candidate_channel_k: int = 30,
        candidate_final_top_k: int = 50,
        telemetry: Telemetry | None = None,
    ) -> None:
        if poll_interval_seconds <= 0:
            raise ValueError("Worker poll interval must be > 0")
        if lease_seconds < 30:
            raise ValueError("Worker lease must be at least 30 seconds")
        if knowledge_quality_mode not in {"off", "shadow", "on"}:
            raise ValueError("Knowledge quality mode must be off, shadow, or on")
        if structured_fact_mode not in {"off", "shadow", "on"}:
            raise ValueError("Structured fact mode must be off, shadow, or on")
        if quality_max_probe_chunks <= 0 or quality_candidates_per_probe <= 0:
            raise ValueError("Knowledge quality candidate limits must be > 0")
        if candidate_generation_mode not in {"legacy", "shadow", "on"}:
            raise ValueError("Candidate generation mode must be legacy, shadow, or on")
        if not 1 <= candidate_channel_k <= 50:
            raise ValueError("Candidate channel limit must be between 1 and 50")
        if not 1 <= candidate_final_top_k <= 50:
            raise ValueError("Final candidate limit must be between 1 and 50")
        self._repository = repository
        self._object_storage = object_storage
        self._pipeline = pipeline
        self._poll_interval_seconds = poll_interval_seconds
        self._lease_seconds = lease_seconds
        self._worker_id = worker_id or f"api-{uuid4()}"
        self._knowledge_quality_mode = knowledge_quality_mode
        self._structured_fact_mode = structured_fact_mode
        self._structured_fact_store = structured_fact_store
        self._quality_max_probe_chunks = quality_max_probe_chunks
        self._quality_candidates_per_probe = quality_candidates_per_probe
        self._candidate_generation_mode = candidate_generation_mode
        self._candidate_channel_k = candidate_channel_k
        self._candidate_final_top_k = candidate_final_top_k
        self._telemetry = telemetry or Telemetry()

    def _structured_mode_for_job(
        self,
        job: ClaimedIngestionJob,
    ) -> StructuredFactMode:
        """Apply the safer durable/runtime mode for structured fact extraction."""
        configured = job.configuration.get("structured_fact_mode")
        if configured not in {"off", "shadow", "on"}:
            LOGGER.warning(
                ("Ingestion job %s has no valid durable structured-fact mode; using fail-safe off"),
                job.id,
            )
            return "off"
        enqueued_mode = cast(StructuredFactMode, configured)
        mode_order: dict[StructuredFactMode, int] = {
            "off": 0,
            "shadow": 1,
            "on": 2,
        }
        mode = min(
            (enqueued_mode, self._structured_fact_mode),
            key=mode_order.__getitem__,
        )
        if enqueued_mode != self._structured_fact_mode:
            LOGGER.warning(
                (
                    "Ingestion job %s was enqueued with structured-fact mode "
                    "%s while this worker is configured for %s; applying the "
                    "safer effective mode %s"
                ),
                job.id,
                enqueued_mode,
                self._structured_fact_mode,
                mode,
            )
        return mode

    def _quality_mode_for_job(
        self,
        job: ClaimedIngestionJob,
    ) -> KnowledgeQualityMode:
        """Keep rollout semantics fixed to the enqueue-time job profile."""
        configured = job.configuration.get("knowledge_quality_mode")
        if configured not in {"off", "shadow", "on"}:
            LOGGER.warning(
                (
                    "Ingestion job %s has no valid durable knowledge-quality "
                    "mode; using fail-safe off"
                ),
                job.id,
            )
            return "off"
        enqueued_mode = cast(KnowledgeQualityMode, configured)
        mode_order: dict[KnowledgeQualityMode, int] = {
            "off": 0,
            "shadow": 1,
            "on": 2,
        }
        mode = min(
            (enqueued_mode, self._knowledge_quality_mode),
            key=mode_order.__getitem__,
        )
        if enqueued_mode != self._knowledge_quality_mode:
            LOGGER.warning(
                (
                    "Ingestion job %s was enqueued with knowledge-quality mode "
                    "%s while this worker is configured for %s; applying the "
                    "safer effective mode %s"
                ),
                job.id,
                enqueued_mode,
                self._knowledge_quality_mode,
                mode,
            )
        return mode

    async def run_forever(self, stop_event: asyncio.Event) -> None:
        """Poll until application shutdown while isolating transient failures."""
        while not stop_event.is_set():
            try:
                processed = await self.run_once()
            except Exception:
                LOGGER.exception("Could not claim an ingestion job")
                await self._wait_or_stop(stop_event)
                continue

            if not processed:
                await self._wait_or_stop(stop_event)

    async def run_once(self) -> bool:
        """Claim and process at most one job, returning whether one was found."""
        job = await self._repository.claim(
            self._worker_id,
            self._lease_seconds,
        )
        if job is None:
            return False
        await self._process(job)
        return True

    async def _process(self, job: ClaimedIngestionJob) -> None:
        trace_id = self._telemetry.create_trace_id(seed=f"ingestion:{job.id}:{job.attempt_number}")
        with self._telemetry.observe(
            "rag.ingestion.job",
            as_type="chain",
            trace_id=trace_id,
            input={
                "job_id": str(job.id),
                "document_id": str(job.document_id),
                "filename": self._telemetry.content(job.original_filename),
                "mime_type": job.mime_type,
                "size_bytes": job.size_bytes,
                "attempt": job.attempt_number,
            },
            metadata={
                "job_id": str(job.id),
                "document_id": str(job.document_id),
                "notebook_id": str(job.notebook_id),
                "attempt": job.attempt_number,
                "worker_id": self._worker_id,
            },
            user_id=str(job.owner_id),
            session_id=str(job.notebook_id),
            tags=("rag", "ingestion", "background-worker"),
            trace_name="rag-ingestion",
        ) as observation:
            await self._process_job(job, observation)

    async def _process_job(
        self,
        job: ClaimedIngestionJob,
        root_observation: Observation,
    ) -> None:
        quality_mode = self._quality_mode_for_job(job)
        structured_mode = self._structured_mode_for_job(job)
        if job.is_enterprise:
            # Legacy quality/structured stores still carry notebook/document
            # foreign keys. Enterprise chunks are persisted canonically by
            # complete_processing_job and must not write those compatibility
            # tables during the expand/cutover phase.
            quality_mode = "off"
            structured_mode = "off"
        is_repair_job = job.configuration.get("ingestion_kind") == "reconciliation_repair"
        if is_repair_job:
            # Repair restores derived artifacts only. It must never create a
            # new duplicate/version/conflict decision or suppress a document.
            quality_mode = "off"
            structured_mode = "off"
        heartbeat_stop = asyncio.Event()
        lease_lost = asyncio.Event()
        heartbeat = asyncio.create_task(
            self._heartbeat(job, heartbeat_stop, lease_lost),
            name=f"ingestion-heartbeat-{job.id}",
        )
        vectors_persisted = False
        current_stage = ProcessingStage.FILE_VALIDATION
        try:
            await self._report_stage(
                job,
                current_stage,
                ProcessingStageStatus.STARTED,
            )
            with self._telemetry.observe(
                "ingestion.storage_download",
                as_type="tool",
                input={
                    "bucket": job.storage_bucket,
                    "object_path": self._telemetry.content(job.storage_object_path),
                },
            ) as observation:
                content = await self._object_storage.download(
                    job.storage_bucket,
                    job.storage_object_path,
                )
                observation.update(output={"size_bytes": len(content)})
            with self._telemetry.observe(
                "ingestion.verify_download",
                as_type="guardrail",
                input={"expected_size_bytes": job.size_bytes},
            ) as observation:
                self._verify_download(job, content)
                observation.update(output={"checksum_valid": True, "size_valid": True})
            await self._report_stage(
                job,
                current_stage,
                ProcessingStageStatus.SUCCEEDED,
            )
            source = DocumentSource(
                document_id=str(job.document_id),
                owner_id=str(job.owner_id),
                tenant_id=str(job.notebook_id),
                title=job.original_filename,
                content=content,
                version=job.document_version,
                mime_type=job.mime_type,
                metadata={
                    "notebook_id": str(job.notebook_id),
                    "ingestion_job_id": str(job.id),
                    "ingestion_attempt": job.attempt_number,
                    "ingestion_generation": str(job.claim_token),
                    "storage_bucket": job.storage_bucket,
                    "storage_object_path": job.storage_object_path,
                    "document_version_id": (
                        str(job.document_version_id) if job.document_version_id else None
                    ),
                },
            )
            current_stage = ProcessingStage.EXTRACTION
            await self._report_stage(
                job,
                current_stage,
                ProcessingStageStatus.STARTED,
            )
            prepared = await asyncio.to_thread(
                self._pipeline.prepare,
                source,
                contextualize=False,
                metadata_enrich=self._document_metadata_enrichment_for_job(job),
            )
            await self._report_stage(
                job,
                current_stage,
                ProcessingStageStatus.SUCCEEDED,
            )
            for completed_stage in (ProcessingStage.PARSING, ProcessingStage.CHUNKING):
                current_stage = completed_stage
                await self._report_stage(
                    job,
                    current_stage,
                    ProcessingStageStatus.STARTED,
                )
                await self._report_stage(
                    job,
                    current_stage,
                    ProcessingStageStatus.SUCCEEDED,
                )
            source_scope = extract_claim_scope(
                prepared.parsed_document.text,
                document_id=str(job.document_id),
                filename=job.original_filename,
                version_id=str(job.document_version),
            )
            repair_expected_hash = job.configuration.get("expected_normalized_content_hash")
            fingerprint_required = (
                quality_mode != "off"
                or structured_mode != "off"
                or (is_repair_job and repair_expected_hash is not None)
            )
            expected_version = job.configuration.get("expected_normalization_version")
            if not fingerprint_required:
                parsed_fingerprint = None
            elif is_repair_job and expected_version == LEGACY_DOCUMENT_NORMALIZATION_VERSION:
                parsed_fingerprint = build_legacy_document_fingerprint(
                    prepared.parsed_document.text
                )
            else:
                parsed_fingerprint = build_parsed_document_fingerprint(prepared.parsed_document)
            fingerprint = parsed_fingerprint if quality_mode != "off" or is_repair_job else None
            structured_template_fingerprint = (
                parsed_fingerprint.template_structure_signature
                if structured_mode != "off" and parsed_fingerprint is not None
                else None
            )
            if is_repair_job and fingerprint is not None:
                expected_loose = job.configuration.get("expected_loose_content_signature")
                if (
                    fingerprint.strict_hash != repair_expected_hash
                    or fingerprint.normalization_version != expected_version
                    or fingerprint.loose_signature != expected_loose
                ):
                    raise RuntimeError("Repair source fingerprint changed after requeue")
            structured_analyses = (
                self._analyze_structured_tables(
                    job=job,
                    tables=prepared.parsed_document.tables,
                    source_scope=source_scope,
                    document_metadata=prepared.parsed_document.document_metadata,
                )
                if structured_mode != "off"
                else ()
            )
            relations: tuple[QualityRelationCandidate, ...] = ()
            chunk_dedup_stats: dict[str, object] = {}
            duplicate_id: UUID | None = None
            if (
                not is_repair_job
                and fingerprint is not None
                and is_auto_identity_eligible(fingerprint)
            ):
                duplicate_id = await self._safe_find_content_duplicate(job, fingerprint)
                if duplicate_id is not None and quality_mode == "on":
                    self._ensure_lease(lease_lost)
                    await self._repository.complete_duplicate(
                        job,
                        self._worker_id,
                        duplicate_id,
                        fingerprint,
                        effective_quality_mode=quality_mode,
                    )
                    root_observation.update(
                        output={
                            "status": "succeeded",
                            "decision": "exact_content_duplicate",
                            "canonical_document_id": str(duplicate_id),
                        }
                    )
                    return
                if duplicate_id is not None:
                    relations = (
                        QualityRelationCandidate(
                            target_document_id=duplicate_id,
                            relation_type=RelationType.EXACT_CONTENT,
                            confidence=1.0,
                            signals={"strict_content_match": True},
                            reason="strict_content_match",
                        ),
                    )

            current_stage = ProcessingStage.CONTEXTUAL_ENRICHMENT
            await self._report_stage(
                job,
                current_stage,
                ProcessingStageStatus.STARTED,
            )
            prepared = await asyncio.to_thread(
                self._pipeline.contextualize,
                prepared,
                enabled=self._contextual_enrichment_for_job(job),
            )
            await self._report_stage(
                job,
                current_stage,
                ProcessingStageStatus.SUCCEEDED,
            )

            chunk_embedding_plan: ChunkEmbeddingPlan | None = None
            high_recall_probes: tuple[ChunkDedupProbe, ...] = ()
            high_recall_candidates: tuple[ChunkDedupCandidate, ...] = ()
            if not is_repair_job and quality_mode != "off":
                with self._telemetry.observe(
                    "ingestion.chunk_preembedding_quality",
                    as_type="guardrail",
                    input={"chunk_count": len(prepared.chunks)},
                ) as observation:
                    if self._candidate_generation_mode in {"shadow", "on"}:
                        high_recall_probes = build_chunk_dedup_probes(
                            prepared.chunks,
                            max_fuzzy_probes=None,
                            scope=source_scope,
                            high_recall_candidates=True,
                        )
                        high_recall_candidates = (
                            await self._safe_find_chunk_dedup_candidates(
                                job,
                                high_recall_probes,
                                candidates_per_probe=self._candidate_channel_k,
                            )
                        )
                        high_recall_plan = plan_chunk_deduplication(
                            high_recall_probes,
                            high_recall_candidates,
                            embedding_model=self._pipeline.embedding_provider.model_name,
                            enable_exact_reuse=(
                                quality_mode == "on"
                                and self._candidate_generation_mode == "on"
                            ),
                        )
                    else:
                        high_recall_plan = None

                    if self._candidate_generation_mode in {"legacy", "shadow"}:
                        probes = build_chunk_dedup_probes(
                            prepared.chunks,
                            max_fuzzy_probes=self._quality_max_probe_chunks,
                            scope=source_scope,
                        )
                        chunk_candidates = await self._safe_find_chunk_dedup_candidates(
                            job,
                            probes,
                        )
                        dedup_plan = plan_chunk_deduplication(
                            probes,
                            chunk_candidates,
                            embedding_model=self._pipeline.embedding_provider.model_name,
                            enable_exact_reuse=quality_mode == "on",
                        )
                    else:
                        assert high_recall_plan is not None
                        dedup_plan = high_recall_plan
                    chunk_embedding_plan = ChunkEmbeddingPlan(
                        precomputed_vectors=dedup_plan.precomputed_vectors,
                        reuse_from_chunk_index=dedup_plan.reuse_from_chunk_index,
                        metadata_by_chunk_index=dedup_plan.metadata_by_chunk_index,
                    )
                    relations = self._merge_relation_candidates(
                        relations,
                        dedup_plan.relations,
                    )
                    chunk_dedup_stats = {
                        "candidate_generation_mode": self._candidate_generation_mode,
                        "active": dedup_plan.to_stats(),
                        "eligible_probe_count": sum(
                            probe.include_fuzzy_candidates
                            for probe in (
                                high_recall_probes
                                if self._candidate_generation_mode == "on"
                                else probes
                            )
                        ),
                    }
                    if (
                        self._candidate_generation_mode == "shadow"
                        and high_recall_plan is not None
                    ):
                        chunk_dedup_stats["p1_shadow"] = {
                            **high_recall_plan.to_stats(),
                            "eligible_probe_count": sum(
                                probe.include_fuzzy_candidates
                                for probe in high_recall_probes
                            ),
                        }
                    observation.update(output=chunk_dedup_stats)

            current_stage = ProcessingStage.EMBEDDING
            await self._report_stage(
                job,
                current_stage,
                ProcessingStageStatus.STARTED,
            )
            result = await asyncio.to_thread(
                self._pipeline.embed,
                prepared,
                persist_vectors=False,
                chunk_plan=chunk_embedding_plan,
            )
            await self._report_stage(
                job,
                current_stage,
                ProcessingStageStatus.SUCCEEDED,
            )
            result = self._attach_claim_scope(
                result,
                source_scope,
                structured_fact_mode=structured_mode,
            )
            if (
                not is_repair_job
                and fingerprint is not None
                and duplicate_id is None
                and self._pipeline.vector_index is not None
            ):
                if self._candidate_generation_mode == "legacy":
                    detected = await self._safe_detect_relations(result)
                    relations = self._merge_relation_candidates(relations, detected)
                elif high_recall_probes:
                    fused = await self._safe_detect_fused_relations(
                        result,
                        high_recall_probes,
                        high_recall_candidates,
                    )
                    chunk_dedup_stats["post_embedding_fusion"] = {
                        "probe_count": fused.probe_count,
                        "ann_candidate_count": fused.ann_candidate_count,
                        "final_candidate_count": len(fused.candidates),
                        "relation_count": len(fused.relations),
                        "channel_candidate_counts": dict(
                            sorted(
                                Counter(
                                    evidence.channel.value
                                    for candidate in fused.candidates
                                    for evidence in candidate.channel_evidence
                                ).items()
                            )
                        ),
                    }
                    if self._candidate_generation_mode == "on":
                        relations = self._merge_relation_candidates(
                            relations,
                            fused.relations,
                        )

            self._ensure_lease(lease_lost)
            renewed = await self._repository.renew_lease(
                job.id,
                self._worker_id,
                job.claim_token,
                self._lease_seconds,
            )
            if not renewed:
                raise IngestionLeaseLostError("Ingestion lease was lost before vector commit")
            current_stage = ProcessingStage.INDEXING
            await self._report_stage(
                job,
                current_stage,
                ProcessingStageStatus.STARTED,
            )
            if self._pipeline.requires_external_vector_persistence:
                await asyncio.to_thread(
                    self._pipeline.persist_vectors,
                    source,
                    result.embedded_chunks,
                )
                vectors_persisted = True
            with self._telemetry.observe(
                "ingestion.map_persisted_chunks",
                as_type="chain",
                input={"embedded_chunk_count": len(result.embedded_chunks)},
            ) as observation:
                chunks = self._to_persisted_chunks(result)
                metadata_coverage = _retrieval_metadata_fill_statistics(chunks)
                enrichment = result.parsed_document.document_metadata.get(
                    "metadata_enrichment"
                )
                enrichment_status = (
                    str(enrichment.get("status") or "unknown")
                    if isinstance(enrichment, Mapping)
                    else "disabled"
                )
                observation.update(
                    output={
                        "persisted_chunk_count": len(chunks),
                        "retrieval_metadata_coverage": metadata_coverage,
                        "document_metadata_enrichment_status": enrichment_status,
                        "document_metadata_assertion_count": len(
                            result.document_metadata_assertions
                        ),
                    }
                )
            if not chunks:
                raise RuntimeError("Extraction produced no indexable chunks")
            dimensions = result.embedded_chunks[0].vector_size
            await self._report_stage(
                job,
                current_stage,
                ProcessingStageStatus.SUCCEEDED,
            )
            current_stage = ProcessingStage.FINALIZING
            await self._report_stage(
                job,
                current_stage,
                ProcessingStageStatus.STARTED,
            )
            with self._telemetry.observe(
                "ingestion.persist_supabase",
                as_type="tool",
                input={
                    "chunk_count": len(chunks),
                    "embedding_model": result.embedding_model,
                    "embedding_dimensions": dimensions,
                },
            ) as observation:
                completion_disposition = await self._repository.complete(
                    job,
                    self._worker_id,
                    chunks,
                    result.embedding_model,
                    dimensions,
                    fingerprint,
                    relations,
                    effective_quality_mode=quality_mode,
                    claim_scope=source_scope,
                )
                observation.update(output={"job_status": "succeeded"})
            if vectors_persisted:
                try:
                    if completion_disposition == "duplicate_suppressed":
                        await asyncio.to_thread(
                            self._pipeline.delete_document_generation_vectors,
                            str(job.document_id),
                            str(job.claim_token),
                        )
                    else:
                        await asyncio.to_thread(
                            self._pipeline.finalize_vector_generation,
                            str(job.document_id),
                            job.document_version,
                            str(job.claim_token),
                        )
                except Exception:
                    # The fenced database completion is authoritative. Leaving
                    # an older Qdrant generation is safe and reconciliation can
                    # remove it without turning a successful job into failure.
                    LOGGER.exception(
                        (
                            "Could not reconcile vector generation after %s "
                            "completion for document %s"
                        ),
                        completion_disposition,
                        job.document_id,
                    )
            structured_write_result: StructuredFactWriteResult | None = None
            if structured_mode != "off" and completion_disposition == "completed":
                structured_write_result = await self._safe_replace_structured_facts(
                    job=job,
                    result=result,
                    analyses=structured_analyses,
                    template_fingerprint=structured_template_fingerprint,
                    fingerprint=fingerprint,
                )
            structured_output: dict[str, object] = {
                "structured_fact_mode": structured_mode,
            }
            if structured_write_result is not None:
                structured_output.update(
                    {
                        "structured_table_count": structured_write_result.table_count,
                        "structured_claim_count": structured_write_result.claim_count,
                        "structured_relation_count": structured_write_result.relation_count,
                    }
                )
            root_observation.update(
                output={
                    "status": "succeeded",
                    "chunk_count": len(chunks),
                    "embedding_model": result.embedding_model,
                    "embedding_dimensions": dimensions,
                    "quality_relation_count": len(relations),
                    "chunk_preembedding_quality": chunk_dedup_stats,
                    "retrieval_metadata_coverage": metadata_coverage,
                    "document_metadata_enrichment_status": enrichment_status,
                    "document_metadata_assertion_count": len(
                        result.document_metadata_assertions
                    ),
                    **structured_output,
                }
            )
        except Exception as exc:
            LOGGER.exception(
                "Ingestion failed for document %s (job %s)",
                job.document_id,
                job.id,
            )
            try:
                safe_error = self._safe_error(exc)
                await self._report_stage(
                    job,
                    current_stage,
                    ProcessingStageStatus.FAILED,
                    message=safe_error[:1000],
                )
                with self._telemetry.observe(
                    "ingestion.persist_failure",
                    as_type="tool",
                    input={"error_type": exc.__class__.__name__},
                ):
                    failure_accepted = await self._repository.fail(
                        job,
                        self._worker_id,
                        safe_error,
                    )
                if failure_accepted and vectors_persisted:
                    # Cleanup is fenced by the accepted failure transition. A
                    # stale worker must not delete a newer claim's vectors.
                    with self._telemetry.observe(
                        "ingestion.compensate_vector_delete",
                        as_type="tool",
                        input={"document_id": str(job.document_id)},
                    ):
                        await asyncio.to_thread(
                            self._pipeline.delete_document_generation_vectors,
                            str(job.document_id),
                            str(job.claim_token),
                        )
                root_observation.update(
                    output={"status": "failed", "error_type": exc.__class__.__name__},
                    level="ERROR",
                    status_message=safe_error,
                )
            except Exception:
                LOGGER.exception("Could not persist failure for ingestion job %s", job.id)
        finally:
            heartbeat_stop.set()
            await heartbeat

    async def _report_stage(
        self,
        job: ClaimedIngestionJob,
        stage: ProcessingStage,
        status: ProcessingStageStatus,
        *,
        message: str | None = None,
    ) -> None:
        if not job.is_enterprise or not isinstance(
            self._repository,
            ProcessingProgressReporter,
        ):
            return
        try:
            await self._repository.record_stage(
                job,
                self._worker_id,
                stage,
                status,
                message=message,
            )
        except Exception:
            # Stage history is observability data. The fenced job transition
            # remains authoritative and must still be attempted.
            LOGGER.warning(
                "Could not persist processing stage %s/%s for job %s",
                stage.value,
                status.value,
                job.id,
                exc_info=True,
            )

    def _analyze_structured_tables(
        self,
        *,
        job: ClaimedIngestionJob,
        tables: Sequence[ParsedTable],
        source_scope: ClaimScope,
        document_metadata: Mapping[str, object],
    ) -> tuple[TableAnalysis, ...]:
        """Analyze tables independently so one malformed table cannot stop ingestion."""

        if not tables:
            return ()
        ingested_at = datetime.now(UTC).isoformat()
        base_scope = BusinessScope(
            location=LocationScope(project=source_scope.project_id),
            document_type=source_scope.document_type,
        )
        analyses: list[TableAnalysis] = []
        for table in tables:
            self._enrich_structured_table_metadata(
                table=table,
                job=job,
                source_scope=source_scope,
                ingested_at=ingested_at,
                document_metadata=document_metadata,
            )
            try:
                analyses.append(
                    analyze_table(
                        document_id=str(job.document_id),
                        table=table,
                        base_scope=base_scope,
                    )
                )
            except Exception:
                LOGGER.exception(
                    "Structured table analysis failed for table %s in document %s; skipping table",
                    table.table_id,
                    job.document_id,
                )
        return tuple(analyses)

    @staticmethod
    def _enrich_structured_table_metadata(
        *,
        table: ParsedTable,
        job: ClaimedIngestionJob,
        source_scope: ClaimScope,
        ingested_at: str,
        document_metadata: Mapping[str, object],
    ) -> None:
        """Attach durable tenant, time, and authority context before extraction."""

        metadata = dict(table.metadata or {})
        metadata.setdefault("owner_id", str(job.owner_id))
        metadata.setdefault("notebook_id", str(job.notebook_id))
        metadata.setdefault("document_id", str(job.document_id))
        metadata.setdefault("document_version", job.document_version)
        metadata.setdefault(
            "source_type",
            document_metadata.get("source_type") or "uploaded_document",
        )
        metadata.setdefault("mime_type", job.mime_type)
        metadata.setdefault("ingested_at", ingested_at)
        if source_scope.effective_date:
            metadata.setdefault("effective_date", source_scope.effective_date)

        inherited_fields = (
            "source_type",
            "publisher",
            "approval_status",
            "authority_level",
            "officiality",
            "authority_metadata",
            "publication_time",
            "observed_at",
            "effective_from",
            "effective_to",
            "effective_date",
        )
        for field in inherited_fields:
            value = document_metadata.get(field)
            if value is not None:
                metadata[field] = metadata.get(field, value)
        table.metadata = metadata

    async def _safe_replace_structured_facts(
        self,
        *,
        job: ClaimedIngestionJob,
        result: IngestionEmbeddingResult,
        analyses: Sequence[TableAnalysis],
        template_fingerprint: str | None,
        fingerprint: DocumentFingerprint | None,
    ) -> StructuredFactWriteResult | None:
        """Persist facts after ingestion commit without changing its outcome."""

        store = self._structured_fact_store
        if store is None:
            LOGGER.warning(
                "Structured fact mode is enabled for document %s but no store is configured",
                job.document_id,
            )
            return None
        try:
            batch = build_structured_fact_persistence_batch(
                analyses=analyses,
                tables=result.parsed_document.tables,
                embedded_chunks=result.embedded_chunks,
                template_fingerprint=template_fingerprint,
                prose_claims=_persistable_p3_claims(result.embedded_chunks),
            )
            candidate_hashes = tuple(
                sorted(
                    {
                        str(claim["candidate_identity_hash"])
                        for claim in batch.claims
                        if claim.get("candidate_identity_hash")
                    }
                )
            )
            schema_fingerprints = tuple(
                sorted(
                    {
                        str(snapshot["schema_fingerprint"])
                        for snapshot in batch.table_snapshots
                        if snapshot.get("schema_fingerprint")
                    }
                )
            )
            last_written_relations: tuple[dict[str, object], ...] | None = None
            write_result: StructuredFactWriteResult | None = None
            successful_writes = 0
            write_failures = 0
            while successful_writes < 2:
                candidates: tuple[StructuredClaimCandidate, ...] = ()
                if candidate_hashes or schema_fingerprints:
                    try:
                        candidates = await store.load_claim_candidates(
                            notebook_id=job.notebook_id,
                            document_id=job.document_id,
                            candidate_identity_hashes=candidate_hashes,
                            schema_fingerprints=schema_fingerprints,
                        )
                    except Exception:
                        LOGGER.exception(
                            (
                                "Structured candidate lookup failed for document %s; "
                                "persisting current facts without comparisons"
                            ),
                            job.document_id,
                        )
                relation_payloads = (
                    *build_structured_relation_payloads(
                        analyses=analyses,
                        table_snapshots=batch.table_snapshots,
                        candidates=candidates,
                    ),
                    *build_unified_claim_relation_payloads(
                        current_claims=batch.claims,
                        table_snapshots=batch.table_snapshots,
                        candidates=candidates,
                    ),
                )
                if write_result is not None and relation_payloads == last_written_relations:
                    break
                try:
                    write_result = await store.replace_for_document(
                        job_id=job.id,
                        document_id=job.document_id,
                        extractor_version=TABLE_FACT_EXTRACTOR_VERSION,
                        table_snapshots=batch.table_snapshots,
                        claims=batch.claims,
                        relations=relation_payloads,
                    )
                except Exception:
                    write_failures += 1
                    if write_failures >= 2:
                        raise
                    LOGGER.warning(
                        (
                            "Structured fact replacement failed for document %s; "
                            "reloading candidates before retry"
                        ),
                        job.document_id,
                        exc_info=True,
                    )
                    continue
                successful_writes += 1
                last_written_relations = relation_payloads
            if write_result is not None and isinstance(store, KnowledgeRelationWriter):
                try:
                    p4_relations = aggregate_persisted_claim_relations(
                        owner_id=job.owner_id,
                        notebook_id=job.notebook_id,
                        source_document_id=job.document_id,
                        current_claims=batch.claims,
                        candidates=candidates,
                        relation_payloads=last_written_relations or (),
                        strict_content_hash=(fingerprint.strict_hash if fingerprint else None),
                        normalization_version=(
                            fingerprint.normalization_version if fingerprint else None
                        ),
                    )
                    await store.replace_p4_relations(
                        source_document_id=job.document_id,
                        detector_version=AGGREGATION_POLICY_VERSION,
                        relations=p4_relations,
                    )
                except Exception:
                    LOGGER.exception(
                        (
                            "P4 document relation materialization failed for document %s; "
                            "P3 facts and vector retrieval remain available"
                        ),
                        job.document_id,
                    )
            return write_result
        except Exception:
            LOGGER.exception(
                (
                    "Structured fact persistence failed for document %s; "
                    "vector retrieval remains available"
                ),
                job.document_id,
            )
        return None

    async def _heartbeat(
        self,
        job: ClaimedIngestionJob,
        stop_event: asyncio.Event,
        lease_lost: asyncio.Event,
    ) -> None:
        interval = max(10.0, self._lease_seconds / 3)
        while not stop_event.is_set():
            try:
                await asyncio.wait_for(stop_event.wait(), timeout=interval)
                return
            except TimeoutError:
                pass
            try:
                renewed = await self._repository.renew_lease(
                    job.id,
                    self._worker_id,
                    job.claim_token,
                    self._lease_seconds,
                )
                if not renewed:
                    LOGGER.error("Lost lease for ingestion job %s", job.id)
                    lease_lost.set()
                    return
            except Exception:
                LOGGER.exception("Could not renew lease for ingestion job %s", job.id)
                lease_lost.set()
                return

    async def _safe_find_content_duplicate(
        self,
        job: ClaimedIngestionJob,
        fingerprint: DocumentFingerprint,
    ) -> UUID | None:
        try:
            return await self._repository.find_content_duplicate(job, fingerprint)
        except Exception:
            LOGGER.exception(
                "Knowledge identity lookup failed for document %s; continuing ingestion",
                job.document_id,
            )
            return None

    def _contextual_enrichment_for_job(self, job: ClaimedIngestionJob) -> bool:
        """Keep contextual retrieval behavior fixed to the enqueue-time profile."""
        configured = job.configuration.get("contextual_enrichment_enabled")
        if not isinstance(configured, bool) or not configured:
            return False
        runtime_profile = self._pipeline.context_enrichment_profile
        if runtime_profile is None:
            raise RuntimeError(
                "Queued job enables contextual enrichment but runtime has no LLM enricher"
            )
        mismatched = tuple(
            key for key, value in runtime_profile.items() if job.configuration.get(key) != value
        )
        if mismatched:
            raise RuntimeError(
                "Queued contextual enrichment profile does not match runtime: "
                + ", ".join(mismatched)
            )
        return True

    def _document_metadata_enrichment_for_job(self, job: ClaimedIngestionJob) -> bool:
        """Keep metadata extraction fixed to the durable enqueue-time policy."""
        configured = job.configuration.get("document_metadata_enrichment_enabled")
        if not isinstance(configured, bool) or not configured:
            return False
        runtime_profile = self._pipeline.document_metadata_enrichment_profile
        if runtime_profile is None:
            raise RuntimeError(
                "Queued job enables metadata enrichment but runtime has no LLM enricher"
            )
        mismatched = tuple(
            key for key, value in runtime_profile.items() if job.configuration.get(key) != value
        )
        if mismatched:
            raise RuntimeError(
                "Queued document metadata profile does not match runtime: "
                + ", ".join(mismatched)
            )
        return True

    async def _safe_find_chunk_dedup_candidates(
        self,
        job: ClaimedIngestionJob,
        probes: Sequence[ChunkDedupProbe],
        *,
        candidates_per_probe: int | None = None,
    ) -> tuple[ChunkDedupCandidate, ...]:
        try:
            return await self._repository.find_chunk_dedup_candidates(
                job,
                probes,
                self._pipeline.embedding_provider.model_name,
                candidates_per_probe or self._quality_candidates_per_probe,
            )
        except Exception:
            LOGGER.exception(
                (
                    "Pre-embedding chunk candidate lookup failed for document "
                    "%s; continuing without database reuse"
                ),
                job.document_id,
            )
            return ()

    async def _safe_detect_fused_relations(
        self,
        result: IngestionEmbeddingResult,
        probes: tuple[ChunkDedupProbe, ...],
        preembedding_candidates: tuple[ChunkDedupCandidate, ...],
    ) -> FusedCandidateDetectionResult:
        if self._pipeline.vector_index is None:
            return FusedCandidateDetectionResult((), (), 0, 0)
        try:
            return await asyncio.to_thread(
                detect_fused_document_relation_candidates,
                vector_index=self._pipeline.vector_index,
                chunks=result.embedded_chunks,
                probes=probes,
                preembedding_candidates=preembedding_candidates,
                candidates_per_channel=self._candidate_channel_k,
                final_candidate_limit=self._candidate_final_top_k,
            )
        except Exception:
            LOGGER.exception(
                "Fused chunk candidate detection failed for document %s; continuing ingestion",
                result.source.document_id,
            )
            return FusedCandidateDetectionResult((), (), 0, 0)

    async def _safe_detect_relations(
        self,
        result: IngestionEmbeddingResult,
    ) -> tuple[QualityRelationCandidate, ...]:
        if self._pipeline.vector_index is None:
            return ()
        try:
            return await asyncio.to_thread(
                detect_document_relation_candidates,
                vector_index=self._pipeline.vector_index,
                chunks=result.embedded_chunks,
                max_probe_chunks=self._quality_max_probe_chunks,
                candidates_per_probe=self._quality_candidates_per_probe,
            )
        except Exception:
            LOGGER.exception(
                "Knowledge relation detection failed for document %s; continuing ingestion",
                result.source.document_id,
            )
            return ()

    @staticmethod
    def _ensure_lease(lease_lost: asyncio.Event) -> None:
        if lease_lost.is_set():
            raise IngestionLeaseLostError("Ingestion lease was lost")

    @staticmethod
    def _merge_relation_candidates(
        existing: tuple[QualityRelationCandidate, ...],
        detected: tuple[QualityRelationCandidate, ...],
    ) -> tuple[QualityRelationCandidate, ...]:
        relation_priority = {
            RelationType.CONFLICT_CANDIDATE: 7,
            RelationType.VERSION_CANDIDATE: 6,
            RelationType.TEMPORAL_SERIES: 5,
            RelationType.NEAR_DUPLICATE: 4,
            RelationType.TEMPLATE_VARIANT: 3,
            RelationType.EXACT_CONTENT: 2,
            RelationType.RELATED: 1,
            RelationType.DISTINCT: 0,
        }
        by_target = {candidate.target_document_id: candidate for candidate in existing}
        for candidate in detected:
            previous = by_target.get(candidate.target_document_id)
            if previous is None or (
                relation_priority.get(candidate.relation_type, 0),
                candidate.confidence,
            ) > (
                relation_priority.get(previous.relation_type, 0),
                previous.confidence,
            ):
                by_target[candidate.target_document_id] = candidate
        return tuple(
            sorted(
                by_target.values(),
                key=lambda candidate: candidate.confidence,
                reverse=True,
            )
        )

    @staticmethod
    def _attach_claim_scope(
        result: IngestionEmbeddingResult,
        scope: ClaimScope,
        *,
        structured_fact_mode: StructuredFactMode = "off",
    ) -> IngestionEmbeddingResult:
        scope_metadata = scope.to_metadata()
        enriched_chunks: list[EmbeddedChunk] = []
        for chunk in result.embedded_chunks:
            contexts: list[ScopeTextContext] = []
            if chunk.section_title:
                contexts.append(
                    ScopeTextContext(
                        chunk.section_title,
                        EntityEvidenceSource.SECTION_HEADING,
                        f"chunk:{chunk.id}:section",
                    )
                )
            for key, source in (
                ("parent_section_title", EntityEvidenceSource.PARENT_CONTEXT),
                ("parent_context", EntityEvidenceSource.PARENT_CONTEXT),
            ):
                raw_context = chunk.metadata.get(key)
                if isinstance(raw_context, str) and raw_context.strip():
                    contexts.append(
                        ScopeTextContext(
                            raw_context,
                            source,
                            f"chunk:{chunk.id}:{key}",
                        )
                    )
            entity_scope = resolve_business_context(
                chunk.canonical_text,
                contexts=tuple(contexts),
            )
            p3_metadata: dict[str, object] = {}
            if structured_fact_mode != "off":
                if chunk.metadata.get("table_atomic") or chunk.metadata.get("table_row_group"):
                    p3_metadata = {
                        "p3_claim_extractor_version": CLAIM_EXTRACTOR_VERSION,
                        "p3_structured_claims": [],
                        "p3_claim_warnings": ["delegated_to_table_analyzer"],
                        "p3_claim_mode": structured_fact_mode,
                    }
                else:
                    p3_result = extract_structured_claims(
                        chunk.canonical_text,
                        document_id=chunk.document_id,
                        contexts=tuple(contexts),
                        owner_id=chunk.owner_id,
                        notebook_id=(
                            str(chunk.metadata["notebook_id"])
                            if chunk.metadata.get("notebook_id") is not None
                            else None
                        ),
                        chunk_id=chunk.id,
                        page_number=chunk.page_number,
                        ocr_noise_level=("medium" if result.parsed_document.ocr_used else "none"),
                    )
                    p3_metadata = {
                        "p3_claim_extractor_version": CLAIM_EXTRACTOR_VERSION,
                        "p3_structured_claims": [claim.to_payload() for claim in p3_result.claims],
                        "p3_claim_warnings": list(p3_result.warnings),
                        "p3_claim_mode": structured_fact_mode,
                    }
            enriched_chunks.append(
                replace(
                    chunk,
                    metadata={
                        **chunk.metadata,
                        "claim_scope": scope_metadata,
                        "entity_scope": entity_scope.to_metadata(),
                        **p3_metadata,
                    },
                )
            )
        return replace(
            result,
            embedded_chunks=tuple(enriched_chunks),
        )

    async def _wait_or_stop(self, stop_event: asyncio.Event) -> None:
        with suppress(TimeoutError):
            await asyncio.wait_for(
                stop_event.wait(),
                timeout=self._poll_interval_seconds,
            )

    @staticmethod
    def _verify_download(job: ClaimedIngestionJob, content: bytes) -> None:
        if len(content) != job.size_bytes:
            raise RuntimeError("Stored object size does not match document metadata")
        if job.content_hash and sha256(content).hexdigest() != job.content_hash:
            raise RuntimeError("Stored object checksum does not match document metadata")

    @staticmethod
    def _to_persisted_chunks(
        result: IngestionEmbeddingResult,
    ) -> tuple[PersistedChunk, ...]:
        persisted: list[PersistedChunk] = []
        for position, chunk in enumerate(result.embedded_chunks):
            row_id = uuid5(NAMESPACE_URL, f"chunk:{chunk.id}")
            metadata = dict(chunk.metadata)
            metadata.update(
                {
                    "source_chunk_id": chunk.id,
                    "qdrant_point_id": str(row_id),
                    "document_version": chunk.document_version,
                    "page_number": chunk.page_number,
                    "section_title": chunk.section_title,
                    "checksum": chunk.checksum,
                    "retrieval_metadata": chunk.retrieval_metadata,
                }
            )
            if chunk.canonical_text != chunk.text:
                metadata["canonical_text"] = chunk.canonical_text
            if chunk.provenance_metadata:
                metadata["provenance_metadata"] = chunk.provenance_metadata
            if chunk.authority_metadata:
                metadata["authority_metadata"] = chunk.authority_metadata
            token_count = chunk.token_count
            if token_count <= 0:
                token_count = max(1, len(chunk.text.split()))
            persisted.append(
                PersistedChunk(
                    id=row_id,
                    chunk_index=chunk.chunk_index,
                    content=chunk.text,
                    token_count=token_count,
                    metadata=_json_safe_mapping(metadata),
                    embedding=chunk.embedding,
                    parent=_parent_persistence_payload(chunk.metadata),
                    projection=_retrieval_projection_payload(chunk),
                    document_metadata_assertions=(
                        tuple(
                            _json_safe_mapping(assertion.as_dict())
                            for assertion in getattr(
                                result, "document_metadata_assertions", ()
                            )
                        )
                        if position == 0
                        else ()
                    ),
                    version_artifact=(
                        _version_artifact_payload(result, chunk)
                        if position == 0
                        else None
                    ),
                )
            )
        return tuple(persisted)

    @staticmethod
    def _safe_error(exc: Exception) -> str:
        detail = str(exc).strip()
        if not detail:
            detail = exc.__class__.__name__
        return f"Document ingestion failed: {detail}"[:2000]


def _json_safe_mapping(value: Mapping[str, Any]) -> dict[str, object]:
    normalized = _json_safe(value)
    if not isinstance(normalized, dict):
        raise TypeError("Chunk metadata must normalize to an object")
    return normalized


def _retrieval_metadata_fill_statistics(
    chunks: Sequence[PersistedChunk],
) -> dict[str, dict[str, int | float]]:
    """Return value-free metadata coverage suitable for ingestion telemetry."""

    total = len(chunks)
    statistics: dict[str, dict[str, int | float]] = {}
    for field_name in _KEY_RETRIEVAL_METADATA_FIELDS:
        filled = 0
        for chunk in chunks:
            nested = chunk.metadata.get("retrieval_metadata")
            if isinstance(nested, Mapping) and nested.get(field_name) not in (None, ""):
                filled += 1
        statistics[field_name] = {
            "filled": filled,
            "total": total,
            "rate": round(filled / total, 4) if total else 0.0,
        }
    return statistics


def _persistable_p3_claims(
    chunks: Sequence[EmbeddedChunk],
) -> tuple[StructuredClaim, ...]:
    claims: list[StructuredClaim] = []
    for chunk in chunks:
        raw_claims = chunk.metadata.get("p3_structured_claims", [])
        if not isinstance(raw_claims, list | tuple):
            raise ValueError("p3_structured_claims metadata must be an array")
        for raw_claim in raw_claims:
            claims.append(StructuredClaim.from_payload(raw_claim))
    return tuple(claims)


def _parent_persistence_payload(metadata: Mapping[str, object]) -> dict[str, object] | None:
    parent = metadata.get("parent_context")
    parent_id = str(metadata.get("parent_chunk_id") or "").strip()
    if not parent_id or not isinstance(parent, Mapping):
        return None
    content = str(parent.get("content") or "").strip()
    if not content:
        return None
    persisted_parent_id = str(uuid5(NAMESPACE_URL, f"parent:{parent_id}"))
    return _json_safe_mapping(
        {
            "parent_id": persisted_parent_id,
            "heading": parent.get("section_title"),
            "section_path": parent.get("section_path") or [],
            "content": content,
            "content_summary": None,
            "page_start": parent.get("page_start"),
            "page_end": parent.get("page_end"),
            "source_block_ids": parent.get("source_block_ids") or [],
            "token_count": parent.get("token_count") or len(content.split()),
            "content_hash": parent.get("content_checksum")
            or compute_checksum_text(content),
            "parent_index": metadata.get("parent_section_id"),
        }
    )


def _retrieval_projection_payload(chunk: EmbeddedChunk) -> dict[str, object]:
    retrieval = chunk.retrieval_metadata
    section_path = retrieval.get("section_path")
    if isinstance(section_path, Sequence) and not isinstance(section_path, str | bytes):
        section_path_text = " > ".join(
            str(item).strip() for item in section_path if str(item).strip()
        )
    else:
        section_path_text = str(section_path or "").strip()
    table_header = str(retrieval.get("table_header") or "").strip()
    section_title = str(retrieval.get("section_title") or chunk.section_title or "").strip()
    document_title = str(retrieval.get("title") or "").strip()
    contextual_summary = str(retrieval.get("contextual_summary") or "").strip()
    verified_aliases = retrieval.get("verified_aliases")
    alias_values = (
        [str(item).strip() for item in verified_aliases if str(item).strip()]
        if isinstance(verified_aliases, Sequence)
        and not isinstance(verified_aliases, str | bytes)
        else []
    )
    identity_text = str(retrieval.get("document_number") or "").strip()
    structure_text = " ".join(value for value in (section_title, table_header) if value)
    context_text = " ".join(
        value for value in (section_path_text, document_title, contextual_summary) if value
    )
    raw_parent_id = str(chunk.metadata.get("parent_chunk_id") or "").strip()
    parent_id = str(uuid5(NAMESPACE_URL, f"parent:{raw_parent_id}")) if raw_parent_id else None
    return _json_safe_mapping(
        {
            "projection_version": chunk.retrieval_projection_version,
            "identity_text": identity_text,
            "structure_text": structure_text,
            "content_text": chunk.text,
            "context_text": context_text,
            "alias_text": " ".join(alias_values),
            "embedding_text": chunk.embedding_text or chunk.text,
            "embedding_model": chunk.embedding_model,
            "embedding_dimensions": chunk.vector_size,
            "source_content_hash": chunk.checksum,
            "normalization_version": str(
                chunk.metadata.get("normalization_version") or "unknown"
            ),
            "parent_id": parent_id,
            "parent_child_index": chunk.metadata.get("parent_child_index"),
        }
    )


def _version_artifact_payload(
    result: IngestionEmbeddingResult,
    chunk: EmbeddedChunk,
) -> dict[str, object] | None:
    parsed = getattr(result, "parsed_document", None)
    if parsed is None:
        return None
    document_metadata = getattr(parsed, "document_metadata", {})
    ocr_used = bool(getattr(parsed, "ocr_used", False))
    parser_name = str(getattr(result, "parser_name", "") or "")
    return _json_safe_mapping(
        {
            "parser_name": parser_name,
            "parser_version": str(getattr(result, "parser_version", "") or ""),
            "ocr_engine": (
                str(document_metadata.get("ocr_provider") or parser_name)
                if ocr_used
                else None
            ),
            "ocr_version": str(document_metadata.get("ocr_version") or "") or None,
            "chunker_name": str(chunk.metadata.get("strategy") or ""),
            "chunker_version": str(chunk.metadata.get("strategy_version") or ""),
            "embedding_model": str(getattr(result, "embedding_model", "") or ""),
            "embedding_dimensions": chunk.vector_size,
            "page_count": len(parsed.pages),
            "language": parsed.detected_language,
            "canonical_content_hash": compute_checksum_text(
                parsed.content_markdown or parsed.text
            ),
            "metadata_enrichment_profile": dict(
                getattr(result, "document_metadata_profile", None) or {}
            ),
        }
    )


def _json_safe(value: Any) -> object:
    if value is None or isinstance(value, str | int | float | bool):
        return value
    if isinstance(value, Enum):
        return _json_safe(value.value)
    if isinstance(value, UUID):
        return str(value)
    if isinstance(value, datetime | date):
        return value.isoformat()
    if isinstance(value, Mapping):
        return {str(key): _json_safe(item) for key, item in value.items()}
    if isinstance(value, list | tuple | set | frozenset):
        return [_json_safe(item) for item in value]
    return str(value)


__all__ = ["IngestionWorker", "build_ingestion_profile"]
