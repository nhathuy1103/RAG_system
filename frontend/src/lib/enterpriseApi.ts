import { supabase } from "./supabase";

const apiUrl = import.meta.env.VITE_API_URL?.trim();

if (!apiUrl) {
  throw new Error("Missing VITE_API_URL");
}

export type DocumentStatus = "DRAFT" | "PUBLISHED" | "ARCHIVED";
export type VersionStatus =
  | "DRAFT"
  | "READY_FOR_REVIEW"
  | "ACTIVE"
  | "REJECTED"
  | "SUPERSEDED";
export type ProcessingStatus = "PENDING" | "RUNNING" | "SUCCEEDED" | "FAILED" | "CANCELLED";
export type DocumentPermission =
  | "READ"
  | "DOWNLOAD"
  | "MANAGE"
  | "REVIEW"
  | "PUBLISH"
  | "ARCHIVE"
  | "MANAGE_PERMISSION";

export interface EnterpriseMe {
  user_id: string;
  email: string | null;
  status: "ACTIVE" | "LOCKED" | "DISABLED";
  roles: Array<{ id: string; code: string; name: string; status: string }>;
  permissions: string[];
  group_ids: string[];
  department_ids: string[];
}

export interface EnterpriseUserProfile {
  user_id: string;
  company_user_id: string | null;
  full_name: string | null;
  status: "ACTIVE" | "LOCKED" | "DISABLED";
  created_at: string | null;
  updated_at: string | null;
}

export interface ProvisionedEmployee extends EnterpriseUserProfile {
  email: string;
}

export interface OrganizationUnit {
  id: string;
  code: string;
  name: string;
  description: string | null;
  status: string;
  parent_department_id?: string | null;
  created_at: string | null;
  updated_at: string | null;
}

export interface FunctionalPermission {
  id: string;
  code: string;
  name: string;
  description: string | null;
  created_at: string | null;
}

export interface UserRoleMembership {
  id: string;
  user_id: string;
  role_id: string;
  role: OrganizationUnit;
  assigned_by: string | null;
  assigned_at: string | null;
}

export interface UserGroupMembership {
  id: string;
  user_id: string;
  group_id: string;
  group: OrganizationUnit;
  added_by: string | null;
  joined_at: string | null;
}

export interface UserDepartmentMembership {
  id: string;
  user_id: string;
  department_id: string;
  department: OrganizationUnit;
  is_primary: boolean;
  start_at: string;
  end_at: string | null;
  assigned_by: string | null;
}

export interface AccessSubject {
  id: string;
  subject_type: "USER" | "ROLE" | "GROUP" | "DEPARTMENT";
  user_id: string | null;
  role_id: string | null;
  group_id: string | null;
  department_id: string | null;
}

export interface EnterpriseAnalyticsSummary {
  published_documents: number;
  draft_documents: number;
  archived_documents: number;
  pending_jobs: number;
  running_jobs: number;
  failed_jobs: number;
  open_reports: number;
  feedback_up: number;
  feedback_down: number;
  no_answer_rate: number | null;
}

export interface EnterpriseAuditLog {
  id: string;
  actor_user_id: string | null;
  action: string;
  entity_type: string;
  entity_id: string | null;
  metadata: Record<string, unknown>;
  created_at: string;
  request_id: string | null;
  trace_id: string | null;
}

export interface EnterpriseAnswerReport {
  id: string;
  message_id: string;
  reporter_user_id: string;
  reason_code: string;
  details: string | null;
  status: "OPEN" | "INVESTIGATING" | "RESOLVED" | "DISMISSED";
  created_at: string;
  resolution_note: string | null;
  resolved_by: string | null;
  resolved_at: string | null;
}

export interface KnowledgeDocument {
  id: string;
  title: string;
  description: string | null;
  document_type: string | null;
  category: string | null;
  document_number: string | null;
  issued_date: string | null;
  effective_date: string | null;
  expiration_date: string | null;
  source: string | null;
  owner_department_id: string | null;
  status: DocumentStatus;
  current_version_id: string | null;
  metadata: Record<string, unknown>;
  created_by: string | null;
  created_at: string | null;
  updated_at: string | null;
  archived_at: string | null;
  archive_reason: string | null;
}

