import { create } from 'zustand';

import {
  getStructuredClaimRelationEvidence,
  getStructuredClaimRelations,
  resolveStructuredClaimRelation,
} from '../lib/api';
import { mergeUniqueById } from '../lib/quality.js';
import { requireStructuredReason } from '../lib/structuredFacts.js';

export const STRUCTURED_FACT_PAGE_SIZE = 20;

const emptyNotebookState = (notebookId = null) => ({
  notebookId,
  pendingRelations: [],
  pendingTotalCount: 0,
  pendingLoaded: false,
  pendingLoading: false,
  pendingLoadingMore: false,
  pendingError: null,
  relationEvidence: {},
  resolvingId: null,
});

const errorMessage = (error) => (
  error instanceof Error ? error.message : 'Đã xảy ra lỗi không xác định.'
);

const errorStatus = (error) => (
  typeof error?.status === 'number' ? error.status : null
);

const unavailableMessage = (status) => {
  if (status === 404) {
    return 'Dữ kiện này không còn tồn tại hoặc bạn không có quyền truy cập. Hàng đợi đã được cập nhật.';
  }
  if (status === 409) {
    return 'Dữ kiện đã được thay đổi bởi một phiên duyệt khác. Hàng đợi đã được làm mới; vui lòng kiểm tra lại trước khi quyết định.';
  }
  return null;
};

export const useStructuredFactStore = create((set, get) => ({
  ...emptyNotebookState(),

  resetForNotebook: (notebookId) => {
    set(emptyNotebookState(notebookId || null));
  },

  fetchPending: async (notebookId, { append = false } = {}) => {
    if (!notebookId) {
      set(emptyNotebookState());
      return [];
    }
    if (get().notebookId !== notebookId) {
      set(emptyNotebookState(notebookId));
    }

    const offset = append ? get().pendingRelations.length : 0;
    set({
      pendingLoading: !append,
      pendingLoadingMore: append,
      pendingError: null,
    });
    try {
      const response = await getStructuredClaimRelations(notebookId, {
        limit: STRUCTURED_FACT_PAGE_SIZE,
        offset,
      });
      if (get().notebookId !== notebookId) return [];
      const incoming = Array.isArray(response.items) ? response.items : [];
      set((state) => ({
        pendingRelations: append
          ? mergeUniqueById(state.pendingRelations, incoming)
          : incoming,
        pendingTotalCount: response.total_count,
        pendingLoaded: true,
        pendingLoading: false,
        pendingLoadingMore: false,
      }));
      return incoming;
    } catch (error) {
      if (get().notebookId === notebookId) {
        set({
          pendingError: errorMessage(error),
          pendingLoaded: true,
          pendingLoading: false,
          pendingLoadingMore: false,
        });
      }
      throw error;
    }
  },

  fetchEvidence: async (notebookId, relationId, { force = false } = {}) => {
    if (!notebookId || !relationId) return null;
    const existing = get().relationEvidence[relationId];
    if (!force && existing?.loaded && existing?.data) return existing.data;
    if (!force && existing?.loading) return existing?.data || null;

    set((state) => ({
      relationEvidence: {
        ...state.relationEvidence,
        [relationId]: {
          data: force ? null : existing?.data || null,
          loaded: false,
          loading: true,
          error: null,
        },
      },
    }));
    try {
      const evidence = await getStructuredClaimRelationEvidence(
        notebookId,
        relationId,
      );
      if (get().notebookId !== notebookId) return null;
      set((state) => ({
        relationEvidence: {
          ...state.relationEvidence,
          [relationId]: {
            data: evidence,
            loaded: true,
            loading: false,
            error: null,
          },
        },
      }));
      return evidence;
    } catch (error) {
      if (get().notebookId === notebookId) {
        const status = errorStatus(error);
        set((state) => {
          const relationEvidence = { ...state.relationEvidence };
          if (status === 404) {
            delete relationEvidence[relationId];
            return {
              pendingRelations: state.pendingRelations.filter(
                (item) => item.id !== relationId,
              ),
              pendingTotalCount: Math.max(0, state.pendingTotalCount - 1),
              pendingError: unavailableMessage(status),
              relationEvidence,
            };
          }
          relationEvidence[relationId] = {
            data: state.relationEvidence[relationId]?.data || null,
            loaded: true,
            loading: false,
            error: errorMessage(error),
          };
          return { relationEvidence };
        });
      }
      const statusMessage = unavailableMessage(errorStatus(error));
      throw new Error(statusMessage || errorMessage(error));
    }
  },

  resolveRelation: async (notebookId, relationId, action, reason) => {
    const normalizedReason = requireStructuredReason(reason);
    set({ resolvingId: relationId, pendingError: null });
    try {
      const current = get().pendingRelations.find(
        (item) => item.id === relationId,
      );
      if (!current) {
        throw new Error('Dữ kiện đã thay đổi; vui lòng làm mới hàng đợi.');
      }
      const relation = await resolveStructuredClaimRelation(
        notebookId,
        relationId,
        action,
        current.updated_at,
        normalizedReason,
      );
      if (get().notebookId !== notebookId) return relation;
      set((state) => {
        const relationEvidence = { ...state.relationEvidence };
        delete relationEvidence[relationId];
        return {
          pendingRelations: state.pendingRelations.filter(
            (item) => item.id !== relationId,
          ),
          pendingTotalCount: Math.max(0, state.pendingTotalCount - 1),
          relationEvidence,
          resolvingId: null,
        };
      });
      return relation;
    } catch (error) {
      if (get().notebookId !== notebookId) throw error;
      const status = errorStatus(error);
      const statusMessage = unavailableMessage(status);

      if (status === 404) {
        set((state) => {
          const relationEvidence = { ...state.relationEvidence };
          delete relationEvidence[relationId];
          return {
            pendingRelations: state.pendingRelations.filter(
              (item) => item.id !== relationId,
            ),
            pendingTotalCount: Math.max(0, state.pendingTotalCount - 1),
            relationEvidence,
            resolvingId: null,
            pendingError: statusMessage,
          };
        });
      } else if (status === 409) {
        set({ resolvingId: null });
        try {
          await get().fetchPending(notebookId);
        } catch {
          // The concurrency message is more actionable than a secondary refresh error.
        }
        if (get().notebookId === notebookId) {
          set((state) => {
            const relationEvidence = { ...state.relationEvidence };
            delete relationEvidence[relationId];
            return { relationEvidence, pendingError: statusMessage };
          });
        }
      } else {
        set({ resolvingId: null, pendingError: errorMessage(error) });
      }

      throw new Error(statusMessage || errorMessage(error));
    }
  },
}));
