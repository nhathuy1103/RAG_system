from __future__ import annotations

from pathlib import Path

SQL = Path("supabase/migrations/29_allow_reupload_after_archive.sql").read_text(
    encoding="utf-8"
).lower()


def test_applied_upload_function_gets_a_guarded_archive_aware_rewrite() -> None:
    assert "pg_catalog.pg_get_functiondef" in SQL
    assert "where source_files.sha256 = normalized_sha" in SQL
    assert "registered_documents.status <> ''archived''" in SQL
    assert "refusing blind rewrite" in SQL


def test_upload_rpc_privileges_are_reasserted() -> None:
    assert "from public, anon" in SQL
    assert "to authenticated" in SQL
