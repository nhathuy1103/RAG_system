from pathlib import Path

SQL = Path("supabase/migrations/32_high_recall_chunk_candidates.sql").read_text(
    encoding="utf-8"
).lower()


def test_v2_candidate_migration_is_additive_bounded_and_tenant_scoped() -> None:
    assert "create or replace function public.find_chunk_candidates_v2" in SQL
    assert "using gin (candidate_binary_keys)" in SQL
    assert "base.search_vector @@ fts_query.value" in SQL
    assert "chunks.owner_id = p_owner_id" in SQL
    assert "chunks.notebook_id = p_notebook_id" in SQL
    assert "chunks.document_id <> p_document_id" in SQL
    assert "p_limit_per_probe > 50" in SQL
    assert "jsonb_array_length(p_probes) > 128" in SQL
    assert "auth.role() <> 'service_role'" in SQL
    assert "drop function if exists public.find_chunk_dedup_candidates" not in SQL


def test_binary_layout_matches_application_contract() -> None:
    assert "array[1, 3, 5, 7, 11, 13, 17, 21]" in SQL
    assert "generated always as" in SQL
    assert "knowledge_simhash_multi_keys(loose_content_signature)" in SQL
