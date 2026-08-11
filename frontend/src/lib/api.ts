import { supabase } from "./supabase";

const apiUrl = import.meta.env.VITE_API_URL?.trim();

if (!apiUrl) {
  throw new Error("Missing VITE_API_URL");
}

export interface SupabaseUserResponse {
  user_id: string;
  email: string | null;
  role: string | null;
}

export interface Notebook {
  id: string;
  owner_id: string;
  title: string;
  description: string;
  is_active: boolean;
  created_at: string;
  updated_at: string;
}

export interface UploadedDocument {
  id: string;
  owner_id: string;
  notebook_id: string;
  original_filename: string;
  storage_bucket: string;
  storage_object_path: string;
  mime_type: string;
  size_bytes: number;
  content_hash: string | null;
  status: string;
  error_message: string | null;
  is_active: boolean;
  created_at: string;
  updated_at: string;
  normalized_content_hash: string | null;
  normalization_version: string | null;
  loose_content_signature: string | null;
  canonical_document_id: string | null;
  version_group_id: string | null;
  version_number: number;
  effective_from: string | null;
  effective_to: string | null;
  supersedes_document_id: string | null;
  is_current: boolean;
  quality_status: string;
}

export type DocumentRelationType =
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

export type DocumentRelationStatus =
  | "pending"
  | "auto_confirmed"
  | "confirmed"
  | "dismissed";

export type DocumentRelationAction =
  | "confirm_duplicate"
  | "mark_version"
  | "confirm_conflict"
  | "keep_separate"
  | "prefer_source"
  | "prefer_target"
  | "dismiss";

export interface DocumentRelation {
  id: string;
  owner_id: string;
  notebook_id: string;
  source_document_id: string;
  target_document_id: string;
  relation_type: DocumentRelationType;
  status: DocumentRelationStatus;
  confidence: number;
  signals: Record<string, unknown>;
  reason: string | null;
  detector_version: string;
  preferred_document_id: string | null;
  resolved_by: string | null;
  resolved_at: string | null;
  created_at: string;
  updated_at: string;
}

export interface DocumentRelationListResponse {
  items: DocumentRelation[];
  total_count: number;
  limit: number;
  offset: number;
}

export interface RelationEvidenceDocument {
  id: string;
  original_filename: string;
  quality_status: string;
  version_number: number;
  is_current: boolean;
  canonical_document_id: string | null;
}

export interface RelationEvidenceChunk {
  id: string;
  document_id: string;
  chunk_index: number;
  content: string;
  page_number: number | null;
  section_title: string | null;
  normalized_content_hash: string | null;
  exact_duplicate_group_id: string | null;
}

export interface RelationEvidenceChunkPair {
  source_chunk: RelationEvidenceChunk | null;
  target_chunk: RelationEvidenceChunk | null;
  evidence_type: string;
  confidence: number;
  signals: Record<string, unknown>;
  reason: string | null;
}

export interface RelationEvidenceBlock {
  id: string;
  document_id: string;
  block_index: number;
  block_type: string;
  text: string;
  page_number: number | null;
  cells: string[];
  highlight_type: string | null;
  matched_pair_index: number | null;
  confidence: number | null;
  reason: string | null;
}

export interface DocumentRelationEvidence {
  relation: DocumentRelation;
  source_document: RelationEvidenceDocument | null;
  target_document: RelationEvidenceDocument | null;
  chunk_pairs: RelationEvidenceChunkPair[];
  source_original_blocks: RelationEvidenceBlock[];
  target_original_blocks: RelationEvidenceBlock[];
}

export interface KnowledgeQualityAudit {
  id: number;
  owner_id: string;
  notebook_id: string;
  relation_id: string | null;
  actor_id: string | null;
  action: string;
  reason: string | null;
  before_state: Record<string, unknown>;
  after_state: Record<string, unknown>;
  created_at: string;
}

export interface KnowledgeQualityAuditListResponse {
  items: KnowledgeQualityAudit[];
  total_count: number;
  limit: number;
  offset: number;
}

