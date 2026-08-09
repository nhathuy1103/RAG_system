import React, { useEffect } from 'react';
import { motion, AnimatePresence } from 'motion/react';
import { useToastStore } from '../../stores/toastStore.js';

const ACCENT_BY_SEVERITY = {
  success: 'border-l-green',
  error: 'border-l-red',
  warning: 'border-l-yellow',
  info: 'border-l-blue',
};

export default function ToastNotification() {
  const toast = useToastStore((state) => state.toast);
  const hideToast = useToastStore((state) => state.hideToast);

  useEffect(() => {
    if (!toast) return undefined;
    const timer = setTimeout(hideToast, 4000);
    return () => clearTimeout(timer);
  }, [toast, hideToast]);

  return (
    <div className="fixed top-16 right-5 z-50 w-full max-w-sm">
      <AnimatePresence>
        {toast && (
          <motion.div
            key={toast.id}
            initial={{ opacity: 0, y: -12, scale: 0.96 }}
            animate={{ opacity: 1, y: 0, scale: 1 }}
            exit={{ opacity: 0, x: 24, scale: 0.96 }}
            transition={{ duration: 0.2, ease: 'easeOut' }}
            className={`flex items-start gap-3 rounded-lg border border-border ${
              ACCENT_BY_SEVERITY[toast.severity] || 'border-l-accent'
            } border-l-4 bg-panel px-4 py-3 shadow-lg`}
          >
            <span className="flex-1 text-sm text-foreground">{toast.message}</span>
            <button
              type="button"
              onClick={hideToast}
              aria-label="Đóng thông báo"
              className="text-faint hover:text-foreground"
            >
              ×
            </button>
          </motion.div>
        )}
      </AnimatePresence>
    </div>
  );
}