export interface DocumentSearchability {
  document_id: string;
  title: string;
  document_status: string;
  visibility: string;
  current_version_id: string | null;
  version_status: string | null;
  metadata_revision: number;
  chunk_count: number;
  ready_projection_count: number;
  lexical_ready_projection_count: number;
  lexical_stale_count: number;
  embedding_stale_count: number;
  refresh_requested_revision: number | null;
  refresh_processed_at: string | null;
  refresh_error: string | null;
  searchable_for_actor: boolean;
  fully_indexed: boolean;
  blocking_reasons: string[];
  warnings: string[];
}

export interface DocumentVersion {
  id: string;
  document_id: string;
  version_number: number;
  source_file_id: string;
  status: VersionStatus;
  previous_version_id: string | null;
  change_summary: string | null;
  effective_date: string | null;
  created_by: string | null;
  created_at: string | null;
  updated_at: string | null;
}

export interface EnterpriseSourceFile {
  id: string;
  bucket_name: string;
  object_path: string;
  original_file_name: string;
  mime_type: string;
  size_bytes: number;
  sha256: string | null;
  created_by: string;
  created_at: string | null;
}

export interface PermissionAssignment {
  id: string;
  document_id: string;
  subject_id: string;
  subject_type?: "USER" | "ROLE" | "GROUP" | "DEPARTMENT";
  permission: DocumentPermission;
  status: "ACTIVE" | "REVOKED";
  granted_by: string;
  granted_at: string;
  revoked_at: string | null;
}

export interface ProcessingJob {
  id: string;
  document_version_id: string;
  job_type: "INITIAL_PROCESS" | "NEW_VERSION" | "REPROCESS";
  status: ProcessingStatus;
  current_stage: string | null;
  attempt_no: number;
  previous_job_id: string | null;
  requested_at: string | null;
  started_at: string | null;
  completed_at: string | null;
  error_code?: string | null;
  error_message?: string | null;
}

export interface ProcessingStageHistory {
  id: number;
  processing_job_id: string;
  stage: string;
  status: string;
  started_at: string;
  completed_at: string | null;
  message: string | null;
}

export interface ProcessingError {
  id: string;
  processing_job_id: string;
  stage: string | null;
  error_type: string;
  error_code: string;
  safe_message: string;
  retryable: boolean;
  created_at: string;
}

export interface ProcessingJobDetail extends ProcessingJob {
  stage_history: ProcessingStageHistory[];
  errors: ProcessingError[];
}

export interface ReviewSourceFile {
  id: string;
  original_file_name: string;
  mime_type: string;
  size_bytes: number;
  sha256: string | null;
  created_by: string;
  created_at: string | null;
}

export interface ReviewChunk {
  chunk_id: string;
  chunk_index: number;
  content: string;
  page_start: number | null;
  page_end: number | null;
  section_path: string | null;
  metadata: Record<string, unknown>;
}

export interface DocumentVersionReviewContext {
  document: KnowledgeDocument;
  version: DocumentVersion;
  source_file: ReviewSourceFile;
  latest_processing_job: ProcessingJob | null;
  stage_history: ProcessingStageHistory[];
  errors: ProcessingError[];
  extracted_chunks: ReviewChunk[];
}

export interface InitialDocumentUploadResponse {
  document: KnowledgeDocument;
  version: DocumentVersion;
  processing_job: ProcessingJob;
  source_file: EnterpriseSourceFile;
}

export interface Page<T> {
  items: T[];
  total_count: number;
  limit: number;
  offset: number;
}

export interface SearchHit {
  chunk_id: string;
  document_id: string;
  document_version_id: string;
  document_title: string;
  excerpt: string;
  page_number: number | null;
  section_title: string | null;
  score: number;
}

export interface SearchResponse {
  query: string;
  hits: SearchHit[];
  strategy: string;
  trace_id: string;
}

export interface EnterpriseCitation {
  document_id: string;
  document_version_id: string;
  document_title: string;
  chunk_id: string;
  page: number | null;
  section: string | null;
}

export type PublicAnswerStatus = "ANSWERED" | "INSUFFICIENT_EVIDENCE" | "FAILED";

/**
 * Retrieval/generation diagnostics are optional for backward compatibility.
 * Newer backend responses expose them both for a freshly-created answer and
 * when conversation history is loaded again.
 */
