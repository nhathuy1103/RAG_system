import fs from "node:fs/promises";
import path from "node:path";
import { Presentation, PresentationFile } from "@oai/artifact-tool";

const OUT = "D:/VIN_AI/VSF/week2/agentic-rag-batch-2-g1-develop (1)/agentic-rag-batch-2-g1-develop/docs/reports/SLIDE_EXACT_DUPLICATE_CHI_TIET.pptx";
const TMP = "D:/VIN_AI/VSF/week2/agentic-rag-batch-2-g1-develop (1)/agentic-rag-batch-2-g1-develop/artifacts/slides_exact_duplicate_build/rendered";

const C = {
  canvas: "#FFFFFF",
  ink: "#000000",
  muted: "#5D6772",
  panel: "#EDEDED",
  panel2: "#F6F7F8",
  rule: "#B8BCC4",
  blue: "#3D8DFF",
  lightBlue: "#D0EDFA",
  green: "#2F7D4A",
  lightGreen: "#E8F4EC",
  amber: "#A66500",
  lightAmber: "#FFF3D6",
  red: "#A33A3A",
  lightRed: "#FBEAEA",
};

const FONT = "Arial";

function addText(slide, text, left, top, width, height, opts = {}) {
  const box = slide.shapes.add({
    geometry: "textbox",
    name: opts.name,
    position: { left, top, width, height },
    fill: "none",
    line: { style: "solid", fill: "none", width: 0 },
  });
  box.text = text;
  box.text.style = {
    fontSize: opts.fontSize ?? 20,
    typeface: FONT,
    color: opts.color ?? C.ink,
    bold: opts.bold ?? false,
    alignment: opts.align ?? "left",
    verticalAlignment: opts.valign ?? "top",
    autoFit: opts.autoFit ?? "shrinkText",
  };
  return box;
}

function addRect(slide, left, top, width, height, opts = {}) {
  return slide.shapes.add({
    geometry: opts.geometry ?? "rect",
    name: opts.name,
    position: { left, top, width, height },
    fill: opts.fill ?? C.panel2,
    line: { style: "solid", fill: opts.line ?? C.rule, width: opts.lineWidth ?? 1 },
    borderRadius: opts.radius ?? 0,
  });
}

function addNode(slide, { left, top, width, height, title, body, fill = C.panel2, line = C.rule, titleColor = C.ink, name }) {
  const shape = addRect(slide, left, top, width, height, { fill, line, lineWidth: 1.5, radius: 10, name });
  addText(slide, title, left + 18, top + 15, width - 36, 42, { fontSize: 22, bold: true, color: titleColor, name: `${name || title}-title` });
  addText(slide, body, left + 18, top + 62, width - 36, height - 76, { fontSize: 16, color: C.ink, name: `${name || title}-body` });
  return shape;
}

function connect(slide, a, b, opts = {}) {
  return slide.shapes.connect(a, b, {
    kind: opts.kind ?? "elbow",
    fromSide: opts.fromSide ?? "right",
    toSide: opts.toSide ?? "left",
    line: { style: opts.dashed ? "dashed" : "solid", fill: opts.color ?? C.muted, width: opts.width ?? 2 },
    head: { type: "arrow", width: "med", length: "med" },
  });
}

function addSlideTitle(slide, title, page, kicker = "EXACT DUPLICATE · REPOSITORY WALKTHROUGH") {
  addText(slide, kicker, 42, 30, 650, 28, { fontSize: 14, bold: true, color: C.muted });
  addText(slide, title, 42, 66, 1140, 72, { fontSize: 38, bold: false, color: C.ink, autoFit: "shrinkText" });
  addText(slide, String(page).padStart(2, "0"), 1185, 670, 50, 20, { fontSize: 13, color: C.muted, align: "right" });
}

function addRule(slide, top = 142) {
  slide.shapes.add({
    geometry: "line",
    position: { left: 42, top, width: 1196, height: 0 },
    fill: "none",
    line: { style: "solid", fill: C.rule, width: 1 },
  });
}

function setSources(slide, sources, presenter = []) {
  const lines = [
    ...presenter,
    "",
    "[Sources]",
    ...sources.map((s) => `- ${s}`),
  ];
  slide.speakerNotes.textFrame.setText(lines.join("\n"));
  slide.speakerNotes.setVisible(true);
}

