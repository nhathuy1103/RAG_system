"""Contract checks for the pre-embedding chunk dedup migration."""

from pathlib import Path

MIGRATION = Path("supabase/migrations/10_chunk_preembedding_dedup.sql")
SQL = MIGRATION.read_text(encoding="utf-8")
NORMALIZED_SQL = " ".join(SQL.lower().split())
RESET_SQL = Path("supabase/migrations/RESET_AND_REBUILD.sql").read_text(encoding="utf-8")


def _nonempty_lines(sql: str) -> tuple[str, ...]:
    return tuple(line.rstrip() for line in sql.splitlines() if line.strip())


def test_reset_script_contains_exact_migration_10_segment() -> None:
    migration_lines = _nonempty_lines(SQL)
    reset_lines = _nonempty_lines(RESET_SQL)

    migration_segment = "\n".join(migration_lines)
    assert migration_segment in "\n".join(reset_lines)


def test_chunk_candidate_rpc_is_bounded_scoped_and_service_role_only() -> None:
    assert "create function public.find_chunk_dedup_candidates(" in NORMALIZED_SQL
    assert "auth.role() <> 'service_role'" in NORMALIZED_SQL
    assert "jsonb_array_length(p_probes) > 128" in NORMALIZED_SQL
    assert "p_limit_per_probe > 50" in NORMALIZED_SQL
    assert "chunks.owner_id = p_owner_id" in NORMALIZED_SQL
    assert "chunks.notebook_id = p_notebook_id" in NORMALIZED_SQL
    assert "chunks.document_id <> p_document_id" in NORMALIZED_SQL
    assert "latest_job.embedding_model = btrim(p_embedding_model)" in NORMALIZED_SQL
    assert "documents.canonical_document_id is null" in NORMALIZED_SQL
    assert "to service_role" in NORMALIZED_SQL


def test_simhash_lsh_has_all_eight_indexed_bands() -> None:
    for band in range(1, 9):
        assert f"document_chunks_simhash_band_{band}_idx" in NORMALIZED_SQL
    for start in range(1, 16, 2):
        assert f"(substr(loose_content_signature, {start}, 2))" in NORMALIZED_SQL


def test_exact_hash_and_lsh_are_candidate_paths_not_merge_decisions() -> None:
    assert (
        "chunks.normalized_content_hash = probe.value ->> 'normalized_content_hash'"
    ) in NORMALIZED_SQL
    assert "(probe.value ->> 'include_fuzzy')::boolean" in NORMALIZED_SQL
    assert "chunks.embedding::text as embedding" in NORMALIZED_SQL


def test_candidate_text_falls_back_to_canonical_chunk_content() -> None:
    assert (
        "coalesce( nullif(chunks.metadata ->> 'canonical_text', ''), "
        "chunks.content ) as canonical_text"
    ) in NORMALIZED_SQL
