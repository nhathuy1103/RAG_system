"""Langfuse telemetry construction and FastAPI dependency."""

from typing import cast

from fastapi import Request

from app.bootstrap.settings import Settings
from app.infrastructure.telemetry import Telemetry, TelemetryConfig


def build_telemetry(settings: Settings) -> Telemetry:
    secret_key = (
        settings.langfuse_secret_key.get_secret_value()
        if settings.langfuse_secret_key is not None
        else None
    )
    return Telemetry(
        TelemetryConfig(
            enabled=settings.langfuse_enabled,
            public_key=settings.langfuse_public_key,
            secret_key=secret_key,
            base_url=str(settings.langfuse_base_url).rstrip("/"),
            environment=settings.langfuse_environment or settings.app_env,
            release=settings.langfuse_release,
            sample_rate=settings.langfuse_sample_rate,
            capture_content=settings.langfuse_capture_content,
        )
    )


def get_telemetry(request: Request) -> Telemetry:
    return cast(Telemetry, request.app.state.telemetry)


__all__ = ["build_telemetry", "get_telemetry"]