function addBulletList(slide, items, left, top, width, opts = {}) {
  let y = top;
  const gap = opts.gap ?? 56;
  for (const [i, item] of items.entries()) {
    const dot = slide.shapes.add({
      geometry: "ellipse",
      position: { left, top: y + 7, width: 12, height: 12 },
      fill: opts.color ?? C.blue,
      line: { style: "solid", fill: opts.color ?? C.blue, width: 0 },
    });
    dot.sendToBack();
    addText(slide, item, left + 28, y, width - 28, gap - 4, { fontSize: opts.fontSize ?? 20, color: C.ink });
    y += gap;
  }
}

function addExampleBand(slide, label, text, top, color = C.blue) {
  addRect(slide, 42, top, 1196, 94, { fill: C.panel2, line: color, lineWidth: 2 });
  addText(slide, label, 64, top + 18, 220, 54, { fontSize: 20, bold: true, color });
  addText(slide, text, 280, top + 16, 930, 58, { fontSize: 18, color: C.ink });
}

const deck = Presentation.create({ slideSize: { width: 1280, height: 720 } });

// Slide 1 — cover, based on Codex Grid slide 01 hierarchy.
{
  const s = deck.slides.add();
  s.background.fill = C.canvas;
  addText(s, "TECHNICAL DEEP DIVE", 42, 42, 420, 38, { fontSize: 24, color: C.muted });
  addText(s, "Exact duplicate\ntrong hệ thống RAG", 42, 174, 1000, 260, { fontSize: 68, bold: false, valign: "bottom", autoFit: "shrinkText" });
  addText(s, "Ba lớp kiểm tra · Cơ chế race · Lưu tạm và lưu bền · Ví dụ bám sát repository", 42, 510, 760, 92, { fontSize: 26, color: C.ink });
  addRect(s, 1080, 42, 158, 48, { fill: C.lightBlue, line: C.blue, lineWidth: 0 });
  addText(s, "REPO-BASED", 1095, 53, 130, 26, { fontSize: 16, bold: true, color: C.ink, align: "center" });
  setSources(s, [
    "README.md:67-84 — ingestion and exact-identity flow overview.",
    "app/documents/application/services.py:149-220 — upload exact-hash path.",
    "app/ingestion/application/worker.py:359-565 — worker canonical/chunk path.",
  ]);
}

// Slide 2 — three-column layout based on Codex Grid slide 06.
{
  const s = deck.slides.add();
  s.background.fill = C.canvas;
  addSlideTitle(s, "Ba lớp exact xử lý ba bài toán khác nhau", 2);
  addRule(s);
  const cols = [
    { x: 42, n: "01", title: "Raw bytes", body: "SHA-256 toàn bộ file\n\nChặn trước Storage và ingestion job\n\nNhanh nhất, nhưng chỉ bắt byte-identical", color: C.blue },
    { x: 452, n: "02", title: "Canonical document", body: "Typed text/table → stable JSON → SHA-256\n\nBắt exact xuyên định dạng sau parse\n\nChỉ auto-alias khi trust gate đạt", color: C.amber },
    { x: 862, n: "03", title: "Exact chunk", body: "Strict content hash + embedding input checksum\n\nGiảm số lần gọi embedding\n\nChỉ reuse khi model và input tương thích", color: C.green },
  ];
  for (const c of cols) {
    addText(s, c.n, c.x, 178, 110, 58, { fontSize: 44, bold: true, color: c.color });
    addText(s, c.title, c.x, 258, 340, 50, { fontSize: 27, bold: true, color: C.ink });
    addText(s, c.body, c.x, 326, 340, 280, { fontSize: 20, color: C.ink });
  }
  setSources(s, [
    "app/documents/application/services.py:162-175 — layer 1 early return.",
    "app/pipeline/documents/application/content_identity.py:44-168 — layer 2 typed canonical projection.",
    "app/knowledge_quality/application/chunk_preembedding.py:93-250 — layer 3 probe, plan and reuse guard.",
  ]);
}

