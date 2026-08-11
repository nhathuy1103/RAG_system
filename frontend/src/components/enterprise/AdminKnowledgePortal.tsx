import { Icon } from "@iconify/react";
import { FormEvent, useEffect, useMemo, useState } from "react";
import { Navigate } from "react-router-dom";

import { GovernanceAdminPanel, IdentityAdminPanel } from "./EnterpriseAdminPanels";
import EnterpriseIssuesPanel from "./EnterpriseIssuesPanel";

import {
  AccessSubject,
  DocumentPermission,
  DocumentSearchability,
  DocumentStatus,
  DocumentVersion,
  DocumentVersionReviewContext,
  EnterpriseApiError,
  KnowledgeDocument,
  PermissionAssignment,
  ProcessingJob,
  ProcessingJobDetail,
  ProcessingStatus,
  archiveKnowledgeDocument,
  createDocumentVersion,
  getDocumentVersionSource,
  getDocumentVersionReviewContext,
  getEnterpriseMe,
  getKnowledgeDocument,
  getProcessingJob,
  grantDocumentPermission,
  listEnterpriseAccessSubjects,
  listDocumentPermissions,
  listDocumentSearchability,
  listDocumentVersions,
  listKnowledgeDocuments,
  listProcessingJobs,
  ENTERPRISE_RELATIONS_UPDATED_EVENT,
  listEnterpriseRelations,
  publishDocumentVersion,
  retryProcessingJob,
  reviewDocumentVersion,
  revokeDocumentPermission,
  testDocumentPermission,
  uploadInitialKnowledgeDocument,
  uploadEnterpriseSourceFile,
} from "../../lib/enterpriseApi";

type Section = "DOCUMENTS" | "ACCESS" | "PROCESSING" | "ISSUES" | "IDENTITY" | "GOVERNANCE";

const SECTION_PERMISSIONS: Record<Section, readonly string[]> = {
  DOCUMENTS: [
    "UPLOAD_DOCUMENT",
    "MANAGE_DOCUMENT",
    "REVIEW_DOCUMENT",
    "PUBLISH_DOCUMENT",
    "ARCHIVE_DOCUMENT",
  ],
  ACCESS: ["MANAGE_ACCESS_POLICY"],
  PROCESSING: ["MANAGE_DOCUMENT"],
  ISSUES: ["MANAGE_DOCUMENT", "REVIEW_DOCUMENT"],
  IDENTITY: ["MANAGE_USER", "MANAGE_ROLE", "MANAGE_GROUP", "MANAGE_DEPARTMENT"],
  GOVERNANCE: ["VIEW_AUDIT", "VIEW_ANALYTICS", "MANAGE_REPORT"],
};

const STATUS_STYLE: Record<string, string> = {
  DRAFT: "border-yellow/30 bg-yellow/10 text-yellow",
  PUBLISHED: "border-green/30 bg-green/10 text-green",
  ARCHIVED: "border-border bg-inset text-faint",
  READY_FOR_REVIEW: "border-blue/30 bg-blue/10 text-blue",
  ACTIVE: "border-green/30 bg-green/10 text-green",
  REJECTED: "border-red/30 bg-red/10 text-red",
  SUPERSEDED: "border-border bg-inset text-faint",
  PENDING: "border-yellow/30 bg-yellow/10 text-yellow",
  RUNNING: "border-blue/30 bg-blue/10 text-blue",
  SUCCEEDED: "border-green/30 bg-green/10 text-green",
  FAILED: "border-red/30 bg-red/10 text-red",
  CANCELLED: "border-border bg-inset text-faint",
  REVOKED: "border-border bg-inset text-faint",
};

const STATUS_LABEL: Record<string, string> = {
  DRAFT: "Bản nháp",
  PUBLISHED: "Đã xuất bản",
  ARCHIVED: "Đã lưu trữ",
  READY_FOR_REVIEW: "Chờ duyệt",
  ACTIVE: "Đang hoạt động",
  REJECTED: "Đã từ chối",
  SUPERSEDED: "Đã được thay thế",
  PENDING: "Đang chờ",
  RUNNING: "Đang xử lý",
  SUCCEEDED: "Thành công",
  FAILED: "Thất bại",
  CANCELLED: "Đã hủy",
  REVOKED: "Đã thu hồi",
  STARTED: "Đã bắt đầu",
  SKIPPED: "Đã bỏ qua",
};

const SUBJECT_TYPE_LABEL: Record<string, string> = {
  USER: "Người dùng",
  ROLE: "Vai trò",
  GROUP: "Nhóm",
  DEPARTMENT: "Phòng ban",
  SUBJECT: "Đối tượng",
};

const DOCUMENT_PERMISSION_LABEL: Record<DocumentPermission, string> = {
  READ: "Xem tài liệu",
  DOWNLOAD: "Tải xuống",
  MANAGE: "Quản lý tài liệu",
  REVIEW: "Kiểm duyệt",
  PUBLISH: "Xuất bản",
  ARCHIVE: "Lưu trữ",
  MANAGE_PERMISSION: "Quản lý phân quyền",
};

const PROCESSING_STAGE_LABEL: Record<string, string> = {
  FILE_VALIDATION: "Kiểm tra tệp",
  EXTRACTION: "Trích xuất nội dung",
  OCR: "Nhận dạng ký tự (OCR)",
  PARSING: "Phân tích cấu trúc",
  CHUNKING: "Chia đoạn nội dung",
  CONTEXTUAL_ENRICHMENT: "Bổ sung ngữ cảnh",
  EMBEDDING: "Tạo vector ngữ nghĩa",
  INDEXING: "Lập chỉ mục tìm kiếm",
  FINALIZING: "Hoàn tất",
};

const PROCESSING_JOB_TYPE_LABEL: Record<string, string> = {
  INITIAL_PROCESS: "Xử lý tài liệu lần đầu",
  NEW_VERSION: "Xử lý phiên bản mới",
  REPROCESS: "Xử lý lại",
};

const REVIEW_DECISION_LABEL: Record<"APPROVE" | "REJECT" | "REPROCESS", string> = {
  APPROVE: "phê duyệt",
  REJECT: "từ chối",
  REPROCESS: "yêu cầu xử lý lại",
};

type UploadLifecyclePhase = "PROCESSING" | "READY_FOR_REVIEW" | "PUBLISHED" | "SEARCHABLE" | "FAILED" | "TIMEOUT";
type UploadLifecycle = {
  tracking_id: string;
  file_name: string;
  document_id: string;
  version_id: string;
  job_id: string | null;
  phase: UploadLifecyclePhase;
  current_stage: string | null;
  started_at: number;
  detail: string | null;
  searchability?: DocumentSearchability | null;
  using_lifecycle_fallback?: boolean;
};
const UPLOAD_POLL_INTERVAL_MS = 2_000;
const UPLOAD_POLL_TIMEOUT_MS = 5 * 60_000;
const UPLOAD_PHASE_PRESENTATION: Record<UploadLifecyclePhase, { label: string; icon: string; className: string }> = {
  PROCESSING: { label: "Đang xử lý", icon: "lucide:loader-circle", className: "border-blue/30 bg-blue/10 text-blue" },
  READY_FOR_REVIEW: { label: "Sẵn sàng để duyệt", icon: "lucide:clipboard-check", className: "border-yellow/30 bg-yellow/10 text-yellow" },
  PUBLISHED: { label: "Đã xuất bản", icon: "lucide:book-check", className: "border-green/30 bg-green/10 text-green" },
  SEARCHABLE: { label: "Chatbot có thể tìm kiếm", icon: "lucide:badge-check", className: "border-green/30 bg-green/10 text-green" },
  FAILED: { label: "Xử lý thất bại", icon: "lucide:circle-x", className: "border-red/30 bg-red/10 text-red" },
  TIMEOUT: { label: "Đã dừng theo dõi", icon: "lucide:clock-alert", className: "border-yellow/30 bg-yellow/10 text-yellow" },
};
const UPLOAD_PHASE_RANK: Record<UploadLifecyclePhase, number> = {
  PROCESSING: 1, READY_FOR_REVIEW: 2, PUBLISHED: 3, SEARCHABLE: 4, FAILED: 0, TIMEOUT: 0,
};

