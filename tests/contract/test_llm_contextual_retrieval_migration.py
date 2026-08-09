"""Contract checks for LLM context in PostgreSQL full-text retrieval."""

from pathlib import Path

MIGRATION = Path("supabase/migrations/12_llm_contextual_retrieval.sql")
SQL = MIGRATION.read_text(encoding="utf-8")
NORMALIZED_SQL = " ".join(SQL.lower().split())
RESET_SQL = Path("supabase/migrations/RESET_AND_REBUILD.sql").read_text(encoding="utf-8")


def _nonempty_lines(sql: str) -> tuple[str, ...]:
    return tuple(line.rstrip() for line in sql.splitlines() if line.strip())


def test_reset_script_contains_exact_migration_12_segment() -> None:
    migration_lines = _nonempty_lines(SQL)
    reset_lines = _nonempty_lines(RESET_SQL)

    assert any(
        reset_lines[start : start + len(migration_lines)] == migration_lines
        for start in range(len(reset_lines) - len(migration_lines) + 1)
    )


def test_generated_search_vector_indexes_validated_llm_context() -> None:
    assert "drop column if exists search_vector" in NORMALIZED_SQL
    assert "{retrieval_metadata,contextual_summary}" in NORMALIZED_SQL
    assert "{retrieval_metadata,contextual_search_terms}" in NORMALIZED_SQL
    assert "setweight(to_tsvector('simple'::regconfig, content), 'd')" in NORMALIZED_SQL
    assert "using gin (search_vector)" in NORMALIZED_SQL