// Slide 3 — overall sequence.
{
  const s = deck.slides.add();
  s.background.fill = C.canvas;
  addSlideTitle(s, "Luồng chính luôn ưu tiên quyết định rẻ và an toàn hơn trước", 3);
  addRule(s);

  const nodes = [];
  const data = [
    [52, 215, 186, 150, "Upload", "Validate file\nTính raw SHA-256", C.lightBlue, C.blue],
    [268, 215, 186, 150, "Raw lookup", "Tenant-scoped\npre-check + unique", C.lightBlue, C.blue],
    [484, 215, 186, 150, "Parse", "Worker verify\nPipeline.prepare", C.panel2, C.rule],
    [700, 215, 186, 150, "Canonical", "Typed projection\nTrust gate + lookup", C.lightAmber, C.amber],
    [916, 215, 186, 150, "Chunk exact", "Probe + DB/batch\nreuse guard", C.lightGreen, C.green],
    [1132, 215, 96, 150, "Persist", "Vector\nrelation", C.panel2, C.rule],
  ];
  for (const [x, y, w, h, title, body, fill, line] of data) {
    nodes.push(addNode(s, { left: x, top: y, width: w, height: h, title, body, fill, line, name: `flow-${title}` }));
  }
  for (let i = 0; i < nodes.length - 1; i++) connect(s, nodes[i], nodes[i + 1], { kind: "straight" });

  addText(s, "DỪNG SỚM", 64, 402, 160, 32, { fontSize: 16, bold: true, color: C.blue });
  addText(s, "Nếu raw match: trả document cũ, không tạo object/job.", 64, 438, 330, 74, { fontSize: 18, color: C.ink });
  addText(s, "DỪNG SAU PARSE", 480, 402, 190, 32, { fontSize: 16, bold: true, color: C.amber });
  addText(s, "Nếu canonical match + mode on: complete_duplicate trước contextualize/embed.", 480, 438, 390, 74, { fontSize: 18, color: C.ink });
  addText(s, "TỐI ƯU EMBEDDING", 914, 402, 220, 32, { fontSize: 16, bold: true, color: C.green });
  addText(s, "Exact chunk chỉ reuse vector khi model và embedding input checksum đều khớp.", 914, 438, 300, 86, { fontSize: 18, color: C.ink });
  addExampleBand(s, "Nguyên tắc", "Pre-check tối ưu latency; database invariant bảo đảm correctness; fuzzy signal không có quyền thực hiện exact action.", 560, C.blue);
  setSources(s, [
    "app/documents/application/services.py:149-220.",
    "app/ingestion/application/worker.py:359-565.",
    "supabase/migrations/08_knowledge_quality.sql:354-361.",
    "supabase/migrations/09_knowledge_quality_hardening.sql:1175-1604.",
  ]);
}

// Slide 4 — layer 1 detail and worked example.
{
  const s = deck.slides.add();
  s.background.fill = C.canvas;
  addSlideTitle(s, "Lớp 1 trả duplicate trước khi hệ thống chạm Storage", 4);
  addRule(s);

  addText(s, "Điều gì xảy ra?", 42, 174, 430, 48, { fontSize: 26, bold: true });
  addBulletList(s, [
    "validate_document_file kiểm tra extension, signature, encoding và giới hạn kích thước.",
    "content_hash = SHA-256(bytes); filename và MIME client không nằm trong identity.",
    "Lookup theo owner_id + notebook_id + content_hash để không rò rỉ xuyên tenant.",
    "Có match: UploadOutcome trả is_duplicate=true ngay lập tức.",
  ], 52, 242, 530, { fontSize: 18, gap: 76, color: C.blue });

  addRect(s, 630, 174, 608, 410, { fill: C.panel2, line: C.rule });
  addText(s, "Ví dụ: đổi tên nhưng không đổi bytes", 664, 202, 540, 42, { fontSize: 25, bold: true });
  addText(s, "Lần 1", 666, 274, 100, 32, { fontSize: 18, bold: true, color: C.blue });
  addText(s, "bao-cao.pdf\nH_raw = a8f3…91c2", 780, 266, 290, 66, { fontSize: 20 });
  addText(s, "→ tạo document + object + job", 780, 338, 360, 34, { fontSize: 18, color: C.muted });
  addText(s, "Lần 2", 666, 414, 100, 32, { fontSize: 18, bold: true, color: C.green });
  addText(s, "bao-cao-ban-sao.pdf\nH_raw = a8f3…91c2", 780, 406, 330, 66, { fontSize: 20 });
  addText(s, "→ trả document lần 1; không object/job mới", 780, 482, 390, 50, { fontSize: 18, color: C.green, bold: true });
  addExampleBand(s, "Hệ quả", "Tên file vẫn được lưu làm metadata hiển thị, nhưng không được dùng để quyết định nội dung có trùng hay không.", 600, C.blue);
  setSources(s, [
    "app/documents/domain/models.py:133-180 — validation and raw SHA-256.",
    "app/documents/application/services.py:149-175 — tenant lookup and early return.",
    "tests/unit/test_documents.py — exact hash duplicate and renamed-file behaviors.",
  ]);
}

