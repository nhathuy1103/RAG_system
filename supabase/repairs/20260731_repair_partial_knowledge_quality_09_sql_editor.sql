-- Prepare a very specific mixed migration-08/09 database for a safe migration-09 rerun.
--
-- Observed pre-repair state:
--   * migration 08 is incomplete (document identity columns/FKs/claim_token missing);
--   * migration 09 is fragmented: dense scope, maintenance and guarded revert exist;
--   * claim/enqueue/chunk identity/canonical indexes/repair path are incomplete;
--   * an unscoped three-input dense-search overload is still exposed;
--   * migration 10 has not been applied.
--
-- Before running:
--   1. Stop API/worker traffic.
--   2. Take and verify a database backup.
--   3. Run supabase/diagnostics/09_10_partial_schema_audit.sql and retain its output.
--
-- This is phase 1 of 2. It repairs the migration-08 baseline, removes unsafe
-- legacy overloads, and installs a migration-09-compatible claim RPC. After it
-- commits, immediately run 09_knowledge_quality_hardening.sql from the top while
-- traffic remains stopped. This script intentionally refuses full migration 09
-- or any migration-10 marker. Every change below is transactional.

begin;

set local lock_timeout = '10s';
set local statement_timeout = '10min';

do $repair_lock$
begin
    perform pg_advisory_xact_lock(
        hashtext('agentic-rag:repair-partial-knowledge-quality-09')
    );
end;
$repair_lock$;

do $repair$
begin
    if to_regclass('public.ingestion_control') is null
       or not exists (
           select 1
           from pg_catalog.pg_proc as functions
           join pg_catalog.pg_namespace as namespaces
             on namespaces.oid = functions.pronamespace
           where namespaces.nspname = 'public'
             and functions.proname = 'match_document_chunks'
             and pg_get_function_identity_arguments(functions.oid) =
                 'p_query_embedding vector, p_owner_id uuid, p_notebook_id uuid, p_document_ids uuid[], p_limit integer'
             and pg_get_function_result(functions.oid)
                 like '%normalized_content_hash%'
             and pg_get_function_result(functions.oid)
                 like '%exact_duplicate_group_id%'
       ) then
        raise exception
            'Repair preflight failed: database is not the expected mixed migration-08/09 state';
    end if;

    if to_regprocedure(
        'public.complete_ingestion_job(uuid,text,uuid,text,integer,jsonb,text,text,text,jsonb,jsonb)'
       ) is null
       or to_regprocedure(
        'public.complete_duplicate_ingestion_job(uuid,text,uuid,uuid,text,text,text,jsonb)'
       ) is null
       or to_regprocedure(
        'public.resolve_document_relation(uuid,uuid,text,timestamptz,text)'
       ) is null
       or to_regprocedure(
        'public.revert_document_relation_resolution(uuid,uuid,timestamptz,text)'
       ) is null
       or to_regprocedure(
        'public.knowledge_exact_chunk_group_id(uuid,uuid,text,text)'
       ) is null then
        raise exception
            'Repair preflight failed: required migration-09 sentinels are missing';
    end if;

    if not exists (
        select 1
        from information_schema.columns
        where table_schema = 'public'
          and table_name = 'knowledge_quality_audit'
          and column_name = 'reverts_audit_id'
          and udt_name = 'int8'
    ) then
        raise exception
            'Repair preflight failed: guarded-revert audit column is missing or incompatible';
    end if;

    if to_regclass('public.document_chunks_simhash_band_1_idx') is not null
       or to_regprocedure(
        'public.find_chunk_dedup_candidates(uuid,uuid,uuid,text,jsonb,integer)'
       ) is not null then
        raise exception
            'Repair preflight failed: migration 10 is already present';
    end if;

    if to_regclass('public.documents_active_normalized_identity_key') is not null
       and to_regclass('public.documents_canonical_family_version_key') is not null
       and to_regclass('public.documents_one_current_canonical_per_family') is not null
       and to_regprocedure(
        'public.requeue_document_ingestion_repair(uuid,uuid,uuid,uuid,timestamptz,text,public.ingestion_repair_issue_kind,text)'
       ) is not null then
        raise exception
            'Repair preflight failed: migration 09 is already complete';
    end if;

    if not exists (
        select 1
        from pg_catalog.pg_class as tables
        join pg_catalog.pg_namespace as namespaces
          on namespaces.oid = tables.relnamespace
        where namespaces.nspname = 'public'
          and tables.relname = 'document_relations'
          and tables.relkind = 'r'
    ) then
        raise exception
            'Repair preflight failed: public.document_relations is not a regular table';
    end if;

    if not exists (
        select 1
        from pg_catalog.pg_class as tables
        join pg_catalog.pg_namespace as namespaces
          on namespaces.oid = tables.relnamespace
        where namespaces.nspname = 'public'
          and tables.relname = 'knowledge_quality_audit'
          and tables.relkind = 'r'
    ) then
        raise exception
            'Repair preflight failed: public.knowledge_quality_audit is not a regular table';
    end if;
end;
$repair$;