export interface AnswerDiagnostics {
  error_code?: string | null;
  gate_reason?: string | null;
  candidate_count?: number | null;
  evidence_count?: number | null;
}

export interface AnswerRetrievalDiagnostics extends AnswerDiagnostics {
  strategy: string;
}

export interface ConversationMessage extends AnswerDiagnostics {
  id: string;
  role: "USER" | "ASSISTANT" | "SYSTEM";
  content: string;
  answer_status?: PublicAnswerStatus | null;
  citations?: EnterpriseCitation[];
  retrieval?: AnswerRetrievalDiagnostics | null;
  created_at: string;
}

export interface EnterpriseConversation {
  id: string;
  title: string;
  messages?: ConversationMessage[];
  created_at: string;
  updated_at: string;
}

export interface AnswerResponse extends AnswerDiagnostics {
  conversation_id: string;
  message_id: string;
  answer: string;
  answer_status: PublicAnswerStatus;
  citations: EnterpriseCitation[];
  retrieval: AnswerRetrievalDiagnostics;
  trace_id?: string;
}

export class EnterpriseApiError extends Error {
  readonly code: string;
  readonly status: number;
  readonly traceId: string | null;
  readonly gateReason: string | null;
  readonly candidateCount: number | null;
  readonly evidenceCount: number | null;

  constructor(
    message: string,
    code: string,
    status: number,
    traceId: string | null,
    diagnostics: AnswerDiagnostics = {},
  ) {
    super(message);
    this.name = "EnterpriseApiError";
    this.code = code;
    this.status = status;
    this.traceId = traceId;
    this.gateReason = diagnostics.gate_reason ?? null;
    this.candidateCount = diagnostics.candidate_count ?? null;
    this.evidenceCount = diagnostics.evidence_count ?? null;
  }
}

const ENTERPRISE_ERROR_MESSAGE_TRANSLATIONS: Record<string, string> = {
  "An identical source is already registered":
    "Tệp này đã được tải lên trước đó. Vui lòng sử dụng tài liệu hiện có hoặc tải tệp dưới dạng phiên bản mới.",
  "An identical source file is already registered":
    "Tệp này đã được tải lên trước đó. Vui lòng sử dụng tài liệu hiện có hoặc tải tệp dưới dạng phiên bản mới.",
};

function translateEnterpriseErrorMessage(message: string): string {
  return ENTERPRISE_ERROR_MESSAGE_TRANSLATIONS[message] || message;
}

async function enterpriseFetch<T>(path: string, init: RequestInit = {}): Promise<T> {
  const {
    data: { session },
  } = await supabase.auth.getSession();
  if (!session) {
    throw new EnterpriseApiError("Phiên đăng nhập đã hết hạn", "UNAUTHENTICATED", 401, null);
  }

  const isMultipart = typeof FormData !== "undefined" && init.body instanceof FormData;
  const response = await fetch(`${apiUrl}${path}`, {
    ...init,
    headers: {
      Authorization: `Bearer ${session.access_token}`,
      ...(init.body && !isMultipart ? { "Content-Type": "application/json" } : {}),
      ...init.headers,
    },
  });

  const payload = response.status === 204 ? null : await response.json().catch(() => null);
  if (!response.ok) {
    const error = payload?.error;
    const diagnostics = error?.diagnostics || error || payload || {};
    const message =
      error?.message || payload?.detail || `Yêu cầu thất bại (${response.status})`;
    throw new EnterpriseApiError(
      translateEnterpriseErrorMessage(message),
      error?.code || "REQUEST_FAILED",
      response.status,
      error?.trace_id || response.headers.get("x-request-id"),
      {
        gate_reason: diagnostics?.gate_reason ?? null,
        candidate_count: diagnostics?.candidate_count ?? null,
        evidence_count: diagnostics?.evidence_count ?? null,
      },
    );
  }
  return payload as T;
}

function queryString(values: Record<string, string | number | null | undefined>): string {
  const params = new URLSearchParams();
  for (const [key, value] of Object.entries(values)) {
    if (value !== null && value !== undefined && value !== "") params.set(key, String(value));
  }
  const query = params.toString();
  return query ? `?${query}` : "";
}

export const getEnterpriseMe = () => enterpriseFetch<EnterpriseMe>("/api/v1/me");

