import React, { useState, useRef, useEffect } from 'react';
import { motion, AnimatePresence } from 'motion/react';
import { Icon } from '@iconify/react';
import { useChatStore } from '../../stores/chatStore.js';
import { useDocumentStore } from '../../stores/documentStore.js';
import { useNotebookStore } from '../../stores/notebookStore.js';
import MarkdownMessage from './MarkdownMessage.jsx';

function ChatMessage({ msg, notebookId }) {
  const isAI = msg.role === 'assistant' || msg.role === 'ai';

  if (!isAI) {
    return (
      <motion.div
        initial={{ opacity: 0, y: 8 }}
        animate={{ opacity: 1, y: 0 }}
        exit={{ opacity: 0 }}
        transition={{ duration: 0.22, ease: 'easeOut' }}
        className="mb-5 flex justify-end"
      >
        <div className="max-w-[70%] rounded-tl-2xl rounded-tr-2xl rounded-bl-2xl rounded-br-md bg-accent px-4 py-3 text-sm leading-relaxed text-accent-foreground">
          {msg.content}
        </div>
      </motion.div>
    );
  }

  return (
    <motion.div
      initial={{ opacity: 0, y: 8 }}
      animate={{ opacity: 1, y: 0 }}
      exit={{ opacity: 0 }}
      transition={{ duration: 0.22, ease: 'easeOut' }}
      className="mb-6 flex items-start gap-3"
    >
      <div className="mt-0.5 flex h-8 w-8 shrink-0 items-center justify-center rounded-full bg-accent text-accent-foreground">
        <Icon icon="lucide:sparkle" width={15} height={15} />
      </div>
      <div className="flex-1">
        <div className="rounded-tl-md rounded-tr-2xl rounded-bl-2xl rounded-br-2xl border border-border bg-inset px-4 py-3.5 text-[13.5px] leading-relaxed text-foreground">
          <MarkdownMessage
            content={msg.content}
            citations={msg.citations}
            notebookId={notebookId}
          />
          {msg.isStreaming && (
            <span className="pulse-glow ml-2 inline-block h-4 w-2 rounded-sm bg-accent align-middle" />
          )}
        </div>
      </div>
    </motion.div>
  );
}

function TypingIndicator() {
  return (
    <motion.div
      initial={{ opacity: 0, y: 8 }}
      animate={{ opacity: 1, y: 0 }}
      exit={{ opacity: 0, y: 8 }}
      transition={{ duration: 0.18, ease: 'easeOut' }}
      className="mb-6 flex items-start gap-3"
    >
      <div className="flex h-8 w-8 shrink-0 items-center justify-center rounded-full bg-accent text-accent-foreground">
        <Icon icon="lucide:sparkle" width={15} height={15} />
      </div>
      <div className="flex items-center gap-1.5 rounded-tl-md rounded-tr-2xl rounded-bl-2xl rounded-br-2xl border border-border bg-inset px-5 py-4">
        {[0, 1, 2].map((i) => (
          <div
            key={i}
            className="h-[7px] w-[7px] rounded-full bg-faint"
            style={{ animation: 'chat-bounce 1.2s ease-in-out infinite', animationDelay: `${i * 0.2}s` }}
          />
        ))}
      </div>
      <style>{`
        @keyframes chat-bounce {
          0%, 60%, 100% { transform: translateY(0); opacity: 0.5; }
          30% { transform: translateY(-6px); opacity: 1; }
        }
      `}</style>
    </motion.div>
  );
}

const SUGGESTED_PROMPTS = [
  "Tóm tắt các ý chính trong tài liệu này",
  "Nêu ra các con số và dữ liệu quan trọng",
  "So sánh các quan điểm được nêu trong bài",
];

