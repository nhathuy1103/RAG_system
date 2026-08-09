import { create } from 'zustand';

let nextToastId = 0;

export const useToastStore = create((set) => ({
  toast: null,

  showToast: (message, severity = 'success') => {
    nextToastId += 1;
    set({
      toast: {
        id: nextToastId,
        message,
        severity,
      },
    });
  },

  hideToast: () => {
    set({ toast: null });
  },
}));