lock table
    public.documents,
    public.ingestion_jobs,
    public.document_chunks,
    public.document_relations,
    public.knowledge_quality_audit,
    public.ingestion_control
in access exclusive mode;

do $repair$
declare
    incompatible_control_columns text;
    actual_issue_labels text[];
begin
    with expected(column_name, udt_name, nullable) as (
        values
            ('singleton', 'bool', false),
            ('maintenance_token', 'uuid', true),
            ('maintenance_owner', 'text', true),
            ('maintenance_reason', 'text', true),
            ('maintenance_expires_at', 'timestamptz', true),
            ('updated_at', 'timestamptz', false)
    )
    select string_agg(expected.column_name, ', ' order by expected.column_name)
    into incompatible_control_columns
    from expected
    left join information_schema.columns as actual
      on actual.table_schema = 'public'
     and actual.table_name = 'ingestion_control'
     and actual.column_name = expected.column_name
    where actual.column_name is null
       or actual.udt_name <> expected.udt_name
       or (actual.is_nullable = 'YES') <> expected.nullable;

    if incompatible_control_columns is not null then
        raise exception
            'Repair preflight failed: incompatible ingestion_control columns: %',
            incompatible_control_columns;
    end if;

    if not exists (
        select 1 from public.ingestion_control where singleton
    ) then
        raise exception
            'Repair preflight failed: ingestion_control singleton row is missing';
    end if;

    if exists (
        select 1
        from public.ingestion_control
        where singleton
          and maintenance_token is not null
          and maintenance_expires_at > now()
    ) then
        raise exception
            'Repair preflight failed: an ingestion maintenance lease is active'
            using errcode = '55P03';
    end if;

    if exists (
        select 1
        from public.ingestion_jobs
        where status = 'running'
          and lease_expires_at > now()
    ) then
        raise exception
            'Repair preflight failed: wait for running ingestion leases to expire'
            using errcode = '55P03';
    end if;

    select array_agg(enums.enumlabel::text order by enums.enumsortorder)
    into actual_issue_labels
    from pg_catalog.pg_type as types
    join pg_catalog.pg_namespace as namespaces
      on namespaces.oid = types.typnamespace
    join pg_catalog.pg_enum as enums
      on enums.enumtypid = types.oid
    where namespaces.nspname = 'public'
      and types.typname = 'ingestion_repair_issue_kind';

    if actual_issue_labels is distinct from array[
        'missing_vector', 'mismatch', 'missing_embedding'
    ]::text[] then
        raise exception
            'Repair preflight failed: incompatible ingestion_repair_issue_kind labels: %',
            actual_issue_labels;
    end if;
end;
$repair$;

-- This SQL-Editor variant intentionally skips the relation/audit preservation
-- snapshot used by the canonical repair script. It is only valid after
-- confirming document_relations and knowledge_quality_audit are both empty.

-- Refuse to keep a same-named table whose shape differs from migration 08.
do $repair$
declare
    incompatible_columns text;
