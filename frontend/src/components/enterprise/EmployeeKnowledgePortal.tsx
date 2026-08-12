import { Icon } from "@iconify/react";
import { FormEvent, useEffect, useMemo, useState } from "react";
import ReactMarkdown from "react-markdown";

import {
  AnswerDiagnostics,
  AnswerResponse,
  ConversationMessage,
  EnterpriseCitation,
  EnterpriseApiError,
  KnowledgeDocument,
  SearchHit,
  askEnterpriseQuestion,
  createEnterpriseConversation,
  getDocumentVersionSource,
  getEnterpriseConversation,
  getEnterpriseMe,
  listKnowledgeDocuments,
  reportAnswer,
  searchKnowledge,
  submitAnswerFeedback,
} from "../../lib/enterpriseApi";
import {
  getCurrentEnterpriseConversationId,
  setCurrentEnterpriseConversationId,
} from "../../lib/enterpriseSession.js";
import {
  buildEnterpriseCitationDisplay,
  buildEnterpriseSourcePreviewUrl,
  formatEnterpriseCitationReferences,
  getEnterpriseCitationOrderFromHref,
} from "./enterpriseCitationDisplay.js";

type ChatRow = AnswerDiagnostics & {
  id: string;
  role: "USER" | "ASSISTANT";
  content: string;
  status?: AnswerResponse["answer_status"];
  citations?: EnterpriseCitation[];
  persisted?: boolean;
};

function toChatRow(message: ConversationMessage): ChatRow | null {
  if (message.role === "SYSTEM") return null;
  return {
    id: message.id,
    role: message.role,
    content: message.content,
    status: message.answer_status ?? undefined,
    citations: message.citations || [],
    error_code: message.error_code,
    gate_reason: message.gate_reason,
    candidate_count: message.candidate_count,
    evidence_count: message.evidence_count,
    persisted: true,
  };
}

type DiagnosticKind =
  | "NO_READABLE_DOCUMENTS"
  | "NO_EVIDENCE"
  | "INSUFFICIENT_EVIDENCE"
  | "RETRIEVAL_FAILED"
  | "CITATION_FAILED"
  | "GENERATION_FAILED"
  | "UNKNOWN_FAILED";

const DIAGNOSTIC_PRESENTATION: Record<DiagnosticKind, {
  icon: string;
  title: string;
  description: string;
  className: string;
}> = {
  NO_READABLE_DOCUMENTS: {
    icon: "lucide:shield-x",
    title: "Tài khoản chưa có tài liệu có thể đọc",
    description: "Không có tài liệu đồng thời ở trạng thái đã xuất bản, phiên bản đang hoạt động và có quyền READ. Tệp có thể vẫn tồn tại trong hệ thống; quản trị viên cần kiểm tra trạng thái và phân quyền.",
    className: "border-red/30 bg-red/10 text-red",
  },
  NO_EVIDENCE: {
    icon: "lucide:search-x",
    title: "Retrieval chưa tìm thấy đoạn nội dung phù hợp",
    description: "Truy vấn này không tạo được candidate phù hợp trong phạm vi được phép đọc. Điều này không có nghĩa kho tài liệu đang trống hoặc tệp đã bị mất.",
    className: "border-yellow/30 bg-yellow/10 text-yellow",
  },
  INSUFFICIENT_EVIDENCE: {
    icon: "lucide:circle-help",
    title: "Đã tìm thấy dữ liệu nhưng chưa đủ để kết luận",
    description: "Một hoặc nhiều đoạn nội dung đã qua retrieval, nhưng cổng kiểm soát evidence chưa cho phép hệ thống trả lời chắc chắn.",
    className: "border-yellow/30 bg-yellow/10 text-yellow",
  },
  RETRIEVAL_FAILED: {
    icon: "lucide:database-zap",
    title: "Retrieval gặp lỗi kỹ thuật",
    description: "Hệ thống không hoàn tất được bước tìm kiếm. Đây là lỗi vận hành cần thử lại hoặc kiểm tra trace, không phải kết luận rằng tài liệu không tồn tại.",
    className: "border-red/30 bg-red/10 text-red",
  },
  CITATION_FAILED: {
    icon: "lucide:quote",
    title: "Có evidence nhưng kiểm tra trích dẫn thất bại",
    description: "Retrieval đã có dữ liệu, nhưng câu trả lời sinh ra không vượt qua contract trích dẫn. Nội dung nguồn không bị coi là thiếu.",
    className: "border-red/30 bg-red/10 text-red",
  },
  GENERATION_FAILED: {
    icon: "lucide:bot-off",
    title: "Có lỗi khi tạo câu trả lời",
    description: "Bước sinh câu trả lời không hoàn tất. Hãy thử lại; đây không phải lỗi upload hay bằng chứng rằng tài liệu bị thiếu.",
    className: "border-red/30 bg-red/10 text-red",
  },
  UNKNOWN_FAILED: {
    icon: "lucide:triangle-alert",
    title: "Yêu cầu chưa hoàn tất",
    description: "Hệ thống trả về lỗi chưa được phân loại. Có thể dùng mã lỗi và trace để chẩn đoán mà không quy kết rằng kho tài liệu trống.",
    className: "border-red/30 bg-red/10 text-red",
  },
};