export default function ChatPanel() {
  const { messages, isStreaming, sendMessage, stopStreaming, clearChat } = useChatStore();
  const { selectedDocumentIds, documents } = useDocumentStore();
  const { activeNotebook } = useNotebookStore();
  const [question, setQuestion] = useState('');
  const messagesEndRef = useRef(null);
  const textareaRef = useRef(null);

  const scrollToBottom = () => {
    messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' });
  };

  useEffect(() => {
    scrollToBottom();
  }, [messages, isStreaming]);

  const handleSend = () => {
    if (!question.trim() || isStreaming || !activeNotebook) return;
    const q = question;
    setQuestion('');
    const docIds = selectedDocumentIds.length > 0 ? selectedDocumentIds : null;
    sendMessage(q, activeNotebook.id, docIds);
  };

  return (
    <div className="flex flex-1 flex-col overflow-hidden bg-background">
      <div className="flex shrink-0 items-center justify-between border-b border-border bg-panel px-6 py-3.5">
        <div>
          <div className="flex items-center gap-1.5 font-heading text-sm font-bold text-foreground">
            <div className="h-2 w-2 rounded-full bg-green" />
            Hỏi đáp RAG Notebook
          </div>
          <div className="mt-0.5 text-xs text-faint">
            Trả lời dựa trên {selectedDocumentIds.length > 0 ? selectedDocumentIds.length : documents.length} nguồn
          </div>
        </div>
        <div className="flex items-center gap-1.5">
          {messages.length > 0 && (
            <button
              onClick={clearChat}
              className="rounded-full border border-red/40 bg-red/10 px-2.5 py-1 text-[11.5px] font-medium text-red"
            >
              Xóa hội thoại
            </button>
          )}
          <div className="rounded-full border border-accent/40 bg-accent/10 px-2.5 py-1 text-[11.5px] font-medium text-accent">
            Streaming
          </div>
        </div>
      </div>

      <div className="flex-1 overflow-y-auto px-7 pb-4 pt-7">
        {messages.length === 0 && !isStreaming && (
          <div className="flex h-full flex-col items-center justify-center text-center">
            <div className="mb-4 flex h-14 w-14 items-center justify-center rounded-full bg-accent/15 text-accent">
              <Icon icon="lucide:sparkle" width={15} height={15} />
            </div>
            <div className="mb-1.5 font-heading text-lg font-bold text-foreground">Hỏi bất cứ điều gì</div>
            <div className="max-w-[340px] text-sm leading-relaxed text-dim">
              Câu trả lời sẽ luôn được trích dẫn trực tiếp từ tài liệu trong sổ tay này.
            </div>
          </div>
        )}
        <AnimatePresence initial={false}>
          {messages.map((msg) => (
            <ChatMessage key={msg.id} msg={msg} notebookId={activeNotebook?.id} />
          ))}
          {isStreaming && messages.length > 0 && messages[messages.length - 1].role === 'user' && (
            <TypingIndicator key="typing-indicator" />
          )}
        </AnimatePresence>
        <div ref={messagesEndRef} />
      </div>

      {messages.length === 0 && (
        <div className="flex flex-wrap gap-2 px-7 pb-3">
          {SUGGESTED_PROMPTS.map((p, i) => (
            <button
              key={i}
              onClick={() => setQuestion(p)}
              className="rounded-full border border-border bg-panel px-3.5 py-1.5 text-[12.5px] font-medium text-accent hover:border-accent/40 hover:bg-accent/10"
            >
              {p}
            </button>
          ))}
        </div>
      )}

      <div className="shrink-0 border-t border-border bg-panel px-6 py-5">
        <div className="flex items-end gap-2.5 rounded-2xl border border-border bg-inset px-3 py-2.5 focus-within:border-accent">
          <textarea
            ref={textareaRef}
            value={question}
            onChange={(e) => setQuestion(e.target.value)}
            onKeyDown={(e) => { if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); handleSend(); } }}
            disabled={!activeNotebook}
            placeholder={!activeNotebook ? 'Vui lòng chọn hoặc tạo sổ tay trước khi hỏi...' : 'Hỏi bất cứ điều gì về nguồn của bạn…'}
            rows={1}
            className="max-h-[140px] flex-1 resize-none overflow-y-auto border-none bg-transparent text-sm leading-relaxed text-foreground outline-none placeholder:text-faint"
          />
          <button
            onClick={isStreaming ? stopStreaming : handleSend}
            disabled={!activeNotebook && !isStreaming}
            className={`flex h-9 w-9 shrink-0 items-center justify-center rounded-lg transition-colors ${
              isStreaming
                ? 'bg-red/10 text-red'
                : question.trim() && activeNotebook
                  ? 'bg-accent text-accent-foreground hover:bg-accent-dim'
                  : 'bg-border text-faint'
            } ${!activeNotebook && !isStreaming ? 'cursor-not-allowed' : 'cursor-pointer'}`}
          >
            {isStreaming ? (
              <Icon icon="ph:stop-fill" width={14} height={14} />
            ) : (
              <Icon icon="lucide:send" width={18} height={18} />
            )}
          </button>
        </div>
        <div className="mt-1.5 text-center text-[11px] text-faint">
          Nhấn Enter để gửi · Shift+Enter để xuống dòng · Câu trả lời luôn trích dẫn nguồn
        </div>
      </div>
    </div>
  );
}