export type StructuredClaimRelationType =
  | "unchanged"
  | "updated"
  | "added"
  | "removed"
  | "equivalent"
  | "source_updates_target"
  | "target_updates_source"
  | "source_supersedes_target"
  | "target_supersedes_source"
  | "source_contains_target"
  | "target_contains_source"
  | "source_only"
  | "target_only"
  | "conflict_candidate"
  | "conflict"
  | "conditional_variant"
  | "distinct"
  | "uncertain";

export type StructuredClaimReviewStatus =
  | "pending"
  | "auto_confirmed"
  | "confirmed"
  | "dismissed";

export type StructuredClaimResolutionAction =
  | "confirm"
  | "confirm_equivalent"
  | "confirm_update"
  | "confirm_conflict"
  | "confirm_conditional_variant"
  | "dismiss";

export interface StructuredClaimRelation {
  id: string;
  owner_id: string;
  notebook_id: string;
  source_snapshot_id: string;
  target_snapshot_id: string;
  source_claim_id: string | null;
  target_claim_id: string | null;
  relation_type: StructuredClaimRelationType;
  scope_relation: string;
  qualifier_compatibility: string;
  temporal_compatibility: string;
  confidence: number;
  evidence: Record<string, unknown>;
  reason: string | null;
  detector_name: string;
  detector_version: string;
  review_status: StructuredClaimReviewStatus;
  resolved_by: string | null;
  resolved_at: string | null;
  created_at: string;
  updated_at: string;
}

export interface StructuredClaimRelationListResponse {
  items: StructuredClaimRelation[];
  total_count: number;
  limit: number;
  offset: number;
}

export interface StructuredFactSnapshotEvidence {
  id: string;
  document_id: string;
  source_chunk_id: string | null;
  snapshot_key: string;
  schema_fingerprint: string;
  template_fingerprint: string | null;
  table_index: number;
  page_from: number | null;
  page_to: number | null;
  source_locator: Record<string, unknown>;
  normalized_schema: Record<string, unknown> | unknown[];
  row_count: number;
  column_count: number;
  extractor_name: string;
  extractor_version: string;
  publication_time: string | null;
  effective_from: string | null;
  effective_to: string | null;
  observed_at: string | null;
  ingested_at: string;
  source_publisher: string | null;
  source_type: string;
  authority_level: number | null;
  authority_metadata: Record<string, unknown>;
  warnings: unknown[];
  extraction_confidence: number;
  created_at: string;
  updated_at: string;
}

export interface StructuredFactClaimEvidence {
  id: string;
  document_id: string;
  snapshot_id: string;
  source_chunk_id: string | null;
  claim_key: string;
  row_identity: string;
  row_identity_hash: string;
  row_index: number;
  data_row_ordinal: number | null;
  page_number: number | null;
  source_text: string | null;
  source_cells: unknown[];
  provenance: Record<string, unknown>;
  subject_identity: Record<string, unknown>;
  subject_identity_hash: string;
  candidate_identity_hash: string;
  predicate: string;
  value_type: string;
  normalized_value: Record<string, unknown>;
  numeric_value: string | null;
  unit: string | null;
  currency: string | null;
  qualifiers: Record<string, unknown>;
  qualifier_hash: string;
  publication_time: string | null;
  effective_from: string | null;
  effective_to: string | null;
  observed_at: string | null;
  ingested_at: string;
  source_publisher: string | null;
  source_type: string;
  authority_level: number | null;
  authority_metadata: Record<string, unknown>;
  confidence: number;
  is_derived: boolean;
  derivation: Record<string, unknown>;
  extractor_version: string;
  created_at: string;
  updated_at: string;
}

export interface StructuredClaimRelationEvidence {
  relation: StructuredClaimRelation;
  source_snapshot: StructuredFactSnapshotEvidence;
  target_snapshot: StructuredFactSnapshotEvidence;
  source_claim: StructuredFactClaimEvidence | null;
  target_claim: StructuredFactClaimEvidence | null;
}

export interface DocumentUploadItem {
  filename: string;
  document: UploadedDocument | null;
  error_code: string | null;
  error_message: string | null;
  // True when `document` is a pre-existing document reused because this
  // file's content is byte-identical to one already in the notebook.
  duplicate: boolean;
}

