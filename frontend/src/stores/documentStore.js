import { create } from 'zustand';
import * as documentsApi from '../lib/api';

const TERMINAL_DOCUMENT_STATUSES = new Set(['uploaded', 'ready', 'failed']);

function uploadedDocuments(response) {
  return (response.items || [])
    .map((item) => item.document)
    .filter(Boolean);
}

function mergeUploadedDocuments(currentDocuments, newDocuments) {
  const uploadedIds = new Set(newDocuments.map((document) => document.id));
  return [
    ...newDocuments,
    ...currentDocuments.filter((document) => !uploadedIds.has(document.id)),
  ];
}

export const useDocumentStore = create((set, get) => ({
  documents: [],
  totalCount: 0,
  selectedDocumentIds: [],
  loading: false,
  uploading: false,
  error: null,

  fetchDocuments: async (notebookId) => {
    if (!notebookId) {
      set({ documents: [], totalCount: 0, selectedDocumentIds: [], loading: false });
      return [];
    }
    set({ loading: true, error: null });
    try {
      const res = await documentsApi.getDocuments(notebookId);
      const items = res.items || [];
      set({ documents: items, totalCount: res.total_count, loading: false });
      // Clean up selectedIds if deleted
      const currentIds = new Set(items.map((doc) => doc.id));
      set((state) => ({
        selectedDocumentIds: state.selectedDocumentIds.filter((id) => currentIds.has(id)),
      }));
      return items;
    } catch (err) {
      set({ error: err.message, loading: false });
      throw err;
    }
  },

  loadMoreDocuments: async (notebookId) => {
    const offset = get().documents.length;
    set({ loading: true, error: null });
    try {
      const res = await documentsApi.getDocuments(notebookId, { offset });
      set((state) => {
        const existingIds = new Set(state.documents.map((document) => document.id));
        const newItems = res.items.filter((document) => !existingIds.has(document.id));
        return {
          documents: [...state.documents, ...newItems],
          totalCount: res.total_count,
          loading: false,
        };
      });
      return res.items;
    } catch (err) {
      set({ error: err.message, loading: false });
      throw err;
    }
  },

  uploadFile: async (file, notebookId) => {
    set({ uploading: true, error: null });
    try {
      const res = await documentsApi.uploadDocument(file, notebookId);
      const createdDocuments = uploadedDocuments(res);
      set((state) => ({
        documents: mergeUploadedDocuments(state.documents, createdDocuments),
        totalCount: state.totalCount + createdDocuments.length,
        uploading: false,
      }));
      return res;
    } catch (err) {
      set({ error: err.message, uploading: false });
      throw err;
    }
  },

  uploadFiles: async (files, notebookId) => {
    set({ uploading: true, error: null });
    try {
      const res = await documentsApi.uploadDocuments(files, notebookId);
      const createdDocuments = uploadedDocuments(res);
      set((state) => ({
        documents: mergeUploadedDocuments(state.documents, createdDocuments),
        totalCount: state.totalCount + createdDocuments.length,
        uploading: false,
      }));
      return res;
    } catch (err) {
      set({ error: err.message, uploading: false });
      throw err;
    }
  },

  uploadUrl: async (url, title = null, notebookId = null) => {
    set({ uploading: true, error: null });
    try {
      const res = await documentsApi.uploadUrl(url, title, notebookId);
      await get().fetchDocuments(notebookId);
      set({ uploading: false });
      return res;
    } catch (err) {
      set({ error: err.message, uploading: false });
      throw err;
    }
  },

  uploadText: async (title, content, notebookId = null) => {
    set({ uploading: true, error: null });
    try {
      const res = await documentsApi.uploadText(title, content, notebookId);
      await get().fetchDocuments(notebookId);
      set({ uploading: false });
      return res;
    } catch (err) {
      set({ error: err.message, uploading: false });
      throw err;
    }
  },

  toggleSelectDocument: (docId) => {
    set((state) => {
      const exists = state.selectedDocumentIds.includes(docId);
      if (exists) {
        return { selectedDocumentIds: state.selectedDocumentIds.filter((id) => id !== docId) };
      } else {
        return { selectedDocumentIds: [...state.selectedDocumentIds, docId] };
      }
    });
  },

  selectAllDocuments: () => {
    const allIds = get().documents.map((doc) => doc.id);
    set({ selectedDocumentIds: allIds });
  },

  clearSelectedDocuments: () => {
    set({ selectedDocumentIds: [] });
  },

  deleteDocument: async (docId, notebookId = null) => {
    set({ error: null });
    try {
      const result = await documentsApi.deleteDocument(docId, notebookId);
      await get().fetchDocuments(notebookId);
      return result;
    } catch (err) {
      set({ error: err.message });
      throw err;
    }
  },

  pollDocumentStatuses: async (notebookId = null) => {
    try {
      const hasActiveDocuments = get().documents.some(
        (doc) => !TERMINAL_DOCUMENT_STATUSES.has(doc.status)
      );
      if (!hasActiveDocuments) return;

      const res = await documentsApi.getDocuments(notebookId, {
        limit: Math.min(Math.max(get().documents.length, 50), 100),
      });
      if (res.items) {
        set({ documents: res.items, totalCount: res.total_count });
      }
    } catch (e) {
      console.error('Failed to poll document statuses', e);
    }
  },
}));
