from pathlib import Path

MIGRATION = Path("supabase/migrations/15_structured_retrieval_filters.sql")
SQL = MIGRATION.read_text(encoding="utf-8")
NORMALIZED = " ".join(SQL.lower().split())
RESET = Path("supabase/migrations/RESET_AND_REBUILD.sql").read_text(encoding="utf-8")


def test_reset_contains_structured_filter_migration_exactly() -> None:
    migration_lines = [line.rstrip() for line in SQL.splitlines() if line.strip()]
    reset_lines = [line.rstrip() for line in RESET.splitlines() if line.strip()]
    assert any(
        reset_lines[start : start + len(migration_lines)] == migration_lines
        for start in range(len(reset_lines) - len(migration_lines) + 1)
    )


def test_migration_indexes_and_applies_every_approved_filter() -> None:
    for field_name in (
        "document_type",
        "content_kind",
        "project_id",
        "project_code",
        "year",
        "data_period",
        "effective_status",
    ):
        assert f"retrieval_metadata,{field_name}" in NORMALIZED
        assert f"p_{field_name}" in NORMALIZED
        assert f"document_chunks_{field_name}_filter_idx" in NORMALIZED


def test_both_rpcs_keep_owner_guard_and_revoke_public_access() -> None:
    assert NORMALIZED.count("auth.uid() is distinct from p_owner_id") == 2
    assert "revoke all on function public.match_document_chunks" in NORMALIZED
    assert "revoke all on function public.search_document_chunks_keyword" in NORMALIZED
