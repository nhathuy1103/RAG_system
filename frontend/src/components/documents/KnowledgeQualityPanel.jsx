import React, { useEffect, useMemo, useState } from 'react';
import { Icon } from '@iconify/react';
import {
  ACTION_LABELS,
  BOOLEAN_SIGNAL_LABELS,
  RELATION_LABELS,
  SCORE_SIGNAL_LABELS,
  STATUS_LABELS,
  canRevertAuditEvent,
  confidenceLabel,
  formatQualityTimestamp,
  isRecord,
  reasonCodeLabel,
  relationSnapshotFromAudit,
  relationSnapshotFromState,
} from '../../lib/quality.js';
import { useQualityStore } from '../../stores/qualityStore.js';

const DECISION_TITLES = {
  confirm_duplicate: 'Xác nhận hai tài liệu là bản trùng',
  mark_version: 'Xác nhận tài liệu mới là một phiên bản',
  confirm_conflict: 'Xác nhận hai tài liệu có nội dung mâu thuẫn',
  keep_separate: 'Giữ hai tài liệu độc lập',
  prefer_source: 'Ưu tiên tài liệu mới khi trả lời',
  prefer_target: 'Ưu tiên tài liệu cũ khi trả lời',
  dismiss: 'Bỏ qua đề xuất này',
};

const MODALITY_LABELS = {
  required: 'Bắt buộc',
  permitted: 'Được phép',
  prohibited: 'Bị cấm',
};

const EVIDENCE_TYPE_LABELS = {
  exact_content: 'Trùng chính xác',
  near_duplicate: 'Gần giống',
  version_candidate: 'Có thể là nội dung thêm/sửa',
  conflict_candidate: 'Có thể mâu thuẫn',
  template_variant: 'Cùng mẫu, khác phạm vi',
  temporal_series: 'Cùng chủ đề, khác thời kỳ',
  source_only: 'Chỉ có trong tài liệu mới',
  target_only: 'Chỉ có trong tài liệu cũ',
  distinct: 'Khác nội dung',
};

function documentName(documentsById, documentId) {
  return (
    documentsById.get(documentId)?.original_filename
    || 'Tài liệu không còn khả dụng'
  );
}

function signalSummary(signals) {
  const parts = [];
  if (typeof signals.lexical_similarity === 'number') {
    parts.push(`Từ ngữ ${confidenceLabel(signals.lexical_similarity)}`);
  }
  if (typeof signals.semantic_similarity === 'number') {
    parts.push(`Ngữ nghĩa ${confidenceLabel(signals.semantic_similarity)}`);
  }
  if (typeof signals.document_probe_coverage === 'number') {
    parts.push(`Độ phủ ${confidenceLabel(signals.document_probe_coverage)}`);
  }
  const reasons = Array.isArray(signals.reason_codes)
    ? signals.reason_codes
    : [];
  parts.push(...reasons.slice(0, 2).map(reasonCodeLabel));
  return parts.slice(0, 4).join(' · ');
}

function ReviewAction({
  icon,
  label,
  title,
  disabled,
  onClick,
  tone = 'default',
}) {
  const toneClass = tone === 'warning'
    ? 'border-yellow/40 text-yellow hover:bg-yellow/10'
    : tone === 'danger'
      ? 'border-red/40 text-red hover:bg-red/10'
      : 'border-border text-dim hover:bg-inset hover:text-foreground';
  return (
    <button
      type="button"
      title={title || label}
      disabled={disabled}
      onClick={onClick}
      className={`flex h-7 items-center gap-1 rounded border px-2 text-[11px] font-medium transition-colors disabled:cursor-not-allowed disabled:opacity-50 ${toneClass}`}
    >
      <Icon icon={icon} width={12} height={12} />
      {label}
    </button>
  );
}

function ErrorBanner({ message, onRetry }) {
  if (!message) return null;
  return (
    <div className="mb-2 rounded-lg border border-red/30 bg-red/5 px-2.5 py-2 text-[11px] text-red">
      <div>{message}</div>
      {onRetry && (
        <button
          type="button"
          onClick={onRetry}
          className="mt-1 font-semibold underline underline-offset-2"
        >
          Thử lại
        </button>
      )}
    </div>
  );
}

function ReasonForm({
  title,
  submitLabel,
  reason,
  error,
  busy,
  onReasonChange,
  onCancel,
  onSubmit,
}) {
  return (
    <form
      className="mt-2.5 rounded-lg border border-accent/30 bg-accent/5 p-2.5"
      onSubmit={onSubmit}
    >
      <label className="block text-[11.5px] font-semibold text-foreground">
        {title}
        <span className="ml-1 text-red">*</span>
      </label>
      <textarea
        autoFocus
        required
        maxLength={2000}
        rows={3}
        value={reason}
        disabled={busy}
        onChange={(event) => onReasonChange(event.target.value)}
        placeholder="Nêu căn cứ để người khác có thể kiểm tra quyết định này…"
        className="mt-1.5 w-full resize-y rounded-md border border-border bg-background px-2 py-1.5 text-[11.5px] text-foreground outline-none placeholder:text-faint focus:border-accent disabled:opacity-60"
      />
      <div className="mt-1 flex items-start justify-between gap-2">
        <span className="text-[10px] text-red">{error || 'Lý do sẽ được lưu vào audit log.'}</span>
        <span className="shrink-0 text-[10px] tabular-nums text-faint">
          {reason.length}/2000
        </span>
      </div>
      <div className="mt-2 flex justify-end gap-1.5">
        <button
          type="button"
          disabled={busy}
          onClick={onCancel}
          className="h-7 rounded border border-border px-2.5 text-[11px] text-dim hover:bg-inset disabled:opacity-50"
        >
          Hủy
        </button>
        <button
          type="submit"
          disabled={busy || !reason.trim()}
          className="flex h-7 items-center gap-1 rounded bg-accent px-2.5 text-[11px] font-semibold text-accent-foreground hover:bg-accent-dim disabled:cursor-not-allowed disabled:opacity-50"
        >
          {busy && (
            <Icon
              icon="lucide:loader-circle"
              className="animate-spin"
              width={12}
            />
          )}
          {submitLabel}
        </button>
      </div>
    </form>
  );
}

function ClaimValueList({ values }) {
  if (!Array.isArray(values) || values.length === 0) return null;
  return (
    <div className="mt-1 space-y-0.5">
      {values.map((value, index) => {
        if (!isRecord(value)) return null;
        const normalized = [
          value.normalized_value,
          value.magnitude,
          value.unit,
        ].filter(Boolean).join(' ');
        return (
          <div
            key={`${value.kind || 'value'}-${index}`}
            className="text-[10px] text-faint"
          >
            <span className="text-dim">{String(value.raw_text || value.kind || 'Giá trị')}</span>
            {normalized && <span> → {normalized}</span>}
          </div>
        );
      })}
    </div>
  );
}

