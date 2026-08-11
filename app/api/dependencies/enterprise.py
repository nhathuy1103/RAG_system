"""Request-scoped Enterprise API repositories, services and authorization gates."""

from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Annotated
from uuid import UUID

import httpx2 as httpx
from fastapi import Depends, HTTPException, status

from app.api.dependencies.auth import get_access_token, get_current_user
from app.api.dependencies.storage import get_document_object_storage
from app.api.dependencies.telemetry import get_telemetry
from app.api.schemas.auth import CurrentUser
from app.bootstrap.settings import Settings, get_settings
from app.documents.adapters.enterprise_postgrest_repository import (
    PostgrestEnterpriseDocumentRepository,
)
from app.documents.adapters.supabase_source_signer import SupabaseSourceUrlSigner
from app.documents.application.enterprise_services import (
    EnterpriseDocumentService,
    EnterpriseSourceFileService,
)
from app.documents.ports.enterprise_repositories import EnterpriseDocumentRepository
from app.documents.ports.source_signing import SourceUrlSigner
from app.documents.ports.storage import DocumentObjectStorage
from app.generation.adapters.openai_generator import OpenAIAnswerGenerator
from app.generation.ports import AnswerGeneratorPort
from app.governance.adapters.postgrest_repository import PostgrestGovernanceRepository
from app.governance.application.services import EnterpriseQuestionService, GovernanceService
from app.governance.ports.repositories import GovernanceRepository
from app.identity.adapters.postgrest_repository import PostgrestIdentityRepository
from app.identity.adapters.supabase_auth_admin import SupabaseAuthAdminProvisioner
from app.identity.application.services import IdentityService
from app.identity.domain.models import PrincipalContext
from app.identity.ports.repositories import AuthUserProvisioner, IdentityRepository
from app.infrastructure.telemetry import Telemetry
from app.infrastructure.telemetry.openai import create_openai_client
from app.pipeline.bootstrap.settings import Settings as IngestionSettings
from app.pipeline.bootstrap.settings import get_settings as get_ingestion_settings
from app.pipeline.indexing.adapters.embedding_providers import create_embedding_provider
from app.pipeline.indexing.ports.embedding_provider import EmbeddingProvider


async def get_enterprise_postgrest_client(
    access_token: Annotated[str, Depends(get_access_token)],
    settings: Annotated[Settings, Depends(get_settings)],
) -> AsyncIterator[httpx.AsyncClient]:
    if settings.supabase_rest_url is None or settings.supabase_publishable_key is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Supabase Data API is not configured",
        )
    async with httpx.AsyncClient(
        base_url=settings.supabase_rest_url,
        headers={
            "apikey": settings.supabase_publishable_key,
            "Authorization": f"Bearer {access_token}",
            "Accept": "application/json",
            "Content-Type": "application/json",
        },
        timeout=15.0,
    ) as client:
        yield client


def get_identity_repository(
    client: Annotated[httpx.AsyncClient, Depends(get_enterprise_postgrest_client)],
) -> IdentityRepository:
    return PostgrestIdentityRepository(client)


def get_enterprise_document_repository(
    client: Annotated[httpx.AsyncClient, Depends(get_enterprise_postgrest_client)],
) -> EnterpriseDocumentRepository:
    return PostgrestEnterpriseDocumentRepository(client)


def get_governance_repository(
    client: Annotated[httpx.AsyncClient, Depends(get_enterprise_postgrest_client)],
) -> GovernanceRepository:
    return PostgrestGovernanceRepository(client)


async def get_enterprise_answer_commit_repository(
    current_user: Annotated[CurrentUser, Depends(get_current_user)],
    settings: Annotated[Settings, Depends(get_settings)],
) -> AsyncIterator[GovernanceRepository]:
    if settings.supabase_rest_url is None or settings.supabase_service_role_key is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Trusted Enterprise answer persistence is not configured",
        )
    service_key = settings.supabase_service_role_key.get_secret_value().strip()
    if not service_key:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Trusted Enterprise answer persistence is not configured",
        )
    try:
        actor_id = UUID(current_user.id)
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authenticated subject is not a valid user identifier",
        ) from exc
    async with httpx.AsyncClient(
        base_url=settings.supabase_rest_url,
        headers={
            "apikey": service_key,
            "Authorization": f"Bearer {service_key}",
            "Accept": "application/json",
            "Content-Type": "application/json",
        },
        timeout=15.0,
    ) as client:
        yield PostgrestGovernanceRepository(client, answer_actor_id=actor_id)


def get_identity_service(
    repository: Annotated[IdentityRepository, Depends(get_identity_repository)],
) -> IdentityService:
    return IdentityService(repository)


