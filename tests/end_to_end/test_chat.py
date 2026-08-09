"""End-to-end contract tests for the chat API."""

import json
from collections.abc import AsyncIterator
from uuid import UUID

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api.dependencies.auth import get_current_user
from app.api.dependencies.services import get_chat_service
from app.api.main import create_app
from app.api.schemas.auth import CurrentUser
from app.bootstrap.settings import Settings
from app.chat.application.services import (
    ChatContext,
    ChatServiceError,
    NotebookNotFoundError,
)
from app.chat.domain.models import (
    AnswerCitation,
    AnswerDone,
    AnswerToken,
    ChatEvent,
    ConversationStarted,
)

OWNER_ID = UUID("20000000-0000-0000-0000-000000000002")
NOTEBOOK_ID = UUID("10000000-0000-0000-0000-000000000001")
CONVERSATION_ID = UUID("50000000-0000-0000-0000-000000000005")
MESSAGE_ID = UUID("60000000-0000-0000-0000-000000000006")
DOCUMENT_ID = UUID("30000000-0000-0000-0000-000000000003")


def _default_events() -> list[ChatEvent]:
    return [
        ConversationStarted(conversation_id=CONVERSATION_ID),
        AnswerToken(text="Nhân viên "),
        AnswerToken(text="được nghỉ 12 ngày."),
        AnswerCitation(
            source_id="chunk-a",
            document_id=DOCUMENT_ID,
            document_title="so-tay-nhan-vien.pdf",
            page_number=3,
            section_title="Nghỉ phép",
            page_or_section="Trang 3 · Nghỉ phép",
            document_version=1,
            excerpt="Nhân viên được nghỉ 12 ngày phép mỗi năm.",
            retrieval_score=0.91,
        ),
        AnswerDone(),
    ]


class FakeChatService:
    def __init__(
        self,
        *,
        prepare_error: Exception | None = None,
        events: list[ChatEvent] | None = None,
    ) -> None:
        self._prepare_error = prepare_error
        self._events = events if events is not None else _default_events()
        self.prepare_calls: list[tuple[object, ...]] = []

    async def prepare(
        self,
        *,
        owner_id: UUID,
        notebook_id: UUID,
        conversation_id: UUID | None,
        question: str,
        requested_document_ids: tuple[UUID, ...] | None,
    ) -> ChatContext:
        self.prepare_calls.append(
            (owner_id, notebook_id, conversation_id, question, requested_document_ids)
        )
        if self._prepare_error is not None:
            raise self._prepare_error
        return ChatContext(
            owner_id=owner_id,
            notebook_id=notebook_id,
            conversation_id=conversation_id or CONVERSATION_ID,
            assistant_message_id=MESSAGE_ID,
            question=question,
            history=(),
            allowed_document_ids=(),
            document_titles={},
        )

    async def respond(self, context: ChatContext) -> AsyncIterator[ChatEvent]:
        del context
        for event in self._events:
            yield event


def make_settings() -> Settings:
    return Settings.model_validate(
        {
            "app_env": "test",
            "supabase_url": "https://example.supabase.co",
            "ingestion_worker_enabled": False,
        }
    )


def make_app(service: FakeChatService | None = None) -> FastAPI:
    app = create_app(make_settings())
    app.dependency_overrides[get_current_user] = lambda: CurrentUser(
        id=str(OWNER_ID),
        email="user@example.com",
        role="authenticated",
    )
    app.dependency_overrides[get_chat_service] = lambda: service or FakeChatService()
    return app


def test_chat_returns_full_answer_with_citations() -> None:
    service = FakeChatService()
    with TestClient(make_app(service)) as client:
        response = client.post(
            "/chat",
            json={"question": "Nghỉ phép bao nhiêu ngày?", "notebook_id": str(NOTEBOOK_ID)},
        )

    assert response.status_code == 200
    body = response.json()
    assert body["conversation_id"] == str(CONVERSATION_ID)
    assert body["answer"] == "Nhân viên được nghỉ 12 ngày."
    assert len(body["citations"]) == 1
    assert body["citations"][0]["source_id"] == "chunk-a"
    assert body["citations"][0]["document_title"] == "so-tay-nhan-vien.pdf"
    assert body["citations"][0]["page_number"] == 3
    assert body["citations"][0]["section_title"] == "Nghỉ phép"
    assert body["citations"][0]["page_or_section"] == "Trang 3 · Nghỉ phép"
    assert service.prepare_calls == [
        (OWNER_ID, NOTEBOOK_ID, None, "Nghỉ phép bao nhiêu ngày?", None)
    ]


def test_chat_returns_not_found_for_foreign_notebook() -> None:
    service = FakeChatService(prepare_error=NotebookNotFoundError("Notebook not found"))
    with TestClient(make_app(service)) as client:
        response = client.post(
            "/chat",
            json={"question": "Câu hỏi", "notebook_id": str(NOTEBOOK_ID)},
        )

    assert response.status_code == 404
    assert response.json() == {"detail": "Notebook not found"}


def test_chat_returns_bad_gateway_when_backend_unavailable() -> None:
    service = FakeChatService(prepare_error=ChatServiceError("Chat storage is unavailable"))
    with TestClient(make_app(service)) as client:
        response = client.post(
            "/chat",
            json={"question": "Câu hỏi", "notebook_id": str(NOTEBOOK_ID)},
        )

    assert response.status_code == 502


def test_chat_rejects_unknown_fields() -> None:
    with TestClient(make_app()) as client:
        response = client.post(
            "/chat",
            json={
                "question": "Câu hỏi",
                "notebook_id": str(NOTEBOOK_ID),
                "unexpected": "nope",
            },
        )

    assert response.status_code == 422


def test_chat_stream_emits_sse_events_in_order() -> None:
    with TestClient(make_app()) as client:
        response = client.post(
            "/chat/stream",
            json={"question": "Nghỉ phép bao nhiêu ngày?", "notebook_id": str(NOTEBOOK_ID)},
        )

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/event-stream")

    blocks = [block for block in response.text.split("\n\n") if block.strip()]
    parsed = []
    for block in blocks:
        lines = block.splitlines()
        event_line = next(line for line in lines if line.startswith("event:"))
        data_line = next(line for line in lines if line.startswith("data:"))
        event_type = event_line.split(":", 1)[1].strip()
        data = json.loads(data_line.split(":", 1)[1].strip())
        parsed.append((event_type, data))

    event_types = [event_type for event_type, _ in parsed]
    assert event_types == ["conversation_id", "token", "token", "citation", "done"]
    assert parsed[0][1] == {"conversation_id": str(CONVERSATION_ID)}
    assert parsed[1][1] == {"text": "Nhân viên "}
    assert parsed[3][1]["source_id"] == "chunk-a"
    assert parsed[3][1]["document_title"] == "so-tay-nhan-vien.pdf"
    assert parsed[3][1]["page_number"] == 3
    assert parsed[3][1]["section_title"] == "Nghỉ phép"
