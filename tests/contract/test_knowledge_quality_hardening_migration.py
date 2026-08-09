"""Contract checks for the forward knowledge-quality hardening migration."""

from pathlib import Path

MIGRATION = Path("supabase/migrations/09_knowledge_quality_hardening.sql")
SQL = MIGRATION.read_text(encoding="utf-8")
NORMALIZED_SQL = " ".join(SQL.lower().split())
STRUCTURED_FACT_SQL = Path("supabase/migrations/16_structured_fact_layer.sql").read_text(
    encoding="utf-8"
)
NORMALIZED_STRUCTURED_FACT_SQL = " ".join(STRUCTURED_FACT_SQL.lower().split())
RESET_SQL = Path("supabase/migrations/RESET_AND_REBUILD.sql").read_text(encoding="utf-8")


def _nonempty_lines(sql: str) -> tuple[str, ...]:
    return tuple(line.rstrip() for line in sql.splitlines() if line.strip())


MIGRATION_NONEMPTY_LINES = _nonempty_lines(SQL)
RESET_NONEMPTY_LINES = _nonempty_lines(RESET_SQL)
CANONICAL_MIGRATION_PATHS = tuple(sorted(Path("supabase/migrations").glob("[0-9][0-9]_*.sql")))
CANONICAL_MIGRATION_SEGMENTS = tuple(
    _nonempty_lines(path.read_text(encoding="utf-8")) for path in CANONICAL_MIGRATION_PATHS
)
ALL_CANONICAL_MIGRATION_LINES = tuple(
    line for segment in CANONICAL_MIGRATION_SEGMENTS for line in segment
)
BEHAVIOR_FIXTURE = Path("tests/fixtures/knowledge_quality_hardening_assertions.sql").read_text(
    encoding="utf-8"
)
NORMALIZED_FIXTURE = " ".join(BEHAVIOR_FIXTURE.lower().split())


def test_reset_script_contains_all_canonical_migrations_as_exact_ordered_segments() -> None:
    assert tuple(path.name[:2] for path in CANONICAL_MIGRATION_PATHS) == tuple(
        f"{index:02d}" for index in range(1, 24)
    )

    suffix_start = len(RESET_NONEMPTY_LINES) - len(ALL_CANONICAL_MIGRATION_LINES)
    assert suffix_start > 0

    cursor = suffix_start
    for segment in CANONICAL_MIGRATION_SEGMENTS:
        segment_end = cursor + len(segment)
        assert RESET_NONEMPTY_LINES[cursor:segment_end] == segment
        cursor = segment_end

    assert cursor == len(RESET_NONEMPTY_LINES)


def test_reset_script_contains_the_complete_hardening_migration() -> None:
    """Keep the migration-09 segment in exact nonblank-line parity."""
    assert any(
        RESET_NONEMPTY_LINES[start : start + len(MIGRATION_NONEMPTY_LINES)]
        == MIGRATION_NONEMPTY_LINES
        for start in range(len(RESET_NONEMPTY_LINES) - len(MIGRATION_NONEMPTY_LINES) + 1)
    )


def test_dense_search_is_tenant_safe_scoped_and_group_aware() -> None:
    assert (
        "drop function if exists public.match_document_chunks( vector, uuid[], integer )"
    ) in NORMALIZED_SQL
    assert (
        "drop function if exists public.match_document_chunks( vector, uuid, uuid[], integer )"
    ) in NORMALIZED_SQL
    assert (
        "create or replace function public.match_document_chunks( "
        "p_query_embedding vector(1536), p_owner_id uuid, "
        "p_notebook_id uuid default null"
    ) in NORMALIZED_SQL
    assert "auth.uid() is distinct from p_owner_id" in NORMALIZED_SQL
    assert "or chunks.notebook_id = p_notebook_id" in NORMALIZED_SQL
    assert "least(coalesce(p_limit, 20), 200)" in NORMALIZED_SQL
    assert "normalized_content_hash text" in NORMALIZED_SQL
    assert "exact_duplicate_group_id uuid" in NORMALIZED_SQL
    assert "chunks.normalized_content_hash" in NORMALIZED_SQL
    assert "chunks.exact_duplicate_group_id" in NORMALIZED_SQL
    assert "to authenticated, service_role" in NORMALIZED_SQL


