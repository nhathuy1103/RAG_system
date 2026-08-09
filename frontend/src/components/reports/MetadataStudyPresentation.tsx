import { useEffect, useRef, useState, type ReactNode } from "react";
import { Icon } from "@iconify/react";

import {
  benchmarkProfile,
  extendedFieldStudyRows,
  liveDocumentScopeStudy,
  modeMetrics,
  reportMeta,
} from "../../data/contextQualityReportV4";

type Slide = {
  eyebrow: string;
  title: string;
  summary: string;
  content: ReactNode;
};

const formatPercent = (value: number) => `${value.toLocaleString("vi-VN", { maximumFractionDigits: 2 })}%`;

export default function MetadataStudyPresentation() {
  const [index, setIndex] = useState(0);
  const frameRef = useRef<HTMLElement>(null);
  const baseline = modeMetrics.find((mode) => mode.shortLabel === "B")!;
  const chunkOnly = modeMetrics.find((mode) => mode.shortLabel === "A")!;
  const sparseCandidate = modeMetrics.find((mode) => mode.shortLabel === "C-sparse")!;
  const fullContext = modeMetrics.find((mode) => mode.shortLabel === "C")!;

  const slides: Slide[] = [
    {
      eyebrow: "Kết quả nghiên cứu retrieval",
      title: "Từ thử nghiệm context đến metadata production",
      summary: "Hai nghiên cứu riêng biệt trả lời hai câu hỏi: text nào nên được index và field nào đủ tin cậy để lọc trước retrieval.",
      content: (
        <div className="report-slide-opening">
          <div><strong>300</strong><span>truy vấn benchmark context</span></div>
          <div><strong>581</strong><span>truy vấn chẩn đoán metadata</span></div>
          <div><strong>277</strong><span>chunk từ tài liệu thật</span></div>
          <div><strong>0</strong><span>business hard filter production</span></div>
        </div>
      ),
    },
    {
      eyebrow: "01 · Nền tảng bằng chứng",
      title: "Bộ test được khóa trước khi so sánh",
      summary: "Mọi cấu hình chạy trên cùng corpus, query và ground truth để delta không bị nhiễu bởi thay đổi tập mẫu.",
      content: (
        <div className="report-slide-grid four">
          <div><Icon icon="lucide:library-big" /><strong>{benchmarkProfile.sourceDocuments} tài liệu</strong><span>{benchmarkProfile.sourceChunks} chunk retrieval</span></div>
          <div><Icon icon="lucide:badge-check" /><strong>{reportMeta.queryCount}/300 duyệt</strong><span>approved frozen gold</span></div>
          <div><Icon icon="lucide:layout-grid" /><strong>10 × 30</strong><span>10 nhóm năng lực</span></div>
          <div><Icon icon="lucide:shield-check" /><strong>0 unresolved</strong><span>fingerprint được khóa</span></div>
        </div>
      ),
    },
    {
      eyebrow: "02 · Chọn text index",
      title: "Tiêu đề cấu trúc tạo ra bước cải thiện lớn nhất",
      summary: "B thêm ngữ cảnh lấy trực tiếp từ cấu trúc tài liệu; summary do AI không tạo thêm lợi ích ổn định khi đưa vào embedding.",
      content: (
        <div className="report-slide-comparison">
          <div><span>A · Chỉ chunk</span><strong>{formatPercent(chunkOnly.recall5)}</strong><small>Recall@5</small></div>
          <Icon icon="lucide:arrow-right" width={28} />
          <div className="is-selected"><span>B · Chunk + tiêu đề cấu trúc</span><strong>{formatPercent(baseline.recall5)}</strong><small>+31,76 điểm %, p=0,0002</small></div>
          <div className="report-slide-context-note"><span>C-sparse: {formatPercent(sparseCandidate.recall5)} · ứng viên canary</span><span>C cả hai kênh: {formatPercent(fullContext.recall5)} · thấp hơn B 1,18 điểm</span></div>
        </div>
      ),
    },
    {
      eyebrow: "03 · Sửa sai phương pháp",
      title: "Chỉ đánh giá field mà pipeline thực sự tạo ra",
      summary: "Nghiên cứu cũ dùng gold/profile có thể làm field trông đầy đủ hơn production. Lần chạy mới reparse tài liệu và lấy current metadata từ parser, chunker và normalizer.",
      content: (
        <div className="report-slide-split">
          <div className="is-rejected"><span>Không dùng để quyết định</span><strong>Oracle / gold injection</strong><p>Field có trong annotation nhưng chưa chắc tồn tại trong dữ liệu runtime.</p></div>
          <div className="is-approved"><span>Nguồn quyết định mới</span><strong>Production-first metadata</strong><p>277/277 chunk được căn chỉnh với frozen benchmark; chỉ thay payload bằng dữ liệu parser tạo thật.</p></div>
        </div>
      ),
    },
    {
      eyebrow: "04 · Quy trình chọn field",
      title: "Mỗi field phải vượt qua bốn lớp kiểm tra",
      summary: "Có tên trong schema là chưa đủ. Field phải có giá trị thật, có provenance, giữ được evidence và tạo lợi ích retrieval.",
      content: (
        <ol className="report-slide-steps">
          <li><span>1</span><div><strong>Tồn tại</strong><p>Đo coverage trên 277 chunk current metadata.</p></div></li>
          <li><span>2</span><div><strong>Đúng</strong><p>Đối chiếu gold nơi có reference và kiểm tra derivation.</p></div></li>
          <li><span>3</span><div><strong>Dùng được</strong><p>581 query có điều kiện và provenance theo field.</p></div></li>
          <li><span>4</span><div><strong>Có lợi</strong><p>Paired A/B, 3 repeats, 5.000 bootstrap/permutation.</p></div></li>
        </ol>
      ),
    },
    {
      eyebrow: "05 · Kết quả từng field",
      title: "Chưa có business field vượt qua cổng production",
      summary: "project_code chỉ có tín hiệu trong subset benchmark chứa heading Pxx. Audit live active/current 0/187 nên không được coi là metadata gốc hoặc dùng để loại candidate.",
      content: (
        <div className="report-slide-table-wrap">
          <table className="report-slide-table">
            <thead><tr><th>Field</th><th>Coverage thật</th><th>Δ Recall@5</th><th>Quyết định</th></tr></thead>
            <tbody>
              {extendedFieldStudyRows.map((row) => (
                <tr key={row.field} className={row.field === "project_code" ? "is-selected" : ""}>
                  <td><code>{row.field}</code></td>
                  <td>{row.field === "project_code" ? "36/277" : row.field === "content_kind" || row.field === "section_title" ? "277/277" : row.field === "year" ? "52/277" : "36/277"}</td>
                  <td>{row.recallGain > 0 ? "+" : ""}{row.recallGain.toFixed(2)} điểm</td>
                  <td>{row.verdict}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      ),
    },
    {
      eyebrow: "06 · A/B trên demo live",
      title: "Tên file thật giảm candidate nhưng chưa cải thiện retrieval",
      summary: "19 câu có ground truth UUID chạy trực tiếp trên PostgreSQL FTS, pgvector và OpenAI; không inject gold metadata. Kết quả âm được giữ nguyên để quyết định rollout an toàn.",
      content: (
        <div className="report-slide-comparison">
          <div><span>Baseline · toàn bộ scope</span><strong>{formatPercent(liveDocumentScopeStudy.baseline.recall5)}</strong><small>{liveDocumentScopeStudy.baseline.medianLatencyMs.toFixed(2)} ms median</small></div>
          <Icon icon="lucide:arrow-right" width={28} />
          <div><span>Route theo ID + tên file</span><strong>{formatPercent(liveDocumentScopeStudy.routed.recall5)}</strong><small>{liveDocumentScopeStudy.routed.medianLatencyMs.toFixed(2)} ms median</small></div>
          <div className="report-slide-context-note"><span>Candidate giảm {formatPercent(liveDocumentScopeStudy.delta.candidateReduction)}</span><span>Quyết định: shadow only, không loại evidence</span></div>
        </div>
      ),
    },
    {
      eyebrow: "07 · Kiến trúc được chọn",
      title: "Mỗi nhóm field có một nhiệm vụ riêng",
      summary: "Không nhồi toàn bộ metadata vào embedding. Tách semantic text, filter canonical, resolver, security và provenance để vừa chính xác vừa dễ kiểm soát.",
      content: (
        <div className="report-slide-grid architecture">
          <div><Icon icon="lucide:brain-circuit" /><strong>Dense + BM25</strong><span>Title, section, loại nội dung có điều kiện, table header và chunk.</span></div>
          <div><Icon icon="lucide:funnel-x" /><strong>Business hard filter</strong><span>Chưa có field được phê duyệt cho corpus production hiện tại.</span></div>
          <div><Icon icon="lucide:tags" /><strong>Resolver / payload</strong><span>Project name, alias, section path, content kind, year.</span></div>
          <div><Icon icon="lucide:shield-check" /><strong>Security / scope</strong><span>Owner, notebook và document IDs chặn trước retrieval.</span></div>
        </div>
      ),
    },
    {
      eyebrow: "08 · Quyết định triển khai",
      title: "Dừng business filter và quay về metadata có thật",
      summary: "Migration 15 chỉ cung cấp khả năng kỹ thuật. Runtime đã tắt structured filter; không backfill project_code nếu tài liệu gốc không có bằng chứng cho mã dự án.",
      content: (
        <div className="report-slide-rollout">
          <div><span>Audit live active</span><strong>0 / 187 chunk</strong><p>có <code>project_code</code></p></div>
          <Icon icon="lucide:arrow-right" width={28} />
          <div><span>Bước bắt buộc</span><strong>Khảo sát nguồn gốc</strong><p>chỉ chọn field vốn có hoặc derive chắc chắn</p></div>
          <Icon icon="lucide:arrow-right" width={28} />
          <div className="is-selected"><span>Production hiện tại</span><strong>Scope-only retrieval</strong><p>owner, notebook và document IDs</p></div>
        </div>
      ),
    },
  ];

  const go = (next: number) => setIndex(Math.min(Math.max(next, 0), slides.length - 1));

  useEffect(() => {
    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key === "ArrowRight" || event.key === "PageDown") go(index + 1);
      if (event.key === "ArrowLeft" || event.key === "PageUp") go(index - 1);
      if (event.key === "Home") go(0);
      if (event.key === "End") go(slides.length - 1);
    };
    window.addEventListener("keydown", onKeyDown);
    return () => window.removeEventListener("keydown", onKeyDown);
  }, [index, slides.length]);

  const toggleFullscreen = async () => {
    if (document.fullscreenElement) await document.exitFullscreen();
    else await frameRef.current?.requestFullscreen();
  };

  const slide = slides[index];
  return (
    <section ref={frameRef} className="report-presentation" aria-label="Trình chiếu kết quả nghiên cứu metadata">
      <header className="report-presentation-toolbar">
        <div><span>Metadata retrieval study</span><strong>{index + 1} / {slides.length}</strong></div>
        <div className="report-presentation-actions">
          <button onClick={() => go(index - 1)} disabled={index === 0} title="Slide trước"><Icon icon="lucide:arrow-left" width={17} /></button>
          <button onClick={() => go(index + 1)} disabled={index === slides.length - 1} title="Slide tiếp theo"><Icon icon="lucide:arrow-right" width={17} /></button>
          <button onClick={toggleFullscreen} title="Toàn màn hình"><Icon icon="lucide:maximize-2" width={17} /></button>
        </div>
      </header>
      <div className="report-slide-stage">
        <article className="report-slide" key={index}>
          <div className="report-slide-copy"><span>{slide.eyebrow}</span><h2>{slide.title}</h2><p>{slide.summary}</p></div>
          <div className="report-slide-content">{slide.content}</div>
          <footer><span>{reportMeta.runId}</span><span>Dùng phím ← → để chuyển slide</span></footer>
        </article>
      </div>
      <div className="report-slide-dots" aria-label="Chọn slide">
        {slides.map((item, slideIndex) => <button key={item.title} onClick={() => go(slideIndex)} className={slideIndex === index ? "is-active" : ""} title={`Slide ${slideIndex + 1}: ${item.title}`} />)}
      </div>
    </section>
  );
}