begin
    with expected_columns(
        table_name,
        column_name,
        udt_name,
        nullable,
        needs_default,
        needs_identity
    ) as (
        values
            ('document_relations', 'id', 'uuid', false, true, false),
            ('document_relations', 'owner_id', 'uuid', false, false, false),
            ('document_relations', 'notebook_id', 'uuid', false, false, false),
            ('document_relations', 'source_document_id', 'uuid', false, false, false),
            ('document_relations', 'target_document_id', 'uuid', false, false, false),
            ('document_relations', 'relation_type', 'text', false, false, false),
            ('document_relations', 'status', 'text', false, true, false),
            ('document_relations', 'confidence', 'float8', false, true, false),
            ('document_relations', 'signals', 'jsonb', false, true, false),
            ('document_relations', 'reason', 'text', true, false, false),
            ('document_relations', 'detector_version', 'text', false, true, false),
            ('document_relations', 'preferred_document_id', 'uuid', true, false, false),
            ('document_relations', 'resolved_by', 'uuid', true, false, false),
            ('document_relations', 'resolved_at', 'timestamptz', true, false, false),
            ('document_relations', 'created_at', 'timestamptz', false, true, false),
            ('document_relations', 'updated_at', 'timestamptz', false, true, false),
            ('knowledge_quality_audit', 'id', 'int8', false, false, true),
            ('knowledge_quality_audit', 'owner_id', 'uuid', false, false, false),
            ('knowledge_quality_audit', 'notebook_id', 'uuid', false, false, false),
            ('knowledge_quality_audit', 'relation_id', 'uuid', true, false, false),
            ('knowledge_quality_audit', 'actor_id', 'uuid', true, false, false),
            ('knowledge_quality_audit', 'action', 'text', false, false, false),
            ('knowledge_quality_audit', 'reason', 'text', true, false, false),
            ('knowledge_quality_audit', 'before_state', 'jsonb', false, true, false),
            ('knowledge_quality_audit', 'after_state', 'jsonb', false, true, false),
            ('knowledge_quality_audit', 'created_at', 'timestamptz', false, true, false)
    )
    select string_agg(
        format('%I.%I', expected.table_name, expected.column_name),
        ', '
        order by expected.table_name, expected.column_name
    )
    into incompatible_columns
    from expected_columns as expected
    left join information_schema.columns as actual
      on actual.table_schema = 'public'
     and actual.table_name = expected.table_name
     and actual.column_name = expected.column_name
    where actual.column_name is null
       or actual.udt_name <> expected.udt_name
       or (actual.is_nullable = 'YES') <> expected.nullable
       or (
            expected.needs_default
            and actual.column_default is null
            and actual.is_identity <> 'YES'
       )
       or (
            expected.needs_identity
            and actual.is_identity <> 'YES'
       );

    if incompatible_columns is not null then
        raise exception
            'Repair preflight failed: incompatible relation/audit columns: %',
            incompatible_columns;
    end if;

    if exists (
        select 1
        from public.document_relations as relations
        left join public.documents as source_documents
          on source_documents.id = relations.source_document_id
         and source_documents.notebook_id = relations.notebook_id
         and source_documents.owner_id = relations.owner_id
        where source_documents.id is null
    ) then
        raise exception
            'Repair preflight failed: a relation source is outside its owner/notebook scope'
            using errcode = '23503';
    end if;

    if exists (
        select 1
        from public.document_relations as relations
        left join public.documents as target_documents
          on target_documents.id = relations.target_document_id
         and target_documents.notebook_id = relations.notebook_id
         and target_documents.owner_id = relations.owner_id
        where target_documents.id is null
    ) then
        raise exception
            'Repair preflight failed: a relation target is outside its owner/notebook scope'
            using errcode = '23503';
    end if;

    if exists (
        select 1
        from public.document_relations as relations
        left join public.documents as preferred_documents
          on preferred_documents.id = relations.preferred_document_id
         and preferred_documents.notebook_id = relations.notebook_id
         and preferred_documents.owner_id = relations.owner_id
        where relations.preferred_document_id is not null
          and preferred_documents.id is null
    ) then
        raise exception
            'Repair preflight failed: a preferred document is outside its owner/notebook scope'
            using errcode = '23503';
    end if;

    if exists (
        select 1
        from public.knowledge_quality_audit as audit
        left join public.notebooks as notebooks
          on notebooks.id = audit.notebook_id
         and notebooks.owner_id = audit.owner_id
        where notebooks.id is null
    ) then
        raise exception
            'Repair preflight failed: an audit row is outside its owner/notebook scope'
            using errcode = '23503';
    end if;

    raise notice 'Repair will preserve % existing relation rows and % audit rows',
        (select count(*) from public.document_relations),
        (select count(*) from public.knowledge_quality_audit);
end;
$repair$;

-- ---------------------------------------------------------------------------
-- Complete migration-08 document identity/lineage schema.
-- ---------------------------------------------------------------------------

do $repair$
declare
    incompatible_columns text;
begin
    with expected_columns(column_name, udt_name) as (
        values
            ('normalized_content_hash', 'text'),
            ('normalization_version', 'text'),
            ('loose_content_signature', 'text'),
            ('canonical_document_id', 'uuid'),
            ('version_group_id', 'uuid'),
            ('version_number', 'int4'),
            ('effective_from', 'date'),
            ('effective_to', 'date'),
            ('supersedes_document_id', 'uuid'),
            ('is_current', 'bool'),
            ('quality_status', 'text'),
            ('quality_metadata', 'jsonb')
    )
    select string_agg(expected.column_name, ', ' order by expected.column_name)
    into incompatible_columns
    from expected_columns as expected
    join information_schema.columns as actual
      on actual.table_schema = 'public'
     and actual.table_name = 'documents'
     and actual.column_name = expected.column_name
    where actual.udt_name <> expected.udt_name;

    if incompatible_columns is not null then
        raise exception
            'Repair preflight failed: migration-08 document columns have incompatible types: %',
            incompatible_columns;
    end if;
end;
$repair$;

alter table public.documents
    add column if not exists normalized_content_hash text,
    add column if not exists normalization_version text,
    add column if not exists loose_content_signature text,
    add column if not exists canonical_document_id uuid,
    add column if not exists version_group_id uuid,
    add column if not exists version_number integer,
    add column if not exists effective_from date,
    add column if not exists effective_to date,
    add column if not exists supersedes_document_id uuid,
    add column if not exists is_current boolean,
    add column if not exists quality_status text,
    add column if not exists quality_metadata jsonb;

alter table public.documents
    alter column version_group_id set default gen_random_uuid(),
    alter column version_number set default 1,
    alter column is_current set default true,
    alter column quality_status set default 'unreviewed',
    alter column quality_metadata set default '{}'::jsonb;

update public.documents
set
    version_group_id = coalesce(version_group_id, gen_random_uuid()),
    version_number = coalesce(version_number, 1),
    is_current = coalesce(is_current, true),
    quality_status = coalesce(quality_status, 'unreviewed'),
    quality_metadata = coalesce(quality_metadata, '{}'::jsonb)
