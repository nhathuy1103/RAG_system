"""Governance, enterprise search and notebook-free conversation models."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from uuid import UUID


@dataclass(frozen=True, slots=True)
class SearchHit:
    chunk_id: UUID
    document_id: UUID
    document_version_id: UUID
    title: str
    content: str
    score: float
    page_start: int | None = None
    page_end: int | None = None
    section_path: str | None = None
    metadata: dict[str, object] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class EnterpriseConversation:
    id: UUID
    user_id: UUID
    title: str | None
    created_at: datetime
    updated_at: datetime


@dataclass(frozen=True, slots=True)
class EnterpriseCitation:
    id: UUID
    answer_message_id: UUID
    document_id: UUID
    document_version_id: UUID
    chunk_id: UUID
    quote_text: str
    citation_order: int
    page_number: int | None = None
    retrieval_score: float | None = None
    document_title: str | None = None
    section_path: str | None = None


@dataclass(frozen=True, slots=True)
class EnterpriseMessage:
    id: UUID
    conversation_id: UUID
    role: str
    content: str
    created_at: datetime
    answer_status: str | None = None
    citations: tuple[EnterpriseCitation, ...] = ()


@dataclass(frozen=True, slots=True)
class AskQuestionResult:
    user_message: EnterpriseMessage
    assistant_message: EnterpriseMessage
    citations: tuple[EnterpriseCitation, ...]
    retrieval_strategy: str
    evidence_count: int
    trace_id: str | None = None


@dataclass(frozen=True, slots=True)
class ConversationDetail:
    conversation: EnterpriseConversation
    messages: tuple[EnterpriseMessage, ...] = ()


@dataclass(frozen=True, slots=True)
class AnswerFeedback:
    id: UUID
    message_id: UUID
    user_id: UUID
    rating: str
    comment: str | None
    created_at: datetime
    updated_at: datetime | None = None


@dataclass(frozen=True, slots=True)
class AnswerReport:
    id: UUID
    message_id: UUID
    reporter_user_id: UUID
    reason_code: str
    details: str | None
    status: str
    created_at: datetime
    resolution_note: str | None = None
    resolved_by: UUID | None = None
    resolved_at: datetime | None = None


@dataclass(frozen=True, slots=True)
class AuditLog:
    id: UUID
    actor_user_id: UUID | None
    action: str
    entity_type: str
    entity_id: UUID | None
    metadata: dict[str, object]
    created_at: datetime
    request_id: str | None = None
    trace_id: str | None = None


@dataclass(frozen=True, slots=True)
class AnalyticsSummary:
    published_documents: int = 0
    draft_documents: int = 0
    archived_documents: int = 0
    pending_jobs: int = 0
    running_jobs: int = 0
    failed_jobs: int = 0
    open_reports: int = 0
    feedback_up: int = 0
    feedback_down: int = 0
    no_answer_rate: float | None = None
