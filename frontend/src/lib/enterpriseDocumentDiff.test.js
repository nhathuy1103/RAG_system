import assert from "node:assert/strict";
import test from "node:test";

import {
  buildEnterpriseDocumentDiff,
  diffInlineSegments,
  lineSimilarity,
} from "./enterpriseDocumentDiff.js";

test("classifies identical document lines as exact duplicates", () => {
  const diff = buildEnterpriseDocumentDiff(
    "Giá căn hộ năm 2025 là 70 triệu đồng/m².",
    "Giá căn hộ năm 2025 là 70 triệu đồng/m².",
    "exact_content",
  );
  assert.equal(diff.counts.exact, 1);
  assert.equal(diff.counts.conflict, 0);
  assert.equal(diff.averageSimilarity, 1);
});

test("marks a numeric change inside a similar claim as high conflict", () => {
  const diff = buildEnterpriseDocumentDiff(
    "Giá căn hộ năm 2025 là 70 triệu đồng/m².",
    "Giá căn hộ năm 2025 là 82 triệu đồng/m².",
    "conflict_candidate",
  );
  assert.equal(diff.rows.length, 1);
  assert.equal(diff.rows[0].kind, "conflict");
  assert.equal(diff.rows[0].severity, "high");
  assert.equal(diff.rows[0].label, "Mâu thuẫn số liệu");
  assert.ok(diff.rows[0].inline.source.some((segment) => segment.text === "70" && segment.changed));
  assert.ok(diff.rows[0].inline.target.some((segment) => segment.text === "82" && segment.changed));
});

test("keeps close wording aligned as a near duplicate", () => {
  const left = "Khách hàng phải thanh toán trong vòng 30 ngày kể từ ngày ký.";
  const right = "Khách hàng phải thực hiện thanh toán trong 30 ngày kể từ ngày ký.";
  assert.ok(lineSimilarity(left, right) > 0.7);
  const diff = buildEnterpriseDocumentDiff(left, right, "near_duplicate");
  assert.equal(diff.rows[0].kind, "near");
});

test("shows content present on only one side without inventing an alignment", () => {
  const diff = buildEnterpriseDocumentDiff("Điều khoản A\nĐiều khoản bổ sung", "Điều khoản A");
  assert.equal(diff.counts.exact, 1);
  assert.equal(diff.counts.source_only, 1);
});

test("inline segments preserve both original lines", () => {
  const result = diffInlineSegments("Giá là 70 triệu", "Giá là 82 triệu");
  assert.equal(result.source.map((segment) => segment.text).join(""), "Giá là 70 triệu");
  assert.equal(result.target.map((segment) => segment.text).join(""), "Giá là 82 triệu");
});
