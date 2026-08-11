from __future__ import annotations

from pathlib import Path

MIGRATION = Path("supabase/migrations/25_canonical_metadata_parent_projection.sql").read_text(
    encoding="utf-8"
).lower()
HOTFIX = Path("supabase/migrations/27_fix_complete_processing_job_v2_digest.sql").read_text(
    encoding="utf-8"
).lower()


def _function_body(name: str) -> str:
    marker = f"create or replace function public.{name}"
    return MIGRATION.split(marker, maxsplit=1)[1].split("$$;", maxsplit=1)[0]


def test_persists_real_parent_child_hierarchy_and_rebuildable_projection() -> None:
    assert "create table if not exists public.knowledge_parent_chunks" in MIGRATION
    assert "knowledge_chunks_parent_same_version_fk" in MIGRATION
    assert "create table if not exists public.chunk_retrieval_projections" in MIGRATION
    assert "embedding_metadata_revision" in MIGRATION
    completion = _function_body("complete_processing_job_v2")
    assert "insert into public.knowledge_parent_chunks" in completion
    assert "insert into public.chunk_retrieval_projections" in completion
    assert "- 'parent_context'" in completion


def test_sparse_and_dense_routes_enforce_acl_current_version_and_canonical_filters() -> None:
    for name in (
        "search_enterprise_retrieval_projection",
        "match_enterprise_retrieval_projection",
    ):
        body = _function_body(name)
        assert "documents.current_version_id = versions.id" in body
        assert "documents.status = 'published'" in body
        assert "documents.deleted_at is null" in body
        assert "public.has_document_permission(actor, documents.id, 'read')" in body
        assert "unsupported canonical metadata filter" in body
        assert "documents.project_code" in body
        assert "versions.effective_date" in body


def test_vietnamese_fts_keeps_original_and_folded_vectors_with_bounded_mix() -> None:
    assert "search_vector_original" in MIGRATION
    assert "search_vector_folded" in MIGRATION
    sparse = _function_body("search_enterprise_retrieval_projection")
    assert "0.80 * ts_rank_cd" in sparse
    assert "0.20 * ts_rank_cd" in sparse
    assert "public.normalize_search_text(p_query)" in sparse
    assert "public.fold_vietnamese_text(p_query)" in sparse


def test_llm_assertions_are_unverified_until_audited_review_updates_canonical_rows() -> None:
    completion = _function_body("complete_processing_job_v2")
    assert "assertion.value ->> 'source' = 'llm_inferred'" in completion
    assert "verification_status" in completion
    review = _function_body("review_document_metadata_assertion")
    assert "has_functional_permission(actor, 'review_document')" in review
    assert "verification_status <> 'unverified'" in review
    assert "update public.knowledge_documents" in review
    assert "update public.document_versions" in review
    assert "write_enterprise_audit" in review


def test_document_number_has_an_acl_gated_exact_route() -> None:
    body = _function_body("resolve_enterprise_document_number")
    assert "normalize_document_number" in body
    assert "current_version_id" in body
    assert "has_document_permission" in body


def test_pgcrypto_digest_is_resolved_without_relaxing_function_search_paths() -> None:
    assert "encode(digest(" not in MIGRATION
    assert "public.knowledge_digest(" in MIGRATION
    assert "pg_catalog.convert_to(" in MIGRATION
    completion = _function_body("complete_processing_job_v2")
    assert "set search_path = ''" in completion


def test_applied_migration_25_databases_receive_a_guarded_digest_hotfix() -> None:
    assert "pg_catalog.pg_get_functiondef" in HOTFIX
    assert "digest(chunks.content, ''sha256'')" in HOTFIX
    assert "public.knowledge_digest(pg_catalog.convert_to" in HOTFIX
    assert "refusing blind rewrite" in HOTFIX
    assert "to service_role" in HOTFIX
