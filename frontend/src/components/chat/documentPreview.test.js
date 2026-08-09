import assert from 'node:assert/strict';
import test from 'node:test';
import {
  buildPdfPreviewUrl,
  getPreviewErrorMessage,
  normalizePdfPageNumber,
} from './documentPreview.js';

test('builds a native PDF viewer URL for the cited page', () => {
  assert.equal(
    buildPdfPreviewUrl('blob:http://localhost/document', 7),
    'blob:http://localhost/document#page=7&view=FitH',
  );
});

test('falls back to the first page for missing or invalid page metadata', () => {
  assert.equal(normalizePdfPageNumber(null), 1);
  assert.equal(normalizePdfPageNumber(0), 1);
  assert.equal(normalizePdfPageNumber('invalid'), 1);
});

test('returns specific user-facing preview errors', () => {
  assert.equal(
    getPreviewErrorMessage({ status: 415 }),
    'Định dạng tài liệu này hiện chưa hỗ trợ xem trước.',
  );
  assert.match(getPreviewErrorMessage({ status: 404 }), /Không tìm thấy tài liệu gốc/);
  assert.match(getPreviewErrorMessage(new Error('network')), /Không thể tải/);
});
