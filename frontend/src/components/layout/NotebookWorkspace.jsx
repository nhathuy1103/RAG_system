import React, { useEffect } from 'react';
import { useParams, useNavigate } from 'react-router-dom';
import { Icon } from '@iconify/react';
import NotebookSidebar from '../notebooks/NotebookSidebar.jsx';
import DocumentPanel from '../documents/DocumentPanel.jsx';
import ChatPanel from '../chat/ChatPanel.jsx';
import { useNotebookStore } from '../../stores/notebookStore.js';
import { useDocumentStore } from '../../stores/documentStore.js';

// URL is source of truth for the active notebook.
export default function NotebookWorkspace() {
  const { notebookId } = useParams();
  const navigate = useNavigate();
  const { notebooks, activeNotebook, selectNotebook, loading: nbLoading, fetchNotebooks } =
    useNotebookStore();
  const { fetchDocuments } = useDocumentStore();

  useEffect(() => {
    if (notebooks.length === 0 && !nbLoading) {
      fetchNotebooks().catch((e) => console.error('Failed to fetch notebooks:', e));
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  useEffect(() => {
    if (!notebookId) return;
    const found = notebooks.find((nb) => nb.id === notebookId);
    if (found) {
      selectNotebook(found);
      fetchDocuments(found.id).catch((e) => console.error('Failed to fetch docs:', e));
    } else if (!nbLoading && notebooks.length > 0) {
      // Notebooks finished loading and this id isn't in the list - either it
      // was deleted or it doesn't belong to this user. Back to the grid.
      navigate('/', { replace: true });
    }
  }, [notebookId, notebooks, nbLoading, selectNotebook, fetchDocuments, navigate]);

  if (nbLoading && notebooks.length === 0) {
    return (
      <div className="flex flex-1 flex-col items-center justify-center gap-4">
        <div className="pulse-glow flex h-10 w-10 items-center justify-center rounded-full bg-accent text-accent-foreground">
          <Icon icon="lucide:sparkle" width={15} height={15} />
        </div>
        <div className="text-sm text-dim">Đang tải không gian làm việc...</div>
      </div>
    );
  }

  if (!activeNotebook || activeNotebook.id !== notebookId) {
    return null;
  }

  return (
    <>
      <NotebookSidebar />
      <DocumentPanel />
      <ChatPanel />
      <style>{`
        @media (max-width: 900px) {
          aside { display: none !important; }
        }
        @media (max-width: 700px) {
          .sources-panel { display: none !important; }
        }
      `}</style>
    </>
  );
}
