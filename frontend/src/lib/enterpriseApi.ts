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

export interface ConversationMessage {
  id: string;
  role: "USER" | "ASSISTANT" | "SYSTEM";
  content: string;
  answer_status?: "ANSWERED" | "INSUFFICIENT_EVIDENCE" | "FAILED";
  citations?: EnterpriseCitation[];
  created_at: string;
}

export interface EnterpriseConversation {
  id: string;
  title: string;
  messages?: ConversationMessage[];
  created_at: string;
  updated_at: string;
}

export interface AnswerResponse {
  conversation_id: string;
  message_id: string;
  answer: string;
  answer_status: "ANSWERED" | "INSUFFICIENT_EVIDENCE" | "FAILED";
  citations: EnterpriseCitation[];
  retrieval: { strategy: string };
  trace_id?: string;
}

export class EnterpriseApiError extends Error {
  readonly code: string;
  readonly status: number;
  readonly traceId: string | null;

  constructor(message: string, code: string, status: number, traceId: string | null) {
    super(message);
    this.name = "EnterpriseApiError";
    this.code = code;
    this.status = status;
    this.traceId = traceId;
  }
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
    throw new EnterpriseApiError(
      error?.message || payload?.detail || `Yêu cầu thất bại (${response.status})`,
      error?.code || "REQUEST_FAILED",
      response.status,
      error?.trace_id || response.headers.get("x-request-id"),
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

export const createKnowledgeDocument = (body: Partial<KnowledgeDocument> & { title: string }) =>
  enterpriseFetch<KnowledgeDocument>("/api/v1/documents", {
    method: "POST",
    body: JSON.stringify(body),
  });

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
  ).then((response) => ({ ...response.conversation, messages: response.messages }));

export const askEnterpriseQuestion = (
  conversationId: string,
  question: string,
  filters: Record<string, unknown> = {},
) =>
  enterpriseFetch<AnswerResponse>(`/api/v1/conversations/${conversationId}/messages`, {
    method: "POST",
    body: JSON.stringify({ content: question, filters }),
  });

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