export const listEnterpriseUsers = (limit = 100, offset = 0) =>
  enterpriseFetch<Page<EnterpriseUserProfile>>(
    `/api/v1/users${queryString({ limit, offset })}`,
  );

export const provisionEnterpriseEmployee = (body: {
  email: string;
  temporary_password: string;
  company_user_id?: string;
  full_name?: string;
}) =>
  enterpriseFetch<ProvisionedEmployee>("/api/v1/users/provision", {
    method: "POST",
    body: JSON.stringify(body),
  });

export const listEnterpriseRoles = () =>
  enterpriseFetch<OrganizationUnit[]>("/api/v1/roles");

export const listEnterpriseFunctionalPermissions = () =>
  enterpriseFetch<FunctionalPermission[]>("/api/v1/functional-permissions");

export const listEnterpriseRolePermissions = (roleId: string) =>
  enterpriseFetch<FunctionalPermission[]>(`/api/v1/roles/${roleId}/permissions`);

export const assignEnterpriseRolePermission = (roleId: string, permissionId: string) =>
  enterpriseFetch<{ message: string }>(`/api/v1/roles/${roleId}/permissions`, {
    method: "POST",
    body: JSON.stringify({ object_id: permissionId }),
  });

export const removeEnterpriseRolePermission = (roleId: string, permissionId: string) =>
  enterpriseFetch<{ message: string }>(
    `/api/v1/roles/${roleId}/permissions/${permissionId}`,
    { method: "DELETE" },
  );

export const listEnterpriseGroups = () =>
  enterpriseFetch<OrganizationUnit[]>("/api/v1/groups");

export const listEnterpriseDepartments = () =>
  enterpriseFetch<OrganizationUnit[]>("/api/v1/departments");

export const listEnterpriseAccessSubjects = (
  subjectType?: AccessSubject["subject_type"],
) =>
  enterpriseFetch<AccessSubject[]>(
    `/api/v1/access-subjects${queryString({ type: subjectType })}`,
  );

export const createEnterpriseOrganization = (
  kind: "roles" | "groups" | "departments",
  body: { code: string; name: string; description?: string; parent_department_id?: string },
) =>
  enterpriseFetch<OrganizationUnit>(`/api/v1/${kind}`, {
    method: "POST",
    body: JSON.stringify(body),
  });

export const assignEnterpriseMembership = (
  userId: string,
  kind: "roles" | "groups" | "departments",
  objectId: string,
  isPrimary = false,
) =>
  enterpriseFetch<{ message: string }>(`/api/v1/users/${userId}/${kind}`, {
    method: "POST",
    body: JSON.stringify({ object_id: objectId, is_primary: isPrimary }),
  });

export const listEnterpriseUserRoles = (userId: string) =>
  enterpriseFetch<UserRoleMembership[]>(`/api/v1/users/${userId}/roles`);

export const listEnterpriseUserGroups = (userId: string) =>
  enterpriseFetch<UserGroupMembership[]>(`/api/v1/users/${userId}/groups`);

export const listEnterpriseUserDepartments = (userId: string, includeInactive = false) =>
  enterpriseFetch<UserDepartmentMembership[]>(
    `/api/v1/users/${userId}/departments${queryString({ include_inactive: String(includeInactive) })}`,
  );

export const removeEnterpriseMembership = (
  userId: string,
  kind: "roles" | "groups" | "departments",
  objectId: string,
) => enterpriseFetch<{ message: string }>(`/api/v1/users/${userId}/${kind}/${objectId}`, {
  method: "DELETE",
});

export const updateEnterpriseUser = (
  userId: string,
  body: Partial<Pick<EnterpriseUserProfile, "company_user_id" | "full_name" | "status">>,
) => enterpriseFetch<EnterpriseUserProfile>(`/api/v1/users/${userId}`, {
  method: "PATCH",
  body: JSON.stringify(body),
});

export const getEnterpriseAnalytics = () =>
  enterpriseFetch<EnterpriseAnalyticsSummary>("/api/v1/analytics/summary");

export const listEnterpriseAuditLogs = (limit = 50, offset = 0) =>
  enterpriseFetch<Page<EnterpriseAuditLog>>(
    `/api/v1/audit-logs${queryString({ limit, offset })}`,
  );

