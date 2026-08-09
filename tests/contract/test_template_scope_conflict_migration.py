"""Contract checks for scope-aware legal-template persistence."""

from pathlib import Path

MIGRATION = Path("supabase/migrations/13_template_scope_conflict.sql")
SQL = MIGRATION.read_text(encoding="utf-8")
NORMALIZED_SQL = " ".join(SQL.lower().split())
RESET_SQL = Path("supabase/migrations/RESET_AND_REBUILD.sql").read_text(encoding="utf-8")
NORMALIZED_RESET_SQL = " ".join(RESET_SQL.lower().split())


def test_template_variant_is_allowed_by_relation_constraint() -> None:
    assert "drop constraint document_relations_type" in NORMALIZED_SQL
    assert "'template_variant'" in NORMALIZED_SQL
    assert "'template_variant'" in NORMALIZED_RESET_SQL


def test_fenced_completion_whitelist_is_extended_in_place() -> None:
    assert "pg_get_functiondef(completion_signature)" in NORMALIZED_SQL
    assert "complete_ingestion_job" in NORMALIZED_SQL
    assert "execute patched_definition" in NORMALIZED_SQL
    assert "'template_variant'" in NORMALIZED_RESET_SQL
