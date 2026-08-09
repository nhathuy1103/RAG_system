import assert from 'node:assert/strict';
import { afterEach, beforeEach, describe, it } from 'node:test';

import { useChatStore } from './chatStore.js';

describe('chatStore', () => {
  const originalFetch = globalThis.fetch;

  beforeEach(() => {
    useChatStore.setState({
      messages: [],
      conversationId: null,
      isStreaming: false,
      error: null,
      activeController: null,
    });
  });

  afterEach(() => {
    globalThis.fetch = originalFetch;
  });

  it('forwards notebook scope when no documents are selected', async () => {
    const calls = [];
    globalThis.fetch = async (...args) => {
      calls.push(args);
      return {
        ok: true,
        body: new ReadableStream({
          start(controller) {
            controller.enqueue(
              new TextEncoder().encode('event: done\ndata: {}\n\n')
            );
            controller.close();
          },
        }),
      };
    };

    await useChatStore.getState().sendMessage('Question', 'notebook-1', null);

    assert.equal(calls.length, 1);
    const [, options] = calls[0];
    assert.deepEqual(JSON.parse(options.body), {
      question: 'Question',
      notebook_id: 'notebook-1',
      document_ids: null,
      conversation_id: null,
    });
  });
});
