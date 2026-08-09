"""Contract checks for the notebook-scoped RAG relational schema.

Points at supabase/migrations/02_tables.sql (tables/constraints),
04_rls_policies.sql (grants/RLS) and 03_functions_triggers.sql (ingestion
queue + deletion RPCs) - the consolidated, always-current schema files that
replaced the incremental timestamped migration history (see
database/README.md / research/feature/note.md for why, and RESET_AND_REBUILD.sql
for the single script that applies all of them together).
"""

import re
from pathlib import Path

TABLES_SQL = Path("supabase/migrations/02_tables.sql").read_text(encoding="utf-8").lower()
RLS_SQL = Path("supabase/migrations/04_rls_policies.sql").read_text(encoding="utf-8").lower()
FUNCTIONS_SQL = (
    Path("supabase/migrations/03_functions_triggers.sql").read_text(encoding="utf-8").lower()
)
STORAGE_SQL = Path("supabase/migrations/05_storage.sql").read_text(encoding="utf-8").lower()

NORMALIZED_TABLES_SQL = re.sub(r"\s+", " ", TABLES_SQL)
NORMALIZED_RLS_SQL = re.sub(r"\s+", " ", RLS_SQL)
NORMALIZED_FUNCTIONS_SQL = re.sub(r"\s+", " ", FUNCTIONS_SQL)
NORMALIZED_STORAGE_SQL = re.sub(r"\s+", " ", STORAGE_SQL)

OWNED_TABLES = (
    "documents",
    "ingestion_jobs",
    "document_chunks",
    "conversations",
    "messages",
    "message_citations",
)
# Every owned table gets full select/insert/update/delete grants + 4 RLS
# policies, except ingestion_jobs: all writes go through the SECURITY
# DEFINER RPCs in 03_functions_triggers.sql (enqueue/claim/renew/complete/
# fail), so authenticated only gets a select grant + 1 policy there.
FULL_CRUD_TABLES = tuple(table for table in OWNED_TABLES if table != "ingestion_jobs")


def test_migration_creates_the_complete_rag_relational_model() -> None:
    assert "create table public.notebooks" in TABLES_SQL
    for table in OWNED_TABLES:
        assert f"create table public.{table}" in TABLES_SQL

    assert "constraint notebooks_id_owner_key" in NORMALIZED_TABLES_SQL
    assert "unique (id, owner_id)" in NORMALIZED_TABLES_SQL
    # notebooks + the 6 OWNED_TABLES each have their own owner_id column;
    # profiles is the only table without one (it uses id -> auth.users directly).
    assert TABLES_SQL.count("owner_id uuid not null default auth.uid()") == len(OWNED_TABLES) + 1
    assert (
        TABLES_SQL.count("references auth.users (id) on delete cascade") == len(OWNED_TABLES) + 2
    )  # +1 notebooks, +1 profiles (id, not owner_id, but same FK target)


def test_composite_foreign_keys_prevent_cross_owner_relationships() -> None:
    expected_constraints = (
        "foreign key (notebook_id, owner_id) references public.notebooks (id, owner_id)",
        "foreign key (document_id, notebook_id, owner_id) "
        "references public.documents (id, notebook_id, owner_id)",
        "foreign key (conversation_id, notebook_id, owner_id) "
        "references public.conversations (id, notebook_id, owner_id)",
        "foreign key (message_id, notebook_id, owner_id) "
        "references public.messages (id, notebook_id, owner_id)",
        "foreign key (chunk_id, document_id, notebook_id, owner_id) "
        "references public.document_chunks (id, document_id, notebook_id, owner_id)",
    )

    for constraint in expected_constraints:
        assert constraint in NORMALIZED_TABLES_SQL


def test_document_upload_contract_is_private_and_bounded() -> None:
    assert "storage_bucket = 'documents'" in TABLES_SQL
    # 10 MiB, aligned with MAX_FILE_SIZE_BYTES and the Storage bucket limit -
    # raised from the original 5 MiB (which itself superseded an even
    # earlier 25 MiB/26214400 value).
    assert "size_bytes between 1 and 10485760" in TABLES_SQL
    assert "content_hash ~ '^[0-9a-f]{64}$'" in TABLES_SQL
    assert (
        "status in ('uploading', 'uploaded', 'processing', 'ready', 'failed')"
        in NORMALIZED_TABLES_SQL
    )
    for mime_type in (
        "'application/pdf'",
        "'application/vnd.openxmlformats-officedocument.wordprocessingml.document'",
        "'text/plain'",
        "'text/markdown'",
    ):
        assert mime_type in TABLES_SQL


