"""Persistence contract for feedback, audit, enterprise search and conversations."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol
from uuid import UUID

from app.governance.domain.models import (
    AnalyticsSummary,
    AnswerFeedback,
    AnswerReport,
    AuditLog,
    ConversationDetail,
    EnterpriseCitation,
    EnterpriseConversation,
    EnterpriseMessage,
    SearchHit,
)


class GovernanceRepositoryError(RuntimeError):
    pass


class GovernanceConflictError(GovernanceRepositoryError):
    pass


class GovernanceAccessDeniedError(GovernanceRepositoryError):
    pass


@dataclass(frozen=True, slots=True)
class NewEnterpriseCitation:
    document_id: UUID
    document_version_id: UUID
    chunk_id: UUID
    quote_text: str
    citation_order: int
    page_number: int | None
    retrieval_score: float | None


class GovernanceRepository(Protocol):
    async def search(
        self, query: str, *, limit: int, filters: dict[str, object]
    ) -> list[SearchHit]: ...

    async def search_dense(
        self,
        query_embedding: list[float],
        *,
        limit: int,
        filters: dict[str, object],
    ) -> list[SearchHit]: ...

    async def resolve_document_number(self, document_number: str) -> list[UUID]: ...

    async def expand_context(
        self,
        chunk_ids: tuple[UUID, ...],
        *,
        sibling_window: int,
        limit: int,
    ) -> list[SearchHit]: ...

    async def create_conversation(self, title: str | None) -> EnterpriseConversation: ...

    async def get_conversation(self, conversation_id: UUID) -> ConversationDetail | None: ...

    async def append_user_message(
        self, conversation_id: UUID, content: str
    ) -> EnterpriseMessage: ...

    async def complete_answer(
        self,
        conversation_id: UUID,
        *,
        content: str,
        answer_status: str,
        model: str | None,
        input_tokens: int | None,
        output_tokens: int | None,
        error_code: str | None,
        trace_id: str | None,
        citations: tuple[NewEnterpriseCitation, ...],
    ) -> tuple[EnterpriseMessage, tuple[EnterpriseCitation, ...]]: ...

    async def submit_feedback(
        self,
        message_id: UUID,
        user_id: UUID,
        *,
        rating: str,
        comment: str | None,
    ) -> AnswerFeedback: ...

    async def submit_report(
        self,
        message_id: UUID,
        user_id: UUID,
        *,
        reason_code: str,
        details: str | None,
    ) -> AnswerReport: ...

    async def list_audit_logs(self, *, limit: int, offset: int) -> tuple[list[AuditLog], int]: ...

    async def analytics_summary(self) -> AnalyticsSummary: ...

    async def list_answer_reports(
        self, *, report_status: str | None, limit: int, offset: int
    ) -> tuple[list[AnswerReport], int]: ...

    async def resolve_answer_report(
        self, report_id: UUID, *, status: str, resolution_note: str
    ) -> AnswerReport | None: ...