function ClaimSide({ title, claim }) {
  if (!isRecord(claim)) return null;
  return (
    <div className="rounded-md border border-border bg-background/60 p-2">
      <div className="mb-1 text-[10px] font-semibold uppercase tracking-wide text-faint">
        {title}
      </div>
      <div className="text-[11px] leading-relaxed text-foreground">
        {String(claim.text || 'Không có đoạn trích')}
      </div>
      <div className="mt-1 flex flex-wrap gap-1">
        {claim.modality && (
          <span className="rounded bg-inset px-1.5 py-0.5 text-[9.5px] text-dim">
            {MODALITY_LABELS[claim.modality] || claim.modality}
          </span>
        )}
        {claim.negated === true && (
          <span className="rounded bg-red/10 px-1.5 py-0.5 text-[9.5px] text-red">
            Có phủ định
          </span>
        )}
        {claim.alignment_key && (
          <span className="max-w-full truncate rounded bg-inset px-1.5 py-0.5 text-[9.5px] text-faint">
            Khóa: {String(claim.alignment_key)}
          </span>
        )}
      </div>
      <ClaimValueList values={claim.values} />
    </div>
  );
}

function evidenceTone(evidenceType) {
  if (String(evidenceType).includes('conflict')) return 'conflict';
  if (evidenceType === 'near_duplicate' || evidenceType === 'version_candidate') {
    return 'near';
  }
  if (evidenceType === 'source_only') return 'added';
  if (evidenceType === 'target_only') return 'removed';
  if (evidenceType === 'exact_content') return 'exact';
  return 'neutral';
}

function evidenceToneClasses(tone) {
  return {
    conflict: 'border-red/40 bg-red/10 text-red',
    near: 'border-yellow/40 bg-yellow/10 text-yellow',
    added: 'border-green/40 bg-green/10 text-green',
    removed: 'border-red/30 bg-red/5 text-red',
    exact: 'border-border bg-background text-dim',
    neutral: 'border-border bg-background text-dim',
  }[tone] || 'border-border bg-background text-dim';
}

function chunkTitle(chunk, fallback) {
  if (!chunk) return fallback;
  const parts = [`chunk ${chunk.chunk_index}`];
  if (chunk.page_number) parts.unshift(`trang ${chunk.page_number}`);
  return parts.join(', ');
}

function splitDiffLines(text) {
  return String(text || '')
    .split(/\n+/)
    .map((line) => line.trim())
    .filter(Boolean);
}

function buildLineDiff(sourceText, targetText) {
  const sourceLines = splitDiffLines(sourceText);
  const targetLines = splitDiffLines(targetText);
  const dp = Array.from(
    { length: sourceLines.length + 1 },
    () => Array(targetLines.length + 1).fill(0),
  );
  for (let i = sourceLines.length - 1; i >= 0; i -= 1) {
    for (let j = targetLines.length - 1; j >= 0; j -= 1) {
      dp[i][j] = sourceLines[i] === targetLines[j]
        ? dp[i + 1][j + 1] + 1
        : Math.max(dp[i + 1][j], dp[i][j + 1]);
    }
  }

  const rows = [];
  let i = 0;
  let j = 0;
  while (i < sourceLines.length || j < targetLines.length) {
    if (
      i < sourceLines.length
      && j < targetLines.length
      && sourceLines[i] === targetLines[j]
    ) {
      rows.push({ kind: 'same', source: sourceLines[i], target: targetLines[j] });
      i += 1;
      j += 1;
    } else if (j >= targetLines.length || (i < sourceLines.length && dp[i + 1][j] >= dp[i][j + 1])) {
      rows.push({ kind: 'source_added', source: sourceLines[i], target: '' });
      i += 1;
    } else {
      rows.push({ kind: 'target_removed', source: '', target: targetLines[j] });
      j += 1;
    }
  }
  return rows;
}

function DiffLine({
  row,
  tone,
  side,
  pairIndex,
  rowIndex,
  selectedId,
  onSelect,
}) {
  const text = side === 'source' ? row.source : row.target;
  if (!text) return <div className="min-h-5" />;
  const isSelected = selectedId === `${pairIndex}:${rowIndex}:${side}`;
  const changed = row.kind !== 'same';
  const toneClass = changed
    ? evidenceToneClasses(tone === 'exact' ? 'near' : tone)
    : 'border-transparent bg-transparent text-foreground';
  return (
    <button
      type="button"
      onClick={() => onSelect(`${pairIndex}:${rowIndex}:${side}`, text)}
      className={`block w-full rounded border px-2 py-1 text-left text-[10.5px] leading-relaxed transition-colors ${
        changed ? toneClass : 'hover:bg-inset text-dim'
      } ${isSelected ? 'ring-2 ring-accent/30' : ''}`}
    >
      {text}
    </button>
  );
}

function EvidencePairCard({
  pair,
  index,
  selectedId,
  onSelect,
}) {
  const tone = evidenceTone(pair.evidence_type);
  const diffRows = buildLineDiff(
    pair.source_chunk?.content || '',
    pair.target_chunk?.content || '',
  );
  const pairLabel = EVIDENCE_TYPE_LABELS[pair.evidence_type] || pair.evidence_type;
  const scoreRows = Object.entries(SCORE_SIGNAL_LABELS)
    .filter(([key]) => typeof pair.signals?.[key] === 'number')
    .slice(0, 3);
  return (
    <div className={`rounded-lg border p-2 ${evidenceToneClasses(tone)}`}>
      <div className="mb-1.5 flex items-start justify-between gap-2">
        <div>
          <div className="text-[10.5px] font-semibold uppercase">{pairLabel}</div>
          <div className="mt-0.5 text-[9.5px] opacity-80">
            {chunkTitle(pair.source_chunk, 'không có ở tài liệu mới')}
            {' ↔ '}
            {chunkTitle(pair.target_chunk, 'không có ở tài liệu cũ')}
          </div>
        </div>
        <span className="shrink-0 text-[10px] tabular-nums">
          {confidenceLabel(pair.confidence)}
        </span>
      </div>

      {scoreRows.length > 0 && (
        <div className="mb-1.5 flex flex-wrap gap-1">
          {scoreRows.map(([key, label]) => (
            <span
              key={key}
              className="rounded bg-background/70 px-1.5 py-0.5 text-[9px] text-faint"
            >
              {label}: {confidenceLabel(pair.signals[key])}
            </span>
          ))}
        </div>
      )}

      <div className="grid grid-cols-1 gap-1.5">
        <div className="rounded-md border border-border/80 bg-background/70 p-1.5">
          <div className="mb-1 text-[9.5px] font-semibold uppercase text-faint">
            Tài liệu mới
          </div>
          <div className="space-y-1">
            {diffRows.map((row, rowIndex) => (
              <DiffLine
                key={`source-${rowIndex}-${row.source}`}
                row={row}
                tone={tone}
                side="source"
                pairIndex={index}
                rowIndex={rowIndex}
                selectedId={selectedId}
                onSelect={onSelect}
              />
            ))}
          </div>
        </div>
        <div className="rounded-md border border-border/80 bg-background/70 p-1.5">
          <div className="mb-1 text-[9.5px] font-semibold uppercase text-faint">
            Tài liệu cũ
          </div>
          <div className="space-y-1">
            {diffRows.map((row, rowIndex) => (
              <DiffLine
                key={`target-${rowIndex}-${row.target}`}
                row={row}
                tone={tone}
                side="target"
                pairIndex={index}
                rowIndex={rowIndex}
                selectedId={selectedId}
                onSelect={onSelect}
              />
            ))}
          </div>
        </div>
      </div>
    </div>
  );
}

