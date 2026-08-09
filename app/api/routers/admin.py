"""Admin dashboard routes. service_role only, gated by require_admin."""

from __future__ import annotations

from typing import Annotated
from uuid import UUID

import httpx2 as httpx
from fastapi import APIRouter, Depends, HTTPException, Query, status

from app.api.dependencies.auth import require_admin
from app.api.schemas.admin import (
    AdminAuditLogEntry,
    AdminAuditLogResponse,
    AdminAuthEventDay,
    AdminAuthEventsResponse,
    AdminUserCountResponse,
)
from app.api.schemas.auth import CurrentUser
from app.api.schemas.notebooks import NotebookResponse
from app.bootstrap.settings import Settings, get_settings

router = APIRouter(prefix="/admin", tags=["admin"])


def _service_role_client(settings: Settings) -> httpx.Client:
    if settings.supabase_rest_url is None or settings.supabase_service_role_key is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Supabase service-role access is not configured",
        )
    service_key = settings.supabase_service_role_key.get_secret_value()
    return httpx.Client(
        base_url=settings.supabase_rest_url,
        headers={
            "apikey": service_key,
            "Authorization": f"Bearer {service_key}",
            "Accept": "application/json",
            "Content-Type": "application/json",
        },
        timeout=15.0,
    )


@router.get("/stats/users", response_model=AdminUserCountResponse)
async def get_user_count(
    _admin: Annotated[CurrentUser, Depends(require_admin)],
    settings: Annotated[Settings, Depends(get_settings)],
) -> AdminUserCountResponse:
    with _service_role_client(settings) as client:
        response = client.post("/rpc/admin_user_count", json={})
    if response.status_code >= 400:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="Could not read user count",
        )
    return AdminUserCountResponse(total_users=int(response.json()))


@router.get("/stats/auth-events", response_model=AdminAuthEventsResponse)
async def get_auth_events(
    _admin: Annotated[CurrentUser, Depends(require_admin)],
    settings: Annotated[Settings, Depends(get_settings)],
    days: Annotated[int, Query(ge=1, le=365)] = 30,
) -> AdminAuthEventsResponse:
    with _service_role_client(settings) as client:
        response = client.post(
            "/rpc/admin_daily_auth_events",
            json={"p_days": days},
        )
    if response.status_code >= 400:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="Could not read auth events",
        )
    rows = response.json()
    return AdminAuthEventsResponse(
        days=[
            AdminAuthEventDay(
                day=row["day"],
                signups=int(row["signups"]),
                logins=int(row["logins"]),
                logouts=int(row["logouts"]),
            )
            for row in rows
        ]
    )


@router.get("/audit-log", response_model=AdminAuditLogResponse)
async def get_audit_log(
    _admin: Annotated[CurrentUser, Depends(require_admin)],
    settings: Annotated[Settings, Depends(get_settings)],
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
) -> AdminAuditLogResponse:
    with _service_role_client(settings) as client:
        response = client.post(
            "/rpc/admin_recent_auth_events",
            json={"p_limit": limit},
        )
    if response.status_code >= 400:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="Could not read audit log",
        )
    rows = response.json()
    return AdminAuditLogResponse(
        entries=[
            AdminAuditLogEntry(
                created_at=row["created_at"],
                action=row.get("action"),
                email=row.get("email"),
            )
            for row in rows
        ]
    )


@router.get("/users/{user_id}/notebooks", response_model=list[NotebookResponse])
async def get_user_notebooks(
    user_id: UUID,
    _admin: Annotated[CurrentUser, Depends(require_admin)],
    settings: Annotated[Settings, Depends(get_settings)],
) -> list[NotebookResponse]:
    with _service_role_client(settings) as client:
        response = client.get(
            "/notebooks",
            params={
                "owner_id": f"eq.{user_id}",
                "select": "*",
                "order": "updated_at.desc",
            },
        )
    if response.status_code >= 400:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="Notebook storage is unavailable",
        )
    return [NotebookResponse.model_validate(row) for row in response.json()]


__all__ = ["router"]
