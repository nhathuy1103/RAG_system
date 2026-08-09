import React, { useMemo, useState } from 'react';
import ReactMarkdown from 'react-markdown';
import remarkMath from 'remark-math';
import rehypeKatex from 'rehype-katex';
import CitationModal from './CitationModal.jsx';
import {
  buildCitationNumbers,
  formatCitationReferences,
  getCitationSourceIdFromHref,
  normalizeCitationSourceId,
  normalizeMathDelimiters,
} from './citationDisplay.js';
import { Icon } from '@iconify/react';

function CitationChip({ label, onClick }) {
  const short = label.replace('.pdf', '').replace(/_/g, ' ');
  return (
    <button
      onClick={onClick}
      className="inline-flex items-center gap-1.5 rounded-full border border-accent/40 bg-accent/10 px-2.5 py-1 text-xs font-medium text-accent transition-colors hover:bg-accent/20"
    >
      <Icon icon="lucide:file" width={15} height={15} />
      {short}
    </button>
  );
}

export default function MarkdownMessage({ content, citations = [], notebookId }) {
  const [selectedCitation, setSelectedCitation] = useState(null);
  const citationNumbers = useMemo(() => buildCitationNumbers(citations), [citations]);
  const citationsBySourceId = useMemo(
    () => new Map(
      citations.map((citation) => [
        normalizeCitationSourceId(citation.source_id),
        citation,
      ]),
    ),
    [citations],
  );
  const displayContent = formatCitationReferences(
    normalizeMathDelimiters(content),
    citationNumbers,
  );

  return (
    <div className="markdown-body">
      <ReactMarkdown
        remarkPlugins={[remarkMath]}
        rehypePlugins={[rehypeKatex]}
        components={{
          a({ href, children }) {
            const sourceId = getCitationSourceIdFromHref(href);
            if (sourceId) {
              const citation = citationsBySourceId.get(sourceId);
              if (!citation) return <span className="citation-unavailable">[?]</span>;
              const number = citationNumbers.get(sourceId);
              const location = citation.page_or_section
                ? `, ${citation.page_or_section}`
                : '';
              return (
                <button
                  type="button"
                  className="citation-reference"
                  aria-label={`Xem nguồn ${number}: ${citation.document_title}${location}`}
                  title={`${citation.document_title}${location}`}
                  onClick={() => setSelectedCitation(citation)}
                >
                  [{children}]
                </button>
              );
            }
            return <a href={href}>{children}</a>;
          },
        }}
      >
        {displayContent}
      </ReactMarkdown>

      {citations.length > 0 && (
        <div className="mt-3 flex flex-wrap items-center gap-1.5 border-t border-border pt-2">
          <span className="text-xs font-semibold leading-[22px] text-faint">Nguồn tham khảo:</span>
          {citations.map((citation) => (
            <CitationChip
              key={citation.source_id}
              label={`[${citationNumbers.get(normalizeCitationSourceId(citation.source_id))}] ${citation.document_title || 'Tài liệu'} ${citation.page_or_section || ''}`}
              onClick={() => setSelectedCitation(citation)}
            />
          ))}
        </div>
      )}

      <CitationModal
        citation={selectedCitation}
        notebookId={notebookId}
        citationNumber={
          selectedCitation
            ? citationNumbers.get(normalizeCitationSourceId(selectedCitation.source_id))
            : null
        }
        open={Boolean(selectedCitation)}
        onClose={() => setSelectedCitation(null)}
      />
    </div>
  );
}