async def get_auth_user_provisioner(
    settings: Annotated[Settings, Depends(get_settings)],
) -> AsyncIterator[AuthUserProvisioner]:
    if settings.supabase_url is None or settings.supabase_service_role_key is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Supabase Auth administration is not configured",
        )
    service_key = settings.supabase_service_role_key.get_secret_value().strip()
    if not service_key:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Supabase Auth administration is not configured",
        )
    async with httpx.AsyncClient(
        base_url=f"{str(settings.supabase_url).rstrip('/')}/auth/v1",
        headers={
            "apikey": service_key,
            "Authorization": f"Bearer {service_key}",
            "Accept": "application/json",
            "Content-Type": "application/json",
        },
        timeout=15.0,
    ) as client:
        yield SupabaseAuthAdminProvisioner(client)


def get_enterprise_document_service(
    repository: Annotated[
        EnterpriseDocumentRepository, Depends(get_enterprise_document_repository)
    ],
) -> EnterpriseDocumentService:
    return EnterpriseDocumentService(repository)


def get_enterprise_source_file_service(
    repository: Annotated[
        EnterpriseDocumentRepository,
        Depends(get_enterprise_document_repository),
    ],
    object_storage: Annotated[
        DocumentObjectStorage,
        Depends(get_document_object_storage),
    ],
) -> EnterpriseSourceFileService:
    return EnterpriseSourceFileService(repository, object_storage)


def get_governance_service(
    repository: Annotated[GovernanceRepository, Depends(get_governance_repository)],
) -> GovernanceService:
    return GovernanceService(repository)


def get_enterprise_answer_generator(
    settings: Annotated[Settings, Depends(get_settings)],
    ingestion_settings: Annotated[IngestionSettings, Depends(get_ingestion_settings)],
    telemetry: Annotated[Telemetry, Depends(get_telemetry)],
) -> AnswerGeneratorPort:
    if not ingestion_settings.openai_api_key:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="OpenAI is not configured for Enterprise knowledge answers",
        )
    client = create_openai_client(
        telemetry=telemetry,
        async_client=True,
        api_key=ingestion_settings.openai_api_key,
        base_url=ingestion_settings.openai_base_url,
        timeout=settings.llm_timeout_seconds,
        max_retries=settings.llm_max_retries,
    )
    return OpenAIAnswerGenerator(
        client=client,
        model=ingestion_settings.openai_chat_model,
        temperature=settings.llm_temperature,
        max_output_tokens=settings.llm_max_output_tokens,
        allow_outside_knowledge=False,
        conflict_annotations_enabled=settings.knowledge_quality_conflict_prompt_enabled,
        telemetry=telemetry,
    )


def get_enterprise_embedding_provider(
    ingestion_settings: Annotated[IngestionSettings, Depends(get_ingestion_settings)],
    telemetry: Annotated[Telemetry, Depends(get_telemetry)],
) -> EmbeddingProvider:
    return create_embedding_provider(
        ingestion_settings.embedding_config,
        telemetry=telemetry,
    )


def get_enterprise_question_service(
    repository: Annotated[GovernanceRepository, Depends(get_governance_repository)],
    answer_repository: Annotated[
        GovernanceRepository,
        Depends(get_enterprise_answer_commit_repository),
    ],
    generator: Annotated[AnswerGeneratorPort, Depends(get_enterprise_answer_generator)],
    embedding_provider: Annotated[
        EmbeddingProvider,
        Depends(get_enterprise_embedding_provider),
    ],
    settings: Annotated[Settings, Depends(get_settings)],
    ingestion_settings: Annotated[IngestionSettings, Depends(get_ingestion_settings)],
    telemetry: Annotated[Telemetry, Depends(get_telemetry)],
) -> EnterpriseQuestionService:
    return EnterpriseQuestionService(
        repository,
        generator,
        answer_repository=answer_repository,
        model_name=ingestion_settings.openai_chat_model,
        retrieval_top_k=settings.retrieval_final_top_k,
        minimum_score=settings.retrieval_min_dense_score,
        embedding_provider=embedding_provider,
        sparse_top_k=settings.retrieval_sparse_top_k,
        dense_top_k=settings.retrieval_dense_top_k,
        rrf_rank_constant=settings.retrieval_rrf_k,
        mmr_lambda=settings.retrieval_mmr_lambda,
        max_chunks_per_document=settings.retrieval_max_chunks_per_document,
        history_limit=settings.chat_history_max_turns,
        telemetry=telemetry,
    )


async def get_source_url_signer(
    access_token: Annotated[str, Depends(get_access_token)],
    settings: Annotated[Settings, Depends(get_settings)],
) -> AsyncIterator[SourceUrlSigner]:
    if settings.supabase_storage_url is None or settings.supabase_publishable_key is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Supabase Storage is not configured",
        )
    async with httpx.AsyncClient(
        base_url=settings.supabase_storage_url,
        headers={
            "apikey": settings.supabase_publishable_key,
            "Authorization": f"Bearer {access_token}",
            "Accept": "application/json",
            "Content-Type": "application/json",
        },
        timeout=15.0,
    ) as client:
        yield SupabaseSourceUrlSigner(client, settings.supabase_storage_url)