def test_ingestion_contract_allows_retries_but_only_one_active_job() -> None:
    assert (
        "status in ('pending', 'running', 'succeeded', 'failed', 'cancelled')"
        in NORMALIZED_TABLES_SQL
    )
    # embedding_model/embedding_dimensions are no longer pinned to one exact
    # value (text-embedding-3-small / 1536) at the table level - they're
    # just bounded/positive, so a future embedding profile change doesn't
    # need a schema migration. The worker itself still requires those exact
    # values (REQUIRED_EMBEDDING_MODEL in app/ingestion/application/worker.py).
    assert "char_length(btrim(embedding_model)) between 1 and 200" in NORMALIZED_TABLES_SQL
    assert "embedding_dimensions > 0" in TABLES_SQL
    assert "unique (document_id, attempt_number)" in NORMALIZED_TABLES_SQL
    assert "create unique index ingestion_jobs_one_active_per_document_idx" in TABLES_SQL
    assert "where status in ('pending', 'running')" in NORMALIZED_TABLES_SQL
    # Worker lease columns (added alongside the RPC-based queue).
    assert "claimed_by text" in TABLES_SQL
    assert "lease_expires_at timestamptz" in TABLES_SQL


def test_document_chunks_stores_its_own_pgvector_embedding() -> None:
    """Qdrant -> pgvector migration: the vector now lives on this table
    itself (see research/feature/note.md), it's no longer external."""
    assert "create table public.document_chunks" in TABLES_SQL
    assert "content text not null" in TABLES_SQL
    assert "token_count integer not null" in TABLES_SQL
    assert "embedding vector(1536)" in TABLES_SQL
    assert "using hnsw (embedding vector_cosine_ops)" in TABLES_SQL


def test_chat_contract_supports_independent_conversations_and_citations() -> None:
    assert "title text not null default 'new chat'" in TABLES_SQL
    assert "role in ('user', 'assistant')" in TABLES_SQL
    assert "status in ('pending', 'completed', 'failed')" in NORMALIZED_TABLES_SQL
    assert "unique (message_id, ordinal)" in NORMALIZED_TABLES_SQL
    assert "unique (message_id, chunk_id)" in NORMALIZED_TABLES_SQL


def test_every_business_table_with_full_crud_has_grants_and_owner_rls() -> None:
    for table in FULL_CRUD_TABLES:
        assert f"revoke all privileges on table public.{table} from anon" in RLS_SQL
        assert f"revoke all privileges on table public.{table} from authenticated" in RLS_SQL
        assert (
            f"grant select, insert, update, delete on table public.{table} to authenticated"
        ) in NORMALIZED_RLS_SQL
        assert f"alter table public.{table} enable row level security" in RLS_SQL
        assert f"alter table public.{table} force row level security" in RLS_SQL

        for operation in ("select", "insert", "update", "delete"):
            assert f"create policy {table}_{operation}_own" in RLS_SQL

    assert RLS_SQL.count("(select auth.uid()) = owner_id") >= len(FULL_CRUD_TABLES) * 5


def test_ingestion_jobs_is_read_only_for_authenticated() -> None:
    """Unlike the other owned tables, ingestion_jobs only allows select for
    authenticated - every state change goes through a SECURITY DEFINER RPC
    (enqueue/claim/renew/complete/fail in 03_functions_triggers.sql)."""
    assert "revoke all privileges on table public.ingestion_jobs from anon" in RLS_SQL
    assert "revoke all privileges on table public.ingestion_jobs from authenticated" in RLS_SQL
    assert "grant select on table public.ingestion_jobs to authenticated" in RLS_SQL
    assert (
        "grant select, insert, update, delete on table public.ingestion_jobs to authenticated"
        not in NORMALIZED_RLS_SQL
    )
    assert "alter table public.ingestion_jobs enable row level security" in RLS_SQL
    assert "alter table public.ingestion_jobs force row level security" in RLS_SQL
    assert "create policy ingestion_jobs_select_own" in RLS_SQL
    for operation in ("insert", "update", "delete"):
        assert f"create policy ingestion_jobs_{operation}_own" not in RLS_SQL