def test_authenticated_direct_writes_cannot_mutate_protected_knowledge() -> None:
    assert (
        "revoke insert, update, delete on table public.document_chunks from authenticated"
    ) in NORMALIZED_SQL
    assert (
        "revoke insert, update, delete on table public.documents from authenticated"
    ) in NORMALIZED_SQL
    assert "grant update (status, error_message)" in NORMALIZED_SQL
    assert "grant insert ( id, owner_id, notebook_id, original_filename" in (NORMALIZED_SQL)
    assert "create or replace function public.guard_authenticated_document_write()" in (
        NORMALIZED_SQL
    )
    assert "if current_user <> 'authenticated' then" in NORMALIZED_SQL
    assert "new.storage_bucket <> 'documents'" in NORMALIZED_SQL
    assert "pg_catalog.string_to_array( new.storage_object_path, '/' )" in NORMALIZED_SQL
    assert "<> new.owner_id::text" in NORMALIZED_SQL
    assert "<> new.notebook_id::text" in NORMALIZED_SQL
    assert "<> new.id::text" in NORMALIZED_SQL
    assert "pg_catalog.strpos(" in NORMALIZED_SQL
    assert "old.status = 'uploading' and new.status = 'failed'" in NORMALIZED_SQL
    assert "document status transition requires a guarded rpc" in NORMALIZED_SQL
    assert "documents_authenticated_write_guard" in NORMALIZED_SQL


def test_chunk_fingerprints_are_persisted_backfilled_and_tenant_scoped() -> None:
    for column in (
        "normalized_content_hash",
        "normalization_version",
        "loose_content_signature",
        "exact_duplicate_group_id",
    ):
        assert f"add column if not exists {column}" in NORMALIZED_SQL
        assert f"alter column {column} set not null" in NORMALIZED_SQL

    assert "create or replace function public.knowledge_exact_chunk_group_id" in (NORMALIZED_SQL)
    assert "6ba7b811-9dad-11d1-80b4-00c04fd430c8" in NORMALIZED_SQL
    assert "'rag-chunk-exact-group:'" in NORMALIZED_SQL
    assert "p_owner_id::text" in NORMALIZED_SQL
    assert "p_notebook_id::text" in NORMALIZED_SQL
    assert "update public.document_chunks as chunks" in NORMALIZED_SQL
    assert "else 'knowledge-chunk-db-v1'" in NORMALIZED_SQL
    assert "document_chunks_exact_identity_idx" in NORMALIZED_SQL
    assert "document_chunks_exact_group_idx" in NORMALIZED_SQL
    assert "document_chunks_loose_candidate_idx" in NORMALIZED_SQL
    assert "document_chunks_exact_group_consistency" in NORMALIZED_SQL


def test_pgcrypto_digest_is_resolved_without_assuming_an_extension_schema() -> None:
    assert "from pg_catalog.pg_extension as installed_extensions" in NORMALIZED_SQL
    assert "where installed_extensions.extname = 'pgcrypto'" in NORMALIZED_SQL
    assert "create or replace function public.knowledge_digest(" in NORMALIZED_SQL
    assert "select %i.digest(p_data, p_algorithm)" in NORMALIZED_SQL
    assert "public.digest(" not in NORMALIZED_SQL
    assert "public.digest(" not in NORMALIZED_STRUCTURED_FACT_SQL
    assert "public.knowledge_digest(" in NORMALIZED_STRUCTURED_FACT_SQL


