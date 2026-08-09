-- Run after 02_tables.sql.

-- updated_at triggers
create function public.set_notebooks_updated_at()
returns trigger
language plpgsql
security invoker
set search_path = ''
as $$
begin
    new.updated_at = now();
    return new;
end;
$$;

revoke all on function public.set_notebooks_updated_at() from public;

create trigger notebooks_set_updated_at
before update on public.notebooks
for each row
execute function public.set_notebooks_updated_at();

create function public.set_rag_record_updated_at()
returns trigger
language plpgsql
security invoker
set search_path = ''
as $$
begin
    new.updated_at = now();
    return new;
end;
$$;

revoke all on function public.set_rag_record_updated_at() from public;

create trigger documents_set_updated_at
before update on public.documents
for each row
execute function public.set_rag_record_updated_at();

create trigger ingestion_jobs_set_updated_at
before update on public.ingestion_jobs
for each row
execute function public.set_rag_record_updated_at();

create trigger conversations_set_updated_at
before update on public.conversations
for each row
execute function public.set_rag_record_updated_at();

create trigger messages_set_updated_at
before update on public.messages
for each row
execute function public.set_rag_record_updated_at();

create trigger profiles_set_updated_at
before update on public.profiles
for each row
execute function public.set_rag_record_updated_at();

-- profiles: auto-create on signup
create function public.handle_new_user()
returns trigger
language plpgsql
security definer
set search_path = ''
as $$
begin
    insert into public.profiles (id, display_name)
    values (new.id, new.raw_user_meta_data ->> 'full_name')
    on conflict (id) do nothing;
    return new;
end;
$$;

revoke all on function public.handle_new_user() from public;

create trigger on_auth_user_created
after insert on auth.users
for each row
execute function public.handle_new_user();

-- Avoids RLS recursion (42P17) in profiles_update_own.
create function public.current_profile_role()
returns text
language sql
stable
security definer
set search_path = ''
as $$
    select role from public.profiles where id = auth.uid();
$$;

revoke all on function public.current_profile_role() from public;
grant execute on function public.current_profile_role() to authenticated;

-- Custom Access Token Hook - injects user_role claim into the JWT.
-- Needs manual enable in Dashboard -> Auth -> Hooks.
create function public.custom_access_token_hook(event jsonb)
returns jsonb
language plpgsql
stable
security definer
set search_path = ''
as $$
declare
    claims jsonb;
    user_role text;
begin
    select role into user_role
    from public.profiles
    where id = (event ->> 'user_id')::uuid;

    claims := event -> 'claims';
    claims := jsonb_set(claims, '{user_role}', to_jsonb(coalesce(user_role, 'user')));
    event := jsonb_set(event, '{claims}', claims);

    return event;
end;
$$;

revoke all on function public.custom_access_token_hook(jsonb) from public, anon, authenticated;
grant execute on function public.custom_access_token_hook(jsonb) to supabase_auth_admin;

