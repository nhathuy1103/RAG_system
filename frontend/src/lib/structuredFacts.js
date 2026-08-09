export const STRUCTURED_RELATION_LABELS = {
  unchanged: 'Không đổi',
  updated: 'Đã cập nhật',
  added: 'Mới xuất hiện',
  removed: 'Không còn xuất hiện',
  equivalent: 'Tương đương',
  source_updates_target: 'Nguồn mới cập nhật nguồn cũ',
  target_updates_source: 'Nguồn cũ cập nhật nguồn mới',
  source_supersedes_target: 'Nguồn mới thay thế nguồn cũ',
  target_supersedes_source: 'Nguồn cũ thay thế nguồn mới',
  source_contains_target: 'Nguồn mới bao hàm nguồn cũ',
  target_contains_source: 'Nguồn cũ bao hàm nguồn mới',
  source_only: 'Chỉ có ở nguồn mới',
  target_only: 'Chỉ có ở nguồn cũ',
  conflict_candidate: 'Có thể mâu thuẫn',
  conflict: 'Mâu thuẫn',
  conditional_variant: 'Khác điều kiện áp dụng',
  distinct: 'Khác dữ kiện',
  uncertain: 'Chưa chắc chắn',
};

const CONFLICT_TYPES = new Set(['conflict', 'conflict_candidate']);
const EQUIVALENT_TYPES = new Set(['unchanged', 'equivalent']);
export function confirmActionForRelation(relationType) {
  if (CONFLICT_TYPES.has(relationType)) return 'confirm_conflict';
  if (EQUIVALENT_TYPES.has(relationType)) return 'confirm_equivalent';
  if (relationType === 'updated') return 'confirm_update';
  if (relationType === 'conditional_variant') {
    return 'confirm_conditional_variant';
  }
  // The backend's confirm_update action always orients the result as
  // source_updates_target. Preserve already directional update/supersession
  // relations with the generic confirm action instead of reversing meaning.
  return 'confirm';
}

export function requireStructuredReason(reason) {
  const normalized = typeof reason === 'string' ? reason.trim() : '';
  if (!normalized) {
    throw new Error('Vui lòng nhập lý do cho quyết định.');
  }
  return normalized;
}

export function structuredClaimValue(claim) {
  if (!claim) return 'Không có claim ở phía này';
  const normalized = claim.normalized_value || {};
  const raw = normalized.raw_value;
  if (typeof raw === 'string' && raw.trim()) return raw.trim();

  const rawValue = normalized.value ?? claim.numeric_value;
  if (rawValue === null || rawValue === undefined || rawValue === '') {
    return 'Không có giá trị';
  }
  const suffix = [claim.currency, claim.unit, normalized.basis]
    .filter((value) => typeof value === 'string' && value.trim())
    .join(' · ');
  return suffix ? `${String(rawValue)} ${suffix}` : String(rawValue);
}

export function structuredSubjectLabel(claim) {
  if (!claim) return 'Không có claim';
  const identity = claim.subject_identity || {};
  if (typeof identity.subject_key === 'string' && identity.subject_key.trim()) {
    return identity.subject_key;
  }
  return claim.row_identity || claim.claim_key || 'Không rõ đối tượng';
}

export function isStructuredConflict(relationType) {
  return CONFLICT_TYPES.has(relationType);
}