export interface DocumentUploadBatchResponse {
  total_count: number;
  succeeded_count: number;
  failed_count: number;
  items: DocumentUploadItem[];
}

export interface DocumentListResponse {
  items: UploadedDocument[];
  total_count: number;
  limit: number;
  offset: number;
}

export interface ExtractionElement {
  element_id: string;
  block_type: string;
  text: string;
  page_number: number | null;
  metadata: Record<string, unknown>;
  bbox: Record<string, unknown> | null;
  confidence: number | null;
  rotation: number;
  provenance: Record<string, unknown>;
}

export interface ExtractionPage {
  page_number: number;
  text: string;
  elements: ExtractionElement[];
  metadata: Record<string, unknown>;
  width: number | null;
  height: number | null;
  rotation: number;
}

export interface ExtractionSection {
  text: string;
  page_number: number | null;
  title: string | null;
  level: number;
  block_ids: string[];
}

export interface ExtractionTable {
  table_id: string;
  location: string;
  rows: string[][];
  columns: number;
  header: string[];
  warnings: string[];
  cells: Record<string, unknown>[];
  bbox: Record<string, unknown> | null;
  confidence: number | null;
  metadata: Record<string, unknown>;
}

export interface ExtractionChunk {
  chunk_id: string;
  chunk_index: number;
  text: string;
  embedding_text: string;
  search_text: string;
  character_count: number;
  estimated_token_count: number;
  page_number: number | null;
  section_title: string | null;
  section_id: string | null;
  offset_start: number;
  offset_end: number;
  strategy: string;
  strategy_version: string;
  config_checksum: string;
  checksum: string;
  content_checksum: string;
  source_block_ids: string[];
  table_identity: string | null;
  retrieval_metadata: Record<string, unknown>;
  metadata: Record<string, unknown>;
}

export interface ExtractionInspectionResponse {
  source: {
    filename: string;
    mime_type: string;
    extension: string;
    size_bytes: number;
    checksum: string;
  };
  summary: {
    parser_name: string;
    parser_version: string;
    detected_language: string;
    ocr_used: boolean;
    index_allowed: boolean;
    quality_status: string;
    quality_action: string;
    page_count: number;
    section_count: number;
    table_count: number;
    element_count: number;
    image_count: number;
    text_characters: number;
    chunk_count: number;
    quality_mode: string;
    ocr_enabled: boolean;
  };
  content: { text: string; markdown: string };
  chunking: {
    status: string;
    strategy: string;
    chunk_size: number;
    chunk_overlap: number;
    chunk_count: number;
    contextual_enrichment_applied: boolean;
    production_contextual_enrichment_enabled: boolean;
    embedding_applied: boolean;
    note: string;
  };
  chunks: ExtractionChunk[];
  parsed_document: {
    pages: ExtractionPage[];
    sections: ExtractionSection[];
    tables: ExtractionTable[];
    images_metadata: Record<string, unknown>[];
    document_metadata: Record<string, unknown>;
    warnings: string[];
    parser_name: string;
    parser_version: string;
    confidence: number | null;
    ocr_used: boolean;
    detected_language: string;
  };
  quality_report: Record<string, unknown>;
  quality_decision: Record<string, unknown>;
  canonical_ir: Record<string, unknown> | null;
  canonical_ir_validation: Record<string, unknown> | null;
  canonical_ir_artifact: Record<string, unknown> | null;
  phases: Record<string, unknown>;
  adaptive_routing: Record<string, unknown>;
}

export interface Profile {
  id: string;
  email: string | null;
  display_name: string | null;
  avatar_url: string | null;
  role: string;
  created_at: string;
  updated_at: string;
}

export interface AdminUserCount {
  total_users: number;
}

export interface AdminAuthEventDay {
  day: string;
  signups: number;
  logins: number;
  logouts: number;
}

export interface AdminAuthEventsResponse {
  days: AdminAuthEventDay[];
}

export interface AdminAuditLogEntry {
  created_at: string;
  action: string | null;
  email: string | null;
}

export interface AdminAuditLogResponse {
  entries: AdminAuditLogEntry[];
}

