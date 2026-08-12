import assert from "node:assert/strict";
import test from "node:test";

import {
  buildEnterpriseCitationDisplay,
  buildEnterpriseSourcePreviewUrl,
  formatEnterpriseCitationReferences,
  getEnterpriseCitationOrderFromHref,
} from "./enterpriseCitationDisplay.js";

test("replaces internal source codes with consecutive visible numbers", () => {
  const display = buildEnterpriseCitationDisplay([
    { citation_order: 2, chunk_id: "second" },
    { citation_order: 5, chunk_id: "fifth" },
  ]);

  assert.equal(
    formatEnterpriseCitationReferences("Dữ kiện A [SRC-2], dữ kiện B [SRC-5].", display),
    "Dữ kiện A [1](#enterprise-citation-2), dữ kiện B [2](#enterprise-citation-5).",
  );
});

test("falls back to array order for legacy citations without citation_order", () => {
  const display = buildEnterpriseCitationDisplay([{ chunk_id: "legacy" }]);
  assert.equal(
    formatEnterpriseCitationReferences("Nội dung [SRC-1].", display),
    "Nội dung [1](#enterprise-citation-1).",
  );
});

test("only accepts internal enterprise citation links", () => {
  assert.equal(getEnterpriseCitationOrderFromHref("#enterprise-citation-3"), 3);
  assert.equal(getEnterpriseCitationOrderFromHref("https://example.com"), null);
});

test("builds a page-bound PDF URL with a best-effort text search", () => {
  const url = buildEnterpriseSourcePreviewUrl(
    "https://files.test/policy.pdf?token=abc#old",
    7,
    "  Giá bán   là 82 triệu đồng/m². ",
    "application/pdf",
  );
  assert.match(url, /^https:\/\/files\.test\/policy\.pdf\?token=abc#page=7&view=FitH&search=/);
  const fragment = new URLSearchParams(url.split("#", 2)[1]);
  assert.equal(fragment.get("search"), "Giá bán là 82 triệu đồng/m².");
});

test("leaves non-PDF source URLs unchanged", () => {
  assert.equal(
    buildEnterpriseSourcePreviewUrl("https://files.test/policy.docx", 2, "quote", "application/vnd.openxmlformats-officedocument.wordprocessingml.document"),
    "https://files.test/policy.docx",
  );
});