// Slide 5 — race sequence.
{
  const s = deck.slides.add();
  s.background.fill = C.canvas;
  addSlideTitle(s, "Database chọn winner khi hai request cùng vượt qua pre-check", 5);
  addRule(s);

  const laneX = [185, 640, 1095];
  const laneNames = ["REQUEST A", "POSTGRESQL", "REQUEST B"];
  for (let i = 0; i < laneX.length; i++) {
    addText(s, laneNames[i], laneX[i] - 100, 170, 200, 30, { fontSize: 18, bold: true, align: "center", color: i === 1 ? C.blue : C.ink });
    s.shapes.add({ geometry: "line", position: { left: laneX[i], top: 210, width: 0, height: 390 }, fill: "none", line: { style: "solid", fill: C.rule, width: 1 } });
  }
  const event = (y, from, to, label, color = C.ink) => {
    const startX = laneX[from];
    const endX = laneX[to];
    s.shapes.add({
      geometry: "line",
      position: { left: Math.min(startX, endX), top: y, width: Math.abs(endX - startX), height: 0 },
      fill: "none",
      line: { style: "solid", fill: color, width: 2 },
    });
    addText(s, label, 420, y - 28, 440, 24, { fontSize: 16, bold: true, color, align: "center" });
  };
  event(240, 0, 1, "lookup → chưa có");
  event(294, 2, 1, "lookup → chưa có");
  event(362, 0, 1, "INSERT A", C.blue);
  event(416, 1, 0, "A thành công → canonical winner", C.green);
  event(484, 2, 1, "INSERT B", C.amber);
  event(538, 1, 2, "unique conflict", C.red);
  event(592, 2, 1, "lookup lại A → is_duplicate=true", C.green);
  addText(s, "Pre-check không khóa race. Partial unique index mới là invariant atomic; request thua không retry INSERT.", 250, 624, 780, 54, { fontSize: 21, bold: true, color: C.ink, align: "center" });
  setSources(s, [
    "app/documents/application/services.py:191-212 — retry winner after DocumentDuplicateError.",
    "app/documents/adapters/postgrest_repository.py:160-186 — mapping unique conflict.",
    "supabase/migrations/08_knowledge_quality.sql:354-361 — partial unique index.",
    "tests/unit/test_documents.py::test_service_resolves_concurrent_exact_upload_from_unique_constraint.",
  ]);
}

// Slide 6 — cross-format canonical example.
{
  const s = deck.slides.add();
  s.background.fill = C.canvas;
  addSlideTitle(s, "Lớp 2 nhận ra cùng nội dung dù bytes và định dạng khác nhau", 6);
  addRule(s);

  addText(s, "Nguồn mới", 42, 170, 210, 32, { fontSize: 18, bold: true, color: C.muted });
  const txt = addNode(s, { left: 42, top: 216, width: 240, height: 128, title: "gia.txt", body: "Raw hash = 111…\nVisible text: Giá căn A101 là 4,5 tỷ", fill: C.lightBlue, line: C.blue, name: "txt-source" });
  const docx = addNode(s, { left: 42, top: 396, width: 240, height: 128, title: "gia.docx", body: "Raw hash = 9af…\nVisible text: Giá căn A101 là 4,5 tỷ", fill: C.lightBlue, line: C.blue, name: "docx-source" });

  const parse = addNode(s, { left: 374, top: 286, width: 250, height: 170, title: "Parser / extraction", body: "Đưa mỗi format về ParsedDocument gồm text, elements, tables và warnings.", fill: C.panel2, line: C.rule, name: "parse" });
  const project = addNode(s, { left: 718, top: 238, width: 250, height: 270, title: "Typed projection", body: "[{ kind: text, value: ... }]\n\nGiữ type, thứ tự và table boundary; bỏ metadata trình bày không mang semantics.", fill: C.lightAmber, line: C.amber, name: "projection" });
  const match = addNode(s, { left: 1050, top: 286, width: 188, height: 170, title: "H_canonical", body: "Hai strict hash giống nhau → lookup canonical + trust gate", fill: C.lightGreen, line: C.green, name: "canonical-match" });
  connect(s, txt, parse, { kind: "elbow", fromSide: "right", toSide: "left" });
  connect(s, docx, parse, { kind: "elbow", fromSide: "right", toSide: "left" });
  connect(s, parse, project, { kind: "straight" });
  connect(s, project, match, { kind: "straight" });
  addExampleBand(s, "Kết quả mode on", "DOCX row trở thành alias của TXT; chunks/vectors/facts riêng bị suppression; object gốc vẫn giữ để audit.", 574, C.green);
  setSources(s, [
    "app/pipeline/documents/application/content_identity.py:44-168 — typed sequence and stable JSON.",
    "app/knowledge_quality/application/analysis.py:99-173 — fingerprint and auto-identity eligibility.",
    "app/ingestion/application/worker.py:359-444 — parse, lookup and complete_duplicate.",
    "tests/unit/test_cross_format_content_identity.py — TXT/DOCX/Markdown/HTML and table cross-format cases.",
  ]);
}

