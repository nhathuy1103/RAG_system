import assert from 'node:assert/strict';
import { beforeEach, describe, it } from 'node:test';

import { useToastStore } from './toastStore.js';

describe('toastStore', () => {
  beforeEach(() => {
    useToastStore.setState({ toast: null });
  });

  it('shows success notifications by default', () => {
    useToastStore.getState().showToast('Đã cập nhật sổ tay.');

    assert.deepEqual(
      {
        message: useToastStore.getState().toast.message,
        severity: useToastStore.getState().toast.severity,
      },
      {
        message: 'Đã cập nhật sổ tay.',
        severity: 'success',
      },
    );
  });

  it('supports error notifications and closing the toast', () => {
    useToastStore.getState().showToast('Không thể xoá tài liệu.', 'error');
    assert.equal(useToastStore.getState().toast.severity, 'error');

    useToastStore.getState().hideToast();
    assert.equal(useToastStore.getState().toast, null);
  });
});
