-- Security, idempotency, identity, lineage, and audit hardening.
-- Run after 08_knowledge_quality.sql.

-- Supabase installs pgcrypto in the `extensions` schema, while a plain
-- PostgreSQL database commonly installs it in `public`. Resolve the actual
-- extension schema once and expose a private, stable wrapper so functions with
-- an empty search_path do not depend on either installation layout.
do $migration$
declare
    pgcrypto_schema name;
begin
    select namespaces.nspname
    into pgcrypto_schema
    from pg_catalog.pg_extension as installed_extensions
    join pg_catalog.pg_namespace as namespaces
      on namespaces.oid = installed_extensions.extnamespace
    where installed_extensions.extname = 'pgcrypto';

    if not found then
        raise exception 'The pgcrypto extension is required before migration 09'
            using errcode = '55000';
    end if;

    execute pg_catalog.format(
        $ddl$
        create or replace function public.knowledge_digest(
            p_data bytea,
            p_algorithm text
        )
        returns bytea
        language sql
        immutable
        strict
        parallel safe
        set search_path = ''
        as $function$
            select %I.digest(p_data, p_algorithm)
        $function$
        $ddl$,
        pgcrypto_schema
    );
end;
$migration$;

revoke all on function public.knowledge_digest(bytea, text)
from public, anon, authenticated;

-- ---------------------------------------------------------------------------
-- Tenant-safe dense retrieval for projects that already applied old
-- unscoped/partially scoped functions from 06_pgvector_search.sql.
-- ---------------------------------------------------------------------------

drop function if exists public.match_document_chunks(
    vector, uuid[], integer
);
drop function if exists public.match_document_chunks(
    vector, uuid, uuid[], integer
);
drop function if exists public.match_document_chunks(
    vector, uuid, uuid, uuid[], integer
);

create or replace function public.match_document_chunks(
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
    if auth.role() <> 'service_role'
       and auth.uid() is distinct from p_owner_id then
        raise exception 'Cannot retrieve another owner''s document chunks'
            using errcode = '42501';
    end if;

    return query
    select
        chunks.id as chunk_id,
        chunks.document_id,
        coalesce(
            (chunks.metadata ->> 'document_version')::integer,
            1
        ) as document_version,
        chunks.chunk_index,
        chunks.content,
        chunks.metadata,
        chunks.normalized_content_hash,
        chunks.exact_duplicate_group_id,
        1 - (
            chunks.embedding OPERATOR(public.<=>) p_query_embedding
        ) as score
    from public.document_chunks as chunks
    where chunks.owner_id = p_owner_id
      and (
          p_notebook_id is null
          or chunks.notebook_id = p_notebook_id
      )
      and chunks.embedding is not null
      and (
          p_document_ids is null
          or chunks.document_id = any(p_document_ids)
      )
    order by chunks.embedding OPERATOR(public.<=>) p_query_embedding
    limit greatest(1, least(coalesce(p_limit, 20), 200));
end;
$$;

revoke all on function public.match_document_chunks(
    vector, uuid, uuid, uuid[], integer
) from public, anon;
grant execute on function public.match_document_chunks(
    vector, uuid, uuid, uuid[], integer
) to authenticated, service_role;

-- ---------------------------------------------------------------------------
-- Database-backed maintenance lease.
--
-- Every claimant takes a shared lock on the singleton row before it selects a
-- job. Maintenance takes an exclusive lock before it verifies that no job is
-- running and publishes its lease. That lock ordering closes the worker/
-- reconciliation TOCTOU window without relying on process-local quiescence.
-- ---------------------------------------------------------------------------

create table if not exists public.ingestion_control (
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
                and char_length(btrim(maintenance_owner))
                    between 1 and 200
                and char_length(btrim(maintenance_reason))
                    between 1 and 2000
                and maintenance_expires_at is not null
            )
        )
);

insert into public.ingestion_control (singleton)
values (true)
on conflict (singleton) do nothing;

comment on table public.ingestion_control is
    'Singleton database lease that fences workers during reconciliation maintenance.';

revoke all privileges on table public.ingestion_control
from public, anon, authenticated, service_role;

create or replace function public.begin_ingestion_maintenance(
    p_maintenance_owner text,
    p_lease_seconds integer,
    p_reason text
)
returns uuid
language plpgsql
security definer
set search_path = ''
as $$
declare
    control_row public.ingestion_control;
    lease_token uuid;
begin
    if auth.role() <> 'service_role' then
        raise exception 'Service role is required'
            using errcode = '42501';
    end if;
    if p_maintenance_owner is null
       or char_length(btrim(p_maintenance_owner)) not between 1 and 200
       or p_reason is null
       or char_length(btrim(p_reason)) not between 1 and 2000
       or p_lease_seconds is null
       or p_lease_seconds not between 30 and 3600 then
        raise exception 'Invalid ingestion maintenance lease'
            using errcode = '22023';
    end if;

    select controls.*
    into control_row
    from public.ingestion_control as controls
    where controls.singleton
    for update;

    if not found then
        raise exception 'Ingestion control row is unavailable'
            using errcode = 'P0002';
    end if;
    if control_row.maintenance_token is not null
       and control_row.maintenance_expires_at > now() then
        raise exception 'Ingestion maintenance is already active'
            using errcode = '55P03';
    end if;

    -- A claimant must lock this row before changing a job to running. Holding
    -- it exclusively makes this zero-running check and lease publication one
    -- serializable critical section.
    if exists (
        select 1
        from public.ingestion_jobs
        where ingestion_jobs.status = 'running'
    ) then
        raise exception 'Ingestion workers have not drained'
            using errcode = '55P03';
    end if;

    lease_token := gen_random_uuid();
    update public.ingestion_control
    set
        maintenance_token = lease_token,
        maintenance_owner = btrim(p_maintenance_owner),
        maintenance_reason = btrim(p_reason),
        maintenance_expires_at =
            now() + make_interval(secs => p_lease_seconds),
        updated_at = now()
    where ingestion_control.singleton;

    return lease_token;
end;
$$;

create or replace function public.renew_ingestion_maintenance(
    p_maintenance_token uuid,
    p_lease_seconds integer
)
returns boolean
language plpgsql
security definer
set search_path = ''
as $$
declare
    renewed_count integer;
begin
    if auth.role() <> 'service_role' then
        raise exception 'Service role is required'
            using errcode = '42501';
    end if;
    if p_maintenance_token is null
       or p_lease_seconds is null
       or p_lease_seconds not between 30 and 3600 then
        raise exception 'Invalid ingestion maintenance renewal'
            using errcode = '22023';
    end if;

    update public.ingestion_control
    set
        maintenance_expires_at =
            now() + make_interval(secs => p_lease_seconds),
        updated_at = now()
    where ingestion_control.singleton
      and ingestion_control.maintenance_token =
          p_maintenance_token
      and ingestion_control.maintenance_expires_at > now();

    get diagnostics renewed_count = row_count;
    return renewed_count = 1;
end;
$$;

create or replace function public.end_ingestion_maintenance(
    p_maintenance_token uuid
)
returns boolean
language plpgsql
security definer
set search_path = ''
as $$
declare
    released_count integer;
begin
    if auth.role() <> 'service_role' then
        raise exception 'Service role is required'
            using errcode = '42501';
    end if;
    if p_maintenance_token is null then
        raise exception 'Invalid ingestion maintenance token'
            using errcode = '22023';
    end if;

    update public.ingestion_control
    set
        maintenance_token = null,
        maintenance_owner = null,
        maintenance_reason = null,
        maintenance_expires_at = null,
        updated_at = now()
    where ingestion_control.singleton
      and ingestion_control.maintenance_token =
          p_maintenance_token;

    get diagnostics released_count = row_count;
    return released_count = 1;
end;
$$;

revoke all on function public.begin_ingestion_maintenance(
    text, integer, text
) from public, anon, authenticated;
revoke all on function public.renew_ingestion_maintenance(
    uuid, integer
) from public, anon, authenticated;
revoke all on function public.end_ingestion_maintenance(
    uuid
) from public, anon, authenticated;
grant execute on function public.begin_ingestion_maintenance(
    text, integer, text
) to service_role;
grant execute on function public.renew_ingestion_maintenance(
    uuid, integer
) to service_role;
grant execute on function public.end_ingestion_maintenance(
    uuid
) to service_role;

