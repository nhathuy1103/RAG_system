-- Reproduces the mixed partial migration-09 state audited on 2026-07-31.
-- Run after knowledge_quality_migration_base.sql and
-- partial_knowledge_quality_08_state.sql on disposable PostgreSQL only.

update public.ingestion_jobs
set lease_expires_at = now() - interval '1 minute'
where status = 'running';

create table public.ingestion_control (
    singleton boolean primary key default true,
    maintenance_token uuid,
    maintenance_owner text,
    maintenance_reason text,
    maintenance_expires_at timestamptz,
    updated_at timestamptz not null default now(),
    constraint ingestion_control_singleton
        check (singleton),
    constraint ingestion_control_maintenance_tuple
        check (
            (
                maintenance_token is null
                and maintenance_owner is null
                and maintenance_reason is null
                and maintenance_expires_at is null
            )
            or
            (
                maintenance_token is not null
                and char_length(btrim(maintenance_owner)) between 1 and 200
                and char_length(btrim(maintenance_reason)) between 1 and 2000
                and maintenance_expires_at is not null
            )
        )
);

insert into public.ingestion_control (singleton)
values (true);

create function public.begin_ingestion_maintenance(text, integer, text)
returns uuid
language sql
security definer
set search_path = ''
as $$
    select gen_random_uuid()
$$;

create function public.renew_ingestion_maintenance(uuid, integer)
returns boolean
language sql
security definer
set search_path = ''
as $$
    select true
$$;

create function public.end_ingestion_maintenance(uuid)
returns boolean
language sql
security definer
set search_path = ''
as $$
    select true
$$;

drop function public.match_document_chunks(
    vector, uuid, uuid, uuid[], integer
);

create function public.match_document_chunks(
    p_query_embedding vector(1536),
    p_owner_id uuid,
    p_notebook_id uuid default null,
    p_document_ids uuid[] default null,
    p_limit integer default 20
)
returns table (
    chunk_id uuid,
    document_id uuid,
    document_version integer,
    chunk_index integer,
    content text,
    metadata jsonb,
    normalized_content_hash text,
    exact_duplicate_group_id uuid,
    score double precision
)
language plpgsql
stable
security definer
set search_path = ''
as $$
begin
    return;
end;
$$;

create function public.match_document_chunks(
    p_query_embedding vector(1536),
    p_document_ids uuid[] default null,
    p_limit integer default 20
)
returns table (
    chunk_id uuid,
    document_id uuid,
    document_version integer,
    chunk_index integer,
    content text,
    metadata jsonb,
    score double precision
)
language sql
stable
security definer
set search_path = ''
as $$
    select
        null::uuid,
        null::uuid,
        1,
        0,
        ''::text,
        '{}'::jsonb,
        0::double precision
    where false
$$;

drop function public.claim_ingestion_job(text, integer);

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
    content_hash text
)
language sql
security definer
set search_path = ''
as $$
    select
        jobs.id,
        jobs.owner_id,
        jobs.notebook_id,
        jobs.document_id,
        jobs.attempt_number,
        jobs.configuration,
        documents.storage_bucket,
        documents.storage_object_path,
        documents.original_filename,
        documents.mime_type,
        documents.size_bytes,
        documents.content_hash
    from public.ingestion_jobs as jobs
    join public.documents
      on documents.id = jobs.document_id
     and documents.notebook_id = jobs.notebook_id
     and documents.owner_id = jobs.owner_id
    where false
$$;

drop function public.complete_ingestion_job(
    uuid, text, uuid, text, integer, jsonb, text, text, text, jsonb, jsonb
);

create function public.complete_ingestion_job(
    p_job_id uuid,
    p_worker_id text,
    p_claim_token uuid,
    p_embedding_model text,
    p_embedding_dimensions integer,
    p_chunks jsonb,
    p_normalized_content_hash text,
    p_normalization_version text,
    p_loose_content_signature text,
    p_quality_metadata jsonb,
    p_relations jsonb
)
returns text
language plpgsql
security definer
set search_path = ''
as $$
begin
    return 'completed';
end;
$$;

drop function public.complete_duplicate_ingestion_job(
    uuid, text, uuid, uuid, text, text, text, jsonb
);

create function public.complete_duplicate_ingestion_job(
    uuid, text, uuid, uuid, text, text, text, jsonb
)
returns void
language plpgsql
security definer
set search_path = ''
as $$
begin
    return;
end;
$$;

alter table public.knowledge_quality_audit
    add column reverts_audit_id bigint;

create function public.revert_document_relation_resolution(
    uuid, uuid, timestamptz, text
)
returns setof public.document_relations
language sql
security definer
set search_path = ''
as $$
    select * from public.document_relations where false
$$;

create function public.guard_authenticated_document_write()
returns trigger
language plpgsql
set search_path = ''
as $$
begin
    return new;
end;
$$;

create type public.ingestion_repair_issue_kind
as enum ('missing_vector', 'mismatch', 'missing_embedding');

create function public.knowledge_exact_chunk_group_id(uuid, uuid, text, text)
returns uuid
language sql
immutable
set search_path = ''
as $$
    select '00000000-0000-0000-0000-000000000000'::uuid
$$;