-- Ingestion job queue RPCs
create function public.enqueue_document_ingestion(
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
    next_attempt integer;
begin
    if auth.uid() is null then
        raise exception 'Authentication is required'
            using errcode = '42501';
    end if;
    if char_length(btrim(p_embedding_model)) not between 1 and 200 then
        raise exception 'Invalid embedding model'
            using errcode = '22023';
    end if;
    if p_embedding_dimensions <= 0 then
        raise exception 'Invalid embedding dimensions'
            using errcode = '22023';
    end if;
    if p_configuration is null or jsonb_typeof(p_configuration) <> 'object' then
        raise exception 'Ingestion configuration must be an object'
            using errcode = '22023';
    end if;

    select documents.*
    into selected_document
    from public.documents
    where documents.id = p_document_id
      and documents.notebook_id = p_notebook_id
      and documents.owner_id = auth.uid()
      and documents.status = 'uploading'
    for update;

    if not found then
        raise exception 'Uploaded document is not available for ingestion'
            using errcode = 'P0002';
    end if;

    select coalesce(max(ingestion_jobs.attempt_number), 0) + 1
    into next_attempt
    from public.ingestion_jobs
    where ingestion_jobs.document_id = p_document_id;

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
        error_message = null
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
language plpgsql
security definer
set search_path = ''
as $$
begin
    if auth.role() <> 'service_role' then
        raise exception 'Service role is required'
            using errcode = '42501';
    end if;
    if p_worker_id is null
       or char_length(btrim(p_worker_id)) = 0
       or p_lease_seconds < 30 then
        raise exception 'Invalid worker lease'
            using errcode = '22023';
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
            lease_expires_at = now() + make_interval(secs => p_lease_seconds),
            started_at = coalesce(jobs.started_at, now()),
            error_message = null
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
        documents.content_hash
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

create function public.renew_ingestion_job_lease(
    p_job_id uuid,
    p_worker_id text,
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
    set lease_expires_at = now() + make_interval(secs => p_lease_seconds)
    where ingestion_jobs.id = p_job_id
      and ingestion_jobs.status = 'running'
      and ingestion_jobs.claimed_by = p_worker_id;

    get diagnostics updated_count = row_count;
    return updated_count = 1;
end;
$$;

revoke all on function public.renew_ingestion_job_lease(uuid, text, integer)
from public, anon, authenticated;
grant execute on function public.renew_ingestion_job_lease(uuid, text, integer)
to service_role;

create function public.complete_ingestion_job(
    p_job_id uuid,
    p_worker_id text,
    p_embedding_model text,
    p_embedding_dimensions integer,
    p_chunks jsonb
)
returns void
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
    if p_chunks is null
       or jsonb_typeof(p_chunks) <> 'array'
       or jsonb_array_length(p_chunks) = 0 then
        raise exception 'Completed ingestion must contain chunks'
            using errcode = '22023';
    end if;
    if char_length(btrim(p_embedding_model)) not between 1 and 200
       or p_embedding_dimensions <= 0 then
        raise exception 'Invalid embedding profile'
            using errcode = '22023';
    end if;

    select ingestion_jobs.*
    into selected_job
    from public.ingestion_jobs
    where ingestion_jobs.id = p_job_id
      and ingestion_jobs.status = 'running'
      and ingestion_jobs.claimed_by = p_worker_id
    for update;

    if not found then
        raise exception 'Ingestion lease is no longer owned by this worker'
            using errcode = 'P0002';
    end if;

    -- Upsert, never touches embedding (order-independent with vector write).
    insert into public.document_chunks (
        id,
        owner_id,
        notebook_id,
        document_id,
        chunk_index,
        content,
        token_count,
        metadata
    )
    select
        (chunk.value ->> 'id')::uuid,
        selected_job.owner_id,
        selected_job.notebook_id,
        selected_job.document_id,
        (chunk.value ->> 'chunk_index')::integer,
        chunk.value ->> 'content',
        (chunk.value ->> 'token_count')::integer,
        chunk.value -> 'metadata'
    from jsonb_array_elements(p_chunks) as chunk(value)
    on conflict (id) do update
    set
        owner_id = excluded.owner_id,
        notebook_id = excluded.notebook_id,
        document_id = excluded.document_id,
        chunk_index = excluded.chunk_index,
        content = excluded.content,
        token_count = excluded.token_count,
        metadata = excluded.metadata;

    -- Drop stale chunks from a previous attempt.
    delete from public.document_chunks
    where document_chunks.document_id = selected_job.document_id
      and document_chunks.id not in (
          select (chunk.value ->> 'id')::uuid
          from jsonb_array_elements(p_chunks) as chunk(value)
      );

    update public.ingestion_jobs
    set
        status = 'succeeded',
        embedding_model = btrim(p_embedding_model),
        embedding_dimensions = p_embedding_dimensions,
        completed_at = now(),
        error_message = null,
        claimed_by = null,
        lease_expires_at = null
    where ingestion_jobs.id = selected_job.id;

    update public.documents
    set
        status = 'ready',
        error_message = null
    where documents.id = selected_job.document_id
      and documents.notebook_id = selected_job.notebook_id
      and documents.owner_id = selected_job.owner_id;
end;
$$;

revoke all on function public.complete_ingestion_job(
    uuid, text, text, integer, jsonb
) from public, anon, authenticated;
grant execute on function public.complete_ingestion_job(
    uuid, text, text, integer, jsonb
) to service_role;

create function public.fail_ingestion_job(
    p_job_id uuid,
    p_worker_id text,
    p_error_message text
)
returns void
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
      and ingestion_jobs.claimed_by = p_worker_id
    for update;

    if not found then
        raise exception 'Ingestion lease is no longer owned by this worker'
            using errcode = 'P0002';
    end if;

    update public.ingestion_jobs
    set
        status = 'failed',
        completed_at = now(),
        error_message = btrim(p_error_message),
        claimed_by = null,
        lease_expires_at = null
    where ingestion_jobs.id = selected_job.id;

    update public.documents
    set
        status = 'failed',
        error_message = btrim(p_error_message)
    where documents.id = selected_job.document_id
      and documents.notebook_id = selected_job.notebook_id
      and documents.owner_id = selected_job.owner_id;
end;
$$;

revoke all on function public.fail_ingestion_job(uuid, text, text)
from public, anon, authenticated;
grant execute on function public.fail_ingestion_job(uuid, text, text)
to service_role;

create function public.soft_delete_document(
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

    -- Stop any in-flight ingestion so it doesn't keep embedding a document
    -- the owner just archived.
    update public.ingestion_jobs
    set
        status = 'cancelled',
        completed_at = now(),
        error_message = 'Document was archived (soft-deleted)',
        claimed_by = null,
        lease_expires_at = null
    where ingestion_jobs.document_id = selected_document.id
      and ingestion_jobs.notebook_id = selected_document.notebook_id
      and ingestion_jobs.owner_id = selected_document.owner_id
      and ingestion_jobs.status in ('pending', 'running');

    -- True soft delete: only flip is_active, keep status/error_message,
    -- storage object and vectors untouched so old citations still resolve.
    update public.documents
    set is_active = false
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
