"""Contract checks for context-weighted PostgreSQL full-text retrieval."""

from pathlib import Path

MIGRATION = Path("supabase/migrations/11_contextual_metadata_fts.sql")
SQL = MIGRATION.read_text(encoding="utf-8")
NORMALIZED_SQL = " ".join(SQL.lower().split())
RESET_SQL = Path("supabase/migrations/RESET_AND_REBUILD.sql").read_text(encoding="utf-8")


def _nonempty_lines(sql: str) -> tuple[str, ...]:
    return tuple(line.rstrip() for line in sql.splitlines() if line.strip())


def test_reset_script_contains_exact_migration_11_segment() -> None:
    migration_lines = _nonempty_lines(SQL)
    reset_lines = _nonempty_lines(RESET_SQL)

    assert any(
        reset_lines[start : start + len(migration_lines)] == migration_lines
        for start in range(len(reset_lines) - len(migration_lines) + 1)
    )


def test_search_vector_weights_context_and_keeps_content_canonical() -> None:
    assert "add column if not exists search_vector tsvector" in NORMALIZED_SQL
    assert "generated always as" in NORMALIZED_SQL
    assert "{retrieval_metadata,title}" in NORMALIZED_SQL
    assert "{retrieval_metadata,section_title}" in NORMALIZED_SQL
    assert "{retrieval_metadata,section_path}" in NORMALIZED_SQL
    assert "{retrieval_metadata,table_header}" in NORMALIZED_SQL
    assert "{retrieval_metadata,document_type}" in NORMALIZED_SQL
    assert "{retrieval_metadata,content_kind}" in NORMALIZED_SQL
    assert "{retrieval_metadata,keyword_aliases}" in NORMALIZED_SQL
    assert "setweight(to_tsvector('simple'::regconfig, content), 'd')" in NORMALIZED_SQL
    assert "using gin (search_vector)" in NORMALIZED_SQL


def test_existing_chunks_receive_document_title_without_overwriting_context() -> None:
    assert "update public.document_chunks as chunks" in NORMALIZED_SQL
    assert "documents.original_filename" in NORMALIZED_SQL
    assert "jsonb_typeof(chunks.metadata -> 'retrieval_metadata') = 'object'" in NORMALIZED_SQL
    assert "documents.id = chunks.document_id" in NORMALIZED_SQL
    assert "documents.owner_id = chunks.owner_id" in NORMALIZED_SQL
    assert "documents.notebook_id = chunks.notebook_id" in NORMALIZED_SQL


def test_keyword_rpc_is_ranked_and_owner_notebook_scoped() -> None:
    assert "create or replace function public.search_document_chunks_keyword(" in NORMALIZED_SQL
    assert "websearch_to_tsquery('simple'::regconfig" in NORMALIZED_SQL
    assert "ts_rank_cd(chunks.search_vector, search_query, 32)" in NORMALIZED_SQL
    assert "chunks.owner_id = p_owner_id" in NORMALIZED_SQL
    assert "chunks.notebook_id = p_notebook_id" in NORMALIZED_SQL
    assert "chunks.document_id = any(p_document_ids)" in NORMALIZED_SQL
    assert "auth.uid() is distinct from p_owner_id" in NORMALIZED_SQL
    assert "to authenticated, service_role" in NORMALIZED_SQL