export const listEnterpriseAnswerReports = (
  status?: EnterpriseAnswerReport["status"],
  limit = 50,
  offset = 0,
) =>
  enterpriseFetch<Page<EnterpriseAnswerReport>>(
    `/api/v1/answer-reports${queryString({ status, limit, offset })}`,
  );

export const resolveEnterpriseAnswerReport = (
  reportId: string,
  status: "RESOLVED" | "DISMISSED",
  resolutionNote: string,
) =>
  enterpriseFetch<EnterpriseAnswerReport>(`/api/v1/answer-reports/${reportId}`, {
    method: "PATCH",
    body: JSON.stringify({ status, resolution_note: resolutionNote }),
  });

export const listKnowledgeDocuments = (options: {
  status?: DocumentStatus;
  limit?: number;
  offset?: number;
} = {}) =>
  enterpriseFetch<Page<KnowledgeDocument>>(
    `/api/v1/documents${queryString({ limit: 50, offset: 0, ...options })}`,
  );

export const getKnowledgeDocument = (documentId: string) =>
  enterpriseFetch<KnowledgeDocument>(`/api/v1/documents/${documentId}`);

export const createKnowledgeDocument = (body: Partial<KnowledgeDocument> & { title: string }) =>
  enterpriseFetch<KnowledgeDocument>("/api/v1/documents", {
    method: "POST",
    body: JSON.stringify(body),
  });

export const listDocumentSearchability = (documentId?: string) =>
  enterpriseFetch<DocumentSearchability[]>(
    "/api/v1/documents/searchability" + queryString({ document_id: documentId }),
  );

export const uploadEnterpriseSourceFile = (file: File) => {
  const body = new FormData();
  body.append("file", file);
  return enterpriseFetch<EnterpriseSourceFile>("/api/v1/source-files", {
    method: "POST",
    body,
  });
};

export const uploadInitialKnowledgeDocument = (
  file: File,
  body: {
    title: string;
    description?: string;
    document_type?: string;
    category?: string;
    metadata?: Record<string, unknown>;
    change_summary?: string;
    effective_date?: string;
  },
) => {
  const form = new FormData();
  form.append("file", file);
  form.append("title", body.title);
  if (body.description) form.append("description", body.description);
  if (body.document_type) form.append("document_type", body.document_type);
  if (body.category) form.append("category", body.category);
  if (body.change_summary) form.append("change_summary", body.change_summary);
  if (body.effective_date) form.append("effective_date", body.effective_date);
  form.append("metadata_json", JSON.stringify(body.metadata ?? {}));
  return enterpriseFetch<InitialDocumentUploadResponse>("/api/v1/documents/upload", {
    method: "POST",
    body: form,
  });
};

export const updateKnowledgeDocument = (
  id: string,
  body: Partial<KnowledgeDocument> & { expected_updated_at: string },
) =>
  enterpriseFetch<KnowledgeDocument>(`/api/v1/documents/${id}`, {
    method: "PATCH",
    body: JSON.stringify(body),
  });

export const listDocumentVersions = (documentId: string) =>
  enterpriseFetch<DocumentVersion[]>(`/api/v1/documents/${documentId}/versions`).then((items) => ({
    items,
    total_count: items.length,
    limit: items.length,
    offset: 0,
  }));

export const createDocumentVersion = (
  documentId: string,
  body: { source_file_id: string; change_summary?: string; effective_date?: string },
) =>
  enterpriseFetch<DocumentVersion>(`/api/v1/documents/${documentId}/versions`, {
    method: "POST",
    body: JSON.stringify(body),
  });

export const getDocumentVersionReviewContext = (versionId: string) =>
  enterpriseFetch<DocumentVersionReviewContext>(
    `/api/v1/document-versions/${versionId}/review-context`,
  );

export const reviewDocumentVersion = (
  versionId: string,
  body: { decision: "APPROVE" | "REJECT" | "REPROCESS"; note?: string; rejection_reason?: string },
) =>
  enterpriseFetch<DocumentVersion>(`/api/v1/document-versions/${versionId}/review`, {
    method: "POST",
    body: JSON.stringify(body),
  });

export const publishDocumentVersion = (versionId: string) =>
  enterpriseFetch<DocumentVersion>(`/api/v1/document-versions/${versionId}/publish`, {
    method: "POST",
  });

