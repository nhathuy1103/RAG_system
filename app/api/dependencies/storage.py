"""Request-scoped object-storage providers."""

from collections.abc import AsyncIterator
from typing import Annotated

import httpx2 as httpx
from fastapi import Depends, HTTPException, status

from app.api.dependencies.auth import get_access_token
from app.bootstrap.settings import Settings, get_settings
from app.documents.adapters.supabase_storage import SupabaseDocumentStorage
from app.documents.ports.storage import DocumentObjectStorage


async def get_document_object_storage(
    access_token: Annotated[str, Depends(get_access_token)],
    settings: Annotated[Settings, Depends(get_settings)],
) -> AsyncIterator[DocumentObjectStorage]:
    """Create a user-scoped Supabase Storage adapter."""
    if settings.supabase_storage_url is None or settings.supabase_publishable_key is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Supabase Storage is not configured",
        )

    headers = {
        "apikey": settings.supabase_publishable_key,
        "Authorization": f"Bearer {access_token}",
        "Accept": "application/json",
    }
    async with httpx.AsyncClient(
        base_url=settings.supabase_storage_url,
        headers=headers,
        timeout=30.0,
    ) as client:
        yield SupabaseDocumentStorage(client)
