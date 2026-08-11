"""PostgREST implementation of the enterprise document lifecycle port."""

from __future__ import annotations

import logging
from collections.abc import Mapping
from datetime import date, datetime
from uuid import UUID

import httpx2 as httpx

from app.documents.domain.enterprise_models import (
    AccessDecision,
    DocumentMetadataAssertion,
    DocumentSearchability,
    DocumentVersion,
    DocumentVersionReviewContext,
    InitialDocumentUpload,
    KnowledgeDocument,
    PermissionAssignment,
    ProcessingError,
    ProcessingJob,
    ProcessingJobDetail,
    ProcessingStageHistory,
    ReviewChunk,
    ReviewSourceFile,
    SourceFile,
    VersionSource,
)
from app.documents.ports.enterprise_repositories import (
    EnterpriseDocumentAccessDeniedError,
    EnterpriseDocumentConflictError,
    EnterpriseDocumentRepository,
    EnterpriseDocumentRepositoryError,
    NewDocumentVersion,
    NewInitialDocumentUpload,
    NewKnowledgeDocument,
    NewSourceFile,
)

LOGGER = logging.getLogger(__name__)


class PostgrestEnterpriseDocumentRepository(EnterpriseDocumentRepository):
    """Call only RLS-protected tables and audited, atomic lifecycle RPCs."""

    def __init__(self, client: httpx.AsyncClient) -> None:
        self._client = client

    async def create_source_file(self, value: NewSourceFile) -> SourceFile:
        response = await self._request(
            "POST",
            "/source_files",
            params={"select": "*"},
            headers={"Prefer": "return=representation"},
            json={
                "id": str(value.id),
                "bucket_name": value.bucket_name,
                "object_path": value.object_path,
                "original_file_name": value.original_file_name,
                "mime_type": value.mime_type,
                "size_bytes": value.size_bytes,
                "sha256": value.sha256,
                "created_by": str(value.created_by),
            },
        )
        return self._parse_source_file(self._one(response.json(), "source file creation"))

    async def create_initial_document_upload(
        self, value: NewInitialDocumentUpload
    ) -> InitialDocumentUpload:
        document = value.document
        source = value.source_file
        payload = await self._rpc(
            "create_enterprise_document_upload",
            {
                "p_source_id": str(source.id),
                "p_bucket_name": source.bucket_name,
                "p_object_path": source.object_path,
                "p_original_file_name": source.original_file_name,
                "p_mime_type": source.mime_type,
                "p_size_bytes": source.size_bytes,
                "p_sha256": source.sha256,
                "p_title": document.title,
                "p_description": document.description,
                "p_document_type": document.document_type,
                "p_category": document.category,
                "p_metadata": document.metadata,
                "p_change_summary": value.change_summary,
                "p_effective_date": (
                    value.effective_date.isoformat() if value.effective_date else None
                ),
            },
        )
        row = self._one(payload, "initial document upload")
        return InitialDocumentUpload(
            document=self._parse_document(self._mapping(row.get("document"), "document")),
            version=self._parse_version(self._mapping(row.get("version"), "version")),
            processing_job=self._parse_processing_job(
                self._mapping(row.get("processing_job"), "processing job")
            ),
            source_file=self._parse_source_file(
                self._mapping(row.get("source_file"), "source file")
            ),
        )

    async def list_documents(
        self, *, document_status: str | None, limit: int, offset: int
    ) -> tuple[list[KnowledgeDocument], int]:
        params = {
            "select": "*",
            "order": "updated_at.desc,id.asc",
            "limit": str(limit),
            "offset": str(offset),
        }
        if document_status is not None:
            params["status"] = f"eq.{document_status}"
        response = await self._request(
            "GET",
            "/knowledge_documents",
            params=params,
            headers={"Prefer": "count=exact"},
        )
        rows = self._rows(response.json(), "document list")
        return [self._parse_document(row) for row in rows], self._total_count(
            response.headers.get("content-range"), fallback=len(rows)
        )

    async def get_document(self, document_id: UUID) -> KnowledgeDocument | None:
        response = await self._request(
            "GET",
            "/knowledge_documents",
            params={"id": f"eq.{document_id}", "select": "*", "limit": "1"},
        )
        rows = self._rows(response.json(), "document lookup")
        return self._parse_document(rows[0]) if rows else None

    async def list_searchability(self, *, document_id: UUID | None) -> list[DocumentSearchability]:
        payload = await self._rpc(
            "get_enterprise_document_searchability",
            {"p_document_id": str(document_id) if document_id is not None else None},
        )
        return [
            self._parse_searchability(row) for row in self._rows(payload, "document searchability")
        ]

    async def create_document(self, value: NewKnowledgeDocument) -> KnowledgeDocument:
        payload = await self._rpc(
            "create_knowledge_document",
            {
                "p_title": value.title,
                "p_description": value.description,
                "p_document_type": value.document_type,
                "p_category": value.category,
                "p_metadata": value.metadata,
            },
        )
        return self._parse_document(self._one(payload, "document creation"))

    async def update_document(
        self, document_id: UUID, changes: dict[str, object]
    ) -> KnowledgeDocument | None:
        payload = await self._rpc(
            "update_knowledge_document",
            {"p_document_id": str(document_id), "p_changes": changes},
        )
        if payload is None or payload == []:
            return None
        return self._parse_document(self._one(payload, "document update"))

    async def list_versions(self, document_id: UUID) -> list[DocumentVersion]:
        response = await self._request(
            "GET",
            "/document_versions",
            params={
                "document_id": f"eq.{document_id}",
                "select": "*",
                "order": "version_number.desc,id.asc",
            },
        )
        return [self._parse_version(row) for row in self._rows(response.json(), "version list")]

    async def get_version_review_context(
        self, version_id: UUID
    ) -> DocumentVersionReviewContext | None:
        payload = await self._rpc(
            "get_document_version_review_context",
            {"p_version_id": str(version_id)},
        )
        if payload is None or payload == []:
            return None
        row = self._one(payload, "version review context")
        source = self._mapping(row.get("source_file"), "review source file")
        latest_job = row.get("latest_processing_job")
        raw_stages = row.get("stage_history", [])
        raw_errors = row.get("errors", [])
        raw_chunks = row.get("extracted_chunks", [])
        stages = self._rows(raw_stages, "review stage history")
        errors = self._rows(raw_errors, "review processing errors")
        chunks = self._rows(raw_chunks, "review extracted chunks")
        return DocumentVersionReviewContext(
            document=self._parse_document(self._mapping(row.get("document"), "document")),
            version=self._parse_version(self._mapping(row.get("version"), "version")),
            source_file=ReviewSourceFile(
                id=UUID(str(source["id"])),
                original_file_name=str(source["original_file_name"]),
                mime_type=str(source["mime_type"]),
                size_bytes=int(str(source["size_bytes"])),
                sha256=(str(source["sha256"]) if source.get("sha256") else None),
                created_by=UUID(str(source["created_by"])),
                created_at=self._datetime(source.get("created_at")),
            ),
            latest_processing_job=(
                self._parse_processing_job(self._mapping(latest_job, "latest processing job"))
                if latest_job is not None
                else None
            ),
            stage_history=tuple(self._parse_processing_stage(item) for item in stages),
            errors=tuple(self._parse_processing_error(item) for item in errors),
            extracted_chunks=tuple(self._parse_review_chunk(item) for item in chunks),
        )

    async def create_version(self, value: NewDocumentVersion) -> DocumentVersion:
        payload = await self._rpc(
            "create_document_version",
            {
                "p_document_id": str(value.document_id),
                "p_source_file_id": str(value.source_file_id),
                "p_change_summary": value.change_summary,
                "p_effective_date": value.effective_date.isoformat()
                if value.effective_date
                else None,
            },
        )
        return self._parse_version(self._one(payload, "version creation"))

    async def review_version(
        self,
        version_id: UUID,
        *,
        decision: str,
        note: str | None,
        rejection_reason: str | None,
    ) -> DocumentVersion:
        payload = await self._rpc(
            "review_document_version",
            {
                "p_version_id": str(version_id),
                "p_decision": decision,
                "p_note": note,
                "p_rejection_reason": rejection_reason,
            },
        )
        return self._parse_version(self._one(payload, "version review"))

    async def list_metadata_assertions(
        self,
        version_id: UUID,
        *,
        verification_status: str | None,
    ) -> list[DocumentMetadataAssertion]:
        params: dict[str, str] = {
            "document_version_id": f"eq.{version_id}",
            "select": "*",
            "order": "created_at.asc,id.asc",
        }
        if verification_status:
            params["verification_status"] = f"eq.{verification_status}"
        response = await self._request(
            "GET",
            "/document_metadata_assertions",
            params=params,
        )
        return [
            self._parse_metadata_assertion(row)
            for row in self._rows(response.json(), "document metadata assertion list")
        ]

    async def review_metadata_assertion(
        self,
        assertion_id: UUID,
        *,
        decision: str,
        rejection_reason: str | None,
    ) -> DocumentMetadataAssertion:
        payload = await self._rpc(
            "review_document_metadata_assertion",
            {
                "p_assertion_id": str(assertion_id),
                "p_decision": decision,
                "p_rejection_reason": rejection_reason,
            },
        )
        return self._parse_metadata_assertion(
            self._one(payload, "document metadata assertion review")
        )

    async def publish_version(self, version_id: UUID) -> DocumentVersion:
        payload = await self._rpc(
            "approve_and_publish_document_version",
            {
                "p_version_id": str(version_id),
                "p_note": "Approved and published through the guided admin workflow",
            },
        )
        return self._parse_version(self._one(payload, "version publication"))

    async def archive_document(self, document_id: UUID, *, reason: str) -> KnowledgeDocument:
        payload = await self._rpc(
            "archive_knowledge_document",
            {"p_document_id": str(document_id), "p_reason": reason},
        )
        return self._parse_document(self._one(payload, "document archive"))

    async def list_permissions(self, document_id: UUID) -> list[PermissionAssignment]:
        response = await self._request(
            "GET",
            "/document_permissions",
            params={
                "document_id": f"eq.{document_id}",
                "select": "*",
                "order": "granted_at.desc,id.asc",
            },
        )
        return [
            self._parse_permission(row)
            for row in self._rows(response.json(), "document permission list")
        ]

    async def grant_permission(
        self, document_id: UUID, subject_id: UUID, permission: str
    ) -> PermissionAssignment:
        payload = await self._rpc(
            "grant_document_permission",
            {
                "p_document_id": str(document_id),
                "p_subject_id": str(subject_id),
                "p_permission": permission,
            },
        )
        return self._parse_permission(self._one(payload, "permission grant"))

    async def revoke_permission(self, document_id: UUID, subject_id: UUID, permission: str) -> None:
        await self._rpc(
            "revoke_document_permission",
            {
                "p_document_id": str(document_id),
                "p_subject_id": str(subject_id),
                "p_permission": permission,
            },
        )

    async def test_access(self, user_id: UUID, document_id: UUID, permission: str) -> bool:
        payload = await self._rpc(
            "test_document_access",
            {
                "p_user_id": str(user_id),
                "p_document_id": str(document_id),
                "p_permission": permission,
            },
        )
        if not isinstance(payload, bool):
            raise EnterpriseDocumentRepositoryError("Invalid access-test response")
        return payload

    async def explain_access(
        self, user_id: UUID, document_id: UUID, permission: str
    ) -> AccessDecision:
        payload = await self._rpc(
            "explain_document_access",
            {
                "p_user_id": str(user_id),
                "p_document_id": str(document_id),
                "p_permission": permission,
            },
        )
        row = self._one(payload, "access explanation")
        raw_sources = row.get("sources", [])
        if not isinstance(raw_sources, list) or not all(
            isinstance(source, str) for source in raw_sources
        ):
            raise EnterpriseDocumentRepositoryError("Invalid access explanation response")
        return AccessDecision(
            allowed=bool(row.get("allowed", False)),
            sources=tuple(raw_sources),
        )

    async def list_processing_jobs(
        self,
        *,
        document_id: UUID | None,
        document_version_id: UUID | None,
        job_status: str | None,
        limit: int,
        offset: int,
    ) -> tuple[list[ProcessingJob], int]:
        select = "*"
        params: dict[str, str] = {
            "select": select,
            "order": "requested_at.desc,id.asc",
            "limit": str(limit),
            "offset": str(offset),
        }
        if document_id is not None:
            params["select"] = "*,document_versions!inner(document_id)"
            params["document_versions.document_id"] = f"eq.{document_id}"
        if document_version_id is not None:
            params["document_version_id"] = f"eq.{document_version_id}"
        if job_status is not None:
            params["status"] = f"eq.{job_status}"
        response = await self._request(
            "GET",
            "/processing_jobs",
            params=params,
            headers={"Prefer": "count=exact"},
        )
        rows = self._rows(response.json(), "processing job list")
        return [self._parse_processing_job(row) for row in rows], self._total_count(
            response.headers.get("content-range"), fallback=len(rows)
        )

    async def get_processing_job(self, job_id: UUID) -> ProcessingJob | None:
        response = await self._request(
            "GET",
            "/processing_jobs",
            params={"id": f"eq.{job_id}", "select": "*", "limit": "1"},
        )
        rows = self._rows(response.json(), "processing job lookup")
        return self._parse_processing_job(rows[0]) if rows else None

    async def get_processing_job_detail(self, job_id: UUID) -> ProcessingJobDetail | None:
        job = await self.get_processing_job(job_id)
        if job is None:
            return None
        stage_response = await self._request(
            "GET",
            "/processing_stage_history",
            params={
                "processing_job_id": f"eq.{job_id}",
                "select": "*",
                "order": "started_at.asc,id.asc",
            },
        )
        error_response = await self._request(
            "GET",
            "/processing_errors",
            params={
                "processing_job_id": f"eq.{job_id}",
                "select": "*",
                "order": "created_at.desc,id.asc",
            },
        )
        return ProcessingJobDetail(
            job=job,
            stage_history=tuple(
                self._parse_processing_stage(row)
                for row in self._rows(stage_response.json(), "processing stage history")
            ),
            errors=tuple(
                self._parse_processing_error(row)
                for row in self._rows(error_response.json(), "processing errors")
            ),
        )

    async def retry_processing_job(self, job_id: UUID) -> ProcessingJob:
        payload = await self._rpc("retry_processing_job", {"p_job_id": str(job_id)})
        return self._parse_processing_job(self._one(payload, "processing job retry"))

    async def get_version_source(self, document_id: UUID, version_id: UUID) -> VersionSource | None:
        payload = await self._rpc(
            "get_document_version_source",
            {"p_document_id": str(document_id), "p_version_id": str(version_id)},
        )
        if payload is None or payload == []:
            return None
        row = self._one(payload, "version source")
        return VersionSource(
            bucket_name=str(row["bucket_name"]),
            object_path=str(row["object_path"]),
            original_file_name=str(row["original_file_name"]),
            mime_type=str(row["mime_type"]),
        )

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
                raise EnterpriseDocumentAccessDeniedError(
                    "Document operation is not permitted"
                ) from exc
            if exc.response.status_code in {400, 409, 422}:
                raise EnterpriseDocumentConflictError(
                    self._safe_error_message(exc.response)
                ) from exc
            LOGGER.exception("Enterprise document request failed: %s %s", method, url)
            raise EnterpriseDocumentRepositoryError("Document storage is unavailable") from exc
        except (httpx.HTTPError, OSError, TypeError, ValueError) as exc:
            LOGGER.exception("Enterprise document request failed: %s %s", method, url)
            raise EnterpriseDocumentRepositoryError("Document storage is unavailable") from exc

    @staticmethod
    def _safe_error_message(response: httpx.Response) -> str:
        try:
            payload = response.json()
            if isinstance(payload, Mapping) and isinstance(payload.get("message"), str):
                return str(payload["message"])
        except ValueError:
            pass
        return "Document lifecycle operation was rejected"

    @staticmethod
    def _rows(payload: object, label: str) -> list[Mapping[str, object]]:
        if not isinstance(payload, list) or not all(isinstance(row, Mapping) for row in payload):
            raise EnterpriseDocumentRepositoryError(f"Invalid {label} response")
        return payload

    @classmethod
    def _one(cls, payload: object, label: str) -> Mapping[str, object]:
        if isinstance(payload, Mapping):
            return payload
        rows = cls._rows(payload, label)
        if len(rows) != 1:
            raise EnterpriseDocumentRepositoryError(f"Invalid {label} response")
        return rows[0]

    @staticmethod
    def _mapping(payload: object, label: str) -> Mapping[str, object]:
        if not isinstance(payload, Mapping):
            raise EnterpriseDocumentRepositoryError(f"Invalid {label} response")
        return payload

    @staticmethod
    def _uuid(value: object) -> UUID | None:
        return UUID(str(value)) if value is not None else None

    @staticmethod
    def _date(value: object) -> date | None:
        return date.fromisoformat(str(value)) if value is not None else None

    @staticmethod
    def _datetime(value: object) -> datetime | None:
        return datetime.fromisoformat(str(value)) if value is not None else None

    @classmethod
    def _parse_document(cls, row: Mapping[str, object]) -> KnowledgeDocument:
        metadata = row.get("metadata", {})
        return KnowledgeDocument(
            id=UUID(str(row["id"])),
            title=str(row["title"]),
            description=(str(row["description"]) if row.get("description") else None),
            document_type=(str(row["document_type"]) if row.get("document_type") else None),
            category=(str(row["category"]) if row.get("category") else None),
            document_number=(str(row["document_number"]) if row.get("document_number") else None),
            issued_date=cls._date(row.get("issued_date")),
            effective_date=cls._date(row.get("effective_date")),
            expiration_date=cls._date(row.get("expiration_date")),
            source=(str(row["source"]) if row.get("source") else None),
            owner_department_id=cls._uuid(row.get("owner_department_id")),
            status=str(row["status"]),
            current_version_id=cls._uuid(row.get("current_version_id")),
            metadata=dict(metadata) if isinstance(metadata, Mapping) else {},
            created_by=cls._uuid(row.get("created_by")),
            created_at=cls._datetime(row.get("created_at")),
            updated_at=cls._datetime(row.get("updated_at")),
            archived_by=cls._uuid(row.get("archived_by")),
            archived_at=cls._datetime(row.get("archived_at")),
            archive_reason=(str(row["archive_reason"]) if row.get("archive_reason") else None),
        )

    @classmethod
    def _parse_searchability(cls, row: Mapping[str, object]) -> DocumentSearchability:
        searchable = row.get("searchable_for_actor")
        fully_indexed = row.get("fully_indexed")
        if not isinstance(searchable, bool) or not isinstance(fully_indexed, bool):
            raise EnterpriseDocumentRepositoryError("Invalid document searchability response")
        blocking_reasons = cls._string_tuple(
            row.get("blocking_reasons", []), "searchability blocking reasons"
        )
        warnings = cls._string_tuple(row.get("warnings", []), "searchability warnings")
        return DocumentSearchability(
            document_id=UUID(str(row["document_id"])),
            title=str(row["title"]),
            document_status=str(row["document_status"]),
            visibility=str(row["visibility"]),
            current_version_id=cls._uuid(row.get("current_version_id")),
            version_status=(str(row["version_status"]) if row.get("version_status") else None),
            metadata_revision=int(str(row["metadata_revision"])),
            chunk_count=int(str(row["chunk_count"])),
            ready_projection_count=int(str(row["ready_projection_count"])),
            lexical_ready_projection_count=int(str(row["lexical_ready_projection_count"])),
            lexical_stale_count=int(str(row["lexical_stale_count"])),
            embedding_stale_count=int(str(row["embedding_stale_count"])),
            refresh_requested_revision=(
                int(str(row["refresh_requested_revision"]))
                if row.get("refresh_requested_revision") is not None
                else None
            ),
            refresh_processed_at=cls._datetime(row.get("refresh_processed_at")),
            refresh_error=(str(row["refresh_error"]) if row.get("refresh_error") else None),
            searchable_for_actor=searchable,
            fully_indexed=fully_indexed,
            blocking_reasons=blocking_reasons,
            warnings=warnings,
        )

    @staticmethod
    def _string_tuple(value: object, label: str) -> tuple[str, ...]:
        if not isinstance(value, list) or not all(isinstance(item, str) for item in value):
            raise EnterpriseDocumentRepositoryError(f"Invalid {label} response")
        return tuple(value)

    @classmethod
    def _parse_version(cls, row: Mapping[str, object]) -> DocumentVersion:
        return DocumentVersion(
            id=UUID(str(row["id"])),
            document_id=UUID(str(row["document_id"])),
            version_number=int(str(row["version_number"])),
            source_file_id=UUID(str(row["source_file_id"])),
            status=str(row["status"]),
            previous_version_id=cls._uuid(row.get("previous_version_id")),
            change_summary=(str(row["change_summary"]) if row.get("change_summary") else None),
            effective_date=cls._date(row.get("effective_date")),
            created_by=cls._uuid(row.get("created_by")),
            created_at=cls._datetime(row.get("created_at")),
            updated_at=cls._datetime(row.get("updated_at")),
            legacy_document_id=cls._uuid(row.get("legacy_document_id")),
        )

    @classmethod
    def _parse_metadata_assertion(
        cls,
        row: Mapping[str, object],
    ) -> DocumentMetadataAssertion:
        evidence = row.get("evidence", [])
        if not isinstance(evidence, list) or not all(
            isinstance(item, Mapping) for item in evidence
        ):
            raise EnterpriseDocumentRepositoryError("Invalid metadata assertion evidence")
        return DocumentMetadataAssertion(
            id=UUID(str(row["id"])),
            document_id=UUID(str(row["document_id"])),
            document_version_id=cls._uuid(row.get("document_version_id")),
            field_name=str(row["field_name"]),
            value=str(row["value"]),
            normalized_value=str(row["normalized_value"]),
            source_type=str(row["source_type"]),
            confidence=float(str(row["confidence"])),
            verification_status=str(row["verification_status"]),
            evidence=tuple(dict(item) for item in evidence),
            model=str(row["model"]) if row.get("model") else None,
            prompt_version=(
                str(row["prompt_version"]) if row.get("prompt_version") else None
            ),
            input_checksum=(
                str(row["input_checksum"]) if row.get("input_checksum") else None
            ),
            created_at=cls._datetime(row.get("created_at")),
            verified_by=cls._uuid(row.get("verified_by")),
            verified_at=cls._datetime(row.get("verified_at")),
            rejection_reason=(
                str(row["rejection_reason"]) if row.get("rejection_reason") else None
            ),
        )

    @classmethod
    def _parse_permission(cls, row: Mapping[str, object]) -> PermissionAssignment:
        return PermissionAssignment(
            id=UUID(str(row["id"])),
            document_id=UUID(str(row["document_id"])),
            subject_id=UUID(str(row["subject_id"])),
            permission=str(row["permission"]),
            status=str(row.get("status", "ACTIVE")),
            granted_by=cls._uuid(row.get("granted_by")),
            granted_at=cls._datetime(row.get("granted_at")),
            revoked_by=cls._uuid(row.get("revoked_by")),
            revoked_at=cls._datetime(row.get("revoked_at")),
        )

    @classmethod
    def _parse_processing_job(cls, row: Mapping[str, object]) -> ProcessingJob:
        return ProcessingJob(
            id=UUID(str(row["id"])),
            document_version_id=UUID(str(row["document_version_id"])),
            job_type=str(row["job_type"]),
            status=str(row["status"]),
            current_stage=(str(row["current_stage"]) if row.get("current_stage") else None),
            attempt_no=int(str(row.get("attempt_no", 1))),
            previous_job_id=cls._uuid(row.get("previous_job_id")),
            requested_by=cls._uuid(row.get("requested_by")),
            requested_at=cls._datetime(row.get("requested_at")),
            started_at=cls._datetime(row.get("started_at")),
            completed_at=cls._datetime(row.get("completed_at")),
            heartbeat_at=cls._datetime(row.get("heartbeat_at")),
            lease_owner=(str(row["lease_owner"]) if row.get("lease_owner") else None),
            lease_expires_at=cls._datetime(row.get("lease_expires_at")),
            error_code=(str(row["error_code"]) if row.get("error_code") else None),
            error_message=(str(row["error_message"]) if row.get("error_message") else None),
        )

    @classmethod
    def _parse_processing_stage(cls, row: Mapping[str, object]) -> ProcessingStageHistory:
        started_at = cls._datetime(row.get("started_at"))
        if started_at is None:
            raise EnterpriseDocumentRepositoryError("Invalid processing stage start time")
        return ProcessingStageHistory(
            id=int(str(row["id"])),
            processing_job_id=UUID(str(row["processing_job_id"])),
            stage=str(row["stage"]),
            status=str(row["status"]),
            started_at=started_at,
            completed_at=cls._datetime(row.get("completed_at")),
            message=(str(row["message"]) if row.get("message") else None),
        )

    @classmethod
    def _parse_processing_error(cls, row: Mapping[str, object]) -> ProcessingError:
        created_at = cls._datetime(row.get("created_at"))
        if created_at is None:
            raise EnterpriseDocumentRepositoryError("Invalid processing error time")
        return ProcessingError(
            id=UUID(str(row["id"])),
            processing_job_id=UUID(str(row["processing_job_id"])),
            stage=(str(row["stage"]) if row.get("stage") else None),
            error_type=str(row["error_type"]),
            error_code=str(row["error_code"]),
            safe_message=str(row["safe_message"]),
            retryable=bool(row.get("retryable", False)),
            created_at=created_at,
        )

    @staticmethod
    def _parse_review_chunk(row: Mapping[str, object]) -> ReviewChunk:
        metadata = row.get("metadata", {})
        return ReviewChunk(
            chunk_id=UUID(str(row["chunk_id"])),
            chunk_index=int(str(row["chunk_index"])),
            content=str(row["content"]),
            page_start=(int(str(row["page_start"])) if row.get("page_start") else None),
            page_end=(int(str(row["page_end"])) if row.get("page_end") else None),
            section_path=(str(row["section_path"]) if row.get("section_path") else None),
            metadata=dict(metadata) if isinstance(metadata, Mapping) else {},
        )

    @classmethod
    def _parse_source_file(cls, row: Mapping[str, object]) -> SourceFile:
        return SourceFile(
            id=UUID(str(row["id"])),
            bucket_name=str(row["bucket_name"]),
            object_path=str(row["object_path"]),
            original_file_name=str(row["original_file_name"]),
            mime_type=str(row["mime_type"]),
            size_bytes=int(str(row["size_bytes"])),
            sha256=(str(row["sha256"]) if row.get("sha256") else None),
            created_by=UUID(str(row["created_by"])),
            created_at=(cls._datetime(row["created_at"]) if row.get("created_at") else None),
        )

    @staticmethod
    def _total_count(content_range: str | None, *, fallback: int) -> int:
        if content_range and "/" in content_range:
            value = content_range.rsplit("/", maxsplit=1)[1]
            if value != "*":
                return int(value)
        return fallback
