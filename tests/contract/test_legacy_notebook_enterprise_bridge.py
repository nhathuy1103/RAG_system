"""Contracts for legacy notebook uploads after the Enterprise cutover."""

from pathlib import Path

MIGRATION = Path(
    "supabase/migrations/24_legacy_notebook_enterprise_bridge.sql"
).read_text(encoding="utf-8").lower()


def _function_body(name: str) -> str:
    marker = f"create or replace function public.{name}"
    return MIGRATION.split(marker, maxsplit=1)[1].split("$$;", maxsplit=1)[0]


def test_legacy_enqueue_lazily_creates_enterprise_mapping() -> None:
    resolver = _function_body("resolve_legacy_ingestion_version")
    assert "ensure_legacy_document_enterprise_mapping(new.document_id)" in resolver

    bridge = _function_body("ensure_legacy_document_enterprise_mapping")
    for table in (
        "source_files",
        "knowledge_documents",
        "document_versions",
        "document_permissions",
    ):
        assert f"insert into public.{table}" in bridge
    assert "pg_advisory_xact_lock" in bridge
    assert "'draft'" in bridge
    assert "'active'" in bridge


def test_bridge_is_internal_and_owner_scoped() -> None:
    bridge = _function_body("ensure_legacy_document_enterprise_mapping")
    assert "legacy_document.owner_id" in bridge
    assert "legacy_document.notebook_id" in bridge
    assert "legacy_document.version_group_id" in bridge
    assert "subjects.subject_type = 'user'" in bridge
    assert (
        "revoke all on function public.ensure_legacy_document_enterprise_mapping(uuid)"
        in MIGRATION
    )
    assert "from public, anon, authenticated" in MIGRATION
