"""Static safety contract for the one-off partial migration-08 repair."""

from pathlib import Path

REPAIR = Path("supabase/repairs/20260731_repair_partial_knowledge_quality_08.sql")
SQL = REPAIR.read_text(encoding="utf-8")
NORMALIZED_SQL = " ".join(SQL.lower().split())


def test_repair_is_atomic_non_destructive_and_outside_canonical_migrations() -> None:
    assert REPAIR.parent.name == "repairs"
    assert NORMALIZED_SQL.startswith("-- repair a very specific")
    assert " begin; " in f" {NORMALIZED_SQL} "
    assert NORMALIZED_SQL.endswith("commit;")
    assert "pg_advisory_xact_lock" in NORMALIZED_SQL
    assert "in access exclusive mode" in NORMALIZED_SQL
    assert "drop table" not in NORMALIZED_SQL
    assert "truncate " not in NORMALIZED_SQL
    assert "drop schema" not in NORMALIZED_SQL
    assert "drop constraint ingestion_jobs_claim cascade" not in NORMALIZED_SQL
    for table in (
        "public.documents",
        "public.document_relations",
        "public.knowledge_quality_audit",
    ):
        assert f"delete from {table}" not in NORMALIZED_SQL


def test_repair_refuses_to_downgrade_migration_09_or_10() -> None:
    first_document_mutation = NORMALIZED_SQL.index("alter table public.documents")
    for marker in (
        "completion_disposition",
        "ingestion_control",
        "reverts_audit_id",
        "find_chunk_dedup_candidates",
        "document_chunks_simhash_band_1_idx",
        "exact_duplicate_group_id",
    ):
        assert NORMALIZED_SQL.index(marker) < first_document_mutation
    assert "refusing to downgrade later rpcs" in NORMALIZED_SQL


def test_migration_06_dense_rpc_is_not_mistaken_for_migration_09() -> None:
    preflight = NORMALIZED_SQL[: NORMALIZED_SQL.index("alter table public.documents")]
    assert "pg_get_function_result(functions.oid)" in preflight
    assert "like '%normalized_content_hash%'" in preflight
    assert "like '%exact_duplicate_group_id%'" in preflight
    baseline_signature_only_guard = (
        "to_regprocedure( "
        "'public.match_document_chunks(vector,uuid,uuid,uuid[],integer)' "
        ") is not null"
    )
    assert baseline_signature_only_guard not in preflight


def test_repair_preserves_complete_existing_relation_and_audit_rows() -> None:
    assert "to_jsonb(relations) as row_snapshot" in NORMALIZED_SQL
    assert "to_jsonb(audit) as row_snapshot" in NORMALIZED_SQL
    assert NORMALIZED_SQL.count("is distinct from preserved.row_snapshot") == 2
    assert "a pre-existing relation row was lost" in NORMALIZED_SQL
    assert "a pre-existing audit row was lost" in NORMALIZED_SQL


def test_repair_converges_all_migration_08_document_columns() -> None:
    for column in (
        "normalized_content_hash",
        "normalization_version",
        "loose_content_signature",
        "canonical_document_id",
        "version_group_id",
        "version_number",
        "effective_from",
        "effective_to",
        "supersedes_document_id",
        "is_current",
        "quality_status",
        "quality_metadata",
    ):
        assert f"add column if not exists {column}" in NORMALIZED_SQL

    assert "alter column version_group_id set not null" in NORMALIZED_SQL
    assert "alter column quality_metadata set not null" in NORMALIZED_SQL
    assert "documents_canonical_owner_fk" in NORMALIZED_SQL
    assert "documents_supersedes_owner_fk" in NORMALIZED_SQL


def test_repair_restores_missing_tenant_foreign_keys_without_replacing_tables() -> None:
    for constraint in (
        "document_relations_source_owner_fk",
        "document_relations_target_owner_fk",
        "document_relations_preferred_owner_fk",
        "knowledge_quality_audit_notebook_owner_fk",
    ):
        assert f"add constraint {constraint}" in NORMALIZED_SQL
        assert constraint in NORMALIZED_SQL.split("required_constraints", 1)[1]

    assert "create table public.document_relations" not in NORMALIZED_SQL
    assert "create table public.knowledge_quality_audit" not in NORMALIZED_SQL


def test_claim_token_is_backfilled_before_the_fenced_constraint() -> None:
    add_token = NORMALIZED_SQL.index("add column if not exists claim_token uuid")
    backfill = NORMALIZED_SQL.index("set claim_token = gen_random_uuid()")
    replace_constraint = NORMALIZED_SQL.index("add constraint ingestion_jobs_claim check")
    assert add_token < backfill < replace_constraint
    assert "status = 'running' and claim_token is null" in NORMALIZED_SQL
    assert "status <> 'running' and claim_token is not null" in NORMALIZED_SQL


def test_claim_and_soft_delete_rpcs_use_generation_token_fencing() -> None:
    assert "drop function if exists public.claim_ingestion_job(text, integer)" in (NORMALIZED_SQL)
    assert "claim_token uuid, document_version integer" in NORMALIZED_SQL
    assert "claim_token = gen_random_uuid()" in NORMALIZED_SQL
    assert "create or replace function public.soft_delete_document" in NORMALIZED_SQL
    assert "status = 'cancelled'" in NORMALIZED_SQL
    assert "claim_token = null" in NORMALIZED_SQL
    assert "grant execute on function public.soft_delete_document(uuid, uuid) to authenticated" in (
        NORMALIZED_SQL
    )


def test_byte_duplicate_backfill_precedes_exact_unique_index() -> None:
    backfill = NORMALIZED_SQL.index("with ranked_documents as")
    relation_insert = NORMALIZED_SQL.index("insert into public.document_relations", backfill)
    exact_index = NORMALIZED_SQL.index(
        "create unique index if not exists documents_active_exact_content_key"
    )
    assert backfill < relation_insert < exact_index
    assert "on conflict (source_document_id, target_document_id, detector_version) do nothing" in (
        NORMALIZED_SQL
    )
    assert "to_regclass('public.documents_active_exact_content_key') is null" in (NORMALIZED_SQL)


def test_repair_has_postconditions_and_reloads_postgrest_schema() -> None:
    assert "missing/unvalidated constraints" in NORMALIZED_SQL
    assert "ingestion claim rows are inconsistent" in NORMALIZED_SQL
    assert "claim_ingestion_job is not generation-fenced" in NORMALIZED_SQL
    assert "one or more migration-08 rpcs are missing" in NORMALIZED_SQL
    assert "notify pgrst, 'reload schema'" in NORMALIZED_SQL
