import { Icon } from "@iconify/react";
import { FormEvent, useEffect, useMemo, useState } from "react";
import ReactMarkdown from "react-markdown";

import {
  AnswerResponse,
  EnterpriseCitation,
  KnowledgeDocument,
  SearchHit,
  askEnterpriseQuestion,
  createEnterpriseConversation,
  getDocumentVersionSource,
  getEnterpriseMe,
  listKnowledgeDocuments,
  reportAnswer,
  searchKnowledge,
  submitAnswerFeedback,
} from "../../lib/enterpriseApi";

type ChatRow = {
  id: string;
  role: "USER" | "ASSISTANT";
  content: string;
  status?: AnswerResponse["answer_status"];
  citations?: EnterpriseCitation[];
};

function CitationList({ citations, onError }: { citations: EnterpriseCitation[]; onError: (message: string) => void }) {
  if (!citations.length) return null;
  async function openSource(citation: EnterpriseCitation) {
    const target = window.open("", "_blank", "noopener,noreferrer");
    try {
      const source = await getDocumentVersionSource(citation.document_id, citation.document_version_id);
      const suffix = citation.page ? `#page=${citation.page}` : "";
      if (target) target.location.href = `${source.signed_url}${suffix}`;
      else window.location.assign(`${source.signed_url}${suffix}`);
    } catch (reason) {
      target?.close();
      onError(reason instanceof Error ? reason.message : "Không thể mở tài liệu nguồn");
    }
  }
  return (
    <div className="mt-4 border-t border-border pt-3">
      <div className="mb-2 text-[11px] font-semibold uppercase tracking-wider text-faint">Nguồn đã kiểm chứng</div>
      <div className="flex flex-wrap gap-2">
        {citations.map((citation, index) => (
          <button
            key={`${citation.chunk_id}-${index}`}
            onClick={() => void openSource(citation)}
            className="inline-flex max-w-full items-center gap-2 rounded-lg border border-accent/30 bg-accent/10 px-3 py-2 text-left text-xs text-accent hover:bg-accent/15"
          >
            <Icon icon="lucide:file-check-2" width={14} />
            <span className="truncate">[{index + 1}] {citation.document_title}</span>
            <span className="shrink-0 text-[10px] opacity-70">
              {citation.page ? `tr. ${citation.page}` : citation.section || "nguồn"}
            </span>
          </button>
        ))}
      </div>
    </div>
  );
}

function SearchResult({ hit, onError }: { hit: SearchHit; onError: (message: string) => void }) {
  async function openSource() {
    const target = window.open("", "_blank", "noopener,noreferrer");
    try {
      const source = await getDocumentVersionSource(hit.document_id, hit.document_version_id);
      const suffix = hit.page_number ? `#page=${hit.page_number}` : "";
      if (target) target.location.href = `${source.signed_url}${suffix}`;
      else window.location.assign(`${source.signed_url}${suffix}`);
    } catch (reason) {
      target?.close();
      onError(reason instanceof Error ? reason.message : "Không thể mở tài liệu nguồn");
    }
  }

  return (
    <article className="rounded-2xl border border-border bg-panel p-5">
      <div className="mb-2 flex items-start justify-between gap-4">
        <div>
          <div className="font-heading text-sm font-semibold text-foreground">{hit.document_title}</div>
          <div className="mt-1 text-[11px] text-faint">
            {hit.section_title || "Không xác định mục"}{hit.page_number ? ` · Trang ${hit.page_number}` : ""}
          </div>
        </div>
        <div className="rounded-full bg-green/10 px-2 py-1 text-[10px] font-semibold text-green">
          {(hit.score * 100).toFixed(0)}%
        </div>
      </div>
      <p className="text-[13px] leading-6 text-dim">{hit.excerpt}</p>
      <button onClick={() => void openSource()} className="mt-3 inline-flex items-center gap-1.5 rounded-lg border border-border px-3 py-1.5 text-[11px] font-semibold text-dim hover:bg-inset hover:text-foreground">
        <Icon icon="lucide:external-link" width={13} /> Mở tài liệu nguồn
      </button>
    </article>
  );
}

