import React from 'react';
import { motion, AnimatePresence } from 'motion/react';

export default function ConfirmModal({ isOpen, title, message, onConfirm, onCancel, confirmText = 'Xóa', cancelText = 'Hủy', isDanger = true }) {
  return (
    <AnimatePresence>
      {isOpen && (
        <motion.div
          initial={{ opacity: 0 }}
          animate={{ opacity: 1 }}
          exit={{ opacity: 0 }}
          transition={{ duration: 0.15 }}
          className="fixed inset-0 z-[1000] flex items-center justify-center bg-black/40 px-4"
        >
          <motion.div
            initial={{ opacity: 0, scale: 0.96, y: 8 }}
            animate={{ opacity: 1, scale: 1, y: 0 }}
            exit={{ opacity: 0, scale: 0.96, y: 8 }}
            transition={{ duration: 0.18, ease: 'easeOut' }}
            className="w-full max-w-[400px] rounded-xl border border-border bg-panel p-6 shadow-xl"
          >
            <div className="mb-3 font-heading text-lg font-semibold text-foreground">{title}</div>
            <div className="mb-6 text-sm leading-relaxed text-dim">{message}</div>
            <div className="flex justify-end gap-2.5">
              <button
                onClick={onCancel}
                className="rounded-lg border border-border bg-background px-4 py-2 text-sm font-medium text-foreground hover:bg-inset"
              >
                {cancelText}
              </button>
              <button
                onClick={onConfirm}
                className={`rounded-lg px-4 py-2 text-sm font-medium text-accent-foreground ${
                  isDanger ? 'bg-red hover:opacity-90' : 'bg-accent hover:bg-accent-dim'
                }`}
              >
                {confirmText}
              </button>
            </div>
          </motion.div>
        </motion.div>
      )}
    </AnimatePresence>
  );
}
