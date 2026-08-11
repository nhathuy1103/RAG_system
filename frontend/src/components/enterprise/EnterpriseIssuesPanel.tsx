import { Icon } from "@iconify/react";
import { useEffect, useMemo, useState } from "react";
import {
  EnterpriseDocumentRelation,
  EnterpriseDocumentRelationAction,
  EnterpriseDocumentRelationEvidence,
  EnterpriseDocumentRelationStatus,
  getEnterpriseRelationEvidence,
  listEnterpriseRelations,
  resolveEnterpriseRelation,
} from "../../lib/enterpriseApi";

const STATUS_OPTIONS: Array<{
  value: EnterpriseDocumentRelationStatus;
  label: string;
}> = [
  { value: "pending", label: "Chờ xử lý" },
  { value: "deferred", label: "Xử lý sau" },
  { value: "auto_confirmed", label: "Tự động xác nhận" },
  { value: "confirmed", label: "Đã xác nhận" },
  { value: "dismissed", label: "Đã bỏ qua" },
];

const DECISION_OPTIONS: Array<{
  value: Exclude<EnterpriseDocumentRelationAction, "defer_review">;
  label: string;
}> = [
  { value: "confirm_duplicate", label: "Xác nhận trùng lặp" },
  { value: "mark_version", label: "Đánh dấu là phiên bản mới" },
  { value: "confirm_conflict", label: "Xác nhận mâu thuẫn" },
  { value: "keep_separate", label: "Giữ hai tài liệu độc lập" },
  { value: "prefer_source", label: "Ưu tiên tài liệu hiện hành" },
  { value: "prefer_target", label: "Ưu tiên tài liệu được phát hiện" },
  { value: "dismiss", label: "Bỏ qua vì báo cáo sai" },
];

type StatusFilter = "all" | EnterpriseDocumentRelationStatus;

function StatusBadge({ status }: { status: EnterpriseDocumentRelationStatus }) {
  const styles: Record<string, string> = {
    pending: "border-yellow/30 bg-yellow/10 text-yellow",
    deferred: "border-blue/30 bg-blue/10 text-blue",
    auto_confirmed: "border-green/30 bg-green/10 text-green",
    confirmed: "border-green/30 bg-green/10 text-green",
    dismissed: "border-border bg-inset text-faint",
  };
  const label = STATUS_OPTIONS.find((option) => option.value === status)?.label || status;
  return (
    <span
      className={`rounded-full border px-2 py-1 text-[10px] font-semibold ${
        styles[status] || styles.pending
      }`}
    >
      {label}
    </span>
  );
}

function RelationTypeBadge({ type }: { type: string }) {
  const styles: Record<string, string> = {
    conflict: "border-red/30 bg-red/10 text-red",
    conflict_candidate: "border-red/30 bg-red/10 text-red",
    near_duplicate: "border-blue/30 bg-blue/10 text-blue",
    exact_content: "border-green/30 bg-green/10 text-green",
    version_candidate: "border-yellow/30 bg-yellow/10 text-yellow",
    version: "border-yellow/30 bg-yellow/10 text-yellow",
    distinct: "border-border bg-inset text-dim",
    related: "border-blue/30 bg-blue/10 text-blue",
    technical_duplicate: "border-green/30 bg-green/10 text-green",
    template_variant: "border-yellow/30 bg-yellow/10 text-yellow",
    temporal_series: "border-blue/30 bg-blue/10 text-blue",
  };
  const labels: Record<string, string> = {
    conflict: "Mâu thuẫn",
    conflict_candidate: "Có thể mâu thuẫn",
    near_duplicate: "Trùng lặp một phần",
    exact_content: "Trùng lặp hoàn toàn",
    version_candidate: "Có thể là phiên bản mới",
    version: "Cùng dòng phiên bản",
    distinct: "Tài liệu độc lập",
    related: "Có liên quan",
    technical_duplicate: "File trùng",
    template_variant: "Cùng mẫu, khác phạm vi",
    temporal_series: "Chuỗi dữ liệu theo thời kỳ",
  };
  return (
    <span
      className={`rounded-md border px-2 py-1 text-[11px] font-semibold ${
        styles[type] || styles.conflict
      }`}
    >
      {labels[type] || type}
    </span>
  );
}

