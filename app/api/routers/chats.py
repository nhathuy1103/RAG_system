"""Chat routes."""

from __future__ import annotations

import json
import logging
from collections.abc import AsyncIterator
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.responses import StreamingResponse

from app.api.dependencies.auth import get_current_user
from app.api.dependencies.services import get_chat_service
from app.api.schemas.auth import CurrentUser
from app.api.schemas.chat import ChatRequest, ChatResponse, CitationResponse
from app.chat.application.services import (
    ChatContext,
    ChatService,
    ChatServiceError,
    ConversationNotFoundError,
    NotebookNotFoundError,
)
from app.chat.domain.models import (
    AnswerCitation,
    AnswerDone,
    AnswerFailed,
    AnswerToken,
    ConversationStarted,
)

LOGGER = logging.getLogger(__name__)

router = APIRouter(prefix="/chat", tags=["chat"])


async def _prepare_context(
    request: ChatRequest,
    current_user: CurrentUser,
    service: ChatService,
) -> ChatContext:
    try:
        owner_id = UUID(current_user.id)
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Access token subject is not a valid UUID",
        ) from exc

    try:
        return await service.prepare(
            owner_id=owner_id,
            notebook_id=request.notebook_id,
            conversation_id=request.conversation_id,
            question=request.question,
            requested_document_ids=(
                tuple(request.document_ids) if request.document_ids is not None else None
            ),
        )
    except NotebookNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Notebook not found",
        ) from exc
    except ConversationNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Conversation not found",
        ) from exc
    except ChatServiceError as exc:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="Chat backend is unavailable",
        ) from exc


def _format_sse(event: str, data: dict[str, object]) -> str:
    return f"event: {event}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n"


def _citation_response(citation: AnswerCitation) -> CitationResponse:
    return CitationResponse(
        source_id=citation.source_id,
        document_id=citation.document_id,
        document_title=citation.document_title,
        page_number=citation.page_number,
        section_title=citation.section_title,
        page_or_section=citation.page_or_section,
        document_version=citation.document_version,
        excerpt=citation.excerpt,
        retrieval_score=citation.retrieval_score,
        claim_ids=list(citation.claim_ids),
        table_id=citation.table_id,
        row_ordinal=citation.row_ordinal,
        evidence_group_id=citation.evidence_group_id,
        occurrence_count=citation.occurrence_count,
        independent_source_count=citation.independent_source_count,
        relation_type=citation.relation_type,
        evidence_status=citation.evidence_status,
        authority_level=citation.authority_level,
        source_type=citation.source_type,
        approval_status=citation.approval_status,
        authority_reason=citation.authority_reason,
    )


def _citation_payload(citation: AnswerCitation) -> dict[str, object]:
    return _citation_response(citation).model_dump(mode="json")


@router.post("", response_model=ChatResponse)
async def send_message(
    request: ChatRequest,
    current_user: Annotated[CurrentUser, Depends(get_current_user)],
    service: Annotated[ChatService, Depends(get_chat_service)],
) -> ChatResponse:
    """Answer one chat turn and return the full result (no streaming)."""
    context = await _prepare_context(request, current_user, service)

    answer_parts: list[str] = []
    citations: list[CitationResponse] = []

    async for event in service.respond(context):
        if isinstance(event, AnswerToken):
            answer_parts.append(event.text)
        elif isinstance(event, AnswerCitation):
            citations.append(_citation_response(event))
        elif isinstance(event, AnswerFailed):
            raise HTTPException(
                status_code=status.HTTP_502_BAD_GATEWAY,
                detail=event.message,
            )

    return ChatResponse(
        conversation_id=context.conversation_id,
        answer="".join(answer_parts),
        citations=citations,
    )


@router.post("/stream")
async def stream_message(
    request: ChatRequest,
    current_user: Annotated[CurrentUser, Depends(get_current_user)],
    service: Annotated[ChatService, Depends(get_chat_service)],
) -> StreamingResponse:
    """Answer one chat turn as a server-sent-event stream."""
    context = await _prepare_context(request, current_user, service)

    async def event_source() -> AsyncIterator[str]:
        try:
            async for event in service.respond(context):
                if isinstance(event, ConversationStarted):
                    yield _format_sse(
                        "conversation_id",
                        {"conversation_id": str(event.conversation_id)},
                    )
                elif isinstance(event, AnswerToken):
                    yield _format_sse("token", {"text": event.text})
                elif isinstance(event, AnswerCitation):
                    yield _format_sse("citation", _citation_payload(event))
                elif isinstance(event, AnswerFailed):
                    yield _format_sse("error", {"message": event.message})
                elif isinstance(event, AnswerDone):
                    yield _format_sse("done", {})
        except Exception:
            LOGGER.exception("Unhandled error while streaming chat response")
            yield _format_sse("error", {"message": "Đã xảy ra lỗi hệ thống"})

    return StreamingResponse(event_source(), media_type="text/event-stream")


__all__ = ["router"]