function diagnosticKind(message: ChatRow, hasReadableDocuments: boolean): DiagnosticKind | null {
  if (message.role !== "ASSISTANT" || message.status === "ANSWERED") return null;
  const signal = `${message.error_code || ""} ${message.gate_reason || ""}`.toUpperCase();
  if (
    signal.includes("NO_READABLE")
    || signal.includes("NO_ACCESSIBLE")
    || signal.includes("ACL_DENIED")
    || signal.includes("ACL_NO")
    || (!hasReadableDocuments && (signal.includes("NO_EVIDENCE") || message.status === "INSUFFICIENT_EVIDENCE"))
  ) return "NO_READABLE_DOCUMENTS";
  if (signal.includes("CITATION")) return "CITATION_FAILED";
  if (signal.includes("RETRIEVAL")) return "RETRIEVAL_FAILED";
  if (signal.includes("GENERATION") || signal.includes("LLM_")) return "GENERATION_FAILED";
  if (signal.includes("NO_EVIDENCE") || message.candidate_count === 0) return "NO_EVIDENCE";
  if (signal.includes("INSUFFICIENT") || message.status === "INSUFFICIENT_EVIDENCE") {
    return "INSUFFICIENT_EVIDENCE";
  }
  return message.status === "FAILED" ? "UNKNOWN_FAILED" : null;
}

function AnswerDiagnosticBanner({
  message,
  hasReadableDocuments,
}: {
  message: ChatRow;
  hasReadableDocuments: boolean;
}) {
  const kind = diagnosticKind(message, hasReadableDocuments);
  if (!kind) return null;
  const presentation = DIAGNOSTIC_PRESENTATION[kind];
  return (
    <div className={`mb-3 rounded-xl border px-3 py-3 ${presentation.className}`}>
      <div className="flex items-start gap-2">
        <Icon icon={presentation.icon} width={15} className="mt-0.5 shrink-0" />
        <div>
          <div className="text-xs font-semibold">{presentation.title}</div>
          <p className="mt-1 text-[11px] leading-5 opacity-90">{presentation.description}</p>
        </div>
      </div>
      <div className="mt-2 flex flex-wrap gap-1.5 text-[10px] font-medium opacity-80">
        {message.error_code && <span className="rounded-full border border-current/20 px-2 py-0.5">Mã: {message.error_code}</span>}
        {message.gate_reason && <span className="rounded-full border border-current/20 px-2 py-0.5">Gate: {message.gate_reason}</span>}
        {message.candidate_count !== null && message.candidate_count !== undefined && (
          <span className="rounded-full border border-current/20 px-2 py-0.5">Candidate: {message.candidate_count}</span>
        )}
        {message.evidence_count !== null && message.evidence_count !== undefined && (
          <span className="rounded-full border border-current/20 px-2 py-0.5">Evidence: {message.evidence_count}</span>
        )}
      </div>
    </div>
  );
}

function EnterpriseAnswerContent({
  content,
  citations,
  onSelect,
}: {
  content: string;
  citations: EnterpriseCitation[];
  onSelect: (citation: EnterpriseCitation) => void;
}) {
  const display = useMemo(() => buildEnterpriseCitationDisplay(citations), [citations]);
  const formatted = useMemo(
    () => formatEnterpriseCitationReferences(content, display),
    [content, display],
  );

  return (
    <div className="markdown-body">
      <ReactMarkdown
        components={{
          a({ href, children }) {
            const sourceOrder = getEnterpriseCitationOrderFromHref(href);
            if (sourceOrder) {
              const item = display.bySourceOrder.get(sourceOrder);
              if (!item) return <span className="citation-unavailable">[?]</span>;
              const location = item.citation.page
                ? `trang ${item.citation.page}`
                : item.citation.section || "tài liệu nguồn";
              return (
                <button
                  type="button"
                  className="citation-reference"
                  aria-label={`Mở nguồn ${item.displayNumber}: ${item.citation.document_title}, ${location}`}
                  title={`${item.citation.document_title} · ${location}`}
                  onClick={() => onSelect(item.citation)}
                >
                  [{children}]
                </button>
              );
            }
            return <a href={href}>{children}</a>;
          },
        }}
      >
        {formatted}
      </ReactMarkdown>
    </div>
  );
}

