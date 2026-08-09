import { Icon } from "@iconify/react";
import { FormEvent, useEffect, useMemo, useState } from "react";
import { Navigate } from "react-router-dom";

import { GovernanceAdminPanel, IdentityAdminPanel } from "./EnterpriseAdminPanels";

import {
  AccessSubject,
  DocumentPermission,
  DocumentStatus,
  DocumentVersion,
  DocumentVersionReviewContext,
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
  getProcessingJob,
  grantDocumentPermission,
  listEnterpriseAccessSubjects,
  listDocumentPermissions,
  listDocumentVersions,
  listKnowledgeDocuments,
  listProcessingJobs,
  publishDocumentVersion,
  retryProcessingJob,
  reviewDocumentVersion,
  revokeDocumentPermission,
  testDocumentPermission,
  updateKnowledgeDocument,
  uploadInitialKnowledgeDocument,
  uploadEnterpriseSourceFile,
} from "../../lib/enterpriseApi";

type Section = "DOCUMENTS" | "ACCESS" | "PROCESSING" | "IDENTITY" | "GOVERNANCE";

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

function StatusBadge({ value }: { value: string }) {
  return <span className={`rounded-full border px-2 py-1 text-[10px] font-semibold ${STATUS_STYLE[value] || STATUS_STYLE.DRAFT}`}>{value}</span>;
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
          <div className="font-heading text-sm font-semibold">Review workspace</div>
          <div className="mt-1 text-[10px] text-faint">{context.source_file.original_file_name} · {(context.source_file.size_bytes / 1024).toFixed(1)} KB · SHA-256 {context.source_file.sha256?.slice(0, 16) || "—"}…</div>
        </div>
        <button onClick={onOpenSource} className="rounded-md border border-border px-2.5 py-1.5 text-[11px] text-dim hover:bg-inset"><Icon icon="lucide:external-link" width={13} className="mr-1 inline" />Mở file gốc</button>
      </div>
      {context.latest_processing_job && <div className="mt-3 flex items-center gap-2 rounded-lg border border-border bg-background p-3 text-xs"><span className="font-semibold">Processing #{context.latest_processing_job.attempt_no}</span><StatusBadge value={context.latest_processing_job.status} /><span className="text-faint">{context.latest_processing_job.current_stage || "—"}</span></div>}
      {!!context.stage_history.length && <div className="mt-3 flex flex-wrap gap-2">{context.stage_history.map((stage) => <span key={stage.id} className="rounded-full border border-border bg-background px-2 py-1 text-[10px] text-dim">{stage.stage} · {stage.status}</span>)}</div>}
      {!!context.errors.length && <div className="mt-3 space-y-2">{context.errors.map((item) => <div key={item.id} className="rounded-lg border border-red/30 bg-red/10 p-3 text-xs text-red"><div className="font-semibold">{item.error_code} · {item.error_type}</div><div className="mt-1">{item.safe_message}</div></div>)}</div>}
      <div className="mt-4 flex items-center justify-between"><div className="text-xs font-semibold">Extracted chunks</div><span className="text-[10px] text-faint">{context.extracted_chunks.length} chunk</span></div>
      <div className="mt-2 max-h-[520px] space-y-2 overflow-y-auto pr-1">
        {context.extracted_chunks.map((chunk) => <article key={chunk.chunk_id} className="rounded-lg border border-border bg-background p-3"><div className="flex flex-wrap items-center gap-2 text-[10px] text-faint"><span className="font-semibold text-foreground">Chunk #{chunk.chunk_index}</span><span>{chunk.section_path || "Không có section"}</span><span>{chunk.page_start ? `tr. ${chunk.page_start}${chunk.page_end && chunk.page_end !== chunk.page_start ? `–${chunk.page_end}` : ""}` : ""}</span></div><p className="mt-2 whitespace-pre-wrap text-xs leading-5 text-dim">{chunk.content}</p></article>)}
        {!context.extracted_chunks.length && <div className="rounded-lg border border-dashed border-border p-8 text-center text-xs text-faint">Chưa có chunk đã trích xuất; kiểm tra processing history trước khi review.</div>}
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
  const [statusFilter, setStatusFilter] = useState<DocumentStatus | "ALL">("ALL");
  const [documentQuery, setDocumentQuery] = useState("");
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [newTitle, setNewTitle] = useState("");
  const [newDescription, setNewDescription] = useState("");
  const [initialSourceFile, setInitialSourceFile] = useState<File | null>(null);
  const [initialSourceInputKey, setInitialSourceInputKey] = useState(0);
  const [creatingInitialDocument, setCreatingInitialDocument] = useState(false);
  const [sourceFileId, setSourceFileId] = useState("");
  const [sourceFile, setSourceFile] = useState<File | null>(null);
  const [sourceInputKey, setSourceInputKey] = useState(0);
  const [uploadingSource, setUploadingSource] = useState(false);
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
  const [metadataDraft, setMetadataDraft] = useState({
    title: "",
    description: "",
    document_type: "",
    category: "",
    document_number: "",
    effective_date: "",
    expiration_date: "",
    owner_department_id: "",
  });

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
    if (!selected) return;
    setMetadataDraft({
      title: selected.title,
      description: selected.description || "",
      document_type: selected.document_type || "",
      category: selected.category || "",
      document_number: selected.document_number || "",
      effective_date: selected.effective_date || "",
      expiration_date: selected.expiration_date || "",
      owner_department_id: selected.owner_department_id || "",
    });
  }, [selected]);

  function success(message: string) {
    setNotice(message);
    setError(null);
    window.setTimeout(() => setNotice(null), 3500);
  }

  async function createDocument(event: FormEvent) {
    event.preventDefault();
    if (!canUploadDocuments || !newTitle.trim() || !initialSourceFile) return;
    setCreatingInitialDocument(true);
    try {
      const created = await uploadInitialKnowledgeDocument(initialSourceFile, {
        title: newTitle.trim(),
        description: newDescription.trim() || undefined,
      });
      setNewTitle("");
      setNewDescription("");
      setInitialSourceFile(null);
      setInitialSourceInputKey((current) => current + 1);
      await reloadDocuments();
      setSelectedId(created.document.id);
      success("Đã upload file và tạo Document + v1 + ProcessingJob trong một transaction");
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "Không thể upload tài liệu khởi tạo");
    } finally {
      setCreatingInitialDocument(false);
    }
  }

  async function saveMetadata(event: FormEvent) {
    event.preventDefault();
    if (
      !canManageDocuments
      || !selected
      || !selected.updated_at
      || selected.status === "ARCHIVED"
      || !metadataDraft.title.trim()
    ) return;
    try {
      await updateKnowledgeDocument(selected.id, {
        expected_updated_at: selected.updated_at,
        title: metadataDraft.title.trim(),
        description: metadataDraft.description.trim() || null,
        document_type: metadataDraft.document_type.trim() || null,
        category: metadataDraft.category.trim() || null,
        document_number: metadataDraft.document_number.trim() || null,
        effective_date: metadataDraft.effective_date || null,
        expiration_date: metadataDraft.expiration_date || null,
        owner_department_id: metadataDraft.owner_department_id.trim() || null,
      });
      await reloadDocuments();
      success("Đã cập nhật metadata; nội dung và version không thay đổi");
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "Không thể cập nhật metadata");
    }
  }

  async function addVersion(event: FormEvent) {
    event.preventDefault();
    if (
      !canManageDocuments
      || !selected
      || selected.status === "ARCHIVED"
      || (!sourceFileId.trim() && !sourceFile)
    ) return;
    setUploadingSource(true);
    try {
      const uploaded = sourceFile ? await uploadEnterpriseSourceFile(sourceFile) : null;
      const resolvedSourceId = uploaded?.id || sourceFileId.trim();
      await createDocumentVersion(selected.id, { source_file_id: resolvedSourceId });
      const page = await listDocumentVersions(selected.id);
      setVersions(page.items);
      setSourceFileId("");
      setSourceFile(null);
      setSourceInputKey((current) => current + 1);
      success("Đã upload source, tạo version và processing job");
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "Không thể tạo version");
    } finally {
      setUploadingSource(false);
    }
  }

  async function review(version: DocumentVersion, decision: "APPROVE" | "REJECT" | "REPROCESS") {
    if (!canReviewDocuments || selected?.status === "ARCHIVED") return;
    try {
      await reviewDocumentVersion(version.id, {
        decision,
        note: decision === "APPROVE" ? "Approved from Enterprise Admin Portal" : undefined,
        rejection_reason: decision === "REJECT" ? "Rejected from Enterprise Admin Portal" : undefined,
      });
      const page = await listDocumentVersions(version.document_id);
      setVersions(page.items);
      success(`Đã ghi nhận quyết định ${decision}`);
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "Không thể kiểm duyệt version");
    }
  }

  async function publish(version: DocumentVersion) {
    if (!canPublishDocuments || selected?.status === "ARCHIVED") return;
    try {
      await publishDocumentVersion(version.id);
      await reloadDocuments();
      const page = await listDocumentVersions(version.document_id);
      setVersions(page.items);
      success("Publish thành công; version cũ đã được supersede atomically");
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "Không thể publish version");
    }
  }

  async function archive() {
    if (!canArchiveDocuments || !selected || selected.status === "ARCHIVED") return;
    const reason = window.prompt("Lý do archive tài liệu:");
    if (!reason?.trim()) return;
    try {
      await archiveKnowledgeDocument(selected.id, reason.trim());
      await reloadDocuments();
      success("Đã archive tài liệu; version và audit vẫn được giữ");
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "Không thể archive tài liệu");
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
      success("Đã cấp quyền và ghi audit");
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
      success("Đã thu hồi assignment; effective permission sẽ được tính lại ở request tiếp theo");
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "Không thể thu hồi quyền");
    }
  }

  async function testAccess(event: FormEvent) {
    event.preventDefault();
    if (!selected || !testUserId.trim()) return;
    try {
      const result = await testDocumentPermission(selected.id, testUserId.trim(), "READ");
      setTestResult(result.allowed ? `ALLOWED · ${result.sources?.join(", ") || "effective grant"}` : "DENIED · default deny");
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "Không thể kiểm tra quyền");
    }
  }

  async function inspectJob(jobId: string) {
    try {
      setJob(await getProcessingJob(jobId));
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "Không thể tải processing job");
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
      success("Đã tạo processing attempt mới");
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "Không thể retry job");
    }
  }

  if (loading || authorized === null) return <div className="flex flex-1 items-center justify-center text-sm text-faint">Đang xác minh quyền quản trị...</div>;
  if (!authorized) return <Navigate to="/knowledge" replace />;

  const allNavigation: Array<{ id: Section; label: string; icon: string }> = [
    { id: "DOCUMENTS", label: "Tài liệu & version", icon: "lucide:files" },
    { id: "ACCESS", label: "Phân quyền", icon: "lucide:shield-check" },
    { id: "PROCESSING", label: "Processing", icon: "lucide:workflow" },
    { id: "IDENTITY", label: "Người dùng & tổ chức", icon: "lucide:users" },
    { id: "GOVERNANCE", label: "Audit & governance", icon: "lucide:scroll-text" },
  ];
  const navigation = allNavigation.filter((item) =>
    SECTION_PERMISSIONS[item.id].some((code) => functionalPermissions.has(code)),
  );

  async function openVersionSource(version: DocumentVersion) {
    const target = window.open("", "_blank", "noopener,noreferrer");
    try {
      const source = await getDocumentVersionSource(version.document_id, version.id);
      if (target) target.location.href = source.signed_url;
      else window.location.assign(source.signed_url);
    } catch (reason) {
      target?.close();
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
      setError(reason instanceof Error ? reason.message : "Không thể tải review workspace");
    } finally {
      setLoadingReviewVersionId(null);
    }
  }

  function accessSubjectLabel(item: AccessSubject) {
    const principalId = item.user_id || item.role_id || item.group_id || item.department_id;
    return `${item.subject_type} · ${principalId || item.id}`;
  }

  return (
    <div className="flex min-h-0 flex-1 bg-background">
      <aside className="w-64 shrink-0 border-r border-border bg-panel p-4">
        <div className="px-3 pb-5 pt-2">
          <div className="text-[10px] font-semibold uppercase tracking-[0.18em] text-accent">Enterprise Control</div>
          <div className="mt-2 font-heading text-lg font-bold">Knowledge Admin</div>
        </div>
        <nav className="space-y-1">
          {navigation.map((item) => (
            <button key={item.id} onClick={() => setSection(item.id)} className={`flex w-full items-center gap-3 rounded-xl px-3 py-2.5 text-left text-xs font-medium ${section === item.id ? "bg-accent text-accent-foreground" : "text-dim hover:bg-inset hover:text-foreground"}`}>
              <Icon icon={item.icon} width={16} /> {item.label}
            </button>
          ))}
        </nav>
        <div className="mt-6 rounded-xl border border-border bg-background p-3 text-[11px] leading-5 text-faint">
          <div className="mb-1 flex items-center gap-1.5 font-semibold text-green"><Icon icon="lucide:shield-check" width={13} /> Fail-closed</div>
          Employee retrieval chỉ dùng PUBLISHED + ACTIVE + READ.
        </div>
      </aside>

      <main className="min-w-0 flex-1 overflow-y-auto p-6 lg:p-8">
        <div className="mx-auto max-w-7xl">
          {error && <div className="mb-5 rounded-xl border border-red/30 bg-red/10 px-4 py-3 text-sm text-red">{error}</div>}
          {notice && <div className="mb-5 rounded-xl border border-green/30 bg-green/10 px-4 py-3 text-sm text-green">{notice}</div>}

          {section === "DOCUMENTS" && (
            <div>
              <div className="mb-6 flex flex-wrap items-end justify-between gap-4">
                <div><h1 className="font-heading text-2xl font-bold">Tài liệu và phiên bản</h1><p className="mt-1 text-sm text-dim">Quản lý lifecycle độc lập giữa Document, Version và ProcessingJob.</p></div>
                <div className="flex gap-2">
                  <input value={documentQuery} onChange={(event) => setDocumentQuery(event.target.value)} placeholder="Tìm theo tên, loại, danh mục…" className="w-56 rounded-lg border border-border bg-panel px-3 py-2 text-xs" />
                  <select value={statusFilter} onChange={(event) => setStatusFilter(event.target.value as DocumentStatus | "ALL")} className="rounded-lg border border-border bg-panel px-3 py-2 text-xs">
                    <option value="ALL">Tất cả trạng thái</option><option>DRAFT</option><option>PUBLISHED</option><option>ARCHIVED</option>
                  </select>
                </div>
              </div>
              {canUploadDocuments && (
                <form onSubmit={createDocument} className="mb-5 grid gap-3 rounded-2xl border border-border bg-panel p-4 md:grid-cols-[1fr_1.25fr_1.25fr_auto]">
                  <input value={newTitle} onChange={(event) => setNewTitle(event.target.value)} placeholder="Tên tài liệu logic" className="rounded-lg border border-border bg-background px-3 py-2 text-sm outline-none focus:border-accent" />
                  <input value={newDescription} onChange={(event) => setNewDescription(event.target.value)} placeholder="Mô tả" className="rounded-lg border border-border bg-background px-3 py-2 text-sm outline-none focus:border-accent" />
                  <input key={initialSourceInputKey} type="file" required onChange={(event) => setInitialSourceFile(event.target.files?.[0] || null)} accept=".pdf,.docx,.pptx,.xlsx,.csv,.md,.markdown,.html,.htm,.txt" className="min-w-0 rounded-lg border border-border bg-background px-3 py-2 text-xs file:mr-2 file:rounded file:border-0 file:bg-inset file:px-2 file:py-1 file:text-[10px]" />
                  <button disabled={creatingInitialDocument || !newTitle.trim() || !initialSourceFile} className="rounded-lg bg-accent px-4 py-2 text-xs font-semibold text-accent-foreground disabled:cursor-not-allowed disabled:opacity-50">{creatingInitialDocument ? "Đang upload…" : "Upload + tạo v1"}</button>
                </form>
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
                      <div className="mt-4 grid grid-cols-2 gap-3 text-xs md:grid-cols-4"><div><span className="text-faint">Loại</span><div className="mt-1 font-medium">{selected.document_type || "—"}</div></div><div><span className="text-faint">Danh mục</span><div className="mt-1 font-medium">{selected.category || "—"}</div></div><div><span className="text-faint">Current version</span><div className="mt-1 truncate font-medium">{selected.current_version_id || "—"}</div></div><div><span className="text-faint">Department</span><div className="mt-1 truncate font-medium">{selected.owner_department_id || "—"}</div></div></div>
                      {canArchiveDocuments && selected.status !== "ARCHIVED" && <button onClick={() => void archive()} className="mt-4 rounded-lg border border-red/30 px-3 py-2 text-xs text-red hover:bg-red/10">Archive</button>}
                    </section>
                    {canManageDocuments && selected.status !== "ARCHIVED" && (
                      <form onSubmit={saveMetadata} className="rounded-2xl border border-border bg-panel p-5">
                        <div className="mb-4"><div className="font-heading text-base font-semibold">Metadata nghiệp vụ</div><p className="mt-1 text-xs text-faint">Chỉnh metadata không tạo version mới và không thay đổi file nguồn.</p></div>
                        <div className="grid gap-3 md:grid-cols-2">
                          <input value={metadataDraft.title} onChange={(event) => setMetadataDraft((current) => ({ ...current, title: event.target.value }))} placeholder="Tên tài liệu" className="rounded-lg border border-border bg-background px-3 py-2 text-xs" />
                          <input value={metadataDraft.description} onChange={(event) => setMetadataDraft((current) => ({ ...current, description: event.target.value }))} placeholder="Mô tả" className="rounded-lg border border-border bg-background px-3 py-2 text-xs" />
                          <input value={metadataDraft.document_type} onChange={(event) => setMetadataDraft((current) => ({ ...current, document_type: event.target.value }))} placeholder="Loại tài liệu" className="rounded-lg border border-border bg-background px-3 py-2 text-xs" />
                          <input value={metadataDraft.category} onChange={(event) => setMetadataDraft((current) => ({ ...current, category: event.target.value }))} placeholder="Danh mục" className="rounded-lg border border-border bg-background px-3 py-2 text-xs" />
                          <input value={metadataDraft.document_number} onChange={(event) => setMetadataDraft((current) => ({ ...current, document_number: event.target.value }))} placeholder="Số hiệu tài liệu" className="rounded-lg border border-border bg-background px-3 py-2 text-xs" />
                          <input value={metadataDraft.owner_department_id} onChange={(event) => setMetadataDraft((current) => ({ ...current, owner_department_id: event.target.value }))} placeholder="Owner Department UUID" className="rounded-lg border border-border bg-background px-3 py-2 text-xs" />
                          <label className="text-[10px] text-faint">Ngày hiệu lực<input type="date" value={metadataDraft.effective_date} onChange={(event) => setMetadataDraft((current) => ({ ...current, effective_date: event.target.value }))} className="mt-1 block w-full rounded-lg border border-border bg-background px-3 py-2 text-xs text-foreground" /></label>
                          <label className="text-[10px] text-faint">Ngày hết hiệu lực<input type="date" value={metadataDraft.expiration_date} onChange={(event) => setMetadataDraft((current) => ({ ...current, expiration_date: event.target.value }))} className="mt-1 block w-full rounded-lg border border-border bg-background px-3 py-2 text-xs text-foreground" /></label>
                        </div>
                        <button className="mt-4 rounded-lg bg-foreground px-4 py-2 text-xs font-semibold text-background">Lưu metadata</button>
                      </form>
                    )}
                    <section className="rounded-2xl border border-border bg-panel p-5">
                      <div className="mb-4 flex items-center justify-between"><div className="font-heading text-base font-semibold">Lịch sử version</div><span className="text-xs text-faint">{versions.length} version</span></div>
                      {canManageDocuments && selected.status !== "ARCHIVED" && (
                        <form onSubmit={addVersion} className="mb-4 grid gap-2 md:grid-cols-[1fr_1fr_auto]">
                          <input key={sourceInputKey} type="file" onChange={(event) => setSourceFile(event.target.files?.[0] || null)} accept=".pdf,.docx,.pptx,.xlsx,.csv,.md,.markdown,.html,.htm,.txt" className="min-w-0 rounded-lg border border-border bg-background px-3 py-2 text-xs file:mr-2 file:rounded file:border-0 file:bg-inset file:px-2 file:py-1 file:text-[10px]" />
                          <input value={sourceFileId} onChange={(event) => setSourceFileId(event.target.value)} placeholder="Hoặc Source file UUID có sẵn" className="min-w-0 rounded-lg border border-border bg-background px-3 py-2 text-xs" />
                          <button disabled={uploadingSource || (!sourceFile && !sourceFileId.trim())} className="rounded-lg bg-foreground px-3 py-2 text-xs font-semibold text-background disabled:cursor-not-allowed disabled:opacity-50">{uploadingSource ? "Đang upload…" : "Tạo version"}</button>
                        </form>
                      )}
                      <div className="space-y-2">
                        {versions.map((version) => (
                          <div key={version.id} className="rounded-xl border border-border bg-background p-3">
                            <div className="flex flex-wrap items-center justify-between gap-3"><div><span className="font-heading text-sm font-semibold">v{version.version_number}</span><span className="ml-2 text-[10px] text-faint">{formatDate(version.created_at)}</span></div><StatusBadge value={version.status} /></div>
                            <div className="mt-3 flex flex-wrap gap-2">
                              <button onClick={() => void openVersionSource(version)} className="rounded-md border border-border px-2.5 py-1.5 text-[11px] text-dim hover:bg-inset">Mở nguồn</button>
                              {canReviewDocuments && selected.status !== "ARCHIVED" && version.status === "READY_FOR_REVIEW" && <><button onClick={() => void review(version, "APPROVE")} className="rounded-md bg-green/10 px-2.5 py-1.5 text-[11px] text-green">Approve</button><button onClick={() => void review(version, "REJECT")} className="rounded-md bg-red/10 px-2.5 py-1.5 text-[11px] text-red">Reject</button><button onClick={() => void review(version, "REPROCESS")} className="rounded-md bg-yellow/10 px-2.5 py-1.5 text-[11px] text-yellow">Reprocess</button></>}
                              {canPublishDocuments && selected.status !== "ARCHIVED" && version.status === "READY_FOR_REVIEW" && <button onClick={() => void publish(version)} className="rounded-md bg-accent px-2.5 py-1.5 text-[11px] font-semibold text-accent-foreground">Publish atomically</button>}
                            </div>
                          </div>
                        ))}
                      </div>
                    </section>
                  </div>
                ) : <EmptyState icon="lucide:file-plus-2" title="Chưa có tài liệu" description="Tạo logical document đầu tiên để bắt đầu upload, xử lý, review và publish." />}
              </div>
            </div>
          )}

          {section === "ACCESS" && (
            <div>
              <h1 className="font-heading text-2xl font-bold">Document Access Control</h1><p className="mt-1 text-sm text-dim">Explicit ALLOW, mặc định DENY. Thu hồi một assignment không nhất thiết làm mất effective permission nếu còn nguồn cấp khác.</p>
              {!selected ? <div className="mt-6"><EmptyState icon="lucide:shield-x" title="Chọn một tài liệu" description="Chọn tài liệu tại mục Tài liệu & version trước khi cấu hình ACL." /></div> : (
                <div className="mt-6 grid gap-5 xl:grid-cols-[1fr_420px]">
                  <section className="rounded-2xl border border-border bg-panel p-5"><div className="mb-4 font-heading font-semibold">Assignments · {selected.title}</div><div className="space-y-2">{permissions.map((item) => <div key={item.id} className="flex items-center justify-between gap-3 rounded-xl border border-border bg-background p-3"><div className="min-w-0"><div className="flex items-center gap-2"><div className="truncate text-xs font-semibold">{item.subject_type || "SUBJECT"} · {item.subject_id}</div><StatusBadge value={item.status} /></div><div className="mt-1 text-[10px] text-faint">{item.permission} · cấp {formatDate(item.granted_at)}{item.revoked_at ? ` · thu hồi ${formatDate(item.revoked_at)}` : ""}</div></div>{item.status === "ACTIVE" && <button onClick={() => void revoke(item)} className="rounded-md border border-red/30 px-2 py-1 text-[10px] text-red">Thu hồi</button>}</div>)}{!permissions.length && <div className="py-12 text-center text-xs text-faint">Chưa có assignment — mọi truy cập bị từ chối.</div>}</div></section>
                  <div className="space-y-5"><form onSubmit={grant} className="rounded-2xl border border-border bg-panel p-5"><div className="mb-4 font-heading font-semibold">Cấp quyền</div><div className="space-y-3"><select value={subjectType} onChange={(event) => setSubjectType(event.target.value as AccessSubject["subject_type"])} className="w-full rounded-lg border border-border bg-background px-3 py-2 text-xs"><option>USER</option><option>ROLE</option><option>GROUP</option><option>DEPARTMENT</option></select><select value={subjectId} onChange={(event) => setSubjectId(event.target.value)} className="w-full rounded-lg border border-border bg-background px-3 py-2 text-xs"><option value="">Chọn access subject</option>{accessSubjects.map((item) => <option key={item.id} value={item.id}>{accessSubjectLabel(item)}</option>)}</select><select value={permission} onChange={(event) => setPermission(event.target.value as DocumentPermission)} className="w-full rounded-lg border border-border bg-background px-3 py-2 text-xs">{["READ","DOWNLOAD","MANAGE","REVIEW","PUBLISH","ARCHIVE","MANAGE_PERMISSION"].map((value) => <option key={value}>{value}</option>)}</select><button disabled={!subjectId} className="w-full rounded-lg bg-accent px-3 py-2 text-xs font-semibold text-accent-foreground disabled:opacity-50">Grant + audit</button></div></form><form onSubmit={testAccess} className="rounded-2xl border border-border bg-panel p-5"><div className="mb-3 font-heading font-semibold">Test effective access</div><input value={testUserId} onChange={(event) => setTestUserId(event.target.value)} placeholder="User UUID" className="w-full rounded-lg border border-border bg-background px-3 py-2 text-xs" /><button className="mt-3 w-full rounded-lg border border-border px-3 py-2 text-xs">Kiểm tra READ</button>{testResult && <div className={`mt-3 rounded-lg px-3 py-2 text-xs font-semibold ${testResult.startsWith("ALLOWED") ? "bg-green/10 text-green" : "bg-red/10 text-red"}`}>{testResult}</div>}</form></div>
                </div>
              )}
            </div>
          )}

          {section === "PROCESSING" && (
            <div>
              <h1 className="font-heading text-2xl font-bold">Processing Monitor</h1>
              <p className="mt-1 text-sm text-dim">Danh sách durable job theo tài liệu/version; retry tạo attempt mới và giữ nguyên lịch sử.</p>
              <div className="mt-6 grid gap-3 rounded-2xl border border-border bg-panel p-4 md:grid-cols-3">
                <select value={selectedId || ""} onChange={(event) => setSelectedId(event.target.value || null)} className="rounded-lg border border-border bg-background px-3 py-2 text-xs">
                  <option value="">Tất cả tài liệu</option>
                  {documents.map((document) => <option key={document.id} value={document.id}>{document.title} · {document.status}</option>)}
                </select>
                <select value={processingVersionId} disabled={!selectedId} onChange={(event) => setProcessingVersionId(event.target.value)} className="rounded-lg border border-border bg-background px-3 py-2 text-xs disabled:opacity-50">
                  <option value="">Tất cả version</option>
                  {versions.map((version) => <option key={version.id} value={version.id}>v{version.version_number} · {version.status}</option>)}
                </select>
                <select value={processingStatus} onChange={(event) => setProcessingStatus(event.target.value as ProcessingStatus | "ALL")} className="rounded-lg border border-border bg-background px-3 py-2 text-xs">
                  <option value="ALL">Tất cả trạng thái</option>
                  {(["PENDING", "RUNNING", "SUCCEEDED", "FAILED", "CANCELLED"] as const).map((status) => <option key={status}>{status}</option>)}
                </select>
              </div>
              <div className="mt-5 grid gap-5 xl:grid-cols-[380px_1fr]">
                <section className="rounded-2xl border border-border bg-panel p-4">
                  <div className="mb-3 flex items-center justify-between"><div className="font-heading text-sm font-semibold">Jobs · {processingJobs.length}</div>{loadingProcessingJobs && <Icon icon="lucide:loader-circle" className="animate-spin text-faint" width={15} />}</div>
                  <div className="max-h-[620px] space-y-2 overflow-y-auto">
                    {processingJobs.map((item) => (
                      <button key={item.id} onClick={() => void inspectJob(item.id)} className={`w-full rounded-xl border p-3 text-left ${job?.id === item.id ? "border-accent bg-accent/10" : "border-border bg-background hover:bg-inset"}`}>
                        <div className="flex items-center justify-between gap-2"><span className="text-xs font-semibold">Attempt #{item.attempt_no} · {item.job_type}</span><StatusBadge value={item.status} /></div>
                        <div className="mt-2 truncate text-[10px] text-faint">{item.current_stage || "Chưa bắt đầu"} · {formatDate(item.requested_at)}</div>
                      </button>
                    ))}
                    {!loadingProcessingJobs && !processingJobs.length && <div className="py-14 text-center text-xs text-faint">Không có job phù hợp bộ lọc.</div>}
                  </div>
                </section>
                {job ? (
                  <section className="rounded-2xl border border-border bg-panel p-5">
                    <div className="flex items-center justify-between"><div className="font-heading text-lg font-semibold">Attempt #{job.attempt_no}</div><StatusBadge value={job.status} /></div>
                    <div className="mt-5 grid grid-cols-2 gap-4 text-xs"><div><span className="text-faint">Stage</span><div className="mt-1 font-semibold">{job.current_stage || "—"}</div></div><div><span className="text-faint">Job type</span><div className="mt-1 font-semibold">{job.job_type}</div></div><div><span className="text-faint">Started</span><div className="mt-1">{formatDate(job.started_at)}</div></div><div><span className="text-faint">Completed</span><div className="mt-1">{formatDate(job.completed_at)}</div></div></div>
                    {!!job.stage_history.length && <div className="mt-5"><div className="mb-2 text-xs font-semibold">Stage history</div><div className="space-y-2">{job.stage_history.map((stage) => <div key={stage.id} className="rounded-lg border border-border bg-background p-3 text-xs"><div className="flex items-center justify-between gap-3"><span className="font-semibold">{stage.stage}</span><StatusBadge value={stage.status} /></div><div className="mt-1 text-[10px] text-faint">{formatDate(stage.started_at)} → {formatDate(stage.completed_at)}</div>{stage.message && <div className="mt-2 text-dim">{stage.message}</div>}</div>)}</div></div>}
                    {!!job.errors.length && <div className="mt-5 space-y-2">{job.errors.map((item) => <div key={item.id} className="rounded-xl border border-red/30 bg-red/10 p-3 text-xs text-red"><div className="font-semibold">{item.error_code} · {item.error_type}</div><div className="mt-1">{item.safe_message}</div><div className="mt-1 text-[10px] opacity-75">{item.retryable ? "Có thể retry" : "Cần xử lý thủ công"} · {formatDate(item.created_at)}</div></div>)}</div>}
                    {!job.errors.length && job.error_code && <div className="mt-4 rounded-xl border border-red/30 bg-red/10 p-3 text-xs text-red"><div className="font-semibold">{job.error_code}</div><div className="mt-1">{job.error_message}</div></div>}
                    {selected?.status !== "ARCHIVED" && (job.status === "FAILED" || job.status === "CANCELLED") && <button onClick={() => void retryJob()} className="mt-4 rounded-lg bg-accent px-3 py-2 text-xs font-semibold text-accent-foreground">Retry bằng job mới</button>}
                  </section>
                ) : <EmptyState icon="lucide:workflow" title="Chọn một processing job" description="Stage history và lỗi an toàn sẽ được hiển thị tại đây." />}
              </div>
            </div>
          )}

          {section === "IDENTITY" && <IdentityAdminPanel permissions={functionalPermissions} onError={setError} onSuccess={success} />}
          {section === "GOVERNANCE" && <GovernanceAdminPanel permissions={functionalPermissions} onError={setError} onSuccess={success} />}
        </div>
      </main>
    </div>
  );
}
