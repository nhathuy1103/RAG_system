import React, { useState, useEffect, useRef } from 'react';
import { motion, AnimatePresence } from 'motion/react';
import { Icon } from '@iconify/react';
import { useDocumentStore } from '../../stores/documentStore.js';
import { useNotebookStore } from '../../stores/notebookStore.js';
import { useToastStore } from '../../stores/toastStore.js';
import ConfirmModal from '../common/ConfirmModal.jsx';
import ReviewPanel from './ReviewPanel.jsx';

const isReadyStatus = (status) => {
  return ['uploaded', 'UPLOADED', 'ready', 'INDEXED'].includes(status);
};
const isFailedStatus = (status) => {
  return ['failed', 'FAILED'].includes(status);
};

function SourceRow({ doc, isSelected, onToggle, onRemove }) {
  const isReady = isReadyStatus(doc.status);
  const isFailed = isFailedStatus(doc.status);
  const versionNumber = doc.version_number || 1;
  const qualityLabel = {
    duplicate: 'Bản trùng',
    superseded: 'Bản cũ',
    conflict: 'Xung đột',
    review_required: 'Cần duyệt',
  }[doc.quality_status];

  return (
    <motion.div
      layout
      initial={{ opacity: 0, y: 6 }}
      animate={{ opacity: 1, y: 0 }}
      exit={{ opacity: 0, height: 0, marginBottom: 0 }}
      transition={{ duration: 0.18, ease: 'easeOut' }}
      className={`mb-1 flex items-center gap-2.5 rounded-lg border px-3 py-2.5 transition-colors ${
        isSelected ? 'border-accent/40 bg-accent/10' : 'border-transparent hover:bg-inset'
      }`}
    >
      <input
        type="checkbox"
        checked={isSelected}
        onChange={onToggle}
        className="h-4 w-4 shrink-0 cursor-pointer accent-[var(--accent)]"
      />
      <Icon icon="vscode-icons:file-type-pdf2" width={28} height={28} />
      <div className="min-w-0 flex-1">
        <div className="truncate text-[13px] font-medium text-foreground">{doc.original_filename}</div>
        <div className="mt-0.5 text-[11.5px] text-faint">
          {versionNumber > 1 ? `v${versionNumber} · ` : ''}
          {!doc.is_current && !doc.canonical_document_id ? 'Lịch sử · ' : ''}
          Trạng thái: {doc.status}
        </div>
      </div>
      <div className="flex shrink-0 items-center gap-1.5">
        {qualityLabel ? (
          <span className={`rounded-full border px-2 py-0.5 text-[11px] font-medium ${
            doc.quality_status === 'conflict'
              ? 'border-red/40 bg-red/10 text-red'
              : 'border-yellow/40 bg-yellow/10 text-yellow'
          }`}>
            {qualityLabel}
          </span>
        ) : isFailed ? (
          <span className="rounded-full border border-red/40 bg-red/10 px-2 py-0.5 text-[11px] font-medium text-red">Lỗi</span>
        ) : !isReady ? (
          <span className="rounded-full border border-yellow/40 bg-yellow/10 px-2 py-0.5 text-[11px] font-medium text-yellow">Đang xử lý…</span>
        ) : (
          <span className="rounded-full border border-green/40 bg-green/10 px-2 py-0.5 text-[11px] font-medium text-green">Sẵn sàng</span>
        )}
        <button onClick={onRemove} className="rounded p-0.5 text-faint hover:text-red">
          <Icon icon="lucide:trash" width={13} height={13} />
        </button>
      </div>
    </motion.div>
  );
}