async function authenticatedFetch(
  path: string,
  init?: RequestInit,
): Promise<Response> {
  const {
    data: { session },
  } = await supabase.auth.getSession();

  if (!session) {
    throw new Error("User chưa đăng nhập");
  }

  const headers = new Headers(init?.headers);
  headers.set("Authorization", `Bearer ${session.access_token}`);

  if (init?.body && !(init.body instanceof FormData) && !headers.has("Content-Type")) {
    headers.set("Content-Type", "application/json");
  }

  return fetch(`${apiUrl}${path}`, {
    ...init,
    headers,
  });
}

export class ApiRequestError extends Error {
  status: number;
  body: unknown;

  constructor(message: string, status: number, body: unknown) {
    super(message);
    this.name = "ApiRequestError";
    this.status = status;
    this.body = body;
  }
}

function responseErrorMessage(body: unknown): string | null {
  if (typeof body === "string") return body || null;
  if (typeof body !== "object" || body === null) return null;
  const record = body as Record<string, unknown>;
  if (typeof record.message === "string") return record.message;
  if (typeof record.detail === "string") return record.detail;
  return null;
}

async function readJson<T>(response: Response): Promise<T> {
  if (!response.ok) {
    let body: unknown;
    try {
      body = await response.json();
    } catch {
      body = await response.text();
    }
    throw new ApiRequestError(
      responseErrorMessage(body) || `FastAPI returned ${response.status}`,
      response.status,
      body,
    );
  }
  return (await response.json()) as T;
}

export async function testFastAPIConnection(): Promise<SupabaseUserResponse> {
  const response = await authenticatedFetch("/debug/supabase-user");
  return readJson<SupabaseUserResponse>(response);
}

// NOTEBOOKS

export async function listNotebooks(): Promise<Notebook[]> {
  const response = await authenticatedFetch("/notebooks");
  return readJson<Notebook[]>(response);
}
export const getNotebooks = listNotebooks; // alias

export async function createNotebook(title: string, description: string = ""): Promise<Notebook> {
  const response = await authenticatedFetch("/notebooks", {
    method: "POST",
    body: JSON.stringify({ title, description }),
  });
  return readJson<Notebook>(response);
}

export async function getNotebook(notebookId: string): Promise<any> {
  const response = await authenticatedFetch(`/notebooks/${notebookId}`);
  return readJson<any>(response);
}

export async function updateNotebook(
  notebookId: string,
  data: { title?: string; description?: string },
): Promise<Notebook> {
  const response = await authenticatedFetch(`/notebooks/${notebookId}`, {
    method: "PATCH",
    body: JSON.stringify(data),
  });
  return readJson<Notebook>(response);
}

export async function deleteNotebook(notebookId: string): Promise<any> {
  const response = await authenticatedFetch(`/notebooks/${notebookId}`, {
    method: "DELETE",
  });
  return readJson<any>(response);
}

// DOCUMENTS

export async function uploadDocument(
  file: File,
  notebookId: string,
): Promise<DocumentUploadBatchResponse> {
  return uploadDocuments([file], notebookId);
}

export async function uploadDocuments(
  files: File[],
  notebookId: string,
): Promise<DocumentUploadBatchResponse> {
  if (!notebookId) {
    throw new Error("Notebook is required");
  }
  const formData = new FormData();
  files.forEach((file) => formData.append("files", file));
  const response = await authenticatedFetch(`/notebooks/${notebookId}/documents`, {
    method: "POST",
    body: formData,
  });
  return readJson<DocumentUploadBatchResponse>(response);
}

export async function inspectDocumentExtraction(
  file: File,
): Promise<ExtractionInspectionResponse> {
  const formData = new FormData();
  formData.append("file", file);
  const response = await authenticatedFetch("/documents/extraction-inspect", {
    method: "POST",
    body: formData,
  });
  return readJson<ExtractionInspectionResponse>(response);
}

export async function uploadUrl(url: string, title: string | null = null, notebookId: string | null = null): Promise<any> {
  const response = await authenticatedFetch("/documents/upload-url", {
    method: "POST",
    body: JSON.stringify({ url, title, notebook_id: notebookId }),
  });
  return readJson<any>(response);
}