function reviewLineTone(pair, row) {
  const tone = evidenceTone(pair.evidence_type);
  if (pair.evidence_type === 'source_only') return 'added';
  if (pair.evidence_type === 'target_only') return 'removed';
  if (row.kind === 'same') return 'neutral';
  if (tone === 'conflict') return 'conflict';
  if (tone === 'near') return 'near';
  return tone;
}

function ReviewBlock({
  block,
  selectedId,
  onSelect,
}) {
  const tone = block.highlight_type ? evidenceTone(block.highlight_type) : 'neutral';
  const label = block.highlight_type
    ? EVIDENCE_TYPE_LABELS[block.highlight_type] || block.highlight_type
    : null;
  const selected = selectedId === block.id;
  const highlighted = Boolean(block.highlight_type);
  const toneClass = highlighted
    ? evidenceToneClasses(tone)
    : 'border-border bg-panel text-foreground';
  const cellCount = Array.isArray(block.cells) ? block.cells.length : 0;
  const gridTemplateColumns = cellCount > 0
    ? `repeat(${Math.min(cellCount, 6)}, minmax(0, 1fr))`
    : undefined;

  return (
    <button
      type="button"
      onClick={() => onSelect(block.id, {
        text: block.text,
        block,
        evidenceType: block.highlight_type,
      })}
      className={`block w-full rounded-md border p-2 text-left shadow-sm transition-colors ${
        toneClass
      } ${selected ? 'ring-2 ring-accent/30' : ''}`}
    >
      <div className="mb-1.5 flex items-center justify-between gap-2 text-[10px]">
        <span className="font-semibold uppercase text-faint">
          {block.page_number ? `trang ${block.page_number}, ` : ''}
          {block.block_type === 'table_row' ? 'dòng bảng' : block.block_type}
          {' '}
          {block.block_index + 1}
        </span>
        {label && (
          <span className={`shrink-0 rounded-full border px-1.5 py-0.5 ${
            evidenceToneClasses(tone)
          }`}>
            {label}
          </span>
        )}
      </div>
      {cellCount > 0 ? (
        <div
          className="grid overflow-hidden rounded border border-border/80 bg-border/80 text-[12px] leading-relaxed"
          style={{ gridTemplateColumns }}
        >
          {block.cells.map((cell, cellIndex) => (
            <div
              key={`${block.id}-cell-${cellIndex}`}
              className="min-w-0 break-words bg-background/80 px-2 py-1.5 text-foreground"
            >
              {cell || '\u00a0'}
            </div>
          ))}
        </div>
      ) : (
        <div className="break-words text-[12px] leading-relaxed">
          {block.text}
        </div>
      )}
    </button>
  );
}

function DocumentReviewPane({
  title,
  document,
  pairs,
  blocks,
  side,
  selectedId,
  onSelect,
}) {
  const originalBlocks = Array.isArray(blocks) ? blocks : [];
  const hasOriginalBlocks = originalBlocks.length > 0;
  const renderedPairs = pairs
    .map((pair, pairIndex) => ({ pair, pairIndex }))
    .filter(({ pair }) => (
      side === 'source' ? pair.source_chunk : pair.target_chunk
    ));
  return (
    <section className="flex min-h-0 flex-1 flex-col rounded-lg border border-border bg-panel">
      <div className="shrink-0 border-b border-border px-3 py-2">
        <div className="text-[10px] font-semibold uppercase tracking-wide text-faint">
          {title}
        </div>
        <div className="mt-0.5 truncate text-[13px] font-semibold text-foreground">
          {document?.original_filename || 'Tài liệu không còn khả dụng'}
        </div>
        {document && (
          <div className="mt-0.5 text-[10px] text-faint">
            v{document.version_number || 1}
            {document.quality_status ? ` · ${document.quality_status}` : ''}
          </div>
        )}
      </div>
      <div className="min-h-0 flex-1 overflow-auto bg-background p-3">
        <div className="mx-auto max-w-[720px] space-y-3">
          {hasOriginalBlocks ? originalBlocks.map((block) => (
            <ReviewBlock
              key={block.id}
              block={block}
              selectedId={selectedId}
              onSelect={onSelect}
            />
          )) : renderedPairs.map(({ pair, pairIndex }) => {
            const chunk = side === 'source' ? pair.source_chunk : pair.target_chunk;
            const diffRows = buildLineDiff(
              pair.source_chunk?.content || '',
              pair.target_chunk?.content || '',
            ).filter((row) => (side === 'source' ? row.source : row.target));
            return (
              <article
                key={`${side}-${chunk.id}-${pair.evidence_type}`}
                className="rounded-md border border-border bg-panel p-2 shadow-sm"
              >
                <div className="mb-1.5 flex items-center justify-between gap-2 text-[10px]">
                  <span className="font-semibold uppercase text-faint">
                    {chunkTitle(chunk, 'chunk')}
                  </span>
                  <span
                    className={`rounded-full border px-1.5 py-0.5 ${
                      evidenceToneClasses(evidenceTone(pair.evidence_type))
                    }`}
                  >
                    {EVIDENCE_TYPE_LABELS[pair.evidence_type] || pair.evidence_type}
                  </span>
                </div>
                <div className="space-y-1">
                  {diffRows.map((row, rowIndex) => {
                    const lineText = side === 'source' ? row.source : row.target;
                    const lineTone = reviewLineTone(pair, row);
                    const id = `${pairIndex}:${rowIndex}:${side}`;
                    const selected = selectedId === id;
                    const highlightClass = lineTone === 'neutral'
                      ? 'border-transparent bg-transparent text-foreground hover:bg-inset'
                      : evidenceToneClasses(lineTone);
                    return (
                      <button
                        key={`${id}-${lineText}`}
                        type="button"
                        onClick={() => onSelect(id, {
                          text: lineText,
                          chunk,
                          evidenceType: pair.evidence_type,
                        })}
                        className={`block w-full rounded border px-2 py-1.5 text-left text-[12px] leading-relaxed transition-colors ${
                          highlightClass
                        } ${selected ? 'ring-2 ring-accent/30' : ''}`}
                      >
                        {lineText}
                      </button>
                    );
                  })}
                </div>
              </article>
            );
          })}
        </div>
      </div>
    </section>
  );
}

