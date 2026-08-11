"""Liveness and readiness routes."""

from fastapi import APIRouter, HTTPException, Request, status

from app.api.schemas.health import HealthResponse

router = APIRouter(prefix="/health", tags=["health"])


@router.get("/live", response_model=HealthResponse)
async def liveness() -> HealthResponse:
    """Confirm that the API process is alive."""
    return HealthResponse(status="ok")


@router.get("/ready", response_model=HealthResponse)
async def readiness(request: Request) -> HealthResponse:
    """Fail when the configured ingestion worker cannot accept work.

    Liveness intentionally remains process-only.  Readiness must not report a
    healthy deployment when uploads will remain queued forever because the
    in-process worker is missing or has terminated.
    """

    worker_enabled = bool(
        getattr(request.app.state, "ingestion_worker_enabled", False)
    )
    worker_configured = bool(
        getattr(request.app.state, "ingestion_worker_configured", False)
    )
    worker_tasks = getattr(request.app.state, "ingestion_worker_tasks", None)
    if worker_tasks is None:
        legacy_task = getattr(request.app.state, "ingestion_worker_task", None)
        worker_tasks = (legacy_task,) if legacy_task is not None else ()
    if worker_enabled and (
        not worker_configured
        or not worker_tasks
        or any(worker_task.done() for worker_task in worker_tasks)
    ):
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail={
                "code": "INGESTION_WORKER_NOT_READY",
                "message": "The ingestion worker is not available.",
            },
        )
    return HealthResponse(status="ok")