function CitationList({
  citations,
  selectedCitation,
  onSelect,
}: {
  citations: EnterpriseCitation[];
  selectedCitation: EnterpriseCitation | null;
  onSelect: (citation: EnterpriseCitation) => void;
}) {
  if (!citations.length) return null;
  const display = buildEnterpriseCitationDisplay(citations);
  return (
    <div className="mt-4 border-t border-border pt-3">
      <div className="mb-2 text-[11px] font-semibold uppercase tracking-wider text-faint">Nguồn đã kiểm chứng</div>
      <div className="flex flex-wrap gap-2">
        {display.items.map(({ citation, displayNumber }) => (
          <button
            key={citation.chunk_id}
            type="button"
            onClick={() => onSelect(citation)}
            aria-pressed={selectedCitation?.chunk_id === citation.chunk_id}
            className={`inline-flex max-w-full items-center gap-2 rounded-lg border px-3 py-2 text-left text-xs transition-colors ${
              selectedCitation?.chunk_id === citation.chunk_id
                ? "border-accent bg-accent text-accent-foreground shadow-sm"
                : "border-accent/30 bg-accent/10 text-accent hover:bg-accent/15"
            }`}
          >
            <span className={`flex h-5 w-5 shrink-0 items-center justify-center rounded-full text-[10px] font-bold ${
              selectedCitation?.chunk_id === citation.chunk_id
                ? "bg-background/20"
                : "bg-accent text-accent-foreground"
            }`}>
              {displayNumber}
            </span>
            <span className="truncate">{citation.document_title}</span>
            <span className="shrink-0 text-[10px] opacity-70">
              {citation.page ? `tr. ${citation.page}` : citation.section || "nguồn"}
            </span>
          </button>
        ))}
      </div>
    </div>
  );
}