export async function uploadText(title: string, content: string, notebookId: string | null = null): Promise<any> {
  const response = await authenticatedFetch("/documents/upload-text", {
    method: "POST",
    body: JSON.stringify({ title, content, notebook_id: notebookId }),
  });
  return readJson<any>(response);
}

export async function getDocuments(
  notebookId: string,
  params: { status?: string | null; limit?: number; offset?: number } = {},
): Promise<DocumentListResponse> {
  if (!notebookId) {
    throw new Error("Notebook is required");
  }
  const { status = null, limit = 50, offset = 0 } = params;
  const searchParams = new URLSearchParams();
  if (status) searchParams.append("status", status);
  searchParams.append("limit", limit.toString());
  searchParams.append("offset", offset.toString());
  const response = await authenticatedFetch(
    `/notebooks/${notebookId}/documents?${searchParams.toString()}`,
  );
  return readJson<DocumentListResponse>(response);
}

export async function getDocumentStatus(documentId: string): Promise<any> {
  const response = await authenticatedFetch(`/documents/${documentId}/status`);
  return readJson<any>(response);
}

export async function deleteDocument(
  documentId: string,
  notebookId: string | null,
): Promise<{ message: string; document_id: string }> {
  if (!notebookId) {
    throw new Error("Notebook ID is required to delete a document");
  }
  const response = await authenticatedFetch(
    `/notebooks/${notebookId}/documents/${documentId}`,
    { method: "DELETE" },
  );
  return readJson<{ message: string; document_id: string }>(response);
}

export async function getDocumentRelations(
  notebookId: string,
  params: {
    status?: DocumentRelationStatus | null;
    relationType?: DocumentRelationType | null;
    limit?: number;
    offset?: number;
  } = {},
): Promise<DocumentRelationListResponse> {
  if (!notebookId) {
    throw new Error("Notebook is required");
  }
  const {
    status = "pending",
    relationType = null,
    limit = 50,
    offset = 0,
  } = params;
  const searchParams = new URLSearchParams({
    limit: limit.toString(),
    offset: offset.toString(),
  });
  if (status) searchParams.set("status", status);
  if (relationType) searchParams.set("relation_type", relationType);
  const response = await authenticatedFetch(
    `/notebooks/${notebookId}/quality/relations?${searchParams.toString()}`,
  );
  return readJson<DocumentRelationListResponse>(response);
}

export async function getDocumentRelationEvidence(
  notebookId: string,
  relationId: string,
): Promise<DocumentRelationEvidence> {
  if (!notebookId || !relationId) {
    throw new Error("Notebook and relation are required");
  }
  const response = await authenticatedFetch(
    `/notebooks/${notebookId}/quality/relations/${relationId}/evidence`,
  );
  return readJson<DocumentRelationEvidence>(response);
}

export async function resolveDocumentRelation(
  notebookId: string,
  relationId: string,
  action: DocumentRelationAction,
  expectedUpdatedAt: string,
  reason: string,
): Promise<DocumentRelation> {
  const normalizedReason = reason.trim();
  if (!normalizedReason) {
    throw new Error("Vui lòng nhập lý do cho quyết định.");
  }
  const response = await authenticatedFetch(
    `/notebooks/${notebookId}/quality/relations/${relationId}/resolve`,
    {
      method: "POST",
      body: JSON.stringify({
        action,
        expected_updated_at: expectedUpdatedAt,
        reason: normalizedReason,
      }),
    },
  );
  return readJson<DocumentRelation>(response);
}

export async function getDocumentRelationAudit(
  notebookId: string,
  params: {
    relationId?: string | null;
    limit?: number;
    offset?: number;
  } = {},
): Promise<KnowledgeQualityAuditListResponse> {
  if (!notebookId) {
    throw new Error("Notebook is required");
  }
  const { relationId = null, limit = 50, offset = 0 } = params;
  const searchParams = new URLSearchParams({
    limit: limit.toString(),
    offset: offset.toString(),
  });
  if (relationId) searchParams.set("relation_id", relationId);
  const response = await authenticatedFetch(
    `/notebooks/${notebookId}/quality/relations/audit?${searchParams.toString()}`,
  );
  return readJson<KnowledgeQualityAuditListResponse>(response);
}