where version_group_id is null
   or version_number is null
   or is_current is null
   or quality_status is null
   or quality_metadata is null;

alter table public.documents
    alter column version_group_id set not null,
    alter column version_number set not null,
    alter column is_current set not null,
    alter column quality_status set not null,
    alter column quality_metadata set not null;

alter table public.documents
    drop constraint if exists documents_normalized_content_hash,
    drop constraint if exists documents_normalization_version,
    drop constraint if exists documents_loose_content_signature,
    drop constraint if exists documents_version_number,
    drop constraint if exists documents_effective_range,
    drop constraint if exists documents_quality_status,
    drop constraint if exists documents_quality_metadata,
    drop constraint if exists documents_canonical_not_self,
    drop constraint if exists documents_supersedes_not_self,
    drop constraint if exists documents_canonical_owner_fk,
    drop constraint if exists documents_supersedes_owner_fk;

alter table public.documents
    add constraint documents_normalized_content_hash
        check (
            normalized_content_hash is null
            or normalized_content_hash ~ '^[0-9a-f]{64}$'
        ),
    add constraint documents_normalization_version
        check (
            normalization_version is null
            or char_length(btrim(normalization_version)) between 1 and 100
        ),
    add constraint documents_loose_content_signature
        check (
            loose_content_signature is null
            or loose_content_signature ~ '^[0-9a-f]{16}$'
        ),
    add constraint documents_version_number
        check (version_number > 0),
    add constraint documents_effective_range
        check (
            effective_from is null
            or effective_to is null
            or effective_from <= effective_to
        ),
    add constraint documents_quality_status
        check (
            quality_status in (
                'unreviewed',
                'clean',
                'review_required',
                'duplicate',
                'superseded',
                'conflict'
            )
        ),
    add constraint documents_quality_metadata
        check (jsonb_typeof(quality_metadata) = 'object'),
    add constraint documents_canonical_not_self
        check (canonical_document_id is null or canonical_document_id <> id),
    add constraint documents_supersedes_not_self
        check (supersedes_document_id is null or supersedes_document_id <> id),
    add constraint documents_canonical_owner_fk
        foreign key (canonical_document_id, notebook_id, owner_id)
        references public.documents (id, notebook_id, owner_id)
        on delete restrict,
    add constraint documents_supersedes_owner_fk
        foreign key (supersedes_document_id, notebook_id, owner_id)
        references public.documents (id, notebook_id, owner_id)
        on delete restrict;

comment on column public.documents.normalized_content_hash is
    'SHA-256 of strictly normalized extracted text; identity only within normalization_version.';
comment on column public.documents.loose_content_signature is
    '64-bit SimHash candidate signature. It must never be used as authoritative identity.';
comment on column public.documents.canonical_document_id is
    'Canonical document for an exact-content alias; null means this row is canonical.';
comment on column public.documents.version_group_id is
    'Stable lineage identifier shared by confirmed versions of the same logical document.';
comment on column public.documents.quality_status is
    'Operational summary; document_relations is the source of truth for review decisions.';

create index if not exists documents_normalized_hash_idx
    on public.documents (
        owner_id,
        notebook_id,
        normalization_version,
        normalized_content_hash
    )
    where normalized_content_hash is not null and is_active;

create index if not exists documents_loose_signature_idx
    on public.documents (owner_id, notebook_id, loose_content_signature)
    where loose_content_signature is not null and is_active;

create index if not exists documents_version_group_idx
    on public.documents (
        owner_id,
        notebook_id,
        version_group_id,
        version_number desc
    );

create index if not exists documents_current_idx
    on public.documents (owner_id, notebook_id, updated_at desc)
    where is_active and is_current and canonical_document_id is null;

-- ---------------------------------------------------------------------------
-- Restore generation-token fencing for ingestion claims.
-- ---------------------------------------------------------------------------

alter table public.ingestion_jobs
    add column if not exists claim_token uuid;

update public.ingestion_jobs
set claim_token = gen_random_uuid()
where status = 'running' and claim_token is null;

update public.ingestion_jobs
set claim_token = null
where status <> 'running' and claim_token is not null;

alter table public.ingestion_jobs
    drop constraint if exists ingestion_jobs_claim;

alter table public.ingestion_jobs
    add constraint ingestion_jobs_claim
        check (
            (
                status = 'running'
                and claimed_by is not null
                and lease_expires_at is not null
                and claim_token is not null
            )
            or
            (
                status <> 'running'
                and claimed_by is null
                and lease_expires_at is null
                and claim_token is null
            )
        );

-- ---------------------------------------------------------------------------
-- Restore the four missing tenant-scoping foreign keys without replacing data.
-- ---------------------------------------------------------------------------

alter table public.document_relations
    drop constraint if exists document_relations_source_owner_fk,
    drop constraint if exists document_relations_target_owner_fk,
    drop constraint if exists document_relations_preferred_owner_fk;

