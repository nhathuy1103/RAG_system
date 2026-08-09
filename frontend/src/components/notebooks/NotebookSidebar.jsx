import React, { useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { motion, AnimatePresence } from 'motion/react';
import { Icon } from '@iconify/react';
import { useNotebookStore } from '../../stores/notebookStore.js';
import { useUiStore } from '../../stores/uiStore.js';
import ConfirmModal from '../common/ConfirmModal.jsx';
import CreateNotebookModal from './CreateNotebookModal.jsx';

function NotebookItem({ nb, active, onClick, onDelete }) {
  const [hov, setHov] = useState(false);
  const dateStr = nb.created_at ? new Date(nb.created_at).toLocaleDateString('en-US', { month: 'short', day: 'numeric' }) : 'Unknown';

  return (
    <div
      onMouseEnter={() => setHov(true)}
      onMouseLeave={() => setHov(false)}
      className="relative"
    >
      <button
        onClick={onClick}
        className={`flex w-full items-center gap-2.5 rounded-lg px-3 py-2.5 text-left transition-colors ${
          active ? 'bg-accent/15' : hov ? 'bg-inset' : 'bg-transparent'
        }`}
      >
        <div
          className={`flex h-[30px] w-[30px] shrink-0 items-center justify-center rounded-lg ${
            active ? 'bg-accent/25 text-accent' : 'bg-inset text-faint'
          }`}
        >
          <Icon icon="lucide:book" width={16} height={16} />
        </div>
        <div className="min-w-0 flex-1" style={{ paddingRight: hov ? 24 : 0 }}>
          <div className={`truncate text-[13px] ${active ? 'font-semibold text-accent-dim' : 'font-medium text-foreground'}`}>
            {nb.title}
          </div>
          <div className={`mt-0.5 text-[11px] ${active ? 'text-accent' : 'text-faint'}`}>{dateStr}</div>
        </div>
      </button>
      {hov && (
        <button
          onClick={(e) => { e.stopPropagation(); onDelete(); }}
          title="Xóa sổ tay"
          className="absolute right-2 top-3 rounded p-1 text-red hover:opacity-80"
        >
          <Icon icon="lucide:trash" width={13} height={13} />
        </button>
      )}
    </div>
  );
}

export default function NotebookSidebar() {
  const navigate = useNavigate();
  const { notebooks, activeNotebook, deleteNotebook } = useNotebookStore();
  const sidebarOpen = useUiStore((state) => state.sidebarOpen);

  const [isModalOpen, setIsModalOpen] = useState(false);
  const [nbToDelete, setNbToDelete] = useState(null);

  const handleSelect = (nb) => {
    navigate(`/notebook/${nb.id}`);
  };

  const requestDelete = (nbId) => {
    setNbToDelete(nbId);
  };

  const handleConfirmDelete = async () => {
    if (!nbToDelete) return;
    try {
      await deleteNotebook(nbToDelete);
      if (activeNotebook?.id === nbToDelete) {
        navigate('/');
      }
    } finally {
      setNbToDelete(null);
    }
  };

  return (
    <>
      <motion.aside
        initial={false}
        animate={{
          width: sidebarOpen ? 240 : 0,
          borderRightWidth: sidebarOpen ? 1 : 0,
        }}
        transition={{ duration: 0.2, ease: 'easeInOut' }}
        style={{ borderRightColor: 'var(--border)', borderRightStyle: 'solid' }}
        className="flex shrink-0 flex-col overflow-hidden bg-panel"
      >
        <div className="flex items-center justify-between px-3.5 pb-2.5 pt-4">
          <span className="text-[11.5px] font-semibold uppercase tracking-wider text-faint">Sổ tay</span>
          <button
            onClick={() => setIsModalOpen(true)}
            className="flex h-[26px] w-[26px] items-center justify-center rounded-md border border-border bg-background text-dim transition-colors hover:border-accent hover:bg-accent hover:text-accent-foreground"
          >
            <Icon icon="lucide:plus" width={13} height={13} />
          </button>
        </div>
        <div className="flex-1 overflow-y-auto px-1.5 pb-4">
          <AnimatePresence initial={false}>
            {notebooks.map((nb) => (
              <motion.div
                key={nb.id}
                layout
                initial={{ opacity: 0, y: 6 }}
                animate={{ opacity: 1, y: 0 }}
                exit={{ opacity: 0, height: 0 }}
                transition={{ duration: 0.16, ease: 'easeOut' }}
              >
                <NotebookItem
                  nb={nb}
                  active={activeNotebook?.id === nb.id}
                  onClick={() => handleSelect(nb)}
                  onDelete={() => requestDelete(nb.id)}
                />
              </motion.div>
            ))}
          </AnimatePresence>
          {notebooks.length === 0 && (
            <div className="p-5 text-center text-[13px] text-faint">Chưa có sổ tay nào</div>
          )}
        </div>
        <div className="border-t border-border px-3.5 py-3">
          <div className="text-[11.5px] text-faint">AI Workspace</div>
          <div className="mt-0.5 text-[11px] text-faint/70">Unlimited notebooks</div>
        </div>
      </motion.aside>

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
    </>
  );
}