def test_storage_bucket_and_policies_enforce_owner_scoped_paths() -> None:
    assert "insert into storage.buckets" in STORAGE_SQL
    assert "'documents', 'documents', false" in NORMALIZED_STORAGE_SQL
    assert "10485760" in STORAGE_SQL
    assert "create policy documents_storage_insert_own" in STORAGE_SQL
    assert "create policy documents_storage_select_own" in STORAGE_SQL
    assert "create policy documents_storage_delete_own" in STORAGE_SQL
    assert "create policy documents_storage_update_own" not in STORAGE_SQL
    assert "(storage.foldername(name))[1] = (select auth.uid())::text" in STORAGE_SQL
    assert "documents.storage_object_path = storage.objects.name" in STORAGE_SQL


def test_document_upload_types_match_between_table_check_and_storage_bucket() -> None:
    expected_mime_types = (
        "application/pdf",
        "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        "application/vnd.openxmlformats-officedocument.presentationml.presentation",
        "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        "text/csv",
        "text/markdown",
        "text/html",
        "text/plain",
    )
    for mime_type in expected_mime_types:
        assert TABLES_SQL.count(f"'{mime_type}'") == 1
        assert STORAGE_SQL.count(f"'{mime_type}'") == 1


def test_upload_and_ingestion_limits_are_aligned_to_ten_mib() -> None:
    config = Path("supabase/config.toml").read_text(encoding="utf-8")

    assert "size_bytes between 1 and 10485760" in NORMALIZED_TABLES_SQL
    assert "10485760" in NORMALIZED_STORAGE_SQL
    assert 'file_size_limit = "10MiB"' in config


def test_ingestion_worker_uses_durable_service_role_leases() -> None:
    assert "create function public.enqueue_document_ingestion" in NORMALIZED_FUNCTIONS_SQL
    assert "security definer" in NORMALIZED_FUNCTIONS_SQL
    assert "create function public.claim_ingestion_job" in NORMALIZED_FUNCTIONS_SQL
    assert "for update skip locked" in NORMALIZED_FUNCTIONS_SQL
    assert "lease_expires_at" in NORMALIZED_FUNCTIONS_SQL
    assert "create function public.renew_ingestion_job_lease" in NORMALIZED_FUNCTIONS_SQL
    assert "create function public.complete_ingestion_job" in NORMALIZED_FUNCTIONS_SQL
    assert "create function public.fail_ingestion_job" in NORMALIZED_FUNCTIONS_SQL
    assert ") to authenticated" in NORMALIZED_FUNCTIONS_SQL
    assert NORMALIZED_FUNCTIONS_SQL.count("to service_role") >= 4
    assert "delete from public.document_chunks" in NORMALIZED_FUNCTIONS_SQL
    assert "insert into public.document_chunks" in NORMALIZED_FUNCTIONS_SQL
    assert "status = 'ready'" in NORMALIZED_FUNCTIONS_SQL
    assert "status = 'failed'" in NORMALIZED_FUNCTIONS_SQL


def test_document_deletion_cancels_active_ingestion_before_cleanup() -> None:
    assert "create function public.soft_delete_document" in NORMALIZED_FUNCTIONS_SQL
    assert "security definer" in NORMALIZED_FUNCTIONS_SQL
    assert "documents.owner_id = auth.uid()" in NORMALIZED_FUNCTIONS_SQL
    assert "status = 'cancelled'" in NORMALIZED_FUNCTIONS_SQL
    assert "ingestion_jobs.status in ('pending', 'running')" in NORMALIZED_FUNCTIONS_SQL
    assert "claimed_by = null" in NORMALIZED_FUNCTIONS_SQL
    assert "lease_expires_at = null" in NORMALIZED_FUNCTIONS_SQL
    assert "to authenticated" in NORMALIZED_FUNCTIONS_SQL