function TwoFileReviewModal({
  evidence,
  pairs,
  selectedEvidence,
  onSelect,
  onClose,
}) {
  return (
    <div className="fixed inset-0 z-[1000] flex items-center justify-center bg-black/45 p-4">
      <div className="flex h-[min(860px,92vh)] w-[min(1280px,96vw)] flex-col overflow-hidden rounded-xl border border-border bg-background shadow-xl">
        <div className="flex shrink-0 items-start justify-between gap-4 border-b border-border bg-panel px-4 py-3">
          <div>
            <div className="text-[10px] font-semibold uppercase tracking-wide text-faint">
              Duyệt quan hệ tài liệu
            </div>
            <div className="mt-1 text-sm font-semibold text-foreground">
              Hai file gốc và vùng nội dung liên quan
            </div>
          </div>
          <button
            type="button"
            onClick={onClose}
            className="flex h-8 items-center gap-1.5 rounded-lg bg-accent px-3 text-xs font-semibold text-accent-foreground hover:bg-accent-dim"
          >
            <Icon icon="lucide:x" width={14} />
            Đóng
          </button>
        </div>

        <div className="flex shrink-0 flex-wrap gap-1.5 border-b border-border bg-inset px-4 py-2">
          <span className="rounded-full border border-red/40 bg-red/10 px-2 py-0.5 text-[10px] text-red">
            Đỏ: conflict
          </span>
          <span className="rounded-full border border-yellow/40 bg-yellow/10 px-2 py-0.5 text-[10px] text-yellow">
            Vàng: near duplicate
          </span>
          <span className="rounded-full border border-green/40 bg-green/10 px-2 py-0.5 text-[10px] text-green">
            Xanh: nội dung thêm ở file mới
          </span>
          <span className="rounded-full border border-border bg-background px-2 py-0.5 text-[10px] text-faint">
            Trắng/xám: trùng hoặc không đổi
          </span>
        </div>

        <div className="grid min-h-0 flex-1 grid-cols-1 gap-3 p-3 lg:grid-cols-2">
          <DocumentReviewPane
            title="File mới"
            document={evidence.source_document}
            pairs={pairs}
            blocks={evidence.source_original_blocks}
            side="source"
            selectedId={selectedEvidence?.id}
            onSelect={onSelect}
          />
          <DocumentReviewPane
            title="File cũ"
            document={evidence.target_document}
            pairs={pairs}
            blocks={evidence.target_original_blocks}
            side="target"
            selectedId={selectedEvidence?.id}
            onSelect={onSelect}
          />
        </div>

        <div className="shrink-0 border-t border-border bg-panel px-4 py-2">
          {selectedEvidence ? (
            <div className="text-[11px] text-dim">
              <span className="font-semibold text-accent">Đoạn đang chọn:</span>
              {' '}
              {selectedEvidence.text}
            </div>
          ) : (
            <div className="text-[11px] text-faint">
              Bấm vào một dòng được tô màu để chọn bằng chứng trước khi quyết định.
            </div>
          )}
        </div>
      </div>
    </div>
  );
}

function EvidenceComparison({
  evidenceState,
  relation,
  onRetry,
}) {
  const [selectedEvidence, setSelectedEvidence] = useState(null);
  const [compareOpen, setCompareOpen] = useState(false);
  if (evidenceState?.loading) {
    return (
      <div className="mt-2.5 flex items-center gap-1.5 rounded-lg border border-border bg-inset/50 p-2.5 text-[10.5px] text-faint">
        <Icon icon="lucide:loader-circle" className="animate-spin" width={12} />
        Đang tải bản so sánh nội dung
      </div>
    );
  }
  if (evidenceState?.error) {
    return (
      <div className="mt-2.5 rounded-lg border border-red/30 bg-red/5 p-2.5 text-[10.5px] text-red">
        <div>{evidenceState.error}</div>
        <button
          type="button"
          onClick={onRetry}
          className="mt-1 font-semibold underline underline-offset-2"
        >
          Thử lại
        </button>
      </div>
    );
  }
  const evidence = evidenceState?.data;
  if (!evidence || !Array.isArray(evidence.chunk_pairs)) return null;
  const pairs = evidence.chunk_pairs;
  const counts = pairs.reduce((acc, pair) => {
    const key = pair.evidence_type || 'unknown';
    acc[key] = (acc[key] || 0) + 1;
    return acc;
  }, {});
  const conflictPairs = pairs.filter((pair) => evidenceTone(pair.evidence_type) === 'conflict');
  const nearPairs = pairs.filter((pair) => evidenceTone(pair.evidence_type) === 'near');
  const addedPairs = pairs.filter((pair) => evidenceTone(pair.evidence_type) === 'added');
  const exactPairs = pairs.filter((pair) => pair.evidence_type === 'exact_content');

  return (
    <div className="mt-2.5 space-y-2 rounded-lg border border-border bg-inset/50 p-2.5">
      {compareOpen && (
        <TwoFileReviewModal
          evidence={evidence}
          pairs={pairs}
          selectedEvidence={selectedEvidence}
          onSelect={(id, selection) => setSelectedEvidence({ id, ...selection })}
          onClose={() => setCompareOpen(false)}
        />
      )}
      <div className="flex items-start justify-between gap-2">
        <div>
          <div className="text-[10px] font-semibold uppercase tracking-wide text-faint">
            Hai file cần duyệt
          </div>
          <div className="mt-0.5 text-[10.5px] text-dim">
            {evidence.source_document?.original_filename || documentName(new Map(), relation.source_document_id)}
            {' ↔ '}
            {evidence.target_document?.original_filename || documentName(new Map(), relation.target_document_id)}
          </div>
        </div>
        <span className="shrink-0 rounded bg-background px-1.5 py-0.5 text-[9.5px] text-faint">
          {pairs.length} cặp
        </span>
      </div>

      <div className="flex flex-wrap gap-1">
        {Object.entries(counts).map(([key, value]) => (
          <span
            key={key}
            className={`rounded-full border px-1.5 py-0.5 text-[9.5px] ${
              evidenceToneClasses(evidenceTone(key))
            }`}
          >
            {EVIDENCE_TYPE_LABELS[key] || key}: {value}
          </span>
        ))}
      </div>

      {selectedEvidence && (
        <div className="rounded-md border border-accent/30 bg-accent/5 p-2 text-[10.5px] text-dim">
          <div className="font-semibold text-accent">Đã chọn đoạn bằng chứng</div>
          <div className="mt-0.5 line-clamp-3">{selectedEvidence.text}</div>
        </div>
      )}

      <button
        type="button"
        onClick={() => setCompareOpen(true)}
        className="flex h-8 w-full items-center justify-center gap-1.5 rounded-lg bg-accent text-[11px] font-semibold text-accent-foreground hover:bg-accent-dim"
      >
        <Icon icon="lucide:scan-text" width={13} />
        Mở 2 file gốc để kiểm tra highlight
      </button>

      <div className="rounded-md border border-border bg-background/70 p-2 text-[10px] leading-relaxed text-faint">
        Khi mở, file mới nằm bên trái và file cũ nằm bên phải. Dòng đỏ là conflict,
        dòng vàng là near duplicate, dòng xanh là phần chỉ có trong file mới.
      </div>

      {exactPairs.length > 0 && addedPairs.length > 0 && (
        <div className="rounded-md border border-yellow/30 bg-yellow/5 p-2 text-[10px] text-yellow">
          Tài liệu có nhiều chunk trùng chính xác và một số phần chỉ có ở tài liệu mới; kiểm tra các dòng màu xanh trước khi chọn “Phiên bản” hoặc “Trùng”.
        </div>
      )}
    </div>
  );
}

