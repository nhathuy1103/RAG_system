import React, { useEffect, useMemo, useState } from 'react';
import { Icon } from '@iconify/react';

import {
  confidenceLabel,
  formatQualityTimestamp,
} from '../../lib/quality.js';
import {
  STRUCTURED_RELATION_LABELS,
  confirmActionForRelation,
  isStructuredConflict,
  structuredClaimValue,
  structuredSubjectLabel,
} from '../../lib/structuredFacts.js';
import { useStructuredFactStore } from '../../stores/structuredFactStore.js';

const compactId = (value) => (
  typeof value === 'string' && value.length > 12
    ? `${value.slice(0, 8)}…`
    : value || '—'
);

const documentName = (documentsById, documentId) => (
  documentsById.get(documentId)?.original_filename || `Tài liệu ${compactId(documentId)}`
);

const dateLabel = (value) => (
  value ? formatQualityTimestamp(value) : 'Không rõ'
);

function JsonDetails({ label, value }) {
  if (!value || typeof value !== 'object' || Object.keys(value).length === 0) {
    return null;
  }
  return (
    <details className="mt-2 text-[10px]">
      <summary className="cursor-pointer font-medium text-accent">{label}</summary>
      <pre className="mt-1 max-h-36 overflow-auto whitespace-pre-wrap break-words rounded bg-background p-2 text-[9px] leading-relaxed text-dim">
        {JSON.stringify(value, null, 2)}
      </pre>
    </details>
  );
}

function EvidenceSide({ label, snapshot, claim, documentsById, tone }) {
  const page = claim?.page_number ?? snapshot.page_from;
  return (
    <section className={`rounded-lg border p-2.5 ${tone}`}>
      <div className="mb-2 flex items-center justify-between gap-2">
        <span className="text-[10px] font-semibold uppercase text-faint">{label}</span>
        <span className="text-[9px] text-faint">Bảng {snapshot.table_index + 1}</span>
      </div>
      <div className="break-words text-[11.5px] font-medium text-foreground">
        {documentName(documentsById, snapshot.document_id)}
      </div>
      <div className="mt-1 text-[9.5px] leading-relaxed text-faint">
        {snapshot.row_count} dòng · {snapshot.column_count} cột
        {page !== null ? ` · Trang ${page}` : ''}
      </div>

      {claim ? (
        <div className="mt-2 border-t border-border pt-2">
          <div className="text-[10px] text-faint">Đối tượng</div>
          <div className="mt-0.5 break-words text-[11px] font-medium text-foreground">
            {structuredSubjectLabel(claim)}
          </div>
          <div className="mt-1.5 text-[10px] text-faint">Thuộc tính</div>
          <div className="mt-0.5 break-words text-[11px] text-dim">
            {claim.predicate}
          </div>
          <div className="mt-1.5 text-[10px] text-faint">Giá trị nguồn</div>
          <div className="mt-0.5 break-words rounded bg-inset px-2 py-1.5 text-[12px] font-semibold text-foreground">
            {structuredClaimValue(claim)}
          </div>
          {claim.source_text && (
            <div className="mt-2 whitespace-pre-wrap break-words text-[10px] leading-relaxed text-dim">
              {claim.source_text}
            </div>
          )}
          <JsonDetails label="Điều kiện áp dụng" value={claim.qualifiers} />
          <JsonDetails label="Dòng dữ liệu gốc" value={claim.source_cells} />
        </div>
      ) : (
        <div className="mt-2 rounded bg-inset px-2 py-2 text-[10px] italic text-faint">
          Quan hệ một phía: snapshot này không có claim tương ứng.
        </div>
      )}

      <div className="mt-2 border-t border-border pt-2 text-[9.5px] leading-relaxed text-faint">
        <div>Hiệu lực: {dateLabel(claim?.effective_from ?? snapshot.effective_from)}</div>
        <div>Nguồn: {claim?.source_publisher || snapshot.source_publisher || snapshot.source_type}</div>
        {(claim?.authority_level ?? snapshot.authority_level) !== null && (
          <div>Độ ưu tiên nguồn: {claim?.authority_level ?? snapshot.authority_level}</div>
        )}
      </div>
    </section>
  );
}