create or replace function public.claim_ingestion_job(
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
            lease_expires_at =
                now() + make_interval(secs => p_lease_seconds),
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

alter table public.ingestion_jobs
    add column if not exists completion_disposition text;

do $migration$
begin
    if not exists (
        select 1
        from pg_catalog.pg_constraint
        where pg_constraint.conrelid =
            'public.ingestion_jobs'::regclass
          and pg_constraint.conname =
            'ingestion_jobs_completion_disposition'
    ) then
        alter table public.ingestion_jobs
            add constraint ingestion_jobs_completion_disposition
            check (
                completion_disposition is null
                or completion_disposition in (
                    'completed',
                    'duplicate_suppressed'
                )
            );
    end if;
end;
$migration$;

-- ---------------------------------------------------------------------------
-- Commit-response-loss-safe enqueueing.
-- ---------------------------------------------------------------------------

create or replace function public.enqueue_document_ingestion(
    p_document_id uuid,
    p_notebook_id uuid,
    p_embedding_model text,
    p_embedding_dimensions integer,
    p_configuration jsonb default '{}'::jsonb
)
returns setof public.documents
language plpgsql
security definer
set search_path = ''
as $$
declare
    selected_document public.documents;
    selected_job public.ingestion_jobs;
    next_attempt integer;
begin
    if auth.uid() is null then
        raise exception 'Authentication is required'
            using errcode = '42501';
    end if;
    if p_embedding_model is null
       or char_length(btrim(p_embedding_model)) not between 1 and 200 then
        raise exception 'Invalid embedding model'
            using errcode = '22023';
    end if;
    if p_embedding_dimensions is null
       or p_embedding_dimensions <= 0 then
        raise exception 'Invalid embedding dimensions'
            using errcode = '22023';
    end if;
    if p_configuration is null
       or jsonb_typeof(p_configuration) <> 'object' then
        raise exception 'Ingestion configuration must be an object'
            using errcode = '22023';
    end if;
    if coalesce(
        nullif(
            btrim(p_configuration ->> 'knowledge_quality_mode'),
            ''
        ),
        'off'
    ) not in ('off', 'shadow', 'on') then
        raise exception 'Invalid knowledge-quality mode'
            using errcode = '22023';
    end if;

    select documents.*
    into selected_document
    from public.documents
    where documents.id = p_document_id
      and documents.notebook_id = p_notebook_id
      and documents.owner_id = auth.uid()
      and documents.is_active
    for update;

    if not found then
        raise exception 'Uploaded document is not available for ingestion'
            using errcode = 'P0002';
    end if;

    select jobs.*
    into selected_job
    from public.ingestion_jobs as jobs
    where jobs.document_id = selected_document.id
      and jobs.notebook_id = selected_document.notebook_id
      and jobs.owner_id = selected_document.owner_id
      and jobs.status in ('pending', 'running', 'succeeded')
    order by
        case
            when jobs.status in ('pending', 'running') then 0
            else 1
        end,
        jobs.attempt_number desc,
        jobs.id
    limit 1
    for update;

    if selected_job.id is not null then
        if selected_job.embedding_model <> btrim(p_embedding_model)
           or selected_job.embedding_dimensions <> p_embedding_dimensions
           or selected_job.configuration <> p_configuration then
            raise exception 'Ingestion profile does not match the existing job'
                using errcode = '22023';
        end if;

        if selected_document.status not in (
            'uploading',
            'processing',
            'ready'
        ) then
            raise exception 'Document state cannot reuse the existing ingestion job'
                using errcode = 'P0002';
        end if;

        if selected_document.status = 'uploading' then
            if selected_job.status not in ('pending', 'running') then
                raise exception 'Succeeded ingestion has an inconsistent document state'
                    using errcode = '40001';
            end if;

            update public.documents
            set
                status = 'processing',
                error_message = null,
                updated_at = now()
            where documents.id = selected_document.id
              and documents.notebook_id = selected_document.notebook_id
              and documents.owner_id = selected_document.owner_id
            returning documents.* into selected_document;
        end if;

        return next selected_document;
        return;
    end if;

    if selected_document.status <> 'uploading' then
        raise exception 'Document has no reusable ingestion job'
            using errcode = 'P0002';
    end if;

    select coalesce(max(jobs.attempt_number), 0) + 1
    into next_attempt
    from public.ingestion_jobs as jobs
    where jobs.document_id = selected_document.id;

    insert into public.ingestion_jobs (
        owner_id,
        notebook_id,
        document_id,
        attempt_number,
        status,
        embedding_model,
        embedding_dimensions,
        configuration
    )
    values (
        selected_document.owner_id,
        selected_document.notebook_id,
        selected_document.id,
        next_attempt,
        'pending',
        btrim(p_embedding_model),
        p_embedding_dimensions,
        p_configuration
    );

    update public.documents
    set
        status = 'processing',
        error_message = null,
        updated_at = now()
    where documents.id = selected_document.id
      and documents.notebook_id = selected_document.notebook_id
      and documents.owner_id = selected_document.owner_id
    returning documents.* into selected_document;

    return next selected_document;
end;
$$;

revoke all on function public.enqueue_document_ingestion(
    uuid, uuid, text, integer, jsonb
) from public, anon;
grant execute on function public.enqueue_document_ingestion(
    uuid, uuid, text, integer, jsonb
) to authenticated;

-- ---------------------------------------------------------------------------
-- Direct-write boundary.
-- Authenticated clients create only an uploading shell, may mark that shell
-- failed, and archive through soft_delete_document. Ingestion/review fields
-- remain writable only through SECURITY DEFINER RPCs with their own checks.
-- ---------------------------------------------------------------------------

revoke insert, update, delete
on table public.document_chunks
from authenticated;

revoke insert, update, delete
on table public.documents
from authenticated;

grant insert (
    id,
    owner_id,
    notebook_id,
    original_filename,
    storage_bucket,
    storage_object_path,
    mime_type,
    size_bytes,
    content_hash,
    status,
    error_message
)
on table public.documents
to authenticated;

grant update (status, error_message)
on table public.documents
to authenticated;

create or replace function public.guard_authenticated_document_write()
returns trigger
language plpgsql
set search_path = ''
as $$
begin
    -- SECURITY DEFINER ingestion/review RPCs and service-role maintenance do
    -- not run as the authenticated table role and retain their guarded paths.
    if current_user <> 'authenticated' then
        return new;
    end if;

    if tg_op = 'INSERT' then
        if auth.uid() is null
           or new.owner_id is distinct from auth.uid()
           or new.storage_bucket <> 'documents'
           or pg_catalog.array_length(
                pg_catalog.string_to_array(
                    new.storage_object_path,
                    '/'
                ),
                1
            ) <> 4
           or pg_catalog.split_part(
                new.storage_object_path,
                '/',
                1
            ) <> new.owner_id::text
           or pg_catalog.split_part(
                new.storage_object_path,
                '/',
                2
            ) <> new.notebook_id::text
           or pg_catalog.split_part(
                new.storage_object_path,
                '/',
                3
            ) <> new.id::text
           or pg_catalog.split_part(
                new.storage_object_path,
                '/',
                4
            ) = ''
           or pg_catalog.strpos(
                pg_catalog.split_part(
                    new.storage_object_path,
                    '/',
                    4
                ),
                '..'
            ) > 0
           or new.status <> 'uploading'
           or new.error_message is not null
           or not new.is_active
           or new.normalized_content_hash is not null
           or new.normalization_version is not null
           or new.loose_content_signature is not null
           or new.canonical_document_id is not null
           or new.version_number <> 1
           or not new.is_current
           or new.quality_status <> 'unreviewed'
           or new.quality_metadata <> '{}'::jsonb then
            raise exception 'Authenticated clients may only create uploading documents'
                using errcode = '42501';
        end if;
        return new;
    end if;

    if new.status is distinct from old.status
       and not (
           old.status = 'uploading'
           and new.status = 'failed'
       ) then
        raise exception 'Document status transition requires a guarded RPC'
            using errcode = '42501';
    end if;

    if new.error_message is distinct from old.error_message
       and new.status <> 'failed' then
        raise exception 'Only failed uploads may set an error message'
            using errcode = '42501';
    end if;

    if new.status = 'failed'
       and (
           new.error_message is null
           or char_length(btrim(new.error_message)) not between 1 and 4000
       ) then
        raise exception 'A failed upload requires a bounded error message'
            using errcode = '22023';
    end if;

    return new;
end;
$$;

drop trigger if exists documents_authenticated_write_guard
on public.documents;
create trigger documents_authenticated_write_guard
before insert or update on public.documents
for each row execute function public.guard_authenticated_document_write();

revoke all on function public.guard_authenticated_document_write()
from public, anon, authenticated;

-- ---------------------------------------------------------------------------
-- Persisted strict/loose chunk identities. Strict identity is authoritative;
-- the loose signature is candidate-only. Group ids include the tenant scope.
-- ---------------------------------------------------------------------------

alter table public.document_chunks
    add column if not exists normalized_content_hash text,
    add column if not exists normalization_version text,
    add column if not exists loose_content_signature text,
    add column if not exists exact_duplicate_group_id uuid;

create or replace function public.knowledge_exact_chunk_group_id(
    p_owner_id uuid,
    p_notebook_id uuid,
    p_normalization_version text,
    p_normalized_content_hash text
)
returns uuid
language sql
immutable
strict
parallel safe
set search_path = ''
as $$
    with group_name as (
        select
            'rag-chunk-exact-group:'
            || p_owner_id::text
            || ':' || p_notebook_id::text
            || ':' || p_normalization_version
            || ':' || p_normalized_content_hash as value
    ),
    sha1_hash as (
        select substring(
            public.knowledge_digest(
                pg_catalog.uuid_send(
                    '6ba7b811-9dad-11d1-80b4-00c04fd430c8'::uuid
                )
                || pg_catalog.convert_to(group_name.value, 'UTF8'),
                'sha1'
            )
            from 1 for 16
        ) as value
        from group_name
    ),
    versioned_hash as (
        select pg_catalog.set_byte(
            pg_catalog.set_byte(
                sha1_hash.value,
                6,
                (
                    pg_catalog.get_byte(sha1_hash.value, 6)
                    & 15
                ) | 80
            ),
            8,
            (
                pg_catalog.get_byte(sha1_hash.value, 8)
                & 63
            ) | 128
        ) as value
        from sha1_hash
    ),
    group_hash as (
        select pg_catalog.encode(versioned_hash.value, 'hex') as value
        from versioned_hash
    )
    select (
        pg_catalog.substr(group_hash.value, 1, 8)
        || '-' || pg_catalog.substr(group_hash.value, 9, 4)
        || '-' || pg_catalog.substr(group_hash.value, 13, 4)
        || '-' || pg_catalog.substr(group_hash.value, 17, 4)
        || '-' || pg_catalog.substr(group_hash.value, 21, 12)
    )::uuid
    from group_hash
$$;

revoke all on function public.knowledge_exact_chunk_group_id(
    uuid, uuid, text, text
) from public, anon, authenticated;

with computed_fingerprints as (
    select
        chunks.id,
        case
            when chunks.metadata ->> 'normalized_content_hash'
                    ~ '^[0-9a-f]{64}$'
             and chunks.metadata ->> 'normalization_version' is not null
             and char_length(
                    btrim(chunks.metadata ->> 'normalization_version')
                 ) between 1 and 100
             and chunks.metadata ->> 'loose_content_signature'
                    ~ '^[0-9a-f]{16}$'
            then chunks.metadata ->> 'normalized_content_hash'
            else encode(
                public.knowledge_digest(
                    pg_catalog.convert_to(
                        regexp_replace(
                            btrim(chunks.content),
                            '[[:space:]]+',
                            ' ',
                            'g'
                        ),
                        'UTF8'
                    ),
                    'sha256'
                ),
                'hex'
            )
        end as strict_hash,
        case
            when chunks.metadata ->> 'normalized_content_hash'
                    ~ '^[0-9a-f]{64}$'
             and chunks.metadata ->> 'normalization_version' is not null
             and char_length(
                    btrim(chunks.metadata ->> 'normalization_version')
                 ) between 1 and 100
             and chunks.metadata ->> 'loose_content_signature'
                    ~ '^[0-9a-f]{16}$'
            then btrim(chunks.metadata ->> 'normalization_version')
            else 'knowledge-chunk-db-v1'
        end as fingerprint_version,
        case
            when chunks.metadata ->> 'normalized_content_hash'
                    ~ '^[0-9a-f]{64}$'
             and chunks.metadata ->> 'normalization_version' is not null
             and char_length(
                    btrim(chunks.metadata ->> 'normalization_version')
                 ) between 1 and 100
             and chunks.metadata ->> 'loose_content_signature'
                    ~ '^[0-9a-f]{16}$'
            then chunks.metadata ->> 'loose_content_signature'
            else substr(
                encode(
                    public.knowledge_digest(
                        pg_catalog.convert_to(
                            lower(
                                regexp_replace(
                                    btrim(chunks.content),
                                    '[[:space:]]+',
                                    ' ',
                                    'g'
                                )
                            ),
                            'UTF8'
                        ),
                        'sha256'
                    ),
                    'hex'
                ),
                1,
                16
            )
        end as loose_signature
    from public.document_chunks as chunks
)
update public.document_chunks as chunks
set
    normalized_content_hash = fingerprints.strict_hash,
    normalization_version = fingerprints.fingerprint_version,
    loose_content_signature = fingerprints.loose_signature,
    exact_duplicate_group_id =
        public.knowledge_exact_chunk_group_id(
            chunks.owner_id,
            chunks.notebook_id,
            fingerprints.fingerprint_version,
            fingerprints.strict_hash
        )
from computed_fingerprints as fingerprints
where fingerprints.id = chunks.id;

alter table public.document_chunks
    alter column normalized_content_hash set not null,
    alter column normalization_version set not null,
    alter column loose_content_signature set not null,
    alter column exact_duplicate_group_id set not null;

do $migration$
begin
    if not exists (
        select 1
        from pg_catalog.pg_constraint
        where pg_constraint.conrelid =
            'public.document_chunks'::regclass
          and pg_constraint.conname =
            'document_chunks_normalized_content_hash_format'
    ) then
        alter table public.document_chunks
            add constraint document_chunks_normalized_content_hash_format
            check (normalized_content_hash ~ '^[0-9a-f]{64}$');
    end if;
    if not exists (
        select 1
        from pg_catalog.pg_constraint
        where pg_constraint.conrelid =
            'public.document_chunks'::regclass
          and pg_constraint.conname =
            'document_chunks_normalization_version_format'
    ) then
        alter table public.document_chunks
            add constraint document_chunks_normalization_version_format
            check (
                char_length(btrim(normalization_version))
                between 1 and 100
            );
    end if;
    if not exists (
        select 1
        from pg_catalog.pg_constraint
        where pg_constraint.conrelid =
            'public.document_chunks'::regclass
          and pg_constraint.conname =
            'document_chunks_loose_content_signature_format'
    ) then
        alter table public.document_chunks
            add constraint document_chunks_loose_content_signature_format
            check (loose_content_signature ~ '^[0-9a-f]{16}$');
    end if;
    if not exists (
        select 1
        from pg_catalog.pg_constraint
        where pg_constraint.conrelid =
            'public.document_chunks'::regclass
          and pg_constraint.conname =
            'document_chunks_exact_group_consistency'
    ) then
        alter table public.document_chunks
            add constraint document_chunks_exact_group_consistency
            check (
                exact_duplicate_group_id =
                    public.knowledge_exact_chunk_group_id(
                        owner_id,
                        notebook_id,
                        normalization_version,
                        normalized_content_hash
                    )
            );
    end if;
end;
$migration$;

create index if not exists document_chunks_exact_identity_idx
    on public.document_chunks (
        owner_id,
        notebook_id,
        normalization_version,
        normalized_content_hash
    );

create index if not exists document_chunks_exact_group_idx
    on public.document_chunks (
        owner_id,
        notebook_id,
        exact_duplicate_group_id
    );

create index if not exists document_chunks_loose_candidate_idx
    on public.document_chunks (
        owner_id,
        notebook_id,
        normalization_version,
        loose_content_signature
    );

-- ---------------------------------------------------------------------------
-- Canonical normalized-content identity and family invariants.
-- Empty/tiny extraction output remains ineligible for automatic identity.
-- ---------------------------------------------------------------------------

with ranked_identity as (
    select
        documents.id,
        documents.owner_id,
        documents.notebook_id,
        documents.normalized_content_hash,
        documents.normalization_version,
        first_value(documents.id) over identity_group as canonical_id,
        row_number() over identity_group as duplicate_rank
    from public.documents
    where documents.normalized_content_hash is not null
      and documents.normalization_version is not null
      and documents.is_active
      and documents.status = 'ready'
      and documents.canonical_document_id is null
      and case
          when documents.quality_metadata ->> 'character_count'
               ~ '^[0-9]+$'
          then (
              documents.quality_metadata ->> 'character_count'
          )::integer >= 40
          else false
      end
      and case
          when documents.quality_metadata ->> 'token_count'
               ~ '^[0-9]+$'
          then (
              documents.quality_metadata ->> 'token_count'
          )::integer >= 6
          else false
      end
    window identity_group as (
        partition by
            documents.owner_id,
            documents.notebook_id,
            documents.normalization_version,
            documents.normalized_content_hash
        order by documents.created_at, documents.id
    )
)
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
    ranked_identity.owner_id,
    ranked_identity.notebook_id,
    ranked_identity.id,
    ranked_identity.canonical_id,
    'exact_content',
    'pending',
    1,
    jsonb_build_object(
        'normalized_content_hash',
        ranked_identity.normalized_content_hash,
        'normalization_version',
        ranked_identity.normalization_version,
        'migration_backfill',
        true,
        'quality_mode',
        'shadow'
    ),
    'Backfilled as review-only; no document was suppressed',
    'knowledge-quality-hardening-shadow-v1'
from ranked_identity
where ranked_identity.duplicate_rank > 1
on conflict (source_document_id, target_document_id, detector_version)
do nothing;

create unique index if not exists documents_active_normalized_identity_key
    on public.documents (
        owner_id,
        notebook_id,
        normalization_version,
        normalized_content_hash
    )
    where (
        normalized_content_hash is not null
        and normalization_version is not null
        and is_active
        and status = 'ready'
        and canonical_document_id is null
        and quality_metadata ->> 'knowledge_quality_mode' = 'on'
        and case
            when quality_metadata ->> 'character_count' ~ '^[0-9]+$'
            then (
                quality_metadata ->> 'character_count'
            )::integer >= 40
            else false
        end
        and case
            when quality_metadata ->> 'token_count' ~ '^[0-9]+$'
            then (
                quality_metadata ->> 'token_count'
            )::integer >= 6
            else false
        end
    );

do $$
begin
    if exists (
        select 1
        from public.documents
        where documents.canonical_document_id is null
        group by
            documents.owner_id,
            documents.notebook_id,
            documents.version_group_id,
            documents.version_number
        having count(*) > 1
    ) then
        raise exception
            'Cannot enforce canonical family versions: duplicate version numbers exist'
            using errcode = '23505';
    end if;

    if exists (
        select 1
        from public.documents
        where documents.canonical_document_id is null
          and documents.is_current
        group by
            documents.owner_id,
            documents.notebook_id,
            documents.version_group_id
        having count(*) > 1
    ) then
        raise exception
            'Cannot enforce one current canonical document: conflicts exist'
            using errcode = '23505';
    end if;
end;
$$;

create unique index if not exists documents_canonical_family_version_key
    on public.documents (
        owner_id,
        notebook_id,
        version_group_id,
        version_number
    )
    where canonical_document_id is null;

create unique index if not exists documents_one_current_canonical_per_family
    on public.documents (
        owner_id,
        notebook_id,
        version_group_id
    )
    where canonical_document_id is null and is_current;

-- Auto-aliasing is a destructive/suppressing decision and is therefore
-- permitted only for jobs durably enqueued in "on" mode.
create or replace function public.complete_duplicate_ingestion_job(
    p_job_id uuid,
    p_worker_id text,
    p_claim_token uuid,
    p_canonical_document_id uuid,
    p_normalized_content_hash text,
    p_normalization_version text,
    p_loose_content_signature text,
    p_quality_metadata jsonb
)
returns void
language plpgsql
security definer
set search_path = ''
as $$
declare
    selected_job public.ingestion_jobs;
    selected_canonical public.documents;
    selected_source public.documents;
    canonical_id uuid;
    created_relation public.document_relations;
    enqueued_quality_mode text;
    knowledge_quality_mode text;
    logical_source_before jsonb;
    before_relation jsonb;
    before_documents jsonb;
    after_documents jsonb;
begin
    if auth.role() <> 'service_role' then
        raise exception 'Service role is required'
            using errcode = '42501';
    end if;
    if p_normalized_content_hash is null
       or p_normalized_content_hash !~ '^[0-9a-f]{64}$'
       or p_normalization_version is null
       or char_length(btrim(p_normalization_version))
            not between 1 and 100
       or p_loose_content_signature is null
       or p_loose_content_signature !~ '^[0-9a-f]{16}$'
       or p_quality_metadata is null
       or jsonb_typeof(p_quality_metadata) <> 'object'
       or p_quality_metadata ->> 'character_count' is null
       or p_quality_metadata ->> 'character_count' !~ '^[0-9]+$'
       or (p_quality_metadata ->> 'character_count')::integer < 40
       or p_quality_metadata ->> 'token_count' is null
       or p_quality_metadata ->> 'token_count' !~ '^[0-9]+$'
       or (p_quality_metadata ->> 'token_count')::integer < 6 then
        raise exception 'Invalid or ineligible document fingerprint'
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
        raise exception 'Ingestion lease is no longer owned by this worker'
            using errcode = 'P0002';
    end if;
    if selected_job.repair_request_key is not null
       or selected_job.configuration
            ->> 'ingestion_kind' = 'reconciliation_repair' then
        raise exception
            'Repair attempts cannot use duplicate completion'
            using errcode = '42501';
    end if;

    enqueued_quality_mode := coalesce(
        nullif(
            btrim(
                selected_job.configuration
                    ->> 'knowledge_quality_mode'
            ),
            ''
        ),
        'off'
    );
    knowledge_quality_mode := coalesce(
        nullif(
            btrim(
                p_quality_metadata
                    ->> 'knowledge_quality_mode'
            ),
            ''
        ),
        'off'
    );
    if enqueued_quality_mode <> 'on'
       or knowledge_quality_mode <> 'on' then
        raise exception 'Automatic duplicate completion requires on mode'
            using errcode = '42501';
    end if;

    perform pg_catalog.pg_advisory_xact_lock(
        pg_catalog.hashtextextended(
            selected_job.owner_id::text
                || ':' || selected_job.notebook_id::text
                || ':' || btrim(p_normalization_version)
                || ':' || p_normalized_content_hash,
            0
        )
    );

    select documents.*
    into selected_canonical
    from public.documents
    where documents.id = p_canonical_document_id
      and documents.notebook_id = selected_job.notebook_id
      and documents.owner_id = selected_job.owner_id
      and documents.id <> selected_job.document_id
      and documents.is_active
      and documents.status = 'ready'
      and documents.normalized_content_hash =
          p_normalized_content_hash
      and documents.normalization_version =
          btrim(p_normalization_version)
      and case
          when documents.quality_metadata ->> 'character_count'
               ~ '^[0-9]+$'
          then (
              documents.quality_metadata ->> 'character_count'
          )::integer >= 40
          else false
      end
      and case
          when documents.quality_metadata ->> 'token_count'
               ~ '^[0-9]+$'
          then (
              documents.quality_metadata ->> 'token_count'
          )::integer >= 6
          else false
      end
    for update;

    if not found then
        raise exception 'Canonical document is unavailable or not identical'
            using errcode = 'P0002';
    end if;

    canonical_id := coalesce(
        selected_canonical.canonical_document_id,
        selected_canonical.id
    );

    if canonical_id <> selected_canonical.id then
        select documents.*
        into selected_canonical
        from public.documents
        where documents.id = canonical_id
          and documents.notebook_id = selected_job.notebook_id
          and documents.owner_id = selected_job.owner_id
          and documents.is_active
          and documents.status = 'ready'
          and documents.canonical_document_id is null
          and documents.normalized_content_hash =
              p_normalized_content_hash
          and documents.normalization_version =
              btrim(p_normalization_version)
          and case
              when documents.quality_metadata ->> 'character_count'
                   ~ '^[0-9]+$'
              then (
                  documents.quality_metadata ->> 'character_count'
              )::integer >= 40
              else false
          end
          and case
              when documents.quality_metadata ->> 'token_count'
                   ~ '^[0-9]+$'
              then (
                  documents.quality_metadata ->> 'token_count'
              )::integer >= 6
              else false
          end
        for update;

        if not found then
            raise exception 'Canonical document root is unavailable or not identical'
                using errcode = 'P0002';
        end if;
    end if;

    select documents.*
    into selected_source
    from public.documents
    where documents.id = selected_job.document_id
      and documents.notebook_id = selected_job.notebook_id
      and documents.owner_id = selected_job.owner_id
      and documents.is_active
      and documents.status = 'processing'
    for update;

    if not found then
        raise exception 'Duplicate source document is unavailable'
            using errcode = 'P0002';
    end if;

    -- This logical pre-resolution state is what a compensating revert restores.
    -- The worker may detect an exact duplicate before it has emitted chunks, so
    -- a later reconciliation can requeue this ready canonical row if needed.
    logical_source_before := to_jsonb(selected_source)
        || jsonb_build_object(
            'status',
            'ready',
            'error_message',
            null,
            'normalized_content_hash',
            p_normalized_content_hash,
            'normalization_version',
            btrim(p_normalization_version),
            'loose_content_signature',
            p_loose_content_signature,
            'canonical_document_id',
            null,
            'is_current',
            true,
            'quality_status',
            'review_required',
            'quality_metadata',
            selected_source.quality_metadata
                || p_quality_metadata
                || jsonb_build_object(
                    'knowledge_quality_mode',
                    'shadow',
                    'automatic_duplicate_reverted',
                    true
                )
        );

    select coalesce(
        jsonb_agg(snapshot.value order by snapshot.document_id),
        '[]'::jsonb
    )
    into before_documents
    from (
        select
            documents.id as document_id,
            case
                when documents.id = selected_source.id
                then logical_source_before
                else to_jsonb(documents)
            end as value
        from public.documents
        where documents.id in (
            selected_source.id,
            selected_canonical.id
        )
          and documents.notebook_id = selected_job.notebook_id
          and documents.owner_id = selected_job.owner_id
    ) as snapshot;

    select to_jsonb(relations)
    into before_relation
    from public.document_relations as relations
    where relations.source_document_id = selected_source.id
      and relations.target_document_id = selected_canonical.id
      and relations.detector_version = 'knowledge-quality-v2'
    for update;

    update public.documents
    set
        status = 'ready',
        error_message = null,
        normalized_content_hash = p_normalized_content_hash,
        normalization_version = btrim(p_normalization_version),
        loose_content_signature = p_loose_content_signature,
        canonical_document_id = selected_canonical.id,
        version_group_id = selected_canonical.version_group_id,
        version_number = selected_canonical.version_number,
        is_current = false,
        quality_status = 'duplicate',
        quality_metadata = documents.quality_metadata
            || p_quality_metadata
            || jsonb_build_object(
                'duplicate_of',
                selected_canonical.id,
                'knowledge_quality_mode',
                knowledge_quality_mode
            ),
        updated_at = now()
    where documents.id = selected_job.document_id
      and documents.notebook_id = selected_job.notebook_id
      and documents.owner_id = selected_job.owner_id;

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
        detector_version,
        preferred_document_id,
        resolved_at
    )
    values (
        selected_job.owner_id,
        selected_job.notebook_id,
        selected_job.document_id,
        selected_canonical.id,
        'exact_content',
        'auto_confirmed',
        1,
        jsonb_build_object(
            'normalized_content_hash',
            p_normalized_content_hash,
            'normalization_version',
            btrim(p_normalization_version),
            'quality_mode',
            knowledge_quality_mode,
            'suppression_applied',
            true
        ),
        'Strict normalized content is identical',
        'knowledge-quality-v2',
        selected_canonical.id,
        now()
    )
    on conflict (
        source_document_id,
        target_document_id,
        detector_version
    )
    do update
    set
        relation_type = excluded.relation_type,
        status = 'auto_confirmed',
        confidence = 1,
        signals = excluded.signals,
        reason = excluded.reason,
        preferred_document_id = excluded.target_document_id,
        resolved_by = null,
        resolved_at = now(),
        updated_at = now()
    returning * into created_relation;

    if before_relation is null then
        before_relation := to_jsonb(created_relation)
            || jsonb_build_object(
                'status',
                'pending',
                'signals',
                created_relation.signals
                    || jsonb_build_object(
                        'quality_mode',
                        'shadow',
                        'suppression_applied',
                        false
                    ),
                'preferred_document_id',
                null,
                'resolved_by',
                null,
                'resolved_at',
                null
            );
    end if;

    select coalesce(
        jsonb_agg(to_jsonb(documents) order by documents.id),
        '[]'::jsonb
    )
    into after_documents
    from public.documents
    where documents.id in (
        selected_source.id,
        selected_canonical.id
    )
      and documents.notebook_id = selected_job.notebook_id
      and documents.owner_id = selected_job.owner_id;

    insert into public.knowledge_quality_audit (
        owner_id,
        notebook_id,
        relation_id,
        actor_id,
        action,
        reason,
        before_state,
        after_state
    )
    values (
        selected_job.owner_id,
        selected_job.notebook_id,
        created_relation.id,
        null,
        'auto_confirm_duplicate',
        'Strict normalized content is identical',
        jsonb_build_object(
            'relation',
            before_relation,
            'documents',
            before_documents,
            'knowledge_quality_mode',
            knowledge_quality_mode,
            'suppression_applied',
            false
        ),
        jsonb_build_object(
            'relation',
            to_jsonb(created_relation),
            'documents',
            after_documents,
            'knowledge_quality_mode',
            knowledge_quality_mode,
            'suppression_applied',
            true
        )
    );

    update public.ingestion_jobs
    set
        status = 'succeeded',
        completion_disposition = 'duplicate_suppressed',
        completed_at = now(),
        error_message = null,
        claimed_by = null,
        claim_token = null,
        lease_expires_at = null,
        updated_at = now()
    where ingestion_jobs.id = selected_job.id;