function EvidenceDetails({ relation }) {
  const signals = isRecord(relation?.signals) ? relation.signals : {};
  const reasonCodes = Array.isArray(signals.reason_codes)
    ? signals.reason_codes
    : [];
  const claimConflicts = Array.isArray(signals.claim_conflicts)
    ? signals.claim_conflicts.filter(isRecord)
    : [];
  const selectedPair = isRecord(signals.selected_chunk_pair)
    ? signals.selected_chunk_pair
    : null;
  const pairCounts = isRecord(signals.relation_pair_counts)
    ? signals.relation_pair_counts
    : null;
  const scoreRows = Object.entries(SCORE_SIGNAL_LABELS)
    .filter(([key]) => typeof signals[key] === 'number');
  const flagRows = Object.entries(BOOLEAN_SIGNAL_LABELS)
    .filter(([key]) => typeof signals[key] === 'boolean');

  return (
    <div className="mt-2.5 space-y-2 rounded-lg border border-border bg-inset/50 p-2.5">
      <div className="grid grid-cols-[auto,1fr] gap-x-2 gap-y-1 text-[10.5px]">
        <span className="text-faint">Bộ dò</span>
        <span className="break-all text-dim">
          {relation?.detector_version || 'Không rõ phiên bản'}
        </span>
        <span className="text-faint">Nhận định</span>
        <span className="text-dim">{relation?.reason || 'Không có ghi chú từ bộ dò'}</span>
      </div>

      {scoreRows.length > 0 && (
        <div>
          <div className="mb-1 text-[10px] font-semibold uppercase tracking-wide text-faint">
            Điểm tín hiệu
          </div>
          <div className="space-y-1">
            {scoreRows.map(([key, label]) => (
              <div
                key={key}
                className="flex items-center justify-between gap-2 text-[10.5px]"
              >
                <span className="text-dim">{label}</span>
                <span className="tabular-nums text-foreground">
                  {confidenceLabel(signals[key])}
                </span>
              </div>
            ))}
          </div>
        </div>
      )}

      {reasonCodes.length > 0 && (
        <div className="flex flex-wrap gap-1">
          {reasonCodes.map((code) => (
            <span
              key={String(code)}
              className="rounded-full border border-yellow/30 bg-yellow/5 px-1.5 py-0.5 text-[9.5px] text-yellow"
            >
              {reasonCodeLabel(code)}
            </span>
          ))}
        </div>
      )}

      {flagRows.length > 0 && (
        <div className="space-y-0.5">
          {flagRows.map(([key, labels]) => {
            const active = signals[key] === true;
            const isProblem = key.includes('mismatch') ? active : !active;
            return (
              <div key={key} className="flex items-center gap-1.5 text-[10px] text-faint">
                <Icon
                  icon={isProblem ? 'lucide:circle-alert' : 'lucide:circle-check'}
                  width={11}
                  className={isProblem ? 'text-yellow' : 'text-faint'}
                />
                {labels[active ? 0 : 1]}
              </div>
            );
          })}
        </div>
      )}

      {(typeof signals.matched_probe_count === 'number'
        || typeof signals.probe_count === 'number'
        || typeof signals.matched_chunk_pair_count === 'number') && (
        <div className="text-[10px] text-faint">
          Khớp {String(signals.matched_probe_count ?? '–')}/{String(signals.probe_count ?? '–')} mẫu dò
          {' · '}
          {String(signals.matched_chunk_pair_count ?? '–')} cặp chunk
        </div>
      )}

      {pairCounts && (
        <div>
          <div className="mb-1 text-[10px] font-semibold uppercase tracking-wide text-faint">
            Phân bố cặp chunk
          </div>
          <div className="flex flex-wrap gap-1">
            {Object.entries(pairCounts).map(([key, value]) => (
              <span
                key={key}
                className="rounded bg-background px-1.5 py-0.5 text-[9.5px] text-dim"
              >
                {RELATION_LABELS[key] || key}: {String(value)}
              </span>
            ))}
          </div>
        </div>
      )}

      {selectedPair && (
        <div className="rounded-md border border-border bg-background/60 p-2 text-[10px] text-faint">
          <div className="mb-1 font-semibold uppercase tracking-wide">Cặp chunk tiêu biểu</div>
          <div>
            Nguồn mới: trang {String(selectedPair.source_page_number ?? '–')},
            chunk {String(selectedPair.source_chunk_index ?? '–')}
          </div>
          <div>
            Nguồn cũ: trang {String(selectedPair.target_page_number ?? '–')},
            chunk {String(selectedPair.target_chunk_index ?? '–')}
          </div>
          <div className="mt-1 break-all">
            {String(selectedPair.source_chunk_id || '–')} ↔ {String(selectedPair.target_chunk_id || '–')}
          </div>
        </div>
      )}

      {claimConflicts.length > 0 && (
        <div>
          <div className="mb-1 text-[10px] font-semibold uppercase tracking-wide text-faint">
            Claim mâu thuẫn ({claimConflicts.length})
          </div>
          <div className="space-y-2">
            {claimConflicts.map((conflict, index) => {
              const codes = Array.isArray(conflict.reason_codes)
                ? conflict.reason_codes
                : [];
              return (
                <div
                  key={`${String(conflict.alignment_score || 'claim')}-${index}`}
                  className="rounded-lg border border-yellow/25 bg-yellow/5 p-2"
                >
                  <div className="mb-1.5 flex items-center justify-between gap-2 text-[10px]">
                    <span className="font-semibold text-yellow">
                      {codes.map(reasonCodeLabel).join(' · ') || 'Khác nội dung'}
                    </span>
                    {typeof conflict.alignment_score === 'number' && (
                      <span className="shrink-0 tabular-nums text-faint">
                        Khớp {confidenceLabel(conflict.alignment_score)}
                      </span>
                    )}
                  </div>
                  <div className="space-y-1.5">
                    <ClaimSide title="Tài liệu mới" claim={conflict.left} />
                    <ClaimSide title="Tài liệu cũ" claim={conflict.right} />
                  </div>
                </div>
              );
            })}
          </div>
        </div>
      )}

      <details>
        <summary className="cursor-pointer text-[10px] text-faint hover:text-dim">
          Xem tín hiệu JSON gốc
        </summary>
        <pre className="mt-1 max-h-52 overflow-auto whitespace-pre-wrap break-all rounded bg-background p-2 text-[9px] leading-relaxed text-faint">
          {JSON.stringify(signals, null, 2)}
        </pre>
      </details>
    </div>
  );
}

function RelationAuditTimeline({
  auditState,
  onLoad,
  onLoadMore,
}) {
  if (!auditState?.loaded && !auditState?.loading) {
    return (
      <button
        type="button"
        onClick={onLoad}
        className="mt-2 text-[10.5px] font-medium text-accent hover:underline"
      >
        Tải lịch sử của cặp tài liệu
      </button>
    );
  }
  if (auditState?.loading) {
    return (
      <div className="mt-2 flex items-center gap-1.5 text-[10.5px] text-faint">
        <Icon icon="lucide:loader-circle" className="animate-spin" width={12} />
        Đang tải audit log
      </div>
    );
  }
  return (
    <div className="mt-2">
      <div className="mb-1 text-[10px] font-semibold uppercase tracking-wide text-faint">
        Audit log
      </div>
      {auditState?.error && <ErrorBanner message={auditState.error} onRetry={onLoad} />}
      {auditState?.items?.length ? (
        <div className="space-y-1 border-l border-border pl-2">
          {auditState.items.map((event) => (
            <div key={event.id} className="text-[10px]">
              <div className="font-medium text-dim">
                {ACTION_LABELS[event.action] || event.action}
              </div>
              <div className="text-faint">{formatQualityTimestamp(event.created_at)}</div>
              {event.reason && <div className="mt-0.5 text-faint">{event.reason}</div>}
            </div>
          ))}
        </div>
      ) : (
        <div className="text-[10px] text-faint">Chưa có quyết định nào.</div>
      )}
      {auditState?.items?.length < auditState?.totalCount && (
        <button
          type="button"
          disabled={auditState.loadingMore}
          onClick={onLoadMore}
          className="mt-1.5 text-[10px] font-medium text-accent hover:underline disabled:opacity-50"
        >
          {auditState.loadingMore ? 'Đang tải…' : 'Tải thêm audit'}
        </button>
      )}
    </div>
  );
}

