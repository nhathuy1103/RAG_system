import assert from 'node:assert/strict';
import test from 'node:test';

import {
  canRevertAuditEvent,
  mergeUniqueById,
  reasonCodeLabel,
  relationSnapshotFromAudit,
  requireQualityReason,
} from './quality.js';

const resolvedRelation = {
  id: 'relation-1',
  source_document_id: 'document-new',
  target_document_id: 'document-old',
  status: 'confirmed',
  updated_at: '2026-07-30T10:00:00Z',
};

test('requires a non-blank audit reason and trims it', () => {
  assert.equal(requireQualityReason('  Có đối chiếu chính sách  '), 'Có đối chiếu chính sách');
  assert.throws(
    () => requireQualityReason('   '),
    /Vui lòng nhập lý do/,
  );
  assert.throws(
    () => requireQualityReason('', 'revert'),
    /lý do hoàn tác/,
  );
});

test('appends paginated results without duplicating stable IDs', () => {
  assert.deepEqual(
    mergeUniqueById(
      [{ id: 1, value: 'old' }, { id: 2, value: 'keep' }],
      [{ id: 1, value: 'new' }, { id: 3, value: 'append' }],
    ),
    [
      { id: 1, value: 'new' },
      { id: 2, value: 'keep' },
      { id: 3, value: 'append' },
    ],
  );
});

test('reads both nested and legacy direct relation audit snapshots', () => {
  assert.equal(
    relationSnapshotFromAudit({
      after_state: { relation: resolvedRelation },
      before_state: {},
    }),
    resolvedRelation,
  );
  assert.equal(
    relationSnapshotFromAudit({
      after_state: resolvedRelation,
      before_state: {},
    }),
    resolvedRelation,
  );
});

test('only offers undo for the latest reversible human resolution', () => {
  const event = {
    relation_id: 'relation-1',
    action: 'confirm_conflict',
    before_state: { relation: { ...resolvedRelation, status: 'pending' }, documents: [] },
    after_state: { relation: resolvedRelation, documents: [] },
  };
  assert.equal(canRevertAuditEvent(event, true), true);
  assert.equal(canRevertAuditEvent(event, false), false);
  assert.equal(
    canRevertAuditEvent({ ...event, action: 'auto_confirm_duplicate' }, true),
    false,
  );
  assert.equal(
    canRevertAuditEvent({ ...event, action: 'revert_resolution' }, true),
    false,
  );
});

test('uses Vietnamese labels for structured conflict reason codes', () => {
  assert.equal(reasonCodeLabel('unit_mismatch'), 'Khác đơn vị');
  assert.equal(
    reasonCodeLabel('policy_modality_mismatch'),
    'Khác mức độ bắt buộc của chính sách',
  );
});
