import { useEffect, useMemo, useState } from "react";
import { Icon } from "@iconify/react";
import {
  Bar,
  BarChart,
  CartesianGrid,
  Cell,
  Legend,
  Pie,
  PieChart,
  ReferenceLine,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";

import {
  benchmarkLimitations,
  benchmarkProfile,
  benchmarkSlices,
  benchmarkTargets,
  contextStatus,
  documentQuality,
  extendedFieldStudyRows,
  filterFieldAblationOverall,
  filterFieldAblationRows,
  metadataChannels,
  metadataCoverage,
  metadataFieldRows,
  metadataProjectionExample,
  modeMetrics,
  pairedComparisons,
  preRetrievalFieldCandidates,
  preRetrievalGates,
  qualityDecisions,
  qualityScores,
  queryStyles,
  queryTypeDeltas,
  recommendedPayloadSchema,
  reportMeta,
  testMethodSteps,
  trustChecks,
} from "../../data/contextQualityReportV4";
import MetadataStudyDetailedReport from "./MetadataStudyDetailedReport";
import MetadataStudyPresentation from "./MetadataStudyPresentation";

type TabId = "overview" | "slides" | "detailed" | "testset" | "metadata" | "queries" | "quality" | "analysis";

type AnalysisNote = {
  id: string;
  title: string;
  body: string;
  createdAt: string;
  updatedAt: string;
};

const NOTES_STORAGE_KEY = "context-quality-v4-analysis-notes";

const tabs: Array<{ id: TabId; label: string; icon: string }> = [
  { id: "overview", label: "Đọc nhanh", icon: "lucide:layout-dashboard" },
  { id: "slides", label: "Trình chiếu", icon: "lucide:presentation" },
  { id: "detailed", label: "Báo cáo chi tiết", icon: "lucide:file-text" },
  { id: "testset", label: "Bộ test", icon: "lucide:badge-check" },
  { id: "metadata", label: "Metadata", icon: "lucide:brackets" },
  { id: "queries", label: "Theo truy vấn", icon: "lucide:table-properties" },
  { id: "quality", label: "Chất lượng context", icon: "lucide:scan-search" },
  { id: "analysis", label: "Phân tích", icon: "lucide:notebook-pen" },
];

const modeColors: Record<string, string> = {
  A: "var(--faint)",
  B: "var(--blue)",
  "C-dense": "var(--yellow)",
  "C-sparse": "var(--green)",
  C: "var(--accent)",
  D: "#7a5aa6",
  E: "var(--red)",
};

function formatPercent(value: number) {
  return `${value.toLocaleString("vi-VN", { minimumFractionDigits: 2, maximumFractionDigits: 2 })}%`;
}

function formatDate(value: string) {
  return new Intl.DateTimeFormat("vi-VN", {
    dateStyle: "medium",
    timeStyle: "short",
  }).format(new Date(value));
}

function ChartTooltip({ active, payload, label }: any) {
  if (!active || !payload?.length) return null;
  return (
    <div className="rounded-md border border-border bg-panel px-3 py-2 shadow-lg">
      <div className="mb-1.5 text-xs font-semibold text-foreground">{label}</div>
      {payload.map((item: any) => (
        <div key={item.dataKey} className="flex min-w-40 items-center justify-between gap-5 text-[11px]">
          <span className="flex items-center gap-1.5 text-dim">
            <span className="h-2 w-2 rounded-sm" style={{ background: item.color }} />
            {item.name}
          </span>
          <strong className="text-foreground">{formatPercent(Number(item.value))}</strong>
        </div>
      ))}
    </div>
  );
}

function PieTooltip({ active, payload }: any) {
  if (!active || !payload?.length) return null;
  const item = payload[0]?.payload as { name: string; value: number; percentage: number } | undefined;
  if (!item) return null;
  return (
    <div className="rounded-md border border-border bg-panel px-3 py-2 text-xs shadow-lg">
      <div className="font-semibold text-foreground">{item.name}</div>
      <div className="mt-1 text-dim">{item.value} chunk · {formatPercent(item.percentage)}</div>
    </div>
  );
}

function KpiCard({ icon, label, value, detail, tone = "blue" }: { icon: string; label: string; value: string; detail: string; tone?: "blue" | "green" | "yellow" | "red" }) {
  return (
    <article className="report-kpi">
      <div className={`report-kpi-icon report-tone-${tone}`}>
        <Icon icon={icon} width={17} height={17} />
      </div>
      <div className="min-w-0">
        <div className="text-[11px] font-semibold uppercase text-faint">{label}</div>
        <div className="mt-1 font-heading text-[25px] font-semibold text-foreground">{value}</div>
        <div className="mt-1 text-xs leading-5 text-dim">{detail}</div>
      </div>
    </article>
  );
}

function VerdictStrip() {
  return (
    <div className="report-verdict-grid">
      <div className="report-verdict border-blue/40">
        <Icon icon="lucide:shield-check" width={18} className="text-blue" />
        <div>
          <div className="text-[11px] font-semibold uppercase text-faint">Production mặc định</div>
          <div className="mt-1 text-sm font-semibold text-foreground">B · Chunk + tiêu đề cấu trúc</div>
          <p className="mt-1 text-xs leading-5 text-dim">Baseline ổn định, Recall@5 96,47% và Recall@10 100%.</p>
        </div>
      </div>
      <div className="report-verdict border-green/40">
        <Icon icon="lucide:flask-conical" width={18} className="text-green" />
        <div>
          <div className="text-[11px] font-semibold uppercase text-faint">Ứng viên canary</div>
          <div className="mt-1 text-sm font-semibold text-foreground">C-sparse · Summary chỉ vào tìm từ khóa</div>
          <p className="mt-1 text-xs leading-5 text-dim">Metric nhỉnh hơn B nhưng CI chạm 0; cần A/B ngoài mẫu.</p>
        </div>
      </div>
      <div className="report-verdict border-[#7a5aa6]/40">
        <Icon icon="lucide:chart-no-axes-combined" width={18} className="text-[#7a5aa6]" />
        <div>
          <div className="text-[11px] font-semibold uppercase text-faint">Mốc trần chẩn đoán</div>
          <div className="mt-1 text-sm font-semibold text-foreground">D · Summary chuẩn tham chiếu</div>
          <p className="mt-1 text-xs leading-5 text-dim">Đứng đầu về MRR/NDCG, nhưng không phải mode production.</p>
        </div>
      </div>
    </div>
  );
}

function ExecutiveExplanation() {
  return (
    <section className="report-executive">
      <div className="report-executive-decision">
        <div className="report-decision-icon"><Icon icon="lucide:circle-pause" width={22} /></div>
        <div>
          <div className="text-[11px] font-semibold uppercase text-red">Quyết định đề xuất</div>
          <h2>Chưa bật contextual summary cho cả dense và sparse</h2>
          <p>Phiên bản v4 đã tốt hơn v3, nhưng cấu hình full context vẫn tìm đúng ít hơn cấu hình header hiện tại. Lợi ích chưa đủ để đánh đổi rủi ro xếp hạng sai.</p>
        </div>
      </div>

      <div className="report-answer-counts">
        <div><span>Hệ thống hiện tại · B</span><strong>246 / 255</strong><p>câu có tài liệu đúng trong 5 kết quả đầu</p></div>
        <div className="is-worse"><span>Bật full context · C</span><strong>243 / 255</strong><p>ít hơn hiện tại 3 câu</p></div>
        <div className="is-candidate"><span>Chỉ thêm vào BM25 · C-sparse</span><strong>248 / 255</strong><p>nhiều hơn 2 câu, nhưng bằng chứng còn ít</p></div>
      </div>

      <div className="report-story-grid">
        <article>
          <span className="report-story-number">01</span>
          <div><h3>V4 có tiến bộ, không phải thất bại</h3><p>Raw context tăng từ 233 câu đúng ở v3 lên 243 câu ở v4. Khoảng cách với B giảm từ 13 câu xuống còn 3 câu.</p></div>
        </article>
        <article>
          <span className="report-story-number">02</span>
          <div><h3>Nhưng full context chưa tạo lợi ích ròng</h3><p>So với B, C giúp 3 câu, không đổi 246 câu và làm kém 6 câu. Tổng cộng hệ thống mất ròng 3 câu.</p></div>
        </article>
        <article>
          <span className="report-story-number">03</span>
          <div><h3>Sparse-only đáng thử, chưa đáng triển khai</h3><p>C-sparse giúp thêm 2 câu và không làm mất câu nào trong mẫu này. Tuy nhiên, chỉ 2/255 câu thay đổi nên chưa đủ bằng chứng thống kê.</p></div>
        </article>
      </div>

      <div className="report-business-questions">
        <div><strong>Context có vô dụng không?</strong><p>Không. Context đúng thắng context bị xáo trộn 16 câu và chỉ thua 4 câu. Vấn đề là header B đã cung cấp phần lớn ngữ cảnh cần thiết.</p></div>
        <div><strong>Tại sao chưa nên bật?</strong><p>Khoảng một nửa summary được sinh vẫn cần theo dõi, sinh lại hoặc reject; một số lỗi gán sai dự án còn lọt qua audit.</p></div>
        <div><strong>Bước tiếp theo là gì?</strong><p>Giữ B, thử C-sparse trên canary và chỉ index summary vượt entity-binding cùng quality gate.</p></div>
      </div>
    </section>
  );
}

function MetricGlossary() {
  return (
    <details className="report-glossary">
      <summary><Icon icon="lucide:book-open" width={15} />Các thuật ngữ trong báo cáo có nghĩa gì?</summary>
      <div className="report-glossary-grid">
        <div><strong>Recall@5</strong><p>Trong các câu có đáp án, tỷ lệ tìm thấy tài liệu đúng trong 5 kết quả đầu. Đây là metric chính để biết hệ thống có “tìm ra” hay không.</p></div>
        <div><strong>MRR@10</strong><p>Đo tài liệu đúng xuất hiện sớm đến đâu. Cùng tìm đúng, kết quả ở vị trí 1 tốt hơn vị trí 5.</p></div>
        <div><strong>NDCG@10</strong><p>Đo chất lượng toàn bộ thứ tự top 10, có xét mức độ liên quan của từng kết quả.</p></div>
        <div><strong>CI 95%</strong><p>Khoảng bất định của delta. Nếu khoảng này cắt qua 0, chưa thể khẳng định cấu hình mới thực sự tốt hơn hoặc kém hơn.</p></div>
        <div><strong>p-value</strong><p>Mức độ kết quả có thể xuất hiện do ngẫu nhiên. Thông thường cần nhỏ hơn 0,05 để coi là bằng chứng rõ.</p></div>
        <div><strong>W / T / L</strong><p>Số truy vấn cấu hình mới thắng, hòa hoặc thua cấu hình so sánh trực tiếp.</p></div>
      </div>
    </details>
  );
}

function ModeLegend() {
  return (
    <aside className="report-mode-legend" aria-label="Chú giải các mode retrieval">
      <div className="report-mode-legend-title">Cấu hình kiểm thử</div>
      <div role="list">
        {modeMetrics.map((mode) => (
          <div key={mode.id} className="report-mode-legend-row" role="listitem" title={mode.explanation}>
            <span
              className="report-mode-legend-dot"
              style={{ background: modeColors[mode.shortLabel] }}
              aria-hidden="true"
            />
            <strong>{mode.shortLabel}</strong>
            <span className="report-mode-legend-copy"><span>{mode.label}</span><small>{mode.explanation}</small></span>
          </div>
        ))}
      </div>
    </aside>
  );
}

function OverviewTab() {
  const chartData = modeMetrics.map((mode) => ({
    name: mode.shortLabel,
    "Recall@5": mode.recall5,
    "MRR@10": mode.mrr10,
    "NDCG@10": mode.ndcg10,
  }));

  return (
    <div className="space-y-8">
      <ExecutiveExplanation />
      <VerdictStrip />

      <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-4">
        <KpiCard icon="lucide:target" label="Baseline Recall@5" value="96,47%" detail="B tăng 31,76 điểm % so với chunk-only" tone="blue" />
        <KpiCard icon="lucide:list-plus" label="Ứng viên raw tốt nhất" value="97,25%" detail="C-sparse, chưa có ý nghĩa thống kê" tone="green" />
        <KpiCard icon="lucide:route" label="Multi-hop all-groups" value="80,00%" detail="Mốc trần D; B hiện đạt 72,50%" tone="yellow" />
        <KpiCard icon="lucide:shield-alert" label="Context fallback" value="0" detail="277 chunk hoàn tất, ground truth đầy đủ" tone="red" />
      </div>

      <section className="report-section">
        <div className="report-section-heading">
          <div>
            <h2>Hiệu quả retrieval theo mode</h2>
            <p>So sánh ba metric xếp hạng chính trên 300 truy vấn.</p>
          </div>
          <div className="mono text-[10px] text-faint">Đơn vị: %</div>
        </div>
        <div className="report-chart-layout">
          <div className="report-chart-canvas">
            <ResponsiveContainer width="100%" height="100%">
              <BarChart data={chartData} margin={{ top: 10, right: 12, left: -14, bottom: 0 }} barGap={3}>
                <CartesianGrid stroke="var(--border)" strokeDasharray="3 3" vertical={false} />
                <XAxis dataKey="name" tick={{ fill: "var(--dim)", fontSize: 11 }} axisLine={{ stroke: "var(--border)" }} tickLine={false} />
                <YAxis domain={[45, 100]} tick={{ fill: "var(--dim)", fontSize: 10 }} axisLine={false} tickLine={false} />
                <Tooltip content={<ChartTooltip />} cursor={{ fill: "var(--inset)", opacity: 0.55 }} />
                <Legend iconType="square" iconSize={8} wrapperStyle={{ fontSize: 11, color: "var(--dim)" }} />
                <Bar dataKey="Recall@5" fill="var(--blue)" radius={[3, 3, 0, 0]} maxBarSize={28} />
                <Bar dataKey="MRR@10" fill="var(--green)" radius={[3, 3, 0, 0]} maxBarSize={28} />
                <Bar dataKey="NDCG@10" fill="var(--accent)" radius={[3, 3, 0, 0]} maxBarSize={28} />
              </BarChart>
            </ResponsiveContainer>
          </div>
          <ModeLegend />
        </div>
      </section>

      <MetricGlossary />

      <section className="report-section">
        <div className="report-section-heading">
          <div>
            <h2>Bảng metric đầy đủ</h2>
            <p>D là mốc trần có gold annotation; không dùng để quyết định cấu hình production trực tiếp.</p>
          </div>
        </div>
        <div className="report-table-wrap">
          <table className="report-table">
            <thead><tr><th>Mode</th><th>Recall@1</th><th>Recall@5</th><th>Recall@10</th><th>MRR@10</th><th>NDCG@10</th><th>MH all@10</th></tr></thead>
            <tbody>
              {modeMetrics.map((mode) => (
                <tr key={mode.id}>
                  <td><span className="mr-2 inline-block h-2 w-2 rounded-sm" style={{ background: modeColors[mode.shortLabel] }} /><strong>{mode.shortLabel}</strong><span className="ml-2 text-faint">{mode.label}</span></td>
                  <td>{formatPercent(mode.recall1)}</td><td className="font-semibold">{formatPercent(mode.recall5)}</td><td>{formatPercent(mode.recall10)}</td><td>{formatPercent(mode.mrr10)}</td><td>{formatPercent(mode.ndcg10)}</td><td>{formatPercent(mode.multiHopAll10)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </section>
    </div>
  );
}

function TestSetTab() {
  return (
    <div className="space-y-8">
      <section className="report-trust-hero">
        <div className="report-trust-icon"><Icon icon="lucide:badge-check" width={22} /></div>
        <div>
          <div className="text-[11px] font-semibold uppercase text-green">Mức tin cậy: tốt cho quyết định retrieval trong phạm vi benchmark</div>
          <h2>Bộ test thật, đã duyệt và khóa fingerprint</h2>
          <p>Đây không phải tập câu hỏi demo. Benchmark dùng 9 tài liệu thật, ground truth theo chunk và các quy tắc riêng cho multi-hop, null, ACL, bảng và xung đột phiên bản. Kết quả đủ mạnh để giữ B làm baseline, nhưng chưa thay thế kiểm thử production end-to-end.</p>
        </div>
        <div className="report-trust-seal"><strong>300/300</strong><span>approved frozen gold</span></div>
      </section>

      <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-4">
        <KpiCard icon="lucide:library-big" label="Corpus retrieval" value="9 tài liệu" detail="277 chunk từ tài liệu PDF và DOCX thật" tone="blue" />
        <KpiCard icon="lucide:layout-list" label="Thiết kế test" value="10 × 30" detail="10 capability slice, mỗi slice đúng 30 query" tone="green" />
        <KpiCard icon="lucide:circle-help" label="Khả năng trả lời" value="255 / 45" detail="255 answerable; 45 null hoặc permission-denied" tone="yellow" />
        <KpiCard icon="lucide:gauge" label="Độ khó" value="80% hard" detail="240 hard, 30 medium và 30 easy" tone="red" />
      </div>

      <div className="report-scope-note"><Icon icon="lucide:scan-search" width={17} /><div><strong>Corpus retrieval rộng hơn nguồn tạo câu hỏi</strong><p>Query được xây dựng từ 6 tài liệu / 125 chunk, nhưng mỗi mode phải tìm trong toàn bộ 9 tài liệu / 277 chunk. Ba tài liệu còn lại vẫn hiện diện như candidate để tạo nhiễu và kiểm tra khả năng phân biệt.</p></div></div>

      <section className="report-section">
        <div className="report-section-heading"><div><h2>Bộ test được tạo và chạy như thế nào?</h2><p>Sáu lớp kiểm soát từ tài liệu nguồn tới paired comparison.</p></div><span className="report-source-tag">Repo verified</span></div>
        <div className="report-method-grid">
          {testMethodSteps.map((step) => <article key={step.title}><span><Icon icon={step.icon} width={17} /></span><div><strong>{step.title}</strong><p>{step.detail}</p></div></article>)}
        </div>
        <div className="report-config-strip">
          <div><span>Retrieval</span><strong>BM25 + dense → RRF → MMR</strong></div>
          <div><span>Candidate / top K</span><strong>20 / 10</strong></div>
          <div><span>RRF / MMR λ</span><strong>60 / 0,7</strong></div>
          <div><span>Embedding</span><strong>text-embedding-3-small</strong></div>
          <div><span>Lặp / bootstrap</span><strong>3 / 5.000</strong></div>
        </div>
      </section>

      <section className="report-section">
        <div className="report-section-heading"><div><h2>10 năng lực được kiểm tra</h2><p>Mỗi dòng có 30 query; tiêu chí pass thay đổi theo bản chất của capability.</p></div></div>
        <div className="report-table-wrap mt-4">
          <table className="report-table report-explain-table">
            <thead><tr><th>Slice</th><th>Số query</th><th>Muốn kiểm tra điều gì?</th><th>Đúng khi nào?</th></tr></thead>
            <tbody>{benchmarkSlices.map((slice) => <tr key={slice.id}><td><strong>{slice.label}</strong><span className="mono mt-1 block text-[9px] text-faint">{slice.id}</span></td><td>30</td><td>{slice.purpose}</td><td>{slice.passRule}</td></tr>)}</tbody>
          </table>
        </div>
      </section>

      <div className="grid gap-8 xl:grid-cols-2">
        <section className="report-section">
          <div className="report-section-heading"><div><h2>Ground truth không chỉ có một kiểu</h2><p>Scorer không dùng cùng một định nghĩa “đúng” cho mọi câu hỏi.</p></div></div>
          <div className="mt-4 divide-y divide-border">
            {benchmarkTargets.map((target) => <div key={target.label} className="report-target-row"><strong>{target.value}</strong><div><span>{target.label}</span><p>{target.detail}</p></div></div>)}
          </div>
        </section>
        <section className="report-section">
          <div className="report-section-heading"><div><h2>Đa dạng cách diễn đạt</h2><p>Sáu style được phân bố gần đều để tránh chỉ chấm câu hỏi “đẹp”.</p></div></div>
          <div className="mt-5 space-y-4">
            {queryStyles.map((style) => <div key={style.label}><div className="mb-1.5 flex justify-between text-xs"><span className="text-dim">{style.label}</span><strong className="text-foreground">{style.value}</strong></div><div className="h-2 bg-inset"><div className="h-full bg-blue" style={{ width: `${(style.value / 51) * 100}%` }} /></div></div>)}
          </div>
          <div className="mt-5 grid grid-cols-3 gap-3 border-t border-border pt-4 text-center"><div><strong className="font-heading text-lg text-foreground">121</strong><p className="text-[10px] text-faint">scenario</p></div><div><strong className="font-heading text-lg text-foreground">123</strong><p className="text-[10px] text-faint">evidence fact</p></div><div><strong className="font-heading text-lg text-foreground">234 / 66</strong><p className="text-[10px] text-faint">test / dev</p></div></div>
        </section>
      </div>

      <section className="report-section">
        <div className="report-section-heading"><div><h2>Bằng chứng tạo niềm tin</h2><p>Những gì đã được kiểm chứng trong chính run v4 và frozen benchmark.</p></div></div>
        <div className="report-trust-checks">
          {trustChecks.map((item) => <article key={item.check}><span className={`report-check-dot is-${item.tone}`} /><div><strong>{item.check}</strong><p>{item.meaning}</p></div><b>{item.result}</b></article>)}
        </div>
      </section>

      <section className="report-limitations">
        <div className="report-section-heading"><div><h2>Kết quả này chưa chứng minh điều gì?</h2><p>Các giới hạn cần đọc cùng metric trước khi quyết định production.</p></div><Icon icon="lucide:triangle-alert" width={19} className="text-yellow" /></div>
        <div className="report-limit-grid">{benchmarkLimitations.map((item, index) => <article key={item}><span>{String(index + 1).padStart(2, "0")}</span><p>{item}</p></article>)}</div>
      </section>

      <details className="report-glossary">
        <summary><Icon icon="lucide:fingerprint" width={15} />Fingerprint và nguồn dữ liệu kiểm chứng</summary>
        <div className="report-fingerprint-grid">
          <div><span>Benchmark version</span><code>{benchmarkProfile.version}</code></div>
          <div><span>Testset SHA-256</span><code>{reportMeta.benchmarkHash}</code></div>
          <div><span>Source bundle SHA-256</span><code>{benchmarkProfile.sourceBundleHash}</code></div>
          <div><span>Gold metadata SHA-256</span><code>{benchmarkProfile.goldMetadataHash}</code></div>
        </div>
      </details>
    </div>
  );
}

function FieldChannelValue({ value }: { value: string }) {
  const normalized = value.toLocaleLowerCase("vi-VN");
  const tone = normalized === "có" || normalized.startsWith("có ·") || normalized.startsWith("bắt buộc") || normalized.startsWith("acl") || normalized.startsWith("provenance")
    ? "is-on"
    : normalized.startsWith("không")
      ? "is-off"
      : "is-conditional";
  return <span className={`report-channel-value ${tone}`}>{value}</span>;
}

function MetadataTab() {
  const [projection, setProjection] = useState<"embedding" | "search">("embedding");

  return (
    <div className="space-y-8">
      <section className="report-metadata-decision">
        <div><span className="report-decision-badge">P</span></div>
        <div><div className="text-[11px] font-semibold uppercase text-blue">Kết luận production hiện tại</div><h2>Chưa có business metadata đủ điều kiện hard-filter</h2><p>Audit live trên 187 chunk active/current không tìm thấy <code>project_code</code> hoặc <code>project_name</code>. A/B định tuyến theo tên file giảm candidate nhưng không vượt gate Recall@5 và latency, nên chỉ chạy shadow.</p></div>
        <div className="report-metadata-score"><span>Filter được duyệt</span><strong>0 field</strong><small>chỉ giữ security scope bắt buộc</small></div>
      </section>

      <div className="report-scope-note"><Icon icon="lucide:info" width={17} /><div><strong>Trạng thái runtime đã hiệu chỉnh</strong><p>Structured business filter đang tắt. Retrieval chỉ enforce <code>owner_id</code>, <code>notebook_id</code> và <code>document_ids</code>; các field coverage 0 không phải metadata gốc và không được dùng để loại candidate.</p></div></div>

      <div className="report-channel-grid">
        {metadataChannels.map((channel) => <article key={channel.id} className={`is-${channel.tone}`}><div className="report-channel-icon"><Icon icon={channel.icon} width={18} /></div><div><span>{channel.role}</span><h3>{channel.label}</h3><p>{channel.detail}</p></div></article>)}
      </div>

      <section className="report-section">
        <div className="report-section-heading"><div><h2>Nghiên cứu oracle cũ · chỉ để tham khảo</h2><p>Phần này dùng gold metadata để đo tiềm năng khi field luôn đúng; không dùng để phê duyệt field production.</p></div><span className="report-source-tag">Không phải activation evidence</span></div>
        <div className="report-ablation-overall">
          <div><span>Recall@5</span><strong>{formatPercent(filterFieldAblationOverall.recallFull)} → {formatPercent(filterFieldAblationOverall.recallWithout)}</strong><p>Bỏ cả 5 field: −6,25 điểm</p></div>
          <div><span>MRR@10</span><strong>{formatPercent(filterFieldAblationOverall.mrrFull)} → {formatPercent(filterFieldAblationOverall.mrrWithout)}</strong><p>−17,50 điểm · cluster p=0,0002</p></div>
          <div><span>Null rejection</span><strong>{formatPercent(filterFieldAblationOverall.nullFull)} → {formatPercent(filterFieldAblationOverall.nullWithout)}</strong><p>30/30 thất bại · cluster p=0,0002</p></div>
          <div><span>Forbidden top-1</span><strong>{formatPercent(filterFieldAblationOverall.forbiddenFull)} → {formatPercent(filterFieldAblationOverall.forbiddenWithout)}</strong><p>cluster p=0,0166</p></div>
        </div>
        <div className="report-table-wrap mt-4">
          <table className="report-table report-ablation-table">
            <thead><tr><th>Field bị bỏ</th><th>Tập đo</th><th>Δ Recall@5</th><th>Δ MRR@10</th><th>Δ Null rejection</th><th>Bằng chứng</th><th>Kết luận</th></tr></thead>
            <tbody>{filterFieldAblationRows.map((row) => <tr key={row.field}><td><code>{row.field}</code></td><td>{row.queries}</td><td><DeltaCell value={row.recallDelta} /></td><td><DeltaCell value={row.mrrDelta} /></td><td>{row.nullDelta === null ? "N/A" : <DeltaCell value={row.nullDelta} />}</td><td>{row.evidence}</td><td><span className={`report-priority is-${row.tone}`}>{row.verdict}</span></td></tr>)}</tbody>
          </table>
        </div>
        <div className="report-scope-note mt-4"><Icon icon="lucide:database-zap" width={17} /><div><strong>Không dùng bảng oracle để triển khai</strong><p>Audit production-first cho thấy <code>document_type</code> thực tế là 0/277, không phải 277/277. Quyết định triển khai nằm ở bảng production-first bên dưới.</p></div></div>
      </section>

      <section className="report-section">
        <div className="report-section-heading"><div><h2>Audit extractor trên corpus benchmark</h2><p>Phần này chỉ mô tả 277 chunk của benchmark đóng băng, không đại diện cho metadata của notebook live. Gold chỉ là reference để đối chiếu.</p></div><span className="report-source-tag">Benchmark snapshot · không phải production live</span></div>
        <div className="report-table-wrap mt-4">
          <table className="report-table report-research-table">
            <thead><tr><th>Field / nhóm identity</th><th>Điều kiện</th><th>Current</th><th>Gold</th><th>Quyết định</th><th>Lý do</th></tr></thead>
            <tbody>{preRetrievalFieldCandidates.map((row) => <tr key={row.field}><td><code>{row.field}</code></td><td>{row.conditions}</td><td className={row.current ? "text-green" : "text-red"}>{row.current}/277</td><td>{row.gold}/277</td><td><span className={`report-priority is-${row.tone}`}>{row.priority}</span></td><td>{row.decision}</td></tr>)}</tbody>
          </table>
        </div>
        <div className="report-research-summary">
          <div><Icon icon="lucide:shield-x" width={17} className="text-red" /><p><strong>Không có field được chọn:</strong> kết quả <code>project_code</code> chỉ mô tả subset benchmark có heading Pxx, không phải quyết định production.</p></div>
          <div><Icon icon="lucide:construction" width={17} className="text-yellow" /><p><strong>Chỉ giữ giá trị có thật:</strong> title, content kind, section và year chỉ được lưu khi parser hoặc nguồn tài liệu thực sự tạo ra chúng.</p></div>
          <div><Icon icon="lucide:ban" width={17} className="text-red" /><p><strong>Không dùng làm authoritative filter:</strong> contextual summary, aliases, page/provenance và các giá trị LLM chưa validate.</p></div>
        </div>
      </section>

      <section className="report-section">
        <div className="report-section-heading"><div><h2>Chẩn đoán filter trên snapshot benchmark</h2><p>581 query đo hành vi khi field đã tồn tại trong subset tương ứng. Kết quả không chứng minh extractor live tạo được field hay corpus khác có cùng schema.</p></div><span className="report-source-tag">Không phải activation evidence</span></div>
        <div className="report-table-wrap mt-4">
          <table className="report-table report-research-table">
            <thead><tr><th>Field</th><th>Tập đo</th><th>Candidate</th><th>Giảm</th><th>Recall@5 tăng</th><th>p scenario</th><th>Local p50 filter / no filter</th><th>Quyết định</th></tr></thead>
            <tbody>{extendedFieldStudyRows.map((row) => <tr key={row.field}><td><code>{row.field}</code></td><td>{row.queries}</td><td>{row.candidates}</td><td>{formatPercent(row.reduction)}</td><td className={row.recallGain > 0 ? "text-green" : row.recallGain < 0 ? "text-red" : "text-dim"}>{row.recallGain > 0 ? "+" : ""}{row.recallGain.toFixed(2)} điểm</td><td>{row.pValue}</td><td>{row.latency}</td><td><span className={`report-priority is-${row.tone}`}>{row.verdict}</span></td></tr>)}</tbody>
          </table>
        </div>
        <div className="report-scope-note mt-4"><Icon icon="lucide:shield-alert" width={17} /><div><strong>Diễn giải đúng mức tin cậy</strong><p><code>project_code</code> chỉ có 18 scenario, p=0,1204 và coverage live active/current 0/187. Kết quả này không đủ để rollout hay backfill field vào tài liệu không chứa mã dự án.</p></div></div>
      </section>

      <section className="report-section">
        <div className="report-section-heading"><div><h2>Payload schema tối thiểu đề xuất</h2><p>Chỉ tạo index cho field có vai trò query rõ; field hiển thị, derivation và audit vẫn được lưu nhưng không nhất thiết tạo payload index.</p></div><span className="report-source-tag">Không đưa domain field vào embedding</span></div>
        <div className="report-table-wrap mt-4">
          <table className="report-table report-field-table">
            <thead><tr><th>Mức</th><th>Field</th><th>Index</th><th>Vai trò</th></tr></thead>
            <tbody>{recommendedPayloadSchema.map((row) => <tr key={`${row.level}-${row.fields}`}><td><span className={`report-priority is-${row.tone}`}>{row.level}</span></td><td><code>{row.fields}</code></td><td>{row.index}</td><td>{row.role}</td></tr>)}</tbody>
          </table>
        </div>
      </section>

      <section className="report-section">
        <div className="report-section-heading"><div><h2>Gate trước khi mở filter production</h2><p>Field chỉ được promote sau khi extraction và retrieval cùng đạt yêu cầu.</p></div></div>
        <div className="mt-4 grid gap-3 md:grid-cols-2 xl:grid-cols-3">{preRetrievalGates.map((gate) => <div key={gate} className="flex gap-2 border-b border-border pb-3 text-xs leading-5 text-dim"><Icon icon="lucide:square-check-big" width={15} className="mt-0.5 shrink-0 text-blue" />{gate}</div>)}</div>
      </section>

      <section className="report-section">
        <div className="report-section-heading"><div><h2>Field nào đi vào kênh nào?</h2><p>Ma trận dưới đây mô tả chính xác mode B trong context-quality v4; “gold cố định” là dữ liệu benchmark, không phải output extraction production.</p></div><span className="report-source-tag">contextual-text-v4</span></div>
        <div className="report-table-wrap mt-4">
          <table className="report-table report-field-table">
            <thead><tr><th>Field</th><th>Cụm</th><th>Dense</th><th>BM25</th><th>Filter / vai trò</th><th>Độ phủ trong run</th><th>Ý nghĩa và chức năng</th></tr></thead>
            <tbody>{metadataFieldRows.map((row) => <tr key={row.fields}><td><code>{row.fields}</code></td><td>{row.group}</td><td><FieldChannelValue value={row.dense} /></td><td><FieldChannelValue value={row.sparse} /></td><td><FieldChannelValue value={row.filter} /></td><td>{row.coverage}</td><td>{row.meaning}</td></tr>)}</tbody>
          </table>
        </div>
      </section>

      <div className="grid gap-8 xl:grid-cols-[0.85fr_1.15fr]">
        <section className="report-section">
          <div className="report-section-heading"><div><h2>Độ phủ header hiện tại</h2><p>Current metadata dùng để dựng header B trước embedding.</p></div></div>
          <div className="mt-5 space-y-5">
            {metadataCoverage.map((item) => { const percentage = (item.value / item.total) * 100; return <div key={item.label}><div className="mb-1.5 flex items-end justify-between gap-3"><div><strong className="text-xs text-foreground">{item.label}</strong><p className="mt-0.5 text-[10px] text-faint">{item.note}</p></div><span className={item.value === 0 ? "text-xs font-semibold text-red" : "text-xs font-semibold text-dim"}>{item.value}/{item.total}</span></div><div className="h-2 bg-inset"><div className={item.value === 0 ? "h-full bg-red" : "h-full bg-blue"} style={{ width: `${Math.max(percentage, item.value === 0 ? 0 : 1)}%` }} /></div></div>; })}
          </div>
          <div className="report-gap-callout"><Icon icon="lucide:table-properties" width={17} /><div><strong>Gap xác nhận từ repo</strong><p><code>table_header</code> có code projection nhưng current metadata không populate giá trị nào; gold metadata có 40 chunk bảng. Nên sửa extraction trước khi kỳ vọng field này tạo lợi ích.</p></div></div>
        </section>

        <section className="report-section">
          <div className="report-section-heading"><div><h2>Dữ liệu thật ngay trước khi index</h2><p>Ví dụ chunk {metadataProjectionExample.chunk}; đây là chuỗi được đưa vào embedding hoặc BM25.</p></div><div className="report-segmented"><button className={projection === "embedding" ? "is-active" : ""} onClick={() => setProjection("embedding")}><Icon icon="lucide:brain-circuit" width={14} />Dense</button><button className={projection === "search" ? "is-active" : ""} onClick={() => setProjection("search")}><Icon icon="lucide:list-filter" width={14} />BM25</button></div></div>
          <pre className="report-projection-code"><code>{metadataProjectionExample[projection]}</code></pre>
          <div className="report-token-strip"><div><span>Chunk-only trung bình</span><strong>239,21 token</strong></div><div><span>B · dense</span><strong>249,86 <small>+10,65</small></strong></div><div><span>B · BM25</span><strong>245,35 <small>+6,14</small></strong></div></div>
        </section>
      </div>

      <section className="report-metadata-notes">
        <article><Icon icon="lucide:circle-check-big" width={18} className="text-green" /><div><strong>Điều đã được chứng minh</strong><p>Header B tăng Recall@5 thêm 31,76 điểm phần trăm so với chunk-only, CI 95% hoàn toàn dương. Domain fields không cần được nhồi vào embedding/search trong phép thử này.</p></div></article>
        <article><Icon icon="lucide:flask-conical" width={18} className="text-yellow" /><div><strong>Điều chưa được chứng minh</strong><p>Chưa có business field nào vừa tồn tại trong metadata gốc, vừa có provenance, coverage và non-regression đủ để lọc production.</p></div></article>
        <article><Icon icon="lucide:message-square-text" width={18} className="text-blue" /><div><strong>Contextual summary đang ở đâu?</strong><p>Field vẫn có trong <code>ChunkContext</code>, gold metadata và mode C. Policy B chỉ không index nó; C-sparse vẫn là ứng viên canary cần kiểm tra ngoài mẫu.</p></div></article>
      </section>
    </div>
  );
}

function DeltaCell({ value }: { value: number }) {
  const className = value > 0 ? "report-delta-positive" : value < 0 ? "report-delta-negative" : "report-delta-neutral";
  return <span className={className}>{value > 0 ? "+" : ""}{value.toLocaleString("vi-VN", { minimumFractionDigits: 2 })}</span>;
}

function QueriesTab() {
  return (
    <div className="space-y-8">
      <section className="report-section">
        <div className="report-section-heading">
          <div><h2>Paired comparison · Recall@5</h2><p>Khoảng tin cậy bootstrap 95%; đường 0 biểu thị không thay đổi.</p></div>
        </div>
        <div className="mt-5 space-y-3">
          {pairedComparisons.map((item) => {
            const significant = item.ciLow > 0 || item.ciHigh < 0;
            const start = Math.max(0, Math.min(100, ((item.ciLow + 5) / 45) * 100));
            const end = Math.max(start + 1, Math.min(100, ((item.ciHigh + 5) / 45) * 100));
            const point = Math.max(0, Math.min(100, ((item.delta + 5) / 45) * 100));
            return (
              <div key={item.label} className="report-ci-row">
                <div className="min-w-0"><div className="truncate text-xs font-semibold text-foreground">{item.label}</div><div className="mt-0.5 text-[10px] text-faint">Thắng {item.wins} · hòa {item.ties} · thua {item.losses}</div></div>
                <div className="report-ci-track">
                  <span className="report-ci-zero" />
                  <span className={`report-ci-range ${significant ? "is-significant" : ""}`} style={{ left: `${start}%`, width: `${end - start}%` }} />
                  <span className="report-ci-point" style={{ left: `${point}%` }} />
                </div>
                <div className="text-right"><DeltaCell value={item.delta} /><div className="mt-0.5 text-[10px] text-faint">{item.verdict} · p={item.pValue}</div></div>
              </div>
            );
          })}
        </div>
      </section>

      <section className="report-section">
        <div className="report-section-heading">
          <div><h2>Delta Recall@5 theo loại truy vấn</h2><p>So với B · deterministic header; đơn vị là điểm phần trăm.</p></div>
        </div>
        <div className="report-table-wrap mt-4">
          <table className="report-table report-heatmap-table">
            <thead><tr><th>Loại truy vấn</th><th>B Recall@5</th><th>C-dense</th><th>C-sparse</th><th>C raw</th><th>D effective</th></tr></thead>
            <tbody>
              {queryTypeDeltas.map((row) => (
                <tr key={row.queryType}>
                  <td className="font-medium">{row.queryType}</td>
                  <td>{row.baseline === null ? "N/A" : formatPercent(row.baseline)}</td>
                  <td><DeltaCell value={row.dense} /></td><td><DeltaCell value={row.sparse} /></td><td><DeltaCell value={row.raw} /></td><td><DeltaCell value={row.effective} /></td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </section>

      <div className="grid gap-4 lg:grid-cols-3">
        <article className="report-insight"><Icon icon="lucide:circle-plus" className="text-green" width={18} /><div><strong>Được lợi</strong><p>Content-only tăng 6,67 điểm với C-sparse. Context giúp chunk thiếu định danh cục bộ.</p></div></article>
        <article className="report-insight"><Icon icon="lucide:circle-minus" className="text-red" width={18} /><div><strong>Cần cảnh giác</strong><p>Full raw C giảm 6,67 điểm ở cross-document và 13,33 điểm ở permission-sensitive.</p></div></article>
        <article className="report-insight"><Icon icon="lucide:equal" className="text-blue" width={18} /><div><strong>Đã bão hòa</strong><p>Explicit/implicit filter đạt Recall@5 100% từ B; context không còn headroom tại K=5.</p></div></article>
      </div>
    </div>
  );
}

function QualityTab() {
  return (
    <div className="space-y-8">
      <div className="grid gap-8 lg:grid-cols-[0.85fr_1.15fr]">
        <section className="report-section">
          <div className="report-section-heading"><div><h2>Quyết định sinh context</h2><p>V4 không ép mọi chunk phải có summary.</p></div></div>
          <div className="relative h-[260px]">
            <ResponsiveContainer width="100%" height="100%">
              <PieChart>
                <Pie data={contextStatus} dataKey="value" nameKey="name" innerRadius={70} outerRadius={96} paddingAngle={2} stroke="var(--panel)" strokeWidth={3}>
                  {contextStatus.map((entry) => <Cell key={entry.name} fill={entry.color} />)}
                </Pie>
                <Tooltip content={<PieTooltip />} />
              </PieChart>
            </ResponsiveContainer>
            <div className="pointer-events-none absolute inset-0 flex flex-col items-center justify-center">
              <strong className="font-heading text-3xl text-foreground">277</strong><span className="text-[11px] text-faint">chunk</span>
            </div>
          </div>
          <div className="grid grid-cols-2 gap-3">
            {contextStatus.map((item) => <div key={item.name} className="flex items-center gap-2 border-t border-border pt-3"><span className="h-2.5 w-2.5 rounded-sm" style={{ background: item.color }} /><div><div className="text-sm font-semibold text-foreground">{item.value}</div><div className="text-[10px] text-faint">{item.name} · {formatPercent(item.percentage)}</div></div></div>)}
          </div>
        </section>

        <section className="report-section">
          <div className="report-section-heading"><div><h2>Quality gate trên 89 summary</h2><p>47 summary được giữ hoặc theo dõi; 42 summary cần xử lý lại.</p></div></div>
          <div className="mt-6 space-y-5">
            {qualityDecisions.map((item) => (
              <div key={item.label}>
                <div className="mb-1.5 flex items-center justify-between text-xs"><span className="font-medium text-foreground">{item.label}</span><span className="text-dim">{item.value} · {formatPercent(item.percentage)}</span></div>
                <div className="h-2 overflow-hidden rounded-sm bg-inset"><div className={`h-full report-bg-${item.tone}`} style={{ width: `${item.percentage}%` }} /></div>
              </div>
            ))}
          </div>
          <div className="mt-7 border-t border-border pt-5">
            <div className="grid grid-cols-3 gap-3 text-center"><div><strong className="font-heading text-xl text-foreground">24,52</strong><div className="mt-1 text-[10px] text-faint">Từ / summary</div></div><div><strong className="font-heading text-xl text-foreground">30</strong><div className="mt-1 text-[10px] text-faint">P95 số từ</div></div><div><strong className="font-heading text-xl text-foreground">0</strong><div className="mt-1 text-[10px] text-faint">Fallback</div></div></div>
          </div>
        </section>
      </div>

      <section className="report-section">
        <div className="report-section-heading"><div><h2>Điểm chất lượng tự động</h2><p>Thang điểm 0-2. Added value là nút thắt chính của v4.</p></div></div>
        <div className="mt-5 grid gap-x-8 gap-y-4 md:grid-cols-2">
          {qualityScores.map((item) => (
            <div key={item.label} className="grid grid-cols-[130px_1fr_74px] items-center gap-3">
              <span className="text-xs font-medium text-foreground">{item.label}</span>
              <div className="h-2 overflow-hidden rounded-sm bg-inset"><div className={`h-full ${item.score < 0.75 ? "bg-red" : item.score < 1.25 ? "bg-yellow" : "bg-green"}`} style={{ width: `${(item.score / 2) * 100}%` }} /></div>
              <span className="text-right text-xs text-dim"><strong className="text-foreground">{item.score.toLocaleString("vi-VN")}</strong>/2 · {item.zeroCount} lỗi</span>
            </div>
          ))}
        </div>
      </section>

      <section className="report-section">
        <div className="report-section-heading"><div><h2>Phân bố theo tài liệu</h2><p>Hai hợp đồng PDF tạo 57/89 context nhưng có tỷ lệ regenerate/reject cao.</p></div></div>
        <div className="report-table-wrap mt-4">
          <table className="report-table"><thead><tr><th>Tài liệu</th><th>Chunk</th><th>Đã sinh</th><th>Không cần</th><th>Keep/monitor</th><th>Sinh lại/reject</th></tr></thead><tbody>{documentQuality.map((row) => <tr key={row.document}><td className="font-medium">{row.document}</td><td>{row.chunks}</td><td>{row.generated}</td><td>{row.skipped}</td><td className="text-green">{row.accepted}</td><td className={row.failed ? "text-red" : "text-dim"}>{row.failed}</td></tr>)}</tbody></table>
        </div>
      </section>

      <div className="grid gap-4 lg:grid-cols-2">
        <article className="report-evidence is-reject"><div className="report-evidence-title"><Icon icon="lucide:shield-x" width={17} /> Audit bắt đúng</div><p>P14 · Ocean Park 3 bị gán quy mô 458 ha và tiện ích của Ocean Park 2. Groundedness bằng 0 và bị reject.</p></article>
        <article className="report-evidence is-warning"><div className="report-evidence-title"><Icon icon="lucide:scan-eye" width={17} /> Audit còn bỏ lọt</div><p>P16 · Smart City bị gán địa bàn Gia Lâm thay vì Nam Từ Liêm nhưng vẫn đạt 10/10. Cần validator kiểm tra ràng buộc entity → attribute.</p></article>
      </div>
    </div>
  );
}

function AnalysisTab() {
  const [notes, setNotes] = useState<AnalysisNote[]>([]);
  const [title, setTitle] = useState("");
  const [body, setBody] = useState("");
  const [editingId, setEditingId] = useState<string | null>(null);
  const [status, setStatus] = useState("");

  useEffect(() => {
    try {
      const stored = window.localStorage.getItem(NOTES_STORAGE_KEY);
      if (stored) setNotes(JSON.parse(stored) as AnalysisNote[]);
    } catch {
      setStatus("Không đọc được ghi chú đã lưu");
    }
  }, []);

  const persistNotes = (nextNotes: AnalysisNote[]) => {
    setNotes(nextNotes);
    window.localStorage.setItem(NOTES_STORAGE_KEY, JSON.stringify(nextNotes));
    setStatus("Đã lưu");
    window.setTimeout(() => setStatus(""), 1800);
  };

  const saveNote = () => {
    const trimmedBody = body.trim();
    if (!trimmedBody) return;
    const now = new Date().toISOString();
    if (editingId) {
      persistNotes(notes.map((note) => note.id === editingId ? { ...note, title: title.trim() || "Phân tích bổ sung", body: trimmedBody, updatedAt: now } : note));
    } else {
      persistNotes([{ id: crypto.randomUUID(), title: title.trim() || `Phân tích bổ sung ${notes.length + 1}`, body: trimmedBody, createdAt: now, updatedAt: now }, ...notes]);
    }
    setTitle(""); setBody(""); setEditingId(null);
  };

  const editNote = (note: AnalysisNote) => {
    setEditingId(note.id); setTitle(note.title); setBody(note.body);
    document.getElementById("analysis-composer")?.scrollIntoView({ behavior: "smooth", block: "center" });
  };

  const deleteNote = (id: string) => persistNotes(notes.filter((note) => note.id !== id));

  const exportNotes = () => {
    const content = [`BÁO CÁO CONTEXTUAL RETRIEVAL V4`, `Xuất lúc: ${new Date().toLocaleString("vi-VN")}`, "", ...notes.flatMap((note) => [`## ${note.title}`, note.body, `Cập nhật: ${formatDate(note.updatedAt)}`, ""])].join("\n");
    const url = URL.createObjectURL(new Blob([content], { type: "text/plain;charset=utf-8" }));
    const anchor = document.createElement("a"); anchor.href = url; anchor.download = "context-quality-v4-phan-tich.txt"; anchor.click(); URL.revokeObjectURL(url);
  };

  const copyConclusion = async () => {
    await navigator.clipboard.writeText("Giữ deterministic header B làm mặc định production. C-sparse là ứng viên canary nhưng chưa có ý nghĩa thống kê. Không bật full raw context cho cả dense và sparse. Ưu tiên entity-binding validator và quality-gated sparse-only.");
    setStatus("Đã sao chép kết luận"); window.setTimeout(() => setStatus(""), 1800);
  };

  return (
    <div className="grid gap-8 xl:grid-cols-[0.8fr_1.2fr]">
      <div className="space-y-6">
        <section className="report-section">
          <div className="report-section-heading"><div><h2>Kết luận đã xác nhận</h2><p>Tổng hợp từ paired comparison, ablation theo kênh và quality audit.</p></div><button onClick={copyConclusion} title="Sao chép kết luận" className="report-icon-button"><Icon icon="lucide:copy" width={15} /></button></div>
          <ol className="mt-5 space-y-4">
            <li className="report-finding"><span>01</span><div><strong>Giữ B cho production</strong><p>Deterministic header có bằng chứng paired mạnh và Recall@10 đạt 100%.</p></div></li>
            <li className="report-finding"><span>02</span><div><strong>Chỉ canary C-sparse</strong><p>Raw sparse-only có hướng cải thiện nhưng CI vẫn chạm 0.</p></div></li>
            <li className="report-finding"><span>03</span><div><strong>Chưa bật full C</strong><p>Context trên cả hai kênh làm giảm ranking và có regression theo nhóm truy vấn.</p></div></li>
            <li className="report-finding"><span>04</span><div><strong>Ưu tiên entity binding</strong><p>Audit lexical chưa phát hiện được lỗi gán đúng thuộc tính cho sai dự án.</p></div></li>
          </ol>
        </section>

        <section className="report-section">
          <div className="report-section-heading"><div><h2>Gate trước khi promote</h2><p>Các điều kiện cần đạt trong lần chạy tiếp theo.</p></div></div>
          <ul className="mt-4 space-y-3">{["Candidate không âm ở Recall@5, MRR, NDCG và multi-hop", "Không regression ở cross-document, permission, null và table", "Correct-vs-shuffled dương với CI 95% không cắt 0", "Không còn hard reject hoặc lỗi entity-attribute trong mẫu review"].map((item) => <li key={item} className="flex gap-2 text-xs leading-5 text-dim"><Icon icon="lucide:square-check-big" width={15} className="mt-0.5 shrink-0 text-green" />{item}</li>)}</ul>
        </section>
      </div>

      <div className="space-y-6">
        <section id="analysis-composer" className="report-section report-analysis-composer">
          <div className="report-section-heading"><div><h2>{editingId ? "Chỉnh sửa phân tích" : "Phân tích bổ sung"}</h2><p>{notes.length} ghi chú đã lưu</p></div>{status && <span className="text-[11px] font-medium text-green">{status}</span>}</div>
          <div className="mt-5 space-y-3">
            <label className="block"><span className="mb-1.5 block text-[11px] font-semibold text-dim">Tiêu đề</span><input value={title} onChange={(event) => setTitle(event.target.value)} placeholder="Ví dụ: Nhận định sau khi review thủ công" className="report-input" /></label>
            <label className="block"><span className="mb-1.5 block text-[11px] font-semibold text-dim">Nội dung phân tích</span><textarea value={body} onChange={(event) => setBody(event.target.value)} placeholder="Bổ sung phát hiện, giả thuyết hoặc quyết định của nhóm..." className="report-textarea" /></label>
          </div>
          <div className="mt-3 flex flex-wrap items-center justify-between gap-3">
            <div className="text-[10px] text-faint">{body.length.toLocaleString("vi-VN")} ký tự</div>
            <div className="flex gap-2">{editingId && <button onClick={() => { setEditingId(null); setTitle(""); setBody(""); }} className="report-secondary-button">Hủy</button>}<button onClick={saveNote} disabled={!body.trim()} className="report-primary-button"><Icon icon={editingId ? "lucide:save" : "lucide:plus"} width={15} />{editingId ? "Lưu thay đổi" : "Thêm phân tích"}</button></div>
          </div>
        </section>

        <section className="report-section">
          <div className="report-section-heading"><div><h2>Ghi chú của nhóm</h2><p>Sắp xếp theo lần cập nhật gần nhất.</p></div><button onClick={exportNotes} disabled={!notes.length} title="Xuất ghi chú" className="report-icon-button"><Icon icon="lucide:download" width={15} /></button></div>
          {notes.length === 0 ? <div className="report-empty"><Icon icon="lucide:notebook-pen" width={24} /><p>Chưa có phân tích bổ sung.</p></div> : <div className="mt-4 divide-y divide-border">{notes.map((note) => <article key={note.id} className="py-4 first:pt-0 last:pb-0"><div className="flex items-start justify-between gap-3"><div><h3 className="text-sm font-semibold text-foreground">{note.title}</h3><div className="mt-1 text-[10px] text-faint">Cập nhật {formatDate(note.updatedAt)}</div></div><div className="flex shrink-0 gap-1"><button onClick={() => editNote(note)} title="Chỉnh sửa" className="report-icon-button"><Icon icon="lucide:pencil" width={14} /></button><button onClick={() => deleteNote(note.id)} title="Xóa" className="report-icon-button hover:!text-red"><Icon icon="lucide:trash-2" width={14} /></button></div></div><p className="mt-3 whitespace-pre-wrap text-xs leading-6 text-dim">{note.body}</p></article>)}</div>}
        </section>
      </div>
    </div>
  );
}

export default function ContextQualityReport() {
  const [activeTab, setActiveTab] = useState<TabId>("overview");
  const activeContent = useMemo(() => {
    if (activeTab === "slides") return <MetadataStudyPresentation />;
    if (activeTab === "detailed") return <MetadataStudyDetailedReport onOpenAnalysis={() => setActiveTab("analysis")} />;
    if (activeTab === "testset") return <TestSetTab />;
    if (activeTab === "metadata") return <MetadataTab />;
    if (activeTab === "queries") return <QueriesTab />;
    if (activeTab === "quality") return <QualityTab />;
    if (activeTab === "analysis") return <AnalysisTab />;
    return <OverviewTab />;
  }, [activeTab]);

  return (
    <main className="report-page">
      <div className="report-page-header">
        <div className="report-container">
          <div className="flex flex-wrap items-start justify-between gap-5">
            <div className="min-w-0">
              <div className="mb-2 flex flex-wrap items-center gap-2 text-[10px] font-semibold uppercase text-faint"><span>Evaluation</span><Icon icon="lucide:chevron-right" width={12} /><span>Context quality</span><span className="report-status"><span />Hoàn tất</span></div>
              <h1 className="font-heading text-[26px] font-semibold text-foreground sm:text-[30px]">Contextual Retrieval v4</h1>
              <p className="mt-2 max-w-3xl text-sm leading-6 text-dim">Đánh giá tác động của deterministic header và contextual summary lên dense, sparse, hybrid retrieval và multi-hop.</p>
            </div>
            <div className="grid shrink-0 grid-cols-3 gap-x-5 border-l border-border pl-5 text-right max-sm:w-full max-sm:border-l-0 max-sm:border-t max-sm:pl-0 max-sm:pt-4">
              <div><strong className="font-heading text-lg text-foreground">{reportMeta.queryCount}</strong><div className="text-[10px] text-faint">Truy vấn</div></div>
              <div><strong className="font-heading text-lg text-foreground">{reportMeta.chunkCount}</strong><div className="text-[10px] text-faint">Chunk</div></div>
              <div><strong className="font-heading text-lg text-foreground">{reportMeta.modeCount}</strong><div className="text-[10px] text-faint">Mode</div></div>
            </div>
          </div>
          <div className="mt-6 flex items-center gap-1 overflow-x-auto border-b border-border" role="tablist" aria-label="Các phần báo cáo">
            {tabs.map((tab) => <button key={tab.id} onClick={() => setActiveTab(tab.id)} role="tab" aria-selected={activeTab === tab.id} className={`report-tab ${activeTab === tab.id ? "is-active" : ""}`}><Icon icon={tab.icon} width={15} />{tab.label}</button>)}
          </div>
        </div>
      </div>

      <div className="report-container py-7 sm:py-9">
        {activeContent}
        <footer className="mt-10 flex flex-wrap items-center justify-between gap-3 border-t border-border pt-4 text-[10px] text-faint"><span className="mono">{reportMeta.runId}</span><span>{reportMeta.promptVersion} · {reportMeta.embeddingModel} · fallback {reportMeta.fallbackCount}</span></footer>
      </div>
    </main>
  );
}
