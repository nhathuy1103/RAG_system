from pathlib import Path

MIGRATION = Path("supabase/migrations/33_domain_entity_scope_metadata.sql")
SQL = MIGRATION.read_text(encoding="utf-8")
NORMALIZED_SQL = " ".join(SQL.lower().split())


def test_p2_scope_migration_indexes_optional_versioned_metadata() -> None:
    assert "document_chunks_entity_scope_version_idx" in NORMALIZED_SQL
    assert "knowledge_chunks_entity_scope_version_idx" in NORMALIZED_SQL
    assert "metadata #>> '{entity_scope,version}'" in NORMALIZED_SQL
    assert NORMALIZED_SQL.count("where metadata ? 'entity_scope'") == 2


def test_p2_scope_migration_does_not_change_candidate_or_reuse_logic() -> None:
    assert "alter table" not in NORMALIZED_SQL
    assert "create or replace function" not in NORMALIZED_SQL
    assert "embedding" not in NORMALIZED_SQL
    assert "high_recall_chunk_candidates" not in NORMALIZED_SQL
