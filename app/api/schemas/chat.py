"""Chat request and response schemas."""

from __future__ import annotations

from typing import Annotated
from uuid import UUID

from pydantic import BaseModel, ConfigDict, StringConstraints

ChatQuestion = Annotated[
    str,
    StringConstraints(strip_whitespace=True, min_length=1, max_length=4000),
]


class ChatRequest(BaseModel):
    """Payload shared by ``POST /chat`` and ``POST /chat/stream``."""

    model_config = ConfigDict(extra="forbid")

    question: ChatQuestion
    notebook_id: UUID
    document_ids: list[UUID] | None = None
    conversation_id: UUID | None = None


class CitationResponse(BaseModel):
    """One evidence citation backing an assistant answer."""

    source_id: str
    document_id: UUID
    document_title: str
    page_number: int | None
    section_title: str | None
    page_or_section: str | None
    document_version: int
    excerpt: str
    retrieval_score: float | None


class ChatResponse(BaseModel):
    """Full (non-streamed) answer to one chat turn."""

    conversation_id: UUID
    answer: str
    citations: list[CitationResponse]


__all__ = ["ChatRequest", "ChatResponse", "CitationResponse"]
