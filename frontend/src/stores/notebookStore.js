import { create } from 'zustand';
import * as notebooksApi from '../lib/api';

export const useNotebookStore = create((set) => ({
  notebooks: [],
  activeNotebook: null,
  loading: false,
  error: null,

  fetchNotebooks: async () => {
    set({ loading: true, error: null });
    try {
      const res = await notebooksApi.getNotebooks();
      const items = Array.isArray(res) ? res : [];
      // No auto-select notebook.
      set({ notebooks: items, loading: false });
      return items;
    } catch (err) {
      set({ error: err.message, loading: false });
      throw err;
    }
  },

  selectNotebook: (notebook) => {
    set({ activeNotebook: notebook });
  },

  createNotebook: async (title, description = '') => {
    set({ loading: true, error: null });
    try {
      const newNb = await notebooksApi.createNotebook(title, description);
      set((state) => ({
        notebooks: [newNb, ...state.notebooks],
        activeNotebook: newNb,
        loading: false,
      }));
      return newNb;
    } catch (err) {
      set({ error: err.message, loading: false });
      throw err;
    }
  },

  updateNotebook: async (id, data) => {
    try {
      const updated = await notebooksApi.updateNotebook(id, data);
      set((state) => ({
        notebooks: state.notebooks.map((nb) => (nb.id === id ? updated : nb)),
        activeNotebook: state.activeNotebook?.id === id ? updated : state.activeNotebook,
      }));
      return updated;
    } catch (err) {
      set({ error: err.message });
      throw err;
    }
  },

  deleteNotebook: async (id) => {
    try {
      await notebooksApi.deleteNotebook(id);
      set((state) => {
        const filtered = state.notebooks.filter((nb) => nb.id !== id);
        return {
          notebooks: filtered,
          activeNotebook: state.activeNotebook?.id === id ? (filtered[0] || null) : state.activeNotebook,
        };
      });
    } catch (err) {
      set({ error: err.message });
      throw err;
    }
  },
}));
