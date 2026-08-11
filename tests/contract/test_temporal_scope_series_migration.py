"""Contract checks for temporal-series relation persistence."""

from pathlib import Path

MIGRATION = Path("supabase/migrations/26_temporal_scope_series.sql")
SQL = MIGRATION.read_text(encoding="utf-8")
NORMALIZED_SQL = " ".join(SQL.lower().split())
RESET_SQL = Path("supabase/migrations/RESET_AND_REBUILD.sql").read_text(encoding="utf-8")
NORMALIZED_RESET_SQL = " ".join(RESET_SQL.lower().split())


def test_temporal_series_is_allowed_by_relation_constraint() -> None:
    assert "drop constraint if exists document_relations_type" in NORMALIZED_SQL
    assert "'template_variant', 'temporal_series'" in NORMALIZED_SQL
    assert NORMALIZED_SQL in NORMALIZED_RESET_SQL
    assert "'temporal_series'" in NORMALIZED_RESET_SQL


def test_fenced_completion_whitelist_is_extended_without_relation_rewrite() -> None:
    assert "pg_get_functiondef(completion_signature)" in NORMALIZED_SQL
    assert "complete_ingestion_job" in NORMALIZED_SQL
    assert "execute patched_definition" in NORMALIZED_SQL
    assert "update public.document_relations" not in NORMALIZED_SQL
