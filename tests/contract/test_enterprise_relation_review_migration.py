"""Contracts for reliable Enterprise relation review and candidate lookup."""

from pathlib import Path

SQL = Path(
    "supabase/migrations/36_enterprise_relation_review.sql"
).read_text(encoding="utf-8")


def test_candidate_rpc_limits_indexed_channels_before_loading_vectors() -> None:
    assert "create or replace function public.find_enterprise_chunk_candidates_v2" in SQL
    assert "exact_limited as" in SQL
    assert "binary_limited as" in SQL
    assert "fts_limited as" in SQL
    assert "fused_limited as" in SQL
    assert SQL.index("fused_limited as") < SQL.index("chunks.embedding,")
    assert "limit p_limit_per_probe" in SQL
    assert "public.has_document_permission(p_actor_id, documents.id, 'READ')" in SQL


def test_relation_review_rpcs_are_acl_scoped_and_audited() -> None:
    assert "create or replace function public.list_enterprise_document_relations" in SQL
    assert "create or replace function public.get_enterprise_document_relation_evidence" in SQL
    assert "create or replace function public.resolve_enterprise_document_relation" in SQL
    assert "status in ('pending', 'deferred', 'auto_confirmed'" in SQL
    assert "selected_relation.status not in ('pending', 'deferred')" in SQL
    assert "p_expected_updated_at" in SQL
    assert "perform public.write_enterprise_audit(" in SQL
    assert "to authenticated;" in SQL
    assert "create or replace function public.queue_enterprise_quality_reprocess" in SQL
    assert "'knowledge_quality_mode', 'on'" in SQL


def test_relation_evidence_is_version_bound_and_content_is_bounded() -> None:
    assert "selected_relation.source_document_version_id" in SQL
    assert "selected_relation.target_document_version_id" in SQL
    assert "chunks.document_version_id = source_version_id" in SQL
    assert "chunks.document_version_id = target_version_id" in SQL
    assert "100000" in SQL