export async function revertDocumentRelation(
  notebookId: string,
  relationId: string,
  expectedUpdatedAt: string,
  reason: string,
): Promise<DocumentRelation> {
  const normalizedReason = reason.trim();
  if (!normalizedReason) {
    throw new Error("Vui lòng nhập lý do hoàn tác.");
  }
  const response = await authenticatedFetch(
    `/notebooks/${notebookId}/quality/relations/${relationId}/revert`,
    {
      method: "POST",
      body: JSON.stringify({
        expected_updated_at: expectedUpdatedAt,
        reason: normalizedReason,
      }),
    },
  );
  return readJson<DocumentRelation>(response);
}

export async function getStructuredClaimRelations(
  notebookId: string,
  params: { limit?: number; offset?: number } = {},
): Promise<StructuredClaimRelationListResponse> {
  if (!notebookId) {
    throw new Error("Notebook is required");
  }
  const { limit = 50, offset = 0 } = params;
  const searchParams = new URLSearchParams({
    limit: limit.toString(),
    offset: offset.toString(),
  });
  const response = await authenticatedFetch(
    `/notebooks/${notebookId}/structured-facts/relations?${searchParams.toString()}`,
  );
  return readJson<StructuredClaimRelationListResponse>(response);
}

export async function getStructuredClaimRelationEvidence(
  notebookId: string,
  relationId: string,
): Promise<StructuredClaimRelationEvidence> {
  if (!notebookId || !relationId) {
    throw new Error("Notebook and relation are required");
  }
  const response = await authenticatedFetch(
    `/notebooks/${notebookId}/structured-facts/relations/${relationId}/evidence`,
  );
  return readJson<StructuredClaimRelationEvidence>(response);
}

export async function resolveStructuredClaimRelation(
  notebookId: string,
  relationId: string,
  action: StructuredClaimResolutionAction,
  expectedUpdatedAt: string,
  reason: string,
): Promise<StructuredClaimRelation> {
  const normalizedReason = reason.trim();
  if (!normalizedReason) {
    throw new Error("Vui lòng nhập lý do cho quyết định.");
  }
  const response = await authenticatedFetch(
    `/notebooks/${notebookId}/structured-facts/relations/${relationId}/resolve`,
    {
      method: "POST",
      body: JSON.stringify({
        action,
        expected_updated_at: expectedUpdatedAt,
        reason: normalizedReason,
      }),
    },
  );
  return readJson<StructuredClaimRelation>(response);
}

// PROFILE

export async function getProfile(): Promise<Profile> {
  const response = await authenticatedFetch("/profile");
  return readJson<Profile>(response);
}

export async function updateProfile(
  data: { display_name?: string | null; avatar_url?: string | null },
): Promise<Profile> {
  const response = await authenticatedFetch("/profile", {
    method: "PATCH",
    body: JSON.stringify(data),
  });
  return readJson<Profile>(response);
}

// ADMIN

export async function getAdminUserCount(): Promise<AdminUserCount> {
  const response = await authenticatedFetch("/admin/stats/users");
  return readJson<AdminUserCount>(response);
}

export async function getAdminAuthEvents(days: number = 30): Promise<AdminAuthEventsResponse> {
  const response = await authenticatedFetch(`/admin/stats/auth-events?days=${days}`);
  return readJson<AdminAuthEventsResponse>(response);
}

export async function getAdminAuditLog(limit: number = 50): Promise<AdminAuditLogResponse> {
  const response = await authenticatedFetch(`/admin/audit-log?limit=${limit}`);
  return readJson<AdminAuditLogResponse>(response);
}

export async function getAdminUserNotebooks(userId: string): Promise<Notebook[]> {
  const response = await authenticatedFetch(`/admin/users/${userId}/notebooks`);
  return readJson<Notebook[]>(response);
}

export class DocumentPreviewRequestError extends Error {
  status: number;

  constructor(message: string, status: number) {
    super(message);
    this.name = "DocumentPreviewRequestError";
    this.status = status;
  }
}

