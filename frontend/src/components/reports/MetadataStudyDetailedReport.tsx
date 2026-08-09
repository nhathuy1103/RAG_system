import { useState } from "react";
import { Icon } from "@iconify/react";

import {
  benchmarkLimitations,
  benchmarkProfile,
  extendedFieldStudyRows,
  liveDocumentScopeStudy,
  liveMetadataAudit,
  modeMetrics,
  preRetrievalGates,
  recommendedPayloadSchema,
  reportMeta,
  testMethodSteps,
  trustChecks,
} from "../../data/contextQualityReportV4";

type Props = { onOpenAnalysis: () => void };

const sections = [
  ["detail-summary", "Kết luận"],
  ["detail-scope", "Dữ liệu và độ tin cậy"],
  ["detail-live", "A/B metadata live"],
  ["detail-context", "Thử nghiệm context"],
  ["detail-method", "Cách chọn metadata"],
  ["detail-fields", "Kết quả từng field"],
  ["detail-policy", "Policy cuối cùng"],
  ["detail-rollout", "Triển khai và giới hạn"],
];

export default function MetadataStudyDetailedReport({ onOpenAnalysis }: Props) {
  const [status, setStatus] = useState("");
  const mode = (id: string) => modeMetrics.find((item) => item.shortLabel === id)!;

  const copyConclusion = async () => {
    await navigator.clipboard.writeText(
      "Kết quả chốt: dùng chunk + deterministic header làm text index mặc định; không đưa contextual_summary vào embedding production. Audit active/current có 187 chunk và không có project_code, project_name hay region. A/B định tuyến theo documents.id + original_filename giảm 65,63% candidate nhưng Recall@5 giảm 5,26 điểm và median latency tăng 18,20 ms, nên chỉ chạy shadow. Production tiếp tục enforce owner_id, notebook_id và document_ids.",
    );
    setStatus("Đã sao chép kết luận");
    window.setTimeout(() => setStatus(""), 1800);
  };

  return (
    <div className="report-detail-layout">
      <aside className="report-detail-toc" aria-label="Mục lục báo cáo chi tiết">
        <div className="report-detail-toc-title">Nội dung</div>
        {sections.map(([id, label], index) => <a key={id} href={`#${id}`}><span>{String(index + 1).padStart(2, "0")}</span>{label}</a>)}
      </aside>

      <article className="report-detailed">
        <header className="report-detailed-header">
          <div><span>Báo cáo quyết định kỹ thuật</span><h2>Đánh giá context và giới hạn metadata cho retrieval</h2><p>Tách riêng kết quả benchmark context, chẩn đoán field trên snapshot và trạng thái metadata live để không suy rộng sai sang production.</p></div>
          <div className="report-detail-actions">
            <button onClick={copyConclusion}><Icon icon="lucide:copy" width={15} />Sao chép kết luận</button>
            <button onClick={() => window.print()}><Icon icon="lucide:printer" width={15} />In / lưu PDF</button>
          </div>
          {status && <div className="report-detail-status">{status}</div>}
        </header>

        <section id="detail-summary" className="report-detail-section">
          <span className="report-detail-kicker">01 · Kết luận điều hành</span>
          <h3>Hai quyết định khác nhau cho hai lớp retrieval</h3>
          <div className="report-detail-decision-grid">
            <div><Icon icon="lucide:brain-circuit" /><span>Text index</span><strong>Giữ cấu hình B</strong><p>Chunk cộng tiêu đề cấu trúc lấy trực tiếp từ tài liệu. Recall@5 đạt 96,47%, cao hơn chunk-only 31,76 điểm phần trăm.</p></div>
            <div><Icon icon="lucide:funnel" /><span>Metadata filter</span><strong>Chưa chọn business field</strong><p>project_code có tín hiệu trên subset heading Pxx nhưng coverage live bằng 0 và chưa đủ bằng chứng để áp dụng production.</p></div>
            <div><Icon icon="lucide:scan-search" /><span>Document identity</span><strong>Shadow, chưa rollout</strong><p>Tên file thật giảm candidate 65,63% nhưng Recall@5 giảm 5,26 điểm và latency không tốt hơn, nên Langfuse chỉ ghi counterfactual.</p></div>
          </div>
          <div className="report-detail-callout"><Icon icon="lucide:info" width={17} /><p><code>contextual_summary</code> và metadata filter là hai vấn đề riêng. Summary thay đổi text xếp hạng; <code>project_code</code> thu hẹp candidate trước xếp hạng.</p></div>
        </section>

        <section id="detail-scope" className="report-detail-section">
          <span className="report-detail-kicker">02 · Dữ liệu và độ tin cậy</span>
          <h3>Benchmark được kiểm soát như thế nào?</h3>
          <div className="report-detail-statline">
            <div><strong>{benchmarkProfile.sourceDocuments}</strong><span>tài liệu thật</span></div>
            <div><strong>{benchmarkProfile.sourceChunks}</strong><span>chunk retrieval</span></div>
            <div><strong>{reportMeta.queryCount}</strong><span>query frozen gold</span></div>
            <div><strong>10 × 30</strong><span>capability slices</span></div>
            <div><strong>0</strong><span>gold unresolved</span></div>
          </div>
          <div className="report-detail-method-list">
            {testMethodSteps.map((step) => <div key={step.title}><Icon icon={step.icon} width={17} /><div><strong>{step.title}</strong><p>{step.detail}</p></div></div>)}
          </div>
          <div className="report-detail-evidence-list">
            {trustChecks.slice(0, 4).map((item) => <div key={item.check}><strong>{item.result}</strong><span>{item.check}</span><p>{item.meaning}</p></div>)}
          </div>
        </section>

        <section id="detail-live" className="report-detail-section">
          <span className="report-detail-kicker">03 · Kiểm chứng metadata trên demo live</span>
          <h3>Field nào thực sự tồn tại trước retrieval?</h3>
          <p className="report-detail-lead">Audit chỉ tính tài liệu <code>ready + active + current</code> trong notebook demo, không trộn ba bản inactive. Nguồn là bảng Supabase live; không điền field từ gold benchmark.</p>
          <div className="report-detail-statline">
            <div><strong>{liveMetadataAudit.activeDocuments}</strong><span>tài liệu active/current</span></div>
            <div><strong>{liveMetadataAudit.activeChunks}</strong><span>chunk đang retrieval</span></div>
            <div><strong>{liveDocumentScopeStudy.queries}</strong><span>query ground truth live</span></div>
            <div><strong>{liveDocumentScopeStudy.repeats}</strong><span>lần lặp A/B</span></div>
            <div><strong>0</strong><span>gold metadata inject</span></div>
          </div>
          <div className="report-table-wrap">
            <table className="report-table"><thead><tr><th>Field thật</th><th>Có giá trị</th><th>Coverage</th><th>Nguồn</th></tr></thead><tbody>
              {liveMetadataAudit.fields.map((row) => <tr key={row.field}><td><code>{row.field}</code></td><td>{row.count}/{liveMetadataAudit.activeChunks}</td><td>{row.coverage.toFixed(2)}%</td><td>{row.source}</td></tr>)}
            </tbody></table>
          </div>
          <h4>A/B <code>documents.id + original_filename</code></h4>
          <p className="report-detail-lead">Planner chỉ route khi tên file khớp duy nhất; ba câu chính sách có hai tài liệu gần trùng tên được giữ fail-open. Ground truth là UUID document/chunk đã tồn tại và các mệnh đề được xác nhận nằm trong chunk nguồn.</p>
          <div className="report-table-wrap">
            <table className="report-table"><thead><tr><th>Mode</th><th>Recall@5</th><th>MRR</th><th>Candidate TB</th><th>Median latency</th><th>Đáp án grounded</th><th>Citation đúng chunk</th></tr></thead><tbody>
              <tr><td>Baseline: toàn bộ scope hợp lệ</td><td>{liveDocumentScopeStudy.baseline.recall5.toFixed(2)}%</td><td>{liveDocumentScopeStudy.baseline.mrr.toFixed(2)}%</td><td>{liveDocumentScopeStudy.baseline.meanCandidateChunks}</td><td>{liveDocumentScopeStudy.baseline.medianLatencyMs.toFixed(2)} ms</td><td>{liveDocumentScopeStudy.baseline.groundedAnswerPass.toFixed(2)}%</td><td>{liveDocumentScopeStudy.baseline.expectedChunkCitation.toFixed(2)}%</td></tr>
              <tr><td>Route theo danh tính tài liệu</td><td>{liveDocumentScopeStudy.routed.recall5.toFixed(2)}%</td><td>{liveDocumentScopeStudy.routed.mrr.toFixed(2)}%</td><td>{liveDocumentScopeStudy.routed.meanCandidateChunks.toFixed(2)}</td><td>{liveDocumentScopeStudy.routed.medianLatencyMs.toFixed(2)} ms</td><td>{liveDocumentScopeStudy.routed.groundedAnswerPass.toFixed(2)}%</td><td>{liveDocumentScopeStudy.routed.expectedChunkCitation.toFixed(2)}%</td></tr>
            </tbody></table>
          </div>
          <div className="report-detail-warning"><Icon icon="lucide:shield-alert" width={17} /><div><strong>Quyết định: {liveDocumentScopeStudy.decision}</strong><p>Candidate giảm {liveDocumentScopeStudy.delta.candidateReduction.toFixed(2)}%, nhưng Recall@5 giảm {Math.abs(liveDocumentScopeStudy.delta.recall5).toFixed(2)} điểm và median latency tăng {liveDocumentScopeStudy.delta.medianLatencyMs.toFixed(2)} ms. Runtime chỉ ghi kế hoạch counterfactual vào Langfuse, không dùng nó để loại evidence.</p></div></div>
        </section>

        <section id="detail-context" className="report-detail-section">
          <span className="report-detail-kicker">04 · Thử nghiệm text context</span>
          <h3>Điều gì được đưa vào dense và sparse?</h3>
          <p className="report-detail-lead">Bảy mode chỉ thay đổi projection text; corpus, query, gold và structured metadata được giữ cố định. Vì vậy delta ở đây đo ảnh hưởng của text context, không phải chất lượng extraction metadata.</p>
          <div className="report-table-wrap">
            <table className="report-table"><thead><tr><th>Cấu hình</th><th>Recall@1</th><th>Recall@5</th><th>MRR@10</th><th>Vai trò</th></tr></thead><tbody>
              {modeMetrics.map((row) => <tr key={row.id}><td><strong>{row.shortLabel}</strong> · {row.label}<small className="report-table-note">{row.explanation}</small></td><td>{row.recall1.toFixed(2)}%</td><td>{row.recall5.toFixed(2)}%</td><td>{row.mrr10.toFixed(2)}%</td><td>{row.shortLabel === "B" ? "Production mặc định" : row.shortLabel === "C-sparse" ? "Canary" : row.role === "diagnostic" || row.role === "control" ? "Chỉ chẩn đoán" : "So sánh"}</td></tr>)}
            </tbody></table>
          </div>
          <div className="report-detail-findings">
            <div><strong>+31,76 điểm</strong><p>B so với A, CI95% [+25,49; +38,04], p=0,0002. Đây là kết quả mạnh nhất.</p></div>
            <div><strong>+0,78 điểm</strong><p>C-sparse so với B, nhưng chỉ 2 thắng/253 hòa và p=0,4981. Chỉ đủ cho canary.</p></div>
            <div><strong>−1,18 điểm</strong><p>Summary trong cả dense và sparse thấp hơn B; không bật full context.</p></div>
          </div>
        </section>

        <section id="detail-method" className="report-detail-section">
          <span className="report-detail-kicker">05 · Phương pháp chọn metadata</span>
          <h3>Từ schema rộng đến field có thể triển khai</h3>
          <p className="report-detail-lead">Quyết định mới không dùng gold để điền metadata còn thiếu. Tài liệu được parse lại bằng production pipeline, sau đó current metadata được căn chỉnh với 277 frozen chunk để giữ nguyên ground truth.</p>
          <ol className="report-detail-funnel">
            <li><span>12 field</span><p>được phát hiện trong current metadata sau reparse.</p></li>
            <li><span>5 field</span><p>có cả giá trị production và query support để A/B: content_kind, project_code, project_name, section_title, year.</p></li>
            <li><span>581 query</span><p>được tạo theo giá trị thật của từng field, có provenance.</p></li>
            <li><span>3.486 rows</span><p>6 mode × 581 query, chạy 3 repeats và chấm bằng 5.000 bootstrap/permutation.</p></li>
            <li><span>0 field</span><p>được phê duyệt làm business hard filter cho corpus production hiện tại.</p></li>
          </ol>
          <h4>Cổng quyết định</h4>
          <ul className="report-detail-gates">{preRetrievalGates.map((gate) => <li key={gate}><Icon icon="lucide:check" width={14} />{gate}</li>)}</ul>
          <div className="report-detail-warning"><Icon icon="lucide:triangle-alert" width={17} /><div><strong>Field bị loại trước A/B</strong><p><code>document_type</code>, <code>data_period</code>, <code>effective_status</code>, <code>lifecycle_status</code> và <code>source</code> có coverage production bằng 0/277. Chúng không được giả lập bằng gold để đưa ra quyết định.</p></div></div>
        </section>

        <section id="detail-fields" className="report-detail-section">
          <span className="report-detail-kicker">06 · Chẩn đoán field trên benchmark</span>
          <h3>Field nào đã thử và vì sao chưa được chọn cho production?</h3>
          <div className="report-table-wrap">
            <table className="report-table"><thead><tr><th>Field</th><th>Coverage</th><th>Candidate</th><th>Giảm candidate</th><th>Δ Recall@5</th><th>p scenario</th><th>Quyết định</th></tr></thead><tbody>
              {extendedFieldStudyRows.map((row) => <tr key={row.field} className={row.field === "project_code" ? "report-row-selected" : ""}><td><code>{row.field}</code></td><td>{row.field === "project_code" ? "36/277" : row.field === "content_kind" || row.field === "section_title" ? "277/277" : row.field === "year" ? "52/277" : "36/277"}</td><td>{row.candidates}</td><td>{row.reduction.toFixed(3)}%</td><td className={row.recallGain > 0 ? "text-green" : "text-red"}>{row.recallGain > 0 ? "+" : ""}{row.recallGain.toFixed(2)} điểm</td><td>{row.pValue}</td><td>{row.verdict}</td></tr>)}
            </tbody></table>
          </div>
          <div className="report-detail-field-notes">
            <div><strong><code>project_code</code></strong><p>36 chunk chỉ thuộc 18 section của một tài liệu có heading Pxx. Audit live active/current của notebook hiện tại là 0/187 và p scenario là 0,1204; vì vậy không được suy rộng hay rollout.</p></div>
            <div><strong><code>project_name</code></strong><p>Không dùng direct filter: relevant retention chỉ 36% và Recall@5 giảm 46 điểm. Tên và alias chỉ resolve về mã canonical.</p></div>
            <div><strong><code>content_kind</code>, <code>section_title</code>, <code>year</code></strong><p>Giữ cho payload, ranking hoặc audit theo vai trò; không được loại candidate tự động vì có regression hoặc thiếu coverage/precision.</p></div>
          </div>
        </section>

        <section id="detail-policy" className="report-detail-section">
          <span className="report-detail-kicker">07 · Policy cuối cùng</span>
          <h3>Metadata được gắn cạnh vector và sử dụng ra sao?</h3>
          <div className="report-table-wrap"><table className="report-table"><thead><tr><th>Mức</th><th>Field</th><th>Index</th><th>Chức năng</th></tr></thead><tbody>{recommendedPayloadSchema.map((row) => <tr key={`${row.level}-${row.fields}`}><td>{row.level}</td><td><code>{row.fields}</code></td><td>{row.index}</td><td>{row.role}</td></tr>)}</tbody></table></div>
          <div className="report-detail-architecture">
            <div><span>1</span><strong>Nhận query</strong><p>Không suy diễn field ngoài metadata gốc</p></div><Icon icon="lucide:arrow-right" />
            <div><span>2</span><strong>Security scope</strong><p>owner/notebook/document IDs</p></div><Icon icon="lucide:arrow-right" />
            <div><span>3</span><strong>Business filter</strong><p>Chưa có field được duyệt</p></div><Icon icon="lucide:arrow-right" />
            <div><span>4</span><strong>Hybrid ranking</strong><p>dense + BM25 trên text B</p></div>
          </div>
        </section>

        <section id="detail-rollout" className="report-detail-section">
          <span className="report-detail-kicker">08 · Triển khai và giới hạn</span>
          <h3>Điều kiện trước khi bật production</h3>
          <div className="report-detail-rollout"><div><strong>Migration</strong><span>Chỉ tạo khả năng kỹ thuật</span></div><div><strong>Audit live</strong><span>0/187 có project_code</span></div><div><strong>Document resolver</strong><span>Shadow trong Langfuse</span></div><div><strong>Business filter</strong><span>Chưa field nào được duyệt</span></div></div>
          <ol className="report-detail-next"><li>Lập inventory metadata gốc theo từng loại tài liệu và nguồn tạo field.</li><li>Chỉ tạo extractor cho field có bằng chứng trong tài liệu hoặc hệ thống nguồn authoritative.</li><li>Đo coverage, precision, relevant retention và non-regression trên corpus production đại diện.</li><li>Chỉ đề xuất rollout sau khi field vượt gate; không backfill giá trị suy đoán.</li></ol>
          <details className="report-detail-limitations"><summary>Giới hạn cần công khai</summary><ul>{benchmarkLimitations.map((item) => <li key={item}>{item}</li>)}</ul></details>
          <button onClick={onOpenAnalysis} className="report-detail-analysis-button"><Icon icon="lucide:notebook-pen" width={16} />Mở phần phân tích bổ sung của nhóm</button>
        </section>
      </article>
    </div>
  );
}
