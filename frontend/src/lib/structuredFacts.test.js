import assert from 'node:assert/strict';
import test from 'node:test';

import {
  confirmActionForRelation,
  requireStructuredReason,
  structuredClaimValue,
  structuredSubjectLabel,
} from './structuredFacts.js';

test('maps relation semantics to the audited backend resolution action', () => {
  assert.equal(confirmActionForRelation('conflict_candidate'), 'confirm_conflict');
  assert.equal(confirmActionForRelation('equivalent'), 'confirm_equivalent');
  assert.equal(confirmActionForRelation('updated'), 'confirm_update');
  assert.equal(confirmActionForRelation('source_updates_target'), 'confirm');
  assert.equal(confirmActionForRelation('target_updates_source'), 'confirm');
  assert.equal(
    confirmActionForRelation('conditional_variant'),
    'confirm_conditional_variant',
  );
  assert.equal(confirmActionForRelation('uncertain'), 'confirm');
});

test('requires and normalizes a human review reason', () => {
  assert.equal(requireStructuredReason('  Đã đối chiếu bảng giá  '), 'Đã đối chiếu bảng giá');
  assert.throws(() => requireStructuredReason('  '), /Vui lòng nhập lý do/);
});

test('presents raw source values first and keeps normalized fallback readable', () => {
  assert.equal(
    structuredClaimValue({ normalized_value: { raw_value: '  82 triệu/m² ' } }),
    '82 triệu/m²',
  );
  assert.equal(
    structuredClaimValue({
      normalized_value: { value: 82, basis: 'm2' },
      currency: 'VND',
      unit: 'million',
    }),
    '82 VND · million · m2',
  );
});

test('uses the canonical subject key before row identity', () => {
  assert.equal(
    structuredSubjectLabel({
      subject_identity: { subject_key: 'Căn A101' },
      row_identity: 'row-1',
    }),
    'Căn A101',
  );
});