function RelationEvidence({ state, documentsById, onRetry }) {
  if (state?.loading) {
    return (
      <div className="mt-2 flex items-center gap-2 rounded-lg bg-inset p-3 text-[10.5px] text-faint">
        <Icon icon="lucide:loader-circle" width={13} className="animate-spin" />
        Đang tải bằng chứng hai phía…
      </div>
    );
  }
  if (state?.error) {
    return (
      <div className="mt-2 rounded-lg border border-red/30 bg-red/5 p-2.5 text-[10px] text-red">
        <div>{state.error}</div>
        <button type="button" onClick={onRetry} className="mt-1 font-semibold underline">
          Thử lại
        </button>
      </div>
    );
  }
  if (!state?.data) return null;

  const evidence = state.data;
  return (
    <div className="mt-2 space-y-2">
      <EvidenceSide
        label="Phía nguồn"
        snapshot={evidence.source_snapshot}
        claim={evidence.source_claim}
        documentsById={documentsById}
        tone="border-accent/30 bg-accent/5"
      />
      <EvidenceSide
        label="Phía đối chiếu"
        snapshot={evidence.target_snapshot}
        claim={evidence.target_claim}
        documentsById={documentsById}
        tone="border-yellow/30 bg-yellow/5"
      />
    </div>
  );
}

function ErrorBanner({ message, onRetry }) {
  if (!message) return null;
  return (
    <div className="mb-2 rounded-lg border border-red/30 bg-red/5 p-2.5 text-[10.5px] text-red">
      <div>{message}</div>
      <button type="button" onClick={onRetry} className="mt-1 font-semibold underline">
        Làm mới hàng đợi
      </button>
    </div>
  );
}

function DecisionForm({ action, reason, error, busy, onReasonChange, onCancel, onSubmit }) {
  return (
    <form onSubmit={onSubmit} className="mt-2 rounded-lg border border-accent/30 bg-accent/5 p-2.5">
      <label className="block text-[10.5px] font-medium text-foreground">
        Lý do {action === 'dismiss' ? 'bỏ qua' : 'xác nhận'}
      </label>
      <textarea
        autoFocus
        value={reason}
        onChange={(event) => onReasonChange(event.target.value)}
        rows={3}
        maxLength={2000}
        placeholder="Ghi rõ căn cứ đối chiếu…"
        className="mt-1.5 w-full resize-y rounded-md border border-border bg-background p-2 text-[11px] text-foreground outline-none focus:border-accent"
      />
      {error && <div className="mt-1 text-[10px] text-red">{error}</div>}
      <div className="mt-2 flex justify-end gap-1.5">
        <button
          type="button"
          disabled={busy}
          onClick={onCancel}
          className="rounded-md px-2 py-1 text-[10.5px] text-dim hover:bg-inset disabled:opacity-50"
        >
          Hủy
        </button>
        <button
          type="submit"
          disabled={busy || !reason.trim()}
          className="rounded-md bg-accent px-2.5 py-1 text-[10.5px] font-semibold text-accent-foreground disabled:opacity-50"
        >
          {busy ? 'Đang lưu…' : 'Lưu quyết định'}
        </button>
      </div>
    </form>
  );
}