def test_pgvector_activation_and_chunk_identity_are_claim_fenced() -> None:
    assert "create function public.complete_ingestion_job(" in NORMALIZED_SQL
    assert "returns text" in NORMALIZED_SQL
    assert "return 'duplicate_suppressed';" in NORMALIZED_SQL
    assert "return 'completed';" in NORMALIZED_SQL
    assert "add column if not exists completion_disposition text" in NORMALIZED_SQL
    assert "ingestion_jobs_completion_disposition" in NORMALIZED_SQL
    assert "completion_disposition = 'duplicate_suppressed'" in NORMALIZED_SQL
    assert "completion_disposition = 'completed'" in NORMALIZED_SQL
    assert "jsonb_typeof(chunk.value -> 'embedding') is distinct from 'array'" in (NORMALIZED_SQL)
    assert "public.vector_dims(" in NORMALIZED_SQL
    assert "<> p_embedding_dimensions" in NORMALIZED_SQL
    assert "selected_job.embedding_dimensions <> p_embedding_dimensions" in NORMALIZED_SQL
    assert "ingestion_jobs.claim_token = p_claim_token" in NORMALIZED_SQL
    assert "ingestion_jobs.lease_expires_at > now()" in NORMALIZED_SQL
    assert "chunk.value -> 'metadata' ->> 'normalized_content_hash'" in NORMALIZED_SQL
    assert "chunk.value -> 'metadata' ->> 'loose_content_signature'" in NORMALIZED_SQL
    assert "chunk exact group does not match its tenant-scoped identity" in NORMALIZED_SQL
    assert "public.knowledge_exact_chunk_group_id(" in NORMALIZED_SQL
    assert "embedding = excluded.embedding" in NORMALIZED_SQL
    assert "exact_duplicate_group_id = excluded.exact_duplicate_group_id" in (NORMALIZED_SQL)

    fence_at = NORMALIZED_SQL.index("ingestion_jobs.claim_token = p_claim_token")
    delete_at = NORMALIZED_SQL.index(
        "delete from public.document_chunks",
        fence_at,
    )
    insert_at = NORMALIZED_SQL.index(
        "insert into public.document_chunks",
        delete_at,
    )
    assert fence_at < delete_at < insert_at


def test_enqueue_retry_is_idempotent_and_profile_exact() -> None:
    assert "create or replace function public.enqueue_document_ingestion(" in (NORMALIZED_SQL)
    assert "jobs.status in ('pending', 'running', 'succeeded')" in NORMALIZED_SQL
    assert "selected_job.embedding_model <> btrim(p_embedding_model)" in NORMALIZED_SQL
    assert "selected_job.embedding_dimensions <> p_embedding_dimensions" in (NORMALIZED_SQL)
    assert "selected_job.configuration <> p_configuration" in NORMALIZED_SQL
    assert "p_configuration ->> 'knowledge_quality_mode'" in NORMALIZED_SQL
    assert "selected_job.configuration ->> 'knowledge_quality_mode'" in NORMALIZED_SQL
    assert "not in ('off', 'shadow', 'on')" in NORMALIZED_SQL
    assert "ingestion profile does not match the existing job" in NORMALIZED_SQL
    assert "return next selected_document; return;" in NORMALIZED_SQL

    document_lock = NORMALIZED_SQL.index("from public.documents where documents.id = p_document_id")
    existing_job_lookup = NORMALIZED_SQL.index(
        "from public.ingestion_jobs as jobs",
        document_lock,
    )
    assert "for update" in NORMALIZED_SQL[document_lock:existing_job_lookup]


def test_database_maintenance_lease_serializes_claims_and_reconciliation() -> None:
    assert "create table if not exists public.ingestion_control" in NORMALIZED_SQL
    assert "constraint ingestion_control_singleton check (singleton)" in NORMALIZED_SQL
    assert "create or replace function public.begin_ingestion_maintenance(" in (NORMALIZED_SQL)
    assert "create or replace function public.renew_ingestion_maintenance(" in (NORMALIZED_SQL)
    assert "create or replace function public.end_ingestion_maintenance(" in (NORMALIZED_SQL)
    assert "from public.ingestion_control as controls where controls.singleton for update" in (
        NORMALIZED_SQL
    )
    assert "where ingestion_jobs.status = 'running'" in NORMALIZED_SQL
    assert "from public.ingestion_control as controls where controls.singleton for share" in (
        NORMALIZED_SQL
    )
    assert "if maintenance_active then return; end if;" in NORMALIZED_SQL
    assert "begin_ingestion_maintenance( text, integer, text ) to service_role" in (NORMALIZED_SQL)