end;
$$;

revoke all on function public.complete_duplicate_ingestion_job(
    uuid, text, uuid, uuid, text, text, text, jsonb
) from public, anon, authenticated;
grant execute on function public.complete_duplicate_ingestion_job(
    uuid, text, uuid, uuid, text, text, text, jsonb
) to service_role;

-- ---------------------------------------------------------------------------
-- Fenced pgvector activation and normalized-identity serialization.
-- Embeddings now become visible in the same transaction that succeeds the job.
-- ---------------------------------------------------------------------------

drop function if exists public.complete_ingestion_job(
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
declare
    selected_job public.ingestion_jobs;
    selected_document public.documents;
    selected_canonical public.documents;
    identity_eligible boolean;
    is_repair_job boolean;
    ingestion_kind text;
    enqueued_quality_mode text;
    knowledge_quality_mode text;
    upserted_chunk_count integer;
begin
    if auth.role() <> 'service_role' then
        raise exception 'Service role is required'
            using errcode = '42501';
    end if;
    if p_chunks is null
       or jsonb_typeof(p_chunks) <> 'array'
       or jsonb_array_length(p_chunks) = 0 then
        raise exception 'Completed ingestion must contain chunks'
            using errcode = '22023';
    end if;
    if p_embedding_model is null
       or char_length(btrim(p_embedding_model)) not between 1 and 200
       or p_embedding_dimensions is null
       or p_embedding_dimensions <= 0 then
        raise exception 'Invalid embedding profile'
            using errcode = '22023';
    end if;
    if p_quality_metadata is null
       or jsonb_typeof(p_quality_metadata) <> 'object'
       or p_relations is null
       or jsonb_typeof(p_relations) <> 'array' then
        raise exception 'Invalid knowledge-quality payload'
            using errcode = '22023';
    end if;
    if (
        p_normalized_content_hash is null
        and (
            p_normalization_version is not null
            or p_loose_content_signature is not null
        )
    ) or (
        p_normalized_content_hash is not null
        and (
            p_normalized_content_hash !~ '^[0-9a-f]{64}$'
            or p_normalization_version is null
            or char_length(btrim(p_normalization_version))
                not between 1 and 100
            or p_loose_content_signature is null
            or p_loose_content_signature !~ '^[0-9a-f]{16}$'
        )
    ) then
        raise exception 'Invalid document fingerprint'
            using errcode = '22023';
    end if;
    if exists (
        select 1
        from jsonb_array_elements(p_chunks) as chunk(value)
        where jsonb_typeof(chunk.value) is distinct from 'object'
           or jsonb_typeof(chunk.value -> 'metadata')
                is distinct from 'object'
           or jsonb_typeof(chunk.value -> 'embedding')
                is distinct from 'array'
           or jsonb_array_length(chunk.value -> 'embedding')
                <> p_embedding_dimensions
           or public.vector_dims(
                (chunk.value ->> 'embedding')::public.vector
            ) <> p_embedding_dimensions
           or chunk.value -> 'metadata' ->> 'normalized_content_hash'
                is null
           or chunk.value -> 'metadata' ->> 'normalized_content_hash'
                !~ '^[0-9a-f]{64}$'
           or chunk.value -> 'metadata' ->> 'normalization_version'
                is null
           or char_length(
                btrim(
                    chunk.value -> 'metadata'
                        ->> 'normalization_version'
                )
            ) not between 1 and 100
           or chunk.value -> 'metadata' ->> 'loose_content_signature'
                is null
           or chunk.value -> 'metadata' ->> 'loose_content_signature'
                !~ '^[0-9a-f]{16}$'
    ) then
        raise exception 'Invalid chunk embedding or identity payload'
            using errcode = '22023';
    end if;

    if jsonb_array_length(p_chunks) <> (
        select count(
            distinct (chunk.value ->> 'id')::uuid
        )
        from jsonb_array_elements(p_chunks) as chunk(value)
    ) or jsonb_array_length(p_chunks) <> (
        select count(
            distinct (chunk.value ->> 'chunk_index')::integer
        )
        from jsonb_array_elements(p_chunks) as chunk(value)
    ) then
        raise exception 'Chunk ids and indexes must be unique'
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
        raise exception 'Ingestion lease is no longer owned by this worker'
            using errcode = 'P0002';
    end if;
    if selected_job.embedding_model <> btrim(p_embedding_model)
       or selected_job.embedding_dimensions <> p_embedding_dimensions then
        raise exception 'Completion profile does not match the claimed job'
            using errcode = '22023';
    end if;

    select documents.*
    into selected_document
    from public.documents
    where documents.id = selected_job.document_id
      and documents.owner_id = selected_job.owner_id
      and documents.notebook_id = selected_job.notebook_id
      and documents.is_active
      and documents.status = 'processing'
    for update;

    if not found then
        raise exception 'Ingestion document is unavailable'
            using errcode = 'P0002';
    end if;

    ingestion_kind := coalesce(
        nullif(
            btrim(selected_job.configuration ->> 'ingestion_kind'),
            ''
        ),
        'standard'
    );
    is_repair_job := ingestion_kind = 'reconciliation_repair';

    if (
        is_repair_job
        and (
            selected_job.repair_request_key is null
            or selected_job.configuration
                    ->> 'repair_request_key'
                    is distinct from
                    selected_job.repair_request_key::text
            or selected_job.configuration
                    ->> 'repair_report_sha256'
                    is null
            or selected_job.configuration
                    ->> 'repair_report_sha256'
                    !~ '^[0-9a-f]{64}$'
            or selected_job.configuration
                    ->> 'repair_issue_kind'
                    is null
            or selected_job.configuration
                    ->> 'repair_issue_kind'
                    not in (
                        'missing_vector',
                        'mismatch',
                        'missing_embedding'
                    )
            or jsonb_typeof(
                selected_job.configuration -> 'expected_lineage'
            ) is distinct from 'object'
        )
    ) or (
        not is_repair_job
        and selected_job.repair_request_key is not null
    ) then
        raise exception 'Invalid reconciliation repair profile'
            using errcode = '22023';
    end if;

    if is_repair_job then
        if jsonb_array_length(p_relations) <> 0 then
            raise exception 'Repair completion cannot create quality relations'
                using errcode = '22023';
        end if;
        if selected_document.content_hash
                is distinct from
                selected_job.configuration
                    ->> 'expected_content_hash'
           or selected_document.normalized_content_hash
                is distinct from
                selected_job.configuration
                    ->> 'expected_normalized_content_hash'
           or selected_document.normalization_version
                is distinct from
                selected_job.configuration
                    ->> 'expected_normalization_version'
           or selected_document.loose_content_signature
                is distinct from
                selected_job.configuration
                    ->> 'expected_loose_content_signature'
           or p_normalized_content_hash
                is distinct from
                selected_job.configuration
                    ->> 'expected_normalized_content_hash'
           or p_normalization_version
                is distinct from
                selected_job.configuration
                    ->> 'expected_normalization_version'
           or p_loose_content_signature
                is distinct from
                selected_job.configuration
                    ->> 'expected_loose_content_signature'
           or selected_document.canonical_document_id
                is distinct from nullif(
                    selected_job.configuration
                        -> 'expected_lineage'
                        ->> 'canonical_document_id',
                    ''
                )::uuid
           or selected_document.version_group_id
                is distinct from (
                    selected_job.configuration
                        -> 'expected_lineage'
                        ->> 'version_group_id'
                )::uuid
           or selected_document.version_number
                is distinct from (
                    selected_job.configuration
                        -> 'expected_lineage'
                        ->> 'version_number'
                )::integer
           or selected_document.effective_from
                is distinct from nullif(
                    selected_job.configuration
                        -> 'expected_lineage'
                        ->> 'effective_from',
                    ''
                )::date
           or selected_document.effective_to
                is distinct from nullif(
                    selected_job.configuration
                        -> 'expected_lineage'
                        ->> 'effective_to',
                    ''
                )::date
           or selected_document.supersedes_document_id
                is distinct from nullif(
                    selected_job.configuration
                        -> 'expected_lineage'
                        ->> 'supersedes_document_id',
                    ''
                )::uuid
           or selected_document.is_current
                is distinct from (
                    selected_job.configuration
                        -> 'expected_lineage'
                        ->> 'is_current'
                )::boolean then
            raise exception
                'Repair completion identity or lineage changed'
                using errcode = '40001';
        end if;
    end if;

    enqueued_quality_mode := coalesce(
        nullif(
            btrim(
                selected_job.configuration
                    ->> 'knowledge_quality_mode'
            ),
            ''
        ),
        'off'
    );
    if enqueued_quality_mode not in ('off', 'shadow', 'on') then
        raise exception 'Claimed job has an invalid knowledge-quality mode'
            using errcode = '22023';
    end if;

    knowledge_quality_mode := coalesce(
        nullif(
            btrim(
                p_quality_metadata
                    ->> 'knowledge_quality_mode'
            ),
            ''
        ),
        'off'
    );
    if knowledge_quality_mode not in ('off', 'shadow', 'on') then
        raise exception 'Completion has an invalid knowledge-quality mode'
            using errcode = '22023';
    end if;
    if (
        enqueued_quality_mode = 'off'
        and knowledge_quality_mode <> 'off'
    ) or (
        enqueued_quality_mode = 'shadow'
        and knowledge_quality_mode = 'on'
    ) then
        raise exception 'Completion cannot upgrade the enqueued quality mode'
            using errcode = '42501';
    end if;
    if knowledge_quality_mode = 'off'
       and not is_repair_job
       and (
           p_normalized_content_hash is not null
           or jsonb_array_length(p_relations) > 0
       ) then
        raise exception 'Off-mode ingestion cannot persist quality decisions'
            using errcode = '22023';
    end if;

    if exists (
        select 1
        from jsonb_array_elements(p_chunks) as chunk(value)
        where case
            when chunk.value -> 'metadata'
                    ->> 'exact_duplicate_group_id'
                    ~ '^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$'
            then (
                chunk.value -> 'metadata'
                    ->> 'exact_duplicate_group_id'
            )::uuid <> public.knowledge_exact_chunk_group_id(
                selected_job.owner_id,
                selected_job.notebook_id,
                btrim(
                    chunk.value -> 'metadata'
                        ->> 'normalization_version'
                ),
                chunk.value -> 'metadata'
                    ->> 'normalized_content_hash'
            )
            else true
        end
    ) then
        raise exception 'Chunk exact group does not match its tenant-scoped identity'
            using errcode = '22023';
    end if;

    if exists (
        select 1
        from public.document_chunks as existing_chunk
        join jsonb_array_elements(p_chunks) as incoming_chunk(value)
          on existing_chunk.id =
              (incoming_chunk.value ->> 'id')::uuid
        where existing_chunk.document_id <> selected_job.document_id
           or existing_chunk.owner_id <> selected_job.owner_id
           or existing_chunk.notebook_id <> selected_job.notebook_id
    ) then
        raise exception 'A chunk id is already owned by another document'
            using errcode = '23505';
    end if;

    identity_eligible := (
        p_normalized_content_hash is not null
        and p_normalization_version is not null
        and p_quality_metadata ->> 'character_count' ~ '^[0-9]+$'
        and (p_quality_metadata ->> 'character_count')::integer >= 40
        and p_quality_metadata ->> 'token_count' ~ '^[0-9]+$'
        and (p_quality_metadata ->> 'token_count')::integer >= 6
    );

    if identity_eligible
       and knowledge_quality_mode = 'on'
       and not is_repair_job then
        perform pg_catalog.pg_advisory_xact_lock(
            pg_catalog.hashtextextended(
                selected_job.owner_id::text
                    || ':' || selected_job.notebook_id::text
                    || ':' || p_normalization_version
                    || ':' || p_normalized_content_hash,
                0
            )
        );

        select documents.*
        into selected_canonical
        from public.documents
        where documents.owner_id = selected_job.owner_id
          and documents.notebook_id = selected_job.notebook_id
          and documents.id <> selected_job.document_id
          and documents.normalized_content_hash =
              p_normalized_content_hash
          and documents.normalization_version =
              p_normalization_version
          and documents.status = 'ready'
          and documents.is_active
          and documents.canonical_document_id is null
          and case
              when documents.quality_metadata ->> 'character_count'
                   ~ '^[0-9]+$'
              then (
                  documents.quality_metadata ->> 'character_count'
              )::integer >= 40
              else false
          end
          and case
              when documents.quality_metadata ->> 'token_count'
                   ~ '^[0-9]+$'
              then (
                  documents.quality_metadata ->> 'token_count'
              )::integer >= 6
              else false
          end
        order by documents.created_at, documents.id
        limit 1
        for update;

        if selected_canonical.id is not null then
            perform public.complete_duplicate_ingestion_job(
                selected_job.id,
                btrim(p_worker_id),
                p_claim_token,
                selected_canonical.id,
                p_normalized_content_hash,
                p_normalization_version,
                p_loose_content_signature,
                p_quality_metadata
            );
            return 'duplicate_suppressed';
        end if;
    end if;

    -- Remove stale ids before inserting so a changed deterministic chunk id
    -- cannot collide with (document_id, chunk_index).
    delete from public.document_chunks
    where document_chunks.document_id = selected_job.document_id
      and document_chunks.id not in (
          select (chunk.value ->> 'id')::uuid
          from jsonb_array_elements(p_chunks) as chunk(value)
      );

    insert into public.document_chunks (
        id,
        owner_id,
        notebook_id,
        document_id,
        chunk_index,
        content,
        token_count,
        metadata,
        normalized_content_hash,
        normalization_version,
        loose_content_signature,
        exact_duplicate_group_id,
        embedding
    )
    select
        (chunk.value ->> 'id')::uuid,
        selected_job.owner_id,
        selected_job.notebook_id,
        selected_job.document_id,
        (chunk.value ->> 'chunk_index')::integer,
        chunk.value ->> 'content',
        (chunk.value ->> 'token_count')::integer,
        chunk.value -> 'metadata',
        chunk.value -> 'metadata' ->> 'normalized_content_hash',
        btrim(
            chunk.value -> 'metadata'
                ->> 'normalization_version'
        ),
        chunk.value -> 'metadata' ->> 'loose_content_signature',
        public.knowledge_exact_chunk_group_id(
            selected_job.owner_id,
            selected_job.notebook_id,
            btrim(
                chunk.value -> 'metadata'
                    ->> 'normalization_version'
            ),
            chunk.value -> 'metadata'
                ->> 'normalized_content_hash'
        ),
        (chunk.value ->> 'embedding')::public.vector
    from jsonb_array_elements(p_chunks) as chunk(value)
    on conflict (id) do update
    set
        owner_id = excluded.owner_id,
        notebook_id = excluded.notebook_id,
        document_id = excluded.document_id,
        chunk_index = excluded.chunk_index,
        content = excluded.content,
        token_count = excluded.token_count,
        metadata = excluded.metadata,
        normalized_content_hash = excluded.normalized_content_hash,
        normalization_version = excluded.normalization_version,
        loose_content_signature = excluded.loose_content_signature,
        exact_duplicate_group_id = excluded.exact_duplicate_group_id,
        embedding = excluded.embedding
    where public.document_chunks.document_id = excluded.document_id
      and public.document_chunks.owner_id = excluded.owner_id
      and public.document_chunks.notebook_id = excluded.notebook_id;

    get diagnostics upserted_chunk_count = row_count;
    if upserted_chunk_count <> jsonb_array_length(p_chunks) then
        raise exception 'A chunk id was concurrently claimed by another document'
            using errcode = '23505';
    end if;

    update public.documents
    set
        status = 'ready',
        error_message = null,
        normalized_content_hash = p_normalized_content_hash,
        normalization_version = p_normalization_version,
        loose_content_signature = p_loose_content_signature,
        quality_metadata = documents.quality_metadata
            || case
                when is_repair_job then '{}'::jsonb
                else p_quality_metadata
                    || jsonb_build_object(
                        'knowledge_quality_mode',
                        knowledge_quality_mode
                    )
            end,
        quality_status = documents.quality_status,
        updated_at = now()
    where documents.id = selected_job.document_id
      and documents.notebook_id = selected_job.notebook_id
      and documents.owner_id = selected_job.owner_id;

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
        selected_job.owner_id,
        selected_job.notebook_id,
        selected_job.document_id,
        target.id,
        relation.value ->> 'relation_type',
        'pending',
        least(
            greatest(
                (relation.value ->> 'confidence')::double precision,
                0
            ),
            1
        ),
        coalesce(relation.value -> 'signals', '{}'::jsonb)
            || jsonb_build_object(
                'quality_mode',
                knowledge_quality_mode,
                'suppression_applied',
                false
            ),
        nullif(btrim(relation.value ->> 'reason'), ''),
        coalesce(
            nullif(
                btrim(relation.value ->> 'detector_version'),
                ''
            ),
            'knowledge-quality-v1'
        )
    from jsonb_array_elements(p_relations) as relation(value)
    join public.documents as target
      on target.id =
          (relation.value ->> 'target_document_id')::uuid
     and target.notebook_id = selected_job.notebook_id
     and target.owner_id = selected_job.owner_id
     and target.is_active
    where target.id <> selected_job.document_id
      and relation.value ->> 'relation_type' in (
          'exact_content',
          'near_duplicate',
          'version_candidate',
          'version',
          'conflict_candidate',
          'conflict',
          'related',
          'distinct',
          'technical_duplicate',
          'template_variant'
      )
      and jsonb_typeof(
          coalesce(relation.value -> 'signals', '{}'::jsonb)
      ) = 'object'
    on conflict (
        source_document_id,
        target_document_id,
        detector_version
    )
    do update
    set
        relation_type = excluded.relation_type,
        confidence = greatest(
            public.document_relations.confidence,
            excluded.confidence
        ),
        signals = excluded.signals,
        reason = excluded.reason,
        updated_at = now()
    where public.document_relations.status = 'pending';

    update public.documents
    set
        quality_status = case
            when is_repair_job then documents.quality_status
            when exists (
                select 1
                from public.document_relations
                where document_relations.source_document_id =
                    selected_job.document_id
                  and document_relations.status = 'pending'
            ) then 'review_required'
            when p_normalized_content_hash is not null
                 and documents.quality_status in (
                     'unreviewed',
                     'clean',
                     'review_required'
                 ) then 'clean'
            else documents.quality_status
        end,
        updated_at = now()
    where documents.id = selected_job.document_id
      and documents.notebook_id = selected_job.notebook_id
      and documents.owner_id = selected_job.owner_id;

    update public.ingestion_jobs
    set
        status = 'succeeded',
        completion_disposition = 'completed',
        embedding_model = btrim(p_embedding_model),
        embedding_dimensions = p_embedding_dimensions,
        completed_at = now(),
        error_message = null,
        claimed_by = null,
        claim_token = null,
        lease_expires_at = null,
        updated_at = now()
    where ingestion_jobs.id = selected_job.id;

    return 'completed';
end;
$$;

revoke all on function public.complete_ingestion_job(
    uuid, text, uuid, text, integer, jsonb, text, text, text, jsonb, jsonb
) from public, anon, authenticated;
grant execute on function public.complete_ingestion_job(
    uuid, text, uuid, text, integer, jsonb, text, text, text, jsonb, jsonb
) to service_role;

-- ---------------------------------------------------------------------------
-- Reconciliation repair path.
--
-- Requeueing is deliberately narrower than user enqueueing: only the service
-- reconciliation loop may repair an active canonical document that is already
-- ready/failed. A checksum-bound reconciliation manifest is authoritative
-- because external-vector-store gaps are not visible to PostgreSQL.
-- ---------------------------------------------------------------------------

do $migration$
begin
    if not exists (
        select 1
        from pg_catalog.pg_type as types
        join pg_catalog.pg_namespace as namespaces
          on namespaces.oid = types.typnamespace
        where namespaces.nspname = 'public'
          and types.typname = 'ingestion_repair_issue_kind'
    ) then
        create type public.ingestion_repair_issue_kind as enum (
            'missing_vector',
            'mismatch',
            'missing_embedding'
        );
    end if;
end;
$migration$;

alter table public.ingestion_jobs
    add column if not exists repair_request_key uuid;

create unique index if not exists
    ingestion_jobs_repair_request_key
    on public.ingestion_jobs (
        owner_id,
        document_id,
        repair_request_key
    )
    where repair_request_key is not null;

comment on column public.ingestion_jobs.repair_request_key is
    'Caller-stable idempotency key for reconciliation repair attempts.';

drop function if exists public.requeue_document_ingestion_repair(
    uuid, uuid, uuid, text
);
drop function if exists public.requeue_document_ingestion_repair(
    uuid, uuid, uuid, uuid, timestamptz, text
);
drop function if exists public.requeue_document_ingestion_repair(
    uuid,
    uuid,
    uuid,
    uuid,
    timestamptz,
    text,
    public.ingestion_repair_issue_kind,
    text
);
create function public.requeue_document_ingestion_repair(
    p_document_id uuid,
    p_owner_id uuid,
    p_notebook_id uuid,
    p_request_key uuid,
    p_expected_updated_at timestamptz,
    p_report_sha256 text,
    p_issue_kind public.ingestion_repair_issue_kind,
    p_reason text
)
returns setof public.ingestion_jobs
language plpgsql
security definer
set search_path = ''
as $$
declare
    selected_document public.documents;
    latest_job public.ingestion_jobs;
    created_job public.ingestion_jobs;
    repaired_document public.documents;
    chunk_count integer;
    invalid_chunk_count integer;
    next_attempt integer;
    before_state jsonb;
    after_state jsonb;
begin
    if auth.role() <> 'service_role' then
        raise exception 'Service role is required'
            using errcode = '42501';
    end if;
    if p_document_id is null
       or p_owner_id is null
       or p_notebook_id is null
       or p_request_key is null
       or p_expected_updated_at is null
       or p_report_sha256 is null
       or p_report_sha256 !~ '^[0-9a-f]{64}$'
       or p_issue_kind is null
       or p_reason is null
       or char_length(btrim(p_reason)) not between 1 and 2000 then
        raise exception 'Invalid repair request'
            using errcode = '22023';
    end if;

    select documents.*
    into selected_document
    from public.documents
    where documents.id = p_document_id
      and documents.owner_id = p_owner_id
      and documents.notebook_id = p_notebook_id
      and documents.is_active
    for update;

    if not found then
        raise exception 'Repair document was not found'
            using errcode = 'P0002';
    end if;

    -- A response-loss retry returns the exact attempt created by the original
    -- request, even though that first attempt already changed document state.
    select jobs.*
    into created_job
    from public.ingestion_jobs as jobs
    where jobs.document_id = selected_document.id
      and jobs.owner_id = selected_document.owner_id
      and jobs.notebook_id = selected_document.notebook_id
      and jobs.repair_request_key = p_request_key
    for update;

    if found then
        if created_job.configuration
                ->> 'repair_report_sha256'
                is distinct from p_report_sha256
           or created_job.configuration
                ->> 'repair_issue_kind'
                is distinct from p_issue_kind::text then
            raise exception
                'Repair request key was reused with a different manifest'
                using errcode = '22023';
        end if;
        return next created_job;
        return;
    end if;

    perform jobs.id
    from public.ingestion_jobs as jobs
    where jobs.document_id = selected_document.id
      and jobs.owner_id = selected_document.owner_id
      and jobs.notebook_id = selected_document.notebook_id
      and jobs.status in ('pending', 'running')
    order by jobs.attempt_number desc, jobs.id
    limit 1
    for update;

    if found then
        raise exception
            'A different ingestion attempt is already active'
            using errcode = '55000';
    end if;

    if selected_document.canonical_document_id is not null
       or selected_document.status not in ('ready', 'failed') then
        raise exception
            'Repair requires an active ready/failed canonical document'
            using errcode = 'P0002';
    end if;
    if selected_document.updated_at <> p_expected_updated_at then
        raise exception 'Repair document changed before requeue'
            using errcode = '40001';
    end if;

    select jobs.*
    into latest_job
    from public.ingestion_jobs as jobs
    where jobs.document_id = selected_document.id
      and jobs.owner_id = selected_document.owner_id
      and jobs.notebook_id = selected_document.notebook_id
      and jobs.status = 'succeeded'
    order by jobs.attempt_number desc, jobs.id
    limit 1
    for update;

    if not found then
        raise exception 'No succeeded ingestion profile is available for repair'
            using errcode = 'P0002';
    end if;

    select
        count(*),
        count(*) filter (
            where chunks.embedding is null
               or public.vector_dims(chunks.embedding)
                    <> latest_job.embedding_dimensions
               or chunks.normalized_content_hash
                    !~ '^[0-9a-f]{64}$'
               or chunks.normalization_version is null
               or char_length(btrim(chunks.normalization_version))
                    not between 1 and 100
               or chunks.loose_content_signature
                    !~ '^[0-9a-f]{16}$'
               or chunks.exact_duplicate_group_id
                    <> public.knowledge_exact_chunk_group_id(
                        chunks.owner_id,
                        chunks.notebook_id,
                        chunks.normalization_version,
                        chunks.normalized_content_hash
                    )
               or chunks.metadata
                    ->> 'normalized_content_hash'
                    is distinct from chunks.normalized_content_hash
               or chunks.metadata
                    ->> 'normalization_version'
                    is distinct from chunks.normalization_version
               or chunks.metadata
                    ->> 'loose_content_signature'
                    is distinct from chunks.loose_content_signature
        )
    into chunk_count, invalid_chunk_count
    from public.document_chunks as chunks
    where chunks.document_id = selected_document.id
      and chunks.owner_id = selected_document.owner_id
      and chunks.notebook_id = selected_document.notebook_id;

    select coalesce(max(jobs.attempt_number), 0) + 1
    into next_attempt
    from public.ingestion_jobs as jobs
    where jobs.document_id = selected_document.id
      and jobs.owner_id = selected_document.owner_id
      and jobs.notebook_id = selected_document.notebook_id;
    before_state := jsonb_build_object(
        'document',
        to_jsonb(selected_document),
        'latest_job',
        to_jsonb(latest_job),
        'diagnostics',
        jsonb_build_object(
            'report_sha256',
            p_report_sha256,
            'issue_kind',
            p_issue_kind::text,
            'chunk_count',
            chunk_count,
            'invalid_chunk_count',
            invalid_chunk_count
        )
    );

    insert into public.ingestion_jobs (
        owner_id,
        notebook_id,
        document_id,
        attempt_number,
        status,
        embedding_model,
        embedding_dimensions,
        configuration,
        repair_request_key
    )
    values (
        selected_document.owner_id,
        selected_document.notebook_id,
        selected_document.id,
        next_attempt,
        'pending',
        latest_job.embedding_model,
        latest_job.embedding_dimensions,
        latest_job.configuration
            || jsonb_build_object(
                'ingestion_kind',
                'reconciliation_repair',
                'repair_request_key',
                p_request_key,
                'repair_report_sha256',
                p_report_sha256,
                'repair_issue_kind',
                p_issue_kind::text,
                'repair_reason',
                btrim(p_reason),
                'expected_content_hash',
                selected_document.content_hash,
                'expected_normalized_content_hash',
                selected_document.normalized_content_hash,
                'expected_normalization_version',
                selected_document.normalization_version,
                'expected_loose_content_signature',
                selected_document.loose_content_signature,
                'expected_lineage',
                jsonb_build_object(
                    'canonical_document_id',
                    selected_document.canonical_document_id,
                    'version_group_id',
                    selected_document.version_group_id,
                    'version_number',
                    selected_document.version_number,
                    'effective_from',
                    selected_document.effective_from,
                    'effective_to',
                    selected_document.effective_to,
                    'supersedes_document_id',
                    selected_document.supersedes_document_id,
                    'is_current',
                    selected_document.is_current
                )
            ),
        p_request_key
    )
    returning * into created_job;

    update public.documents
    set
        status = 'processing',
        error_message = null,
        quality_metadata = documents.quality_metadata
            || jsonb_build_object(
                'repair_requeue_reason',
                btrim(p_reason),
                'repair_requeue_job_id',
                created_job.id,
                'repair_requeued_at',
                now()
            ),
        updated_at = now()
    where documents.id = selected_document.id
      and documents.owner_id = selected_document.owner_id
      and documents.notebook_id = selected_document.notebook_id
    returning documents.* into repaired_document;

    after_state := jsonb_build_object(
        'document',
        to_jsonb(repaired_document),
        'job',
        to_jsonb(created_job)
    );

    insert into public.knowledge_quality_audit (
        owner_id,
        notebook_id,
        relation_id,
        actor_id,
        action,
        reason,
        before_state,
        after_state
    )
    values (
        selected_document.owner_id,
        selected_document.notebook_id,
        null,
        null,
        'repair_requeue',
        btrim(p_reason),
        before_state,
        after_state
    );

    return next created_job;
end;
$$;

revoke all on function public.requeue_document_ingestion_repair(
    uuid,
    uuid,
    uuid,
    uuid,
    timestamptz,
    text,
    public.ingestion_repair_issue_kind,
    text
) from public, anon, authenticated;
grant execute on function public.requeue_document_ingestion_repair(
    uuid,
    uuid,
    uuid,
    uuid,
    timestamptz,
    text,
    public.ingestion_repair_issue_kind,
    text
) to service_role;

-- ---------------------------------------------------------------------------
-- Complete affected-document snapshots and family-serialized resolution.
-- ---------------------------------------------------------------------------

drop function if exists public.resolve_document_relation(
    uuid, uuid, text, timestamptz, text
);
create function public.resolve_document_relation(
    p_relation_id uuid,
    p_notebook_id uuid,
    p_action text,
    p_expected_updated_at timestamptz,
    p_reason text
)
returns setof public.document_relations
language plpgsql
security definer
set search_path = ''
as $$
declare
    actor uuid;
    selected_relation public.document_relations;
    source_document public.documents;
    target_document public.documents;
    family_group_id uuid;
    affected_document_ids uuid[];
    before_documents jsonb;
    after_documents jsonb;
    before_state jsonb;
    after_state jsonb;
    preferred_id uuid;
    next_version integer;
begin
    actor := auth.uid();
    if actor is null then
        raise exception 'Authentication is required'
            using errcode = '42501';
    end if;
    if p_action not in (
        'confirm_duplicate',
        'mark_version',
        'confirm_conflict',
        'keep_separate',
        'prefer_source',
        'prefer_target',
        'dismiss'
    ) then
        raise exception 'Unsupported relation action'
            using errcode = '22023';
    end if;
    if p_reason is null
       or char_length(btrim(p_reason)) not between 1 and 2000 then
        raise exception 'Invalid resolution reason'
            using errcode = '22023';
    end if;

    select relations.*
    into selected_relation
    from public.document_relations as relations
    where relations.id = p_relation_id
      and relations.notebook_id = p_notebook_id
      and relations.owner_id = actor
    for update;

    if not found then
        raise exception 'Document relation was not found'
            using errcode = 'P0002';
    end if;
    if p_expected_updated_at is null
       or selected_relation.updated_at <> p_expected_updated_at then
        raise exception 'Document relation changed before resolution'
            using errcode = '40001';
    end if;

    if p_action = 'mark_version' then
        select documents.version_group_id
        into family_group_id
        from public.documents
        where documents.id = selected_relation.target_document_id
          and documents.notebook_id = p_notebook_id
          and documents.owner_id = actor;

        if family_group_id is null then
            raise exception 'Related document was not found'
                using errcode = 'P0002';
        end if;

        perform pg_catalog.pg_advisory_xact_lock(
            pg_catalog.hashtextextended(
                actor::text
                    || ':' || p_notebook_id::text
                    || ':' || family_group_id::text,
                0
            )
        );

        perform 1
        from public.documents
        where documents.owner_id = actor
          and documents.notebook_id = p_notebook_id
          and (
              documents.version_group_id = family_group_id
              or documents.id = selected_relation.source_document_id
          )
        order by documents.id
        for update;
    else
        perform 1
        from public.documents
        where documents.owner_id = actor
          and documents.notebook_id = p_notebook_id
          and documents.id in (
              selected_relation.source_document_id,
              selected_relation.target_document_id
          )
        order by documents.id
        for update;
    end if;

    select documents.*
    into source_document
    from public.documents
    where documents.id = selected_relation.source_document_id
      and documents.notebook_id = p_notebook_id
      and documents.owner_id = actor;

    select documents.*
    into target_document
    from public.documents
    where documents.id = selected_relation.target_document_id
      and documents.notebook_id = p_notebook_id
      and documents.owner_id = actor;

    if source_document.id is null or target_document.id is null then
        raise exception 'Related document was not found'
            using errcode = 'P0002';
    end if;
    if p_action = 'mark_version'
       and target_document.version_group_id <> family_group_id then
        raise exception 'Document family changed before resolution'
            using errcode = '40001';
    end if;

    if p_action = 'mark_version' then
        select array_agg(documents.id order by documents.id)
        into affected_document_ids
        from public.documents
        where documents.owner_id = actor
          and documents.notebook_id = p_notebook_id
          and (
              documents.version_group_id = family_group_id
              or documents.id = source_document.id
          );
    else
        affected_document_ids := array[
            source_document.id,
            target_document.id
        ];
    end if;

    select coalesce(
        jsonb_agg(to_jsonb(documents) order by documents.id),
        '[]'::jsonb
    )
    into before_documents
    from public.documents
    where documents.id = any(affected_document_ids)
      and documents.owner_id = actor
      and documents.notebook_id = p_notebook_id;

    before_state := jsonb_build_object(
        'relation', to_jsonb(selected_relation),
        'documents', before_documents,
        'source_document', to_jsonb(source_document),
        'target_document', to_jsonb(target_document)
    );

    if p_action = 'confirm_duplicate' then
        preferred_id := coalesce(
            target_document.canonical_document_id,
            target_document.id
        );

        if preferred_id <> target_document.id then
            select documents.*
            into target_document
            from public.documents
            where documents.id = preferred_id
              and documents.notebook_id = p_notebook_id
              and documents.owner_id = actor
            for update;
        end if;

        update public.documents
        set
            canonical_document_id = target_document.id,
            version_group_id = target_document.version_group_id,
            version_number = target_document.version_number,
            is_current = false,
            quality_status = 'duplicate',
            updated_at = now()
        where documents.id = source_document.id;

        update public.document_relations
        set
            relation_type = 'exact_content',
            status = 'confirmed',
            preferred_document_id = target_document.id,
            resolved_by = actor,
            resolved_at = now(),
            reason = coalesce(
                nullif(btrim(p_reason), ''),
                document_relations.reason
            ),
            updated_at = now()
        where document_relations.id = selected_relation.id;

    elsif p_action = 'mark_version' then
        select coalesce(max(documents.version_number), 0) + 1
        into next_version
        from public.documents
        where documents.owner_id = actor
          and documents.notebook_id = p_notebook_id
          and documents.version_group_id = family_group_id
          and documents.canonical_document_id is null;

        update public.documents
        set
            is_current = false,
            quality_status = case
                when documents.id = target_document.id
                then 'superseded'
                else documents.quality_status
            end,
            effective_to = case
                when documents.id = target_document.id
                then coalesce(documents.effective_to, current_date)
                else documents.effective_to
            end,
            updated_at = now()
        where documents.owner_id = actor
          and documents.notebook_id = p_notebook_id
          and documents.version_group_id = family_group_id
          and documents.id <> source_document.id;

        update public.documents
        set
            canonical_document_id = null,
            version_group_id = family_group_id,
            version_number = next_version,
            supersedes_document_id = target_document.id,
            is_current = true,
            effective_from = coalesce(
                documents.effective_from,
                current_date
            ),
            effective_to = null,
            quality_status = 'clean',
            updated_at = now()
        where documents.id = source_document.id;

        update public.document_relations
        set
            relation_type = 'version',
            status = 'confirmed',
            preferred_document_id = source_document.id,
            resolved_by = actor,
            resolved_at = now(),
            reason = coalesce(
                nullif(btrim(p_reason), ''),
                document_relations.reason
            ),
            updated_at = now()
        where document_relations.id = selected_relation.id;

    elsif p_action in (
        'confirm_conflict',
        'prefer_source',
        'prefer_target'
    ) then
        preferred_id := case
            when p_action = 'prefer_source' then source_document.id
            when p_action = 'prefer_target' then target_document.id
            else null
        end;

        update public.documents
        set
            quality_status = 'conflict',
            updated_at = now()
        where documents.id in (
            source_document.id,
            target_document.id
        );

        update public.document_relations
        set
            relation_type = 'conflict',
            status = 'confirmed',
            preferred_document_id = preferred_id,
            resolved_by = actor,
            resolved_at = now(),
            reason = coalesce(
                nullif(btrim(p_reason), ''),
                document_relations.reason
            ),
            updated_at = now()
        where document_relations.id = selected_relation.id;

    elsif p_action = 'keep_separate' then
        update public.document_relations
        set
            relation_type = 'distinct',
            status = 'confirmed',
            preferred_document_id = null,
            resolved_by = actor,
            resolved_at = now(),
            reason = coalesce(
                nullif(btrim(p_reason), ''),
                document_relations.reason
            ),
            updated_at = now()
        where document_relations.id = selected_relation.id;

    else
        update public.document_relations
        set
            status = 'dismissed',
            preferred_document_id = null,
            resolved_by = actor,
            resolved_at = now(),
            reason = coalesce(
                nullif(btrim(p_reason), ''),
                document_relations.reason
            ),
            updated_at = now()
        where document_relations.id = selected_relation.id;
    end if;

    select relations.*
    into selected_relation
    from public.document_relations as relations
    where relations.id = p_relation_id;

    select documents.*
    into source_document
    from public.documents
    where documents.id = selected_relation.source_document_id;

    select documents.*
    into target_document
    from public.documents
    where documents.id = selected_relation.target_document_id;

    select coalesce(
        jsonb_agg(to_jsonb(documents) order by documents.id),
        '[]'::jsonb
    )
    into after_documents
    from public.documents
    where documents.id = any(affected_document_ids)
      and documents.owner_id = actor
      and documents.notebook_id = p_notebook_id;

    after_state := jsonb_build_object(
        'relation', to_jsonb(selected_relation),
        'documents', after_documents,
        'source_document', to_jsonb(source_document),
        'target_document', to_jsonb(target_document)
    );

    insert into public.knowledge_quality_audit (
        owner_id,
        notebook_id,
        relation_id,
        actor_id,
        action,
        reason,
        before_state,
        after_state
    )
    values (
        actor,
        p_notebook_id,
        selected_relation.id,
        actor,
        p_action,
        nullif(btrim(p_reason), ''),
        before_state,
        after_state
    );

    return next selected_relation;
end;
$$;

revoke all on function public.resolve_document_relation(
    uuid, uuid, text, timestamptz, text
) from public, anon;
grant execute on function public.resolve_document_relation(
    uuid, uuid, text, timestamptz, text
) to authenticated;

-- ---------------------------------------------------------------------------
-- Append-only compensating reverts.
-- ---------------------------------------------------------------------------

alter table public.knowledge_quality_audit
    add column if not exists reverts_audit_id bigint;

do $migration$
begin
    if not exists (
        select 1
        from pg_catalog.pg_constraint
        where pg_constraint.conrelid =
            'public.knowledge_quality_audit'::regclass
          and pg_constraint.conname =
            'knowledge_quality_audit_reverts_fk'
    ) then
        alter table public.knowledge_quality_audit
            add constraint knowledge_quality_audit_reverts_fk
            foreign key (reverts_audit_id)
            references public.knowledge_quality_audit (id)
            on delete restrict;
    end if;
end;
$migration$;

create unique index if not exists knowledge_quality_audit_one_revert
    on public.knowledge_quality_audit (reverts_audit_id)
    where reverts_audit_id is not null;

drop function if exists public.revert_document_relation_resolution(
    uuid, uuid, timestamptz, text
);
create function public.revert_document_relation_resolution(
    p_relation_id uuid,
    p_notebook_id uuid,
    p_expected_updated_at timestamptz,
    p_reason text
)
returns setof public.document_relations
language plpgsql
security definer
set search_path = ''
as $$
declare
    actor uuid;
    original_audit public.knowledge_quality_audit;
    selected_relation public.document_relations;
    restored_relation public.document_relations;
    snapshot_document_count integer;
    matched_document_count integer;
    snapshot_document_ids uuid[];
    current_documents jsonb;
    restored_documents jsonb;
    before_state jsonb;
    after_state jsonb;
begin
    actor := auth.uid();
    if actor is null then
        raise exception 'Authentication is required'
            using errcode = '42501';
    end if;
    if p_reason is null
       or char_length(btrim(p_reason)) not between 1 and 2000 then
        raise exception 'Invalid revert reason'
            using errcode = '22023';
    end if;

    select relations.*
    into selected_relation
    from public.document_relations as relations
    where relations.id = p_relation_id
      and relations.notebook_id = p_notebook_id
      and relations.owner_id = actor
    for update;

    if not found then
        raise exception 'Document relation was not found'
            using errcode = 'P0002';
    end if;
    if p_expected_updated_at is null
       or selected_relation.updated_at
            <> p_expected_updated_at then
        raise exception 'Document relation changed before revert'
            using errcode = '40001';
    end if;

    select audit.*
    into original_audit
    from public.knowledge_quality_audit as audit
    where audit.relation_id = selected_relation.id
      and audit.notebook_id = p_notebook_id
      and audit.owner_id = actor
      and audit.reverts_audit_id is null
      and audit.action <> 'revert_resolution'
      and jsonb_typeof(audit.before_state -> 'documents') = 'array'
      and jsonb_typeof(audit.after_state -> 'documents') = 'array'
      and audit.after_state -> 'relation' = to_jsonb(selected_relation)
      and not exists (
          select 1
          from public.knowledge_quality_audit as revert_audit
          where revert_audit.reverts_audit_id = audit.id
      )
    order by audit.id desc
    limit 1
    for update;

    if not found then
        raise exception 'No reversible current resolution was found'
            using errcode = 'P0002';
    end if;

    select
        count(*),
        array_agg(
            (snapshot.value ->> 'id')::uuid
            order by (snapshot.value ->> 'id')::uuid
        )
    into snapshot_document_count, snapshot_document_ids
    from jsonb_array_elements(
        original_audit.before_state -> 'documents'
    ) as snapshot(value);

    if snapshot_document_count = 0
       or snapshot_document_count
            <> jsonb_array_length(
                original_audit.after_state -> 'documents'
            ) then
        raise exception 'Audit event has an incomplete document snapshot'
            using errcode = '22023';
    end if;

    perform 1
    from public.documents
    where documents.id = any(snapshot_document_ids)
      and documents.owner_id = actor
      and documents.notebook_id = p_notebook_id
    order by documents.id
    for update;

    select
        count(*),
        coalesce(
            jsonb_agg(to_jsonb(documents) order by documents.id),
            '[]'::jsonb
        )
    into matched_document_count, current_documents
    from public.documents
    where documents.id = any(snapshot_document_ids)
      and documents.owner_id = actor
      and documents.notebook_id = p_notebook_id;

    if matched_document_count <> snapshot_document_count then
        raise exception 'A snapshotted document is no longer available'
            using errcode = 'P0002';
    end if;
    if current_documents <> original_audit.after_state -> 'documents' then
        raise exception 'Affected documents changed before revert'
            using errcode = '40001';
    end if;

    before_state := jsonb_build_object(
        'relation', to_jsonb(selected_relation),
        'documents', current_documents,
        'reverted_audit_id', original_audit.id
    );

    -- Clear the immediate current-document invariant before restoring all
    -- snapshotted rows in one deterministic update.
    update public.documents
    set
        is_current = false,
        updated_at = now()
    where documents.id = any(snapshot_document_ids)
      and documents.owner_id = actor
      and documents.notebook_id = p_notebook_id;

    with snapshots as (
        select snapshot.value
        from jsonb_array_elements(
            original_audit.before_state -> 'documents'
        ) as snapshot(value)
    )
    update public.documents
    set
        original_filename = snapshots.value ->> 'original_filename',
        storage_bucket = snapshots.value ->> 'storage_bucket',
        storage_object_path =
            snapshots.value ->> 'storage_object_path',
        mime_type = snapshots.value ->> 'mime_type',
        size_bytes = (snapshots.value ->> 'size_bytes')::bigint,
        content_hash = snapshots.value ->> 'content_hash',
        status = snapshots.value ->> 'status',
        error_message = snapshots.value ->> 'error_message',
        is_active = (snapshots.value ->> 'is_active')::boolean,
        normalized_content_hash =
            snapshots.value ->> 'normalized_content_hash',
        normalization_version =
            snapshots.value ->> 'normalization_version',
        loose_content_signature =
            snapshots.value ->> 'loose_content_signature',
        canonical_document_id = nullif(
            snapshots.value ->> 'canonical_document_id',
            ''
        )::uuid,
        version_group_id = (
            snapshots.value ->> 'version_group_id'
        )::uuid,
        version_number = (
            snapshots.value ->> 'version_number'
        )::integer,
        effective_from = nullif(
            snapshots.value ->> 'effective_from',
            ''
        )::date,
        effective_to = nullif(
            snapshots.value ->> 'effective_to',
            ''
        )::date,
        supersedes_document_id = nullif(
            snapshots.value ->> 'supersedes_document_id',
            ''
        )::uuid,
        is_current = (
            snapshots.value ->> 'is_current'
        )::boolean,
        quality_status = snapshots.value ->> 'quality_status',
        quality_metadata = snapshots.value -> 'quality_metadata',
        updated_at = now()
    from snapshots
    where documents.id = (snapshots.value ->> 'id')::uuid
      and documents.owner_id = actor
      and documents.notebook_id = p_notebook_id;

    update public.document_relations
    set
        relation_type =
            original_audit.before_state -> 'relation'
                ->> 'relation_type',
        status =
            original_audit.before_state -> 'relation'
                ->> 'status',
        confidence = (
            original_audit.before_state -> 'relation'
                ->> 'confidence'
        )::double precision,
        signals =
            original_audit.before_state -> 'relation' -> 'signals',
        reason =
            original_audit.before_state -> 'relation' ->> 'reason',
        detector_version =
            original_audit.before_state -> 'relation'
                ->> 'detector_version',
        preferred_document_id = nullif(
            original_audit.before_state -> 'relation'
                ->> 'preferred_document_id',
            ''
        )::uuid,
        resolved_by = nullif(
            original_audit.before_state -> 'relation'
                ->> 'resolved_by',
            ''
        )::uuid,
        resolved_at = nullif(
            original_audit.before_state -> 'relation'
                ->> 'resolved_at',
            ''
        )::timestamptz,
        updated_at = now()
    where document_relations.id = selected_relation.id
      and document_relations.notebook_id = p_notebook_id
      and document_relations.owner_id = actor
    returning document_relations.* into restored_relation;

    select coalesce(
        jsonb_agg(to_jsonb(documents) order by documents.id),
        '[]'::jsonb
    )
    into restored_documents
    from public.documents
    where documents.id = any(snapshot_document_ids)
      and documents.owner_id = actor
      and documents.notebook_id = p_notebook_id;

    after_state := jsonb_build_object(
        'relation', to_jsonb(restored_relation),
        'documents', restored_documents,
        'reverted_audit_id', original_audit.id
    );

    insert into public.knowledge_quality_audit (
        owner_id,
        notebook_id,
        relation_id,
        actor_id,
        action,
        reason,
        before_state,
        after_state,
        reverts_audit_id
    )
    values (
        actor,
        p_notebook_id,
        restored_relation.id,
        actor,
        'revert_resolution',
        nullif(btrim(p_reason), ''),
        before_state,
        after_state,
        original_audit.id
    );

    return next restored_relation;
end;
$$;

revoke all on function public.revert_document_relation_resolution(
    uuid, uuid, timestamptz, text
) from public, anon;
grant execute on function public.revert_document_relation_resolution(
    uuid, uuid, timestamptz, text
) to authenticated;
