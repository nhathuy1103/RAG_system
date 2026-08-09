import { create } from 'zustand';
import {
  getDocumentRelationEvidence,
  getDocumentRelationAudit,
  getDocumentRelations,
  resolveDocumentRelation,
  revertDocumentRelation,
} from '../lib/api';
import {
  mergeUniqueById,
  requireQualityReason,
} from '../lib/quality.js';

export const QUALITY_PAGE_SIZE = 20;

const emptyNotebookState = (notebookId = null) => ({
  notebookId,
  pendingRelations: [],
  pendingTotalCount: 0,
  pendingLoaded: false,
  pendingLoading: false,
  pendingLoadingMore: false,
  pendingError: null,
  auditEvents: [],
  auditTotalCount: 0,
  auditLoaded: false,
  auditLoading: false,
  auditLoadingMore: false,
  auditError: null,
  relationAudits: {},
  relationEvidence: {},
  resolvingId: null,
  revertingId: null,
});

const errorMessage = (error) => (
  error instanceof Error ? error.message : 'Đã xảy ra lỗi không xác định.'
);

export const useQualityStore = create((set, get) => ({
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

    const currentItems = append ? get().pendingRelations : [];
    const offset = currentItems.length;
    set({
      pendingLoading: !append,
      pendingLoadingMore: append,
      pendingError: null,
    });
    try {
      const response = await getDocumentRelations(notebookId, {
        status: 'pending',
        limit: QUALITY_PAGE_SIZE,
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

  fetchAuditEvents: async (notebookId, { append = false } = {}) => {
    if (!notebookId) {
      set(emptyNotebookState());
      return [];
    }
    if (get().notebookId !== notebookId) {
      set(emptyNotebookState(notebookId));
    }

    const currentItems = append ? get().auditEvents : [];
    const offset = currentItems.length;
    set({
      auditLoading: !append,
      auditLoadingMore: append,
      auditError: null,
    });
    try {
      const response = await getDocumentRelationAudit(notebookId, {
        limit: QUALITY_PAGE_SIZE,
        offset,
      });
      if (get().notebookId !== notebookId) return [];
      const incoming = Array.isArray(response.items) ? response.items : [];
      set((state) => ({
        auditEvents: append
          ? mergeUniqueById(state.auditEvents, incoming)
          : incoming,
        auditTotalCount: response.total_count,
        auditLoaded: true,
        auditLoading: false,
        auditLoadingMore: false,
      }));
      return incoming;
    } catch (error) {
      if (get().notebookId === notebookId) {
        set({
          auditError: errorMessage(error),
          auditLoaded: true,
          auditLoading: false,
          auditLoadingMore: false,
        });
      }
      throw error;
    }
  },

  fetchRelationAudit: async (
    notebookId,
    relationId,
    { append = false } = {},
  ) => {
    if (!notebookId || !relationId) return [];
    const existing = get().relationAudits[relationId];
    const currentItems = append ? existing?.items || [] : [];
    const offset = currentItems.length;
    set((state) => ({
      relationAudits: {
        ...state.relationAudits,
        [relationId]: {
          items: currentItems,
          totalCount: existing?.totalCount || 0,
          loaded: existing?.loaded || false,
          loading: !append,
          loadingMore: append,
          error: null,
        },
      },
    }));
    try {
      const response = await getDocumentRelationAudit(notebookId, {
        relationId,
        limit: QUALITY_PAGE_SIZE,
        offset,
      });
      if (get().notebookId !== notebookId) return [];
      const incoming = Array.isArray(response.items) ? response.items : [];
      set((state) => {
        const latest = state.relationAudits[relationId];
        return {
          relationAudits: {
            ...state.relationAudits,
            [relationId]: {
              items: append
                ? mergeUniqueById(latest?.items || [], incoming)
                : incoming,
              totalCount: response.total_count,
              loaded: true,
              loading: false,
              loadingMore: false,
              error: null,
            },
          },
        };
      });
      return incoming;
    } catch (error) {
      if (get().notebookId === notebookId) {
        set((state) => ({
          relationAudits: {
            ...state.relationAudits,
            [relationId]: {
              items: state.relationAudits[relationId]?.items || [],
              totalCount: state.relationAudits[relationId]?.totalCount || 0,
              loaded: true,
              loading: false,
              loadingMore: false,
              error: errorMessage(error),
            },
          },
        }));
      }
      throw error;
    }
  },

  fetchRelationEvidence: async (notebookId, relationId, options = {}) => {
    if (!notebookId || !relationId) return null;
    const force = Boolean(options.force);
    const existing = get().relationEvidence[relationId];
    if (!force && existing?.loaded && existing?.data) return existing.data;
    if (!force && existing?.loading) return existing.data || null;

    set((state) => ({
      relationEvidence: {
        ...state.relationEvidence,
        [relationId]: {
          data: force ? null : existing?.data || null,
          loaded: force ? false : existing?.loaded || false,
          loading: true,
          error: null,
        },
      },
    }));
    try {
      const evidence = await getDocumentRelationEvidence(notebookId, relationId);
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
        set((state) => ({
          relationEvidence: {
            ...state.relationEvidence,
            [relationId]: {
              data: state.relationEvidence[relationId]?.data || null,
              loaded: true,
              loading: false,
              error: errorMessage(error),
            },
          },
        }));
      }
      throw error;
    }
  },

  resolveRelation: async (
    notebookId,
    relationId,
    action,
    reason,
  ) => {
    const normalizedReason = requireQualityReason(reason);
    set({ resolvingId: relationId, pendingError: null });
    try {
      const currentRelation = get().pendingRelations.find(
        (item) => item.id === relationId,
      );
      if (!currentRelation) {
        throw new Error('Đề xuất đã thay đổi; vui lòng làm mới hàng đợi.');
      }
      const relation = await resolveDocumentRelation(
        notebookId,
        relationId,
        action,
        currentRelation.updated_at,
        normalizedReason,
      );
      if (get().notebookId !== notebookId) return relation;
      set((state) => {
        const nextRelationAudits = { ...state.relationAudits };
        const nextRelationEvidence = { ...state.relationEvidence };
        delete nextRelationAudits[relationId];
        delete nextRelationEvidence[relationId];
        return {
          pendingRelations: state.pendingRelations.filter(
            (item) => item.id !== relationId,
          ),
          pendingTotalCount: Math.max(0, state.pendingTotalCount - 1),
          auditEvents: [],
          auditTotalCount: 0,
          auditLoaded: false,
          relationAudits: nextRelationAudits,
          relationEvidence: nextRelationEvidence,
          resolvingId: null,
        };
      });
      return relation;
    } catch (error) {
      if (get().notebookId === notebookId) {
        set({
          pendingError: errorMessage(error),
          resolvingId: null,
        });
      }
      throw error;
    }
  },

  revertRelation: async (
    notebookId,
    relationId,
    expectedUpdatedAt,
    reason,
  ) => {
    const normalizedReason = requireQualityReason(reason, 'revert');
    set({ revertingId: relationId, auditError: null });
    try {
      const relation = await revertDocumentRelation(
        notebookId,
        relationId,
        expectedUpdatedAt,
        normalizedReason,
      );
      if (get().notebookId !== notebookId) return relation;
      set((state) => {
        const nextRelationAudits = { ...state.relationAudits };
        const nextRelationEvidence = { ...state.relationEvidence };
        delete nextRelationAudits[relationId];
        delete nextRelationEvidence[relationId];
        const alreadyPending = state.pendingRelations.some(
          (item) => item.id === relationId,
        );
        const restoredPending = relation.status === 'pending' && !alreadyPending;
        return {
          pendingRelations: restoredPending
            ? [relation, ...state.pendingRelations]
            : state.pendingRelations,
          pendingTotalCount: restoredPending
            ? state.pendingTotalCount + 1
            : state.pendingTotalCount,
          auditEvents: [],
          auditTotalCount: 0,
          auditLoaded: false,
          relationAudits: nextRelationAudits,
          relationEvidence: nextRelationEvidence,
          revertingId: null,
        };
      });
      return relation;
    } catch (error) {
      if (get().notebookId === notebookId) {
        set({
          auditError: errorMessage(error),
          revertingId: null,
        });
      }
      throw error;
    }
  },
}));