alter table public.document_relations
    add constraint document_relations_source_owner_fk
        foreign key (source_document_id, notebook_id, owner_id)
        references public.documents (id, notebook_id, owner_id)
        on delete cascade,
    add constraint document_relations_target_owner_fk
        foreign key (target_document_id, notebook_id, owner_id)
        references public.documents (id, notebook_id, owner_id)
        on delete cascade,
    add constraint document_relations_preferred_owner_fk
        foreign key (preferred_document_id, notebook_id, owner_id)
        references public.documents (id, notebook_id, owner_id)
        on delete restrict;

alter table public.knowledge_quality_audit
    drop constraint if exists knowledge_quality_audit_notebook_owner_fk;

alter table public.knowledge_quality_audit
    add constraint knowledge_quality_audit_notebook_owner_fk
        foreign key (notebook_id, owner_id)
        references public.notebooks (id, owner_id)
        on delete cascade;

-- Preserve existing byte-identical uploads by making later copies aliases of
-- the earliest active row before enforcing atomic exact-byte uniqueness.
with ranked_documents as (
    select
        documents.id,
        documents.owner_id,
        documents.notebook_id,
        documents.content_hash,
        first_value(documents.id) over duplicate_group as canonical_id,
        row_number() over duplicate_group as duplicate_rank
    from public.documents
    where documents.content_hash is not null
      and documents.is_active
      and documents.status <> 'failed'
      and to_regclass('public.documents_active_exact_content_key') is null
    window duplicate_group as (
        partition by
            documents.owner_id,
            documents.notebook_id,
            documents.content_hash
        order by documents.created_at, documents.id
    )
)
update public.documents as duplicate
set
    canonical_document_id = ranked_documents.canonical_id,
    version_group_id = canonical.version_group_id,
    version_number = canonical.version_number,
    is_current = false,
    quality_status = 'duplicate',
    quality_metadata = duplicate.quality_metadata
        || jsonb_build_object('backfilled_exact_upload_duplicate', true)
from ranked_documents
join public.documents as canonical
  on canonical.id = ranked_documents.canonical_id
where duplicate.id = ranked_documents.id
  and ranked_documents.duplicate_rank > 1;

insert into public.document_relations (
    owner_id,
    notebook_id,
    source_document_id,
    target_document_id,
    relation_type,
    status,
    confidence,
    signals,
    reason,
    detector_version
)
select
    duplicate.owner_id,
    duplicate.notebook_id,
    duplicate.id,
    duplicate.canonical_document_id,
    'technical_duplicate',
    'auto_confirmed',
    1,
    jsonb_build_object('content_hash', duplicate.content_hash),
    'Backfilled from an existing byte-identical upload',
    'migration-08'
from public.documents as duplicate
where duplicate.canonical_document_id is not null
  and duplicate.content_hash is not null
  and to_regclass('public.documents_active_exact_content_key') is null
on conflict (source_document_id, target_document_id, detector_version)
do nothing;

create unique index if not exists documents_active_exact_content_key
    on public.documents (owner_id, notebook_id, content_hash)
    where (
        content_hash is not null
        and is_active
        and status <> 'failed'
        and canonical_document_id is null
    );

-- Remove old dense-search overloads whose signatures either omit owner scope
-- or keep the migration-06 result shape. The migration-09 canonical signature
-- is re-run in phase 2 and must remain present here.
drop function if exists public.match_document_chunks(
    vector, uuid[], integer
);
drop function if exists public.match_document_chunks(
    vector, uuid, uuid[], integer
);

-- The legacy and fenced functions share an input signature but have different
-- TABLE result shapes, so CREATE OR REPLACE cannot upgrade this RPC safely.
drop function if exists public.claim_ingestion_job(text, integer);
drop function if exists public.renew_ingestion_job_lease(uuid, text, integer);
drop function if exists public.complete_ingestion_job(
    uuid, text, text, integer, jsonb
);
drop function if exists public.fail_ingestion_job(uuid, text, text);
drop function if exists public.resolve_document_relation(
    uuid, uuid, text, text
);

create function public.claim_ingestion_job(
    p_worker_id text,
    p_lease_seconds integer
)
returns table (
    id uuid,
    owner_id uuid,
    notebook_id uuid,
    document_id uuid,
    attempt_number integer,
    configuration jsonb,
    storage_bucket text,
    storage_object_path text,
    original_filename text,
    mime_type text,
    size_bytes bigint,
    content_hash text,
    claim_token uuid,
    document_version integer
)
language plpgsql
security definer
set search_path = ''
as $$
declare
    maintenance_active boolean;
