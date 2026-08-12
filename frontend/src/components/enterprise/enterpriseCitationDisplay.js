const ENTERPRISE_SOURCE_PATTERN = /\[SRC-(\d+)\]/gi;
const ENTERPRISE_CITATION_PREFIX = "#enterprise-citation-";

function positiveInteger(value) {
  const parsed = Number.parseInt(String(value ?? ""), 10);
  return Number.isInteger(parsed) && parsed > 0 ? parsed : null;
}

export function buildEnterpriseCitationDisplay(citations = []) {
  const items = citations.map((citation, index) => ({
    citation,
    displayNumber: index + 1,
    sourceOrder: positiveInteger(citation?.citation_order) || index + 1,
  }));
  return {
    items,
    bySourceOrder: new Map(items.map((item) => [item.sourceOrder, item])),
  };
}

export function formatEnterpriseCitationReferences(content = "", display) {
  return content.replace(ENTERPRISE_SOURCE_PATTERN, (_, rawOrder) => {
    const sourceOrder = positiveInteger(rawOrder);
    const item = sourceOrder ? display.bySourceOrder.get(sourceOrder) : null;
    return item
      ? `[${item.displayNumber}](${ENTERPRISE_CITATION_PREFIX}${sourceOrder})`
      : "[nguồn không khả dụng]";
  });
}

export function getEnterpriseCitationOrderFromHref(href = "") {
  if (!href.startsWith(ENTERPRISE_CITATION_PREFIX)) return null;
  return positiveInteger(href.slice(ENTERPRISE_CITATION_PREFIX.length));
}

export function buildEnterpriseSourcePreviewUrl(sourceUrl, page, quoteText, mimeType) {
  if (!sourceUrl || !String(mimeType || "").toLowerCase().includes("pdf")) {
    return sourceUrl || "";
  }
  const pageNumber = positiveInteger(page) || 1;
  const searchText = String(quoteText || "")
    .replace(/\s+/g, " ")
    .trim()
    .slice(0, 120);
  const params = new URLSearchParams({
    page: String(pageNumber),
    view: "FitH",
  });
  if (searchText) params.set("search", searchText);
  return `${sourceUrl.split("#", 1)[0]}#${params.toString()}`;
}
