"""Application-lifetime construction for the in-process ingestion worker."""

from __future__ import annotations

import asyncio
import logging

import httpx2 as httpx

from app.bootstrap.settings import Settings as ApiSettings
from app.documents.adapters.supabase_storage import SupabaseDocumentStorage
from app.infrastructure.telemetry import Telemetry
from app.ingestion.adapters.postgrest_repository import (
    PostgrestIngestionRepository,
)
from app.ingestion.application.worker import (
    IngestionWorker,
    build_ingestion_profile,
)
from app.pipeline.bootstrap.composition import build_ingestion_embedding_pipeline
from app.pipeline.bootstrap.settings import get_settings as get_ingestion_settings
from app.structured_facts.adapters.postgrest_repository import (
    PostgrestStructuredFactRepository,
)

LOGGER = logging.getLogger(__name__)


async def run_ingestion_worker(
    settings: ApiSettings,
    stop_event: asyncio.Event,
    *,
    telemetry: Telemetry | None = None,
) -> None:
    """Run a service-role worker until the FastAPI lifespan asks it to stop."""
    if (
        settings.supabase_rest_url is None
        or settings.supabase_storage_url is None
        or settings.supabase_service_role_key is None
    ):
        raise RuntimeError("Supabase service-role worker is not configured")

    service_key = settings.supabase_service_role_key.get_secret_value()
    headers = {
        "apikey": service_key,
        "Authorization": f"Bearer {service_key}",
        "Accept": "application/json",
    }
    ingestion_settings = get_ingestion_settings()
    build_ingestion_profile(ingestion_settings)
    # warning level - no logging.basicConfig here, INFO would be swallowed.
    LOGGER.warning(
        (
            "Ingestion worker starting with VECTOR_STORE_BACKEND=%s, "
            "CHUNKING_STRATEGY=%s, CONTEXTUAL_ENRICHMENT_ENABLED=%s, "
            "KNOWLEDGE_QUALITY_MODE=%s, CANDIDATE_GENERATION_MODE=%s, "
            "STRUCTURED_FACT_MODE=%s"
        ),
        ingestion_settings.vector_store_backend,
        ingestion_settings.chunking_strategy,
        ingestion_settings.contextual_enrichment_enabled,
        settings.knowledge_quality_mode,
        settings.knowledge_candidate_generation_mode,
        settings.structured_fact_mode,
    )
    pipeline = build_ingestion_embedding_pipeline(
        ingestion_settings,
        telemetry=telemetry,
        postgrest_base_url=settings.supabase_rest_url,
        postgrest_headers=headers,
    )

    async with (
        httpx.AsyncClient(
            base_url=settings.supabase_rest_url,
            headers={**headers, "Content-Type": "application/json"},
            timeout=30.0,
        ) as rest_client,
        httpx.AsyncClient(
            base_url=settings.supabase_storage_url,
            headers=headers,
            timeout=60.0,
        ) as storage_client,
    ):
        worker = IngestionWorker(
            repository=PostgrestIngestionRepository(
                rest_client,
                enterprise_queue_enabled=True,
            ),
            structured_fact_store=PostgrestStructuredFactRepository(rest_client),
            object_storage=SupabaseDocumentStorage(storage_client),
            pipeline=pipeline,
            poll_interval_seconds=settings.ingestion_worker_poll_seconds,
            lease_seconds=settings.ingestion_worker_lease_seconds,
            knowledge_quality_mode=settings.knowledge_quality_mode,
            structured_fact_mode=settings.structured_fact_mode,
            quality_max_probe_chunks=settings.knowledge_quality_max_probe_chunks,
            quality_candidates_per_probe=settings.knowledge_quality_candidates_per_probe,
            candidate_generation_mode=settings.knowledge_candidate_generation_mode,
            candidate_channel_k=settings.knowledge_candidate_channel_k,
            candidate_final_top_k=settings.knowledge_candidate_final_top_k,
            telemetry=telemetry,
        )
        await worker.run_forever(stop_event)


__all__ = ["run_ingestion_worker"]