begin
    if auth.role() <> 'service_role' then
        raise exception 'Service role is required'
            using errcode = '42501';
    end if;
    if p_worker_id is null
       or char_length(btrim(p_worker_id)) = 0
       or p_lease_seconds is null
       or p_lease_seconds < 30 then
        raise exception 'Invalid worker lease'
            using errcode = '22023';
    end if;

    select (
        controls.maintenance_token is not null
        and controls.maintenance_expires_at > now()
    )
    into maintenance_active
    from public.ingestion_control as controls
    where controls.singleton
    for share;

    if not found then
        raise exception 'Ingestion control row is unavailable'
            using errcode = 'P0002';
    end if;
    if maintenance_active then
        return;
    end if;

    return query
    with candidate as (
        select jobs.id
        from public.ingestion_jobs as jobs
        where jobs.status = 'pending'
           or (
                jobs.status = 'running'
                and jobs.lease_expires_at <= now()
           )
        order by jobs.created_at, jobs.id
        for update skip locked
        limit 1
    ),
    claimed as (
        update public.ingestion_jobs as jobs
        set
            status = 'running',
            claimed_by = btrim(p_worker_id),
            claim_token = gen_random_uuid(),
            lease_expires_at = now() + make_interval(secs => p_lease_seconds),
            started_at = coalesce(jobs.started_at, now()),
            error_message = null,
            updated_at = now()
        from candidate
        where jobs.id = candidate.id
        returning jobs.*
    )
    select
        claimed.id,
        claimed.owner_id,
        claimed.notebook_id,
        claimed.document_id,
        claimed.attempt_number,
        claimed.configuration,
        documents.storage_bucket,
        documents.storage_object_path,
        documents.original_filename,
        documents.mime_type,
        documents.size_bytes,
        documents.content_hash,
        claimed.claim_token,
        documents.version_number
    from claimed
    join public.documents
      on documents.id = claimed.document_id
     and documents.notebook_id = claimed.notebook_id
     and documents.owner_id = claimed.owner_id;
end;
$$;

revoke all on function public.claim_ingestion_job(text, integer)
from public, anon, authenticated;
grant execute on function public.claim_ingestion_job(text, integer)
to service_role;

create or replace function public.renew_ingestion_job_lease(
    p_job_id uuid,
    p_worker_id text,
    p_claim_token uuid,
    p_lease_seconds integer
)
returns boolean
language plpgsql
security definer
set search_path = ''
as $$
declare
    updated_count integer;
begin
    if auth.role() <> 'service_role' then
        raise exception 'Service role is required'
            using errcode = '42501';
    end if;
    if p_lease_seconds < 30 then
        raise exception 'Invalid worker lease'
            using errcode = '22023';
    end if;

    update public.ingestion_jobs
    set
        lease_expires_at = now() + make_interval(secs => p_lease_seconds),
        updated_at = now()
    where ingestion_jobs.id = p_job_id
      and ingestion_jobs.status = 'running'
      and ingestion_jobs.claimed_by = btrim(p_worker_id)
      and ingestion_jobs.claim_token = p_claim_token
      and ingestion_jobs.lease_expires_at > now();

    get diagnostics updated_count = row_count;
    return updated_count = 1;
end;
$$;

create or replace function public.fail_ingestion_job(
    p_job_id uuid,
    p_worker_id text,
    p_claim_token uuid,
    p_error_message text
)
returns boolean
language plpgsql
security definer
set search_path = ''
as $$
declare
    selected_job public.ingestion_jobs;
begin
    if auth.role() <> 'service_role' then
        raise exception 'Service role is required'
            using errcode = '42501';
    end if;
    if p_error_message is null or char_length(btrim(p_error_message)) = 0 then
        raise exception 'Error message must not be empty'
            using errcode = '22023';
    end if;

    select ingestion_jobs.*
    into selected_job
    from public.ingestion_jobs
    where ingestion_jobs.id = p_job_id
      and ingestion_jobs.status = 'running'
      and ingestion_jobs.claimed_by = btrim(p_worker_id)
      and ingestion_jobs.claim_token = p_claim_token
      and ingestion_jobs.lease_expires_at > now()
    for update;

    if not found then
        return false;
    end if;

    update public.ingestion_jobs
    set
        status = 'failed',
        completed_at = now(),
        error_message = btrim(p_error_message),
        claimed_by = null,
        claim_token = null,
        lease_expires_at = null,
        updated_at = now()
    where ingestion_jobs.id = selected_job.id;

    update public.documents
    set
        status = 'failed',
        error_message = btrim(p_error_message),
        updated_at = now()
    where documents.id = selected_job.document_id
      and documents.notebook_id = selected_job.notebook_id
      and documents.owner_id = selected_job.owner_id;

    return true;
end;
$$;

-- The observed soft-delete path is still compatible with the legacy job
-- schema. Reinstall the migration-08 body so cancellation also clears the
-- newly restored generation token.
create or replace function public.soft_delete_document(
    p_document_id uuid,
    p_notebook_id uuid
)
returns setof public.documents
language plpgsql
security definer
set search_path = ''
as $$
declare
    selected_document public.documents;
begin
    if auth.uid() is null then
        raise exception 'Authentication is required'
            using errcode = '42501';
    end if;

    select documents.*
    into selected_document
    from public.documents
    where documents.id = p_document_id
      and documents.notebook_id = p_notebook_id
      and documents.owner_id = auth.uid()
      and documents.is_active;

    if not found then
        return;
    end if;

    update public.ingestion_jobs
    set
        status = 'cancelled',
        completed_at = now(),
        error_message = 'Document was archived (soft-deleted)',
        claimed_by = null,
        claim_token = null,
        lease_expires_at = null,
        updated_at = now()
    where ingestion_jobs.document_id = selected_document.id
      and ingestion_jobs.notebook_id = selected_document.notebook_id
      and ingestion_jobs.owner_id = selected_document.owner_id
      and ingestion_jobs.status in ('pending', 'running');

    update public.documents
    set is_active = false, updated_at = now()
    where documents.id = selected_document.id
      and documents.notebook_id = selected_document.notebook_id
      and documents.owner_id = selected_document.owner_id
    returning documents.* into selected_document;

    return next selected_document;