def test_canonical_identity_and_version_invariants_are_serialized() -> None:
    assert "documents_active_normalized_identity_key" in NORMALIZED_SQL
    assert "quality_metadata ->> 'knowledge_quality_mode' = 'on'" in NORMALIZED_SQL
    assert "pg_catalog.pg_advisory_xact_lock(" in NORMALIZED_SQL
    assert "public.complete_duplicate_ingestion_job(" in NORMALIZED_SQL
    assert "automatic duplicate completion requires on mode" in NORMALIZED_SQL
    assert "enqueued_quality_mode <> 'on' or knowledge_quality_mode <> 'on'" in (NORMALIZED_SQL)
    assert "completion cannot upgrade the enqueued quality mode" in NORMALIZED_SQL
    assert "if identity_eligible and knowledge_quality_mode = 'on'" in NORMALIZED_SQL
    assert "and not is_repair_job then" in NORMALIZED_SQL
    assert "'knowledge_quality_mode', knowledge_quality_mode" in NORMALIZED_SQL
    assert "'knowledge-quality-hardening-shadow-v1'" in NORMALIZED_SQL
    assert "'backfilled as review-only; no document was suppressed'" in NORMALIZED_SQL
    assert "documents_canonical_family_version_key" in NORMALIZED_SQL
    assert "documents_one_current_canonical_per_family" in NORMALIZED_SQL
    assert "and documents.canonical_document_id is null" in NORMALIZED_SQL
    assert (
        "documents.version_group_id = family_group_id "
        "or documents.id = selected_relation.source_document_id"
    ) in NORMALIZED_SQL

    backfill_start = NORMALIZED_SQL.index("with ranked_identity as")
    backfill_end = NORMALIZED_SQL.index(
        "create unique index if not exists documents_active_normalized_identity_key",
        backfill_start,
    )
    assert "update public.documents" not in NORMALIZED_SQL[backfill_start:backfill_end]

    duplicate_start = NORMALIZED_SQL.index(
        "create or replace function public.complete_duplicate_ingestion_job("
    )
    duplicate_end = NORMALIZED_SQL.index(
        "revoke all on function public.complete_duplicate_ingestion_job(",
        duplicate_start,
    )
    duplicate_function = NORMALIZED_SQL[duplicate_start:duplicate_end]
    assert "delete from public.document_chunks" not in duplicate_function
    assert "'documents', before_documents" in duplicate_function
    assert "'documents', after_documents" in duplicate_function
    assert "'relation', before_relation" in duplicate_function


def test_reconciliation_repair_is_idempotent_cas_guarded_and_audited() -> None:
    assert "add column if not exists repair_request_key uuid" in NORMALIZED_SQL
    assert "ingestion_jobs_repair_request_key" in NORMALIZED_SQL
    assert (
        "create function public.requeue_document_ingestion_repair( "
        "p_document_id uuid, p_owner_id uuid, p_notebook_id uuid, "
        "p_request_key uuid, p_expected_updated_at timestamptz, "
        "p_report_sha256 text, "
        "p_issue_kind public.ingestion_repair_issue_kind, p_reason text"
    ) in NORMALIZED_SQL
    assert "create type public.ingestion_repair_issue_kind as enum" in NORMALIZED_SQL
    assert "'missing_vector', 'mismatch', 'missing_embedding'" in NORMALIZED_SQL
    assert "p_report_sha256 !~ '^[0-9a-f]{64}$'" in NORMALIZED_SQL
    assert "jobs.repair_request_key = p_request_key" in NORMALIZED_SQL
    assert "return next created_job; return;" in NORMALIZED_SQL
    assert "jobs.status in ('pending', 'running')" in NORMALIZED_SQL
    assert "selected_document.updated_at <> p_expected_updated_at" in NORMALIZED_SQL
    assert "and jobs.status = 'succeeded'" in NORMALIZED_SQL
    assert "'ingestion_kind', 'reconciliation_repair'" in NORMALIZED_SQL
    assert "'expected_content_hash', selected_document.content_hash" in NORMALIZED_SQL
    assert "'expected_lineage', jsonb_build_object(" in NORMALIZED_SQL
    assert "repair completion identity or lineage changed" in NORMALIZED_SQL
    assert "and not is_repair_job" in NORMALIZED_SQL
    assert "'repair_requeue'" in NORMALIZED_SQL
    assert (
        "requeue_document_ingestion_repair( "
        "uuid, uuid, uuid, uuid, timestamptz, text, "
        "public.ingestion_repair_issue_kind, text ) to service_role"
    ) in NORMALIZED_SQL