export default function EmployeeKnowledgePortal() {
  const [documents, setDocuments] = useState<KnowledgeDocument[]>([]);
  const [query, setQuery] = useState("");
  const [searchHits, setSearchHits] = useState<SearchHit[]>([]);
  const [searching, setSearching] = useState(false);
  const [activeMode, setActiveMode] = useState<"CHAT" | "SEARCH">("CHAT");
  const [conversationId, setConversationId] = useState<string | null>(null);
  const [messages, setMessages] = useState<ChatRow[]>([]);
  const [asking, setAsking] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [identity, setIdentity] = useState<string>("Nhân viên");

  useEffect(() => {
    let cancelled = false;
    Promise.all([getEnterpriseMe(), listKnowledgeDocuments({ status: "PUBLISHED", limit: 100 })])
      .then(([me, page]) => {
        if (cancelled) return;
        setIdentity(me.email || me.user_id);
        setDocuments(page.items);
      })
      .catch((reason: unknown) => {
        if (!cancelled) setError(reason instanceof Error ? reason.message : "Không thể tải kho tri thức");
      });
    return () => { cancelled = true; };
  }, []);

  const categories = useMemo(
    () => Array.from(new Set(documents.map((item) => item.category).filter(Boolean))).slice(0, 8),
    [documents],
  );

  async function handleSearch(event: FormEvent) {
    event.preventDefault();
    const normalized = query.trim();
    if (!normalized) return;
    setSearching(true);
    setError(null);
    try {
      const response = await searchKnowledge(normalized);
      setSearchHits(response.hits);
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "Không thể tìm kiếm");
    } finally {
      setSearching(false);
    }
  }

  async function handleAsk(event: FormEvent) {
    event.preventDefault();
    const question = query.trim();
    if (!question || asking) return;
    setAsking(true);
    setError(null);
    setQuery("");
    const userRow: ChatRow = { id: crypto.randomUUID(), role: "USER", content: question };
    setMessages((current) => [...current, userRow]);
    try {
      let targetConversation = conversationId;
      if (!targetConversation) {
        const created = await createEnterpriseConversation(question.slice(0, 120));
        targetConversation = created.id;
        setConversationId(created.id);
      }
      const answer = await askEnterpriseQuestion(targetConversation, question);
      setMessages((current) => [
        ...current,
        {
          id: answer.message_id,
          role: "ASSISTANT",
          content: answer.answer,
          status: answer.answer_status,
          citations: answer.citations,
        },
      ]);
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "Không thể trả lời câu hỏi");
    } finally {
      setAsking(false);
    }
  }

  async function rate(messageId: string, rating: "UP" | "DOWN") {
    try {
      await submitAnswerFeedback(messageId, rating);
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "Không thể gửi đánh giá");
    }
  }

  async function report(messageId: string) {
    try {
      await reportAnswer(messageId, "INCORRECT", "Employee reported the answer from the knowledge portal");
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "Không thể gửi báo cáo");
    }
  }

  return (
    <div className="flex min-h-0 flex-1 bg-background">
      <aside className="hidden w-72 shrink-0 overflow-y-auto border-r border-border bg-panel p-5 lg:block">
        <div className="mb-6">
          <div className="text-[10px] font-semibold uppercase tracking-[0.18em] text-accent">Enterprise Knowledge</div>
          <h1 className="mt-2 font-heading text-xl font-bold text-foreground">Kho tri thức nội bộ</h1>
          <p className="mt-2 text-xs leading-5 text-dim">Chỉ hiển thị tài liệu đã xuất bản mà {identity} được cấp quyền.</p>
        </div>
        <div className="mb-5 grid grid-cols-2 gap-2">
          <div className="rounded-xl border border-border bg-background p-3">
            <div className="font-heading text-xl font-bold text-foreground">{documents.length}</div>
            <div className="text-[10px] text-faint">Tài liệu khả dụng</div>
          </div>
          <div className="rounded-xl border border-border bg-background p-3">
            <div className="font-heading text-xl font-bold text-foreground">{categories.length}</div>
            <div className="text-[10px] text-faint">Danh mục</div>
          </div>
        </div>
        <div className="text-[11px] font-semibold uppercase tracking-wider text-faint">Danh mục</div>
        <div className="mt-3 flex flex-wrap gap-2">
          {categories.length ? categories.map((category) => (
            <span key={category} className="rounded-full border border-border bg-background px-2.5 py-1 text-[11px] text-dim">{category}</span>
          )) : <span className="text-xs text-faint">Chưa có metadata danh mục</span>}
        </div>
        <div className="mt-7 text-[11px] font-semibold uppercase tracking-wider text-faint">Tài liệu gần đây</div>
        <div className="mt-2 space-y-1">
          {documents.slice(0, 8).map((document) => (
            <div key={document.id} className="rounded-lg px-2 py-2 text-xs text-dim hover:bg-inset">
              <div className="truncate font-medium text-foreground">{document.title}</div>
              <div className="mt-0.5 truncate text-[10px] text-faint">{document.document_type || "Tài liệu nội bộ"}</div>
            </div>
          ))}
        </div>
      </aside>

      <main className="flex min-w-0 flex-1 flex-col">
        <div className="border-b border-border bg-panel px-5 py-4 sm:px-8">
          <div className="mx-auto flex max-w-5xl items-center justify-between gap-4">
            <div>
              <div className="font-heading text-lg font-bold text-foreground">Tra cứu tri thức doanh nghiệp</div>
              <div className="mt-0.5 text-xs text-faint">Câu trả lời được kiểm soát bằng quyền và luôn truy ngược tới version nguồn.</div>
            </div>
            <div className="flex rounded-xl border border-border bg-background p-1">
              {(["CHAT", "SEARCH"] as const).map((mode) => (
                <button
                  key={mode}
                  onClick={() => setActiveMode(mode)}
                  className={`rounded-lg px-3 py-1.5 text-xs font-semibold ${activeMode === mode ? "bg-accent text-accent-foreground" : "text-dim"}`}
                >
                  {mode === "CHAT" ? "Hỏi đáp" : "Tìm kiếm"}
                </button>
              ))}
            </div>
          </div>
        </div>

        <div className="min-h-0 flex-1 overflow-y-auto px-5 py-6 sm:px-8">
          <div className="mx-auto max-w-5xl">
            {error && (
              <div className="mb-5 flex items-start gap-2 rounded-xl border border-red/30 bg-red/10 px-4 py-3 text-sm text-red">
                <Icon icon="lucide:shield-alert" width={17} className="mt-0.5 shrink-0" />
                <span>{error}</span>
              </div>
            )}

            {activeMode === "SEARCH" ? (
              <div className="space-y-4">
                {!searchHits.length && !searching && (
                  <div className="py-20 text-center">
                    <Icon icon="lucide:files" width={42} className="mx-auto text-faint" />
                    <div className="mt-4 font-heading text-lg font-semibold">Tìm trên các tài liệu được phép</div>
                    <p className="mx-auto mt-2 max-w-lg text-sm leading-6 text-dim">Tìm kiếm sparse áp dụng ACL, trạng thái PUBLISHED và version ACTIVE trước khi xếp hạng. Chế độ hỏi đáp dùng pipeline hybrid có kiểm soát.</p>
                  </div>
                )}
                {searching && <div className="py-20 text-center text-sm text-faint">Đang tìm kiếm evidence phù hợp...</div>}
                {searchHits.map((hit) => <SearchResult key={hit.chunk_id} hit={hit} onError={setError} />)}
              </div>
            ) : (
              <div className="space-y-5 pb-8">
                {!messages.length && (
                  <div className="py-16 text-center">
                    <div className="mx-auto flex h-14 w-14 items-center justify-center rounded-2xl bg-accent text-accent-foreground">
                      <Icon icon="lucide:sparkles" width={24} />
                    </div>
                    <h2 className="mt-5 font-heading text-2xl font-bold">Bạn muốn biết điều gì?</h2>
                    <p className="mx-auto mt-2 max-w-xl text-sm leading-6 text-dim">Hệ thống sẽ từ chối trả lời nếu không tìm thấy đủ evidence đáng tin cậy trong phạm vi bạn được truy cập.</p>
                  </div>
                )}
                {messages.map((message) => (
                  <div key={message.id} className={`flex ${message.role === "USER" ? "justify-end" : "justify-start"}`}>
                    <article className={`max-w-3xl rounded-2xl px-5 py-4 ${message.role === "USER" ? "bg-accent text-accent-foreground" : "border border-border bg-panel text-foreground"}`}>
                      {message.status === "INSUFFICIENT_EVIDENCE" && (
                        <div className="mb-3 inline-flex items-center gap-1.5 rounded-full border border-yellow/30 bg-yellow/10 px-2.5 py-1 text-[10px] font-semibold text-yellow">
                          <Icon icon="lucide:circle-help" width={12} /> Không đủ evidence
                        </div>
                      )}
                      <div className="markdown-body"><ReactMarkdown>{message.content}</ReactMarkdown></div>
                      {message.role === "ASSISTANT" && (
                        <>
                          <CitationList citations={message.citations || []} onError={setError} />
                          <div className="mt-3 flex items-center gap-1 border-t border-border pt-2 text-faint">
                            <button onClick={() => void rate(message.id, "UP")} title="Hữu ích" className="rounded-md p-1.5 hover:bg-inset hover:text-green"><Icon icon="lucide:thumbs-up" width={14} /></button>
                            <button onClick={() => void rate(message.id, "DOWN")} title="Không hữu ích" className="rounded-md p-1.5 hover:bg-inset hover:text-red"><Icon icon="lucide:thumbs-down" width={14} /></button>
                            <button onClick={() => void report(message.id)} title="Báo cáo câu trả lời" className="rounded-md p-1.5 hover:bg-inset hover:text-red"><Icon icon="lucide:flag" width={14} /></button>
                          </div>
                        </>
                      )}
                    </article>
                  </div>
                ))}
                {asking && <div className="text-sm text-faint">Đang kiểm tra quyền và tổng hợp evidence...</div>}
              </div>
            )}
          </div>
        </div>

        <div className="border-t border-border bg-panel px-5 py-4 sm:px-8">
          <form onSubmit={activeMode === "CHAT" ? handleAsk : handleSearch} className="mx-auto flex max-w-5xl gap-3">
            <div className="relative flex-1">
              <Icon icon={activeMode === "CHAT" ? "lucide:message-square" : "lucide:search"} width={17} className="absolute left-4 top-1/2 -translate-y-1/2 text-faint" />
              <input
                value={query}
                onChange={(event) => setQuery(event.target.value)}
                maxLength={4000}
                placeholder={activeMode === "CHAT" ? "Đặt câu hỏi về tri thức nội bộ..." : "Tìm tài liệu, quy định hoặc chính sách..."}
                className="h-12 w-full rounded-xl border border-border bg-background pl-11 pr-4 text-sm text-foreground outline-none focus:border-accent"
              />
            </div>
            <button disabled={!query.trim() || asking || searching} className="flex h-12 items-center gap-2 rounded-xl bg-accent px-5 text-sm font-semibold text-accent-foreground">
              <Icon icon="lucide:arrow-up" width={16} />
              <span className="hidden sm:inline">{activeMode === "CHAT" ? "Gửi" : "Tìm"}</span>
            </button>
          </form>
        </div>
      </main>
    </div>
  );
}