end;
$$;

revoke all on function public.soft_delete_document(uuid, uuid)
from public, anon;
grant execute on function public.soft_delete_document(uuid, uuid)
to authenticated;

revoke all on function public.resolve_document_relation(
    uuid, uuid, text, timestamptz, text
) from public, anon;
grant execute on function public.resolve_document_relation(
    uuid, uuid, text, timestamptz, text
) to authenticated;

create or replace function public.prevent_knowledge_quality_audit_mutation()
returns trigger
language plpgsql
set search_path = ''
as $$
begin
    if pg_trigger_depth() > 1 then
        return null;
    end if;
    raise exception 'knowledge_quality_audit is append-only'
        using errcode = '42501';
end;
$$;

drop trigger if exists knowledge_quality_audit_immutable
on public.knowledge_quality_audit;
create trigger knowledge_quality_audit_immutable
before update or delete on public.knowledge_quality_audit
for each statement
execute function public.prevent_knowledge_quality_audit_mutation();

-- Reassert migration-08 privileges and RLS without exposing direct writes.
revoke all privileges on table public.document_relations from anon;
revoke all privileges on table public.document_relations from authenticated;
grant select on table public.document_relations to authenticated;
grant all privileges on table public.document_relations to service_role;

revoke all privileges on table public.knowledge_quality_audit from anon;
revoke all privileges on table public.knowledge_quality_audit from authenticated;
grant select on table public.knowledge_quality_audit to authenticated;
grant select, insert on table public.knowledge_quality_audit to service_role;
grant usage, select on sequence public.knowledge_quality_audit_id_seq
to service_role;

alter table public.document_relations enable row level security;
alter table public.document_relations force row level security;
alter table public.knowledge_quality_audit enable row level security;
alter table public.knowledge_quality_audit force row level security;

drop policy if exists document_relations_select_own
on public.document_relations;
create policy document_relations_select_own
on public.document_relations for select to authenticated
using ((select auth.uid()) = owner_id);

drop policy if exists knowledge_quality_audit_select_own
on public.knowledge_quality_audit;
create policy knowledge_quality_audit_select_own
on public.knowledge_quality_audit for select to authenticated
using ((select auth.uid()) = owner_id);

-- Reassert execution grants for the already-present baseline/migration-09 RPCs.
revoke all on function public.renew_ingestion_job_lease(
    uuid, text, uuid, integer
) from public, anon, authenticated;
grant execute on function public.renew_ingestion_job_lease(
    uuid, text, uuid, integer
) to service_role;

revoke all on function public.complete_ingestion_job(
    uuid, text, uuid, text, integer, jsonb, text, text, text, jsonb, jsonb
) from public, anon, authenticated;
grant execute on function public.complete_ingestion_job(
    uuid, text, uuid, text, integer, jsonb, text, text, text, jsonb, jsonb
) to service_role;

revoke all on function public.complete_duplicate_ingestion_job(
    uuid, text, uuid, uuid, text, text, text, jsonb
) from public, anon, authenticated;
grant execute on function public.complete_duplicate_ingestion_job(
    uuid, text, uuid, uuid, text, text, text, jsonb
) to service_role;

revoke all on function public.fail_ingestion_job(
    uuid, text, uuid, text
) from public, anon, authenticated;
grant execute on function public.fail_ingestion_job(
    uuid, text, uuid, text
) to service_role;

-- ---------------------------------------------------------------------------
-- Postconditions: any failure below rolls back every change above.
-- ---------------------------------------------------------------------------

do $repair$
declare
    missing_objects text;
    dense_result text;
