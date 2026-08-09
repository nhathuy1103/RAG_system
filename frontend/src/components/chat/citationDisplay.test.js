import assert from 'node:assert/strict';
import test from 'node:test';
import {
  buildCitationNumbers,
  formatCitationReferences,
  getCitationSourceIdFromHref,
  normalizeCitationSourceId,
  normalizeMathDelimiters,
} from './citationDisplay.js';

test('formats source aliases as clickable friendly sequential references', () => {
  const numbers = buildCitationNumbers([
    { source_id: 'SRC-1' },
    { source_id: 'SRC-2' },
  ]);
  assert.equal(
    formatCitationReferences('A [SRC-1], B [SRC-2], A again [SRC-1].', numbers),
    'A [1](#citation-SRC-1), B [2](#citation-SRC-2), A again [1](#citation-SRC-1).',
  );
});

test('hides an unknown technical source ID without assigning a wrong number', () => {
  const numbers = buildCitationNumbers([{ source_id: 'SRC-1' }]);
  assert.equal(
    formatCitationReferences('[SRC-UNKNOWN]', numbers),
    '[nguồn không khả dụng]',
  );
});

test('normalizes legacy backend IDs that omitted the SRC prefix', () => {
  const numbers = buildCitationNumbers([{ source_id: 'legacy-chunk-id' }]);
  assert.equal(normalizeCitationSourceId('legacy-chunk-id'), 'SRC-legacy-chunk-id');
  assert.equal(
    formatCitationReferences('[SRC-legacy-chunk-id]', numbers),
    '[1](#citation-SRC-legacy-chunk-id)',
  );
});

test('reads source aliases from internal citation links only', () => {
  assert.equal(getCitationSourceIdFromHref('#citation-SRC-2'), 'SRC-2');
  assert.equal(getCitationSourceIdFromHref('https://example.com'), null);
});

test('normalizes LaTeX delimiters supported by remark-math', () => {
  assert.equal(
    normalizeMathDelimiters(
      String.raw`Inline \(\sqrt{d_k}\) and block \[\frac{QK^T}{\sqrt{d_k}}\].`,
    ),
    'Inline $\\sqrt{d_k}$ and block \n$$\n\\frac{QK^T}{\\sqrt{d_k}}\n$$\n.',
  );
});

test('does not normalize math-like text inside inline or fenced code', () => {
  const content = [
    String.raw`Outside \(x\).`,
    'Inline code: `\\(\\text{literal}\\)`.',
    '```latex',
    String.raw`\[x + y\]`,
    '```',
  ].join('\n');

  const normalized = normalizeMathDelimiters(content);

  assert.match(normalized, /Outside \$x\$\./);
  assert.match(normalized, /`\\\(\\text\{literal\}\\\)`/);
  assert.match(normalized, /```latex\n\\\[x \+ y\\\]\n```/);
});
