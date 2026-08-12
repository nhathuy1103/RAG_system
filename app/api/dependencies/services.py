"""Application-service providers."""

from collections.abc import Iterator
from typing import Annotated

import httpx2 as httpx
from fastapi import Depends, HTTPException, status

from app.api.dependencies.auth import get_access_token
from app.api.dependencies.repositories import (
    get_chat_repository,
    get_document_repository,
    get_ingestion_repository,
    get_knowledge_quality_repository,
    get_notebook_repository,
    get_structured_fact_review_repository,
)
from app.api.dependencies.storage import get_document_object_storage
from app.api.dependencies.telemetry import get_telemetry
from app.bootstrap.settings import Settings, get_settings
from app.chat.application.document_scope_planner import DeterministicDocumentScopePlanner
from app.chat.application.services import ChatService
from app.chat.ports.repositories import ChatRepository
from app.documents.application.services import DocumentService
from app.documents.ports.repositories import DocumentRepository
from app.documents.ports.storage import DocumentObjectStorage
from app.generation.adapters.openai_generator import OpenAIAnswerGenerator
from app.generation.application.evidence_context import EvidenceContextPolicy
from app.infrastructure.telemetry import Telemetry
from app.infrastructure.telemetry.openai import create_openai_client
from app.ingestion.application.worker import build_ingestion_profile
from app.ingestion.ports.repositories import IngestionRepository
from app.knowledge_quality.application.services import KnowledgeQualityService
from app.knowledge_quality.ports.repositories import KnowledgeQualityRepository
from app.notebooks.application.services import NotebookService
from app.notebooks.ports.repositories import NotebookRepository
from app.pipeline.bootstrap.composition import build_vector_index
from app.pipeline.bootstrap.settings import Settings as IngestionSettings
from app.pipeline.bootstrap.settings import get_settings as get_ingestion_settings
from app.pipeline.indexing.adapters.embedding_providers import create_embedding_provider
from app.retrieval.adapters.fusion import ReciprocalRankFusion
from app.retrieval.adapters.hybrid_search import HybridRetrievalAdapter
from app.retrieval.adapters.local_adaptive import HeuristicAdaptiveClassifier
from app.retrieval.adapters.local_contextualizer import HeuristicContextualizer
from app.retrieval.adapters.local_reformulation import FallbackQueryReformulator
from app.retrieval.adapters.local_sufficiency import KeywordOverlapSufficiencyChecker
from app.retrieval.adapters.mmr_reranker import MaximalMarginalRelevanceReranker
from app.retrieval.adapters.postgrest_full_text_search import (
    PostgrestFullTextRetrievalAdapter,
)
from app.retrieval.adapters.postgrest_relation_metadata import (
    PostgrestRelationMetadataAdapter,
)
from app.retrieval.adapters.qdrant_dense_search import (
    DenseVectorRetrievalAdapter,
)
from app.retrieval.application.agentic_retrieval import AgenticRetrievalUseCase
from app.retrieval.application.handle_retrieval_request import (
    RetrievalRequestHandler,
)
from app.retrieval.application.metadata_filter_planner import (
    DeterministicMetadataFilterPlanner,
    ProjectAliasRegistry,
)
from app.structured_facts.adapters.postgrest_repository import (
    PostgrestStructuredFactReader,
)
from app.structured_facts.application.review import StructuredFactReviewService
from app.structured_facts.ports.repositories import StructuredFactReviewRepository


def get_notebook_service(
    repository: Annotated[NotebookRepository, Depends(get_notebook_repository)],
) -> NotebookService:
    return NotebookService(repository)


def get_document_service(
    notebook_repository: Annotated[
        NotebookRepository,
        Depends(get_notebook_repository),
    ],
    document_repository: Annotated[
        DocumentRepository,
        Depends(get_document_repository),
    ],
    object_storage: Annotated[
        DocumentObjectStorage,
        Depends(get_document_object_storage),
    ],
    ingestion_repository: Annotated[
        IngestionRepository,
        Depends(get_ingestion_repository),
    ],
    ingestion_settings: Annotated[
        IngestionSettings,
        Depends(get_ingestion_settings),
    ],
    settings: Annotated[Settings, Depends(get_settings)],
) -> DocumentService:
    return DocumentService(
        notebook_repository,
        document_repository,
        object_storage,
        ingestion_repository,
        build_ingestion_profile(
            ingestion_settings,
            knowledge_quality_mode=settings.knowledge_quality_mode,
            structured_fact_mode=settings.structured_fact_mode,
        ),
    )


def get_knowledge_quality_service(
    notebook_repository: Annotated[
        NotebookRepository,
        Depends(get_notebook_repository),
    ],
    quality_repository: Annotated[
        KnowledgeQualityRepository,
        Depends(get_knowledge_quality_repository),
    ],
    object_storage: Annotated[
        DocumentObjectStorage,
        Depends(get_document_object_storage),
    ],
) -> KnowledgeQualityService:
    return KnowledgeQualityService(
        notebook_repository,
        quality_repository,
        object_storage,
    )


def get_structured_fact_review_service(
    notebook_repository: Annotated[
        NotebookRepository,
        Depends(get_notebook_repository),
    ],
    review_repository: Annotated[
        StructuredFactReviewRepository,
        Depends(get_structured_fact_review_repository),
    ],
) -> StructuredFactReviewService:
    return StructuredFactReviewService(notebook_repository, review_repository)


