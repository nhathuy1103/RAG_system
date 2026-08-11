from __future__ import annotations

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api import main as api_main
from app.api.routers import health
from app.bootstrap.settings import Settings


def _health_app(*, worker_enabled: bool, worker_configured: bool) -> FastAPI:
    app = FastAPI()
    app.state.ingestion_worker_enabled = worker_enabled
    app.state.ingestion_worker_configured = worker_configured
    app.state.ingestion_worker_task = None
    app.include_router(health.router)
    return app


def test_readiness_is_ok_when_ingestion_worker_is_intentionally_disabled() -> None:
    with TestClient(
        _health_app(worker_enabled=False, worker_configured=False)
    ) as client:
        response = client.get("/health/ready")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_readiness_fails_when_enabled_worker_is_not_configured() -> None:
    with TestClient(
        _health_app(worker_enabled=True, worker_configured=False)
    ) as client:
        response = client.get("/health/ready")

    assert response.status_code == 503
    assert response.json()["detail"]["code"] == "INGESTION_WORKER_NOT_READY"


def test_app_starts_the_configured_number_of_lease_workers(monkeypatch) -> None:
    started: list[str] = []

    async def fake_worker(settings, stop_event, *, telemetry=None) -> None:
        del settings, telemetry
        started.append("started")
        await stop_event.wait()

    monkeypatch.setattr(api_main, "run_ingestion_worker", fake_worker)
    app = api_main.create_app(
        Settings(
            app_env="test",
            ingestion_worker_enabled=True,
            ingestion_worker_concurrency=3,
            supabase_url="https://example.supabase.co",
            supabase_service_role_key="test-service-role-key",
            langfuse_enabled=False,
        )
    )

    with TestClient(app) as client:
        response = client.get("/health/ready")
        assert len(app.state.ingestion_worker_tasks) == 3
        assert len(started) == 3

    assert response.status_code == 200
    assert app.state.ingestion_worker_tasks == ()


def test_readiness_fails_when_configured_worker_task_is_missing() -> None:
    with TestClient(
        _health_app(worker_enabled=True, worker_configured=True)
    ) as client:
        response = client.get("/health/ready")

    assert response.status_code == 503
    assert response.json()["detail"]["code"] == "INGESTION_WORKER_NOT_READY"
