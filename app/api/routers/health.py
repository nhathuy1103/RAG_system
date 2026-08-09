"""Liveness and readiness routes."""

from fastapi import APIRouter

from app.api.schemas.health import HealthResponse

router = APIRouter(prefix="/health", tags=["health"])


@router.get("/live", response_model=HealthResponse)
async def liveness() -> HealthResponse:
    """Confirm that the API process is alive."""
    return HealthResponse(status="ok")


@router.get("/ready", response_model=HealthResponse)
async def readiness() -> HealthResponse:
    """Confirm that the currently configured API surface is ready."""
    return HealthResponse(status="ok")
