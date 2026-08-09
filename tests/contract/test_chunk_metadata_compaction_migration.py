"""Contract checks for lossless chunk metadata compaction."""

from pathlib import Path

MIGRATION = Path("supabase/migrations/14_compact_chunk_metadata.sql")
SQL = MIGRATION.read_text(encoding="utf-8")
NORMALIZED_SQL = " ".join(SQL.lower().split())
RESET_SQL = Path("supabase/migrations/RESET_AND_REBUILD.sql").read_text(encoding="utf-8")


def _nonempty_lines(sql: str) -> tuple[str, ...]:
    return tuple(line.rstrip() for line in sql.splitlines() if line.strip())


def test_reset_script_contains_exact_migration_14_segment() -> None:
    migration_lines = _nonempty_lines(SQL)
    reset_lines = _nonempty_lines(RESET_SQL)

    assert any(
        reset_lines[start : start + len(migration_lines)] == migration_lines
        for start in range(len(reset_lines) - len(migration_lines) + 1)
    )


def test_compaction_only_removes_provably_redundant_values() -> None:
    assert "metadata ->> 'canonical_text' = chunks.content" in NORMALIZED_SQL
    assert "metadata -> 'provenance_metadata' = '{}'::jsonb" in NORMALIZED_SQL
    assert "metadata -> 'authority_metadata' = '{}'::jsonb" in NORMALIZED_SQL
    assert "metadata is distinct from compacted.metadata" in NORMALIZED_SQL
    assert "normalized_content_hash" not in NORMALIZED_SQL
    assert "exact_duplicate_group_id" not in NORMALIZED_SQL
