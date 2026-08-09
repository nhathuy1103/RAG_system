"""Request-scoped repository providers."""

from collections.abc import AsyncIterator
from typing import Annotated

import httpx2 as httpx
from fastapi import Depends, HTTPException, status

from app.api.dependencies.auth import get_access_token
from app.bootstrap.settings import Settings, get_settings
from app.chat.adapters.postgrest_repository import PostgrestChatRepository
from app.chat.ports.repositories import ChatRepository
from app.documents.adapters.postgrest_repository import (
    PostgrestDocumentRepository,
)
from app.documents.ports.repositories import DocumentRepository
from app.ingestion.adapters.postgrest_repository import (
    PostgrestIngestionRepository,
)
from app.ingestion.ports.repositories import IngestionRepository
from app.knowledge_quality.adapters.postgrest_repository import (
    PostgrestKnowledgeQualityRepository,
)
from app.knowledge_quality.ports.repositories import KnowledgeQualityRepository
from app.notebooks.adapters.postgrest_repository import (
    PostgrestNotebookRepository,
)
from app.notebooks.ports.repositories import NotebookRepository
from app.structured_facts.adapters.postgrest_repository import (
    PostgrestStructuredFactReviewRepository,
)
from app.structured_facts.ports.repositories import StructuredFactReviewRepository


async def get_notebook_repository(
    access_token: Annotated[str, Depends(get_access_token)],
    settings: Annotated[Settings, Depends(get_settings)],
) -> AsyncIterator[NotebookRepository]:
    """Create an isolated PostgREST client for the current user request."""
    if settings.supabase_rest_url is None or settings.supabase_publishable_key is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Supabase Data API is not configured",
        )

    headers = {
        "apikey": settings.supabase_publishable_key,
        "Authorization": f"Bearer {access_token}",
        "Accept": "application/json",
        "Content-Type": "application/json",
    }
    async with httpx.AsyncClient(
        base_url=settings.supabase_rest_url,
        headers=headers,
        timeout=10.0,
    ) as client:
        yield PostgrestNotebookRepository(client)


async def get_document_repository(
    access_token: Annotated[str, Depends(get_access_token)],
    settings: Annotated[Settings, Depends(get_settings)],
) -> AsyncIterator[DocumentRepository]:
    """Create a user-scoped PostgREST document metadata adapter."""
    if settings.supabase_rest_url is None or settings.supabase_publishable_key is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Supabase Data API is not configured",
        )

    headers = {
        "apikey": settings.supabase_publishable_key,
        "Authorization": f"Bearer {access_token}",
        "Accept": "application/json",
        "Content-Type": "application/json",
    }
    async with httpx.AsyncClient(
        base_url=settings.supabase_rest_url,
        headers=headers,
        timeout=15.0,
    ) as client:
        yield PostgrestDocumentRepository(client)


async def get_ingestion_repository(
    access_token: Annotated[str, Depends(get_access_token)],
    settings: Annotated[Settings, Depends(get_settings)],
) -> AsyncIterator[IngestionRepository]:
    """Create the user-scoped adapter used to enqueue uploaded documents."""
    if settings.supabase_rest_url is None or settings.supabase_publishable_key is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Supabase Data API is not configured",
        )

    headers = {
        "apikey": settings.supabase_publishable_key,
        "Authorization": f"Bearer {access_token}",
        "Accept": "application/json",
        "Content-Type": "application/json",
    }
    async with httpx.AsyncClient(
        base_url=settings.supabase_rest_url,
        headers=headers,
        timeout=15.0,
    ) as client:
        yield PostgrestIngestionRepository(client)


async def get_chat_repository(
    access_token: Annotated[str, Depends(get_access_token)],
    settings: Annotated[Settings, Depends(get_settings)],
) -> AsyncIterator[ChatRepository]:
    """Create a user-scoped adapter for conversations/messages/citations."""
    if settings.supabase_rest_url is None or settings.supabase_publishable_key is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Supabase Data API is not configured",
        )

    headers = {
        "apikey": settings.supabase_publishable_key,
        "Authorization": f"Bearer {access_token}",
        "Accept": "application/json",
        "Content-Type": "application/json",
    }
    async with httpx.AsyncClient(
        base_url=settings.supabase_rest_url,
        headers=headers,
        timeout=15.0,
    ) as client:
        yield PostgrestChatRepository(client)


async def get_knowledge_quality_repository(
    access_token: Annotated[str, Depends(get_access_token)],
    settings: Annotated[Settings, Depends(get_settings)],
) -> AsyncIterator[KnowledgeQualityRepository]:
    """Create a user-scoped adapter for relation review and resolution."""
    if settings.supabase_rest_url is None or settings.supabase_publishable_key is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Supabase Data API is not configured",
        )

    headers = {
        "apikey": settings.supabase_publishable_key,
        "Authorization": f"Bearer {access_token}",
        "Accept": "application/json",
        "Content-Type": "application/json",
    }
    async with httpx.AsyncClient(
        base_url=settings.supabase_rest_url,
        headers=headers,
        timeout=15.0,
    ) as client:
        yield PostgrestKnowledgeQualityRepository(client)


async def get_structured_fact_review_repository(
    access_token: Annotated[str, Depends(get_access_token)],
    settings: Annotated[Settings, Depends(get_settings)],
) -> AsyncIterator[StructuredFactReviewRepository]:
    """Create an authenticated owner-scoped structured review adapter."""
    if settings.supabase_rest_url is None or settings.supabase_publishable_key is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Supabase Data API is not configured",
        )

    headers = {
        "apikey": settings.supabase_publishable_key,
        "Authorization": f"Bearer {access_token}",
        "Accept": "application/json",
        "Content-Type": "application/json",
    }
    async with httpx.AsyncClient(
        base_url=settings.supabase_rest_url,
        headers=headers,
        timeout=15.0,
    ) as client:
        yield PostgrestStructuredFactReviewRepository(client)
