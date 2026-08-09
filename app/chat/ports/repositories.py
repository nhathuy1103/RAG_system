"""Chat persistence contracts."""

from __future__ import annotations

from typing import Protocol
from uuid import UUID

from app.chat.domain.models import Conversation, Message, NewCitation


class ChatRepositoryError(RuntimeError):
    """Raised when chat persistence cannot complete safely."""


class ChatRepository(Protocol):
    """Persistence operations required by the chat use case."""

    async def create_conversation(
        self,
        *,
        owner_id: UUID,
        notebook_id: UUID,
        title: str,
    ) -> Conversation: ...

    async def get_conversation(
        self,
        conversation_id: UUID,
        notebook_id: UUID,
    ) -> Conversation | None: ...

    async def list_recent_user_questions(
        self,
        conversation_id: UUID,
        notebook_id: UUID,
        *,
        limit: int,
    ) -> tuple[str, ...]: ...

    async def insert_user_message(
        self,
        *,
        owner_id: UUID,
        notebook_id: UUID,
        conversation_id: UUID,
        content: str,
    ) -> Message: ...

    async def insert_pending_assistant_message(
        self,
        *,
        owner_id: UUID,
        notebook_id: UUID,
        conversation_id: UUID,
    ) -> Message: ...

    async def complete_assistant_message(
        self,
        message_id: UUID,
        notebook_id: UUID,
        *,
        content: str,
        model: str | None,
        input_tokens: int | None,
        output_tokens: int | None,
    ) -> Message: ...

    async def fail_assistant_message(
        self,
        message_id: UUID,
        notebook_id: UUID,
        *,
        error_message: str,
        content: str | None = None,
    ) -> Message: ...

    async def insert_citations(
        self,
        *,
        owner_id: UUID,
        notebook_id: UUID,
        message_id: UUID,
        citations: tuple[NewCitation, ...],
    ) -> None: ...


__all__ = ["ChatRepository", "ChatRepositoryError"]