def get_chat_service(
    notebook_repository: Annotated[NotebookRepository, Depends(get_notebook_repository)],
    document_repository: Annotated[DocumentRepository, Depends(get_document_repository)],
    chat_repository: Annotated[ChatRepository, Depends(get_chat_repository)],
    quality_repository: Annotated[
        KnowledgeQualityRepository,
        Depends(get_knowledge_quality_repository),
    ],
    access_token: Annotated[str, Depends(get_access_token)],
    settings: Annotated[Settings, Depends(get_settings)],
    ingestion_settings: Annotated[IngestionSettings, Depends(get_ingestion_settings)],
    telemetry: Annotated[Telemetry, Depends(get_telemetry)],
) -> Iterator[ChatService]:
    if settings.supabase_rest_url is None or settings.supabase_publishable_key is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Supabase Data API is not configured",
        )
    if not ingestion_settings.openai_api_key:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="OpenAI is not configured for chat",
        )

    chunk_headers = {
        "apikey": settings.supabase_publishable_key,
        "Authorization": f"Bearer {access_token}",
        "Accept": "application/json",
        "Content-Type": "application/json",
    }
    with httpx.Client(
        base_url=settings.supabase_rest_url,
        headers=chunk_headers,
        timeout=15.0,
    ) as chunks_client:
        embedding_provider = create_embedding_provider(
            ingestion_settings.embedding_config,
            telemetry=telemetry,
        )
        vector_index = build_vector_index(
            ingestion_settings,
            postgrest_base_url=settings.supabase_rest_url,
            postgrest_headers=chunk_headers,
        )

        hybrid_retrieval = HybridRetrievalAdapter(
            sparse=PostgrestFullTextRetrievalAdapter(
                client=chunks_client,
                telemetry=telemetry,
            ),
            dense=DenseVectorRetrievalAdapter(
                vector_index=vector_index,
                embedding_provider=embedding_provider,
                telemetry=telemetry,
            ),
            fusion=ReciprocalRankFusion(rank_constant=settings.retrieval_rrf_k),
            sparse_candidate_k=settings.retrieval_sparse_top_k,
            dense_candidate_k=settings.retrieval_dense_top_k,
            telemetry=telemetry,
        )
        agentic_retrieval = AgenticRetrievalUseCase(
            retrieval_port=hybrid_retrieval,
            sufficiency_checker=KeywordOverlapSufficiencyChecker(),
            reformulator=FallbackQueryReformulator(),
            reranker=MaximalMarginalRelevanceReranker(
                lambda_param=settings.retrieval_mmr_lambda,
                collapse_exact_duplicates=(settings.knowledge_quality_mode == "on"),
            ),
            score_threshold=settings.retrieval_min_dense_score,
            rerank_pool_size=max(
                settings.retrieval_dense_top_k,
                settings.retrieval_sparse_top_k,
            ),
            max_chunks_per_document=(settings.retrieval_max_chunks_per_document),
            knowledge_quality_mode=settings.knowledge_quality_mode,
            relation_metadata_port=PostgrestRelationMetadataAdapter(chunks_client),
            telemetry=telemetry,
        )
        retrieval_handler = RetrievalRequestHandler(
            contextualizer=HeuristicContextualizer(),
            adaptive_classifier=HeuristicAdaptiveClassifier(),
            agentic_retrieval=agentic_retrieval,
            metadata_filter_planner=(
                DeterministicMetadataFilterPlanner(
                    project_registry=ProjectAliasRegistry.from_json_file(
                        settings.retrieval_project_registry_path
                    ),
                    allowed_fields=settings.retrieval_structured_filter_field_set,
                )
                if settings.retrieval_structured_filters_enabled
                else None
            ),
            telemetry=telemetry,
        )

        openai_client = create_openai_client(
            telemetry=telemetry,
            async_client=True,
            api_key=ingestion_settings.openai_api_key,
            base_url=ingestion_settings.openai_base_url,
            timeout=settings.llm_timeout_seconds,
            max_retries=settings.llm_max_retries,
        )
        answer_generator = OpenAIAnswerGenerator(
            client=openai_client,
            model=ingestion_settings.openai_chat_model,
            temperature=settings.llm_temperature,
            max_output_tokens=settings.llm_max_output_tokens,
            allow_outside_knowledge=settings.generation_allow_outside_knowledge,
            conflict_annotations_enabled=(
                settings.knowledge_quality_conflict_prompt_enabled
                and (
                    settings.knowledge_quality_mode == "on" or settings.structured_fact_mode == "on"
                )
            ),
            telemetry=telemetry,
        )

        yield ChatService(
            notebook_repository=notebook_repository,
            document_repository=document_repository,
            chat_repository=chat_repository,
            retrieval_handler=retrieval_handler,
            answer_generator=answer_generator,
            chat_model_name=ingestion_settings.openai_chat_model,
            quality_repository=quality_repository,
            knowledge_quality_mode=settings.knowledge_quality_mode,
            structured_fact_mode=settings.structured_fact_mode,
            structured_fact_reader=PostgrestStructuredFactReader(chunks_client),
            retrieval_top_k=settings.retrieval_final_top_k,
            history_limit=settings.chat_history_max_turns,
            telemetry=telemetry,
            document_scope_planner=(
                DeterministicDocumentScopePlanner()
                if settings.retrieval_document_scope_planner_mode != "off"
                else None
            ),
            document_scope_planner_mode=settings.retrieval_document_scope_planner_mode,
            p5_mode=settings.rag_p5_mode,
            p5_context_policy=EvidenceContextPolicy(
                max_evidence_items=settings.rag_p5_context_max_items,
                max_characters=settings.rag_p5_context_max_characters,
                characters_per_token=settings.rag_p5_characters_per_token,
                max_near_duplicate_representatives=(settings.rag_p5_near_duplicate_representatives),
            ),
        )