export const archiveKnowledgeDocument = (documentId: string, reason: string) =>
  enterpriseFetch<KnowledgeDocument>(`/api/v1/documents/${documentId}/archive`, {
    method: "POST",
    body: JSON.stringify({ reason }),
  });

export const listDocumentPermissions = (documentId: string) =>
  enterpriseFetch<PermissionAssignment[]>(`/api/v1/documents/${documentId}/permissions`).then((items) => ({
    items,
    total_count: items.length,
    limit: items.length,
    offset: 0,
  }));

export const grantDocumentPermission = (
  documentId: string,
  body: { subject_id: string; permission: DocumentPermission },
) =>
  enterpriseFetch<PermissionAssignment>(`/api/v1/documents/${documentId}/permissions`, {
    method: "POST",
    body: JSON.stringify(body),
  });

export const revokeDocumentPermission = (
  documentId: string,
  subjectId: string,
  permission: DocumentPermission,
) =>
  enterpriseFetch<void>(
    `/api/v1/documents/${documentId}/permissions${queryString({
      subject_id: subjectId,
      permission,
    })}`,
    { method: "DELETE" },
  );

export const testDocumentPermission = (documentId: string, userId: string, permission: DocumentPermission) =>
  enterpriseFetch<{ allowed: boolean; sources?: string[] }>(
    `/api/v1/documents/${documentId}/permissions/test`,
    { method: "POST", body: JSON.stringify({ user_id: userId, permission }) },
  );

export const listProcessingJobs = (options: {
  document_id?: string;
  document_version_id?: string;
  status?: ProcessingStatus;
  limit?: number;
  offset?: number;
} = {}) =>
  enterpriseFetch<Page<ProcessingJob>>(
    `/api/v1/processing-jobs${queryString({ limit: 50, offset: 0, ...options })}`,
  );

export const getProcessingJob = (jobId: string) =>
  enterpriseFetch<ProcessingJobDetail>(`/api/v1/processing-jobs/${jobId}`);

export const retryProcessingJob = (jobId: string) =>
  enterpriseFetch<ProcessingJob>(`/api/v1/processing-jobs/${jobId}/retry`, { method: "POST" });

export const searchKnowledge = (query: string, filters: Record<string, unknown> = {}) =>
  enterpriseFetch<{ items: Array<{
    chunk_id: string;
    document_id: string;
    document_version_id: string;
    title: string;
    content: string;
    score: number;
    page_start: number | null;
    section_path: string | null;
  }> }>("/api/v1/search", {
    method: "POST",
    body: JSON.stringify({ query, filters }),
  }).then((response): SearchResponse => ({
    query,
    strategy: "SECURE_SPARSE_FAST_PATH",
    trace_id: "",
    hits: response.items.map((item) => ({
      chunk_id: item.chunk_id,
      document_id: item.document_id,
      document_version_id: item.document_version_id,
      document_title: item.title,
      excerpt: item.content,
      page_number: item.page_start,
      section_title: item.section_path,
      score: item.score,
    })),
  }));

export const createEnterpriseConversation = (title?: string) =>
  enterpriseFetch<EnterpriseConversation>("/api/v1/conversations", {
    method: "POST",
    body: JSON.stringify({ title }),
  });

export const getEnterpriseConversation = (conversationId: string) =>
  enterpriseFetch<{ conversation: EnterpriseConversation; messages: ConversationMessage[] }>(
    `/api/v1/conversations/${conversationId}`,
  ).then((response) => ({
    ...response.conversation,
    messages: response.messages.map((message) => normalizeConversationMessage(message)),
  }));

function normalizeAnswerDiagnostics<T extends AnswerDiagnostics & {
  retrieval?: AnswerRetrievalDiagnostics | null;
}>(value: T): T {
  const retrieval = value.retrieval;
  return {
    ...value,
    error_code: value.error_code ?? retrieval?.error_code ?? null,
    gate_reason: value.gate_reason ?? retrieval?.gate_reason ?? null,
    candidate_count: value.candidate_count ?? retrieval?.candidate_count ?? null,
    evidence_count: value.evidence_count ?? retrieval?.evidence_count ?? null,
  };
}

function normalizeConversationMessage(message: ConversationMessage): ConversationMessage {
  return normalizeAnswerDiagnostics(message);
}

