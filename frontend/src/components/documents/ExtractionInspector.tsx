import { useMemo, useRef, useState } from "react";
import { Icon } from "@iconify/react";
import { motion } from "motion/react";

import {
  inspectDocumentExtraction,
  type ExtractionChunk,
  type ExtractionInspectionResponse,
  type ExtractionTable,
} from "../../lib/api";

type ResultTab = "content" | "structure" | "tables" | "chunks" | "metadata" | "raw";

const ACCEPTED_EXTENSIONS = ".pdf,.docx,.pptx,.xlsx,.csv,.md,.markdown,.html,.htm,.txt";

function formatBytes(value: number): string {
  if (value < 1024) return `${value} B`;
  if (value < 1024 * 1024) return `${(value / 1024).toFixed(1)} KB`;
  return `${(value / (1024 * 1024)).toFixed(2)} MB`;
}

function asRecord(value: unknown): Record<string, unknown> {
  return typeof value === "object" && value !== null ? value as Record<string, unknown> : {};
}

function JsonPanel({ title, value, defaultOpen = false }: {
  title: string;
  value: unknown;
  defaultOpen?: boolean;
}) {
  return (
    <details open={defaultOpen} className="group overflow-hidden rounded-xl border border-border bg-background">
      <summary className="flex cursor-pointer list-none items-center justify-between px-4 py-3 text-[13px] font-semibold text-foreground hover:bg-inset">
        <span>{title}</span>
        <Icon icon="lucide:chevron-down" width={15} className="text-faint transition-transform group-open:rotate-180" />
      </summary>
      <pre className="max-h-[460px] overflow-auto border-t border-border bg-inset p-4 text-[11.5px] leading-5 text-dim">
        {JSON.stringify(value, null, 2)}
      </pre>
    </details>
  );
}

function MetricCard({ icon, label, value, note }: {
  icon: string;
  label: string;
  value: string | number;
  note?: string;
}) {
  return (
    <div className="rounded-xl border border-border bg-panel p-3.5">
      <div className="mb-2 flex items-center gap-2 text-faint">
        <Icon icon={icon} width={14} />
        <span className="text-[11px] font-semibold uppercase tracking-[0.1em]">{label}</span>
      </div>
      <div className="font-heading text-xl font-bold text-foreground">{value}</div>
      {note && <div className="mt-1 truncate text-[11px] text-faint">{note}</div>}
    </div>
  );
}

function EmptyResult({ onPick }: { onPick: () => void }) {
  return (
    <div className="mx-auto flex min-h-[calc(100vh-12rem)] max-w-3xl items-center justify-center px-6 py-12">
      <div className="relative w-full overflow-hidden rounded-3xl border border-border bg-panel px-8 py-14 text-center shadow-sm">
        <div className="pointer-events-none absolute -right-20 -top-24 h-64 w-64 rounded-full bg-accent/10 blur-3xl" />
        <div className="pointer-events-none absolute -bottom-28 -left-12 h-56 w-56 rounded-full bg-blue/10 blur-3xl" />
        <div className="relative">
          <div className="mx-auto mb-5 flex h-16 w-16 items-center justify-center rounded-2xl border border-accent/30 bg-accent/10 text-accent">
            <Icon icon="lucide:scan-text" width={30} />
          </div>
          <h2 className="font-heading text-2xl font-bold text-foreground">Kiểm tra đầu ra trích xuất</h2>
          <p className="mx-auto mt-3 max-w-xl text-sm leading-6 text-dim">
            Chọn một file để xem chính xác parser lấy được nội dung, bảng, cấu trúc trang,
            quality gate và metadata như thế nào.
          </p>
          <button
            onClick={onPick}
            className="mt-7 inline-flex h-11 items-center gap-2 rounded-xl bg-accent px-5 text-sm font-semibold text-accent-foreground hover:bg-accent-dim"
          >
            <Icon icon="lucide:upload" width={16} />
            Chọn file để kiểm tra
          </button>
          <div className="mt-5 flex flex-wrap items-center justify-center gap-x-4 gap-y-2 text-[11.5px] text-faint">
            <span>PDF · DOCX · PPTX · XLSX · CSV · Markdown · HTML · TXT</span>
            <span className="hidden h-3 w-px bg-border sm:block" />
            <span>Tối đa 10 MB</span>
          </div>
          <div className="mx-auto mt-7 flex max-w-md items-start gap-2 rounded-xl border border-green/25 bg-green/5 px-3.5 py-3 text-left text-[11.5px] leading-5 text-dim">
            <Icon icon="lucide:shield-check" width={15} className="mt-0.5 shrink-0 text-green" />
            File chỉ được xử lý trong bộ nhớ để kiểm tra; không lưu vào notebook và không tạo embedding.
          </div>
        </div>
      </div>
    </div>
  );
}

