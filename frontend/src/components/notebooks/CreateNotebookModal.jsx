import React, { useState } from 'react';
import { motion, AnimatePresence } from 'motion/react';
import { useNotebookStore } from '../../stores/notebookStore.js';
import { useToastStore } from '../../stores/toastStore.js';

export default function CreateNotebookModal({ isOpen, onClose, onCreated }) {
  const createNotebook = useNotebookStore((state) => state.createNotebook);
  const showToast = useToastStore((state) => state.showToast);

  const [title, setTitle] = useState('');
  const [description, setDescription] = useState('');
  const [isCreating, setIsCreating] = useState(false);

  const handleClose = () => {
    setTitle('');
    setDescription('');
    onClose();
  };

  const handleCreate = async (e) => {
    e.preventDefault();
    if (!title.trim()) return;
    setIsCreating(true);
    try {
      const newNb = await createNotebook(title, description);
      setTitle('');
      setDescription('');
      onClose();
      onCreated?.(newNb);
    } catch (err) {
      console.error('Failed to create notebook:', err);
      showToast(err.message || 'Lỗi khi tạo sổ tay', 'error');
    } finally {
      setIsCreating(false);
    }
  };

  return (
    <AnimatePresence>
      {isOpen && (
        <motion.div
          initial={{ opacity: 0 }}
          animate={{ opacity: 1 }}
          exit={{ opacity: 0 }}
          transition={{ duration: 0.15 }}
          className="fixed inset-0 z-[100] flex items-center justify-center bg-black/40 px-4"
        >
          <motion.div
            initial={{ opacity: 0, scale: 0.96, y: 8 }}
            animate={{ opacity: 1, scale: 1, y: 0 }}
            exit={{ opacity: 0, scale: 0.96, y: 8 }}
            transition={{ duration: 0.18, ease: 'easeOut' }}
            className="w-full max-w-[400px] rounded-xl border border-border bg-panel p-6 shadow-xl"
          >
            <div className="mb-4 font-heading text-lg font-semibold text-foreground">Tạo Sổ Tay Mới</div>
            <form onSubmit={handleCreate}>
              <div className="mb-3">
                <label className="mb-1.5 block text-[13px] font-medium text-dim">Tên sổ tay</label>
                <input
                  autoFocus
                  required
                  value={title}
                  onChange={(e) => setTitle(e.target.value)}
                  className="w-full rounded-lg border border-border bg-background px-3 py-2 text-sm text-foreground outline-none focus:border-accent"
                />
              </div>
              <div className="mb-5">
                <label className="mb-1.5 block text-[13px] font-medium text-dim">Mô tả (tùy chọn)</label>
                <textarea
                  rows={3}
                  value={description}
                  onChange={(e) => setDescription(e.target.value)}
                  className="w-full resize-y rounded-lg border border-border bg-background px-3 py-2 text-sm text-foreground outline-none focus:border-accent"
                />
              </div>
              <div className="flex justify-end gap-2.5">
                <button
                  type="button"
                  onClick={handleClose}
                  className="rounded-lg border border-border bg-background px-4 py-2 text-sm font-medium text-foreground hover:bg-inset"
                >
                  Hủy
                </button>
                <button
                  type="submit"
                  disabled={isCreating || !title.trim()}
                  className="rounded-lg bg-accent px-4 py-2 text-sm font-medium text-accent-foreground hover:bg-accent-dim disabled:opacity-60"
                >
                  {isCreating ? 'Đang tạo...' : 'Tạo mới'}
                </button>
              </div>
            </form>
          </motion.div>
        </motion.div>
      )}
    </AnimatePresence>
  );
}