export default function StructuredFactReviewPanel({ notebookId, documents, showToast }) {
  const {
    pendingRelations,
    pendingTotalCount,
    pendingLoaded,
    pendingLoading,
    pendingLoadingMore,
    pendingError,
    relationEvidence,
    resolvingId,
    resetForNotebook,
    fetchPending,
    fetchEvidence,
    resolveRelation,
  } = useStructuredFactStore();
  const [expandedId, setExpandedId] = useState(null);
  const [draft, setDraft] = useState(null);
  const [reason, setReason] = useState('');
  const [draftError, setDraftError] = useState('');

  const documentsById = useMemo(
    () => new Map((documents || []).map((document) => [document.id, document])),
    [documents],
  );

  useEffect(() => {
    resetForNotebook(notebookId);
    if (notebookId) {
      fetchPending(notebookId).catch(() => {});
    }
  }, [notebookId, resetForNotebook, fetchPending]);

  const toggleEvidence = (relationId) => {
    if (expandedId === relationId) {
      setExpandedId(null);
      return;
    }
    setExpandedId(relationId);
    fetchEvidence(notebookId, relationId).catch((error) => {
      showToast?.(error.message || 'Không thể tải bằng chứng.', 'error');
    });
  };

  const beginDecision = (relationId, action) => {
    setDraft({ relationId, action });
    setReason('');
    setDraftError('');
  };

  const submitDecision = async (event, relation) => {
    event.preventDefault();
    if (!draft || draft.relationId !== relation.id) return;
    try {
      await resolveRelation(
        notebookId,
        relation.id,
        draft.action === 'dismiss'
          ? 'dismiss'
          : confirmActionForRelation(relation.relation_type),
        reason,
      );
      setDraft(null);
      setReason('');
      setExpandedId((current) => (current === relation.id ? null : current));
      showToast?.(
        draft.action === 'dismiss'
          ? 'Đã bỏ qua quan hệ số liệu.'
          : 'Đã xác nhận quan hệ số liệu.',
        'success',
      );
    } catch (error) {
      setDraftError(error.message || 'Không thể lưu quyết định.');
      showToast?.(error.message || 'Không thể lưu quyết định.', 'error');
    }
  };

  return (
    <div>
      <div className="mb-2 flex items-start justify-between gap-2 px-1">
        <div>
          <div className="text-[12px] font-semibold text-foreground">Quan hệ số liệu cần duyệt</div>
          <div className="mt-0.5 text-[10px] leading-relaxed text-faint">
            Đối chiếu claim theo phạm vi, điều kiện và thời gian hiệu lực.
          </div>
        </div>
        <button
          type="button"
          title="Làm mới"
          disabled={pendingLoading}
          onClick={() => fetchPending(notebookId).catch(() => {})}
          className="flex h-7 w-7 shrink-0 items-center justify-center rounded-md text-faint hover:bg-inset hover:text-foreground disabled:opacity-50"
        >
          <Icon icon="lucide:refresh-cw" width={13} className={pendingLoading ? 'animate-spin' : ''} />
        </button>
      </div>

      <ErrorBanner
        message={pendingError}
        onRetry={() => fetchPending(notebookId).catch(() => {})}
      />

      {pendingLoading && pendingRelations.length === 0 ? (
        <div className="flex items-center justify-center gap-2 py-8 text-[11px] text-faint">
          <Icon icon="lucide:loader-circle" width={14} className="animate-spin" />
          Đang tải quan hệ số liệu…
        </div>
      ) : pendingLoaded && pendingRelations.length === 0 ? (
        <div className="rounded-lg border border-dashed border-border px-3 py-8 text-center">
          <Icon icon="lucide:badge-check" width={20} className="mx-auto mb-2 text-green" />
          <div className="text-[11.5px] font-medium text-foreground">Không còn số liệu chờ duyệt</div>
          <div className="mt-1 text-[10px] text-faint">Các quan hệ chắc chắn đã được xử lý tự động.</div>
        </div>
      ) : (
        <>
          <div className="mb-1 px-1 text-[10px] text-faint">
            Hiển thị {pendingRelations.length}/{pendingTotalCount} quan hệ
          </div>
          {pendingRelations.map((relation) => {
            const expanded = expandedId === relation.id;
            const busy = resolvingId === relation.id;
            const decisionOpen = draft?.relationId === relation.id;
            const conflict = isStructuredConflict(relation.relation_type);
            return (
              <section key={relation.id} className="border-b border-border px-1 py-3 last:border-b-0">
                <div className="flex items-start justify-between gap-2">
                  <span className={`text-[11px] font-semibold ${conflict ? 'text-red' : 'text-accent'}`}>
                    {STRUCTURED_RELATION_LABELS[relation.relation_type] || relation.relation_type}
                  </span>
                  <span className="text-[10px] tabular-nums text-faint">
                    {confidenceLabel(relation.confidence)}
                  </span>
                </div>
                <div className="mt-1.5 grid grid-cols-2 gap-1 text-[9.5px] text-faint">
                  <span className="truncate">Scope: {relation.scope_relation}</span>
                  <span className="truncate">Điều kiện: {relation.qualifier_compatibility}</span>
                  <span className="truncate">Thời gian: {relation.temporal_compatibility}</span>
                  <span className="truncate">Bộ dò: {relation.detector_version}</span>
                </div>
                {relation.reason && (
                  <div className="mt-1.5 text-[10px] leading-relaxed text-dim">
                    {relation.reason}
                  </div>
                )}
                <JsonDetails label="Tín hiệu so sánh" value={relation.evidence} />

                <button
                  type="button"
                  aria-expanded={expanded}
                  onClick={() => toggleEvidence(relation.id)}
                  className="mt-2 flex items-center gap-1 text-[10.5px] font-medium text-accent hover:underline"
                >
                  <Icon icon={expanded ? 'lucide:chevron-up' : 'lucide:chevron-down'} width={11} />
                  {expanded ? 'Ẩn bằng chứng hai phía' : 'Xem bằng chứng hai phía'}
                </button>
                {expanded && (
                  <RelationEvidence
                    state={relationEvidence[relation.id]}
                    documentsById={documentsById}
                    onRetry={() => fetchEvidence(
                      notebookId,
                      relation.id,
                      { force: true },
                    ).catch(() => {})}
                  />
                )}

                <div className="mt-2.5 flex gap-1.5">
                  <button
                    type="button"
                    disabled={busy}
                    onClick={() => beginDecision(relation.id, 'confirm')}
                    className="flex items-center gap-1 rounded-md bg-accent/10 px-2 py-1 text-[10.5px] font-medium text-accent hover:bg-accent/20 disabled:opacity-50"
                  >
                    <Icon icon="lucide:check" width={11} />
                    Xác nhận
                  </button>
                  <button
                    type="button"
                    disabled={busy}
                    onClick={() => beginDecision(relation.id, 'dismiss')}
                    className="flex items-center gap-1 rounded-md bg-red/5 px-2 py-1 text-[10.5px] font-medium text-red hover:bg-red/10 disabled:opacity-50"
                  >
                    <Icon icon="lucide:x" width={11} />
                    Bỏ qua
                  </button>
                </div>

                {decisionOpen && (
                  <DecisionForm
                    action={draft.action}
                    reason={reason}
                    error={draftError}
                    busy={busy}
                    onReasonChange={(value) => {
                      setReason(value);
                      setDraftError('');
                    }}
                    onCancel={() => {
                      setDraft(null);
                      setReason('');
                      setDraftError('');
                    }}
                    onSubmit={(event) => submitDecision(event, relation)}
                  />
                )}
              </section>
            );
          })}
          {pendingRelations.length < pendingTotalCount && (
            <button
              type="button"
              disabled={pendingLoadingMore}
              onClick={() => fetchPending(notebookId, { append: true }).catch(() => {})}
              className="mt-3 w-full rounded-lg border border-border py-2 text-[10.5px] font-medium text-dim hover:bg-inset disabled:opacity-50"
            >
              {pendingLoadingMore ? 'Đang tải…' : 'Tải thêm quan hệ'}
            </button>
          )}
        </>
      )}
    </div>
  );
}