export default function EnterpriseIssuesPanel() {
  const [relations, setRelations] = useState<EnterpriseDocumentRelation[]>([]);
  const [loading, setLoading] = useState(true);
  const [selectedRelation, setSelectedRelation] = useState<EnterpriseDocumentRelation | null>(null);
  const [evidence, setEvidence] = useState<EnterpriseDocumentRelationEvidence | null>(null);
  const [loadingEvidence, setLoadingEvidence] = useState(false);
  const [reason, setReason] = useState("");
  const [decisionAction, setDecisionAction] = useState<
    Exclude<EnterpriseDocumentRelationAction, "defer_review">
  >("confirm_conflict");
  const [statusFilter, setStatusFilter] = useState<StatusFilter>("pending");
  const [resolving, setResolving] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);

  const statusCounts = useMemo(() => {
    const counts: Record<EnterpriseDocumentRelationStatus, number> = {
      pending: 0,
      deferred: 0,
      auto_confirmed: 0,
      confirmed: 0,
      dismissed: 0,
    };
    relations.forEach((relation) => {
      counts[relation.status] += 1;
    });
    return counts;
  }, [relations]);

  const filteredRelations = useMemo(
    () => relations.filter(
      (relation) => statusFilter === "all" || relation.status === statusFilter,
    ),
    [relations, statusFilter],
  );

  useEffect(() => {
    let cancelled = false;
    listEnterpriseRelations()
      .then((data) => {
        if (!cancelled) setRelations(data.items);
      })
      .catch((err) => {
        if (!cancelled) setError(err.message);
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, []);

  useEffect(() => {
    if (!selectedRelation) {
      setEvidence(null);
      return;
    }
    let cancelled = false;
    setLoadingEvidence(true);
    getEnterpriseRelationEvidence(selectedRelation.id)
      .then((data) => {
        if (!cancelled) setEvidence(data);
      })
      .catch((err) => {
        if (!cancelled) setError(err.message);
      })
      .finally(() => {
        if (!cancelled) setLoadingEvidence(false);
      });
    return () => {
      cancelled = true;
    };
  }, [selectedRelation]);

  function success(message: string) {
    setNotice(message);
    setError(null);
    window.setTimeout(() => setNotice(null), 3500);
  }

  function selectRelation(relation: EnterpriseDocumentRelation) {
    setSelectedRelation(relation);
    setDecisionAction(
      relation.relation_type.includes("conflict")
        ? "confirm_conflict"
        : "confirm_duplicate",
    );
    setReason("");
    setError(null);
  }

  async function resolveIssue(action: EnterpriseDocumentRelationAction) {
    if (!selectedRelation) return;
    setResolving(true);
    try {
      const updated = await resolveEnterpriseRelation(selectedRelation.id, action, reason);
      setRelations((prev) =>
        prev.map((r) => (r.id === updated.id ? updated : r))
      );
      setReason("");
      if (action === "defer_review") {
        setSelectedRelation(null);
        success("Đã chuyển sang danh sách Xử lý sau. Bạn có thể quay lại bất cứ lúc nào.");
      } else {
        setSelectedRelation(updated);
        success("Đã lưu quyết định. Trạng thái này sẽ không bị mất khi tải lại trang.");
      }
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : "Không thể lưu quyết định.");
    } finally {
      setResolving(false);
    }
  }

  if (loading) return <div className="p-8 text-center text-sm text-dim">Đang tải dữ liệu...</div>;

  return (
    <div>
      <h1 className="font-heading text-2xl font-bold">Vấn đề & Mâu thuẫn</h1>
      <p className="mt-1 text-sm text-dim">
        Theo dõi và giải quyết các lỗi trùng lặp (duplicate) hoặc mâu thuẫn (conflict) nội dung giữa các tài liệu.
      </p>

      <div className="mt-5 flex flex-wrap gap-2" aria-label="Lọc theo trạng thái">
        <button
          type="button"
          onClick={() => setStatusFilter("all")}
          className={`rounded-full border px-3 py-1.5 text-[11px] font-semibold transition-colors ${
            statusFilter === "all"
              ? "border-accent bg-accent text-accent-foreground"
              : "border-border bg-panel text-dim hover:bg-inset"
          }`}
        >
          Tất cả · {relations.length}
        </button>
        {STATUS_OPTIONS.map((option) => (
          <button
            key={option.value}
            type="button"
            onClick={() => setStatusFilter(option.value)}
            className={`rounded-full border px-3 py-1.5 text-[11px] font-semibold transition-colors ${
              statusFilter === option.value
                ? "border-accent bg-accent text-accent-foreground"
                : "border-border bg-panel text-dim hover:bg-inset"
            }`}
          >
            {option.label} · {statusCounts[option.value]}
          </button>
        ))}
      </div>

      {error && (
        <div className="mt-5 rounded-xl border border-red/30 bg-red/10 px-4 py-3 text-sm text-red">
          {error}
        </div>
      )}
      {notice && (
        <div className="mt-5 rounded-xl border border-green/30 bg-green/10 px-4 py-3 text-sm text-green">
          {notice}
        </div>
      )}

      <div className="mt-6 grid min-h-[600px] gap-5 xl:grid-cols-[380px_1fr]">
        <div className="flex flex-col overflow-hidden rounded-2xl border border-border bg-panel">
          <div className="border-b border-border px-4 py-3 text-xs font-semibold">
            {filteredRelations.length} / {relations.length} vấn đề theo bộ lọc
          </div>
          <div className="flex-1 overflow-y-auto p-2">
            {filteredRelations.length === 0 && (
              <div className="p-8 text-center text-xs text-faint">
                Không có vấn đề nào ở trạng thái này.
              </div>
            )}
            {filteredRelations.map((relation) => (
              <button
                key={relation.id}
                type="button"
                onClick={() => selectRelation(relation)}
                className={`mb-2 w-full rounded-xl border px-3 py-3 text-left transition-colors ${
                  selectedRelation?.id === relation.id
                    ? "border-accent bg-accent/10"
                    : "border-transparent hover:bg-inset"
                }`}
              >
                <div className="flex items-start justify-between gap-2">
                  <RelationTypeBadge type={relation.relation_type} />
                  <StatusBadge status={relation.status} />
                </div>
                <div className="mt-2 text-[11px] text-foreground font-medium line-clamp-1">
                  Độ tin cậy: {(relation.confidence * 100).toFixed(1)}%
                </div>
                <div className="mt-1 text-[10px] text-faint">
                  Ngày tạo: {new Date(relation.created_at).toLocaleString("vi-VN")}
                </div>
              </button>
            ))}
          </div>
        </div>

        {selectedRelation ? (
          <div className="flex flex-col space-y-4">
            {/* Comparison Split Pane */}
            <div className="flex-1 rounded-2xl border border-border bg-panel p-5">
              <h2 className="mb-4 font-heading text-lg font-semibold">
                Giao diện so sánh
              </h2>
              {loadingEvidence ? (
                <div className="flex h-40 items-center justify-center text-xs text-dim">
                  Đang tải nội dung...
                </div>
              ) : evidence ? (
                <div className="grid grid-cols-2 gap-4">
                  {/* Source Document */}
                  <div className="flex flex-col rounded-xl border border-border bg-background p-4">
                    <div className="mb-3 border-b border-border pb-3">
                      <div className="text-[10px] font-bold uppercase tracking-wider text-faint">
                        Tài liệu hiện hành
                      </div>
                      <div className="mt-1 font-semibold text-foreground truncate" title={evidence.source_document.title}>
                        {evidence.source_document.title}
                      </div>
                      <div className="mt-1 text-xs text-dim">
                        Phiên bản {evidence.source_document.version_number}
                      </div>
                    </div>
                    <div className="flex-1 overflow-y-auto whitespace-pre-wrap text-sm leading-6 text-foreground">
                      {evidence.source_document.text_content}
                    </div>
                  </div>
                  {/* Target Document */}
                  <div className="flex flex-col rounded-xl border border-border bg-background p-4">
                    <div className="mb-3 border-b border-border pb-3">
                      <div className="text-[10px] font-bold uppercase tracking-wider text-faint">
                        Tài liệu phát hiện trùng/mâu thuẫn
                      </div>
                      <div className="mt-1 font-semibold text-foreground truncate" title={evidence.target_document.title}>
                        {evidence.target_document.title}
                      </div>
                      <div className="mt-1 text-xs text-dim">
                        Phiên bản {evidence.target_document.version_number}
                      </div>
                    </div>
                    <div className="flex-1 overflow-y-auto whitespace-pre-wrap text-sm leading-6 text-foreground">
                      {evidence.target_document.text_content}
                    </div>
                  </div>
                </div>
              ) : (
                <div className="text-center text-xs text-faint p-4">
                  Không tìm thấy dữ liệu so sánh.
                </div>
              )}
              {evidence?.overlaps && evidence.overlaps.length > 0 && (
                <div className="mt-4 rounded-xl border border-red/20 bg-red/5 p-4">
                  <div className="mb-2 text-xs font-semibold text-red flex items-center gap-2">
                    <Icon icon="lucide:alert-circle" width={16} />
                    Điểm cần lưu ý (Highlight)
                  </div>
                  {evidence.overlaps.map((overlap, idx) => (
                    <div key={idx} className="grid grid-cols-2 gap-4 text-xs">
                      <div className="rounded bg-red/10 p-2 text-red-900 dark:text-red-300">
                        "{overlap.source_text}"
                      </div>
                      <div className="rounded bg-red/10 p-2 text-red-900 dark:text-red-300">
                        "{overlap.target_text}"
                      </div>
                    </div>
                  ))}
                </div>
              )}
            </div>

            {/* Action Panel */}
            <div className="rounded-2xl border border-border bg-panel p-5">
              <h3 className="font-heading text-sm font-semibold mb-3">Đánh giá & Quyết định</h3>
              {selectedRelation.status === "pending" || selectedRelation.status === "deferred" ? (
                <div className="flex flex-col gap-3">
                  {selectedRelation.status === "deferred" && (
                    <div className="rounded-lg border border-blue/30 bg-blue/10 px-3 py-2 text-xs text-blue">
                      Mục này đang ở danh sách Xử lý sau. Bạn vẫn có thể quyết định ngay bên dưới.
                    </div>
                  )}
                  <label className="text-xs font-semibold text-foreground" htmlFor="enterprise-relation-decision">
                    Chọn cách xử lý
                  </label>
                  <select
                    id="enterprise-relation-decision"
                    value={decisionAction}
                    onChange={(event) => setDecisionAction(
                      event.target.value as Exclude<EnterpriseDocumentRelationAction, "defer_review">,
                    )}
                    className="w-full rounded-lg border border-border bg-background px-3 py-2.5 text-xs focus:border-accent focus:outline-none focus:ring-1 focus:ring-accent"
                  >
                    {DECISION_OPTIONS.map((option) => (
                      <option key={option.value} value={option.value}>{option.label}</option>
                    ))}
                  </select>
                  <textarea
                    value={reason}
                    onChange={(e) => setReason(e.target.value)}
                    placeholder="Nhập lý do cho quyết định của bạn (bắt buộc)..."
                    className="h-20 w-full resize-none rounded-lg border border-border bg-background p-3 text-xs focus:border-accent focus:outline-none focus:ring-1 focus:ring-accent"
                  />
                  <div className="flex flex-wrap items-center gap-2">
                    <button
                      type="button"
                      disabled={!reason.trim() || resolving}
                      onClick={() => void resolveIssue(decisionAction)}
                      className="rounded-lg bg-accent px-4 py-2 text-xs font-semibold text-accent-foreground hover:opacity-90 disabled:opacity-50"
                    >
                      {resolving ? "Đang lưu..." : "Lưu quyết định"}
                    </button>
                    <button
                      type="button"
                      disabled={resolving}
                      onClick={() => void resolveIssue("defer_review")}
                      className="rounded-lg border border-blue/30 bg-blue/10 px-4 py-2 text-xs font-semibold text-blue hover:bg-blue/20 disabled:opacity-50"
                    >
                      <Icon icon="lucide:clock-3" width={14} className="mr-1 inline" />
                      Không có thời gian · Xử lý sau
                    </button>
                  </div>
                  <p className="text-[10px] leading-4 text-faint">
                    “Xử lý sau” không yêu cầu nhập lý do và sẽ tạm ngừng nhắc mục này trong hàng chờ chính.
                  </p>
                </div>
              ) : (
                <div className="rounded-lg border border-green/30 bg-green/10 p-4">
                  <div className="text-sm font-semibold text-green flex items-center gap-2">
                    <Icon icon="lucide:check-circle" width={18} />
                    Vấn đề này đã được xử lý
                  </div>
                  <div className="mt-2 flex flex-wrap items-center gap-2 text-xs text-green/80">
                    <StatusBadge status={selectedRelation.status} />
                    <span>Lý do: {selectedRelation.reason || "Không có ghi chú"}</span>
                  </div>
                </div>
              )}
            </div>
          </div>
        ) : (
          <div className="flex items-center justify-center rounded-2xl border border-dashed border-border bg-panel/50 p-8 text-center">
            <div>
              <Icon icon="lucide:split" width={48} className="mx-auto text-faint" />
              <div className="mt-4 font-heading text-lg font-semibold text-foreground">
                Chọn một vấn đề để so sánh
              </div>
              <p className="mt-2 text-sm text-dim">
                Chi tiết tài liệu và giao diện đánh giá sẽ hiển thị tại đây.
              </p>
            </div>
          </div>
        )}
      </div>
    </div>
  );
}
