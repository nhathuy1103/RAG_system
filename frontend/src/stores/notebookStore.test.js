import assert from 'node:assert/strict';
import { afterEach, beforeEach, describe, it } from 'node:test';

import { useNotebookStore } from './notebookStore.js';

describe('notebookStore', () => {
  const originalFetch = globalThis.fetch;

  beforeEach(() => {
    useNotebookStore.setState({
      notebooks: [],
      activeNotebook: null,
      loading: false,
      error: null,
    });
  });

  afterEach(() => {
    globalThis.fetch = originalFetch;
  });

  it('uses the array returned by GET /notebooks', async () => {
    const notebooks = [
      { id: 'notebook-1', title: 'First' },
      { id: 'notebook-2', title: 'Second' },
    ];
    globalThis.fetch = async () => ({
      ok: true,
      headers: { get: () => 'application/json' },
      json: async () => notebooks,
    });

    const result = await useNotebookStore.getState().fetchNotebooks();

    assert.deepEqual(result, notebooks);
    assert.deepEqual(useNotebookStore.getState().notebooks, notebooks);
    assert.deepEqual(useNotebookStore.getState().activeNotebook, notebooks[0]);
  });
});