function EmptyState({ view }) {
  const history = view === 'history';
  return (
    <div className="px-4 py-9 text-center">
      <Icon
        icon={history ? 'lucide:history' : 'lucide:badge-check'}
        width={24}
        className="mx-auto mb-2 text-green"
      />
      <div className="text-[13px] font-semibold text-foreground">
        {history ? 'Chưa có lịch sử quyết định' : 'Không còn mục cần duyệt'}
      </div>
      <div className="mt-1 text-[11.5px] text-faint">
        {history
          ? 'Mọi quyết định và lần hoàn tác sẽ xuất hiện tại đây.'
          : 'Các cặp đáng ngờ mới sẽ xuất hiện sau khi xử lý tài liệu.'}
      </div>
    </div>
  );
}

function LoadingState({ label }) {
  return (
    <div className="flex items-center justify-center gap-2 px-3 py-8 text-xs text-faint">
      <Icon icon="lucide:loader-circle" className="animate-spin" width={15} />
      {label}
    </div>
  );
}

function LoadMoreButton({ busy, onClick, children = 'Tải thêm' }) {
  return (
    <button
      type="button"
      disabled={busy}
      onClick={onClick}
      className="mt-2 flex h-8 w-full items-center justify-center gap-1.5 rounded-lg border border-border text-[11px] font-medium text-dim hover:bg-inset hover:text-foreground disabled:opacity-50"
    >
      {busy && <Icon icon="lucide:loader-circle" className="animate-spin" width={12} />}
      {busy ? 'Đang tải…' : children}
    </button>
  );
}