begin
    with required_columns(table_name, column_name) as (
        values
            ('documents', 'normalized_content_hash'),
            ('documents', 'normalization_version'),
            ('documents', 'loose_content_signature'),
            ('documents', 'canonical_document_id'),
            ('documents', 'version_group_id'),
            ('documents', 'version_number'),
            ('documents', 'effective_from'),
            ('documents', 'effective_to'),
            ('documents', 'supersedes_document_id'),
            ('documents', 'is_current'),
            ('documents', 'quality_status'),
            ('documents', 'quality_metadata'),
            ('ingestion_jobs', 'claim_token')
    )
    select string_agg(
        format('%I.%I', required.table_name, required.column_name),
        ', '
    )
    into missing_objects
    from required_columns as required
    left join information_schema.columns as actual
      on actual.table_schema = 'public'
     and actual.table_name = required.table_name
     and actual.column_name = required.column_name
    where actual.column_name is null;

    if missing_objects is not null then
        raise exception
            'Repair postcondition failed: missing columns: %',
            missing_objects;
    end if;

    with required_constraints(table_name, constraint_name) as (
        values
            ('documents', 'documents_normalized_content_hash'),
            ('documents', 'documents_normalization_version'),
            ('documents', 'documents_loose_content_signature'),
            ('documents', 'documents_version_number'),
            ('documents', 'documents_effective_range'),
            ('documents', 'documents_quality_status'),
            ('documents', 'documents_quality_metadata'),
            ('documents', 'documents_canonical_not_self'),
            ('documents', 'documents_supersedes_not_self'),
            ('documents', 'documents_canonical_owner_fk'),
            ('documents', 'documents_supersedes_owner_fk'),
            ('ingestion_jobs', 'ingestion_jobs_claim'),
            ('document_relations', 'document_relations_source_owner_fk'),
            ('document_relations', 'document_relations_target_owner_fk'),
            ('document_relations', 'document_relations_preferred_owner_fk'),
            ('knowledge_quality_audit', 'knowledge_quality_audit_notebook_owner_fk')
    )
    select string_agg(
        format('%I.%I', required.table_name, required.constraint_name),
        ', '
    )
    into missing_objects
    from required_constraints as required
    left join pg_catalog.pg_constraint as actual
      on actual.conrelid = to_regclass(
          format('public.%I', required.table_name)
      )
     and actual.conname = required.constraint_name
     and actual.convalidated
    where actual.oid is null;

    if missing_objects is not null then
        raise exception
            'Repair postcondition failed: missing/unvalidated constraints: %',
            missing_objects;
    end if;

    if exists (
        select 1
        from public.ingestion_jobs
        where (
            status = 'running'
            and (
                claimed_by is null
                or lease_expires_at is null
                or claim_token is null
            )
        ) or (
            status <> 'running'
            and (
                claimed_by is not null
                or lease_expires_at is not null
                or claim_token is not null
            )
        )
    ) then
        raise exception
            'Repair postcondition failed: ingestion claim rows are inconsistent';
    end if;

    if to_regclass('public.documents_active_exact_content_key') is null then
        raise exception
            'Repair postcondition failed: exact-byte identity index is missing';
    end if;

    if to_regprocedure(
        'public.claim_ingestion_job(text,integer)'
    ) is null or lower(
        pg_get_function_result(
            to_regprocedure('public.claim_ingestion_job(text,integer)')
        )
    ) not like '%claim_token uuid%' then
        raise exception
            'Repair postcondition failed: claim_ingestion_job is not generation-fenced';
    end if;

    if lower(
        pg_get_functiondef(
            to_regprocedure('public.claim_ingestion_job(text,integer)')
        )
    ) not like '%public.ingestion_control%' then
        raise exception
            'Repair postcondition failed: claim_ingestion_job is not maintenance-fenced';
    end if;

    if to_regprocedure(
        'public.match_document_chunks(vector,uuid[],integer)'
    ) is not null
       or to_regprocedure(
           'public.match_document_chunks(vector,uuid,uuid[],integer)'
       ) is not null then
        raise exception
            'Repair postcondition failed: legacy dense-search overloads remain';
    end if;

    select lower(pg_get_function_result(functions.oid))
    into dense_result
    from pg_catalog.pg_proc as functions
    join pg_catalog.pg_namespace as namespaces
      on namespaces.oid = functions.pronamespace
    where namespaces.nspname = 'public'
      and functions.proname = 'match_document_chunks'
      and pg_get_function_identity_arguments(functions.oid) =
          'p_query_embedding vector, p_owner_id uuid, p_notebook_id uuid, p_document_ids uuid[], p_limit integer';

    if dense_result is null
       or dense_result not like '%normalized_content_hash text%'
       or dense_result not like '%exact_duplicate_group_id uuid%' then
        raise exception
            'Repair postcondition failed: migration-09 dense-search RPC is missing';
    end if;

    if to_regprocedure(
        'public.renew_ingestion_job_lease(uuid,text,uuid,integer)'
    ) is null
       or to_regprocedure(
           'public.complete_ingestion_job(uuid,text,uuid,text,integer,jsonb,text,text,text,jsonb,jsonb)'
       ) is null
       or to_regprocedure(
           'public.complete_duplicate_ingestion_job(uuid,text,uuid,uuid,text,text,text,jsonb)'
       ) is null
       or to_regprocedure(
           'public.fail_ingestion_job(uuid,text,uuid,text)'
       ) is null
       or to_regprocedure(
           'public.soft_delete_document(uuid,uuid)'
       ) is null
       or to_regprocedure(
           'public.resolve_document_relation(uuid,uuid,text,timestamptz,text)'
    ) is null then
        raise exception
            'Repair postcondition failed: one or more required RPCs are missing';
    end if;

    if exists (select 1 from public.document_relations)
       or exists (select 1 from public.knowledge_quality_audit) then
        raise exception
            'Repair postcondition failed: SQL Editor variant expected empty relation/audit tables';
    end if;
end;
$repair$;

notify pgrst, 'reload schema';

commit;

select 'repair09_sql_editor_done' as status;
