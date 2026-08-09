"""Profile routes."""

from __future__ import annotations

import logging
from typing import Annotated

import httpx2 as httpx
from fastapi import APIRouter, Depends, HTTPException, status

from app.api.dependencies.auth import get_access_token, get_current_user
from app.api.schemas.auth import CurrentUser
from app.api.schemas.profile import ProfileResponse, ProfileUpdate
from app.bootstrap.settings import Settings, get_settings

LOGGER = logging.getLogger(__name__)

router = APIRouter(prefix="/profile", tags=["profile"])


def _to_response(row: dict[str, object], current_user: CurrentUser) -> ProfileResponse:
    return ProfileResponse.model_validate({**row, "email": current_user.email})


def _client(settings: Settings, access_token: str) -> httpx.Client:
    if settings.supabase_rest_url is None or settings.supabase_publishable_key is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Supabase Data API is not configured",
        )
    return httpx.Client(
        base_url=settings.supabase_rest_url,
        headers={
            "apikey": settings.supabase_publishable_key,
            "Authorization": f"Bearer {access_token}",
            "Accept": "application/json",
            "Content-Type": "application/json",
        },
        timeout=10.0,
    )


@router.get("", response_model=ProfileResponse)
async def get_profile(
    current_user: Annotated[CurrentUser, Depends(get_current_user)],
    access_token: Annotated[str, Depends(get_access_token)],
    settings: Annotated[Settings, Depends(get_settings)],
) -> ProfileResponse:
    with _client(settings, access_token) as client:
        response = client.get(
            "/profiles",
            params={"id": f"eq.{current_user.id}", "select": "*"},
        )
        if response.status_code >= 400:
            LOGGER.error(
                "GET /profile: PostgREST returned %s: %s",
                response.status_code,
                response.text,
            )
            raise HTTPException(
                status_code=status.HTTP_502_BAD_GATEWAY,
                detail="Profile storage is unavailable",
            )
        rows = response.json()
        if rows:
            return _to_response(rows[0], current_user)

        # Self-heal: create a missing profile row.
        created = client.post(
            "/profiles",
            params={"on_conflict": "id"},
            headers={"Prefer": "resolution=merge-duplicates,return=representation"},
            json={"id": current_user.id},
        )
    if created.status_code >= 400:
        LOGGER.error(
            "GET /profile self-heal insert: PostgREST returned %s: %s",
            created.status_code,
            created.text,
        )
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="Profile storage is unavailable",
        )
    created_rows = created.json()
    if not created_rows:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="Could not create profile",
        )
    return _to_response(created_rows[0], current_user)


@router.patch("", response_model=ProfileResponse)
async def update_profile(
    payload: ProfileUpdate,
    current_user: Annotated[CurrentUser, Depends(get_current_user)],
    access_token: Annotated[str, Depends(get_access_token)],
    settings: Annotated[Settings, Depends(get_settings)],
) -> ProfileResponse:
    changes = payload.model_dump(exclude_unset=True)
    if not changes:
        return await get_profile(current_user, access_token, settings)

    with _client(settings, access_token) as client:
        response = client.patch(
            "/profiles",
            params={"id": f"eq.{current_user.id}"},
            headers={"Prefer": "return=representation"},
            json=changes,
        )
    if response.status_code >= 400:
        LOGGER.error(
            "PATCH /profile: PostgREST returned %s: %s",
            response.status_code,
            response.text,
        )
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="Profile storage is unavailable",
        )
    rows = response.json()
    if not rows:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Profile not found",
        )
    return _to_response(rows[0], current_user)


__all__ = ["router"]