async def _require_permissions(
    permission_codes: frozenset[str],
    current_user: CurrentUser,
    identity_service: IdentityService,
) -> PrincipalContext:
    try:
        user_id = UUID(current_user.id)
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Access token subject is not a valid UUID",
        ) from exc
    principal = await identity_service.current_principal(user_id, email=current_user.email)
    if principal.permissions.intersection(permission_codes):
        return principal
    raise HTTPException(
        status_code=status.HTTP_403_FORBIDDEN,
        detail="Required functional permission is missing",
    )


async def require_manage_user(
    current_user: Annotated[CurrentUser, Depends(get_current_user)],
    service: Annotated[IdentityService, Depends(get_identity_service)],
) -> PrincipalContext:
    return await _require_permissions(frozenset({"MANAGE_USER"}), current_user, service)


async def require_ask_knowledge(
    current_user: Annotated[CurrentUser, Depends(get_current_user)],
    service: Annotated[IdentityService, Depends(get_identity_service)],
) -> PrincipalContext:
    return await _require_permissions(frozenset({"ASK_KNOWLEDGE"}), current_user, service)


async def require_manage_role(
    current_user: Annotated[CurrentUser, Depends(get_current_user)],
    service: Annotated[IdentityService, Depends(get_identity_service)],
) -> PrincipalContext:
    return await _require_permissions(frozenset({"MANAGE_ROLE"}), current_user, service)


async def require_manage_group(
    current_user: Annotated[CurrentUser, Depends(get_current_user)],
    service: Annotated[IdentityService, Depends(get_identity_service)],
) -> PrincipalContext:
    return await _require_permissions(frozenset({"MANAGE_GROUP"}), current_user, service)


async def require_manage_department(
    current_user: Annotated[CurrentUser, Depends(get_current_user)],
    service: Annotated[IdentityService, Depends(get_identity_service)],
) -> PrincipalContext:
    return await _require_permissions(frozenset({"MANAGE_DEPARTMENT"}), current_user, service)


async def require_manage_document(
    current_user: Annotated[CurrentUser, Depends(get_current_user)],
    service: Annotated[IdentityService, Depends(get_identity_service)],
) -> PrincipalContext:
    return await _require_permissions(frozenset({"MANAGE_DOCUMENT"}), current_user, service)


async def require_upload_document(
    current_user: Annotated[CurrentUser, Depends(get_current_user)],
    service: Annotated[IdentityService, Depends(get_identity_service)],
) -> PrincipalContext:
    return await _require_permissions(
        frozenset({"UPLOAD_DOCUMENT", "MANAGE_DOCUMENT"}),
        current_user,
        service,
    )


async def require_review_document(
    current_user: Annotated[CurrentUser, Depends(get_current_user)],
    service: Annotated[IdentityService, Depends(get_identity_service)],
) -> PrincipalContext:
    return await _require_permissions(frozenset({"REVIEW_DOCUMENT"}), current_user, service)


async def require_review_workspace(
    current_user: Annotated[CurrentUser, Depends(get_current_user)],
    service: Annotated[IdentityService, Depends(get_identity_service)],
) -> PrincipalContext:
    return await _require_permissions(
        frozenset({"REVIEW_DOCUMENT", "PUBLISH_DOCUMENT", "MANAGE_DOCUMENT"}),
        current_user,
        service,
    )


async def require_publish_document(
    current_user: Annotated[CurrentUser, Depends(get_current_user)],
    service: Annotated[IdentityService, Depends(get_identity_service)],
) -> PrincipalContext:
    return await _require_permissions(frozenset({"PUBLISH_DOCUMENT"}), current_user, service)


async def require_archive_document(
    current_user: Annotated[CurrentUser, Depends(get_current_user)],
    service: Annotated[IdentityService, Depends(get_identity_service)],
) -> PrincipalContext:
    return await _require_permissions(frozenset({"ARCHIVE_DOCUMENT"}), current_user, service)


async def require_manage_access_policy(
    current_user: Annotated[CurrentUser, Depends(get_current_user)],
    service: Annotated[IdentityService, Depends(get_identity_service)],
) -> PrincipalContext:
    return await _require_permissions(frozenset({"MANAGE_ACCESS_POLICY"}), current_user, service)


async def require_governance_access(
    current_user: Annotated[CurrentUser, Depends(get_current_user)],
    service: Annotated[IdentityService, Depends(get_identity_service)],
) -> PrincipalContext:
    """Require read access to governance audit and report data."""

    return await _require_permissions(frozenset({"VIEW_AUDIT"}), current_user, service)


async def require_view_analytics(
    current_user: Annotated[CurrentUser, Depends(get_current_user)],
    service: Annotated[IdentityService, Depends(get_identity_service)],
) -> PrincipalContext:
    """Require access to aggregated Enterprise knowledge analytics."""

    return await _require_permissions(frozenset({"VIEW_ANALYTICS"}), current_user, service)


async def require_manage_report(
    current_user: Annotated[CurrentUser, Depends(get_current_user)],
    service: Annotated[IdentityService, Depends(get_identity_service)],
) -> PrincipalContext:
    """Require permission to investigate or resolve submitted answer reports."""

    return await _require_permissions(frozenset({"MANAGE_REPORT"}), current_user, service)