export async function getDocumentPreview(
  notebookId: string,
  documentId: string,
  signal?: AbortSignal,
): Promise<Blob> {
  const response = await authenticatedFetch(
    `/notebooks/${notebookId}/documents/${documentId}/preview`,
    { signal },
  );

  if (!response.ok) {
    let message = "Không thể tải bản xem trước tài liệu";
    try {
      const payload = await response.json();
      if (payload && typeof payload.detail === "string") {
        message = payload.detail;
      }
    } catch {
      // Keep the safe fallback message when the error response is not JSON.
    }
    throw new DocumentPreviewRequestError(message, response.status);
  }

  const contentType = response.headers.get("Content-Type") || "";
  if (!contentType.toLowerCase().startsWith("application/pdf")) {
    throw new DocumentPreviewRequestError(
      "Định dạng tài liệu này hiện chưa hỗ trợ xem trước",
      415,
    );
  }

  return response.blob();
}

// CHAT

export async function sendMessage(question: string, documentIds: string[] | null = null, notebookId: string | null = null, conversationId: string | null = null): Promise<any> {
  const response = await authenticatedFetch("/chat", {
    method: "POST",
    body: JSON.stringify({
      question,
      notebook_id: notebookId,
      document_ids: documentIds,
      conversation_id: conversationId,
    }),
  });
  return readJson<any>(response);
}

export async function streamMessage(
  question: string,
  documentIds: string[] | null = null,
  notebookId: string | null = null,
  conversationId: string | null = null,
  callbacks: {
    onConversationId?: (id: string) => void,
    onToken?: (text: string) => void,
    onCitation?: (citation: any) => void,
    onDone?: () => void,
    onError?: (error: string) => void,
    signal?: AbortSignal,
  } = {}
) {
  const { onConversationId, onToken, onCitation, onDone, onError, signal } = callbacks;

  try {
    const { data: { session } } = await supabase.auth.getSession();
    if (!session) throw new Error("User chưa đăng nhập");

    const headers = {
      "Content-Type": "application/json",
      "Authorization": `Bearer ${session.access_token}`
    };

    const response = await fetch(`${apiUrl}/chat/stream`, {
      method: "POST",
      headers,
      body: JSON.stringify({
        question,
        notebook_id: notebookId,
        document_ids: documentIds,
        conversation_id: conversationId,
      }),
      signal,
    });

    if (!response.ok) {
      let errText = await response.text();
      try {
        const errJson = JSON.parse(errText);
        throw new Error(errJson.message || errJson.detail || "Lỗi streaming");
      } catch (e) {
        throw new Error(errText || `Lỗi HTTP ${response.status}`);
      }
    }

    const reader = response.body?.getReader();
    if (!reader) throw new Error("Response body is null");
    const decoder = new TextDecoder("utf-8");
    let buffer = "";

    while (true) {
      const { value, done } = await reader.read();
      if (done) break;

      buffer += decoder.decode(value, { stream: true });
      const events = buffer.split("\n\n");
      buffer = events.pop() || "";

      for (const eventBlock of events) {
        if (!eventBlock.trim()) continue;
        const lines = eventBlock.split("\n");
        let eventType = "message";
        let dataStr = "";

        for (const line of lines) {
          if (line.startsWith("event:")) {
            eventType = line.slice(6).trim();
          } else if (line.startsWith("data:")) {
            dataStr = line.slice(5).trim();
          }
        }

        if (dataStr) {
          try {
            const payload = JSON.parse(dataStr);
            if (eventType === "conversation_id" && onConversationId) {
              onConversationId(payload.conversation_id);
            } else if (eventType === "token" && onToken) {
              onToken(payload.text);
            } else if (eventType === "citation" && onCitation) {
              onCitation(payload);
            } else if (eventType === "error") {
              if (onError) onError(payload.message || "Lỗi hệ thống");
            } else if (eventType === "done" && onDone) {
              onDone();
            }
          } catch (e) {
            console.error("Failed to parse SSE payload:", dataStr, e);
          }
        }
      }
    }
  } catch (error: any) {
    if (error.name !== "AbortError" && onError) {
      onError(error.message);
    }
  }
}
