"""Contract checks for the additive structured-fact persistence layer."""

from __future__ import annotations

from pathlib import Path

MIGRATION = Path("supabase/migrations/16_structured_fact_layer.sql")
SQL = MIGRATION.read_text(encoding="utf-8")
NORMALIZED = " ".join(SQL.lower().split())
RESET = Path("supabase/migrations/RESET_AND_REBUILD.sql").read_text(encoding="utf-8")


def test_reset_contains_structured_fact_migration_exactly_after_existing_schema() -> None:
    migration_lines = [line.rstrip() for line in SQL.splitlines() if line.strip()]
    reset_lines = [line.rstrip() for line in RESET.splitlines() if line.strip()]
    matches = [
        start
        for start in range(len(reset_lines) - len(migration_lines) + 1)
        if reset_lines[start : start + len(migration_lines)] == migration_lines
    ]
    assert len(matches) == 1
    assert RESET.index("-- Run after 14_compact_chunk_metadata.sql.") < RESET.index(
        "-- Additive structured-fact persistence"
    )


def test_migration_is_additive_and_creates_all_structured_fact_tables() -> None:
    for table_name in (
        "table_snapshots",
        "structured_claims",
        "claim_relations",
        "structured_claim_audit",
    ):
        assert f"create table public.{table_name}" in NORMALIZED
    assert "drop table" not in NORMALIZED
    assert "alter table public.documents add" not in NORMALIZED
    assert "alter table public.document_chunks add" not in NORMALIZED


def test_every_core_link_is_tenant_scoped_by_composite_foreign_keys() -> None:
    assert "foreign key (document_id, notebook_id, owner_id)" in NORMALIZED
    assert "foreign key (snapshot_id, document_id, notebook_id, owner_id)" in NORMALIZED
    assert "foreign key (source_snapshot_id, notebook_id, owner_id)" in NORMALIZED
    assert "foreign key (target_snapshot_id, notebook_id, owner_id)" in NORMALIZED
    assert (
        "foreign key ( source_claim_id, source_snapshot_id, notebook_id, owner_id )" in NORMALIZED
    )
    assert (
        "foreign key ( target_claim_id, target_snapshot_id, notebook_id, owner_id )" in NORMALIZED
    )
    assert "relation target snapshot is outside this tenant" in NORMALIZED
    assert NORMALIZED.count("chunks.owner_id = selected_document.owner_id") == 2


def test_extractions_are_idempotently_keyed_by_extractor_version() -> None:
    assert "constraint table_snapshots_extractor_key unique" in NORMALIZED
    assert "constraint structured_claims_snapshot_claim_extractor_key unique" in NORMALIZED
    assert "extractor_version text not null" in NORMALIZED
    assert "create unique index claim_relations_detector_key" in NORMALIZED
    assert "detector_version" in NORMALIZED


def test_claims_preserve_citable_cell_and_chunk_provenance() -> None:
    assert (
        "source_chunk_id uuid references public.document_chunks (id) on delete set null"
        in NORMALIZED
    )
    for field in (
        "row_identity",
        "row_index",
        "data_row_ordinal",
        "page_number",
        "source_text",
        "source_cells",
        "provenance",
    ):
        assert f"{field} " in NORMALIZED
    assert "jsonb_typeof(source_cells) = 'array'" in NORMALIZED
    assert "jsonb_typeof(provenance) = 'object'" in NORMALIZED
    assert "data_row_ordinal is null or data_row_ordinal >= 0" in NORMALIZED
    assert "claim source chunk is outside this document" in NORMALIZED


def test_mapper_temporal_diagnostics_and_authority_fields_are_not_discarded() -> None:
    assert "warnings jsonb not null default '[]'::jsonb" in NORMALIZED
    assert "jsonb_typeof(warnings) = 'array'" in NORMALIZED
    assert "snapshot_payload -> 'warnings'" in NORMALIZED
    assert "snapshot_payload ->> 'ingested_at'" in NORMALIZED
    assert "claim_payload ->> 'data_row_ordinal'" in NORMALIZED
    assert "claim_provenance ->> 'data_row_ordinal'" in NORMALIZED
    assert "claim_payload ->> 'ingested_at'" in NORMALIZED
    assert "claim_payload #>> '{temporal,ingested_at}'" in NORMALIZED
    assert "claims.authority_metadata -> 'approval_status'" in NORMALIZED
    assert "claims.authority_metadata -> 'officiality'" in NORMALIZED
    assert "'source_type', claims.source_type" in NORMALIZED
    assert "'publisher', claims.source_publisher" in NORMALIZED
    assert "'authority_level', claims.authority_level" in NORMALIZED
    assert "jsonb_typeof(claims.authority_metadata -> 'metadata') = 'object'" in NORMALIZED
    assert "claims.authority_metadata ? 'source_type'" not in NORMALIZED
    assert (
        "claims.authority_metadata - array['approval_status', 'officiality']::text[]" in NORMALIZED
    )


def test_claims_model_temporal_authority_qualifiers_and_derivation() -> None:
    for field in (
        "publication_time",
        "effective_from",
        "effective_to",
        "observed_at",
        "ingested_at",
        "source_publisher",
        "source_type",
        "authority_level",
        "authority_metadata",
        "qualifiers",
        "qualifier_hash",
        "candidate_identity_hash",
        "confidence",
        "is_derived",
        "derivation",
    ):
        assert f"{field} " in NORMALIZED
    assert "effective_to >= effective_from" in NORMALIZED
    assert "jsonb_typeof(authority_metadata) = 'object'" in NORMALIZED
    assert "authority_level between 0 and 100" in NORMALIZED
    assert "check (confidence between 0 and 1)" in NORMALIZED