const SEARCHABILITY_REASON_LABEL: Record<string, string> = {
  DOCUMENT_NOT_PUBLISHED: "Tài liệu chưa xuất bản",
  VERSION_NOT_ACTIVE: "Phiên bản chưa hoạt động",
  NO_CURRENT_VERSION: "Chưa có phiên bản hiện hành",
  NO_READ_PERMISSION: "Tài khoản chưa có quyền đọc",
  NO_CHUNKS: "Chưa có chunk",
  PROJECTION_NOT_READY: "Retrieval projection chưa sẵn sàng",
  LEXICAL_PROJECTION_STALE: "Chỉ mục lexical đang cũ",
  EMBEDDING_METADATA_STALE: "Metadata embedding đang cũ",
};

function displaySearchabilityReason(value: string) {
  return SEARCHABILITY_REASON_LABEL[value] || value.replaceAll("_", " ").toLocaleLowerCase("vi-VN");
}

function displayStatus(value: string) {
  return STATUS_LABEL[value] || value;
}

function displayStage(value: string | null) {
  return value ? PROCESSING_STAGE_LABEL[value] || value : "Chưa bắt đầu";
}

function StatusBadge({ value }: { value: string }) {
  return <span title={value} className={`rounded-full border px-2 py-1 text-[10px] font-semibold ${STATUS_STYLE[value] || STATUS_STYLE.DRAFT}`}>{displayStatus(value)}</span>;
}

function formatDate(value: string | null) {
  if (!value) return "—";
  return new Date(value).toLocaleString("vi-VN", { dateStyle: "short", timeStyle: "short" });
}

function EmptyState({ icon, title, description }: { icon: string; title: string; description: string }) {
  return (
    <div className="flex min-h-72 flex-col items-center justify-center rounded-2xl border border-dashed border-border bg-panel/50 p-8 text-center">
      <Icon icon={icon} width={38} className="text-faint" />
      <div className="mt-4 font-heading text-lg font-semibold text-foreground">{title}</div>
      <p className="mt-2 max-w-md text-sm leading-6 text-dim">{description}</p>
    </div>
  );
}