// Slide 7 — trust gate.
{
  const s = deck.slides.add();
  s.background.fill = C.canvas;
  addSlideTitle(s, "Trust gate ngăn canonical hash được dùng quá tay", 7);
  addRule(s);

  addText(s, "Chỉ auto-alias khi representation đủ đáng tin", 42, 174, 650, 42, { fontSize: 26, bold: true });
  addBulletList(s, [
    "Nội dung phải đủ dài và đủ token để tránh fingerprint yếu.",
    "Cấu trúc text/table phải được chứng minh, không flatten table thành prose.",
    "Không có phần visual/OCR quan trọng chưa được biểu diễn đáng tin cậy.",
    "Normalization version phải khớp với bản ghi canonical được tra cứu.",
    "Nếu không đạt: không auto-alias; pipeline tiếp tục giữ và embedding tài liệu mới.",
  ], 52, 238, 600, { fontSize: 18, gap: 66, color: C.amber });

  addRect(s, 710, 174, 528, 400, { fill: C.panel2, line: C.rule });
  addText(s, "Các ca cố ý KHÔNG coi là exact", 742, 204, 465, 40, { fontSize: 25, bold: true });
  addText(s, "01", 744, 274, 50, 34, { fontSize: 24, bold: true, color: C.red });
  addText(s, "Cùng bảng nhưng đổi một value", 816, 274, 360, 36, { fontSize: 19, bold: true });
  addText(s, "02", 744, 350, 50, 34, { fontSize: 24, bold: true, color: C.red });
  addText(s, "Cùng cells nhưng đổi row order", 816, 350, 360, 36, { fontSize: 19, bold: true });
  addText(s, "03", 744, 426, 50, 34, { fontSize: 24, bold: true, color: C.red });
  addText(s, "Flatten table text so với structured table", 816, 426, 380, 50, { fontSize: 19, bold: true });
  addText(s, "04", 744, 510, 50, 34, { fontSize: 24, bold: true, color: C.red });
  addText(s, "Ảnh/OCR chưa được biểu diễn đáng tin", 816, 510, 370, 50, { fontSize: 19, bold: true });
  addExampleBand(s, "Lựa chọn an toàn", "False negative được đẩy sang candidate/review; false positive không được phép làm mất dữ liệu.", 600, C.amber);
  setSources(s, [
    "app/pipeline/documents/application/content_identity.py:44-168 — projection signals and unsupported content handling.",
    "app/knowledge_quality/application/analysis.py:146-173 — is_auto_identity_eligible.",
    "tests/unit/test_cross_format_content_identity.py — value/order/table-type negative cases.",
  ]);
}

