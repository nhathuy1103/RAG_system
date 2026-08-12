"""Chat domain models: conversations, messages, and their citations."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from uuid import UUID


@dataclass(frozen=True, slots=True)
class Conversation:
    """A chat thread scoped to one notebook."""

    id: UUID
    owner_id: UUID
    notebook_id: UUID
    title: str
    created_at: datetime
    updated_at: datetime


@dataclass(frozen=True, slots=True)
class Message:
    """One turn (user question or assistant answer) in a conversation."""

    id: UUID
    owner_id: UUID
    notebook_id: UUID
    conversation_id: UUID
    role: str
    content: str
    status: str
    model: str | None
    input_tokens: int | None
    output_tokens: int | None
    error_message: str | None
    created_at: datetime
    updated_at: datetime


@dataclass(frozen=True, slots=True)
class MessageCitation:
    """A persisted, immutable evidence snapshot backing an assistant message."""

    id: UUID
    owner_id: UUID
    notebook_id: UUID
    message_id: UUID
    document_id: UUID
    chunk_id: UUID
    ordinal: int
    quote: str
    retrieval_score: float | None
    created_at: datetime


@dataclass(frozen=True, slots=True)
class NewCitation:
    """A citation row awaiting persistence."""

    document_id: UUID
    chunk_id: UUID
    ordinal: int
    quote: str
    retrieval_score: float | None


@dataclass(frozen=True)
class ConversationStarted:
    """First event of every chat turn: the thread this turn belongs to."""

    conversation_id: UUID


@dataclass(frozen=True)
class AnswerToken:
    """One piece of streamed answer text."""

    text: str


@dataclass(frozen=True)
class AnswerCitation:
    """A citation ready for the wire: enriched with document display info."""

    source_id: str
    document_id: UUID
    document_title: str
    page_number: int | None
    section_title: str | None
    page_or_section: str | None
    document_version: int
    excerpt: str
    retrieval_score: float | None
    claim_ids: tuple[str, ...] = ()
    table_id: str | None = None
    row_ordinal: int | None = None
    evidence_group_id: str | None = None
    occurrence_count: int = 1
    independent_source_count: int = 1
    relation_type: str | None = None
    evidence_status: str | None = None
    authority_level: int | None = None
    source_type: str | None = None
    approval_status: str | None = None
    authority_reason: str | None = None


@dataclass(frozen=True)
class AnswerDone:
    """Terminal success event."""


@dataclass(frozen=True)
class AnswerFailed:
    """Terminal failure event."""

    message: str


ChatEvent = ConversationStarted | AnswerToken | AnswerCitation | AnswerDone | AnswerFailed


__all__ = [
    "AnswerCitation",
    "AnswerDone",
    "AnswerFailed",
    "AnswerToken",
    "ChatEvent",
    "Conversation",
    "ConversationStarted",
    "Message",
    "MessageCitation",
    "NewCitation",
]