export default function DocumentPanel() {
  const { activeNotebook } = useNotebookStore();
  const showToast = useToastStore((state) => state.showToast);
  const {
    documents, totalCount, selectedDocumentIds,
    loading, uploading, fetchDocuments, loadMoreDocuments,
    uploadFiles, uploadUrl, uploadText,
    toggleSelectDocument, selectAllDocuments, clearSelectedDocuments,
    deleteDocument, pollDocumentStatuses,
  } = useDocumentStore();

  const [activeTab, setActiveTab] = useState('files');
  const [dragOver, setDragOver] = useState(false);
  const [urlInput, setUrlInput] = useState('');
  const [urlTitle, setUrlTitle] = useState('');
  const [docToDelete, setDocToDelete] = useState(null);
  const fileInputRef = useRef(null);

  useEffect(() => {
    if (!activeNotebook) return;
    const interval = setInterval(() => {
      pollDocumentStatuses(activeNotebook.id);
    }, 3000);
    return () => clearInterval(interval);
  }, [activeNotebook, pollDocumentStatuses]);

  const handleFileAdd = async (files) => {
    if (!activeNotebook) {
      showToast('Vui lòng chọn hoặc tạo sổ tay trước', 'error');
      return;
    }
    if (files.length === 0) return;
    if (files.length > 20) {
      showToast('Chỉ có thể tải lên tối đa 20 file mỗi lần', 'error');
      files = files.slice(0, 20);
    }
    try {
      const result = await uploadFiles(files, activeNotebook.id);
      const items = result?.items || [];
      const duplicateItems = items.filter((item) => item.duplicate);
      const newCount = (result?.succeeded_count || 0) - duplicateItems.length;

      const messages = [];
      let severity = 'success';

      if (result?.failed_count > 0) {
        const reasons = items
          .filter((item) => item.error_message)
          .map((item) => `${item.filename}: ${item.error_message}`)
          .join(' | ');
        messages.push(`${result.failed_count} file tải lên thất bại. ${reasons}`);
        severity = 'error';
      }
      if (duplicateItems.length > 0) {
        const names = duplicateItems.map((item) => item.filename).join(', ');
        messages.push(
          `${duplicateItems.length} file đã có sẵn trong sổ tay (${names}) — dùng lại bản cũ, không tải lên lại.`,
        );
        if (severity === 'success') severity = 'info';
      }
      if (newCount > 0) {
        messages.push(`Đã tải lên ${newCount} file.`);
      }
      if (messages.length > 0) {
        showToast(messages.join(' '), severity);
      }
    } catch (err) {
      showToast(err.message || 'Tải file thất bại', 'error');
    }
  };

  const handleUploadUrl = async (e) => {
    e.preventDefault();
    if (!urlInput.trim()) return;
    try {
      await uploadUrl(urlInput, urlTitle || null, activeNotebook?.id);
      setUrlInput('');
      setUrlTitle('');
      showToast('Đã thêm URL thành công', 'success');
    } catch (err) {
      showToast(err.message || 'Thêm URL thất bại', 'error');
    }
  };

  const requestDeleteDocument = (document) => {
    setDocToDelete(document);
  };

  const handleConfirmDelete = async () => {
    if (!docToDelete) return;
    try {
      await deleteDocument(docToDelete.id, activeNotebook?.id);
      showToast(`Đã xoá tài liệu "${docToDelete.original_filename}".`, 'success');
    } catch (err) {
      showToast(err.message || 'Không thể xoá tài liệu', 'error');
    } finally {
      setDocToDelete(null);
    }
  };

  return (
    <div className="sources-panel flex w-[320px] shrink-0 flex-col overflow-hidden border-r border-border bg-panel">
      <div className="border-b border-border px-4 pt-4">
        <div className="mb-3 flex items-center justify-between">
          <div>
            <div className="font-heading text-sm font-bold text-foreground">Nguồn dữ liệu</div>
            <div className="mt-0.5 text-[11.5px] text-faint">{totalCount} tài liệu</div>
          </div>
          <button
            onClick={() => fileInputRef.current?.click()}
            disabled={uploading || !activeNotebook}
            className="flex h-[30px] items-center gap-1.5 rounded-lg bg-accent px-3 text-xs font-semibold text-accent-foreground hover:bg-accent-dim disabled:cursor-not-allowed disabled:opacity-60"
          >
            {uploading ? 'Đang tải...' : <><Icon icon="lucide:plus" width={12} height={12} /> Thêm</>}
          </button>
        </div>
        <div className="flex">
          {[
            ['files', 'Files'],
            ['urls', 'URLs'],
            ['text', 'Dán chữ'],
            ['quality', 'Duyệt'],
          ].map(([tab, label]) => (
            <button
              key={tab}
              onClick={() => setActiveTab(tab)}
              className={`h-[34px] flex-1 border-b-2 text-[11.5px] font-medium transition-colors ${
                activeTab === tab ? 'border-accent text-accent' : 'border-transparent text-faint'
              }`}
            >
              {label}
            </button>
          ))}
        </div>
      </div>

      <div className="flex-1 overflow-y-auto p-3">
        {activeTab === 'files' && (
          <>
            <div
              onClick={() => activeNotebook && !uploading && fileInputRef.current?.click()}
              onDragOver={(e) => { e.preventDefault(); if (activeNotebook) setDragOver(true); }}
              onDragLeave={() => setDragOver(false)}
              onDrop={(e) => {
                e.preventDefault();
                setDragOver(false);
                if (activeNotebook && !uploading) {
                  handleFileAdd(Array.from(e.dataTransfer.files));
                }
              }}
              className={`mb-3 rounded-xl border-2 border-dashed p-5 text-center transition-colors ${
                dragOver ? 'border-accent bg-accent/10' : 'border-border bg-inset'
              } ${!activeNotebook || uploading ? 'cursor-not-allowed opacity-60' : 'cursor-pointer'}`}
            >
              <div className="mb-2 flex justify-center text-accent"><Icon icon="lucide:upload-cloud" width={22} height={22} /></div>
              <div className="mb-0.5 text-[13px] font-semibold text-foreground">Kéo thả file vào đây</div>
              <div className="text-[11.5px] text-faint">PDF, DOCX, TXT, HTML · Tối đa 20 file</div>
            </div>
            <input
              ref={fileInputRef}
              type="file"
              accept=".pdf,.docx,.pptx,.xlsx,.csv,.md,.html,.txt"
              multiple
              className="hidden"
              onChange={(e) => { handleFileAdd(Array.from(e.target.files || [])); e.target.value = ''; }}
            />
          </>
        )}

        {activeTab === 'urls' && (
          <form onSubmit={handleUploadUrl} className="mb-3 px-1 py-2">
            <div className="mb-2.5 text-[13px] font-medium text-dim">Thêm URL trang web</div>
            <div className="flex flex-col gap-2">
              <input
                value={urlInput}
                onChange={(e) => setUrlInput(e.target.value)}
                placeholder="https://example.com/article"
                className="h-9 w-full rounded-lg border border-border bg-background px-3 text-[13px] text-foreground outline-none focus:border-accent"
              />
              <input
                value={urlTitle}
                onChange={(e) => setUrlTitle(e.target.value)}
                placeholder="Tiêu đề (tùy chọn)"
                className="h-9 w-full rounded-lg border border-border bg-background px-3 text-[13px] text-foreground outline-none focus:border-accent"
              />
              <button
                type="submit"
                disabled={!urlInput.trim() || uploading || !activeNotebook}
                className="h-9 rounded-lg bg-accent text-[13px] font-semibold text-accent-foreground hover:bg-accent-dim disabled:cursor-not-allowed disabled:opacity-60"
              >
                {uploading ? 'Đang thêm...' : 'Thêm'}
              </button>
            </div>
          </form>
        )}

        {activeTab === 'quality' ? (
          <ReviewPanel
            notebookId={activeNotebook?.id}
            documents={documents}
            showToast={showToast}
            onResolved={() => fetchDocuments(activeNotebook?.id)}
          />
        ) : (
          <>
            {documents.length > 0 && (
              <div className="mb-2 flex items-center justify-between px-1">
                <label className="flex cursor-pointer items-center gap-1.5 text-xs text-dim">
                  <input
                    type="checkbox"
                    checked={selectedDocumentIds.length === documents.length}
                    onChange={(e) => (e.target.checked ? selectAllDocuments() : clearSelectedDocuments())}
                    className="cursor-pointer accent-[var(--accent)]"
                  />
                  Chọn tất cả ({selectedDocumentIds.length}/{documents.length})
                </label>
              </div>
            )}

            <AnimatePresence initial={false}>
              {documents.map((doc) => (
                <SourceRow
                  key={doc.id}
                  doc={doc}
                  isSelected={selectedDocumentIds.includes(doc.id)}
                  onToggle={() => toggleSelectDocument(doc.id)}
                  onRemove={() => requestDeleteDocument(doc)}
                />
              ))}
            </AnimatePresence>

            {documents.length < totalCount && (
              <div className="mt-3 text-center">
                <button
                  onClick={() => loadMoreDocuments(activeNotebook.id)}
                  disabled={loading}
                  className="rounded-full border border-border bg-background px-3 py-1.5 text-xs text-dim hover:bg-inset"
                >
                  {loading ? 'Đang tải...' : 'Tải thêm'}
                </button>
              </div>
            )}
          </>
        )}
      </div>
      <ConfirmModal
        isOpen={!!docToDelete}
        title="Xóa tài liệu"
        message={`Bạn có chắc chắn muốn xóa tài liệu "${docToDelete?.original_filename}" không?`}
        onConfirm={handleConfirmDelete}
        onCancel={() => setDocToDelete(null)}
      />
    </div>
  );
}