// Slide 8 — chunk reuse decision.
{
  const s = deck.slides.add();
  s.background.fill = C.canvas;
  addSlideTitle(s, "Lớp 3 chỉ reuse vector khi content và embedding input đều giống", 8);
  addRule(s);

  const a = addNode(s, { left: 52, top: 216, width: 210, height: 160, title: "Chunk mới", body: "strict_hash từ canonical_text\nchecksum từ embedding_text", fill: C.lightBlue, line: C.blue, name: "new-chunk" });
  const b = addNode(s, { left: 326, top: 216, width: 210, height: 160, title: "Exact candidate", body: "DB candidate hoặc representative trong cùng batch", fill: C.panel2, line: C.rule, name: "chunk-candidate" });
  const c = addNode(s, { left: 600, top: 188, width: 260, height: 216, title: "Reuse guard", body: "1. strict text giống\n2. quality mode = on\n3. embedding model giống\n4. embedding checksum giống\n5. candidate có vector", fill: C.lightAmber, line: C.amber, name: "reuse-guard" });
  const yes = addNode(s, { left: 942, top: 170, width: 260, height: 150, title: "Reuse vector", body: "Provider không nhận chunk này; decision metadata ghi reuse_exact_embedding.", fill: C.lightGreen, line: C.green, name: "reuse-vector" });
  const no = addNode(s, { left: 942, top: 380, width: 260, height: 150, title: "Embed mới", body: "Exact relation vẫn tồn tại, nhưng vector không được dùng lại.", fill: C.lightRed, line: C.red, name: "embed-new" });
  connect(s, a, b, { kind: "straight" });
  connect(s, b, c, { kind: "straight" });
  connect(s, c, yes, { kind: "elbow", fromSide: "right", toSide: "left", color: C.green });
  connect(s, c, no, { kind: "elbow", fromSide: "right", toSide: "left", color: C.red });

  addExampleBand(s, "Ví dụ được reuse", "A và B chứa cùng canonical chunk, cùng contextual prefix và model text-embedding-3-small → dùng vector persisted của A.", 564, C.green);
  addExampleBand(s, "Ví dụ không reuse", "Canonical chunk giống nhưng contextual prefix khác → embedding_text_checksum khác → B phải gọi embedding provider.", 664, C.red);
  setSources(s, [
    "app/knowledge_quality/application/chunk_preembedding.py:93-250 — probes, exact match and reuse guards.",
    "app/pipeline/indexing/application/pipeline.py:433-530 — provider filtering and dependency vector resolution.",
    "tests/unit/test_chunk_preembedding.py — exact reuse, context mismatch and same-batch reuse.",
    "tests/unit/test_ingestion_embedding_pipeline.py — provider receives only non-reused chunks.",
  ]);
}

// Slide 9 — storage lifecycle.
{
  const s = deck.slides.add();
  s.background.fill = C.canvas;
  addSlideTitle(s, "Dữ liệu so sánh nằm trong RAM; quyết định mới được lưu bền", 9);
  addRule(s);

  addRect(s, 42, 174, 560, 430, { fill: C.panel2, line: C.blue, lineWidth: 2 });
  addText(s, "TẠM THỜI TRONG PROCESS", 72, 202, 480, 34, { fontSize: 22, bold: true, color: C.blue });
  addBulletList(s, [
    "Upload bytes và ValidatedDocumentFile",
    "Downloaded bytes và DocumentSource",
    "ParsedDocument: text, elements, tables, warnings",
    "Canonical sequence, stable JSON và fingerprint",
    "Chunk probes, candidate list và dedup plan",
    "Embedding vectors trước commit",
  ], 76, 262, 480, { fontSize: 18, gap: 50, color: C.blue });

  addRect(s, 678, 174, 560, 430, { fill: C.panel2, line: C.green, lineWidth: 2 });
  addText(s, "LƯU BỀN / CÓ THỂ AUDIT", 708, 202, 480, 34, { fontSize: 22, bold: true, color: C.green });
  addBulletList(s, [
    "Storage object gốc",
    "documents, content_hash và canonical_document_id",
    "normalized hash, version và quality_status",
    "ingestion job, attempt, worker_id và claim_token",
    "chunk decision metadata, relations và vectors",
    "Qdrant generation staging nếu dùng external index",
  ], 712, 262, 480, { fontSize: 18, gap: 50, color: C.green });
  addText(s, "Không có bảng DB temp riêng để chứa canonical JSON hoặc phép so sánh.", 300, 630, 680, 44, { fontSize: 21, bold: true, align: "center" });
  setSources(s, [
    "app/ingestion/application/worker.py:315-565 — in-process lifecycle and fenced completion.",
    "app/pipeline/indexing/adapters/vector_indexes.py:272-342 — Qdrant generation finalization/deletion.",
    "supabase/migrations/09_knowledge_quality_hardening.sql — durable document identity, job fencing and audit.",
  ]);
}

