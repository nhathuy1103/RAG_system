"""HTTP contracts for the additive Enterprise Knowledge API v1."""

from __future__ import annotations

from datetime import date, datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator


class ApiErrorDetail(BaseModel):
    code: str
    message: str
    trace_id: str


class ApiErrorResponse(BaseModel):
    error: ApiErrorDetail


class RoleResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    code: str
    name: str
    description: str | None = None
    status: str
    created_at: datetime | None = None
    updated_at: datetime | None = None


class GroupResponse(RoleResponse):
    pass


class DepartmentResponse(RoleResponse):
    parent_department_id: UUID | None = None


class FunctionalPermissionResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    code: str
    name: str
    description: str | None = None
    created_at: datetime | None = None


class UserRoleMembershipResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    user_id: UUID
    role_id: UUID
    role: RoleResponse
    assigned_by: UUID | None = None
    assigned_at: datetime | None = None


class UserGroupMembershipResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    user_id: UUID
    group_id: UUID
    group: GroupResponse
    added_by: UUID | None = None
    joined_at: datetime | None = None


class UserDepartmentMembershipResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    user_id: UUID
    department_id: UUID
    department: DepartmentResponse
    is_primary: bool
    start_at: datetime
    end_at: datetime | None = None
    assigned_by: UUID | None = None


class AccessSubjectResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    subject_type: str
    user_id: UUID | None = None
    role_id: UUID | None = None
    group_id: UUID | None = None
    department_id: UUID | None = None


class PrincipalResponse(BaseModel):
    user_id: UUID
    email: str | None
    status: str
    roles: list[RoleResponse]
    permissions: list[str]
    group_ids: list[UUID]
    department_ids: list[UUID]


class ProfileResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    user_id: UUID
    company_user_id: str | None = None
    full_name: str | None = None
    status: str
    created_at: datetime | None = None
    updated_at: datetime | None = None


class ProfileListResponse(BaseModel):
    items: list[ProfileResponse]
    total_count: int
    limit: int
    offset: int


class ProfileCreateRequest(BaseModel):
    user_id: UUID
    company_user_id: str | None = Field(default=None, max_length=100)
    full_name: str | None = Field(default=None, max_length=255)
    status: Literal["ACTIVE", "LOCKED", "DISABLED"] = "ACTIVE"


class EmployeeProvisionRequest(BaseModel):
    email: str = Field(min_length=3, max_length=320)
    temporary_password: str = Field(min_length=8, max_length=128)
    company_user_id: str | None = Field(default=None, max_length=100)
    full_name: str | None = Field(default=None, max_length=255)

    @field_validator("email")
    @classmethod
    def normalize_email(cls, value: str) -> str:
        normalized = value.strip().lower()
        local, separator, domain = normalized.partition("@")
        if not separator or not local or "." not in domain or domain.startswith("."):
            raise ValueError("A valid employee email address is required")
        return normalized

    @field_validator("company_user_id", "full_name")
    @classmethod
    def normalize_optional_text(cls, value: str | None) -> str | None:
        if value is None:
            return None
        normalized = value.strip()
        return normalized or None


class EmployeeProvisionResponse(ProfileResponse):
    email: str


class ProfileUpdateRequest(BaseModel):
    company_user_id: str | None = Field(default=None, max_length=100)
    full_name: str | None = Field(default=None, max_length=255)
    status: Literal["ACTIVE", "LOCKED", "DISABLED"] | None = None


class OrganizationCreateRequest(BaseModel):
    code: str = Field(min_length=1, max_length=100)
    name: str = Field(min_length=1, max_length=255)
    description: str | None = Field(default=None, max_length=2000)
    status: Literal["ACTIVE", "DISABLED"] = "ACTIVE"
    parent_department_id: UUID | None = None


class OrganizationUpdateRequest(BaseModel):
    code: str | None = Field(default=None, min_length=1, max_length=100)
    name: str | None = Field(default=None, min_length=1, max_length=255)
    description: str | None = Field(default=None, max_length=2000)
    status: Literal["ACTIVE", "DISABLED"] | None = None
    parent_department_id: UUID | None = None


class AssignmentRequest(BaseModel):
    object_id: UUID
    is_primary: bool = False


class OperationResponse(BaseModel):
    message: str


class KnowledgeDocumentResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    title: str
    description: str | None = None
    document_type: str | None = None
    category: str | None = None
    document_number: str | None = None
    issued_date: date | None = None
    effective_date: date | None = None
    expiration_date: date | None = None
    source: str | None = None
    owner_department_id: UUID | None = None
    status: str
    current_version_id: UUID | None = None
    metadata: dict[str, object]
    created_by: UUID | None = None
    created_at: datetime | None = None
    updated_at: datetime | None = None
    archived_by: UUID | None = None
    archived_at: datetime | None = None
    archive_reason: str | None = None


class KnowledgeDocumentListResponse(BaseModel):
    items: list[KnowledgeDocumentResponse]
    total_count: int
    limit: int
    offset: int


class DocumentSearchabilityResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    document_id: UUID
    title: str
    document_status: str
    visibility: str
    current_version_id: UUID | None = None
    version_status: str | None = None
    metadata_revision: int
    chunk_count: int
    ready_projection_count: int
    lexical_ready_projection_count: int
    lexical_stale_count: int
    embedding_stale_count: int
    refresh_requested_revision: int | None = None
    refresh_processed_at: datetime | None = None
    refresh_error: str | None = None
    searchable_for_actor: bool
    fully_indexed: bool
    blocking_reasons: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)


class KnowledgeDocumentCreateRequest(BaseModel):
    title: str = Field(min_length=1, max_length=500)
    description: str | None = Field(default=None, max_length=5000)
    document_type: str | None = Field(default=None, max_length=100)
    category: str | None = Field(default=None, max_length=100)
    metadata: dict[str, object] = Field(default_factory=dict)


class KnowledgeDocumentUpdateRequest(BaseModel):
    expected_updated_at: datetime
    title: str | None = Field(default=None, min_length=1, max_length=500)
    description: str | None = Field(default=None, max_length=5000)
    document_type: str | None = Field(default=None, max_length=100)
    category: str | None = Field(default=None, max_length=100)
    document_number: str | None = Field(default=None, max_length=255)
    issued_date: date | None = None
    effective_date: date | None = None
    expiration_date: date | None = None
    source: str | None = Field(default=None, max_length=500)
    owner_department_id: UUID | None = None
    metadata: dict[str, object] | None = None


class DocumentVersionResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    document_id: UUID
    version_number: int
    source_file_id: UUID
    status: str
    previous_version_id: UUID | None = None
    change_summary: str | None = None
    effective_date: date | None = None
    created_by: UUID | None = None
    created_at: datetime | None = None
    updated_at: datetime | None = None
    legacy_document_id: UUID | None = None


class DocumentVersionCreateRequest(BaseModel):
    source_file_id: UUID
    change_summary: str | None = Field(default=None, max_length=5000)
    effective_date: date | None = None


class VersionReviewRequest(BaseModel):
    decision: Literal["APPROVE", "REJECT", "REPROCESS"]
    note: str | None = Field(default=None, max_length=5000)
    rejection_reason: str | None = Field(default=None, max_length=5000)


class MetadataAssertionReviewRequest(BaseModel):
    decision: Literal["VERIFIED", "REJECTED"]
    rejection_reason: str | None = Field(default=None, max_length=5000)


class DocumentMetadataAssertionResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    document_id: UUID
    document_version_id: UUID | None
    field_name: str
    value: str
    normalized_value: str
    source_type: str
    confidence: float
    verification_status: str
    evidence: list[dict[str, object]] = Field(default_factory=list)
    model: str | None = None
    prompt_version: str | None = None
    input_checksum: str | None = None
    created_at: datetime | None = None
    verified_by: UUID | None = None
    verified_at: datetime | None = None
    rejection_reason: str | None = None


class ArchiveDocumentRequest(BaseModel):
    reason: str = Field(min_length=1, max_length=5000)


class PermissionResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    document_id: UUID
    subject_id: UUID
    permission: str
    status: str
    granted_by: UUID | None = None
    granted_at: datetime | None = None
    revoked_by: UUID | None = None
    revoked_at: datetime | None = None


DocumentPermissionLiteral = Literal[
    "READ",
    "DOWNLOAD",
    "MANAGE",
    "REVIEW",
    "PUBLISH",
    "ARCHIVE",
    "MANAGE_PERMISSION",
]


class PermissionGrantRequest(BaseModel):
    subject_id: UUID
    permission: DocumentPermissionLiteral


class AccessTestRequest(BaseModel):
    user_id: UUID
    permission: DocumentPermissionLiteral = "READ"


class AccessTestResponse(BaseModel):
    allowed: bool
    sources: list[str] = Field(default_factory=list)


class ProcessingJobResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    document_version_id: UUID
    job_type: str
    status: str
    current_stage: str | None = None
    attempt_no: int
    previous_job_id: UUID | None = None
    requested_by: UUID | None = None
    requested_at: datetime | None = None
    started_at: datetime | None = None
    completed_at: datetime | None = None
    heartbeat_at: datetime | None = None
    lease_owner: str | None = None
    lease_expires_at: datetime | None = None
    error_code: str | None = None
    error_message: str | None = None


class ProcessingJobListResponse(BaseModel):
    items: list[ProcessingJobResponse]
    total_count: int
    limit: int
    offset: int


class ProcessingStageHistoryResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    processing_job_id: UUID
    stage: str
    status: str
    started_at: datetime
    completed_at: datetime | None = None
    message: str | None = None


class ProcessingErrorResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    processing_job_id: UUID
    stage: str | None = None
    error_type: str
    error_code: str
    safe_message: str
    retryable: bool
    created_at: datetime


class ProcessingJobDetailResponse(ProcessingJobResponse):
    stage_history: list[ProcessingStageHistoryResponse] = Field(default_factory=list)
    errors: list[ProcessingErrorResponse] = Field(default_factory=list)


class VersionSourceResponse(BaseModel):
    signed_url: str
    expires_at: datetime
    original_file_name: str
    mime_type: str


class SourceFileResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    bucket_name: str
    object_path: str
    original_file_name: str
    mime_type: str
    size_bytes: int
    sha256: str | None = None
    created_by: UUID
    created_at: datetime | None = None


class InitialDocumentUploadResponse(BaseModel):
    document: KnowledgeDocumentResponse
    version: DocumentVersionResponse
    processing_job: ProcessingJobResponse
    source_file: SourceFileResponse


class ReviewSourceFileResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    original_file_name: str
    mime_type: str
    size_bytes: int
    sha256: str | None = None
    created_by: UUID
    created_at: datetime | None = None


class ReviewChunkResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    chunk_id: UUID
    chunk_index: int
    content: str
    page_start: int | None = None
    page_end: int | None = None
    section_path: str | None = None
    metadata: dict[str, object] = Field(default_factory=dict)


class DocumentVersionReviewContextResponse(BaseModel):
    document: KnowledgeDocumentResponse
    version: DocumentVersionResponse
    source_file: ReviewSourceFileResponse
    latest_processing_job: ProcessingJobResponse | None = None
    stage_history: list[ProcessingStageHistoryResponse] = Field(default_factory=list)
    errors: list[ProcessingErrorResponse] = Field(default_factory=list)
    extracted_chunks: list[ReviewChunkResponse] = Field(default_factory=list)


class SearchRequest(BaseModel):
    query: str = Field(min_length=1, max_length=4000)
    limit: int = Field(default=10, ge=1, le=50)
    filters: dict[str, object] = Field(default_factory=dict)


class SearchHitResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    chunk_id: UUID
    document_id: UUID
    document_version_id: UUID
    title: str
    content: str
    score: float
    page_start: int | None = None
    page_end: int | None = None
    section_path: str | None = None
    metadata: dict[str, object]


class SearchResponse(BaseModel):
    items: list[SearchHitResponse]


class ConversationCreateRequest(BaseModel):
    title: str | None = Field(default=None, max_length=500)


class ConversationResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    user_id: UUID
    title: str | None = None
    created_at: datetime
    updated_at: datetime


class MessageCreateRequest(BaseModel):
    content: str = Field(min_length=1, max_length=4000)
    filters: dict[str, object] = Field(default_factory=dict)


class EnterpriseCitationResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True, populate_by_name=True)

    document_id: UUID
    document_version_id: UUID
    document_title: str | None = None
    chunk_id: UUID
    page: int | None = Field(default=None, validation_alias="page_number")
    section: str | None = Field(default=None, validation_alias="section_path")


class AnswerRetrievalResponse(BaseModel):
    strategy: str
    candidate_count: int = 0
    evidence_count: int
    gate_reason: str | None = None


class AskQuestionResponse(BaseModel):
    conversation_id: UUID
    message_id: UUID
    answer: str
    answer_status: Literal["ANSWERED", "INSUFFICIENT_EVIDENCE", "FAILED"]
    citations: list[EnterpriseCitationResponse]
    retrieval: AnswerRetrievalResponse
    error_code: str | None = None
    trace_id: str | None = None


class MessageResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    conversation_id: UUID
    role: str
    content: str
    created_at: datetime
    answer_status: Literal["ANSWERED", "INSUFFICIENT_EVIDENCE", "FAILED"] | None = None
    error_code: str | None = None
    citations: list[EnterpriseCitationResponse] = Field(default_factory=list)


class ConversationDetailResponse(BaseModel):
    conversation: ConversationResponse
    messages: list[MessageResponse]


class FeedbackCreateRequest(BaseModel):
    rating: Literal["UP", "DOWN"]
    comment: str | None = Field(default=None, max_length=5000)


class FeedbackResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    message_id: UUID
    user_id: UUID
    rating: str
    comment: str | None = None
    created_at: datetime
    updated_at: datetime | None = None


class AnswerReportCreateRequest(BaseModel):
    reason_code: str = Field(min_length=1, max_length=100)
    details: str | None = Field(default=None, max_length=10000)


class AnswerReportResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    message_id: UUID
    reporter_user_id: UUID
    reason_code: str
    details: str | None = None
    status: str
    created_at: datetime
    resolution_note: str | None = None
    resolved_by: UUID | None = None
    resolved_at: datetime | None = None


class AnswerReportListResponse(BaseModel):
    items: list[AnswerReportResponse]
    total_count: int
    limit: int
    offset: int


class AnswerReportResolutionRequest(BaseModel):
    status: Literal["RESOLVED", "DISMISSED"]
    resolution_note: str = Field(min_length=1, max_length=10000)


class AuditLogResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    actor_user_id: UUID | None = None
    action: str
    entity_type: str
    entity_id: UUID | None = None
    metadata: dict[str, object]
    created_at: datetime
    request_id: str | None = None
    trace_id: str | None = None


class AuditLogListResponse(BaseModel):
    items: list[AuditLogResponse]
    total_count: int
    limit: int
    offset: int


class AnalyticsSummaryResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    published_documents: int
    draft_documents: int
    archived_documents: int
    pending_jobs: int
    running_jobs: int
    failed_jobs: int
    open_reports: int
    feedback_up: int
    feedback_down: int
    no_answer_rate: float | None = None