export const askEnterpriseQuestion = (
  conversationId: string,
  question: string,
  filters: Record<string, unknown> = {},
) =>
  enterpriseFetch<AnswerResponse>(`/api/v1/conversations/${conversationId}/messages`, {
    method: "POST",
    body: JSON.stringify({ content: question, filters }),
  }).then((response) => normalizeAnswerDiagnostics(response));

export const getDocumentVersionSource = (documentId: string, versionId: string) =>
  enterpriseFetch<{ signed_url: string; expires_at: string; original_file_name: string; mime_type: string }>(
    `/api/v1/documents/${documentId}/versions/${versionId}/source`,
  );

export const submitAnswerFeedback = (messageId: string, rating: "UP" | "DOWN", comment?: string) =>
  enterpriseFetch<void>(`/api/v1/answers/${messageId}/feedback`, {
    method: "POST",
    body: JSON.stringify({ rating, comment }),
  });

export const reportAnswer = (messageId: string, reasonCode: string, details?: string) =>
  enterpriseFetch<void>(`/api/v1/answers/${messageId}/reports`, {
    method: "POST",
    body: JSON.stringify({ reason_code: reasonCode, details }),
  });

export type EnterpriseDocumentRelationType =
  | "exact_content"
  | "near_duplicate"
  | "version_candidate"
  | "version"
  | "conflict_candidate"
  | "conflict"
  | "related"
  | "distinct"
  | "technical_duplicate"
  | "template_variant"
  | "temporal_series";

export type EnterpriseDocumentRelationStatus =
  | "pending"
  | "deferred"
  | "auto_confirmed"
  | "confirmed"
  | "dismissed";

export type EnterpriseDocumentRelationAction =
  | "confirm_duplicate"
  | "mark_version"
  | "confirm_conflict"
  | "keep_separate"
  | "prefer_source"
  | "prefer_target"
  | "dismiss"
  | "defer_review";

export interface EnterpriseDocumentRelation {
  id: string;
  source_document_id: string;
  target_document_id: string;
  relation_type: EnterpriseDocumentRelationType;
  status: EnterpriseDocumentRelationStatus;
  confidence: number;
  reason: string | null;
  created_at: string;
  updated_at: string;
  resolution_action: EnterpriseDocumentRelationAction | null;
}

export interface EnterpriseDocumentRelationEvidence {
  relation_id: string;
  source_document: {
    id: string;
    title: string;
    version_number: number;
    text_content: string;
  };
  target_document: {
    id: string;
    title: string;
    version_number: number;
    text_content: string;
  };
  overlaps: Array<{
    source_text: string;
    target_text: string;
  }>;
}

const ENTERPRISE_RELATION_STORAGE_KEY = "enterprise-document-relations-demo-v4";
export const ENTERPRISE_RELATIONS_UPDATED_EVENT = "enterprise-relations-updated";

const enterpriseRelationSeed: EnterpriseDocumentRelation[] = [
  {
    id: "mock-rel-1",
    source_document_id: "doc-1",
    target_document_id: "doc-2",
    relation_type: "conflict",
    status: "pending",
    confidence: 0.95,
    reason: null,
    created_at: "2026-08-10T16:27:28.000Z",
    updated_at: "2026-08-10T16:27:28.000Z",
    resolution_action: null,
  },
  {
    id: "mock-rel-2",
    source_document_id: "doc-3",
    target_document_id: "doc-4",
    relation_type: "near_duplicate",
    status: "pending",
    confidence: 0.88,
    reason: null,
    created_at: "2026-08-09T16:27:28.000Z",
    updated_at: "2026-08-09T16:27:28.000Z",
    resolution_action: null,
  },
];

let enterpriseRelationMemory = enterpriseRelationSeed.map((item) => ({ ...item }));

function isEnterpriseRelation(value: unknown): value is EnterpriseDocumentRelation {
  if (!value || typeof value !== "object") return false;
  const relation = value as Partial<EnterpriseDocumentRelation>;
  return (
    typeof relation.id === "string"
    && typeof relation.source_document_id === "string"
    && typeof relation.target_document_id === "string"
    && typeof relation.relation_type === "string"
    && typeof relation.status === "string"
    && typeof relation.confidence === "number"
    && typeof relation.created_at === "string"
  );
}

