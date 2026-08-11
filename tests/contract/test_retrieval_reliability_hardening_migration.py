from __future__ import annotations

from pathlib import Path

MIGRATION_PATH = Path(
    "supabase/migrations/31_retrieval_reliability_hardening.sql"
)
MIGRATION = MIGRATION_PATH.read_text(encoding="utf-8").lower()


def _function_body(name: str) -> str:
    marker = f"create or replace function public.{name}"
    return MIGRATION.split(marker, maxsplit=1)[1].split("$$;", maxsplit=1)[0]


def test_metadata_revision_refreshes_lexical_projection_from_all_column_trigger() -> None:
    queue = _function_body("queue_retrieval_projection_refresh")

    assert "new.metadata_revision is distinct from old.metadata_revision" in queue
    assert "update public.chunk_retrieval_projections" in queue
    assert "source_metadata_revision = new.metadata_revision" in queue
    assert "requested_metadata_revision <= new.metadata_revision" in queue
    assert "lexical projection coverage mismatch" in queue

    # The migration-25 trigger using UPDATE OF misses revisions changed only by
    # its BEFORE trigger. The all-column queue trigger remains and owns refresh.
    assert "drop trigger if exists knowledge_documents_refresh_lexical_projection" in MIGRATION
    assert (
        "create trigger knowledge_documents_refresh_lexical_projection\n"
        "after update of metadata_revision"
    ) not in MIGRATION


def test_existing_projection_revision_drift_is_backfilled_without_forging_embeddings() -> None:
    assert "source_metadata_revision = documents.metadata_revision" in MIGRATION
    assert "embedding_metadata_revision = documents.metadata_revision" not in MIGRATION
    assert "current version is missing a current lexical retrieval projection" in MIGRATION
    assert "processed_at = now()" in MIGRATION


def test_sparse_recall_removes_fillers_and_uses_bounded_or_without_relaxing_security() -> None:
    terms = _function_body("enterprise_recall_search_terms")
    sparse = _function_body("search_enterprise_retrieval_projection")

    assert "limit 32" in terms
    assert "'các', 'cac'" in terms
    assert "'được', 'duoc'" in terms
    assert "`an` is intentionally kept" in terms
    assert "' | '" in _function_body("enterprise_recall_tsquery")

    assert "websearch_to_tsquery" in sparse
    assert "enterprise_recall_tsquery" in sparse
    assert "search_vector_original @@ recall_original_query" in sparse
    assert "documents.current_version_id = versions.id" in sparse
    assert "documents.status = 'published'" in sparse
    assert "documents.deleted_at is null" in sparse
    assert "versions.status = 'active'" in sparse
    assert "public.has_document_permission(actor, documents.id, 'read')" in sparse
    assert "projections.source_metadata_revision = documents.metadata_revision" in sparse


def test_effective_status_is_derived_at_query_time_on_sparse_and_dense_routes() -> None:
    effective_status = _function_body("enterprise_effective_status")
    assert "current_date" in MIGRATION
    assert "'scheduled'" in effective_status
    assert "'expired'" in effective_status
    assert "'current'" in effective_status
    assert "'undated'" in effective_status

    for name in (
        "search_enterprise_retrieval_projection",
        "match_enterprise_retrieval_projection",
    ):
        body = _function_body(name)
        assert "'effective_status'" in body
        assert "public.enterprise_effective_status(" in body
        assert "versions.effective_date is null" in body
        assert "versions.effective_to is null" in body
        assert "public.has_document_permission(actor, documents.id, 'read')" in body


def test_published_organization_read_path_is_explicit_role_acl_and_never_anon() -> None:
    sync = _function_body("sync_published_knowledge_reader_acl")

    assert "grant_source" in MIGRATION
    assert "published_role_default" in MIGRATION
    assert "new.visibility in ('internal', 'public')" in sync
    assert "subjects.subject_type = 'role'" in sync
    assert "permissions.code = 'ask_knowledge'" in sync
    assert "insert into public.document_permissions" in sync
    assert "grant_source = 'published_role_default'" in sync
    assert "status = 'revoked'" in sync
    assert "grant_source = 'manual'" not in sync
    assert "grant execute on function public.sync_published_knowledge_reader_acl" not in MIGRATION
    assert "to anon" not in MIGRATION


def test_searchability_diagnostic_is_read_only_acl_aware_and_separates_staleness() -> None:
    diagnostic = _function_body("get_enterprise_document_searchability")

    assert "actor uuid := auth.uid()" in diagnostic
    assert "has_document_permission(" in diagnostic
    assert "manage_access_policy" in diagnostic
    assert "document_not_published" in diagnostic
    assert "read_denied" in diagnostic
    assert "no_ready_projections" in diagnostic
    assert "lexical_projection_stale" in diagnostic
    assert "embedding_metadata_stale" in diagnostic
    assert "projection_refresh_pending" in diagnostic
    assert "chunks.content" not in diagnostic
    assert "insert into" not in diagnostic
    assert "update public." not in diagnostic

    assert (
        "grant execute on function public.get_enterprise_document_searchability(uuid)\n"
        "to authenticated;"
    ) in MIGRATION
    assert (
        "revoke all on function public.get_enterprise_document_searchability(uuid)\n"
        "from public, anon, service_role;"
    ) in MIGRATION
