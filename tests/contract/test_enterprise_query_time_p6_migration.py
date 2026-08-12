from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
MIGRATION = ROOT / "supabase" / "migrations" / "37_enterprise_query_time_p6.sql"


def test_p6_migration_uses_canonical_reference_year_not_effective_date() -> None:
    sql = MIGRATION.read_text(encoding="utf-8")

    assert "enterprise_chunk_reference_year" in sql
    assert "{retrieval_metadata,year}" in sql
    assert "canonical_reference_year" in sql
    assert "knowledge_chunks_reference_year_idx" in sql
    assert "extract(year from versions.effective_date)" not in sql


def test_p6_search_and_dense_rpc_signatures_remain_backward_compatible() -> None:
    sql = MIGRATION.read_text(encoding="utf-8")

    assert "search_enterprise_retrieval_projection(\n    p_query text" in sql
    assert "match_enterprise_retrieval_projection(\n    p_query_embedding vector(1536)" in sql
    assert "'reference_years'" in sql
    assert "'normalized_content_hash', chunks.normalized_content_hash" in sql
    assert "public.has_document_permission(actor, documents.id, 'READ')" in sql
    assert "security definer" in sql


def test_reset_bundle_contains_p6_migration_verbatim() -> None:
    reset = (ROOT / "supabase" / "migrations" / "RESET_AND_REBUILD.sql").read_text(encoding="utf-8")
    migration = MIGRATION.read_text(encoding="utf-8").strip()

    assert migration in reset