function readEnterpriseRelations(): EnterpriseDocumentRelation[] {
  if (typeof window === "undefined") {
    return enterpriseRelationMemory.map((item) => ({ ...item }));
  }
  try {
    const stored = window.localStorage.getItem(ENTERPRISE_RELATION_STORAGE_KEY);
    if (stored) {
      const parsed: unknown = JSON.parse(stored);
      if (Array.isArray(parsed) && parsed.every(isEnterpriseRelation)) {
        enterpriseRelationMemory = parsed.map((item) => ({
          ...item,
          updated_at: item.updated_at || item.created_at,
          resolution_action: item.resolution_action || null,
        }));
        return enterpriseRelationMemory.map((item) => ({ ...item }));
      }
    }
    window.localStorage.setItem(
      ENTERPRISE_RELATION_STORAGE_KEY,
      JSON.stringify(enterpriseRelationMemory),
    );
  } catch {
    // The in-memory copy still keeps the demo usable when storage is blocked.
  }
  return enterpriseRelationMemory.map((item) => ({ ...item }));
}

function writeEnterpriseRelations(relations: EnterpriseDocumentRelation[]) {
  enterpriseRelationMemory = relations.map((item) => ({ ...item }));
  if (typeof window === "undefined") return;
  try {
    window.localStorage.setItem(
      ENTERPRISE_RELATION_STORAGE_KEY,
      JSON.stringify(enterpriseRelationMemory),
    );
  } catch {
    // Keep the decision in memory for storage-restricted browser sessions.
  }
  window.dispatchEvent(new Event(ENTERPRISE_RELATIONS_UPDATED_EVENT));
}

export async function listEnterpriseRelations(): Promise<{ items: EnterpriseDocumentRelation[] }> {
  return { items: readEnterpriseRelations() };
}

export async function getEnterpriseRelationEvidence(relationId: string): Promise<EnterpriseDocumentRelationEvidence> {
  return {
    relation_id: relationId,
    source_document: {
      id: "doc-1",
      title: "Chính sách nhân sự 2024.pdf",
      version_number: 2,
      text_content: "Công ty hỗ trợ 100% chi phí ăn trưa cho nhân viên khối văn phòng. Phụ cấp đi lại là 500k/tháng.",
    },
    target_document: {
      id: "doc-2",
      title: "Quy định phụ cấp 2024.docx",
      version_number: 1,
      text_content: "Công ty hỗ trợ 50% chi phí ăn trưa cho nhân viên khối văn phòng. Phụ cấp đi lại là 300k/tháng.",
    },
    overlaps: [
      {
        source_text: "100% chi phí ăn trưa ... 500k/tháng",
        target_text: "50% chi phí ăn trưa ... 300k/tháng",
      }
    ]
  };
}

export async function resolveEnterpriseRelation(
  relationId: string,
  action: EnterpriseDocumentRelationAction,
  reason: string,
): Promise<EnterpriseDocumentRelation> {
  const relations = readEnterpriseRelations();
  const current = relations.find((relation) => relation.id === relationId);
  if (!current) throw new Error("Không tìm thấy vấn đề cần xử lý.");
  if (current.status !== "pending" && current.status !== "deferred") {
    throw new Error("Vấn đề này đã được xử lý. Hãy tải lại danh sách trước khi quyết định.");
  }

  const normalizedReason = reason.trim();
  if (action !== "defer_review" && !normalizedReason) {
    throw new Error("Vui lòng nhập lý do cho quyết định.");
  }

  let relationType = current.relation_type;
  let status: EnterpriseDocumentRelationStatus = "confirmed";
  if (action === "confirm_duplicate") relationType = "exact_content";
  if (action === "mark_version") relationType = "version";
  if (["confirm_conflict", "prefer_source", "prefer_target"].includes(action)) {
    relationType = "conflict";
  }
  if (action === "keep_separate") relationType = "distinct";
  if (action === "dismiss") status = "dismissed";
  if (action === "defer_review") status = "deferred";

  const updated: EnterpriseDocumentRelation = {
    ...current,
    relation_type: relationType,
    status,
    reason: action === "defer_review"
      ? normalizedReason || "Người dùng chọn xử lý sau."
      : normalizedReason,
    updated_at: new Date().toISOString(),
    resolution_action: action,
  };
  writeEnterpriseRelations(
    relations.map((relation) => (relation.id === relationId ? updated : relation)),
  );
  return { ...updated };
}