def test_resolution_snapshots_are_complete_and_revert_is_compensating() -> None:
    assert "create function public.resolve_document_relation(" in NORMALIZED_SQL
    assert "'documents', before_documents" in NORMALIZED_SQL
    assert "'documents', after_documents" in NORMALIZED_SQL
    assert "add column if not exists reverts_audit_id bigint" in NORMALIZED_SQL
    assert "knowledge_quality_audit_one_revert" in NORMALIZED_SQL
    assert (
        "create function public.revert_document_relation_resolution( "
        "p_relation_id uuid, p_notebook_id uuid, "
        "p_expected_updated_at timestamptz, p_reason text"
    ) in NORMALIZED_SQL
    assert (
        NORMALIZED_SQL.count(
            "p_reason is null or char_length(btrim(p_reason)) not between 1 and 2000"
        )
        >= 2
    )
    assert "invalid resolution reason" in NORMALIZED_SQL
    assert "invalid revert reason" in NORMALIZED_SQL
    assert "relations.owner_id = actor" in NORMALIZED_SQL
    assert "relations.notebook_id = p_notebook_id" in NORMALIZED_SQL
    assert "selected_relation.updated_at <> p_expected_updated_at" in NORMALIZED_SQL
    assert "current_documents <> original_audit.after_state -> 'documents'" in (NORMALIZED_SQL)
    assert "'revert_resolution'" in NORMALIZED_SQL
    assert "original_audit.id" in NORMALIZED_SQL
    assert "insert into public.knowledge_quality_audit" in NORMALIZED_SQL
    assert "update public.knowledge_quality_audit" not in NORMALIZED_SQL
    assert (
        "revert_document_relation_resolution( uuid, uuid, timestamptz, text ) to authenticated"
    ) in NORMALIZED_SQL


def test_behavior_fixture_exercises_the_hardening_boundaries() -> None:
    assert "enqueue retry created more than one attempt" in NORMALIZED_FIXTURE
    assert "a stale claim token activated vectors" in NORMALIZED_FIXTURE
    assert "shadow mode performed direct duplicate suppression" in NORMALIZED_FIXTURE
    assert "shadow duplicate was suppressed instead of recorded" in NORMALIZED_FIXTURE
    assert "runtime on-to-shadow rollback still suppressed data" in NORMALIZED_FIXTURE
    assert "maintenance started while a job was running" in NORMALIZED_FIXTURE
    assert "maintenance lease allowed a worker claim" in NORMALIZED_FIXTURE
    assert "automatic exact decision lacks reversible snapshots" in NORMALIZED_FIXTURE
    assert "repair request key created a duplicate attempt" in NORMALIZED_FIXTURE
    assert "repair accepted a second active request" in NORMALIZED_FIXTURE
    assert "repair accepted a stale document timestamp" in NORMALIZED_FIXTURE
    assert "canonical completion returned the wrong disposition" in NORMALIZED_FIXTURE
    assert "duplicate completion returned the wrong disposition" in NORMALIZED_FIXTURE
    assert "completion disposition was not durably persisted" in NORMALIZED_FIXTURE
    assert "strict-identical chunks were not grouped" in NORMALIZED_FIXTURE
    assert "database chunk group uuidv5 differs from the application formula" in (
        NORMALIZED_FIXTURE
    )
    assert "cross-owner dense retrieval was accepted" in NORMALIZED_FIXTURE
    assert "serialized version resolution did not advance lineage" in (NORMALIZED_FIXTURE)
    assert "resolution accepted a null reason" in NORMALIZED_FIXTURE
    assert "revert accepted a null reason" in NORMALIZED_FIXTURE
    assert "revert did not restore the complete prior snapshot" in NORMALIZED_FIXTURE
    assert "revert did not append a compensating audit event" in NORMALIZED_FIXTURE
