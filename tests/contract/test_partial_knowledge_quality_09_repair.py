"""Static safety contract for the partial migration-09 bridge repair."""

from pathlib import Path

REPAIR = Path("supabase/repairs/20260731_repair_partial_knowledge_quality_09.sql")
SQL = REPAIR.read_text(encoding="utf-8")
NORMALIZED_SQL = " ".join(SQL.lower().split())


def test_repair_is_atomic_targeted_and_non_destructive() -> None:
    assert REPAIR.parent.name == "repairs"
    assert NORMALIZED_SQL.startswith("-- prepare a very specific")
    assert " begin; " in f" {NORMALIZED_SQL} "
    assert NORMALIZED_SQL.endswith("commit;")
    assert "pg_advisory_xact_lock" in NORMALIZED_SQL
    assert "in access exclusive mode" in NORMALIZED_SQL
    assert "public.ingestion_control" in NORMALIZED_SQL
    assert "drop table" not in NORMALIZED_SQL
    assert "truncate " not in NORMALIZED_SQL
    assert "drop schema" not in NORMALIZED_SQL
    for table in (
        "public.documents",
        "public.document_relations",
        "public.knowledge_quality_audit",
    ):
        assert f"delete from {table}" not in NORMALIZED_SQL


def test_preflight_requires_mixed_09_and_refuses_completed_later_migrations() -> None:
    first_document_mutation = NORMALIZED_SQL.index("alter table public.documents")
    for marker in (
        "public.ingestion_control",
        "normalized_content_hash%",
        "exact_duplicate_group_id%",
        "reverts_audit_id",
        "document_chunks_simhash_band_1_idx",
        "find_chunk_dedup_candidates",
        "migration 09 is already complete",
    ):
        assert NORMALIZED_SQL.index(marker) < first_document_mutation

    assert "database is not the expected mixed migration-08/09 state" in NORMALIZED_SQL
    assert "required migration-09 sentinels are missing" in NORMALIZED_SQL


def test_preflight_fences_live_ingestion_and_preserves_existing_rows() -> None:
    assert "where singleton" in NORMALIZED_SQL
    assert "maintenance_token is not null" in NORMALIZED_SQL
    assert "maintenance_expires_at > now()" in NORMALIZED_SQL
    assert "status = 'running' and lease_expires_at > now()" in NORMALIZED_SQL
    assert "repair09_preserved_relation_ids" in NORMALIZED_SQL
    assert "repair09_preserved_audit_ids" in NORMALIZED_SQL
    assert "repair08_preserved_" not in NORMALIZED_SQL
    assert NORMALIZED_SQL.count("is distinct from preserved.row_snapshot") == 2
    assert "a pre-existing relation row was lost" in NORMALIZED_SQL
    assert "a pre-existing audit row was lost" in NORMALIZED_SQL


def test_repair_removes_legacy_dense_search_without_dropping_final_09_rpc() -> None:
    assert (
        "drop function if exists public.match_document_chunks( vector, uuid[], integer )"
    ) in NORMALIZED_SQL
    assert (
        "drop function if exists public.match_document_chunks( vector, uuid, uuid[], integer )"
    ) in NORMALIZED_SQL
    assert (
        "drop function if exists public.match_document_chunks( "
        "vector, uuid, uuid, uuid[], integer )"
    ) not in NORMALIZED_SQL
    assert "legacy dense-search overloads remain" in NORMALIZED_SQL
    assert "migration-09 dense-search rpc is missing" in NORMALIZED_SQL


def test_repair_bridges_claim_rpc_without_downgrading_final_completion_rpcs() -> None:
    assert "drop function if exists public.claim_ingestion_job(text, integer)" in (NORMALIZED_SQL)
    assert "create function public.claim_ingestion_job(" in NORMALIZED_SQL
    assert "claim_token uuid, document_version integer" in NORMALIZED_SQL
    assert "from public.ingestion_control as controls where controls.singleton for share" in (
        NORMALIZED_SQL
    )
    assert "if maintenance_active then return; end if;" in NORMALIZED_SQL
    assert "claim_ingestion_job is not maintenance-fenced" in NORMALIZED_SQL

    assert (
        "drop function if exists public.complete_ingestion_job( uuid, text, text, integer, jsonb )"
    ) in NORMALIZED_SQL
    assert (
        "drop function if exists public.complete_ingestion_job( uuid, text, uuid, "
        "text, integer, jsonb, text, text, text, jsonb, jsonb )"
    ) not in NORMALIZED_SQL
    assert "create or replace function public.complete_ingestion_job" not in (NORMALIZED_SQL)
    assert "create function public.complete_ingestion_job" not in NORMALIZED_SQL


def test_repair_keeps_phase_two_explicit_and_reloads_postgrest_schema() -> None:
    assert "this is phase 1 of 2" in NORMALIZED_SQL
    assert "immediately run 09_knowledge_quality_hardening.sql from the top" in (NORMALIZED_SQL)
    assert "repair postcondition failed: missing columns" in NORMALIZED_SQL
    assert "repair postcondition failed: missing/unvalidated constraints" in (NORMALIZED_SQL)
    assert "repair postcondition failed: one or more required rpcs are missing" in (NORMALIZED_SQL)
    assert "notify pgrst, 'reload schema'" in NORMALIZED_SQL
