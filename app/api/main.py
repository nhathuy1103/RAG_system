"""FastAPI application entry point."""

import asyncio
import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.dependencies.telemetry import build_telemetry
from app.api.enterprise_errors import install_enterprise_error_contract, request_id_middleware
from app.api.routers import (
    admin,
    chats,
    debug,
    documents,
    enterprise_documents,
    enterprise_governance,
    enterprise_identity,
    extraction,
    health,
    notebooks,
    profile,
    quality,
    structured_facts,
)
from app.bootstrap.settings import Settings, get_settings
from app.ingestion.application.runtime import run_ingestion_worker

LOGGER = logging.getLogger(__name__)


def create_app(settings: Settings | None = None) -> FastAPI:
    """Create and configure the FastAPI application."""
    resolved_settings = settings or get_settings()
    telemetry = build_telemetry(resolved_settings)

    @asynccontextmanager
    async def lifespan(_app: FastAPI) -> AsyncIterator[None]:
        stop_event = asyncio.Event()
        worker_tasks: list[asyncio.Task[None]] = []
        _app.state.ingestion_worker_enabled = resolved_settings.ingestion_worker_enabled
        _app.state.ingestion_worker_configured = (
            resolved_settings.ingestion_worker_is_configured
        )
        _app.state.ingestion_worker_task = None
        _app.state.ingestion_worker_tasks = ()
        if resolved_settings.ingestion_worker_is_configured:
            worker_tasks = [
                asyncio.create_task(
                    run_ingestion_worker(
                        resolved_settings,
                        stop_event,
                        telemetry=telemetry,
                    ),
                    name=f"document-ingestion-worker-{slot + 1}",
                )
                for slot in range(resolved_settings.ingestion_worker_concurrency)
            ]
            _app.state.ingestion_worker_task = worker_tasks[0]
            _app.state.ingestion_worker_tasks = tuple(worker_tasks)
            await asyncio.sleep(0)
            for worker_task in worker_tasks:
                if worker_task.done():
                    await worker_task
        elif resolved_settings.ingestion_worker_enabled:
            LOGGER.warning(
                "Ingestion worker is enabled but SUPABASE_SERVICE_ROLE_KEY is not configured"
            )
        try:
            yield
        finally:
            if worker_tasks:
                stop_event.set()
                try:
                    results = await asyncio.wait_for(
                        asyncio.gather(*worker_tasks, return_exceptions=True),
                        timeout=10,
                    )
                    for result in results:
                        if isinstance(result, Exception):
                            LOGGER.error(
                                "Ingestion worker stopped unexpectedly",
                                exc_info=result,
                            )
                except TimeoutError:
                    for worker_task in worker_tasks:
                        worker_task.cancel()
                finally:
                    _app.state.ingestion_worker_task = None
                    _app.state.ingestion_worker_tasks = ()
            telemetry.flush()
            telemetry.shutdown()

    app = FastAPI(
        title="RAG Notebook API",
        version="0.1.0",
        lifespan=lifespan,
    )
    app.state.telemetry = telemetry
    app.middleware("http")(request_id_middleware)
    install_enterprise_error_contract(app)

    app.add_middleware(
        CORSMiddleware,
        allow_origins=resolved_settings.cors_origins,
        allow_credentials=False,
        allow_methods=["GET", "POST", "PATCH", "DELETE", "OPTIONS"],
        allow_headers=["Authorization", "Content-Type", "X-Request-ID"],
        expose_headers=["X-Request-ID"],
    )

    def provide_settings() -> Settings:
        return resolved_settings

    app.dependency_overrides[get_settings] = provide_settings
    app.include_router(health.router)
    app.include_router(notebooks.router)
    app.include_router(documents.router)
    app.include_router(extraction.router)
    app.include_router(quality.router)
    app.include_router(structured_facts.router)
    app.include_router(chats.router)
    app.include_router(profile.router)
    app.include_router(admin.router)
    app.include_router(enterprise_identity.router)
    app.include_router(enterprise_documents.router)
    app.include_router(enterprise_governance.router)

    if resolved_settings.is_development:
        app.include_router(debug.router)

    return app


app = create_app()