function ReviewWorkspace({
  context,
  onOpenSource,
}: {
  context: DocumentVersionReviewContext;
  onOpenSource: () => void;
}) {
  return (
    <div className="mt-4 rounded-xl border border-accent/30 bg-panel p-4">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <div className="font-heading text-sm font-semibold">Không gian kiểm duyệt phiên bản</div>
          <div className="mt-1 text-[10px] text-faint">{context.source_file.original_file_name} · {(context.source_file.size_bytes / 1024).toFixed(1)} KB · SHA-256 {context.source_file.sha256?.slice(0, 16) || "—"}…</div>
        </div>
        <button type="button" onClick={onOpenSource} className="rounded-md border border-border px-2.5 py-1.5 text-[11px] text-dim hover:bg-inset"><Icon icon="lucide:external-link" width={13} className="mr-1 inline" />Mở file gốc</button>
      </div>
      {context.latest_processing_job && <div className="mt-3 flex items-center gap-2 rounded-lg border border-border bg-background p-3 text-xs"><span className="font-semibold">Lần xử lý #{context.latest_processing_job.attempt_no}</span><StatusBadge value={context.latest_processing_job.status} /><span className="text-faint">{displayStage(context.latest_processing_job.current_stage)}</span></div>}
      {!!context.stage_history.length && <div className="mt-3 flex flex-wrap gap-2">{context.stage_history.map((stage) => <span key={stage.id} title={`${stage.stage} · ${stage.status}`} className="rounded-full border border-border bg-background px-2 py-1 text-[10px] text-dim">{displayStage(stage.stage)} · {displayStatus(stage.status)}</span>)}</div>}
      {!!context.errors.length && <div className="mt-3 space-y-2">{context.errors.map((item) => <div key={item.id} className="rounded-lg border border-red/30 bg-red/10 p-3 text-xs text-red"><div className="font-semibold">{item.error_code} · {item.error_type}</div><div className="mt-1">{item.safe_message}</div></div>)}</div>}
      <div className="mt-4 flex items-center justify-between"><div className="text-xs font-semibold">Các đoạn nội dung đã trích xuất</div><span className="text-[10px] text-faint">{context.extracted_chunks.length} đoạn</span></div>
      <div className="mt-2 max-h-[520px] space-y-2 overflow-y-auto pr-1">
        {context.extracted_chunks.map((chunk) => <article key={chunk.chunk_id} className="rounded-lg border border-border bg-background p-3"><div className="flex flex-wrap items-center gap-2 text-[10px] text-faint"><span className="font-semibold text-foreground">Đoạn #{chunk.chunk_index}</span><span>{chunk.section_path || "Không xác định mục"}</span><span>{chunk.page_start ? `tr. ${chunk.page_start}${chunk.page_end && chunk.page_end !== chunk.page_start ? `–${chunk.page_end}` : ""}` : ""}</span></div><p className="mt-2 whitespace-pre-wrap text-xs leading-5 text-dim">{chunk.content}</p></article>)}
        {!context.extracted_chunks.length && <div className="rounded-lg border border-dashed border-border p-8 text-center text-xs text-faint">Chưa có đoạn nội dung được trích xuất. Hãy kiểm tra lịch sử xử lý trước khi kiểm duyệt.</div>}
      </div>
    </div>
  );
}

export default function AdminKnowledgePortal() {
  const [authorized, setAuthorized] = useState<boolean | null>(null);
  const [functionalPermissions, setFunctionalPermissions] = useState<Set<string>>(new Set());
  const [section, setSection] = useState<Section>("DOCUMENTS");
  const [documents, setDocuments] = useState<KnowledgeDocument[]>([]);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [versions, setVersions] = useState<DocumentVersion[]>([]);
  const [permissions, setPermissions] = useState<PermissionAssignment[]>([]);
  const [reviewContext, setReviewContext] = useState<DocumentVersionReviewContext | null>(null);
  const [loadingReviewVersionId, setLoadingReviewVersionId] = useState<string | null>(null);
  const [publishingVersionId, setPublishingVersionId] = useState<string | null>(null);
  const [statusFilter, setStatusFilter] = useState<DocumentStatus | "ALL">("ALL");
  const [documentQuery, setDocumentQuery] = useState("");
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [initialSourceFile, setInitialSourceFile] = useState<File | null>(null);
  const [initialSourceInputKey, setInitialSourceInputKey] = useState(0);
  const [creatingInitialDocument, setCreatingInitialDocument] = useState(false);
  const [sourceFile, setSourceFile] = useState<File | null>(null);
  const [sourceInputKey, setSourceInputKey] = useState(0);
  const [uploadingSource, setUploadingSource] = useState(false);
  const [uploadLifecycle, setUploadLifecycle] = useState<UploadLifecycle | null>(null);
  const [subjectId, setSubjectId] = useState("");
  const [subjectType, setSubjectType] = useState<AccessSubject["subject_type"]>("GROUP");
  const [accessSubjects, setAccessSubjects] = useState<AccessSubject[]>([]);
  const [permission, setPermission] = useState<DocumentPermission>("READ");
  const [testUserId, setTestUserId] = useState("");
  const [testResult, setTestResult] = useState<string | null>(null);
  const [processingJobs, setProcessingJobs] = useState<ProcessingJob[]>([]);
  const [processingStatus, setProcessingStatus] = useState<ProcessingStatus | "ALL">("ALL");
  const [processingVersionId, setProcessingVersionId] = useState("");
  const [loadingProcessingJobs, setLoadingProcessingJobs] = useState(false);
  const [job, setJob] = useState<ProcessingJobDetail | null>(null);

  const [pendingIssuesCount, setPendingIssuesCount] = useState(0);

  const canManageDocuments = functionalPermissions.has("MANAGE_DOCUMENT");
  const canUploadDocuments = functionalPermissions.has("UPLOAD_DOCUMENT") || canManageDocuments;
  const canReviewDocuments = functionalPermissions.has("REVIEW_DOCUMENT");
  const canPublishDocuments = functionalPermissions.has("PUBLISH_DOCUMENT");
  const canArchiveDocuments = functionalPermissions.has("ARCHIVE_DOCUMENT");
  const canManageAccess = functionalPermissions.has("MANAGE_ACCESS_POLICY");
  const canUseReviewWorkspace = canManageDocuments || canReviewDocuments || canPublishDocuments;
  const canViewDocumentWorkspace = SECTION_PERMISSIONS.DOCUMENTS.some((code) =>
    functionalPermissions.has(code),
  );

  const selected = useMemo(
    () => documents.find((document) => document.id === selectedId) || null,
    [documents, selectedId],
  );
  const visibleDocuments = useMemo(
    () => {
      const normalizedQuery = documentQuery.trim().toLocaleLowerCase("vi-VN");
      return documents.filter((item) => {
        if (statusFilter !== "ALL" && item.status !== statusFilter) return false;
        if (!normalizedQuery) return true;
        return [item.title, item.description, item.document_type, item.category, item.document_number]
          .some((value) => value?.toLocaleLowerCase("vi-VN").includes(normalizedQuery));
      });
    },
    [documentQuery, documents, statusFilter],
  );

  async function reloadDocuments() {
    const page = await listKnowledgeDocuments({ limit: 200 });
    setDocuments(page.items);
    setSelectedId((current) => current && page.items.some((item) => item.id === current) ? current : page.items[0]?.id || null);
  }

  useEffect(() => {
    let cancelled = false;
    getEnterpriseMe()
      .then(async (me) => {
        const permissionSet = new Set(me.permissions);
        const allowedSections = (Object.keys(SECTION_PERMISSIONS) as Section[])
          .filter((candidate) => SECTION_PERMISSIONS[candidate].some((code) => permissionSet.has(code)));
        if (cancelled) return;
        setFunctionalPermissions(permissionSet);
        setAuthorized(allowedSections.length > 0);
        setSection((current) => allowedSections.includes(current) ? current : allowedSections[0] || "DOCUMENTS");
        if (
          !SECTION_PERMISSIONS.DOCUMENTS.some((code) => permissionSet.has(code))
          && !permissionSet.has("MANAGE_ACCESS_POLICY")
        ) return;
        const page = await listKnowledgeDocuments({ limit: 200 });
        if (cancelled) return;
        setDocuments(page.items);
        setSelectedId(page.items[0]?.id || null);
      })
      .catch((reason: unknown) => {
        if (!cancelled) {
          setAuthorized(false);
          setError(reason instanceof Error ? reason.message : "Không thể tải Admin Portal");
        }
      })
      .finally(() => { if (!cancelled) setLoading(false); });
    return () => { cancelled = true; };
  }, []);

  useEffect(() => {
    if (!selectedId) {
      setVersions([]);
      setPermissions([]);
      return;
    }
    let cancelled = false;
    Promise.all([
      canViewDocumentWorkspace ? listDocumentVersions(selectedId) : Promise.resolve({ items: [] }),
      canManageAccess ? listDocumentPermissions(selectedId) : Promise.resolve({ items: [] }),
    ])
      .then(([versionPage, permissionPage]) => {
        if (cancelled) return;
        setVersions(versionPage.items);
        setPermissions(permissionPage.items);
      })
      .catch((reason: unknown) => {
        if (!cancelled) setError(reason instanceof Error ? reason.message : "Không thể tải chi tiết tài liệu");
      });
    return () => { cancelled = true; };
  }, [canManageAccess, canViewDocumentWorkspace, selectedId]);

  useEffect(() => {
    if (!canManageAccess) {
      setAccessSubjects([]);
      setSubjectId("");
      return;
    }
    let cancelled = false;
    listEnterpriseAccessSubjects(subjectType)
      .then((items) => {
        if (cancelled) return;
        setAccessSubjects(items);
        setSubjectId((current) => items.some((item) => item.id === current) ? current : "");
      })
      .catch((reason: unknown) => {
        if (!cancelled) setError(reason instanceof Error ? reason.message : "Không thể tải access subject");
      });
    return () => { cancelled = true; };
  }, [canManageAccess, subjectType]);

  useEffect(() => {
    setProcessingVersionId("");
    setProcessingJobs([]);
    setJob(null);
    setReviewContext(null);
  }, [selectedId]);

  useEffect(() => {
    if (!canManageDocuments || section !== "PROCESSING") {
      setProcessingJobs([]);
      setJob(null);
      return;
    }
    let cancelled = false;
    setLoadingProcessingJobs(true);
    listProcessingJobs({
      document_id: selectedId || undefined,
      document_version_id: processingVersionId || undefined,
      status: processingStatus === "ALL" ? undefined : processingStatus,
      limit: 200,
    })
      .then((page) => {
        if (!cancelled) setProcessingJobs(page.items);
      })
      .catch((reason: unknown) => {
        if (!cancelled) setError(reason instanceof Error ? reason.message : "Không thể tải processing jobs");
      })
      .finally(() => {
        if (!cancelled) setLoadingProcessingJobs(false);
      });
    return () => { cancelled = true; };
  }, [canManageDocuments, processingStatus, processingVersionId, section, selectedId]);

  useEffect(() => {
    const lifecycle = uploadLifecycle;
    if (!lifecycle || ["SEARCHABLE", "FAILED", "TIMEOUT"].includes(lifecycle.phase)) return;
    let cancelled = false;
    let checking = false;
    const poll = async () => {
      if (checking || cancelled) return;
      if (Date.now() - lifecycle.started_at >= UPLOAD_POLL_TIMEOUT_MS) {
        setUploadLifecycle((current) => current?.tracking_id === lifecycle.tracking_id
          ? { ...current, phase: "TIMEOUT", detail: "Hết 5 phút theo dõi. Job có thể vẫn chạy; mở mục Theo dõi xử lý để kiểm tra tiếp." } : current);
        return;
      }
      checking = true;
      try {
        const [document, versionPage, resolvedJob, searchabilityResult] = await Promise.all([
          getKnowledgeDocument(lifecycle.document_id),
          listDocumentVersions(lifecycle.document_id),
          lifecycle.job_id ? getProcessingJob(lifecycle.job_id)
            : listProcessingJobs({ document_version_id: lifecycle.version_id, limit: 10 })
                .then((page) => page.items.sort((a, b) => b.attempt_no - a.attempt_no)[0] || null),
          listDocumentSearchability(lifecycle.document_id)
            .then((items) => ({
              supported: true,
              diagnostic: items.find((item) => item.document_id === lifecycle.document_id) || null,
            }))
            .catch((reason: unknown) => {
              if (reason instanceof EnterpriseApiError && reason.status === 404) {
                return { supported: false, diagnostic: null };
              }
              throw reason;
            }),
        ]);
        if (cancelled) return;
        const version = versionPage.items.find((item) => item.id === lifecycle.version_id);
        const diagnostic = searchabilityResult.diagnostic;
        const lifecycleReady = resolvedJob?.status === "SUCCEEDED"
          && document.status === "PUBLISHED"
          && document.current_version_id === lifecycle.version_id
          && version?.status === "ACTIVE";
        setDocuments((current) => [document, ...current.filter((item) => item.id !== document.id)]);
        if (selectedId === lifecycle.document_id) setVersions(versionPage.items);
        let phase: UploadLifecyclePhase = "PROCESSING";
        let detail: string | null = null;
        if (document.status === "ARCHIVED") {
          phase = "FAILED";
          detail = "Tài liệu đã bị lưu trữ nên chatbot không thể retrieval.";
        } else if (resolvedJob?.status === "FAILED" || resolvedJob?.status === "CANCELLED") {
          phase = "FAILED";
          detail = resolvedJob.error_message || resolvedJob.error_code || "Pipeline xử lý không hoàn tất.";
        } else if (
          lifecycleReady
          && diagnostic?.current_version_id === lifecycle.version_id
          && diagnostic.searchable_for_actor
          && diagnostic.fully_indexed
        ) {
          phase = "SEARCHABLE";
          detail = "Endpoint searchability xác nhận phiên bản đã index đầy đủ và tài khoản hiện tại có thể retrieval.";
        } else if (lifecycleReady && !searchabilityResult.supported) {
          phase = "SEARCHABLE";
          detail = "Server cũ chưa có endpoint searchability; tạm xác nhận bằng lifecycle PUBLISHED/ACTIVE và job thành công.";
        } else if (document.status === "PUBLISHED") {
          phase = "PUBLISHED";
          detail = diagnostic
            ? "Đã xuất bản nhưng endpoint searchability chưa xác nhận index đầy đủ và quyền retrieval."
            : "Đã xuất bản; đang chờ endpoint searchability trả về chẩn đoán cho tài liệu.";
        } else if (version?.status === "READY_FOR_REVIEW" || resolvedJob?.status === "SUCCEEDED") {
          phase = "READY_FOR_REVIEW";
          detail = "Xử lý đã xong nhưng chưa là phiên bản hiện hành. Nếu tự động xuất bản không chạy, dùng nút Đưa vào chatbot.";
        }
        setUploadLifecycle((current) => current?.tracking_id === lifecycle.tracking_id
          ? { ...current, job_id: resolvedJob?.id || current.job_id, phase,
              current_stage: resolvedJob?.current_stage || current.current_stage, detail,
              searchability: diagnostic,
              using_lifecycle_fallback: !searchabilityResult.supported } : current);
      } catch (reason) {
        if (!cancelled) setUploadLifecycle((current) => current?.tracking_id === lifecycle.tracking_id
          ? { ...current, detail: reason instanceof Error ? "Lần kiểm tra gần nhất lỗi: " + reason.message : "Không thể cập nhật trạng thái." } : current);
      } finally {
        checking = false;
      }
    };
    void poll();
    const intervalId = window.setInterval(() => void poll(), UPLOAD_POLL_INTERVAL_MS);
    return () => { cancelled = true; window.clearInterval(intervalId); };
  }, [selectedId, uploadLifecycle?.job_id, uploadLifecycle?.phase, uploadLifecycle?.tracking_id]);

  useEffect(() => {
    let cancelled = false;
    let intervalId: number;

    const checkIssues = async () => {
      try {
        const data = await listEnterpriseRelations();
        const pendingCount = data.items.filter(r => r.status === "pending").length;
        if (!cancelled) {
          setPendingIssuesCount(prev => {
            if (pendingCount > prev && prev !== 0) {
              setNotice("Phát hiện tài liệu mới có lỗi trùng lặp/mâu thuẫn. Vui lòng kiểm tra tab Vấn đề & Mâu thuẫn.");
              window.setTimeout(() => setNotice(null), 5000);
            }
            return pendingCount;
          });
        }
      } catch (e) {}
    };

    if (authorized) {
      checkIssues();
      intervalId = window.setInterval(checkIssues, 10000);
      window.addEventListener(ENTERPRISE_RELATIONS_UPDATED_EVENT, checkIssues);
    }

    return () => {
      cancelled = true;
      if (intervalId) window.clearInterval(intervalId);
      window.removeEventListener(ENTERPRISE_RELATIONS_UPDATED_EVENT, checkIssues);
    };
  }, [authorized]);

  function success(message: string) {
    setNotice(message);
    setError(null);
    window.setTimeout(() => setNotice(null), 3500);
  }

  async function createDocument(event: FormEvent) {
    event.preventDefault();
    if (!canUploadDocuments || !initialSourceFile) return;
    setCreatingInitialDocument(true);
    try {
      const created = await uploadInitialKnowledgeDocument(initialSourceFile, {
        title: initialSourceFile.name,
      });
      setUploadLifecycle({
        tracking_id: crypto.randomUUID(), file_name: initialSourceFile.name, document_id: created.document.id,
        version_id: created.version.id, job_id: created.processing_job.id, phase: "PROCESSING",
        current_stage: created.processing_job.current_stage, started_at: Date.now(),
        detail: "Tệp đã được nhận; đang chờ trích xuất, chunking, embedding và indexing.",
      });
      setInitialSourceFile(null);
      setInitialSourceInputKey((current) => current + 1);
      await reloadDocuments();
      setSelectedId(created.document.id);
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "Không thể upload tài liệu khởi tạo");
    } finally {
      setCreatingInitialDocument(false);
    }
  }

  async function addVersion(event: FormEvent) {
    event.preventDefault();
    if (
      !canManageDocuments
      || !selected
      || selected.status === "ARCHIVED"
      || !sourceFile
    ) return;
    setUploadingSource(true);
    try {
      const uploaded = await uploadEnterpriseSourceFile(sourceFile);
      const createdVersion = await createDocumentVersion(selected.id, { source_file_id: uploaded.id });
      setUploadLifecycle({
        tracking_id: crypto.randomUUID(), file_name: sourceFile.name, document_id: selected.id,
        version_id: createdVersion.id, job_id: null, phase: "PROCESSING", current_stage: null,
        started_at: Date.now(), detail: "Phiên bản đã được tạo; đang chờ worker nhận job xử lý.",
      });
      const page = await listDocumentVersions(selected.id);
      setVersions(page.items);
      setSourceFile(null);
      setSourceInputKey((current) => current + 1);
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "Không thể tạo phiên bản");
    } finally {
      setUploadingSource(false);
    }
  }

  async function review(version: DocumentVersion, decision: "APPROVE" | "REJECT" | "REPROCESS") {
    if (!canReviewDocuments || selected?.status === "ARCHIVED") return;
    try {
      await reviewDocumentVersion(version.id, {
        decision,
        note: decision === "APPROVE" ? "Được phê duyệt từ cổng quản trị kho tri thức" : undefined,
        rejection_reason: decision === "REJECT" ? "Bị từ chối từ cổng quản trị kho tri thức" : undefined,
      });
      const page = await listDocumentVersions(version.document_id);
      setVersions(page.items);
      success(`Đã ghi nhận quyết định: ${REVIEW_DECISION_LABEL[decision]}`);
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "Không thể kiểm duyệt phiên bản");
    }
  }

  async function publish(version: DocumentVersion) {
    if (
      !canPublishDocuments
      || selected?.status === "ARCHIVED"
      || publishingVersionId !== null
    ) return;
    setPublishingVersionId(version.id);
    try {
      await publishDocumentVersion(version.id);
      setUploadLifecycle((current) => current?.version_id === version.id
        ? { ...current, phase: "PUBLISHED", detail: "Đã xuất bản; đang xác nhận phiên bản hiện hành có thể tìm kiếm." } : current);
      await reloadDocuments();
      const page = await listDocumentVersions(version.document_id);
      setVersions(page.items);
      success("Tài liệu đã được duyệt và đưa vào chatbot");
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "Không thể đưa tài liệu vào chatbot");
    } finally {
      setPublishingVersionId(null);
    }
  }

  async function archive() {
    if (!canArchiveDocuments || !selected || selected.status === "ARCHIVED") return;
    const confirmation = window.prompt(
      `Lưu trữ sẽ gỡ tài liệu khỏi chatbot và không thể hoàn tác trên giao diện.\n\nNhập chính xác tên tài liệu để xác nhận:\n${selected.title}`,
    );
    if (confirmation !== selected.title) {
      if (confirmation !== null) setError("Tên xác nhận không khớp; tài liệu chưa bị lưu trữ");
      return;
    }
    try {
      await archiveKnowledgeDocument(
        selected.id,
        "Lưu trữ thủ công sau khi xác nhận chính xác tên tài liệu",
      );
      await reloadDocuments();
      success("Đã lưu trữ tài liệu; lịch sử phiên bản và nhật ký vẫn được giữ lại");
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "Không thể lưu trữ tài liệu");
    }
  }

  async function grant(event: FormEvent) {
    event.preventDefault();
    if (!selected || !subjectId.trim()) return;
    try {
      await grantDocumentPermission(selected.id, {
        subject_id: subjectId.trim(),
        permission,
      });
      const page = await listDocumentPermissions(selected.id);
      setPermissions(page.items);
      setSubjectId("");
      success("Đã cấp quyền và ghi nhật ký kiểm toán");
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "Không thể cấp quyền");
    }
  }

  async function revoke(item: PermissionAssignment) {
    if (!canManageAccess || !selected || item.status !== "ACTIVE") return;
    try {
      await revokeDocumentPermission(selected.id, item.subject_id, item.permission);
      const page = await listDocumentPermissions(selected.id);
      setPermissions(page.items);
      success("Đã thu hồi lượt cấp quyền; quyền hiệu lực sẽ được tính lại ở yêu cầu tiếp theo");
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "Không thể thu hồi quyền");
    }
  }

  async function testAccess(event: FormEvent) {
    event.preventDefault();
    if (!selected || !testUserId.trim()) return;
    try {
      const result = await testDocumentPermission(selected.id, testUserId.trim(), "READ");
      setTestResult(result.allowed ? `Được phép · ${result.sources?.join(", ") || "có nguồn cấp quyền hợp lệ"}` : "Bị từ chối · mặc định không cấp quyền");
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "Không thể kiểm tra quyền");
    }
  }

  async function inspectJob(jobId: string) {
    try {
      setJob(await getProcessingJob(jobId));
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "Không thể tải yêu cầu xử lý");
    }
  }

  async function retryJob() {
    if (!job) return;
    try {
      const retried = await retryProcessingJob(job.id);
      setJob(await getProcessingJob(retried.id));
      setProcessingStatus("ALL");
      const page = await listProcessingJobs({
        document_id: selectedId || undefined,
        document_version_id: processingVersionId || undefined,
        limit: 200,
      });
      setProcessingJobs(page.items);
      success("Đã tạo một lần xử lý mới");
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "Không thể chạy lại yêu cầu xử lý");
    }
  }

  if (loading || authorized === null) return <div className="flex flex-1 items-center justify-center text-sm text-faint">Đang xác minh quyền quản trị...</div>;
  if (!authorized) return <Navigate to="/knowledge" replace />;

  const allNavigation: Array<{ id: Section; label: string; icon: string }> = [
    { id: "DOCUMENTS", label: "Tài liệu và phiên bản", icon: "lucide:files" },
    { id: "ACCESS", label: "Phân quyền", icon: "lucide:shield-check" },
    { id: "PROCESSING", label: "Theo dõi xử lý", icon: "lucide:workflow" },
    { id: "ISSUES", label: "Vấn đề & Mâu thuẫn", icon: "lucide:triangle-alert" },
    { id: "IDENTITY", label: "Người dùng & tổ chức", icon: "lucide:users" },
    { id: "GOVERNANCE", label: "Kiểm toán và giám sát", icon: "lucide:scroll-text" },
  ];
  const navigation = allNavigation.filter((item) =>
    SECTION_PERMISSIONS[item.id].some((code) => functionalPermissions.has(code)),
  );

  async function openVersionSource(version: DocumentVersion) {
    const target = window.open("", "_blank");
    if (!target) {
      setError("Trình duyệt đã chặn tab tài liệu nguồn. Hãy cho phép popup rồi thử lại.");
      return;
    }
    target.opener = null;
    try {
      const source = await getDocumentVersionSource(version.document_id, version.id);
      target.location.href = source.signed_url;
    } catch (reason) {
      target.close();
      setError(reason instanceof Error ? reason.message : "Không thể mở tài liệu nguồn");
    }
  }

  async function toggleReviewWorkspace(version: DocumentVersion) {
    if (!canUseReviewWorkspace) return;
    if (reviewContext?.version.id === version.id) {
      setReviewContext(null);
      return;
    }
    setLoadingReviewVersionId(version.id);
    try {
      setReviewContext(await getDocumentVersionReviewContext(version.id));
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "Không thể tải không gian kiểm duyệt");
    } finally {
      setLoadingReviewVersionId(null);
    }
  }

  function accessSubjectLabel(item: AccessSubject) {
    const principalId = item.user_id || item.role_id || item.group_id || item.department_id;
    return `${SUBJECT_TYPE_LABEL[item.subject_type] || item.subject_type} · ${principalId || item.id}`;
  }

  return (
    <div className="flex min-h-0 flex-1 bg-background">
      <aside className="w-64 shrink-0 border-r border-border bg-panel p-4">
        <div className="px-3 pb-5 pt-2">
          <div className="text-[10px] font-semibold uppercase tracking-[0.18em] text-accent">Trung tâm điều hành</div>
          <div className="mt-2 font-heading text-lg font-bold">Quản trị kho tri thức</div>
        </div>
        <nav className="space-y-1">
          {navigation.map((item) => (
            <button key={item.id} onClick={() => setSection(item.id)} className={`flex w-full items-center justify-between gap-3 rounded-xl px-3 py-2.5 text-left text-xs font-medium ${section === item.id ? "bg-accent text-accent-foreground" : "text-dim hover:bg-inset hover:text-foreground"}`}>
              <div className="flex items-center gap-3">
                <Icon icon={item.icon} width={16} /> {item.label}
              </div>
              {item.id === "ISSUES" && pendingIssuesCount > 0 && (
                <span className="flex h-5 items-center justify-center rounded-full bg-red px-2 text-[10px] font-bold text-white">
                  {pendingIssuesCount}
                </span>
              )}
            </button>
          ))}
        </nav>
        <div className="mt-6 rounded-xl border border-border bg-background p-3 text-[11px] leading-5 text-faint">
          <div className="mb-1 flex items-center gap-1.5 font-semibold text-green"><Icon icon="lucide:shield-check" width={13} /> An toàn mặc định</div>
          Nhân viên chỉ tra cứu được tài liệu đã xuất bản, phiên bản đang hoạt động và có quyền xem.
        </div>
      </aside>

      <main className="min-w-0 flex-1 overflow-y-auto p-6 lg:p-8">
        <div className="mx-auto max-w-7xl">
          {error && <div className="mb-5 rounded-xl border border-red/30 bg-red/10 px-4 py-3 text-sm text-red">{error}</div>}
          {notice && <div className="mb-5 rounded-xl border border-green/30 bg-green/10 px-4 py-3 text-sm text-green">{notice}</div>}

          {section === "DOCUMENTS" && (
            <div>
              <div className="mb-6 flex flex-wrap items-end justify-between gap-4">
                <div><h1 className="font-heading text-2xl font-bold">Tài liệu và phiên bản</h1><p className="mt-1 text-sm text-dim">Tải tài liệu lên, theo dõi xử lý và kiểm tra kết quả tự động.</p></div>
                <div className="flex gap-2">
                  <input value={documentQuery} onChange={(event) => setDocumentQuery(event.target.value)} placeholder="Tìm theo tên, loại, danh mục…" className="w-56 rounded-lg border border-border bg-panel px-3 py-2 text-xs" />
                  <select value={statusFilter} onChange={(event) => setStatusFilter(event.target.value as DocumentStatus | "ALL")} className="rounded-lg border border-border bg-panel px-3 py-2 text-xs">
                    <option value="ALL">Tất cả trạng thái</option><option value="DRAFT">Bản nháp</option><option value="PUBLISHED">Đã xuất bản</option><option value="ARCHIVED">Đã lưu trữ</option>
                  </select>
                </div>
              </div>
              {canUploadDocuments && (
                <form onSubmit={createDocument} className="mb-5 rounded-2xl border border-border bg-panel p-4">
                  <div className="mb-3 flex items-start gap-3 rounded-xl border border-border bg-background px-3 py-2.5">
                    <Icon icon="lucide:sparkles" width={16} className="mt-0.5 shrink-0 text-accent" />
                    <div className="text-xs leading-5 text-dim">
                      <div className="font-semibold text-foreground">Chỉ cần chọn tệp</div>
                      Hệ thống tự dùng tên tệp, trích xuất nội dung và đề xuất metadata có bằng chứng. Bạn không cần nhập thông tin trước khi tải lên.
                    </div>
                  </div>
                  <div className="grid gap-3 md:grid-cols-[1fr_auto]">
                    <label className="flex min-w-0 cursor-pointer items-center gap-2 rounded-lg border border-border bg-background px-3 py-2.5 text-xs hover:bg-inset"><Icon icon="lucide:upload" width={14} /><span className="truncate">{initialSourceFile?.name || "Chọn tệp tài liệu"}</span><input key={initialSourceInputKey} type="file" required onChange={(event) => setInitialSourceFile(event.target.files?.[0] || null)} accept=".pdf,.docx,.pptx,.xlsx,.csv,.md,.markdown,.html,.htm,.txt" className="sr-only" /></label>
                    <button disabled={creatingInitialDocument || !initialSourceFile} className="rounded-lg bg-accent px-5 py-2.5 text-xs font-semibold text-accent-foreground disabled:cursor-not-allowed disabled:opacity-50">{creatingInitialDocument ? "Đang tải lên…" : "Tải tài liệu"}</button>
                  </div>
                </form>
              )}
              {uploadLifecycle && (
                <section className="mb-5 rounded-2xl border border-border bg-panel p-4">
                  <div className="flex flex-wrap items-start justify-between gap-3">
                    <div className="min-w-0">
                      <div className="text-[10px] font-semibold uppercase tracking-wider text-faint">Trạng thái sau upload</div>
                      <div className="mt-1 truncate text-sm font-semibold">{uploadLifecycle.file_name}</div>
                    </div>
                    <span className={"inline-flex items-center gap-1.5 rounded-full border px-3 py-1.5 text-[11px] font-semibold " + UPLOAD_PHASE_PRESENTATION[uploadLifecycle.phase].className}>
                      <Icon icon={UPLOAD_PHASE_PRESENTATION[uploadLifecycle.phase].icon} width={14} className={uploadLifecycle.phase === "PROCESSING" ? "animate-spin" : ""} />
                      {UPLOAD_PHASE_PRESENTATION[uploadLifecycle.phase].label}
                    </span>
                  </div>
                  <div className="mt-4 grid gap-2 text-[10px] sm:grid-cols-5">
                    {[
                      ["Đã nhận tệp", 0],
                      ["Xử lý & lập chỉ mục", 1],
                      ["Sẵn sàng duyệt", 2],
                      ["Published", 3],
                      ["Searchable", 4],
                    ].map(([label, rank]) => {
                      const completed = UPLOAD_PHASE_RANK[uploadLifecycle.phase] >= Number(rank);
                      return <div key={String(label)} className={"rounded-lg border px-2 py-2 " + (completed ? "border-green/30 bg-green/10 text-green" : "border-border bg-background text-faint")}>{completed ? "✓ " : "○ "}{label}</div>;
                    })}
                  </div>
                  <p className="mt-3 text-xs leading-5 text-dim">
                    {uploadLifecycle.current_stage ? displayStage(uploadLifecycle.current_stage) + " · " : ""}
                    {uploadLifecycle.detail}
                  </p>
                  {uploadLifecycle.searchability && (
                    <div className="mt-3 rounded-xl border border-border bg-background p-3 text-[10px]">
                      <div className="flex flex-wrap gap-x-4 gap-y-1 text-dim">
                        <span>Chunk: <strong className="text-foreground">{uploadLifecycle.searchability.chunk_count}</strong></span>
                        <span>Projection ready: <strong className="text-foreground">{uploadLifecycle.searchability.ready_projection_count}/{uploadLifecycle.searchability.chunk_count}</strong></span>
                        <span>Lexical ready: <strong className="text-foreground">{uploadLifecycle.searchability.lexical_ready_projection_count}</strong></span>
                        <span>Lexical stale: <strong className="text-foreground">{uploadLifecycle.searchability.lexical_stale_count}</strong></span>
                        <span>Embedding stale: <strong className="text-foreground">{uploadLifecycle.searchability.embedding_stale_count}</strong></span>
                      </div>
                      {!!uploadLifecycle.searchability.blocking_reasons.length && (
                        <div className="mt-2 flex flex-wrap items-center gap-1.5 text-red">
                          <span className="font-semibold">Đang chặn:</span>
                          {uploadLifecycle.searchability.blocking_reasons.slice(0, 3).map((reason) => (
                            <span key={reason} className="rounded-full border border-red/30 bg-red/10 px-2 py-1">{displaySearchabilityReason(reason)}</span>
                          ))}
                        </div>
                      )}
                      {!!uploadLifecycle.searchability.warnings.length && (
                        <div className="mt-2 flex flex-wrap items-center gap-1.5 text-yellow">
                          <span className="font-semibold">Cảnh báo:</span>
                          {uploadLifecycle.searchability.warnings.slice(0, 3).map((warning) => (
                            <span key={warning} className="rounded-full border border-yellow/30 bg-yellow/10 px-2 py-1">{displaySearchabilityReason(warning)}</span>
                          ))}
                        </div>
                      )}
                    </div>
                  )}
                  {uploadLifecycle.using_lifecycle_fallback && (
                    <div className="mt-3 rounded-lg border border-yellow/30 bg-yellow/10 px-3 py-2 text-[10px] leading-4 text-yellow">
                      Server chưa có endpoint searchability (404); trạng thái đang dùng fallback lifecycle để tương thích migration cũ.
                    </div>
                  )}
                  {uploadLifecycle.phase === "TIMEOUT" && (
                    <button type="button" onClick={() => setUploadLifecycle((current) => current ? { ...current, phase: "PROCESSING", started_at: Date.now(), detail: "Đang theo dõi lại lifecycle…" } : current)} className="mt-3 rounded-lg border border-border px-3 py-2 text-xs font-semibold">Theo dõi lại</button>
                  )}
                  {uploadLifecycle.phase === "FAILED" && (
                    <button type="button" onClick={() => { setSelectedId(uploadLifecycle.document_id); setSection("PROCESSING"); }} className="mt-3 rounded-lg border border-red/30 px-3 py-2 text-xs font-semibold text-red">Xem lỗi xử lý</button>
                  )}
                </section>
              )}
              <div className="grid min-h-[580px] gap-5 xl:grid-cols-[360px_1fr]">
                <div className="overflow-hidden rounded-2xl border border-border bg-panel">
                  <div className="border-b border-border px-4 py-3 text-xs font-semibold">{visibleDocuments.length} tài liệu</div>
                  <div className="max-h-[680px] overflow-y-auto p-2">
                    {visibleDocuments.map((document) => (
                      <button key={document.id} onClick={() => setSelectedId(document.id)} className={`mb-1 w-full rounded-xl border px-3 py-3 text-left ${selectedId === document.id ? "border-accent bg-accent/10" : "border-transparent hover:bg-inset"}`}>
                        <div className="flex items-start justify-between gap-3"><span className="line-clamp-2 text-sm font-semibold">{document.title}</span><StatusBadge value={document.status} /></div>
                        <div className="mt-2 text-[10px] text-faint">Cập nhật {formatDate(document.updated_at)}</div>
                      </button>
                    ))}
                  </div>
                </div>
                {selected ? (
                  <div className="space-y-5">
                    <section className="rounded-2xl border border-border bg-panel p-5">
                      <div className="flex items-start justify-between gap-4"><div><div className="font-heading text-xl font-bold">{selected.title}</div><p className="mt-2 text-sm leading-6 text-dim">{selected.description || "Chưa có mô tả"}</p></div><StatusBadge value={selected.status} /></div>
                      <div className="mt-4 grid grid-cols-2 gap-3 text-xs md:grid-cols-4"><div><span className="text-faint">Loại tài liệu</span><div className="mt-1 font-medium">{selected.document_type || "—"}</div></div><div><span className="text-faint">Danh mục</span><div className="mt-1 font-medium">{selected.category || "—"}</div></div><div><span className="text-faint">Phiên bản hiện hành</span><div className="mt-1 truncate font-medium">{selected.current_version_id || "—"}</div></div><div><span className="text-faint">Phòng ban sở hữu</span><div className="mt-1 truncate font-medium">{selected.owner_department_id || "—"}</div></div></div>
                      {canArchiveDocuments && selected.status !== "ARCHIVED" && (
                        <details className="mt-4 rounded-lg border border-border bg-background px-3 py-2 text-xs">
                          <summary className="cursor-pointer text-faint">Thao tác khác</summary>
                          <div className="mt-3 border-t border-border pt-3">
                            <p className="mb-2 text-[10px] leading-4 text-faint">Lưu trữ sẽ gỡ tài liệu khỏi chatbot. Đây không phải bước cần làm sau khi upload.</p>
                            <button onClick={() => void archive()} className="rounded-lg border border-red/30 px-3 py-2 text-xs text-red hover:bg-red/10">Lưu trữ tài liệu</button>
                          </div>
                        </details>
                      )}
                    </section>
                    <section className="rounded-2xl border border-border bg-panel p-5">
                      <div className="mb-4 flex items-center justify-between"><div className="font-heading text-base font-semibold">Lịch sử phiên bản</div><span className="text-xs text-faint">{versions.length} phiên bản</span></div>
                      {canManageDocuments && selected.status !== "ARCHIVED" && (
                        <form onSubmit={addVersion} className="mb-4 grid gap-2 md:grid-cols-[1fr_auto]">
                          <label className="flex min-w-0 cursor-pointer items-center gap-2 rounded-lg border border-border bg-background px-3 py-2 text-xs hover:bg-inset"><Icon icon="lucide:upload" width={14} /><span className="truncate">{sourceFile?.name || "Chọn tệp cho phiên bản mới"}</span><input key={sourceInputKey} type="file" onChange={(event) => setSourceFile(event.target.files?.[0] || null)} accept=".pdf,.docx,.pptx,.xlsx,.csv,.md,.markdown,.html,.htm,.txt" className="sr-only" /></label>
                          <button disabled={uploadingSource || !sourceFile} className="rounded-lg bg-foreground px-3 py-2 text-xs font-semibold text-background disabled:cursor-not-allowed disabled:opacity-50">{uploadingSource ? "Đang tải lên…" : "Tải phiên bản mới"}</button>
                        </form>
                      )}
                      <div className="space-y-2">
                        {versions.map((version) => (
                          <div key={version.id} className="rounded-xl border border-border bg-background p-3">
                            <div className="flex flex-wrap items-center justify-between gap-3"><div><span className="font-heading text-sm font-semibold">v{version.version_number}</span><span className="ml-2 text-[10px] text-faint">{formatDate(version.created_at)}</span></div><StatusBadge value={version.status} /></div>
                            <div className="mt-3 flex flex-wrap gap-2">
                              <button type="button" onClick={() => void openVersionSource(version)} className="rounded-md border border-border px-2.5 py-1.5 text-[11px] text-dim hover:bg-inset">Mở nguồn</button>
                              {canUseReviewWorkspace && (
                                <button
                                  type="button"
                                  onClick={() => void toggleReviewWorkspace(version)}
                                  disabled={loadingReviewVersionId === version.id}
                                  aria-expanded={reviewContext?.version.id === version.id}
                                  className="rounded-md border border-accent/40 bg-accent/5 px-2.5 py-1.5 text-[11px] font-semibold text-accent hover:bg-accent/10 disabled:cursor-wait disabled:opacity-60"
                                >
                                  <Icon
                                    icon={loadingReviewVersionId === version.id ? "lucide:loader-circle" : "lucide:scan-text"}
                                    width={13}
                                    className={`mr-1 inline ${loadingReviewVersionId === version.id ? "animate-spin" : ""}`}
                                  />
                                  {loadingReviewVersionId === version.id
                                    ? "Đang tải nội dung…"
                                    : reviewContext?.version.id === version.id
                                      ? "Ẩn nội dung trích xuất"
                                      : "Xem nội dung trích xuất"}
                                </button>
                              )}
                              {canPublishDocuments && selected.status !== "ARCHIVED" && version.status === "READY_FOR_REVIEW" && <button disabled={publishingVersionId !== null} onClick={() => void publish(version)} className="rounded-md bg-accent px-3 py-1.5 text-[11px] font-semibold text-accent-foreground disabled:cursor-wait disabled:opacity-60"><Icon icon={publishingVersionId === version.id ? "lucide:loader-circle" : "lucide:message-circle-check"} width={13} className={`mr-1 inline ${publishingVersionId === version.id ? "animate-spin" : ""}`} />{publishingVersionId === version.id ? "Đang đưa vào chatbot…" : "Đưa vào chatbot"}</button>}
                              {canReviewDocuments && selected.status !== "ARCHIVED" && version.status === "READY_FOR_REVIEW" && (
                                <details className="relative rounded-md border border-border px-2.5 py-1.5 text-[11px] text-dim">
                                  <summary className="cursor-pointer">Chỉ khi có vấn đề</summary>
                                  <div className="mt-2 flex flex-wrap gap-2 border-t border-border pt-2">
                                    {!canPublishDocuments && <button onClick={() => void review(version, "APPROVE")} className="rounded-md bg-green/10 px-2.5 py-1.5 text-green">Phê duyệt</button>}
                                    <button onClick={() => void review(version, "REJECT")} className="rounded-md bg-red/10 px-2.5 py-1.5 text-red">Không sử dụng</button>
                                    <button onClick={() => void review(version, "REPROCESS")} className="rounded-md bg-yellow/10 px-2.5 py-1.5 text-yellow">Xử lý lại</button>
                                  </div>
                                </details>
                              )}
                            </div>
                            {selected.status === "ARCHIVED" && (
                              <p className="mt-3 rounded-lg border border-border bg-panel px-3 py-2 text-[10px] leading-4 text-faint">
                                Tài liệu đã được lưu trữ. Bạn vẫn có thể xem nguồn và nội dung trích xuất, nhưng không thể kiểm duyệt hoặc xuất bản phiên bản này.
                              </p>
                            )}
                            {reviewContext?.version.id === version.id && (
                              <ReviewWorkspace
                                context={reviewContext}
                                onOpenSource={() => void openVersionSource(version)}
                              />
                            )}
                          </div>
                        ))}
                      </div>
                    </section>
                  </div>
                ) : <EmptyState icon="lucide:file-plus-2" title="Chưa có tài liệu" description="Tải tài liệu đầu tiên lên để bắt đầu quy trình xử lý, kiểm duyệt và xuất bản." />}
              </div>
            </div>
          )}

          {section === "ACCESS" && (
            <div>
              <h1 className="font-heading text-2xl font-bold">Phân quyền truy cập tài liệu</h1><p className="mt-1 text-sm text-dim">Mặc định từ chối truy cập. Người dùng chỉ có quyền khi được cấp trực tiếp hoặc thông qua vai trò, nhóm hay phòng ban.</p>
              {!selected ? <div className="mt-6"><EmptyState icon="lucide:shield-x" title="Chọn một tài liệu" description="Chọn tài liệu tại mục Tài liệu và phiên bản trước khi cấu hình quyền truy cập." /></div> : (
                <div className="mt-6 grid gap-5 xl:grid-cols-[1fr_420px]">
                  <section className="rounded-2xl border border-border bg-panel p-5"><div className="mb-4 font-heading font-semibold">Các quyền đã cấp · {selected.title}</div><div className="space-y-2">{permissions.map((item) => <div key={item.id} className="flex items-center justify-between gap-3 rounded-xl border border-border bg-background p-3"><div className="min-w-0"><div className="flex items-center gap-2"><div className="truncate text-xs font-semibold">{SUBJECT_TYPE_LABEL[item.subject_type || "SUBJECT"] || item.subject_type} · {item.subject_id}</div><StatusBadge value={item.status} /></div><div className="mt-1 text-[10px] text-faint">{DOCUMENT_PERMISSION_LABEL[item.permission]} · cấp {formatDate(item.granted_at)}{item.revoked_at ? ` · thu hồi ${formatDate(item.revoked_at)}` : ""}</div></div>{item.status === "ACTIVE" && <button onClick={() => void revoke(item)} className="rounded-md border border-red/30 px-2 py-1 text-[10px] text-red">Thu hồi</button>}</div>)}{!permissions.length && <div className="py-12 text-center text-xs text-faint">Chưa cấp quyền cho đối tượng nào — mọi truy cập đều bị từ chối.</div>}</div></section>
                  <div className="space-y-5"><form onSubmit={grant} className="rounded-2xl border border-border bg-panel p-5"><div className="mb-4 font-heading font-semibold">Cấp quyền mới</div><div className="space-y-3"><select value={subjectType} onChange={(event) => setSubjectType(event.target.value as AccessSubject["subject_type"])} className="w-full rounded-lg border border-border bg-background px-3 py-2 text-xs"><option value="USER">Người dùng</option><option value="ROLE">Vai trò</option><option value="GROUP">Nhóm</option><option value="DEPARTMENT">Phòng ban</option></select><select value={subjectId} onChange={(event) => setSubjectId(event.target.value)} className="w-full rounded-lg border border-border bg-background px-3 py-2 text-xs"><option value="">Chọn đối tượng nhận quyền</option>{accessSubjects.map((item) => <option key={item.id} value={item.id}>{accessSubjectLabel(item)}</option>)}</select><select value={permission} onChange={(event) => setPermission(event.target.value as DocumentPermission)} className="w-full rounded-lg border border-border bg-background px-3 py-2 text-xs">{(Object.keys(DOCUMENT_PERMISSION_LABEL) as DocumentPermission[]).map((value) => <option key={value} value={value}>{DOCUMENT_PERMISSION_LABEL[value]}</option>)}</select><button disabled={!subjectId} className="w-full rounded-lg bg-accent px-3 py-2 text-xs font-semibold text-accent-foreground disabled:opacity-50">Cấp quyền và ghi nhật ký</button></div></form><form onSubmit={testAccess} className="rounded-2xl border border-border bg-panel p-5"><div className="mb-3 font-heading font-semibold">Kiểm tra quyền thực tế</div><input value={testUserId} onChange={(event) => setTestUserId(event.target.value)} placeholder="UUID người dùng" className="w-full rounded-lg border border-border bg-background px-3 py-2 text-xs" /><button className="mt-3 w-full rounded-lg border border-border px-3 py-2 text-xs">Kiểm tra quyền xem tài liệu</button>{testResult && <div className={`mt-3 rounded-lg px-3 py-2 text-xs font-semibold ${testResult.startsWith("Được phép") ? "bg-green/10 text-green" : "bg-red/10 text-red"}`}>{testResult}</div>}</form></div>
                </div>
              )}
            </div>
          )}

          {section === "PROCESSING" && (
            <div>
              <h1 className="font-heading text-2xl font-bold">Theo dõi xử lý tài liệu</h1>
              <p className="mt-1 text-sm text-dim">Theo dõi từng lần xử lý theo tài liệu và phiên bản. Khi chạy lại, hệ thống tạo lần xử lý mới và vẫn giữ lịch sử cũ.</p>
              <div className="mt-6 grid gap-3 rounded-2xl border border-border bg-panel p-4 md:grid-cols-3">
                <select value={selectedId || ""} onChange={(event) => setSelectedId(event.target.value || null)} className="rounded-lg border border-border bg-background px-3 py-2 text-xs">
                  <option value="">Tất cả tài liệu</option>
                  {documents.map((document) => <option key={document.id} value={document.id}>{document.title} · {displayStatus(document.status)}</option>)}
                </select>
                <select value={processingVersionId} disabled={!selectedId} onChange={(event) => setProcessingVersionId(event.target.value)} className="rounded-lg border border-border bg-background px-3 py-2 text-xs disabled:opacity-50">
                  <option value="">Tất cả phiên bản</option>
                  {versions.map((version) => <option key={version.id} value={version.id}>Phiên bản {version.version_number} · {displayStatus(version.status)}</option>)}
                </select>
                <select value={processingStatus} onChange={(event) => setProcessingStatus(event.target.value as ProcessingStatus | "ALL")} className="rounded-lg border border-border bg-background px-3 py-2 text-xs">
                  <option value="ALL">Tất cả trạng thái</option>
                  {(["PENDING", "RUNNING", "SUCCEEDED", "FAILED", "CANCELLED"] as const).map((status) => <option key={status} value={status}>{displayStatus(status)}</option>)}
                </select>
              </div>
              <div className="mt-5 grid gap-5 xl:grid-cols-[380px_1fr]">
                <section className="rounded-2xl border border-border bg-panel p-4">
                  <div className="mb-3 flex items-center justify-between"><div className="font-heading text-sm font-semibold">Các lần xử lý · {processingJobs.length}</div>{loadingProcessingJobs && <Icon icon="lucide:loader-circle" className="animate-spin text-faint" width={15} />}</div>
                  <div className="max-h-[620px] space-y-2 overflow-y-auto">
                    {processingJobs.map((item) => (
                      <button key={item.id} onClick={() => void inspectJob(item.id)} className={`w-full rounded-xl border p-3 text-left ${job?.id === item.id ? "border-accent bg-accent/10" : "border-border bg-background hover:bg-inset"}`}>
                        <div className="flex items-center justify-between gap-2"><span className="text-xs font-semibold">Lần #{item.attempt_no} · {PROCESSING_JOB_TYPE_LABEL[item.job_type] || item.job_type}</span><StatusBadge value={item.status} /></div>
                        <div className="mt-2 truncate text-[10px] text-faint">{displayStage(item.current_stage)} · {formatDate(item.requested_at)}</div>
                      </button>
                    ))}
                    {!loadingProcessingJobs && !processingJobs.length && <div className="py-14 text-center text-xs text-faint">Không có lần xử lý nào phù hợp với bộ lọc.</div>}
                  </div>
                </section>
                {job ? (
                  <section className="rounded-2xl border border-border bg-panel p-5">
                    <div className="flex items-center justify-between"><div className="font-heading text-lg font-semibold">Lần xử lý #{job.attempt_no}</div><StatusBadge value={job.status} /></div>
                    <div className="mt-5 grid grid-cols-2 gap-4 text-xs"><div><span className="text-faint">Bước hiện tại</span><div className="mt-1 font-semibold">{displayStage(job.current_stage)}</div></div><div><span className="text-faint">Loại xử lý</span><div className="mt-1 font-semibold">{PROCESSING_JOB_TYPE_LABEL[job.job_type] || job.job_type}</div></div><div><span className="text-faint">Bắt đầu</span><div className="mt-1">{formatDate(job.started_at)}</div></div><div><span className="text-faint">Hoàn tất</span><div className="mt-1">{formatDate(job.completed_at)}</div></div></div>
                    {!!job.stage_history.length && <div className="mt-5"><div className="mb-2 text-xs font-semibold">Lịch sử các bước</div><div className="space-y-2">{job.stage_history.map((stage) => <div key={stage.id} className="rounded-lg border border-border bg-background p-3 text-xs"><div className="flex items-center justify-between gap-3"><span className="font-semibold">{displayStage(stage.stage)}</span><StatusBadge value={stage.status} /></div><div className="mt-1 text-[10px] text-faint">{formatDate(stage.started_at)} → {formatDate(stage.completed_at)}</div>{stage.message && <div className="mt-2 text-dim">{stage.message}</div>}</div>)}</div></div>}
                    {!!job.errors.length && <div className="mt-5 space-y-2">{job.errors.map((item) => <div key={item.id} className="rounded-xl border border-red/30 bg-red/10 p-3 text-xs text-red"><div className="font-semibold">{item.error_code} · {item.error_type}</div><div className="mt-1">{item.safe_message}</div><div className="mt-1 text-[10px] opacity-75">{item.retryable ? "Có thể chạy lại" : "Cần xử lý thủ công"} · {formatDate(item.created_at)}</div></div>)}</div>}
                    {!job.errors.length && job.error_code && <div className="mt-4 rounded-xl border border-red/30 bg-red/10 p-3 text-xs text-red"><div className="font-semibold">{job.error_code}</div><div className="mt-1">{job.error_message}</div></div>}
                    {selected?.status !== "ARCHIVED" && (job.status === "FAILED" || job.status === "CANCELLED") && <button onClick={() => void retryJob()} className="mt-4 rounded-lg bg-accent px-3 py-2 text-xs font-semibold text-accent-foreground">Chạy lại bằng yêu cầu mới</button>}
                  </section>
                ) : <EmptyState icon="lucide:workflow" title="Chọn một lần xử lý" description="Lịch sử từng bước và thông tin lỗi an toàn sẽ hiển thị tại đây." />}
              </div>
            </div>
          )}

          {section === "ISSUES" && <EnterpriseIssuesPanel />}
          {section === "IDENTITY" && <IdentityAdminPanel permissions={functionalPermissions} onError={setError} onSuccess={success} />}
          {section === "GOVERNANCE" && <GovernanceAdminPanel permissions={functionalPermissions} onError={setError} onSuccess={success} />}
        </div>
      </main>
    </div>
  );
}
