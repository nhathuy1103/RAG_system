import { create } from 'zustand';
import * as chatApi from '../lib/api';

export const useChatStore = create((set, get) => ({
  messages: [],
  conversationId: null,
  isStreaming: false,
  error: null,
  activeController: null,

  sendMessage: async (question, notebookId, documentIds = null) => {
    // Add user message immediately
    const userMsg = {
      id: `user-${Date.now()}`,
      role: 'user',
      content: question,
      timestamp: new Date().toISOString(),
    };
    const aiMsgId = `ai-${Date.now()}`;
    const aiMsg = {
      id: aiMsgId,
      role: 'assistant',
      content: '',
      citations: [],
      isStreaming: true,
      timestamp: new Date().toISOString(),
    };

    set((state) => ({
      messages: [...state.messages, userMsg, aiMsg],
      isStreaming: true,
      error: null,
    }));

    const controller = new AbortController();
    set({ activeController: controller });

    try {
      await chatApi.streamMessage(question, documentIds, notebookId, get().conversationId, {
        signal: controller.signal,
        onConversationId: (conversationId) => {
          set({ conversationId });
        },
        onToken: (token) => {
          set((state) => ({
            messages: state.messages.map((msg) =>
              msg.id === aiMsgId ? { ...msg, content: msg.content + token } : msg
            ),
          }));
        },
        onCitation: (citation) => {
          set((state) => ({
            messages: state.messages.map((msg) =>
              msg.id === aiMsgId
                ? {
                    ...msg,
                    citations: [
                      ...msg.citations.filter((c) => c.source_id !== citation.source_id),
                      citation,
                    ],
                  }
                : msg
            ),
          }));
        },
        onDone: () => {
          set((state) => ({
            messages: state.messages.map((msg) =>
              msg.id === aiMsgId ? { ...msg, isStreaming: false } : msg
            ),
            isStreaming: false,
            activeController: null,
          }));
        },
        onError: (errMsg) => {
          set((state) => ({
            messages: state.messages.map((msg) =>
              msg.id === aiMsgId
                ? {
                    ...msg,
                    isStreaming: false,
                    content: msg.content || `⚠️ Lỗi: ${errMsg}`,
                  }
                : msg
            ),
            isStreaming: false,
            error: errMsg,
            activeController: null,
          }));
        },
      });
    } catch (err) {
      if (err.name !== 'AbortError') {
        set({ error: err.message, isStreaming: false, activeController: null });
      }
    }
  },

  stopStreaming: () => {
    const { activeController } = get();
    if (activeController) {
      activeController.abort();
      set((state) => ({
        isStreaming: false,
        activeController: null,
        messages: state.messages.map((msg) =>
          msg.isStreaming ? { ...msg, isStreaming: false } : msg
        ),
      }));
    }
  },

  clearChat: () => {
    get().stopStreaming();
    set({ messages: [], conversationId: null, error: null });
  },
}));