def test_directional_relation_taxonomy_keeps_scope_qualifier_and_time_separate() -> None:
    for relation_type in (
        "source_updates_target",
        "target_updates_source",
        "source_supersedes_target",
        "target_supersedes_source",
        "source_contains_target",
        "target_contains_source",
        "source_only",
        "target_only",
        "conflict_candidate",
        "conditional_variant",
        "uncertain",
    ):
        assert f"'{relation_type}'" in NORMALIZED
    for compatibility_field in (
        "scope_relation",
        "qualifier_compatibility",
        "temporal_compatibility",
    ):
        assert f"{compatibility_field} text not null" in NORMALIZED
    for review_status in (
        "pending",
        "auto_confirmed",
        "confirmed",
        "dismissed",
    ):
        assert f"'{review_status}'" in NORMALIZED


def test_audit_is_append_only_and_relation_review_is_optimistic() -> None:
    assert "structured_claim_audit is append-only" in SQL
    assert "before update or delete on public.structured_claim_audit" in NORMALIZED
    assert "create function public.resolve_structured_claim_relation" in NORMALIZED
    assert "p_expected_updated_at timestamptz" in NORMALIZED
    assert "using errcode = '40001'" in NORMALIZED
    assert "insert into public.structured_claim_audit" in NORMALIZED


def test_authenticated_users_can_read_but_cannot_directly_mutate_derived_data() -> None:
    for table_name in (
        "table_snapshots",
        "structured_claims",
        "claim_relations",
        "structured_claim_audit",
    ):
        assert f"alter table public.{table_name} enable row level security" in NORMALIZED
        assert f"grant select on table public.{table_name} to authenticated" in NORMALIZED
        assert (
            f"grant all privileges on table public.{table_name} to authenticated" not in NORMALIZED
        )
    assert " for insert to authenticated" not in NORMALIZED
    assert " for update to authenticated" not in NORMALIZED
    assert " for delete to authenticated" not in NORMALIZED


def test_worker_rpc_is_service_only_fenced_and_replaces_one_version_atomically() -> None:
    signature = (
        "public.replace_structured_facts_for_document( uuid, uuid, text, jsonb, jsonb, jsonb )"
    )
    assert "create function public.replace_structured_facts_for_document" in NORMALIZED
    assert "returns jsonb" in NORMALIZED
    assert "if auth.role() <> 'service_role'" in NORMALIZED
    assert "selected_job.status <> 'succeeded'" in NORMALIZED
    assert "selected_job.completion_disposition = 'duplicate_suppressed'" in NORMALIZED
    assert "a newer successful ingestion supersedes this job" in NORMALIZED
    assert "documents.canonical_document_id is null" in NORMALIZED
    assert "pg_catalog.pg_advisory_xact_lock" in NORMALIZED
    assert (
        "delete from public.table_snapshots where "
        "table_snapshots.document_id = selected_document.id"
    ) in NORMALIZED
    assert "table_snapshots.extractor_version = normalized_extractor_version" in NORMALIZED
    assert "'snapshot_count', snapshot_count" in NORMALIZED
    assert "'claim_count', claim_count" in NORMALIZED
    assert "'relation_count', relation_count" in NORMALIZED
    assert f"revoke all on function {signature}" in NORMALIZED
    assert f"grant execute on function {signature} to service_role" in NORMALIZED


def test_subject_qualifier_and_temporal_candidate_paths_are_indexed() -> None:
    for index_name in (
        "table_snapshots_document_extractor_idx",
        "table_snapshots_template_idx",
        "table_snapshots_effective_time_idx",
        "structured_claims_subject_predicate_qualifier_idx",
        "structured_claims_candidate_identity_idx",
        "structured_claims_row_predicate_idx",
        "structured_claims_effective_time_idx",
        "structured_claims_qualifiers_gin_idx",
        "structured_claims_subject_gin_idx",
        "claim_relations_review_queue_idx",
    ):
        assert f"create index {index_name}" in NORMALIZED


def test_structured_search_is_owner_guarded_citable_and_temporally_fail_closed() -> None:
    signature = (
        "public.search_structured_claims( uuid, uuid[], text, text, "
        "timestamptz, timestamptz, integer, jsonb )"
    )
    assert "create function public.search_structured_claims" in NORMALIZED
    assert "actor is distinct from selected_owner_id" in NORMALIZED
    assert "claims.source_chunk_id is not null" in NORMALIZED
    assert "claims.predicate = normalized_predicate" in NORMALIZED
    assert "claims.candidate_identity_hash = lower(normalized_subject_query)" in NORMALIZED
    assert "claims.qualifiers @> normalized_qualifiers" in NORMALIZED
    assert "p_qualifiers jsonb default '{}'::jsonb" in NORMALIZED
    assert (
        "pg_catalog.split_part(subject_segment.value, '=', 2) = lower(normalized_subject_query)"
    ) in NORMALIZED
    assert (
        "pg_catalog.strpos( lower(claims.row_identity), lower(normalized_subject_query)"
        not in NORMALIZED
    )
    assert "claims.effective_from is not null" in NORMALIZED
    assert "claims.effective_from <= query_end" in NORMALIZED
    assert "claims.effective_to, 'infinity'::timestamptz" in NORMALIZED
    assert "relation_warnings jsonb" in NORMALIZED
    assert f"revoke all on function {signature}" in NORMALIZED
    assert f"grant execute on function {signature} to authenticated, service_role" in NORMALIZED
