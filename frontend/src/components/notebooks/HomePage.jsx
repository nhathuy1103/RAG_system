import React, { useEffect, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { motion, AnimatePresence } from 'motion/react';
import { Icon } from '@iconify/react';
import { useNotebookStore } from '../../stores/notebookStore.js';
import ConfirmModal from '../common/ConfirmModal.jsx';
import CreateNotebookModal from './CreateNotebookModal.jsx';

function formatDate(value) {
  if (!value) return '';
  return new Date(value).toLocaleDateString('vi-VN', {
    day: '2-digit',
    month: '2-digit',
    year: 'numeric',
  });
}

function NotebookCard({ nb, index, onOpen, onDelete }) {
  return (
    <motion.button
      layout
      initial={{ opacity: 0, y: 12 }}
      animate={{ opacity: 1, y: 0 }}
      exit={{ opacity: 0, scale: 0.96 }}
      transition={{ duration: 0.22, delay: Math.min(index, 8) * 0.03, ease: 'easeOut' }}
      onClick={onOpen}
      className="group relative flex flex-col items-start rounded-2xl border border-border bg-panel p-5 text-left transition-colors hover:border-accent/50 hover:bg-inset"
    >
      <div className="mb-3 flex h-11 w-11 items-center justify-center rounded-xl bg-accent/15 text-accent">
        <Icon icon="lucide:book" width={20} height={20} />
      </div>
      <div className="mb-1 line-clamp-1 font-heading text-[15px] font-semibold text-foreground">
        {nb.title}
      </div>
      <div className="mb-3 line-clamp-2 min-h-[36px] text-[13px] leading-relaxed text-dim">
        {nb.description || 'Chưa có mô tả'}
      </div>
      <div className="text-[11.5px] text-faint">Cập nhật {formatDate(nb.updated_at)}</div>

      <button
        onClick={(e) => { e.stopPropagation(); onDelete(); }}
        title="Xóa sổ tay"
        className="absolute right-3 top-3 rounded-md p-1.5 text-faint opacity-0 transition-opacity hover:bg-red/10 hover:text-red group-hover:opacity-100"
      >
        <Icon icon="lucide:trash" width={14} height={14} />
      </button>
    </motion.button>
  );
}

function CreateNotebookCard({ onClick }) {
  return (
    <motion.button
      initial={{ opacity: 0, y: 12 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ duration: 0.22, ease: 'easeOut' }}
      onClick={onClick}
      className="flex flex-col items-center justify-center gap-2.5 rounded-2xl border-2 border-dashed border-border p-5 text-dim transition-colors hover:border-accent hover:bg-accent/5 hover:text-accent"
      style={{ minHeight: 168 }}
    >
      <div className="flex h-11 w-11 items-center justify-center rounded-xl bg-inset">
        <Icon icon="lucide:plus" width={20} height={20} />
      </div>
      <div className="text-[13.5px] font-medium">Tạo sổ tay mới</div>
    </motion.button>
  );
}

export default function HomePage() {
  const navigate = useNavigate();
  const { notebooks, loading, fetchNotebooks, deleteNotebook } = useNotebookStore();
  const [isModalOpen, setIsModalOpen] = useState(false);
  const [nbToDelete, setNbToDelete] = useState(null);

  useEffect(() => {
    fetchNotebooks().catch((e) => console.error('Failed to fetch notebooks:', e));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const handleConfirmDelete = async () => {
    if (!nbToDelete) return;
    try {
      await deleteNotebook(nbToDelete);
    } finally {
      setNbToDelete(null);
    }
  };

  return (
    <div className="flex-1 overflow-y-auto px-8 py-8">
      <div className="mx-auto max-w-[1000px]">
        <div className="mb-7">
          <div className="font-heading text-2xl font-bold text-foreground">Sổ tay của bạn</div>
          <div className="mt-1 text-sm text-dim">Chọn 1 sổ tay để bắt đầu, hoặc tạo mới.</div>
        </div>

        {loading && notebooks.length === 0 ? (
          <div className="flex items-center justify-center py-24 text-sm text-faint">Đang tải...</div>
        ) : (
          <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-3">
            <AnimatePresence initial={false}>
              {notebooks.map((nb, index) => (
                <NotebookCard
                  key={nb.id}
                  nb={nb}
                  index={index}
                  onOpen={() => navigate(`/notebook/${nb.id}`)}
                  onDelete={() => setNbToDelete(nb.id)}
                />
              ))}
            </AnimatePresence>
            <CreateNotebookCard onClick={() => setIsModalOpen(true)} />
          </div>
        )}
      </div>

      <CreateNotebookModal
        isOpen={isModalOpen}
        onClose={() => setIsModalOpen(false)}
        onCreated={(nb) => navigate(`/notebook/${nb.id}`)}
      />

      <ConfirmModal
        isOpen={!!nbToDelete}
        title="Xóa Sổ Tay"
        message="Bạn có chắc muốn xóa sổ tay này và toàn bộ tài liệu bên trong? Hành động này không thể hoàn tác."
        onConfirm={handleConfirmDelete}
        onCancel={() => setNbToDelete(null)}
      />
    </div>
  );
}