function CitationSourcePanel({
  citation,
  onClose,
  onError,
}: {
  citation: EnterpriseCitation;
  onClose: () => void;
  onError: (message: string) => void;
}) {
  const [sourceUrl, setSourceUrl] = useState("");
  const [mimeType, setMimeType] = useState("");
  const [fileName, setFileName] = useState("");
  const [loading, setLoading] = useState(true);
  const [previewError, setPreviewError] = useState("");

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    setPreviewError("");
    setSourceUrl("");
    void getDocumentVersionSource(citation.document_id, citation.document_version_id)
      .then((source) => {
        if (cancelled) return;
        setMimeType(source.mime_type);
        setFileName(source.original_file_name);
        setSourceUrl(buildEnterpriseSourcePreviewUrl(
          source.signed_url,
          citation.page,
          citation.quote_text,
          source.mime_type,
        ));
      })
      .catch((reason) => {
        if (cancelled) return;
        const message = reason instanceof Error ? reason.message : "Không thể tải tài liệu nguồn";
        setPreviewError(message);
        onError(message);
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => { cancelled = true; };
  }, [citation, onError]);

  const isPdf = mimeType.toLowerCase().includes("pdf");
  const isImage = mimeType.toLowerCase().startsWith("image/");
  const canEmbed = isPdf || isImage || mimeType.toLowerCase().startsWith("text/");

  return (
    <aside className="fixed inset-y-0 right-0 z-50 flex w-[min(92vw,520px)] shrink-0 flex-col border-l border-border bg-panel shadow-2xl xl:relative xl:inset-auto xl:z-auto xl:w-[460px] xl:shadow-none">
      <div className="flex items-start justify-between gap-4 border-b border-border p-4">
        <div className="min-w-0">
          <div className="flex items-center gap-2 text-[10px] font-bold uppercase tracking-[0.16em] text-accent">
            <Icon icon="lucide:quote" width={13} /> Nguồn trích dẫn
          </div>
          <h2 className="mt-1.5 truncate font-heading text-sm font-bold text-foreground" title={citation.document_title}>
            {citation.document_title || fileName || "Tài liệu nguồn"}
          </h2>
          <div className="mt-1 flex flex-wrap items-center gap-2 text-[10px] text-faint">
            {citation.page && <span className="rounded-full border border-border px-2 py-0.5">Trang {citation.page}</span>}
            {citation.section && <span className="truncate">{citation.section}</span>}
          </div>
        </div>
        <button
          type="button"
          onClick={onClose}
          aria-label="Đóng tài liệu nguồn"
          className="rounded-lg border border-border p-2 text-dim hover:bg-inset hover:text-foreground"
        >
          <Icon icon="lucide:x" width={16} />
        </button>
      </div>

      {citation.quote_text && (
        <div className="border-b border-yellow/30 bg-yellow/10 p-4">
          <div className="mb-2 flex items-center gap-1.5 text-[10px] font-bold uppercase tracking-wider text-yellow">
            <Icon icon="lucide:highlighter" width={13} /> Đoạn được dùng để trả lời
          </div>
          <mark className="block max-h-36 overflow-y-auto whitespace-pre-wrap rounded-lg border border-yellow/30 bg-yellow/15 px-3 py-2.5 text-xs leading-5 text-foreground">
            {citation.quote_text}
          </mark>
        </div>
      )}

      <div className="relative min-h-0 flex-1 bg-inset">
        {loading && (
          <div className="absolute inset-0 flex flex-col items-center justify-center gap-3 text-xs text-faint">
            <span className="h-7 w-7 animate-spin rounded-full border-2 border-border border-t-accent" />
            Đang mở đúng trang tài liệu…
          </div>
        )}
        {!loading && previewError && (
          <div className="absolute inset-0 flex flex-col items-center justify-center gap-3 px-8 text-center text-xs leading-5 text-faint">
            <Icon icon="lucide:file-warning" width={28} />
            {previewError}
          </div>
        )}
        {!loading && !previewError && sourceUrl && canEmbed && (
          isImage ? (
            <div className="h-full overflow-auto p-4">
              <img src={sourceUrl} alt={citation.document_title || fileName} className="mx-auto max-w-full rounded-lg bg-white shadow" />
            </div>
          ) : (
            <iframe
              key={sourceUrl}
              src={sourceUrl}
              title={`${citation.document_title} — ${citation.page ? `trang ${citation.page}` : "tài liệu nguồn"}`}
              className="h-full w-full border-0 bg-white"
              sandbox={isPdf ? undefined : ""}
            />
          )
        )}
        {!loading && !previewError && sourceUrl && !canEmbed && (
          <div className="absolute inset-0 flex flex-col items-center justify-center gap-3 px-8 text-center">
            <Icon icon="lucide:file-down" width={34} className="text-accent" />
            <div className="text-sm font-semibold text-foreground">Định dạng này không thể hiển thị trực tiếp</div>
            <p className="text-xs leading-5 text-faint">Đoạn trích đã được tô sáng ở phía trên. Bạn có thể mở file gốc để kiểm tra toàn bộ nội dung.</p>
          </div>
        )}
      </div>

      {sourceUrl && (
        <div className="border-t border-border bg-panel p-3">
          <a
            href={sourceUrl}
            target="_blank"
            rel="noreferrer"
            className="flex w-full items-center justify-center gap-2 rounded-lg border border-accent/30 bg-accent/10 px-3 py-2 text-xs font-semibold text-accent hover:bg-accent/15"
          >
            <Icon icon="lucide:external-link" width={14} />
            Mở tài liệu gốc {citation.page ? `tại trang ${citation.page}` : ""}
          </a>
        </div>
      )}
    </aside>
  );
}

