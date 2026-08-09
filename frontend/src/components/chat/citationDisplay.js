const SOURCE_REFERENCE_PATTERN = /\[(SRC-[A-Za-z0-9_-]+)\]/g;
const PROTECTED_MARKDOWN_PATTERN = /(```[\s\S]*?```|~~~[\s\S]*?~~~|`[^`\n]*`)/g;
const CITATION_TARGET_PREFIX = '#citation-';

export function normalizeCitationSourceId(sourceId = '') {
  if (!sourceId) return '';
  return sourceId.startsWith('SRC-') ? sourceId : `SRC-${sourceId}`;
}

export function buildCitationNumbers(citations = []) {
  const numbers = new Map();
  citations.forEach((citation) => {
    const sourceId = normalizeCitationSourceId(citation?.source_id);
    if (sourceId && !numbers.has(sourceId)) {
      numbers.set(sourceId, numbers.size + 1);
    }
  });
  return numbers;
}

export function formatCitationReferences(content = '', citationNumbers) {
  return content.replace(SOURCE_REFERENCE_PATTERN, (reference, sourceId) => {
    const number = citationNumbers.get(sourceId);
    return number
      ? `[${number}](${CITATION_TARGET_PREFIX}${sourceId})`
      : '[nguồn không khả dụng]';
  });
}

export function getCitationSourceIdFromHref(href = '') {
  return href.startsWith(CITATION_TARGET_PREFIX)
    ? href.slice(CITATION_TARGET_PREFIX.length)
    : null;
}

export function normalizeMathDelimiters(content = '') {
  return content
    .split(PROTECTED_MARKDOWN_PATTERN)
    .map((segment, index) => {
      if (index % 2 === 1) return segment;
      return segment
        .replace(
          /\\\[([\s\S]*?)\\\]/g,
          (_, expression) => `\n$$\n${expression.trim()}\n$$\n`,
        )
        .replace(
          /\\\(([\s\S]*?)\\\)/g,
          (_, expression) => `$${expression.trim()}$`,
        );
    })
    .join('');
}
