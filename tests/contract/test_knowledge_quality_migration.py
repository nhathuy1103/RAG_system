"""Contract checks for the duplicate/version/conflict database migration."""

from pathlib import Path

MIGRATION = Path("supabase/migrations/08_knowledge_quality.sql")
SQL = MIGRATION.read_text(encoding="utf-8")
NORMALIZED_SQL = " ".join(SQL.lower().split())


def test_document_identity_and_lineage_columns_are_persisted() -> None:
    for column in (
        "normalized_content_hash",
        "normalization_version",
        "loose_content_signature",
        "canonical_document_id",
        "version_group_id",
        "version_number",
        "supersedes_document_id",
        "is_current",
        "quality_status",
    ):
        assert f"add column if not exists {column}" in NORMALIZED_SQL
    assert "create unique index documents_active_exact_content_key" in NORMALIZED_SQL
    assert "canonical_document_id is null" in NORMALIZED_SQL


def test_relation_queue_is_owner_scoped_and_decisions_are_audited() -> None:
    assert "create table public.document_relations" in NORMALIZED_SQL
    assert "create table public.knowledge_quality_audit" in NORMALIZED_SQL
    assert "create policy document_relations_select_own" in NORMALIZED_SQL
    assert "create policy knowledge_quality_audit_select_own" in NORMALIZED_SQL
    assert "create function public.resolve_document_relation" in NORMALIZED_SQL
    assert "p_expected_updated_at timestamptz" in NORMALIZED_SQL
    assert "using errcode = '40001'" in NORMALIZED_SQL
    assert "insert into public.knowledge_quality_audit" in NORMALIZED_SQL
    assert "knowledge_quality_audit is append-only" in SQL
    assert "grant select on table public.document_relations to authenticated" in NORMALIZED_SQL
    assert "grant all privileges on table public.document_relations to authenticated" not in (
        NORMALIZED_SQL
    )


def test_every_worker_transition_is_fenced_by_claim_generation() -> None:
    assert "add column if not exists claim_token uuid" in NORMALIZED_SQL
    assert NORMALIZED_SQL.count("ingestion_jobs.claim_token = p_claim_token") >= 3
    assert NORMALIZED_SQL.count("ingestion_jobs.lease_expires_at > now()") >= 3
    assert "create function public.complete_duplicate_ingestion_job" in NORMALIZED_SQL
    assert "returns boolean" in NORMALIZED_SQL
    assert "claim_token = null" in NORMALIZED_SQL


def test_soft_delete_clears_generation_token_before_cancelling_job() -> None:
    assert "create or replace function public.soft_delete_document" in NORMALIZED_SQL
    assert "status = 'cancelled'" in NORMALIZED_SQL
    assert "claim_token = null" in NORMALIZED_SQL
