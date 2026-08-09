"""PostgREST adapter for enterprise search, conversations and governance."""

from __future__ import annotations

import logging
from collections.abc import Mapping
from datetime import datetime
from uuid import UUID

import httpx2 as httpx

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
from app.governance.ports.repositories import (
    GovernanceAccessDeniedError,
    GovernanceConflictError,
    GovernanceRepository,
    GovernanceRepositoryError,
    NewEnterpriseCitation,
)

LOGGER = logging.getLogger(__name__)


class PostgrestGovernanceRepository(GovernanceRepository):
    def __init__(
        self,
        client: httpx.AsyncClient,
        *,
        answer_actor_id: UUID | None = None,
    ) -> None:
        self._client = client
        self._answer_actor_id = answer_actor_id

    async def search(
        self, query: str, *, limit: int, filters: dict[str, object]
    ) -> list[SearchHit]:
        payload = await self._rpc(
            "search_enterprise_knowledge",
            {"p_query": query, "p_limit": limit, "p_filters": filters},
        )
        return [self._parse_search_hit(row) for row in self._rows(payload, "search")]

    async def search_dense(
        self,
        query_embedding: list[float],
        *,
        limit: int,
        filters: dict[str, object],
    ) -> list[SearchHit]:
        payload = await self._rpc(
            "match_enterprise_document_chunks",
            {
                "p_query_embedding": query_embedding,
                "p_limit": limit,
                "p_filters": filters,
            },
        )
        return [
            self._parse_search_hit(row)
            for row in self._rows(payload, "dense enterprise search")
        ]

    async def create_conversation(self, title: str | None) -> EnterpriseConversation:
        payload = await self._rpc("create_enterprise_conversation", {"p_title": title})
        return self._parse_conversation(self._one(payload, "conversation creation"))

    async def get_conversation(self, conversation_id: UUID) -> ConversationDetail | None:
        payload = await self._rpc(
            "get_enterprise_conversation", {"p_conversation_id": str(conversation_id)}
        )
        if payload is None or payload == []:
            return None
        row = self._one(payload, "conversation detail")
        conversation_value = row.get("conversation", row)
        if not isinstance(conversation_value, Mapping):
            raise GovernanceRepositoryError("Invalid conversation detail response")
        messages_value = row.get("messages", [])
        messages = (
            tuple(
                self._parse_message(message)
                for message in messages_value
                if isinstance(message, Mapping)
            )
            if isinstance(messages_value, list)
            else ()
        )
        return ConversationDetail(
            conversation=self._parse_conversation(conversation_value), messages=messages
        )

    async def append_user_message(self, conversation_id: UUID, content: str) -> EnterpriseMessage:
        payload = await self._rpc(
            "append_enterprise_message",
            {
                "p_conversation_id": str(conversation_id),
                "p_role": "USER",
                "p_content": content,
            },
        )
        return self._parse_message(self._one(payload, "message append"))

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
    ) -> tuple[EnterpriseMessage, tuple[EnterpriseCitation, ...]]:
        if self._answer_actor_id is None:
            raise GovernanceAccessDeniedError(
                "A trusted answer-commit client is required"
            )
        payload = await self._rpc(
            "complete_enterprise_answer",
            {
                "p_actor_user_id": str(self._answer_actor_id),
                "p_conversation_id": str(conversation_id),
                "p_content": content,
                "p_answer_status": answer_status,
                "p_model": model,
                "p_input_tokens": input_tokens,
                "p_output_tokens": output_tokens,
                "p_error_code": error_code,
                "p_trace_id": trace_id,
                "p_citations": [
                    {
                        "document_id": str(item.document_id),
                        "document_version_id": str(item.document_version_id),
                        "chunk_id": str(item.chunk_id),
                        "quote_text": item.quote_text,
                        "citation_order": item.citation_order,
                        "page_number": item.page_number,
                        "retrieval_score": item.retrieval_score,
                    }
                    for item in citations
                ],
            },
        )
        row = self._one(payload, "answer completion")
        message_value = row.get("message")
        citations_value = row.get("citations", [])
        if not isinstance(message_value, Mapping) or not isinstance(citations_value, list):
            raise GovernanceRepositoryError("Invalid answer completion response")
        return self._parse_message(message_value), tuple(
            self._parse_citation(item)
            for item in citations_value
            if isinstance(item, Mapping)
        )

    async def submit_feedback(
        self,
        message_id: UUID,
        user_id: UUID,
        *,
        rating: str,
        comment: str | None,
    ) -> AnswerFeedback:
        response = await self._request(
            "POST",
            "/answer_feedback",
            params={"on_conflict": "message_id,user_id", "select": "*"},
            headers={"Prefer": "resolution=merge-duplicates,return=representation"},
            json={
                "message_id": str(message_id),
                "user_id": str(user_id),
                "rating": rating,
                "comment": comment,
            },
        )
        return self._parse_feedback(self._one(response.json(), "feedback submission"))

    async def submit_report(
        self,
        message_id: UUID,
        user_id: UUID,
        *,
        reason_code: str,
        details: str | None,
    ) -> AnswerReport:
        response = await self._request(
            "POST",
            "/answer_reports",
            params={"select": "*"},
            headers={"Prefer": "return=representation"},
            json={
                "message_id": str(message_id),
                "reporter_user_id": str(user_id),
                "reason_code": reason_code,
                "details": details,
            },
        )
        return self._parse_report(self._one(response.json(), "answer report submission"))

    async def list_audit_logs(self, *, limit: int, offset: int) -> tuple[list[AuditLog], int]:
        response = await self._request(
            "GET",
            "/audit_logs",
            params={
                "select": "*",
                "order": "created_at.desc,id.desc",
                "limit": str(limit),
                "offset": str(offset),
            },
            headers={"Prefer": "count=exact"},
        )
        rows = self._rows(response.json(), "audit log list")
        return [self._parse_audit(row) for row in rows], self._count(
            response.headers.get("content-range"), len(rows)
        )

    async def analytics_summary(self) -> AnalyticsSummary:
        payload = await self._rpc("enterprise_analytics_summary", {})
        row = self._one(payload, "analytics summary")
        return AnalyticsSummary(
            published_documents=int(str(row.get("published_documents", 0))),
            draft_documents=int(str(row.get("draft_documents", 0))),
            archived_documents=int(str(row.get("archived_documents", 0))),
            pending_jobs=int(str(row.get("pending_jobs", 0))),
            running_jobs=int(str(row.get("running_jobs", 0))),
            failed_jobs=int(str(row.get("failed_jobs", 0))),
            open_reports=int(str(row.get("open_reports", 0))),
            feedback_up=int(str(row.get("feedback_up", 0))),
            feedback_down=int(str(row.get("feedback_down", 0))),
            no_answer_rate=(
                float(str(row["no_answer_rate"])) if row.get("no_answer_rate") is not None else None
            ),
        )

    async def list_answer_reports(
        self, *, report_status: str | None, limit: int, offset: int
    ) -> tuple[list[AnswerReport], int]:
        params = {
            "select": "*",
            "order": "created_at.desc,id.desc",
            "limit": str(limit),
            "offset": str(offset),
        }
        if report_status is not None:
            params["status"] = f"eq.{report_status}"
        response = await self._request(
            "GET", "/answer_reports", params=params, headers={"Prefer": "count=exact"}
        )
        rows = self._rows(response.json(), "answer report list")
        return [self._parse_report(row) for row in rows], self._count(
            response.headers.get("content-range"), len(rows)
        )

    async def resolve_answer_report(
        self, report_id: UUID, *, status: str, resolution_note: str
    ) -> AnswerReport | None:
        response = await self._request(
            "PATCH",
            "/answer_reports",
            params={"id": f"eq.{report_id}", "select": "*"},
            headers={"Prefer": "return=representation"},
            json={"status": status, "resolution_note": resolution_note},
        )
        rows = self._rows(response.json(), "answer report resolution")
        return self._parse_report(rows[0]) if rows else None

    async def _rpc(self, name: str, body: dict[str, object]) -> object:
        response = await self._request("POST", f"/rpc/{name}", json=body)
        return response.json()

    async def _request(
        self,
        method: str,
        url: str,
        *,
        params: Mapping[str, str | int | float | bool | None] | None = None,
        headers: Mapping[str, str] | None = None,
        json: object | None = None,
    ) -> httpx.Response:
        try:
            response = await self._client.request(
                method, url, params=params, headers=headers, json=json
            )
            response.raise_for_status()
            return response
        except httpx.HTTPStatusError as exc:
            if exc.response.status_code in {401, 403}:
                raise GovernanceAccessDeniedError("Governance operation is not permitted") from exc
            if exc.response.status_code in {400, 409, 422}:
                raise GovernanceConflictError(self._safe_message(exc.response)) from exc
            LOGGER.exception("Governance PostgREST request failed: %s %s", method, url)
            raise GovernanceRepositoryError("Governance storage is unavailable") from exc
        except (httpx.HTTPError, OSError, TypeError, ValueError) as exc:
            LOGGER.exception("Governance PostgREST request failed: %s %s", method, url)
            raise GovernanceRepositoryError("Governance storage is unavailable") from exc

    @staticmethod
    def _safe_message(response: httpx.Response) -> str:
        try:
            payload = response.json()
            if isinstance(payload, Mapping) and isinstance(payload.get("message"), str):
                return str(payload["message"])
        except ValueError:
            pass
        return "Governance operation was rejected"

    @staticmethod
    def _rows(payload: object, label: str) -> list[Mapping[str, object]]:
        if not isinstance(payload, list) or not all(isinstance(row, Mapping) for row in payload):
            raise GovernanceRepositoryError(f"Invalid {label} response")
        return payload

    @classmethod
    def _one(cls, payload: object, label: str) -> Mapping[str, object]:
        if isinstance(payload, Mapping):
            return payload
        rows = cls._rows(payload, label)
        if len(rows) != 1:
            raise GovernanceRepositoryError(f"Invalid {label} response")
        return rows[0]

    @staticmethod
    def _datetime(value: object) -> datetime:
        return datetime.fromisoformat(str(value))

    @staticmethod
    def _uuid(value: object) -> UUID | None:
        return UUID(str(value)) if value is not None else None

    @classmethod
    def _parse_search_hit(cls, row: Mapping[str, object]) -> SearchHit:
        metadata = row.get("metadata", {})
        return SearchHit(
            chunk_id=UUID(str(row["chunk_id"])),
            document_id=UUID(str(row["document_id"])),
            document_version_id=UUID(str(row["document_version_id"])),
            title=str(row.get("title", "")),
            content=str(row["content"]),
            score=float(str(row.get("score", 0.0))),
            page_start=int(str(row["page_start"])) if row.get("page_start") is not None else None,
            page_end=int(str(row["page_end"])) if row.get("page_end") is not None else None,
            section_path=(str(row["section_path"]) if row.get("section_path") else None),
            metadata=dict(metadata) if isinstance(metadata, Mapping) else {},
        )

    @classmethod
    def _parse_conversation(cls, row: Mapping[str, object]) -> EnterpriseConversation:
        return EnterpriseConversation(
            id=UUID(str(row["id"])),
            user_id=UUID(str(row["user_id"])),
            title=(str(row["title"]) if row.get("title") else None),
            created_at=cls._datetime(row["created_at"]),
            updated_at=cls._datetime(row["updated_at"]),
        )

    @classmethod
    def _parse_message(cls, row: Mapping[str, object]) -> EnterpriseMessage:
        citations_value = row.get("citations", [])
        return EnterpriseMessage(
            id=UUID(str(row["id"])),
            conversation_id=UUID(str(row["conversation_id"])),
            role=str(row["role"]),
            content=str(row["content"]),
            created_at=cls._datetime(row["created_at"]),
            answer_status=(str(row["answer_status"]) if row.get("answer_status") else None),
            citations=(
                tuple(
                    cls._parse_citation(item)
                    for item in citations_value
                    if isinstance(item, Mapping)
                )
                if isinstance(citations_value, list)
                else ()
            ),
        )

    @staticmethod
    def _parse_citation(row: Mapping[str, object]) -> EnterpriseCitation:
        return EnterpriseCitation(
            id=UUID(str(row["id"])),
            answer_message_id=UUID(str(row["answer_message_id"])),
            document_id=UUID(str(row["document_id"])),
            document_version_id=UUID(str(row["document_version_id"])),
            chunk_id=UUID(str(row["chunk_id"])),
            quote_text=str(row["quote_text"]),
            citation_order=int(str(row["citation_order"])),
            page_number=(
                int(str(row["page_number"])) if row.get("page_number") is not None else None
            ),
            retrieval_score=(
                float(str(row["retrieval_score"]))
                if row.get("retrieval_score") is not None
                else None
            ),
            document_title=(
                str(row["document_title"]) if row.get("document_title") else None
            ),
            section_path=(str(row["section_path"]) if row.get("section_path") else None),
        )

    @classmethod
    def _parse_feedback(cls, row: Mapping[str, object]) -> AnswerFeedback:
        return AnswerFeedback(
            id=UUID(str(row["id"])),
            message_id=UUID(str(row["message_id"])),
            user_id=UUID(str(row["user_id"])),
            rating=str(row["rating"]),
            comment=(str(row["comment"]) if row.get("comment") else None),
            created_at=cls._datetime(row["created_at"]),
            updated_at=(cls._datetime(row["updated_at"]) if row.get("updated_at") else None),
        )

    @classmethod
    def _parse_report(cls, row: Mapping[str, object]) -> AnswerReport:
        return AnswerReport(
            id=UUID(str(row["id"])),
            message_id=UUID(str(row["message_id"])),
            reporter_user_id=UUID(str(row["reporter_user_id"])),
            reason_code=str(row["reason_code"]),
            details=(str(row["details"]) if row.get("details") else None),
            status=str(row.get("status", "OPEN")),
            created_at=cls._datetime(row["created_at"]),
            resolution_note=(str(row["resolution_note"]) if row.get("resolution_note") else None),
            resolved_by=cls._uuid(row.get("resolved_by")),
            resolved_at=(cls._datetime(row["resolved_at"]) if row.get("resolved_at") else None),
        )

    @classmethod
    def _parse_audit(cls, row: Mapping[str, object]) -> AuditLog:
        metadata = row.get("metadata", {})
        return AuditLog(
            id=UUID(str(row["id"])),
            actor_user_id=cls._uuid(row.get("actor_user_id")),
            action=str(row["action"]),
            entity_type=str(row["entity_type"]),
            entity_id=cls._uuid(row.get("entity_id")),
            metadata=dict(metadata) if isinstance(metadata, Mapping) else {},
            created_at=cls._datetime(row["created_at"]),
            request_id=(str(row["request_id"]) if row.get("request_id") else None),
            trace_id=(str(row["trace_id"]) if row.get("trace_id") else None),
        )

    @staticmethod
    def _count(content_range: str | None, fallback: int) -> int:
        if content_range and "/" in content_range:
            value = content_range.rsplit("/", maxsplit=1)[1]
            if value != "*":
                return int(value)
        return fallback