function SearchResult({ hit, onError }: { hit: SearchHit; onError: (message: string) => void }) {
  async function openSource() {
    const target = window.open("", "_blank");
    if (!target) {
      onError("Trình duyệt đã chặn tab tài liệu nguồn. Hãy cho phép popup rồi thử lại.");
      return;
    }
    target.opener = null;
    try {
      const source = await getDocumentVersionSource(hit.document_id, hit.document_version_id);
      const suffix = hit.page_number ? `#page=${hit.page_number}` : "";
      target.location.href = `${source.signed_url}${suffix}`;
    } catch (reason) {
      target.close();
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
  const [hasSearched, setHasSearched] = useState(false);
  const [activeMode, setActiveMode] = useState<"CHAT" | "SEARCH">("CHAT");
  const [conversationId, setConversationId] = useState<string | null>(null);
  const [messages, setMessages] = useState<ChatRow[]>([]);
  const [asking, setAsking] = useState(false);
  const [restoringConversation, setRestoringConversation] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [enterpriseUserId, setEnterpriseUserId] = useState<string | null>(null);
  const [identity, setIdentity] = useState<string>("Nhân viên");
  const [selectedCitation, setSelectedCitation] = useState<EnterpriseCitation | null>(null);

  useEffect(() => {
    let cancelled = false;
    async function restorePortal() {
      try {
        const [me, page] = await Promise.all([
          getEnterpriseMe(),
          listKnowledgeDocuments({ status: "PUBLISHED", limit: 100 }),
        ]);
        if (cancelled) return;
        setIdentity(me.email || me.user_id);
        setEnterpriseUserId(me.user_id);
        setDocuments(page.items);

        const storedConversationId = getCurrentEnterpriseConversationId(me.user_id);
        if (!storedConversationId) return;
        try {
          const conversation = await getEnterpriseConversation(storedConversationId);
          if (cancelled) return;
          setConversationId(conversation.id);
          setMessages(
            (conversation.messages || [])
              .map(toChatRow)
              .filter((message): message is ChatRow => message !== null),
          );
        } catch (reason) {
          if (cancelled) return;
          const unavailable = reason instanceof EnterpriseApiError
            && [403, 404].includes(reason.status);
          if (unavailable) {
            setCurrentEnterpriseConversationId(me.user_id, null);
          } else {
            setError(reason instanceof Error
              ? `Không thể khôi phục cuộc trò chuyện: ${reason.message}`
              : "Không thể khôi phục cuộc trò chuyện hiện tại");
          }
        }
      } catch (reason) {
        if (!cancelled) {
          setError(reason instanceof Error ? reason.message : "Không thể tải kho tri thức");
        }
      } finally {
        if (!cancelled) setRestoringConversation(false);
      }
    }
    void restorePortal();
    return () => { cancelled = true; };
  }, []);

  useEffect(() => {
    if (!enterpriseUserId || restoringConversation || !conversationId) return;
    setCurrentEnterpriseConversationId(enterpriseUserId, conversationId);
  }, [conversationId, enterpriseUserId, restoringConversation]);

  const categories = useMemo(
    () => Array.from(new Set(documents.map((item) => item.category).filter(Boolean))).slice(0, 8),
    [documents],
  );

  async function handleSearch(event: FormEvent) {
    event.preventDefault();
    const normalized = query.trim();
    if (!normalized) return;
    setSearching(true);
    setHasSearched(true);
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
    if (!question || asking || restoringConversation) return;
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
      if (enterpriseUserId) {
        setCurrentEnterpriseConversationId(enterpriseUserId, targetConversation);
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
          error_code: answer.error_code,
          gate_reason: answer.gate_reason,
          candidate_count: answer.candidate_count,
          evidence_count: answer.evidence_count,
          persisted: true,
        },
      ]);
    } catch (reason) {
      const apiError = reason instanceof EnterpriseApiError ? reason : null;
      setMessages((current) => [
        ...current,
        {
          id: crypto.randomUUID(),
          role: "ASSISTANT",
          content: reason instanceof Error ? reason.message : "Không thể trả lời câu hỏi",
          status: "FAILED",
          error_code: apiError?.code || "REQUEST_FAILED",
          gate_reason: apiError?.gateReason,
          candidate_count: apiError?.candidateCount,
          evidence_count: apiError?.evidenceCount,
          persisted: false,
        },
      ]);
    } finally {
      setAsking(false);
    }
  }

  function startNewConversation() {
    if (asking) return;
    if (enterpriseUserId) setCurrentEnterpriseConversationId(enterpriseUserId, null);
    setConversationId(null);
    setMessages([]);
    setQuery("");
    setError(null);
    setSelectedCitation(null);
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
            <div className="flex items-center gap-2">
              {activeMode === "CHAT" && (conversationId || messages.length > 0) && (
                <button
                  type="button"
                  disabled={asking}
                  onClick={startNewConversation}
                  className="inline-flex items-center gap-1.5 rounded-lg border border-border px-3 py-2 text-xs font-semibold text-dim hover:bg-inset hover:text-foreground disabled:opacity-50"
                >
                  <Icon icon="lucide:plus" width={14} /> Hội thoại mới
                </button>
              )}
              <div className="flex rounded-xl border border-border bg-background p-1">
                {(["CHAT", "SEARCH"] as const).map((mode) => (
                  <button
                    key={mode}
                    onClick={() => {
                      setActiveMode(mode);
                      if (mode !== "CHAT") setSelectedCitation(null);
                    }}
                    className={`rounded-lg px-3 py-1.5 text-xs font-semibold ${activeMode === mode ? "bg-accent text-accent-foreground" : "text-dim"}`}
                  >
                    {mode === "CHAT" ? "Hỏi đáp" : "Tìm kiếm"}
                  </button>
                ))}
              </div>
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
                {!searchHits.length && !searching && !hasSearched && (
                  <div className="py-20 text-center">
                    <Icon icon="lucide:files" width={42} className="mx-auto text-faint" />
                    <div className="mt-4 font-heading text-lg font-semibold">Tìm trên các tài liệu được phép</div>
                    <p className="mx-auto mt-2 max-w-lg text-sm leading-6 text-dim">Tìm kiếm sparse áp dụng ACL, trạng thái PUBLISHED và version ACTIVE trước khi xếp hạng. Chế độ hỏi đáp dùng pipeline hybrid có kiểm soát.</p>
                  </div>
                )}
                {!searchHits.length && !searching && hasSearched && (
                  <div className="rounded-2xl border border-yellow/30 bg-yellow/10 px-5 py-6 text-yellow">
                    <div className="flex items-center gap-2 font-heading text-base font-semibold">
                      <Icon icon="lucide:search-x" width={18} /> Chưa có đoạn nội dung khớp truy vấn
                    </div>
                    <p className="mt-2 text-sm leading-6 opacity-90">
                      Tìm kiếm không trả về candidate trong các tài liệu bạn được phép đọc. Kết quả này không khẳng định tệp chưa được upload hoặc kho tài liệu đang trống.
                    </p>
                  </div>
                )}
                {searching && <div className="py-20 text-center text-sm text-faint">Đang tìm kiếm evidence phù hợp...</div>}
                {searchHits.map((hit) => <SearchResult key={hit.chunk_id} hit={hit} onError={setError} />)}
              </div>
            ) : (
              <div className="space-y-5 pb-8">
                {restoringConversation && (
                  <div className="py-16 text-center text-sm text-faint">
                    Đang khôi phục cuộc trò chuyện...
                  </div>
                )}
                {!restoringConversation && !messages.length && (
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
                      <AnswerDiagnosticBanner
                        message={message}
                        hasReadableDocuments={documents.length > 0}
                      />
                      {message.role === "ASSISTANT" ? (
                        <EnterpriseAnswerContent
                          content={message.content}
                          citations={message.citations || []}
                          onSelect={setSelectedCitation}
                        />
                      ) : (
                        <div className="markdown-body"><ReactMarkdown>{message.content}</ReactMarkdown></div>
                      )}
                      {message.role === "ASSISTANT" && (
                        <>
                          <CitationList
                            citations={message.citations || []}
                            selectedCitation={selectedCitation}
                            onSelect={setSelectedCitation}
                          />
                          {message.persisted !== false && <div className="mt-3 flex items-center gap-1 border-t border-border pt-2 text-faint">
                            <button onClick={() => void rate(message.id, "UP")} title="Hữu ích" className="rounded-md p-1.5 hover:bg-inset hover:text-green"><Icon icon="lucide:thumbs-up" width={14} /></button>
                            <button onClick={() => void rate(message.id, "DOWN")} title="Không hữu ích" className="rounded-md p-1.5 hover:bg-inset hover:text-red"><Icon icon="lucide:thumbs-down" width={14} /></button>
                            <button onClick={() => void report(message.id)} title="Báo cáo câu trả lời" className="rounded-md p-1.5 hover:bg-inset hover:text-red"><Icon icon="lucide:flag" width={14} /></button>
                          </div>}
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
            <button disabled={!query.trim() || asking || searching || restoringConversation} className="flex h-12 items-center gap-2 rounded-xl bg-accent px-5 text-sm font-semibold text-accent-foreground">
              <Icon icon="lucide:arrow-up" width={16} />
              <span className="hidden sm:inline">{activeMode === "CHAT" ? "Gửi" : "Tìm"}</span>
            </button>
          </form>
        </div>
      </main>

      {selectedCitation && (
        <>
          <button
            type="button"
            aria-label="Đóng khung tài liệu nguồn"
            onClick={() => setSelectedCitation(null)}
            className="fixed inset-0 z-40 bg-black/35 xl:hidden"
          />
          <CitationSourcePanel
            citation={selectedCitation}
            onClose={() => setSelectedCitation(null)}
            onError={setError}
          />
        </>
      )}
    </div>
  );
}
