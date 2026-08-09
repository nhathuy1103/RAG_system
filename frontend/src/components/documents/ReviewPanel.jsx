import React, { useState } from 'react';

import KnowledgeQualityPanel from './KnowledgeQualityPanel.jsx';
import StructuredFactReviewPanel from './StructuredFactReviewPanel.jsx';

export default function ReviewPanel(props) {
  const [layer, setLayer] = useState('documents');

  return (
    <div className="min-h-0">
      <div
        role="tablist"
        aria-label="Lớp dữ liệu cần duyệt"
        className="mb-3 grid grid-cols-2 rounded-lg bg-inset p-1"
      >
        <button
          type="button"
          role="tab"
          aria-selected={layer === 'documents'}
          onClick={() => setLayer('documents')}
          className={`rounded-md px-2 py-1.5 text-[11px] font-medium transition-colors ${
            layer === 'documents'
              ? 'bg-panel text-foreground shadow-sm'
              : 'text-faint hover:text-foreground'
          }`}
        >
          Tài liệu
        </button>
        <button
          type="button"
          role="tab"
          aria-selected={layer === 'structured'}
          onClick={() => setLayer('structured')}
          className={`rounded-md px-2 py-1.5 text-[11px] font-medium transition-colors ${
            layer === 'structured'
              ? 'bg-panel text-foreground shadow-sm'
              : 'text-faint hover:text-foreground'
          }`}
        >
          Số liệu bảng
        </button>
      </div>

      {layer === 'documents' ? (
        <KnowledgeQualityPanel {...props} />
      ) : (
        <StructuredFactReviewPanel {...props} />
      )}
    </div>
  );
}
