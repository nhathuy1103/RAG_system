import React, { useEffect, useState } from 'react';
import { getDocumentPreview } from '../../lib/api.ts';
import {
  buildPdfPreviewUrl,
  getPreviewErrorMessage,
} from './documentPreview.js';

export default function CitationModal({
  citation,
  citationNumber,
  notebookId,
  open,
  onClose,
  previewLoader = getDocumentPreview,
}) {
  const [previewUrl, setPreviewUrl] = useState(null);
  const [previewError, setPreviewError] = useState('');
  const [isLoadingPreview, setIsLoadingPreview] = useState(false);

  useEffect(() => {
    if (!open || !citation) return undefined;

    if (!notebookId || !citation.document_id) {
      setPreviewUrl(null);
      setPreviewError('Không xác định được tài liệu nguồn để xem trước.');
      setIsLoadingPreview(false);
      return undefined;
    }

    const controller = new AbortController();
    let objectUrl = null;
    setPreviewUrl(null);
    setPreviewError('');
    setIsLoadingPreview(true);

    previewLoader(notebookId, citation.document_id, controller.signal)
      .then((blob) => {
        objectUrl = URL.createObjectURL(blob);
        setPreviewUrl(buildPdfPreviewUrl(objectUrl, citation.page_number));
      })
      .catch((error) => {
        if (error?.name !== 'AbortError') {
          setPreviewError(getPreviewErrorMessage(error));
        }
      })
      .finally(() => {
        if (!controller.signal.aborted) {
          setIsLoadingPreview(false);
        }
      });

    return () => {
      controller.abort();
      if (objectUrl) URL.revokeObjectURL(objectUrl);
    };
  }, [
    citation?.document_id,
    citation?.page_number,
    notebookId,
    open,
    previewLoader,
  ]);

  if (!open || !citation) return null;

  return (
    <div
      className="fixed inset-0 z-[1000] flex items-center justify-start bg-black/40"
      onClick={onClose}
    >
      <div
        className="relative flex h-[650px] max-h-screen w-[550px] max-w-full flex-col overflow-hidden rounded-xl border border-border bg-panel shadow-xl"
        role="dialog"
        aria-modal="true"
        aria-label="Xem tài liệu nguồn"
        onClick={(event) => event.stopPropagation()}
      >
        <button
          type="button"
          onClick={onClose}
          className="absolute right-3 top-3 z-10 rounded-lg bg-accent px-3 py-1.5 text-sm font-medium text-accent-foreground shadow hover:bg-accent-dim"
        >
          Đóng
        </button>

        <div className="flex min-h-0 flex-1 flex-col">
          <div className="shrink-0 py-4 pl-6 pr-24">
            <div className="mb-1 text-xs font-semibold tracking-wide text-faint">TÀI LIỆU</div>
            <div className="flex items-center gap-2 font-medium text-foreground">
              <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" className="shrink-0 text-accent">
                <path d="M4 19.5A2.5 2.5 0 0 1 6.5 17H20" />
                <path d="M6.5 2H20v20H6.5A2.5 2.5 0 0 1 4 19.5v-15A2.5 2.5 0 0 1 6.5 2z" />
              </svg>
              {citation.document_title}
            </div>
          </div>

          <div className="flex min-h-0 flex-1 flex-col border-t border-border bg-inset">
            <div className="flex shrink-0 items-center gap-2 px-4 py-2.5">
              <span className="text-xs font-semibold text-faint">TRANG TÀI LIỆU GỐC</span>
              <span className="rounded-full border border-accent px-2 py-0.5 text-xs font-medium text-accent">
                Nguồn [{citationNumber}]
              </span>
            </div>
            <div className="relative min-h-0 flex-1 overflow-hidden border-t border-border bg-panel">
              {isLoadingPreview && (
                <div className="absolute inset-0 flex flex-col items-center justify-center gap-3 text-center text-sm text-faint">
                  <span className="h-7 w-7 animate-spin rounded-full border-2 border-border border-t-accent" />
                  Đang tải trang tài liệu…
                </div>
              )}
              {!isLoadingPreview && previewError && (
                <div className="absolute inset-0 flex items-center justify-center px-6 text-center text-sm leading-relaxed text-faint">
                  {previewError}
                </div>
              )}
              {!isLoadingPreview && previewUrl && (
                <iframe
                  src={previewUrl}
                  title={`${citation.document_title} — trang ${citation.page_number || 1}`}
                  className="h-full w-full border-0"
                />
              )}
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}