// Slide 10 — three worked outcomes based on Codex Grid slide 18 silhouette.
{
  const s = deck.slides.add();
  s.background.fill = C.canvas;
  addSlideTitle(s, "Ba ví dụ giống nhau ở bề mặt nhưng kết thúc tại ba điểm khác nhau", 10);
  addRule(s);
  const examples = [
    { x: 42, title: "A · Đổi tên file", body: "bao-cao.pdf\n→ bao-cao-copy.pdf\n\nBytes giống hoàn toàn\n\nKết thúc: raw lookup\nKhông Storage/job mới", label: "LỚP 1", color: C.blue },
    { x: 452, title: "B · Đổi định dạng", body: "gia.txt\n→ gia.docx\n\nRaw hash khác; typed canonical giống và trust gate đạt\n\nKết thúc: complete_duplicate", label: "LỚP 2", color: C.amber },
    { x: 862, title: "C · Chung một chunk", body: "Document B có một đoạn giống A\n\nDocument identity khác\n\nKết thúc: reuse đúng vector chunk; phần còn lại vẫn embed", label: "LỚP 3", color: C.green },
  ];
  for (const e of examples) {
    addRect(s, e.x, 172, 376, 398, { fill: C.panel2, line: e.color, lineWidth: 2 });
    addText(s, e.label, e.x + 26, 196, 150, 28, { fontSize: 16, bold: true, color: e.color });
    addText(s, e.title, e.x + 26, 244, 324, 48, { fontSize: 25, bold: true });
    addText(s, e.body, e.x + 26, 316, 324, 220, { fontSize: 19 });
  }
  addText(s, "Cùng nhãn “duplicate” nhưng identity, chi phí đã bỏ ra và quyền tự động ở mỗi lớp hoàn toàn khác nhau.", 180, 610, 920, 50, { fontSize: 22, bold: true, align: "center" });
  setSources(s, [
    "tests/unit/test_documents.py — raw exact examples.",
    "tests/unit/test_cross_format_content_identity.py — cross-format canonical examples.",
    "tests/unit/test_chunk_preembedding.py — chunk exact reuse examples.",
  ]);
}

// Slide 11 — close based on Codex Grid slide 26 hierarchy.
{
  const s = deck.slides.add();
  s.background.fill = C.canvas;
  addText(s, "KẾT LUẬN", 42, 42, 240, 38, { fontSize: 24, color: C.muted });
  addText(s, "Exact chỉ được tự động\nkhi bằng chứng đủ chặt", 42, 168, 1000, 252, { fontSize: 62, valign: "bottom", autoFit: "shrinkText" });
  addText(s, "1 · Hash đúng representation\n2 · Scope tenant đúng\n3 · Database đóng race\n4 · Reuse đúng embedding input", 42, 510, 620, 132, { fontSize: 24 });
  addText(s, "Thông điệp bảo vệ", 805, 494, 330, 36, { fontSize: 18, bold: true, color: C.blue });
  addText(s, "Pre-check giúp nhanh.\nInvariant và guard mới giúp đúng.", 805, 538, 390, 94, { fontSize: 28, bold: true });
  setSources(s, [
    "README.md:268-296 — off/shadow/on policy and exact-vs-fuzzy safety.",
    "docs/operations/knowledge-quality-runbook.md:107-117 — duplicate/version/conflict operator rules.",
  ]);
}

await fs.mkdir(path.dirname(OUT), { recursive: true });
await fs.mkdir(TMP, { recursive: true });

for (const [index, slide] of deck.slides.items.entries()) {
  const stem = `slide-${String(index + 1).padStart(2, "0")}`;
  const png = await deck.export({ slide, format: "png", scale: 1 });
  await fs.writeFile(path.join(TMP, `${stem}.png`), new Uint8Array(await png.arrayBuffer()));
  const layout = await slide.export({ format: "layout" });
  await fs.writeFile(path.join(TMP, `${stem}.layout.json`), await layout.text(), "utf8");
}

const montage = await deck.export({ format: "webp", montage: true, scale: 1 });
await fs.writeFile(path.join(TMP, "montage.webp"), new Uint8Array(await montage.arrayBuffer()));

const pptx = await PresentationFile.exportPptx(deck);
await pptx.save(OUT);
console.log(OUT);
