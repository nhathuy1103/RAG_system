export const RELATION_LABELS = {
  exact_content: 'Nội dung trùng',
  technical_duplicate: 'File trùng',
  near_duplicate: 'Gần giống',
  version_candidate: 'Có thể là phiên bản mới',
  version: 'Cùng dòng phiên bản',
  conflict_candidate: 'Có thể mâu thuẫn',
  conflict: 'Mâu thuẫn',
  related: 'Có liên quan',
  distinct: 'Tách biệt',
  template_variant: 'Cùng mẫu, khác phạm vi',
};

export const STATUS_LABELS = {
  pending: 'Chờ duyệt',
  auto_confirmed: 'Tự động xác nhận',
  confirmed: 'Đã xác nhận',
  dismissed: 'Đã bỏ qua',
};

export const ACTION_LABELS = {
  auto_confirm_duplicate: 'Tự động xác nhận trùng',
  confirm_duplicate: 'Xác nhận trùng',
  mark_version: 'Đánh dấu phiên bản mới',
  confirm_conflict: 'Xác nhận mâu thuẫn',
  keep_separate: 'Giữ tách biệt',
  prefer_source: 'Ưu tiên tài liệu mới',
  prefer_target: 'Ưu tiên tài liệu cũ',
  dismiss: 'Bỏ qua đề xuất',
  revert_resolution: 'Hoàn tác quyết định',
};

export const REASON_CODE_LABELS = {
  number_mismatch: 'Khác số liệu',
  semantic_quantity_mismatch: 'Khác giá trị định lượng',
  unit_mismatch: 'Khác đơn vị',
  unit_value_mismatch: 'Khác đơn vị hoặc thang đo',
  date_mismatch: 'Khác ngày hoặc thời điểm hiệu lực',
  date_value_mismatch: 'Khác ngày hoặc thời điểm hiệu lực',
  negation_mismatch: 'Khác ý phủ định',
  policy_modality_mismatch: 'Khác mức độ bắt buộc của chính sách',
  different_claim_scope: 'Khác phạm vi áp dụng',
  different_project_entity: 'Khác dự án',
  different_contract_entity: 'Khác hợp đồng',
  shared_legal_template: 'Dùng chung mẫu pháp lý',
  structural_numbers_ignored: 'Đã bỏ qua số tham chiếu cấu trúc',
  template_overlap_without_claim_alignment: 'Mẫu giống nhưng không cùng claim',
  scope_unknown_conflict_suppressed: 'Chưa đủ scope để xác nhận mâu thuẫn',
};

export const SCORE_SIGNAL_LABELS = {
  lexical_similarity: 'Tương đồng từ ngữ',
  semantic_similarity: 'Tương đồng ngữ nghĩa',
  containment: 'Mức bao phủ nội dung',
  document_probe_coverage: 'Độ phủ tài liệu',
  template_similarity: 'Tương đồng mẫu',
};

export const BOOLEAN_SIGNAL_LABELS = {
  number_agreement: ['Số liệu đồng nhất', 'Số liệu khác nhau'],
  unit_agreement: ['Đơn vị đồng nhất', 'Đơn vị khác nhau'],
  date_agreement: ['Ngày đồng nhất', 'Ngày khác nhau'],
  negation_mismatch: ['Khác ý phủ định', 'Không khác ý phủ định'],
  policy_modality_mismatch: [
    'Khác mức độ chính sách',
    'Không khác mức độ chính sách',
  ],
};

const HUMAN_RESOLUTION_ACTIONS = new Set([
  'confirm_duplicate',
  'mark_version',
  'confirm_conflict',
  'keep_separate',
  'prefer_source',
  'prefer_target',
  'dismiss',
]);

export function isRecord(value) {
  return value !== null && typeof value === 'object' && !Array.isArray(value);
}

export function requireQualityReason(reason, kind = 'decision') {
  const normalized = typeof reason === 'string' ? reason.trim() : '';
  if (!normalized) {
    throw new Error(
      kind === 'revert'
        ? 'Vui lòng nhập lý do hoàn tác.'
        : 'Vui lòng nhập lý do cho quyết định.',
    );
  }
  return normalized;
}

export function mergeUniqueById(current, incoming) {
  const merged = [...current];
  const indexes = new Map(
    current.map((item, index) => [String(item.id), index]),
  );
  for (const item of incoming) {
    const key = String(item.id);
    const existingIndex = indexes.get(key);
    if (existingIndex === undefined) {
      indexes.set(key, merged.length);
      merged.push(item);
    } else {
      merged[existingIndex] = item;
    }
  }
  return merged;
}

export function relationSnapshotFromState(state) {
  if (!isRecord(state)) return null;
  const candidate = isRecord(state.relation) ? state.relation : state;
  if (
    typeof candidate.id !== 'string'
    || typeof candidate.source_document_id !== 'string'
    || typeof candidate.target_document_id !== 'string'
  ) {
    return null;
  }
  return candidate;
}

export function relationSnapshotFromAudit(event) {
  return (
    relationSnapshotFromState(event?.after_state)
    || relationSnapshotFromState(event?.before_state)
  );
}

export function canRevertAuditEvent(event, isLatestForRelation) {
  if (
    !isLatestForRelation
    || !event?.relation_id
    || !HUMAN_RESOLUTION_ACTIONS.has(event.action)
    || !Array.isArray(event?.before_state?.documents)
  ) {
    return false;
  }
  const relation = relationSnapshotFromAudit(event);
  return typeof relation?.updated_at === 'string' && relation.updated_at.length > 0;
}

export function confidenceLabel(confidence) {
  const numeric = Number(confidence);
  const safeValue = Number.isFinite(numeric)
    ? Math.max(0, Math.min(1, numeric))
    : 0;
  return `${Math.round(safeValue * 100)}%`;
}

export function formatQualityTimestamp(value) {
  const parsed = new Date(value);
  if (Number.isNaN(parsed.getTime())) return 'Không rõ thời điểm';
  return new Intl.DateTimeFormat('vi-VN', {
    dateStyle: 'short',
    timeStyle: 'short',
  }).format(parsed);
}

export function reasonCodeLabel(code) {
  return REASON_CODE_LABELS[code] || String(code).replaceAll('_', ' ');
}