export default function KnowledgeQualityPanel({
  notebookId,
  documents,
  onResolved,
  showToast,
}) {
  const {
    pendingRelations,
    pendingTotalCount,
    pendingLoaded,
    pendingLoading,
    pendingLoadingMore,
    pendingError,
    auditEvents,
    auditTotalCount,
    auditLoaded,
    auditLoading,
    auditLoadingMore,
    auditError,
    relationAudits,
    relationEvidence,
    resolvingId,
    revertingId,
    resetForNotebook,
    fetchPending,
    fetchAuditEvents,
    fetchRelationAudit,
    fetchRelationEvidence,
    resolveRelation,
    revertRelation,
  } = useQualityStore();
  const [view, setView] = useState('pending');
  const [expandedRelationId, setExpandedRelationId] = useState(null);
  const [expandedAuditId, setExpandedAuditId] = useState(null);
  const [draft, setDraft] = useState(null);
  const [draftReason, setDraftReason] = useState('');
  const [draftError, setDraftError] = useState('');

  useEffect(() => {
    setView('pending');
    setExpandedRelationId(null);
    setExpandedAuditId(null);
    setDraft(null);
    setDraftReason('');
    setDraftError('');
    resetForNotebook(notebookId);
    if (notebookId) {
      fetchPending(notebookId).catch(() => {});
    }
  }, [notebookId, fetchPending, resetForNotebook]);

  useEffect(() => {
    if (
      notebookId
      && view === 'history'
      && !auditLoaded
      && !auditLoading
    ) {
      fetchAuditEvents(notebookId).catch(() => {});
    }
  }, [
    notebookId,
    view,
    auditLoaded,
    auditLoading,
    fetchAuditEvents,
  ]);

  const documentsById = useMemo(
    () => new Map(documents.map((document) => [document.id, document])),
    [documents],
  );
  const latestAuditByRelation = useMemo(() => {
    const latest = new Map();
    for (const event of auditEvents) {
      if (event.relation_id && !latest.has(event.relation_id)) {
        latest.set(event.relation_id, event.id);
      }
    }
    return latest;
  }, [auditEvents]);

  const beginDraft = (kind, relationId, action = null, auditId = null) => {
    setDraft({ kind, relationId, action, auditId });
    setDraftReason('');
    setDraftError('');
  };

  const cancelDraft = () => {
    setDraft(null);
    setDraftReason('');
    setDraftError('');
  };

  const applyDecision = async (event, relation, action) => {
    event.preventDefault();
    if (!draftReason.trim()) {
      setDraftError('Lý do là bắt buộc.');
      return;
    }
    setDraftError('');
    try {
      await resolveRelation(
        notebookId,
        relation.id,
        action,
        draftReason,
      );
      cancelDraft();
      await onResolved?.();
      showToast?.('Đã lưu quyết định cùng lý do vào audit log.', 'success');
    } catch (decisionError) {
      const message = decisionError instanceof Error
        ? decisionError.message
        : 'Không thể lưu quyết định';
      setDraftError(message);
      showToast?.(message, 'error');
    }
  };

  const applyRevert = async (event, auditEvent) => {
    event.preventDefault();
    if (!draftReason.trim()) {
      setDraftError('Lý do hoàn tác là bắt buộc.');
      return;
    }
    const relation = relationSnapshotFromAudit(auditEvent);
    if (!relation?.updated_at || !auditEvent.relation_id) {
      setDraftError('Audit event không có phiên bản relation hợp lệ để hoàn tác.');
      return;
    }
    setDraftError('');
    try {
      await revertRelation(
        notebookId,
        auditEvent.relation_id,
        relation.updated_at,
        draftReason,
      );
      cancelDraft();
      await onResolved?.();
      showToast?.('Đã hoàn tác và ghi thêm một audit event.', 'success');
    } catch (revertError) {
      const message = revertError instanceof Error
        ? revertError.message
        : 'Không thể hoàn tác quyết định';
      setDraftError(message);
      showToast?.(message, 'error');
    }
  };

  const toggleRelationDetails = (relationId) => {
    const opening = expandedRelationId !== relationId;
    setExpandedRelationId(opening ? relationId : null);
    const evidenceState = relationEvidence[relationId];
    const needsOriginalPreviewReload = Boolean(
      evidenceState?.loaded
      && evidenceState?.data
      && (
        !Array.isArray(evidenceState.data.source_original_blocks)
        || !Array.isArray(evidenceState.data.target_original_blocks)
      ),
    );
    if (
      opening
      && notebookId
      && !relationAudits[relationId]?.loaded
      && !relationAudits[relationId]?.loading
    ) {
      fetchRelationAudit(notebookId, relationId).catch(() => {});
    }
    if (
      opening
      && notebookId
      && (!evidenceState?.loaded || needsOriginalPreviewReload)
      && !evidenceState?.loading
    ) {
      fetchRelationEvidence(
        notebookId,
        relationId,
        { force: needsOriginalPreviewReload },
      ).catch(() => {});
    }
  };

  if (!notebookId) {
    return (
      <div className="px-3 py-8 text-center text-xs text-faint">
        Chọn một sổ tay để kiểm tra tài liệu.
      </div>
    );
  }

  const refreshing = view === 'pending' ? pendingLoading : auditLoading;
  const refresh = () => (
    view === 'pending'
      ? fetchPending(notebookId)
      : fetchAuditEvents(notebookId)
  );

  return (
    <div>
      <div className="mb-2 flex items-center gap-1 rounded-lg bg-inset p-1">
        <button
          type="button"
          role="tab"
          aria-selected={view === 'pending'}
          onClick={() => setView('pending')}
          className={`flex h-7 flex-1 items-center justify-center gap-1 rounded-md text-[11px] font-medium transition-colors ${
            view === 'pending'
              ? 'bg-panel text-foreground shadow-sm'
              : 'text-faint hover:text-dim'
          }`}
        >
          Chờ duyệt
          {pendingLoaded && (
            <span className="rounded-full bg-accent/10 px-1.5 text-[9.5px] text-accent">
              {pendingTotalCount}
            </span>
          )}
        </button>
        <button
          type="button"
          role="tab"
          aria-selected={view === 'history'}
          onClick={() => setView('history')}
          className={`flex h-7 flex-1 items-center justify-center gap-1 rounded-md text-[11px] font-medium transition-colors ${
            view === 'history'
              ? 'bg-panel text-foreground shadow-sm'
              : 'text-faint hover:text-dim'
          }`}
        >
          Lịch sử
          {auditLoaded && (
            <span className="rounded-full bg-accent/10 px-1.5 text-[9.5px] text-accent">
              {auditTotalCount}
            </span>
          )}
        </button>
        <button
          type="button"
          title="Làm mới"
          aria-label="Làm mới danh sách chất lượng"
          disabled={refreshing}
          onClick={() => refresh().catch(() => {})}
          className="flex h-7 w-7 items-center justify-center rounded-md text-faint hover:bg-panel hover:text-foreground disabled:opacity-50"
        >
          <Icon
            icon="lucide:refresh-cw"
            width={13}
            className={refreshing ? 'animate-spin' : ''}
          />
        </button>
      </div>

      {view === 'pending' ? (
        <>
          <ErrorBanner
            message={pendingError}
            onRetry={() => fetchPending(notebookId).catch(() => {})}
          />
          {pendingLoading && pendingRelations.length === 0 ? (
            <LoadingState label="Đang tải hàng chờ" />
          ) : pendingRelations.length === 0 ? (
            <EmptyState view="pending" />
          ) : (
            <>
              <div className="mb-1 px-1 text-[10.5px] text-faint">
                Hiển thị {pendingRelations.length}/{pendingTotalCount} cặp
              </div>
              {pendingRelations.map((relation) => {
                const busy = resolvingId === relation.id;
                const signals = isRecord(relation.signals) ? relation.signals : {};
                const summary = signalSummary(signals);
                const isConflict = relation.relation_type.includes('conflict');
                const isTemporalSeries = relation.relation_type === 'temporal_series';
                const expanded = expandedRelationId === relation.id;
                const decisionOpen = draft?.kind === 'resolve'
                  && draft.relationId === relation.id;
                return (
                  <section
                    key={relation.id}
                    className="border-b border-border px-1 py-3 last:border-b-0"
                  >
                    <div className="mb-1.5 flex items-start justify-between gap-2">
                      <span className="text-[11px] font-semibold uppercase text-accent">
                        {RELATION_LABELS[relation.relation_type] || relation.relation_type}
                      </span>
                      <span className="text-[11px] tabular-nums text-faint">
                        {confidenceLabel(relation.confidence)}
                      </span>
                    </div>

                    <div className="space-y-1 text-[12px]">
                      <div className="flex min-w-0 items-center gap-1.5">
                        <Icon icon="lucide:file-up" width={12} className="shrink-0 text-faint" />
                        <span className="truncate font-medium text-foreground">
                          {documentName(documentsById, relation.source_document_id)}
                        </span>
                      </div>
                      <div className="flex min-w-0 items-center gap-1.5">
                        <Icon icon="lucide:file-clock" width={12} className="shrink-0 text-faint" />
                        <span className="truncate text-dim">
                          {documentName(documentsById, relation.target_document_id)}
                        </span>
                      </div>
                    </div>

                    {summary && (
                      <div className="mt-1.5 text-[10.5px] text-faint">{summary}</div>
                    )}
                    <div className="mt-1 text-[9.5px] text-faint">
                      Bộ dò: {relation.detector_version}
                    </div>

                    <button
                      type="button"
                      aria-expanded={expanded}
                      onClick={() => toggleRelationDetails(relation.id)}
                      className="mt-1.5 flex items-center gap-1 text-[10.5px] font-medium text-accent hover:underline"
                    >
                      <Icon
                        icon={expanded ? 'lucide:chevron-up' : 'lucide:chevron-down'}
                        width={11}
                      />
                      {expanded ? 'Ẩn bằng chứng' : 'Xem bằng chứng và audit'}
                    </button>

                    {expanded && (
                      <>
                        <EvidenceComparison
                          evidenceState={relationEvidence[relation.id]}
                          relation={relation}
                          onRetry={() => (
                            fetchRelationEvidence(
                              notebookId,
                              relation.id,
                              { force: true },
                            ).catch(() => {})
                          )}
                        />
                        <EvidenceDetails relation={relation} />
                        <RelationAuditTimeline
                          auditState={relationAudits[relation.id]}
                          onLoad={() => (
                            fetchRelationAudit(notebookId, relation.id).catch(() => {})
                          )}
                          onLoadMore={() => (
                            fetchRelationAudit(
                              notebookId,
                              relation.id,
                              { append: true },
                            ).catch(() => {})
                          )}
                        />
                      </>
                    )}

                    <div className="mt-2.5 flex flex-wrap gap-1.5">
                      {isConflict ? (
                        <>
                          <ReviewAction
                            icon="lucide:file-up"
                            label="Ưu tiên mới"
                            disabled={busy}
                            tone="warning"
                            onClick={() => beginDraft('resolve', relation.id, 'prefer_source')}
                          />
                          <ReviewAction
                            icon="lucide:file-clock"
                            label="Ưu tiên cũ"
                            disabled={busy}
                            tone="warning"
                            onClick={() => beginDraft('resolve', relation.id, 'prefer_target')}
                          />
                          <ReviewAction
                            icon="lucide:triangle-alert"
                            label="Giữ cả hai"
                            title="Giữ cả hai nguồn và cảnh báo khi trả lời"
                            disabled={busy}
                            tone="warning"
                            onClick={() => beginDraft('resolve', relation.id, 'confirm_conflict')}
                          />
                        </>
                      ) : isTemporalSeries ? null : (
                        <>
                          <ReviewAction
                            icon="lucide:copy-check"
                            label="Trùng"
                            title="Dùng tài liệu cũ làm bản chuẩn"
                            disabled={busy}
                            onClick={() => beginDraft('resolve', relation.id, 'confirm_duplicate')}
                          />
                          <ReviewAction
                            icon="lucide:triangle-alert"
                            label="Xung đột"
                            disabled={busy}
                            tone="warning"
                            onClick={() => beginDraft('resolve', relation.id, 'confirm_conflict')}
                          />
                        </>
                      )}
                      <ReviewAction
                        icon="lucide:git-compare-arrows"
                        label="Phiên bản"
                        title="Tài liệu mới cập nhật tài liệu cũ"
                        disabled={busy}
                        onClick={() => beginDraft('resolve', relation.id, 'mark_version')}
                      />
                      <ReviewAction
                        icon="lucide:split"
                        label="Tách riêng"
                        disabled={busy}
                        onClick={() => beginDraft('resolve', relation.id, 'keep_separate')}
                      />
                      <ReviewAction
                        icon="lucide:x"
                        label="Bỏ qua"
                        disabled={busy}
                        tone="danger"
                        onClick={() => beginDraft('resolve', relation.id, 'dismiss')}
                      />
                    </div>

                    {decisionOpen && (
                      <ReasonForm
                        title={DECISION_TITLES[draft.action] || 'Nhập lý do quyết định'}
                        submitLabel="Lưu quyết định"
                        reason={draftReason}
                        error={draftError}
                        busy={busy}
                        onReasonChange={(value) => {
                          setDraftReason(value);
                          setDraftError('');
                        }}
                        onCancel={cancelDraft}
                        onSubmit={(event) => (
                          applyDecision(event, relation, draft.action)
                        )}
                      />
                    )}
                  </section>
                );
              })}
              {pendingRelations.length < pendingTotalCount && (
                <LoadMoreButton
                  busy={pendingLoadingMore}
                  onClick={() => (
                    fetchPending(notebookId, { append: true }).catch(() => {})
                  )}
                >
                  Tải thêm cặp cần duyệt
                </LoadMoreButton>
              )}
            </>
          )}
        </>
      ) : (
        <>
          <ErrorBanner
            message={auditError}
            onRetry={() => fetchAuditEvents(notebookId).catch(() => {})}
          />
          {auditLoading && auditEvents.length === 0 ? (
            <LoadingState label="Đang tải lịch sử" />
          ) : auditEvents.length === 0 ? (
            <EmptyState view="history" />
          ) : (
            <>
              <div className="mb-1 px-1 text-[10.5px] text-faint">
                Hiển thị {auditEvents.length}/{auditTotalCount} audit event
              </div>
              {auditEvents.map((auditEvent) => {
                const relation = relationSnapshotFromAudit(auditEvent);
                const beforeRelation = relationSnapshotFromState(auditEvent.before_state);
                const afterRelation = relationSnapshotFromState(auditEvent.after_state);
                const expanded = expandedAuditId === auditEvent.id;
                const latest = latestAuditByRelation.get(auditEvent.relation_id)
                  === auditEvent.id;
                const reversible = canRevertAuditEvent(auditEvent, latest);
                const revertOpen = draft?.kind === 'revert'
                  && draft.auditId === auditEvent.id;
                const busy = revertingId === auditEvent.relation_id;
                return (
                  <section
                    key={auditEvent.id}
                    className="border-b border-border px-1 py-3 last:border-b-0"
                  >
                    <div className="flex items-start justify-between gap-2">
                      <div>
                        <div className="text-[11px] font-semibold text-foreground">
                          {ACTION_LABELS[auditEvent.action] || auditEvent.action}
                        </div>
                        <div className="mt-0.5 text-[9.5px] text-faint">
                          {auditEvent.actor_id ? 'Người dùng' : 'Hệ thống'}
                          {' · '}
                          {formatQualityTimestamp(auditEvent.created_at)}
                        </div>
                      </div>
                      <span className="shrink-0 rounded bg-inset px-1.5 py-0.5 text-[9px] tabular-nums text-faint">
                        #{auditEvent.id}
                      </span>
                    </div>

                    {relation && (
                      <div className="mt-2 space-y-1 text-[11.5px]">
                        <div className="flex min-w-0 items-center gap-1.5">
                          <Icon icon="lucide:file-up" width={11} className="shrink-0 text-faint" />
                          <span className="truncate text-foreground">
                            {documentName(documentsById, relation.source_document_id)}
                          </span>
                        </div>
                        <div className="flex min-w-0 items-center gap-1.5">
                          <Icon icon="lucide:file-clock" width={11} className="shrink-0 text-faint" />
                          <span className="truncate text-dim">
                            {documentName(documentsById, relation.target_document_id)}
                          </span>
                        </div>
                      </div>
                    )}

                    <div className="mt-1.5 text-[10.5px] leading-relaxed text-dim">
                      <span className="text-faint">Lý do: </span>
                      {auditEvent.reason || 'Không có lý do được ghi nhận'}
                    </div>

                    {relation && (
                      <div className="mt-1 flex flex-wrap items-center gap-1 text-[9.5px] text-faint">
                        <span>{RELATION_LABELS[relation.relation_type] || relation.relation_type}</span>
                        <span>·</span>
                        <span>{STATUS_LABELS[relation.status] || relation.status}</span>
                        {relation.detector_version && (
                          <>
                            <span>·</span>
                            <span>{relation.detector_version}</span>
                          </>
                        )}
                      </div>
                    )}

                    <div className="mt-2 flex items-center gap-2">
                      <button
                        type="button"
                        aria-expanded={expanded}
                        onClick={() => setExpandedAuditId(expanded ? null : auditEvent.id)}
                        className="flex items-center gap-1 text-[10.5px] font-medium text-accent hover:underline"
                      >
                        <Icon
                          icon={expanded ? 'lucide:chevron-up' : 'lucide:chevron-down'}
                          width={11}
                        />
                        {expanded ? 'Ẩn chi tiết' : 'Xem snapshot'}
                      </button>
                      {reversible && (
                        <button
                          type="button"
                          disabled={busy}
                          onClick={() => (
                            beginDraft(
                              'revert',
                              auditEvent.relation_id,
                              null,
                              auditEvent.id,
                            )
                          )}
                          className="flex items-center gap-1 text-[10.5px] font-medium text-yellow hover:underline disabled:opacity-50"
                        >
                          <Icon icon="lucide:undo-2" width={11} />
                          Hoàn tác
                        </button>
                      )}
                    </div>

                    {expanded && (
                      <div className="mt-2 rounded-lg border border-border bg-inset/50 p-2.5">
                        <div className="grid grid-cols-[auto,1fr] gap-x-2 gap-y-1 text-[10px]">
                          <span className="text-faint">Trước</span>
                          <span className="text-dim">
                            {beforeRelation
                              ? STATUS_LABELS[beforeRelation.status] || beforeRelation.status
                              : 'Không có relation snapshot'}
                          </span>
                          <span className="text-faint">Sau</span>
                          <span className="text-dim">
                            {afterRelation
                              ? STATUS_LABELS[afterRelation.status] || afterRelation.status
                              : 'Không có relation snapshot'}
                          </span>
                          <span className="text-faint">Relation ID</span>
                          <span className="break-all text-dim">
                            {auditEvent.relation_id || 'Relation đã bị xóa'}
                          </span>
                        </div>
                        {relation && <EvidenceDetails relation={relation} />}
                      </div>
                    )}

                    {revertOpen && (
                      <ReasonForm
                        title="Lý do hoàn tác quyết định"
                        submitLabel="Xác nhận hoàn tác"
                        reason={draftReason}
                        error={draftError}
                        busy={busy}
                        onReasonChange={(value) => {
                          setDraftReason(value);
                          setDraftError('');
                        }}
                        onCancel={cancelDraft}
                        onSubmit={(event) => applyRevert(event, auditEvent)}
                      />
                    )}
                  </section>
                );
              })}
              {auditEvents.length < auditTotalCount && (
                <LoadMoreButton
                  busy={auditLoadingMore}
                  onClick={() => (
                    fetchAuditEvents(notebookId, { append: true }).catch(() => {})
                  )}
                >
                  Tải thêm lịch sử
                </LoadMoreButton>
              )}
            </>
          )}
        </>
      )}
    </div>
  );
}