function TableView({ table, index }: { table: ExtractionTable; index: number }) {
  return (
    <section className="overflow-hidden rounded-xl border border-border bg-background">
      <div className="flex flex-wrap items-center justify-between gap-2 border-b border-border bg-inset px-4 py-3">
        <div>
          <div className="text-[13px] font-semibold text-foreground">Bảng {index + 1}</div>
          <div className="mt-0.5 text-[11px] text-faint">{table.table_id} · {table.location}</div>
        </div>
        <div className="flex items-center gap-2 text-[11px] text-dim">
          <span className="rounded-full border border-border bg-background px-2 py-1">{table.rows.length} hàng</span>
          <span className="rounded-full border border-border bg-background px-2 py-1">{table.columns} cột</span>
          {table.confidence != null && (
            <span className="rounded-full border border-green/30 bg-green/5 px-2 py-1 text-green">
              {(table.confidence * 100).toFixed(0)}%
            </span>
          )}
        </div>
      </div>
      <div className="overflow-x-auto">
        <table className="w-full min-w-max border-collapse text-left text-[12px]">
          <tbody>
            {table.rows.map((row, rowIndex) => (
              <tr key={rowIndex} className={rowIndex === 0 ? "bg-accent/5" : "hover:bg-inset/60"}>
                <td className="w-10 border-b border-r border-border px-2 py-2 text-center text-[10px] text-faint">{rowIndex + 1}</td>
                {Array.from({ length: table.columns }, (_, columnIndex) => (
                  <td
                    key={columnIndex}
                    className={`max-w-sm border-b border-border px-3 py-2.5 align-top ${rowIndex === 0 ? "font-semibold text-foreground" : "text-dim"}`}
                  >
                    {row[columnIndex] ?? ""}
                  </td>
                ))}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      {table.warnings.length > 0 && (
        <div className="border-t border-yellow/20 bg-yellow/5 px-4 py-2.5 text-[11.5px] text-yellow">
          {table.warnings.join(" · ")}
        </div>
      )}
    </section>
  );
}

function ChunkView({ chunk }: { chunk: ExtractionChunk }) {
  const [representation, setRepresentation] = useState<"text" | "embedding_text" | "search_text">("text");
  const retrievalEntries = Object.entries(chunk.retrieval_metadata);

  return (
    <article className="overflow-hidden rounded-xl border border-border bg-background">
      <div className="flex flex-col gap-3 border-b border-border bg-inset px-4 py-3 sm:flex-row sm:items-center sm:justify-between">
        <div className="flex min-w-0 items-center gap-3">
          <span className="flex h-8 min-w-8 items-center justify-center rounded-lg bg-accent text-xs font-bold text-accent-foreground">
            {chunk.chunk_index + 1}
          </span>
          <div className="min-w-0">
            <div className="flex flex-wrap items-center gap-2 text-[12.5px] font-semibold text-foreground">
              Chunk {chunk.chunk_index}
              {chunk.table_identity && <span className="rounded bg-blue/10 px-1.5 py-0.5 text-[9.5px] text-blue">TABLE ATOMIC</span>}
            </div>
            <div className="mono mt-0.5 truncate text-[9.5px] text-faint">{chunk.chunk_id}</div>
          </div>
        </div>
        <div className="flex flex-wrap gap-1.5 text-[10.5px] text-dim">
          <span className="rounded-full border border-border bg-background px-2 py-1">Trang {chunk.page_number ?? "—"}</span>
          <span className="rounded-full border border-border bg-background px-2 py-1">{chunk.estimated_token_count} từ</span>
          <span className="rounded-full border border-border bg-background px-2 py-1">{chunk.character_count} ký tự</span>
          <span className="rounded-full border border-border bg-background px-2 py-1">offset {chunk.offset_start}–{chunk.offset_end}</span>
        </div>
      </div>

      <div className="p-4">
        <div className="mb-3 flex flex-col gap-2 sm:flex-row sm:items-center sm:justify-between">
          <div className="min-w-0 text-[11px] text-faint">
            <span className="font-semibold text-dim">Section:</span> {chunk.section_title || "Không xác định"}
          </div>
          <div className="flex w-fit rounded-lg border border-border bg-inset p-0.5">
            {([
              ["text", "Text"],
              ["embedding_text", "Embedding"],
              ["search_text", "Search"],
            ] as const).map(([value, label]) => (
              <button
                key={value}
                onClick={() => setRepresentation(value)}
                className={`rounded-md px-2.5 py-1 text-[10.5px] font-semibold ${representation === value ? "bg-accent text-accent-foreground" : "text-faint hover:text-foreground"}`}
              >
                {label}
              </button>
            ))}
          </div>
        </div>

        <pre className="max-h-72 overflow-auto whitespace-pre-wrap rounded-lg border border-border bg-panel p-3.5 text-[11.5px] leading-5 text-dim">
          {chunk[representation]}
        </pre>

        <div className="mt-3 grid gap-3 lg:grid-cols-[minmax(0,1fr)_auto]">
          <div>
            <div className="mb-1.5 text-[10px] font-semibold uppercase tracking-[0.1em] text-faint">Metadata nghiệp vụ dùng cho retrieval</div>
            <div className="flex min-h-8 flex-wrap gap-1.5">
              {retrievalEntries.map(([key, value]) => (
                <span key={key} className="rounded-md border border-green/20 bg-green/5 px-2 py-1 text-[10.5px] text-dim">
                  <strong className="font-semibold text-green">{key}</strong>: {Array.isArray(value) ? value.join(", ") : String(value)}
                </span>
              ))}
              {retrievalEntries.length === 0 && <span className="text-[11px] text-faint">Chunk này chưa có metadata nghiệp vụ.</span>}
            </div>
          </div>
          <div className="flex items-end">
            <details className="relative">
              <summary className="cursor-pointer list-none rounded-lg border border-border bg-panel px-3 py-2 text-[10.5px] font-semibold text-dim hover:bg-inset">Metadata kỹ thuật</summary>
              <div className="mt-2 max-h-72 overflow-auto rounded-lg border border-border bg-inset p-3 lg:absolute lg:right-0 lg:z-10 lg:w-[520px]">
                <pre className="text-[9.5px] leading-4 text-dim">{JSON.stringify({
                  strategy: chunk.strategy,
                  strategy_version: chunk.strategy_version,
                  checksum: chunk.checksum,
                  source_block_ids: chunk.source_block_ids,
                  table_identity: chunk.table_identity,
                  metadata: chunk.metadata,
                }, null, 2)}</pre>
              </div>
            </details>
          </div>
        </div>
      </div>
    </article>
  );
}

export default function ExtractionInspector() {
  const inputRef = useRef<HTMLInputElement>(null);
  const [file, setFile] = useState<File | null>(null);
  const [result, setResult] = useState<ExtractionInspectionResponse | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [tab, setTab] = useState<ResultTab>("content");
  const [contentMode, setContentMode] = useState<"markdown" | "text">("markdown");
  const [copied, setCopied] = useState(false);

  const metrics = useMemo(() => asRecord(result?.quality_report.metrics), [result]);

  async function runInspection(selected: File) {
    setFile(selected);
    setLoading(true);
    setError(null);
    setResult(null);
    try {
      const payload = await inspectDocumentExtraction(selected);
      setResult(payload);
      setTab("content");
    } catch (inspectionError) {
      setError(inspectionError instanceof Error ? inspectionError.message : "Không thể kiểm tra file.");
    } finally {
      setLoading(false);
    }
  }

  function handleSelection(files: FileList | File[]) {
    const selected = Array.from(files)[0];
    if (selected) void runInspection(selected);
  }

  async function copyJson() {
    if (!result) return;
    await navigator.clipboard.writeText(JSON.stringify(result, null, 2));
    setCopied(true);
    window.setTimeout(() => setCopied(false), 1600);
  }

  function downloadJson() {
    if (!result) return;
    const blob = new Blob([JSON.stringify(result, null, 2)], { type: "application/json" });
    const url = URL.createObjectURL(blob);
    const anchor = document.createElement("a");
    anchor.href = url;
    anchor.download = `${result.source.filename}.extraction.json`;
    anchor.click();
    URL.revokeObjectURL(url);
  }

  const tabs: Array<[ResultTab, string, string, number | null]> = [
    ["content", "Nội dung", "lucide:file-text", null],
    ["structure", "Cấu trúc", "lucide:blocks", result?.summary.page_count ?? null],
    ["tables", "Bảng", "lucide:table-2", result?.summary.table_count ?? null],
    ["chunks", "Chunks", "lucide:scissors-line-dashed", result?.summary.chunk_count ?? null],
    ["metadata", "Metadata", "lucide:braces", null],
    ["raw", "Raw JSON", "lucide:code-xml", null],
  ];

  return (
    <main className="flex-1 overflow-y-auto bg-background">
      <input
        ref={inputRef}
        type="file"
        accept={ACCEPTED_EXTENSIONS}
        className="hidden"
        onChange={(event) => {
          if (event.target.files) handleSelection(event.target.files);
          event.target.value = "";
        }}
      />

      <div className="border-b border-border bg-panel px-5 py-4 sm:px-8">
        <div className="mx-auto flex max-w-[1500px] items-center justify-between gap-4">
          <div>
            <div className="flex items-center gap-2 text-[11px] font-semibold uppercase tracking-[0.14em] text-accent">
              <Icon icon="lucide:microscope" width={13} /> Extraction lab
            </div>
            <h1 className="mt-1 font-heading text-xl font-bold text-foreground">Extraction Inspector</h1>
          </div>
          <button
            onClick={() => inputRef.current?.click()}
            disabled={loading}
            className="flex h-9 items-center gap-2 rounded-lg border border-border bg-background px-3.5 text-[12.5px] font-semibold text-foreground hover:bg-inset"
          >
            <Icon icon={result ? "lucide:refresh-cw" : "lucide:upload"} width={14} className={loading ? "animate-spin" : ""} />
            {result ? "Kiểm tra file khác" : "Chọn file"}
          </button>
        </div>
      </div>

      {!file && !result && !loading && <EmptyResult onPick={() => inputRef.current?.click()} />}

      {(loading || error) && (
        <div className="mx-auto max-w-3xl px-6 py-16">
          {loading ? (
            <div className="rounded-2xl border border-border bg-panel p-8 text-center">
              <div className="mx-auto mb-4 flex h-12 w-12 items-center justify-center rounded-xl bg-accent/10 text-accent">
                <Icon icon="lucide:loader-circle" width={24} className="animate-spin" />
              </div>
              <div className="font-heading text-lg font-semibold text-foreground">Đang phân tích {file?.name}</div>
              <div className="mt-2 text-sm text-dim">Parser → Quality gate → Canonical IR → Layout → Tables</div>
            </div>
          ) : (
            <div className="rounded-2xl border border-red/30 bg-red/5 p-6">
              <div className="flex gap-3">
                <Icon icon="lucide:circle-alert" width={20} className="mt-0.5 shrink-0 text-red" />
                <div className="flex-1">
                  <div className="font-semibold text-red">Không thể trích xuất file</div>
                  <div className="mt-1 text-sm leading-6 text-dim">{error}</div>
                  <button onClick={() => inputRef.current?.click()} className="mt-4 rounded-lg bg-red px-3.5 py-2 text-xs font-semibold text-white">Chọn file khác</button>
                </div>
              </div>
            </div>
          )}
        </div>
      )}

      {result && !loading && (
        <motion.div initial={{ opacity: 0, y: 8 }} animate={{ opacity: 1, y: 0 }} className="mx-auto max-w-[1500px] px-5 py-6 sm:px-8">
          <section className="mb-4 flex flex-col gap-4 rounded-2xl border border-border bg-panel p-4 lg:flex-row lg:items-center lg:justify-between">
            <div className="flex min-w-0 items-center gap-3">
              <div className="flex h-11 w-11 shrink-0 items-center justify-center rounded-xl bg-accent/10 text-accent"><Icon icon="lucide:file-check-2" width={22} /></div>
              <div className="min-w-0">
                <div className="truncate text-sm font-semibold text-foreground">{result.source.filename}</div>
                <div className="mt-1 flex flex-wrap items-center gap-x-3 gap-y-1 text-[11.5px] text-faint">
                  <span>{formatBytes(result.source.size_bytes)}</span><span>{result.source.mime_type}</span><span className="mono">SHA-256 {result.source.checksum.slice(0, 12)}…</span>
                </div>
              </div>
            </div>
            <div className="flex flex-wrap items-center gap-2">
              <span className={`rounded-full border px-2.5 py-1 text-[11.5px] font-semibold ${result.summary.index_allowed ? "border-green/30 bg-green/10 text-green" : "border-red/30 bg-red/10 text-red"}`}>{result.summary.index_allowed ? "Cho phép index" : "Chặn index"}</span>
              <span className="rounded-full border border-border bg-background px-2.5 py-1 text-[11.5px] text-dim">{result.summary.quality_action}</span>
              <span className="rounded-full border border-border bg-background px-2.5 py-1 text-[11.5px] text-dim">{result.summary.parser_name} {result.summary.parser_version}</span>
            </div>
          </section>

          <section className="mb-5 grid grid-cols-2 gap-3 md:grid-cols-4 xl:grid-cols-7">
            <MetricCard icon="lucide:gauge" label="Chất lượng" value={result.summary.quality_status} note={`Confidence ${String(metrics.confidence_score ?? "—")}`} />
            <MetricCard icon="lucide:files" label="Số trang" value={result.summary.page_count} />
            <MetricCard icon="lucide:blocks" label="Phần tử" value={result.summary.element_count} note={`${result.summary.section_count} sections`} />
            <MetricCard icon="lucide:table-2" label="Bảng" value={result.summary.table_count} />
            <MetricCard icon="lucide:type" label="Ký tự" value={result.summary.text_characters.toLocaleString("vi-VN")} />
            <MetricCard icon="lucide:scissors-line-dashed" label="Chunks" value={result.summary.chunk_count} note={`${result.chunking.chunk_size}/${result.chunking.chunk_overlap} size/overlap`} />
            <MetricCard icon="lucide:languages" label="Ngôn ngữ" value={result.summary.detected_language.toUpperCase()} note={result.summary.ocr_used ? "Có sử dụng OCR" : "Không sử dụng OCR"} />
          </section>

          <section className="overflow-hidden rounded-2xl border border-border bg-panel">
            <div className="overflow-x-auto border-b border-border px-2 sm:px-4">
              <div className="flex min-w-max">
                {tabs.map(([id, label, icon, count]) => (
                  <button key={id} onClick={() => setTab(id)} className={`relative flex h-12 items-center gap-2 px-3 text-[12.5px] font-medium transition-colors ${tab === id ? "text-accent" : "text-faint hover:text-foreground"}`}>
                    <Icon icon={icon} width={14} />{label}
                    {count != null && <span className="rounded-full bg-inset px-1.5 py-0.5 text-[10px] text-dim">{count}</span>}
                    {tab === id && <motion.div layoutId="extract-tab" className="absolute inset-x-2 bottom-0 h-0.5 bg-accent" />}
                  </button>
                ))}
              </div>
            </div>

            <div className="min-h-[460px] p-4 sm:p-5">
              {tab === "content" && (
                <div>
                  <div className="mb-3 flex items-center justify-between gap-3">
                    <div><h2 className="text-sm font-semibold text-foreground">Nội dung đã chuẩn hóa</h2><p className="mt-0.5 text-[11.5px] text-faint">So sánh representation Markdown và text phẳng.</p></div>
                    <div className="flex rounded-lg border border-border bg-background p-0.5">
                      {(["markdown", "text"] as const).map((mode) => <button key={mode} onClick={() => setContentMode(mode)} className={`rounded-md px-3 py-1.5 text-[11px] font-semibold ${contentMode === mode ? "bg-accent text-accent-foreground" : "text-faint"}`}>{mode === "markdown" ? "Markdown" : "Text"}</button>)}
                    </div>
                  </div>
                  <pre className="max-h-[650px] min-h-[380px] overflow-auto whitespace-pre-wrap rounded-xl border border-border bg-background p-5 text-[12.5px] leading-6 text-dim">{result.content[contentMode] || "Không có nội dung văn bản."}</pre>
                </div>
              )}

              {tab === "structure" && (
                <div className="grid gap-4 xl:grid-cols-[340px_minmax(0,1fr)]">
                  <div>
                    <h2 className="mb-3 text-sm font-semibold text-foreground">Sections ({result.parsed_document.sections.length})</h2>
                    <div className="space-y-2">
                      {result.parsed_document.sections.map((section, index) => <div key={index} className="rounded-xl border border-border bg-background p-3"><div className="flex items-center justify-between gap-2"><span className="truncate text-[12px] font-semibold text-foreground">{section.title || `Section ${index + 1}`}</span><span className="shrink-0 text-[10px] text-faint">Trang {section.page_number ?? "—"} · L{section.level}</span></div><p className="mt-2 line-clamp-3 text-[11.5px] leading-5 text-dim">{section.text}</p></div>)}
                      {result.parsed_document.sections.length === 0 && <div className="rounded-xl border border-dashed border-border p-5 text-center text-xs text-faint">Không phát hiện section.</div>}
                    </div>
                  </div>
                  <div>
                    <h2 className="mb-3 text-sm font-semibold text-foreground">Pages & elements ({result.parsed_document.pages.length})</h2>
                    <div className="space-y-3">
                      {result.parsed_document.pages.map((page) => <details key={page.page_number} className="group overflow-hidden rounded-xl border border-border bg-background" open={result.parsed_document.pages.length === 1}><summary className="flex cursor-pointer list-none items-center justify-between gap-4 bg-inset px-4 py-3"><div className="flex items-center gap-2"><Icon icon="lucide:file" width={14} className="text-accent" /><span className="text-[12.5px] font-semibold text-foreground">Trang {page.page_number}</span></div><span className="text-[10.5px] text-faint">{page.elements.length} elements · rotation {page.rotation}°</span></summary><div className="divide-y divide-border">{page.elements.length > 0 ? page.elements.map((element) => <div key={element.element_id} className="grid gap-2 px-4 py-3 sm:grid-cols-[120px_minmax(0,1fr)]"><div><span className="rounded-md bg-accent/10 px-2 py-1 text-[10px] font-semibold text-accent">{element.block_type}</span><div className="mono mt-2 truncate text-[9.5px] text-faint">{element.element_id}</div></div><p className="whitespace-pre-wrap text-[11.5px] leading-5 text-dim">{element.text}</p></div>) : <p className="px-4 py-5 text-xs text-faint">Parser không tạo element riêng cho trang này.</p>}</div></details>)}
                    </div>
                  </div>
                </div>
              )}

              {tab === "tables" && (
                <div>
                  <div className="mb-4"><h2 className="text-sm font-semibold text-foreground">Bảng được parser trích xuất</h2><p className="mt-0.5 text-[11.5px] text-faint">Hiển thị đúng ma trận hàng/cột trước khi tạo structured facts.</p></div>
                  <div className="space-y-4">
                    {result.parsed_document.tables.map((table, index) => <TableView key={table.table_id} table={table} index={index} />)}
                    {result.parsed_document.tables.length === 0 && <div className="flex min-h-[320px] flex-col items-center justify-center rounded-xl border border-dashed border-border bg-background text-center"><Icon icon="lucide:table-properties" width={30} className="mb-3 text-faint" /><div className="text-sm font-semibold text-foreground">Không phát hiện bảng</div><div className="mt-1 text-xs text-faint">`table_count` bằng 0 trong kết quả parser.</div></div>}
                  </div>
                </div>
              )}

              {tab === "chunks" && (
                <div>
                  <div className="mb-4 flex flex-col gap-3 rounded-xl border border-border bg-background p-4 sm:flex-row sm:items-center sm:justify-between">
                    <div>
                      <h2 className="text-sm font-semibold text-foreground">Chunks trước embedding</h2>
                      <p className="mt-1 text-[11.5px] leading-5 text-faint">{result.chunking.note}</p>
                    </div>
                    <div className="flex flex-wrap gap-2 text-[10.5px] text-dim">
                      <span className="rounded-full border border-border bg-inset px-2.5 py-1">{result.chunking.strategy}</span>
                      <span className="rounded-full border border-border bg-inset px-2.5 py-1">size {result.chunking.chunk_size}</span>
                      <span className="rounded-full border border-border bg-inset px-2.5 py-1">overlap {result.chunking.chunk_overlap}</span>
                      <span className={`rounded-full border px-2.5 py-1 ${result.chunking.status === "generated" ? "border-green/25 bg-green/5 text-green" : "border-red/25 bg-red/5 text-red"}`}>{result.chunking.status}</span>
                    </div>
                  </div>
                  {result.chunking.production_contextual_enrichment_enabled && !result.chunking.contextual_enrichment_applied && (
                    <div className="mb-4 flex items-start gap-2 rounded-xl border border-yellow/25 bg-yellow/5 px-4 py-3 text-[11.5px] leading-5 text-dim">
                      <Icon icon="lucide:triangle-alert" width={15} className="mt-0.5 shrink-0 text-yellow" />
                      Production có bật contextual enrichment, nhưng Inspector không gọi LLM để tránh phát sinh chi phí. Vì vậy embedding/search text ở đây là bản trước enrichment.
                    </div>
                  )}
                  <div className="space-y-4">
                    {result.chunks.map((chunk) => <ChunkView key={chunk.chunk_id} chunk={chunk} />)}
                    {result.chunks.length === 0 && (
                      <div className="flex min-h-[300px] flex-col items-center justify-center rounded-xl border border-dashed border-border bg-background text-center">
                        <Icon icon="lucide:shield-x" width={30} className="mb-3 text-faint" />
                        <div className="text-sm font-semibold text-foreground">Không có chunk để index</div>
                        <div className="mt-1 max-w-md text-xs leading-5 text-faint">{result.chunking.status === "blocked_by_quality" ? "Quality gate đã chặn tài liệu. Hãy xem Quality decision để biết nguyên nhân." : "Nội dung trích xuất không tạo được chunk."}</div>
                      </div>
                    )}
                  </div>
                </div>
              )}

              {tab === "metadata" && <div className="grid gap-3 lg:grid-cols-2"><JsonPanel title="Quality report" value={result.quality_report} defaultOpen /><JsonPanel title="Quality decision" value={result.quality_decision} defaultOpen /><JsonPanel title="Document metadata" value={result.parsed_document.document_metadata} /><JsonPanel title="Canonical IR validation" value={result.canonical_ir_validation} /><JsonPanel title="Phase 3–6 metadata" value={result.phases} /><JsonPanel title="Adaptive routing / OCR" value={result.adaptive_routing} /><JsonPanel title="Canonical IR artifact" value={result.canonical_ir_artifact} /><JsonPanel title="Canonical IR v2" value={result.canonical_ir} /></div>}

              {tab === "raw" && (
                <div>
                  <div className="mb-3 flex flex-wrap items-center justify-between gap-3"><div><h2 className="text-sm font-semibold text-foreground">Response JSON đầy đủ</h2><p className="mt-0.5 text-[11.5px] text-faint">Payload trả về trực tiếp từ endpoint inspection.</p></div><div className="flex gap-2"><button onClick={() => void copyJson()} className="flex items-center gap-1.5 rounded-lg border border-border bg-background px-3 py-2 text-[11.5px] font-semibold text-dim hover:bg-inset"><Icon icon={copied ? "lucide:check" : "lucide:copy"} width={13} />{copied ? "Đã sao chép" : "Sao chép"}</button><button onClick={downloadJson} className="flex items-center gap-1.5 rounded-lg bg-accent px-3 py-2 text-[11.5px] font-semibold text-accent-foreground hover:bg-accent-dim"><Icon icon="lucide:download" width={13} />Tải JSON</button></div></div>
                  <pre className="max-h-[680px] overflow-auto rounded-xl border border-border bg-background p-5 text-[11.5px] leading-5 text-dim">{JSON.stringify(result, null, 2)}</pre>
                </div>
              )}
            </div>
          </section>
        </motion.div>
      )}
    </main>
  );
}
