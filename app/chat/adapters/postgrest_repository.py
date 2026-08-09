"""Supabase PostgREST adapter for conversations, messages, and citations."""

from __future__ import annotations

import logging
from collections.abc import Mapping
from datetime import datetime
from uuid import UUID

import httpx2 as httpx

from app.chat.domain.models import Conversation, Message, NewCitation
from app.chat.ports.repositories import ChatRepository, ChatRepositoryError

LOGGER = logging.getLogger(__name__)

CONVERSATION_COLUMNS = "id,owner_id,notebook_id,title,created_at,updated_at"
MESSAGE_COLUMNS = (
    "id,owner_id,notebook_id,conversation_id,role,content,status,model,"
    "input_tokens,output_tokens,error_message,created_at,updated_at"
)


class PostgrestChatRepository(ChatRepository):
    """Persist conversations/messages/citations through a user-scoped client."""

    def __init__(self, client: httpx.AsyncClient) -> None:
        self._client = client

    async def create_conversation(
        self,
        *,
        owner_id: UUID,
        notebook_id: UUID,
        title: str,
    ) -> Conversation:
        try:
            response = await self._client.post(
                "/conversations",
                params={"select": CONVERSATION_COLUMNS},
                headers={"Prefer": "return=representation"},
                json={
                    "owner_id": str(owner_id),
                    "notebook_id": str(notebook_id),
                    "title": title,
                },
            )
            response.raise_for_status()
            payload = response.json()
            if not isinstance(payload, list) or len(payload) != 1:
                raise TypeError("PostgREST create response must contain one row")
            return self._parse_conversation(payload[0])
        except (httpx.HTTPError, OSError, KeyError, TypeError, ValueError) as exc:
            LOGGER.exception("PostgREST conversation creation failed")
            raise ChatRepositoryError("Failed to create conversation") from exc

    async def get_conversation(
        self,
        conversation_id: UUID,
        notebook_id: UUID,
    ) -> Conversation | None:
        try:
            response = await self._client.get(
                "/conversations",
                params={
                    "id": f"eq.{conversation_id}",
                    "notebook_id": f"eq.{notebook_id}",
                    "select": CONVERSATION_COLUMNS,
                    "limit": "1",
                },
            )
            response.raise_for_status()
            payload = response.json()
            if not isinstance(payload, list):
                raise TypeError("PostgREST get response must be an array")
            if not payload:
                return None
            return self._parse_conversation(payload[0])
        except (httpx.HTTPError, OSError, KeyError, TypeError, ValueError) as exc:
            LOGGER.exception("PostgREST conversation lookup failed")
            raise ChatRepositoryError("Failed to look up conversation") from exc

    async def list_recent_user_questions(
        self,
        conversation_id: UUID,
        notebook_id: UUID,
        *,
        limit: int,
    ) -> tuple[str, ...]:
        try:
            response = await self._client.get(
                "/messages",
                params={
                    "conversation_id": f"eq.{conversation_id}",
                    "notebook_id": f"eq.{notebook_id}",
                    "role": "eq.user",
                    "select": "content",
                    "order": "created_at.desc,id.desc",
                    "limit": str(limit),
                },
            )
            response.raise_for_status()
            payload = response.json()
            if not isinstance(payload, list):
                raise TypeError("PostgREST message listing must be an array")
            questions = [str(row["content"]) for row in payload]
            questions.reverse()
            return tuple(questions)
        except (httpx.HTTPError, OSError, KeyError, TypeError, ValueError) as exc:
            LOGGER.exception("PostgREST recent-question listing failed")
            raise ChatRepositoryError("Failed to list recent questions") from exc

    async def insert_user_message(
        self,
        *,
        owner_id: UUID,
        notebook_id: UUID,
        conversation_id: UUID,
        content: str,
    ) -> Message:
        return await self._insert_message(
            owner_id=owner_id,
            notebook_id=notebook_id,
            conversation_id=conversation_id,
            role="user",
            content=content,
            status="completed",
        )

    async def insert_pending_assistant_message(
        self,
        *,
        owner_id: UUID,
        notebook_id: UUID,
        conversation_id: UUID,
    ) -> Message:
        return await self._insert_message(
            owner_id=owner_id,
            notebook_id=notebook_id,
            conversation_id=conversation_id,
            role="assistant",
            content="",
            status="pending",
        )

    async def _insert_message(
        self,
        *,
        owner_id: UUID,
        notebook_id: UUID,
        conversation_id: UUID,
        role: str,
        content: str,
        status: str,
    ) -> Message:
        try:
            response = await self._client.post(
                "/messages",
                params={"select": MESSAGE_COLUMNS},
                headers={"Prefer": "return=representation"},
                json={
                    "owner_id": str(owner_id),
                    "notebook_id": str(notebook_id),
                    "conversation_id": str(conversation_id),
                    "role": role,
                    "content": content,
                    "status": status,
                },
            )
            response.raise_for_status()
            payload = response.json()
            if not isinstance(payload, list) or len(payload) != 1:
                raise TypeError("PostgREST create response must contain one row")
            return self._parse_message(payload[0])
        except (httpx.HTTPError, OSError, KeyError, TypeError, ValueError) as exc:
            LOGGER.exception("PostgREST message creation failed")
            raise ChatRepositoryError("Failed to create message") from exc

    async def complete_assistant_message(
        self,
        message_id: UUID,
        notebook_id: UUID,
        *,
        content: str,
        model: str | None,
        input_tokens: int | None,
        output_tokens: int | None,
    ) -> Message:
        return await self._update_message(
            message_id,
            notebook_id,
            {
                "content": content,
                "status": "completed",
                "model": model,
                "input_tokens": input_tokens,
                "output_tokens": output_tokens,
                "error_message": None,
            },
        )

    async def fail_assistant_message(
        self,
        message_id: UUID,
        notebook_id: UUID,
        *,
        error_message: str,
        content: str | None = None,
    ) -> Message:
        changes: dict[str, object] = {"status": "failed", "error_message": error_message}
        if content is not None:
            changes["content"] = content
        return await self._update_message(message_id, notebook_id, changes)

    async def _update_message(
        self,
        message_id: UUID,
        notebook_id: UUID,
        changes: dict[str, object],
    ) -> Message:
        try:
            response = await self._client.patch(
                "/messages",
                params={
                    "id": f"eq.{message_id}",
                    "notebook_id": f"eq.{notebook_id}",
                    "select": MESSAGE_COLUMNS,
                },
                headers={"Prefer": "return=representation"},
                json=changes,
            )
            response.raise_for_status()
            payload = response.json()
            if not isinstance(payload, list) or len(payload) != 1:
                raise TypeError("PostgREST update response must contain one row")
            return self._parse_message(payload[0])
        except (httpx.HTTPError, OSError, KeyError, TypeError, ValueError) as exc:
            LOGGER.exception("PostgREST message update failed")
            raise ChatRepositoryError("Failed to update message") from exc

    async def insert_citations(
        self,
        *,
        owner_id: UUID,
        notebook_id: UUID,
        message_id: UUID,
        citations: tuple[NewCitation, ...],
    ) -> None:
        if not citations:
            return
        try:
            response = await self._client.post(
                "/message_citations",
                params={"select": "id"},
                headers={"Prefer": "return=representation"},
                json=[
                    {
                        "owner_id": str(owner_id),
                        "notebook_id": str(notebook_id),
                        "message_id": str(message_id),
                        "document_id": str(citation.document_id),
                        "chunk_id": str(citation.chunk_id),
                        "ordinal": citation.ordinal,
                        "quote": citation.quote,
                        "retrieval_score": citation.retrieval_score,
                    }
                    for citation in citations
                ],
            )
            response.raise_for_status()
            payload = response.json()
            if not isinstance(payload, list) or len(payload) != len(citations):
                raise TypeError("PostgREST citation insert must return one row per citation")
        except (httpx.HTTPError, OSError, KeyError, TypeError, ValueError) as exc:
            LOGGER.exception("PostgREST citation insert failed")
            raise ChatRepositoryError("Failed to persist citations") from exc

    @staticmethod
    def _parse_conversation(row: object) -> Conversation:
        if not isinstance(row, Mapping):
            raise TypeError("Conversation row must be an object")
        return Conversation(
            id=UUID(str(row["id"])),
            owner_id=UUID(str(row["owner_id"])),
            notebook_id=UUID(str(row["notebook_id"])),
            title=str(row["title"]),
            created_at=datetime.fromisoformat(str(row["created_at"])),
            updated_at=datetime.fromisoformat(str(row["updated_at"])),
        )

    @staticmethod
    def _parse_message(row: object) -> Message:
        if not isinstance(row, Mapping):
            raise TypeError("Message row must be an object")
        return Message(
            id=UUID(str(row["id"])),
            owner_id=UUID(str(row["owner_id"])),
            notebook_id=UUID(str(row["notebook_id"])),
            conversation_id=UUID(str(row["conversation_id"])),
            role=str(row["role"]),
            content=str(row["content"]),
            status=str(row["status"]),
            model=(str(row["model"]) if row["model"] is not None else None),
            input_tokens=(int(row["input_tokens"]) if row["input_tokens"] is not None else None),
            output_tokens=(int(row["output_tokens"]) if row["output_tokens"] is not None else None),
            error_message=(str(row["error_message"]) if row["error_message"] is not None else None),
            created_at=datetime.fromisoformat(str(row["created_at"])),
            updated_at=datetime.fromisoformat(str(row["updated_at"])),
        )


__all__ = ["PostgrestChatRepository"]
