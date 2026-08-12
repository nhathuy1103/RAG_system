-- !! DESTRUCTIVE !! Drops and rebuilds every app table. Does not touch
-- auth.users or Storage files. No undo - back up first if unsure.

-- Storage tables cannot be dropped through SQL. Existing files become
-- unreferenced after this rebuild and must be reviewed separately.

drop policy if exists documents_storage_insert_own on storage.objects;
drop policy if exists documents_storage_select_own on storage.objects;
drop policy if exists documents_storage_delete_own on storage.objects;
drop policy if exists enterprise_source_storage_insert on storage.objects;
drop policy if exists enterprise_source_storage_select on storage.objects;
drop policy if exists enterprise_source_storage_delete on storage.objects;

drop trigger if exists auth_users_enforce_enterprise_email_domain on auth.users;
drop trigger if exists on_auth_user_created on auth.users;

-- Drop the additive Enterprise model before its legacy lineage targets.  The
-- CASCADE clauses also remove functions, policies and triggers whose signatures
-- depend on these composite table types; migrations 17-23 recreate them below.
drop table if exists public.enterprise_allowed_email_domains cascade;
drop table if exists public.answer_feedback cascade;
drop table if exists public.answer_reports cascade;
drop table if exists public.enterprise_citations cascade;
drop table if exists public.enterprise_messages cascade;
drop table if exists public.enterprise_conversations cascade;
drop table if exists public.processing_errors cascade;
drop table if exists public.processing_stage_history cascade;
drop table if exists public.processing_jobs cascade;
drop table if exists public.knowledge_chunks cascade;
drop table if exists public.audit_logs cascade;
drop table if exists public.document_permissions cascade;
drop table if exists public.publications cascade;
drop table if exists public.document_reviews cascade;
drop table if exists public.document_version_status_history cascade;
drop table if exists public.document_versions cascade;
drop table if exists public.source_files cascade;
drop table if exists public.knowledge_documents cascade;
drop table if exists public.access_subjects cascade;
drop table if exists public.user_departments cascade;
drop table if exists public.departments cascade;
drop table if exists public.user_groups cascade;
drop table if exists public.groups cascade;
drop table if exists public.role_permissions cascade;
drop table if exists public.user_roles cascade;
drop table if exists public.functional_permissions cascade;
drop table if exists public.roles cascade;
drop table if exists public.user_profiles cascade;

drop table if exists public.structured_claim_audit cascade;
drop table if exists public.claim_relations cascade;
drop table if exists public.structured_claims cascade;
drop table if exists public.table_snapshots cascade;
drop table if exists public.knowledge_quality_audit cascade;
drop table if exists public.document_relations cascade;
drop table if exists public.message_citations cascade;
drop table if exists public.messages cascade;
drop table if exists public.conversations cascade;
drop table if exists public.document_chunks cascade;
drop table if exists public.ingestion_control cascade;
drop table if exists public.ingestion_jobs cascade;
drop table if exists public.documents cascade;
drop table if exists public.notebooks cascade;
drop table if exists public.profiles cascade;

-- This CASCADE also removes the current repair RPC when its enum-typed
-- signature exists. Older signature variants are dropped explicitly below.
drop type if exists public.ingestion_repair_issue_kind cascade;

drop function if exists public.set_notebooks_updated_at() cascade;
drop function if exists public.set_rag_record_updated_at() cascade;
drop function if exists public.handle_new_user() cascade;
drop function if exists public.current_profile_role() cascade;
drop function if exists public.custom_access_token_hook(jsonb) cascade;
drop function if exists public.enqueue_document_ingestion(
    uuid, uuid, text, integer, jsonb
) cascade;
drop function if exists public.claim_ingestion_job(text, integer) cascade;
drop function if exists public.begin_ingestion_maintenance(
    text, integer, text
) cascade;
drop function if exists public.renew_ingestion_maintenance(
    uuid, integer
) cascade;
drop function if exists public.end_ingestion_maintenance(uuid) cascade;
drop function if exists public.renew_ingestion_job_lease(
    uuid, text, integer
) cascade;
drop function if exists public.renew_ingestion_job_lease(
    uuid, text, uuid, integer
) cascade;
drop function if exists public.complete_ingestion_job(
    uuid, text, text, integer, jsonb
) cascade;
drop function if exists public.complete_ingestion_job(
    uuid, text, uuid, text, integer, jsonb, text, text, text, jsonb, jsonb
) cascade;
drop function if exists public.complete_duplicate_ingestion_job(
    uuid, text, uuid, uuid, text, text, text, jsonb
) cascade;
drop function if exists public.fail_ingestion_job(
    uuid, text, text
) cascade;
drop function if exists public.fail_ingestion_job(
    uuid, text, uuid, text
) cascade;
drop function if exists public.soft_delete_document(uuid, uuid) cascade;
drop function if exists public.resolve_document_relation(
    uuid, uuid, text, text
) cascade;
drop function if exists public.resolve_document_relation(
    uuid, uuid, text, timestamptz, text
) cascade;
drop function if exists public.revert_document_relation_resolution(
    uuid, uuid, timestamptz, text
) cascade;
drop function if exists public.requeue_document_ingestion_repair(
    uuid, uuid, uuid, text
) cascade;
drop function if exists public.requeue_document_ingestion_repair(
    uuid, uuid, uuid, uuid, timestamptz, text
) cascade;
drop function if exists public.guard_authenticated_document_write() cascade;
drop function if exists public.knowledge_exact_chunk_group_id(
    uuid, uuid, text, text
) cascade;
drop function if exists public.prevent_knowledge_quality_audit_mutation() cascade;
drop function if exists public.prevent_structured_claim_audit_mutation() cascade;
drop function if exists public.replace_structured_facts_for_document(
    uuid, uuid, text, jsonb, jsonb, jsonb
) cascade;
drop function if exists public.resolve_structured_claim_relation(
    uuid, uuid, text, timestamptz, text
) cascade;
drop function if exists public.prepare_document_deletion(uuid, uuid) cascade;
-- Avoid naming the vector type before migration 01 has installed its
-- extension. Any existing overload necessarily has a resolvable signature.
do $reset$
declare
    function_signature regprocedure;
begin
    for function_signature in
        select procedures.oid::regprocedure
        from pg_catalog.pg_proc as procedures
        join pg_catalog.pg_namespace as namespaces
          on namespaces.oid = procedures.pronamespace
        where namespaces.nspname = 'public'
          and procedures.proname = 'match_document_chunks'
    loop
        execute pg_catalog.format(
            'drop function %s cascade',
            function_signature
        );
    end loop;
end;
$reset$;
drop function if exists public.admin_user_count() cascade;
drop function if exists public.admin_daily_auth_events(integer) cascade;
drop function if exists public.admin_recent_auth_events(integer) cascade;

-- Canonical migrations 01 through 33 are appended verbatim below.

-- Extensions required by the schema.
create extension if not exists pgcrypto;
create extension if not exists vector;

-- All application tables. Run 01_extensions.sql first.

-- notebooks
create table public.notebooks (
    id uuid primary key default gen_random_uuid(),
    owner_id uuid not null default auth.uid()
        references auth.users (id) on delete cascade,
    title text not null,
    description text not null default '',
    is_active boolean not null default true,
    created_at timestamptz not null default now(),
    updated_at timestamptz not null default now(),
    constraint notebooks_title_length
        check (char_length(btrim(title)) between 1 and 200),
    constraint notebooks_id_owner_key
        unique (id, owner_id)
);

comment on table public.notebooks is
    'User-owned collections of documents and conversations.';
comment on column public.notebooks.owner_id is
    'Supabase Auth user that exclusively owns this notebook.';
comment on column public.notebooks.description is
    'Optional user-provided description of the notebook.';
comment on column public.notebooks.is_active is
    'Soft-delete flag. False = archived by the owner; row and all child data are kept.';

create index notebooks_owner_updated_idx
    on public.notebooks (owner_id, updated_at desc, id);

-- documents
create table public.documents (
    id uuid primary key default gen_random_uuid(),
    owner_id uuid not null default auth.uid()
        references auth.users (id) on delete cascade,
    notebook_id uuid not null,
    original_filename text not null,
    storage_bucket text not null default 'documents',
    storage_object_path text not null,
    mime_type text not null,
    size_bytes bigint not null,
    content_hash text,
    status text not null default 'uploading',
    error_message text,
    is_active boolean not null default true,
    created_at timestamptz not null default now(),
    updated_at timestamptz not null default now(),
    constraint documents_notebook_owner_fk
        foreign key (notebook_id, owner_id)
        references public.notebooks (id, owner_id)
        on delete cascade,
    constraint documents_id_notebook_owner_key
        unique (id, notebook_id, owner_id),
    constraint documents_storage_object_key
        unique (storage_bucket, storage_object_path),
    constraint documents_filename_length
        check (char_length(btrim(original_filename)) between 1 and 255),
    constraint documents_storage_bucket
        check (storage_bucket = 'documents'),
    constraint documents_storage_path
        check (
            storage_object_path like
                owner_id::text || '/' ||
                notebook_id::text || '/' ||
                id::text || '/%'
        ),
    constraint documents_mime_type
        check (
            mime_type in (
                'application/pdf',
                'application/vnd.openxmlformats-officedocument.wordprocessingml.document',
                'application/vnd.openxmlformats-officedocument.presentationml.presentation',
                'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
                'text/csv',
                'text/markdown',
                'text/html',
                'text/plain'
            )
        ),
    -- 10 MiB, matches MAX_FILE_SIZE_BYTES and Storage bucket limit.
    constraint documents_size
        check (size_bytes between 1 and 10485760),
    constraint documents_content_hash
        check (content_hash is null or content_hash ~ '^[0-9a-f]{64}$'),
    constraint documents_status
        check (status in ('uploading', 'uploaded', 'processing', 'ready', 'failed')),
    constraint documents_error_message
        check (error_message is null or char_length(btrim(error_message)) > 0)
);

comment on table public.documents is
    'Metadata for immutable files uploaded to a notebook; file bytes live in Supabase Storage.';
comment on column public.documents.content_hash is
    'Lowercase SHA-256 used to detect duplicate content without rejecting it.';
comment on column public.documents.storage_object_path is
    'Object key: owner_id/notebook_id/document_id/sanitized_filename.';
comment on column public.documents.is_active is
    'Soft-delete flag. False = archived by the owner; storage object, vectors and row are kept.';

create index documents_owner_notebook_updated_idx
    on public.documents (owner_id, notebook_id, updated_at desc, id);
create index documents_owner_content_hash_idx
    on public.documents (owner_id, content_hash)
    where content_hash is not null;

-- ingestion_jobs
create table public.ingestion_jobs (
    id uuid primary key default gen_random_uuid(),
    owner_id uuid not null default auth.uid()
        references auth.users (id) on delete cascade,
    notebook_id uuid not null,
    document_id uuid not null,
    attempt_number integer not null default 1,
    status text not null default 'pending',
    embedding_model text not null default 'text-embedding-3-small',
    embedding_dimensions integer not null default 1536,
    configuration jsonb not null default '{}'::jsonb,
    error_message text,
    claimed_by text,
    lease_expires_at timestamptz,
    started_at timestamptz,
    completed_at timestamptz,
    created_at timestamptz not null default now(),
    updated_at timestamptz not null default now(),
    constraint ingestion_jobs_document_owner_fk
        foreign key (document_id, notebook_id, owner_id)
        references public.documents (id, notebook_id, owner_id)
        on delete cascade,
    constraint ingestion_jobs_attempt
        check (attempt_number > 0),
    constraint ingestion_jobs_status
        check (status in ('pending', 'running', 'succeeded', 'failed', 'cancelled')),
    constraint ingestion_jobs_embedding_model
        check (char_length(btrim(embedding_model)) between 1 and 200),
    constraint ingestion_jobs_embedding_dimensions
        check (embedding_dimensions > 0),
    constraint ingestion_jobs_configuration
        check (jsonb_typeof(configuration) = 'object'),
    constraint ingestion_jobs_error_message
        check (error_message is null or char_length(btrim(error_message)) > 0),
    constraint ingestion_jobs_attempt_key
        unique (document_id, attempt_number),
    constraint ingestion_jobs_claim
        check (
            (status = 'running' and claimed_by is not null and lease_expires_at is not null)
            or
            (status <> 'running' and claimed_by is null and lease_expires_at is null)
        )
);

comment on table public.ingestion_jobs is
    'Retryable attempts that parse, chunk, embed and index one uploaded document.';

create unique index ingestion_jobs_one_active_per_document_idx
    on public.ingestion_jobs (document_id)
    where status in ('pending', 'running');
create index ingestion_jobs_owner_notebook_created_idx
    on public.ingestion_jobs (owner_id, notebook_id, created_at desc, id);
create index ingestion_jobs_claimable_idx
    on public.ingestion_jobs (created_at, id)
    where status in ('pending', 'running');

-- document_chunks
create table public.document_chunks (
    id uuid primary key default gen_random_uuid(),
    owner_id uuid not null default auth.uid()
        references auth.users (id) on delete cascade,
    notebook_id uuid not null,
    document_id uuid not null,
    chunk_index integer not null,
    content text not null,
    token_count integer not null,
    metadata jsonb not null default '{}'::jsonb,
    embedding vector(1536),
    created_at timestamptz not null default now(),
    constraint document_chunks_document_owner_fk
        foreign key (document_id, notebook_id, owner_id)
        references public.documents (id, notebook_id, owner_id)
        on delete cascade,
    constraint document_chunks_id_document_notebook_owner_key
        unique (id, document_id, notebook_id, owner_id),
    constraint document_chunks_document_index_key
        unique (document_id, chunk_index),
    constraint document_chunks_index
        check (chunk_index >= 0),
    constraint document_chunks_content
        check (char_length(btrim(content)) > 0),
    constraint document_chunks_token_count
        check (token_count > 0),
    constraint document_chunks_metadata
        check (jsonb_typeof(metadata) = 'object')
);

comment on table public.document_chunks is
    'Canonical chunk text, metadata and embedding vector (pgvector).';
comment on column public.document_chunks.embedding is
    'text-embedding-3-small vector, 1536 dims. Null until the ingestion worker embeds this chunk.';

create index document_chunks_owner_notebook_document_idx
    on public.document_chunks (owner_id, notebook_id, document_id, chunk_index);

-- HNSW index, cosine distance.
create index document_chunks_embedding_hnsw_idx
    on public.document_chunks
    using hnsw (embedding vector_cosine_ops);

-- conversations
create table public.conversations (
    id uuid primary key default gen_random_uuid(),
    owner_id uuid not null default auth.uid()
        references auth.users (id) on delete cascade,
    notebook_id uuid not null,
    title text not null default 'New chat',
    created_at timestamptz not null default now(),
    updated_at timestamptz not null default now(),
    constraint conversations_notebook_owner_fk
        foreign key (notebook_id, owner_id)
        references public.notebooks (id, owner_id)
        on delete cascade,
    constraint conversations_id_notebook_owner_key
        unique (id, notebook_id, owner_id),
    constraint conversations_title_length
        check (char_length(btrim(title)) between 1 and 200)
);

comment on table public.conversations is
    'Independent chat sessions scoped to exactly one user-owned notebook.';

create index conversations_owner_notebook_updated_idx
    on public.conversations (owner_id, notebook_id, updated_at desc, id);

-- messages
create table public.messages (
    id uuid primary key default gen_random_uuid(),
    owner_id uuid not null default auth.uid()
        references auth.users (id) on delete cascade,
    notebook_id uuid not null,
    conversation_id uuid not null,
    role text not null,
    content text not null default '',
    status text not null default 'completed',
    model text,
    input_tokens integer,
    output_tokens integer,
    error_message text,
    created_at timestamptz not null default now(),
    updated_at timestamptz not null default now(),
    constraint messages_conversation_owner_fk
        foreign key (conversation_id, notebook_id, owner_id)
        references public.conversations (id, notebook_id, owner_id)
        on delete cascade,
    constraint messages_id_notebook_owner_key
        unique (id, notebook_id, owner_id),
    constraint messages_role
        check (role in ('user', 'assistant')),
    constraint messages_content
        check (role = 'assistant' or char_length(btrim(content)) > 0),
    constraint messages_status
        check (status in ('pending', 'completed', 'failed')),
    constraint messages_model
        check (model is null or char_length(btrim(model)) between 1 and 200),
    constraint messages_input_tokens
        check (input_tokens is null or input_tokens >= 0),
    constraint messages_output_tokens
        check (output_tokens is null or output_tokens >= 0),
    constraint messages_error_message
        check (error_message is null or char_length(btrim(error_message)) > 0)
);

comment on table public.messages is
    'User prompts and assistant responses ordered within a conversation by created_at and id.';

create index messages_owner_conversation_created_idx
    on public.messages (owner_id, conversation_id, created_at, id);

-- message_citations
create table public.message_citations (
    id uuid primary key default gen_random_uuid(),
    owner_id uuid not null default auth.uid()
        references auth.users (id) on delete cascade,
    notebook_id uuid not null,
    message_id uuid not null,
    document_id uuid not null,
    chunk_id uuid not null,
    ordinal integer not null,
    quote text not null,
    retrieval_score double precision,
    created_at timestamptz not null default now(),
    constraint message_citations_message_owner_fk
        foreign key (message_id, notebook_id, owner_id)
        references public.messages (id, notebook_id, owner_id)
        on delete cascade,
    constraint message_citations_chunk_owner_fk
        foreign key (chunk_id, document_id, notebook_id, owner_id)
        references public.document_chunks (id, document_id, notebook_id, owner_id)
        on delete cascade,
    constraint message_citations_ordinal
        check (ordinal > 0),
    constraint message_citations_quote
        check (char_length(btrim(quote)) > 0),
    constraint message_citations_message_ordinal_key
        unique (message_id, ordinal),
    constraint message_citations_message_chunk_key
        unique (message_id, chunk_id)
);

comment on table public.message_citations is
    'Ordered evidence snapshots linking an assistant response to canonical document chunks.';

create index message_citations_owner_message_ordinal_idx
    on public.message_citations (owner_id, message_id, ordinal);
create index message_citations_chunk_idx
    on public.message_citations (chunk_id);

-- profiles
create table public.profiles (
    id uuid primary key
        references auth.users (id) on delete cascade,
    display_name text,
    avatar_url text,
    role text not null default 'user',
    created_at timestamptz not null default now(),
    updated_at timestamptz not null default now(),
    constraint profiles_role
        check (role in ('user', 'admin')),
    constraint profiles_display_name_length
        check (display_name is null or char_length(btrim(display_name)) between 1 and 200)
);

comment on table public.profiles is
    'App-owned 1:1 extension of auth.users - display name, avatar, admin role.';
comment on column public.profiles.role is
    'Read by the Custom Access Token Hook (see 03_functions_triggers.sql) to inject the user_role JWT claim.';

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

-- Grants + RLS for every table. Run after 02_tables.sql and 03_functions_triggers.sql.

-- notebooks
revoke all on table public.notebooks from anon;
revoke all on table public.notebooks from authenticated;
grant select, insert, update, delete on table public.notebooks to authenticated;
grant all privileges on table public.notebooks to service_role;

alter table public.notebooks enable row level security;
alter table public.notebooks force row level security;

create policy notebooks_select_own on public.notebooks for select to authenticated
    using ((select auth.uid()) = owner_id);
create policy notebooks_insert_own on public.notebooks for insert to authenticated
    with check ((select auth.uid()) = owner_id);
create policy notebooks_update_own on public.notebooks for update to authenticated
    using ((select auth.uid()) = owner_id) with check ((select auth.uid()) = owner_id);
create policy notebooks_delete_own on public.notebooks for delete to authenticated
    using ((select auth.uid()) = owner_id);

-- documents / ingestion_jobs / document_chunks / conversations / messages / message_citations
revoke all privileges on table public.documents from anon;
revoke all privileges on table public.ingestion_jobs from anon;
revoke all privileges on table public.document_chunks from anon;
revoke all privileges on table public.conversations from anon;
revoke all privileges on table public.messages from anon;
revoke all privileges on table public.message_citations from anon;

revoke all privileges on table public.documents from authenticated;
revoke all privileges on table public.ingestion_jobs from authenticated;
revoke all privileges on table public.document_chunks from authenticated;
revoke all privileges on table public.conversations from authenticated;
revoke all privileges on table public.messages from authenticated;
revoke all privileges on table public.message_citations from authenticated;

grant select, insert, update, delete on table public.documents to authenticated;
-- ingestion_jobs: read-only, writes go through RPCs only.
grant select on table public.ingestion_jobs to authenticated;
grant select, insert, update, delete on table public.document_chunks to authenticated;
grant select, insert, update, delete on table public.conversations to authenticated;
grant select, insert, update, delete on table public.messages to authenticated;
grant select, insert, update, delete on table public.message_citations to authenticated;

grant all privileges on table public.documents to service_role;
grant all privileges on table public.ingestion_jobs to service_role;
grant all privileges on table public.document_chunks to service_role;
grant all privileges on table public.conversations to service_role;
grant all privileges on table public.messages to service_role;
grant all privileges on table public.message_citations to service_role;

alter table public.documents enable row level security;
alter table public.documents force row level security;
alter table public.ingestion_jobs enable row level security;
alter table public.ingestion_jobs force row level security;
alter table public.document_chunks enable row level security;
alter table public.document_chunks force row level security;
alter table public.conversations enable row level security;
alter table public.conversations force row level security;
alter table public.messages enable row level security;
alter table public.messages force row level security;
alter table public.message_citations enable row level security;
alter table public.message_citations force row level security;

create policy documents_select_own on public.documents for select to authenticated
    using ((select auth.uid()) = owner_id);
create policy documents_insert_own on public.documents for insert to authenticated
    with check ((select auth.uid()) = owner_id);
create policy documents_update_own on public.documents for update to authenticated
    using ((select auth.uid()) = owner_id) with check ((select auth.uid()) = owner_id);
create policy documents_delete_own on public.documents for delete to authenticated
    using ((select auth.uid()) = owner_id);

create policy ingestion_jobs_select_own on public.ingestion_jobs for select to authenticated
    using ((select auth.uid()) = owner_id);

create policy document_chunks_select_own on public.document_chunks for select to authenticated
    using ((select auth.uid()) = owner_id);
create policy document_chunks_insert_own on public.document_chunks for insert to authenticated
    with check ((select auth.uid()) = owner_id);
create policy document_chunks_update_own on public.document_chunks for update to authenticated
    using ((select auth.uid()) = owner_id) with check ((select auth.uid()) = owner_id);
create policy document_chunks_delete_own on public.document_chunks for delete to authenticated
    using ((select auth.uid()) = owner_id);

create policy conversations_select_own on public.conversations for select to authenticated
    using ((select auth.uid()) = owner_id);
create policy conversations_insert_own on public.conversations for insert to authenticated
    with check ((select auth.uid()) = owner_id);
create policy conversations_update_own on public.conversations for update to authenticated
    using ((select auth.uid()) = owner_id) with check ((select auth.uid()) = owner_id);
create policy conversations_delete_own on public.conversations for delete to authenticated
    using ((select auth.uid()) = owner_id);

create policy messages_select_own on public.messages for select to authenticated
    using ((select auth.uid()) = owner_id);
create policy messages_insert_own on public.messages for insert to authenticated
    with check ((select auth.uid()) = owner_id);
create policy messages_update_own on public.messages for update to authenticated
    using ((select auth.uid()) = owner_id) with check ((select auth.uid()) = owner_id);
create policy messages_delete_own on public.messages for delete to authenticated
    using ((select auth.uid()) = owner_id);

create policy message_citations_select_own on public.message_citations for select to authenticated
    using ((select auth.uid()) = owner_id);
create policy message_citations_insert_own on public.message_citations for insert to authenticated
    with check ((select auth.uid()) = owner_id);
create policy message_citations_update_own on public.message_citations for update to authenticated
    using ((select auth.uid()) = owner_id) with check ((select auth.uid()) = owner_id);
create policy message_citations_delete_own on public.message_citations for delete to authenticated
    using ((select auth.uid()) = owner_id);

-- profiles
revoke all on table public.profiles from anon;
revoke all on table public.profiles from authenticated;
-- No delete grant; insert allows GET /profile self-heal.
grant select, insert, update on table public.profiles to authenticated;
grant all privileges on table public.profiles to service_role;

alter table public.profiles enable row level security;
alter table public.profiles force row level security;

create policy profiles_select_own on public.profiles for select to authenticated
    using ((select auth.uid()) = id);
create policy profiles_insert_own on public.profiles for insert to authenticated
    -- Self-heal only creates 'user' rows.
    with check ((select auth.uid()) = id and role = 'user');
create policy profiles_update_own on public.profiles for update to authenticated
    using ((select auth.uid()) = id)
    -- Blocks self-promotion to admin.
    with check (
        (select auth.uid()) = id
        and role = public.current_profile_role()
    );

-- Storage bucket + policies for uploaded document bytes. Run after
-- 02_tables.sql (policies reference public.documents).

insert into storage.buckets (
    id,
    name,
    public,
    file_size_limit,
    allowed_mime_types
)
values (
    'documents',
    'documents',
    false,
    -- 10 MiB, matches documents_size and MAX_FILE_SIZE_BYTES.
    10485760,
    array[
        'application/pdf',
        'application/vnd.openxmlformats-officedocument.wordprocessingml.document',
        'application/vnd.openxmlformats-officedocument.presentationml.presentation',
        'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
        'text/csv',
        'text/markdown',
        'text/html',
        'text/plain'
    ]::text[]
)
on conflict (id) do update
set
    name = excluded.name,
    public = excluded.public,
    file_size_limit = excluded.file_size_limit,
    allowed_mime_types = excluded.allowed_mime_types;

create policy documents_storage_insert_own
on storage.objects
for insert
to authenticated
with check (
    bucket_id = 'documents'
    and (storage.foldername(name))[1] = (select auth.uid())::text
    and exists (
        select 1
        from public.documents
        where documents.owner_id = (select auth.uid())
          and documents.storage_bucket = storage.objects.bucket_id
          and documents.storage_object_path = storage.objects.name
    )
);

create policy documents_storage_select_own
on storage.objects
for select
to authenticated
using (
    bucket_id = 'documents'
    and (storage.foldername(name))[1] = (select auth.uid())::text
);

create policy documents_storage_delete_own
on storage.objects
for delete
to authenticated
using (
    bucket_id = 'documents'
    and (storage.foldername(name))[1] = (select auth.uid())::text
);

-- Dense retrieval RPC (pgvector). Run after 02_tables.sql.

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
        c.id as chunk_id,
        c.document_id,
        coalesce((c.metadata ->> 'document_version')::integer, 1) as document_version,
        c.chunk_index,
        c.content,
        c.metadata,
        1 - (c.embedding OPERATOR(public.<=>) p_query_embedding) as score
    from public.document_chunks c
    where c.owner_id = p_owner_id
      and (p_notebook_id is null or c.notebook_id = p_notebook_id)
      and c.embedding is not null
      and (p_document_ids is null or c.document_id = any(p_document_ids))
    order by c.embedding OPERATOR(public.<=>) p_query_embedding
    limit greatest(1, least(p_limit, 200));
end;
$$;

revoke all on function public.match_document_chunks(
    vector, uuid, uuid, uuid[], integer
)
from public, anon;
grant execute on function public.match_document_chunks(
    vector, uuid, uuid, uuid[], integer
)
to authenticated, service_role;

-- Admin dashboard read functions. service_role only - bypass RLS.

create function public.admin_user_count()
returns bigint
language sql
stable
security definer
set search_path = ''
as $$
    select count(*) from auth.users;
$$;

revoke all on function public.admin_user_count() from public, anon, authenticated;
grant execute on function public.admin_user_count() to service_role;

-- Verify action values first:
--   select payload->>'action', count(*) from auth.audit_log_entries group by 1 order by 2 desc;
create function public.admin_daily_auth_events(p_days integer default 30)
returns table (
    day date,
    signups bigint,
    logins bigint,
    logouts bigint
)
language sql
stable
security definer
set search_path = ''
as $$
    select
        (created_at at time zone 'utc')::date as day,
        count(*) filter (where payload ->> 'action' = 'user_signedup') as signups,
        count(*) filter (where payload ->> 'action' = 'login') as logins,
        count(*) filter (where payload ->> 'action' = 'logout') as logouts
    from auth.audit_log_entries
    where created_at >= (now() - make_interval(days => greatest(1, p_days)))
    group by 1
    order by 1;
$$;

revoke all on function public.admin_daily_auth_events(integer) from public, anon, authenticated;
grant execute on function public.admin_daily_auth_events(integer) to service_role;

-- Audit log list. email reads payload->>'actor_username'.
create function public.admin_recent_auth_events(p_limit integer default 50)
returns table (
    created_at timestamptz,
    action text,
    email text
)
language sql
stable
security definer
set search_path = ''
as $$
    select
        audit_log_entries.created_at,
        audit_log_entries.payload ->> 'action' as action,
        audit_log_entries.payload ->> 'actor_username' as email
    from auth.audit_log_entries
    order by audit_log_entries.created_at desc
    limit greatest(1, least(p_limit, 200));
$$;

revoke all on function public.admin_recent_auth_events(integer) from public, anon, authenticated;
grant execute on function public.admin_recent_auth_events(integer) to service_role;

-- Durable document identity, version/conflict review, and ingestion fencing.
-- Run after 07_admin_stats.sql.

-- ---------------------------------------------------------------------------
-- Document identity and version metadata
-- ---------------------------------------------------------------------------

alter table public.documents
    add column if not exists normalized_content_hash text,
    add column if not exists normalization_version text,
    add column if not exists loose_content_signature text,
    add column if not exists canonical_document_id uuid,
    add column if not exists version_group_id uuid not null default gen_random_uuid(),
    add column if not exists version_number integer not null default 1,
    add column if not exists effective_from date,
    add column if not exists effective_to date,
    add column if not exists supersedes_document_id uuid,
    add column if not exists is_current boolean not null default true,
    add column if not exists quality_status text not null default 'unreviewed',
    add column if not exists quality_metadata jsonb not null default '{}'::jsonb;

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

-- Each lease claim gets a generation token. A worker from an expired generation
-- can no longer renew, complete, fail, or compensate a newer generation.
alter table public.ingestion_jobs
    add column if not exists claim_token uuid;

update public.ingestion_jobs
set claim_token = gen_random_uuid()
where status = 'running' and claim_token is null;

alter table public.ingestion_jobs
    drop constraint ingestion_jobs_claim;

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
-- Relation and immutable decision-audit tables
-- ---------------------------------------------------------------------------

create table public.document_relations (
    id uuid primary key default gen_random_uuid(),
    owner_id uuid not null references auth.users (id) on delete cascade,
    notebook_id uuid not null,
    source_document_id uuid not null,
    target_document_id uuid not null,
    relation_type text not null,
    status text not null default 'pending',
    confidence double precision not null default 0,
    signals jsonb not null default '{}'::jsonb,
    reason text,
    detector_version text not null default 'knowledge-quality-v1',
    preferred_document_id uuid,
    resolved_by uuid references auth.users (id) on delete set null,
    resolved_at timestamptz,
    created_at timestamptz not null default now(),
    updated_at timestamptz not null default now(),
    constraint document_relations_source_owner_fk
        foreign key (source_document_id, notebook_id, owner_id)
        references public.documents (id, notebook_id, owner_id)
        on delete cascade,
    constraint document_relations_target_owner_fk
        foreign key (target_document_id, notebook_id, owner_id)
        references public.documents (id, notebook_id, owner_id)
        on delete cascade,
    constraint document_relations_preferred_owner_fk
        foreign key (preferred_document_id, notebook_id, owner_id)
        references public.documents (id, notebook_id, owner_id)
        on delete restrict,
    constraint document_relations_source_target
        check (source_document_id <> target_document_id),
    constraint document_relations_type
        check (
            relation_type in (
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
        ),
    constraint document_relations_status
        check (
            status in ('pending', 'auto_confirmed', 'confirmed', 'dismissed')
        ),
    constraint document_relations_confidence
        check (confidence between 0 and 1),
    constraint document_relations_signals
        check (jsonb_typeof(signals) = 'object'),
    constraint document_relations_reason
        check (reason is null or char_length(btrim(reason)) between 1 and 2000),
    constraint document_relations_detector_version
        check (char_length(btrim(detector_version)) between 1 and 100),
    constraint document_relations_resolution
        check (
            (
                status = 'pending'
                and resolved_by is null
                and resolved_at is null
            )
            or status = 'auto_confirmed'
            or (
                status in ('confirmed', 'dismissed')
                and resolved_by is not null
                and resolved_at is not null
            )
        ),
    constraint document_relations_source_target_detector_key
        unique (source_document_id, target_document_id, detector_version)
);

comment on table public.document_relations is
    'Detected and human-resolved exact, near-duplicate, version, and conflict relationships.';

create index document_relations_review_queue_idx
    on public.document_relations (
        owner_id,
        notebook_id,
        status,
        confidence desc,
        created_at desc
    );

create index document_relations_target_idx
    on public.document_relations (target_document_id, relation_type, status);

create table public.knowledge_quality_audit (
    id bigint generated always as identity primary key,
    owner_id uuid not null references auth.users (id) on delete cascade,
    notebook_id uuid not null,
    relation_id uuid references public.document_relations (id) on delete set null,
    actor_id uuid references auth.users (id) on delete set null,
    action text not null,
    reason text,
    before_state jsonb not null default '{}'::jsonb,
    after_state jsonb not null default '{}'::jsonb,
    created_at timestamptz not null default now(),
    constraint knowledge_quality_audit_notebook_owner_fk
        foreign key (notebook_id, owner_id)
        references public.notebooks (id, owner_id)
        on delete cascade,
    constraint knowledge_quality_audit_action
        check (char_length(btrim(action)) between 1 and 100),
    constraint knowledge_quality_audit_reason
        check (reason is null or char_length(btrim(reason)) between 1 and 2000),
    constraint knowledge_quality_audit_states
        check (
            jsonb_typeof(before_state) = 'object'
            and jsonb_typeof(after_state) = 'object'
        )
);

comment on table public.knowledge_quality_audit is
    'Append-only audit trail for automatic and human document-relation decisions.';

create index knowledge_quality_audit_owner_created_idx
    on public.knowledge_quality_audit (
        owner_id,
        notebook_id,
        created_at desc,
        id desc
    );

create function public.prevent_knowledge_quality_audit_mutation()
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

create trigger knowledge_quality_audit_immutable
before update or delete on public.knowledge_quality_audit
for each statement execute function public.prevent_knowledge_quality_audit_mutation();

-- Preserve old byte-identical uploads by turning every later copy into an
-- alias of the earliest active row before enforcing atomic uniqueness.
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
on conflict (source_document_id, target_document_id, detector_version)
do nothing;

create unique index documents_active_exact_content_key
    on public.documents (owner_id, notebook_id, content_hash)
    where (
        content_hash is not null
        and is_active
        and status <> 'failed'
        and canonical_document_id is null
    );

-- ---------------------------------------------------------------------------
-- Service-role ingestion functions with generation-token fencing
-- ---------------------------------------------------------------------------

drop function if exists public.claim_ingestion_job(text, integer);
drop function if exists public.renew_ingestion_job_lease(uuid, text, integer);
drop function if exists public.renew_ingestion_job_lease(
    uuid, text, uuid, integer
);
drop function if exists public.complete_ingestion_job(
    uuid, text, text, integer, jsonb
);
drop function if exists public.complete_ingestion_job(
    uuid, text, uuid, text, integer, jsonb, text, text, text, jsonb, jsonb
);
drop function if exists public.complete_duplicate_ingestion_job(
    uuid, text, uuid, uuid, text, text, text, jsonb
);
drop function if exists public.fail_ingestion_job(uuid, text, text);
drop function if exists public.fail_ingestion_job(uuid, text, uuid, text);

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

create function public.renew_ingestion_job_lease(
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

revoke all on function public.renew_ingestion_job_lease(
    uuid, text, uuid, integer
) from public, anon, authenticated;
grant execute on function public.renew_ingestion_job_lease(
    uuid, text, uuid, integer
) to service_role;

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
            or char_length(btrim(p_normalization_version)) not between 1 and 100
            or p_loose_content_signature is null
            or p_loose_content_signature !~ '^[0-9a-f]{16}$'
        )
    ) then
        raise exception 'Invalid document fingerprint'
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

    -- Upsert canonical chunks. The vector adapter has already persisted the
    -- same deterministic ids; this transaction fences metadata completion.
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

    delete from public.document_chunks
    where document_chunks.document_id = selected_job.document_id
      and document_chunks.id not in (
          select (chunk.value ->> 'id')::uuid
          from jsonb_array_elements(p_chunks) as chunk(value)
      );

    update public.documents
    set
        status = 'ready',
        error_message = null,
        normalized_content_hash = p_normalized_content_hash,
        normalization_version = p_normalization_version,
        loose_content_signature = p_loose_content_signature,
        quality_metadata = documents.quality_metadata || p_quality_metadata,
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
            greatest((relation.value ->> 'confidence')::double precision, 0),
            1
        ),
        coalesce(relation.value -> 'signals', '{}'::jsonb),
        nullif(btrim(relation.value ->> 'reason'), ''),
        coalesce(
            nullif(btrim(relation.value ->> 'detector_version'), ''),
            'knowledge-quality-v1'
        )
    from jsonb_array_elements(p_relations) as relation(value)
    join public.documents as target
      on target.id = (relation.value ->> 'target_document_id')::uuid
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
    on conflict (source_document_id, target_document_id, detector_version)
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
            when exists (
                select 1
                from public.document_relations
                where document_relations.source_document_id = selected_job.document_id
                  and document_relations.status = 'pending'
            ) then 'review_required'
            when p_normalized_content_hash is not null
                 and documents.quality_status in (
                     'unreviewed', 'clean', 'review_required'
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
        embedding_model = btrim(p_embedding_model),
        embedding_dimensions = p_embedding_dimensions,
        completed_at = now(),
        error_message = null,
        claimed_by = null,
        claim_token = null,
        lease_expires_at = null,
        updated_at = now()
    where ingestion_jobs.id = selected_job.id;
end;
$$;

revoke all on function public.complete_ingestion_job(
    uuid, text, uuid, text, integer, jsonb, text, text, text, jsonb, jsonb
) from public, anon, authenticated;
grant execute on function public.complete_ingestion_job(
    uuid, text, uuid, text, integer, jsonb, text, text, text, jsonb, jsonb
) to service_role;

create function public.complete_duplicate_ingestion_job(
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
    canonical_id uuid;
    created_relation public.document_relations;
begin
    if auth.role() <> 'service_role' then
        raise exception 'Service role is required'
            using errcode = '42501';
    end if;
    if p_normalized_content_hash is null
       or p_normalized_content_hash !~ '^[0-9a-f]{64}$'
       or p_normalization_version is null
       or char_length(btrim(p_normalization_version)) not between 1 and 100
       or p_loose_content_signature is null
       or p_loose_content_signature !~ '^[0-9a-f]{16}$'
       or p_quality_metadata is null
       or jsonb_typeof(p_quality_metadata) <> 'object' then
        raise exception 'Invalid document fingerprint'
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

    select documents.*
    into selected_canonical
    from public.documents
    where documents.id = p_canonical_document_id
      and documents.notebook_id = selected_job.notebook_id
      and documents.owner_id = selected_job.owner_id
      and documents.id <> selected_job.document_id
      and documents.is_active
      and documents.status = 'ready'
    for update;

    if not found then
        raise exception 'Canonical document is unavailable'
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
        for update;

        if not found then
            raise exception 'Canonical document root is unavailable'
                using errcode = 'P0002';
        end if;
    end if;

    delete from public.document_chunks
    where document_chunks.document_id = selected_job.document_id;

    update public.documents
    set
        status = 'ready',
        error_message = null,
        normalized_content_hash = p_normalized_content_hash,
        normalization_version = p_normalization_version,
        loose_content_signature = p_loose_content_signature,
        canonical_document_id = selected_canonical.id,
        version_group_id = selected_canonical.version_group_id,
        version_number = selected_canonical.version_number,
        is_current = false,
        quality_status = 'duplicate',
        quality_metadata = documents.quality_metadata
            || p_quality_metadata
            || jsonb_build_object('duplicate_of', selected_canonical.id),
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
            p_normalization_version
        ),
        'Strict normalized content is identical',
        'knowledge-quality-v1'
    )
    on conflict (source_document_id, target_document_id, detector_version)
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
        '{}'::jsonb,
        to_jsonb(created_relation)
    );

    update public.ingestion_jobs
    set
        status = 'succeeded',
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

create function public.fail_ingestion_job(
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

revoke all on function public.fail_ingestion_job(uuid, text, uuid, text)
from public, anon, authenticated;
grant execute on function public.fail_ingestion_job(uuid, text, uuid, text)
to service_role;

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

-- ---------------------------------------------------------------------------
-- Authenticated, audited relation resolution
-- ---------------------------------------------------------------------------

drop function if exists public.resolve_document_relation(
    uuid, uuid, text, text
);
drop function if exists public.resolve_document_relation(
    uuid, uuid, text, timestamptz, text
);

create function public.resolve_document_relation(
    p_relation_id uuid,
    p_notebook_id uuid,
    p_action text,
    p_expected_updated_at timestamptz,
    p_reason text default null
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
    if p_reason is not null
       and char_length(btrim(p_reason)) not between 1 and 2000 then
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

    select documents.*
    into source_document
    from public.documents
    where documents.id = selected_relation.source_document_id
      and documents.notebook_id = p_notebook_id
      and documents.owner_id = actor
    for update;

    select documents.*
    into target_document
    from public.documents
    where documents.id = selected_relation.target_document_id
      and documents.notebook_id = p_notebook_id
      and documents.owner_id = actor
    for update;

    if source_document.id is null or target_document.id is null then
        raise exception 'Related document was not found'
            using errcode = 'P0002';
    end if;

    before_state := jsonb_build_object(
        'relation', to_jsonb(selected_relation),
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
          and documents.version_group_id = target_document.version_group_id;

        update public.documents
        set
            is_current = false,
            quality_status = case
                when documents.id = target_document.id then 'superseded'
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
          and documents.version_group_id = target_document.version_group_id
          and documents.id <> source_document.id;

        update public.documents
        set
            canonical_document_id = null,
            version_group_id = target_document.version_group_id,
            version_number = next_version,
            supersedes_document_id = target_document.id,
            is_current = true,
            effective_from = coalesce(documents.effective_from, current_date),
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
        set quality_status = 'conflict', updated_at = now()
        where documents.id in (source_document.id, target_document.id);

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

    after_state := jsonb_build_object(
        'relation', to_jsonb(selected_relation),
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
-- Grants and RLS
-- ---------------------------------------------------------------------------

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

create policy document_relations_select_own
on public.document_relations for select to authenticated
using ((select auth.uid()) = owner_id);

create policy knowledge_quality_audit_select_own
on public.knowledge_quality_audit for select to authenticated
using ((select auth.uid()) = owner_id);

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

-- Pre-embedding chunk candidate lookup.
--
-- Strict SHA-256 identity is authoritative. The eight SimHash bands only
-- generate bounded candidates; application code verifies every fuzzy match
-- with lexical, containment and structured-claim checks. Eight 8-bit bands
-- keep fuzzy recall useful while fuzzy probes remain bounded by the worker.

create index if not exists document_chunks_simhash_band_1_idx
    on public.document_chunks (
        owner_id,
        notebook_id,
        normalization_version,
        (substr(loose_content_signature, 1, 2))
    )
    where embedding is not null;

create index if not exists document_chunks_simhash_band_2_idx
    on public.document_chunks (
        owner_id,
        notebook_id,
        normalization_version,
        (substr(loose_content_signature, 3, 2))
    )
    where embedding is not null;

create index if not exists document_chunks_simhash_band_3_idx
    on public.document_chunks (
        owner_id,
        notebook_id,
        normalization_version,
        (substr(loose_content_signature, 5, 2))
    )
    where embedding is not null;

create index if not exists document_chunks_simhash_band_4_idx
    on public.document_chunks (
        owner_id,
        notebook_id,
        normalization_version,
        (substr(loose_content_signature, 7, 2))
    )
    where embedding is not null;

create index if not exists document_chunks_simhash_band_5_idx
    on public.document_chunks (
        owner_id,
        notebook_id,
        normalization_version,
        (substr(loose_content_signature, 9, 2))
    )
    where embedding is not null;

create index if not exists document_chunks_simhash_band_6_idx
    on public.document_chunks (
        owner_id,
        notebook_id,
        normalization_version,
        (substr(loose_content_signature, 11, 2))
    )
    where embedding is not null;

create index if not exists document_chunks_simhash_band_7_idx
    on public.document_chunks (
        owner_id,
        notebook_id,
        normalization_version,
        (substr(loose_content_signature, 13, 2))
    )
    where embedding is not null;

create index if not exists document_chunks_simhash_band_8_idx
    on public.document_chunks (
        owner_id,
        notebook_id,
        normalization_version,
        (substr(loose_content_signature, 15, 2))
    )
    where embedding is not null;

drop function if exists public.find_chunk_dedup_candidates(
    uuid, uuid, uuid, text, jsonb, integer
);

create function public.find_chunk_dedup_candidates(
    p_owner_id uuid,
    p_notebook_id uuid,
    p_document_id uuid,
    p_embedding_model text,
    p_probes jsonb,
    p_limit_per_probe integer default 8
)
returns table (
    source_chunk_index integer,
    target_chunk_id uuid,
    target_document_id uuid,
    target_chunk_index integer,
    canonical_text text,
    normalized_content_hash text,
    normalization_version text,
    loose_content_signature text,
    embedding_text_checksum text,
    embedding text,
    embedding_model text,
    lsh_band_matches integer
)
language plpgsql
stable
security definer
set search_path = ''
as $$
begin
    if auth.role() <> 'service_role' then
        raise exception 'Service role is required'
            using errcode = '42501';
    end if;
    if p_owner_id is null
       or p_notebook_id is null
       or p_document_id is null
       or p_embedding_model is null
       or char_length(btrim(p_embedding_model)) not between 1 and 200 then
        raise exception 'Invalid chunk candidate scope or embedding model'
            using errcode = '22023';
    end if;
    if p_limit_per_probe is null
       or p_limit_per_probe < 1
       or p_limit_per_probe > 50 then
        raise exception 'Chunk candidate limit must be between 1 and 50'
            using errcode = '22023';
    end if;
    if p_probes is null
       or jsonb_typeof(p_probes) <> 'array'
       or jsonb_array_length(p_probes) = 0
       or jsonb_array_length(p_probes) > 128 then
        raise exception 'Chunk probes must contain between 1 and 128 items'
            using errcode = '22023';
    end if;
    if exists (
        select 1
        from jsonb_array_elements(p_probes) as probe(value)
        where jsonb_typeof(probe.value) <> 'object'
           or probe.value ->> 'chunk_index' is null
           or probe.value ->> 'chunk_index' !~ '^[0-9]+$'
           or probe.value ->> 'normalized_content_hash' is null
           or probe.value ->> 'normalized_content_hash'
                !~ '^[0-9a-f]{64}$'
           or probe.value ->> 'normalization_version' is null
           or char_length(
                btrim(probe.value ->> 'normalization_version')
            ) not between 1 and 100
           or probe.value ->> 'loose_content_signature' is null
           or probe.value ->> 'loose_content_signature'
                !~ '^[0-9a-f]{16}$'
           or probe.value -> 'include_fuzzy' is null
           or jsonb_typeof(probe.value -> 'include_fuzzy') <> 'boolean'
    ) then
        raise exception 'A chunk probe has an invalid fingerprint payload'
            using errcode = '22023';
    end if;

    return query
    select
        (probe.value ->> 'chunk_index')::integer,
        candidate.target_chunk_id,
        candidate.target_document_id,
        candidate.target_chunk_index,
        candidate.canonical_text,
        candidate.normalized_content_hash,
        candidate.normalization_version,
        candidate.loose_content_signature,
        candidate.embedding_text_checksum,
        candidate.embedding,
        candidate.embedding_model,
        candidate.lsh_band_matches
    from jsonb_array_elements(p_probes) as probe(value)
    cross join lateral (
        select
            chunks.id as target_chunk_id,
            chunks.document_id as target_document_id,
            chunks.chunk_index as target_chunk_index,
            coalesce(
                nullif(chunks.metadata ->> 'canonical_text', ''),
                chunks.content
            ) as canonical_text,
            chunks.normalized_content_hash,
            chunks.normalization_version,
            chunks.loose_content_signature,
            nullif(
                chunks.metadata ->> 'embedding_text_checksum',
                ''
            ) as embedding_text_checksum,
            chunks.embedding::text as embedding,
            latest_job.embedding_model,
            (
                case
                    when substr(chunks.loose_content_signature, 1, 2)
                        = substr(
                            probe.value ->> 'loose_content_signature',
                            1,
                            2
                        )
                    then 1 else 0
                end
                + case
                    when substr(chunks.loose_content_signature, 3, 2)
                        = substr(
                            probe.value ->> 'loose_content_signature',
                            3,
                            2
                        )
                    then 1 else 0
                end
                + case
                    when substr(chunks.loose_content_signature, 5, 2)
                        = substr(
                            probe.value ->> 'loose_content_signature',
                            5,
                            2
                        )
                    then 1 else 0
                end
                + case
                    when substr(chunks.loose_content_signature, 7, 2)
                        = substr(
                            probe.value ->> 'loose_content_signature',
                            7,
                            2
                        )
                    then 1 else 0
                end
                + case
                    when substr(chunks.loose_content_signature, 9, 2)
                        = substr(
                            probe.value ->> 'loose_content_signature',
                            9,
                            2
                        )
                    then 1 else 0
                end
                + case
                    when substr(chunks.loose_content_signature, 11, 2)
                        = substr(
                            probe.value ->> 'loose_content_signature',
                            11,
                            2
                        )
                    then 1 else 0
                end
                + case
                    when substr(chunks.loose_content_signature, 13, 2)
                        = substr(
                            probe.value ->> 'loose_content_signature',
                            13,
                            2
                        )
                    then 1 else 0
                end
                + case
                    when substr(chunks.loose_content_signature, 15, 2)
                        = substr(
                            probe.value ->> 'loose_content_signature',
                            15,
                            2
                        )
                    then 1 else 0
                end
            )::integer as lsh_band_matches
        from public.document_chunks as chunks
        join public.documents as documents
          on documents.id = chunks.document_id
         and documents.owner_id = chunks.owner_id
         and documents.notebook_id = chunks.notebook_id
        join lateral (
            select
                jobs.embedding_model,
                jobs.embedding_dimensions
            from public.ingestion_jobs as jobs
            where jobs.document_id = chunks.document_id
              and jobs.owner_id = chunks.owner_id
              and jobs.notebook_id = chunks.notebook_id
              and jobs.status = 'succeeded'
              and jobs.completion_disposition
                    is distinct from 'duplicate_suppressed'
            order by jobs.attempt_number desc, jobs.id desc
            limit 1
        ) as latest_job
          on latest_job.embedding_model = btrim(p_embedding_model)
         and public.vector_dims(chunks.embedding)
                = latest_job.embedding_dimensions
        where chunks.owner_id = p_owner_id
          and chunks.notebook_id = p_notebook_id
          and chunks.document_id <> p_document_id
          and chunks.normalization_version
                = btrim(probe.value ->> 'normalization_version')
          and chunks.embedding is not null
          and documents.status = 'ready'
          and documents.is_active
          and documents.is_current
          and documents.canonical_document_id is null
          and documents.quality_status not in ('duplicate', 'superseded')
          and (
              chunks.normalized_content_hash
                = probe.value ->> 'normalized_content_hash'
              or (
                  (probe.value ->> 'include_fuzzy')::boolean
                  and (
                      substr(chunks.loose_content_signature, 1, 2)
                        = substr(
                            probe.value ->> 'loose_content_signature',
                            1,
                            2
                        )
                      or substr(chunks.loose_content_signature, 3, 2)
                        = substr(
                            probe.value ->> 'loose_content_signature',
                            3,
                            2
                        )
                      or substr(chunks.loose_content_signature, 5, 2)
                        = substr(
                            probe.value ->> 'loose_content_signature',
                            5,
                            2
                        )
                      or substr(chunks.loose_content_signature, 7, 2)
                        = substr(
                            probe.value ->> 'loose_content_signature',
                            7,
                            2
                        )
                      or substr(chunks.loose_content_signature, 9, 2)
                        = substr(
                            probe.value ->> 'loose_content_signature',
                            9,
                            2
                        )
                      or substr(chunks.loose_content_signature, 11, 2)
                        = substr(
                            probe.value ->> 'loose_content_signature',
                            11,
                            2
                        )
                      or substr(chunks.loose_content_signature, 13, 2)
                        = substr(
                            probe.value ->> 'loose_content_signature',
                            13,
                            2
                        )
                      or substr(chunks.loose_content_signature, 15, 2)
                        = substr(
                            probe.value ->> 'loose_content_signature',
                            15,
                            2
                        )
                  )
              )
          )
        order by
            (
                chunks.normalized_content_hash
                    = probe.value ->> 'normalized_content_hash'
            ) desc,
            lsh_band_matches desc,
            documents.created_at,
            chunks.chunk_index,
            chunks.id
        limit p_limit_per_probe
    ) as candidate;
end;
$$;

comment on function public.find_chunk_dedup_candidates(
    uuid, uuid, uuid, text, jsonb, integer
) is
    'Service-role bounded exact/SimHash-LSH chunk candidates before embedding.';

revoke all on function public.find_chunk_dedup_candidates(
    uuid, uuid, uuid, text, jsonb, integer
) from public, anon, authenticated;

grant execute on function public.find_chunk_dedup_candidates(
    uuid, uuid, uuid, text, jsonb, integer
) to service_role;

-- Context-weighted PostgreSQL full-text retrieval over canonical chunk content.
-- Run after 10_chunk_preembedding_dedup.sql.

-- Chunks indexed before contextual metadata existed still need a stable title.
-- Preserve every existing retrieval field and fill only a missing/blank title
-- from the authoritative documents row.
update public.document_chunks as chunks
set metadata = jsonb_set(
    chunks.metadata,
    '{retrieval_metadata}',
    jsonb_set(
        case
            when jsonb_typeof(chunks.metadata -> 'retrieval_metadata') = 'object'
            then chunks.metadata -> 'retrieval_metadata'
            else '{}'::jsonb
        end,
        '{title}',
        to_jsonb(
            coalesce(
                nullif(chunks.metadata #>> '{retrieval_metadata,title}', ''),
                nullif(chunks.metadata ->> 'title', ''),
                documents.original_filename
            )
        ),
        true
    ),
    true
)
from public.documents as documents
where documents.id = chunks.document_id
  and documents.owner_id = chunks.owner_id
  and documents.notebook_id = chunks.notebook_id
  and coalesce(
      chunks.metadata #>> '{retrieval_metadata,title}',
      chunks.metadata ->> 'title',
      ''
  ) = '';

alter table public.document_chunks
    add column if not exists search_vector tsvector
    generated always as (
        setweight(
            to_tsvector(
                'simple'::regconfig,
                coalesce(
                    metadata #>> '{retrieval_metadata,title}',
                    metadata ->> 'title',
                    ''
                )
            ),
            'A'
        )
        || setweight(
            to_tsvector(
                'simple'::regconfig,
                coalesce(
                    metadata #>> '{retrieval_metadata,section_title}',
                    metadata ->> 'section_title',
                    ''
                )
            ),
            'B'
        )
        || setweight(
            to_tsvector(
                'simple'::regconfig,
                coalesce(
                    metadata #>> '{retrieval_metadata,section_path}',
                    ''
                )
            ),
            'B'
        )
        || setweight(
            to_tsvector(
                'simple'::regconfig,
                coalesce(
                    metadata #>> '{retrieval_metadata,table_header}',
                    ''
                )
            ),
            'B'
        )
        || setweight(
            to_tsvector(
                'simple'::regconfig,
                coalesce(
                    metadata #>> '{retrieval_metadata,document_type}',
                    metadata ->> 'document_type',
                    ''
                )
            ),
            'C'
        )
        || setweight(
            to_tsvector(
                'simple'::regconfig,
                coalesce(
                    metadata #>> '{retrieval_metadata,content_kind}',
                    metadata ->> 'content_kind',
                    ''
                )
            ),
            'C'
        )
        || setweight(
            to_tsvector(
                'simple'::regconfig,
                coalesce(
                    metadata #>> '{retrieval_metadata,keyword_aliases}',
                    ''
                )
            ),
            'C'
        )
        || setweight(to_tsvector('simple'::regconfig, content), 'D')
    ) stored;

create index if not exists document_chunks_search_vector_idx
    on public.document_chunks using gin (search_vector);

create or replace function public.search_document_chunks_keyword(
    p_query text,
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
declare
    search_query tsquery;
begin
    if auth.role() <> 'service_role'
       and auth.uid() is distinct from p_owner_id then
        raise exception 'Cannot retrieve another owner''s document chunks'
            using errcode = '42501';
    end if;

    if p_query is null or btrim(p_query) = '' then
        return;
    end if;
    search_query := websearch_to_tsquery('simple'::regconfig, btrim(p_query));
    if numnode(search_query) = 0 then
        return;
    end if;

    return query
    select
        chunks.id,
        chunks.document_id,
        case
            when chunks.metadata ->> 'document_version' ~ '^[1-9][0-9]*$'
            then (chunks.metadata ->> 'document_version')::integer
            else 1
        end,
        chunks.chunk_index,
        chunks.content,
        chunks.metadata,
        chunks.normalized_content_hash,
        chunks.exact_duplicate_group_id,
        ts_rank_cd(chunks.search_vector, search_query, 32)::double precision
    from public.document_chunks as chunks
    where chunks.owner_id = p_owner_id
      and (p_notebook_id is null or chunks.notebook_id = p_notebook_id)
      and (p_document_ids is null or chunks.document_id = any(p_document_ids))
      and chunks.search_vector @@ search_query
    order by
        ts_rank_cd(chunks.search_vector, search_query, 32) desc,
        chunks.id
    limit greatest(1, least(coalesce(p_limit, 20), 200));
end;
$$;

revoke all on function public.search_document_chunks_keyword(
    text, uuid, uuid, uuid[], integer
) from public, anon;
grant execute on function public.search_document_chunks_keyword(
    text, uuid, uuid, uuid[], integer
) to authenticated, service_role;

-- Add validated LLM-generated chunk context to PostgreSQL full-text retrieval.
-- Run after 11_contextual_metadata_fts.sql.

drop index if exists public.document_chunks_search_vector_idx;

alter table public.document_chunks
    drop column if exists search_vector;

alter table public.document_chunks
    add column search_vector tsvector
    generated always as (
        setweight(
            to_tsvector(
                'simple'::regconfig,
                coalesce(
                    metadata #>> '{retrieval_metadata,title}',
                    metadata ->> 'title',
                    ''
                )
            ),
            'A'
        )
        || setweight(
            to_tsvector(
                'simple'::regconfig,
                coalesce(
                    metadata #>> '{retrieval_metadata,section_title}',
                    metadata ->> 'section_title',
                    ''
                )
            ),
            'B'
        )
        || setweight(
            to_tsvector(
                'simple'::regconfig,
                coalesce(
                    metadata #>> '{retrieval_metadata,section_path}',
                    ''
                )
            ),
            'B'
        )
        || setweight(
            to_tsvector(
                'simple'::regconfig,
                coalesce(
                    metadata #>> '{retrieval_metadata,table_header}',
                    ''
                )
            ),
            'B'
        )
        || setweight(
            to_tsvector(
                'simple'::regconfig,
                coalesce(
                    metadata #>> '{retrieval_metadata,contextual_summary}',
                    ''
                )
            ),
            'B'
        )
        || setweight(
            to_tsvector(
                'simple'::regconfig,
                coalesce(
                    metadata #>> '{retrieval_metadata,document_type}',
                    metadata ->> 'document_type',
                    ''
                )
            ),
            'C'
        )
        || setweight(
            to_tsvector(
                'simple'::regconfig,
                coalesce(
                    metadata #>> '{retrieval_metadata,content_kind}',
                    metadata ->> 'content_kind',
                    ''
                )
            ),
            'C'
        )
        || setweight(
            to_tsvector(
                'simple'::regconfig,
                coalesce(
                    metadata #>> '{retrieval_metadata,keyword_aliases}',
                    ''
                )
            ),
            'C'
        )
        || setweight(
            to_tsvector(
                'simple'::regconfig,
                coalesce(
                    metadata #>> '{retrieval_metadata,contextual_search_terms}',
                    ''
                )
            ),
            'C'
        )
        || setweight(to_tsvector('simple'::regconfig, content), 'D')
    ) stored;

create index document_chunks_search_vector_idx
    on public.document_chunks using gin (search_vector);

-- Scope-aware legal-template relation support.
-- Run after 12_llm_contextual_retrieval.sql.

alter table public.document_relations
    drop constraint document_relations_type;

alter table public.document_relations
    add constraint document_relations_type
        check (
            relation_type in (
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
        );

-- Migration 09 owns the fenced completion RPC. Patch its relation whitelist
-- in place so deployed databases keep the exact audited/fenced implementation.
do $$
declare
    completion_signature regprocedure := (
        'public.complete_ingestion_job('
        'uuid,text,uuid,text,integer,jsonb,text,text,text,jsonb,jsonb)'
    )::regprocedure;
    function_definition text;
    patched_definition text;
begin
    select pg_get_functiondef(completion_signature)
    into function_definition;

    if function_definition like '%''template_variant''%' then
        return;
    end if;

    patched_definition := regexp_replace(
        function_definition,
        '(''technical_duplicate''[[:space:]]*\))',
        E'''technical_duplicate'',\n          ''template_variant''\n      )',
        'g'
    );

    if patched_definition = function_definition then
        raise exception 'Could not extend complete_ingestion_job relation whitelist';
    end if;

    execute patched_definition;
end;
$$;

comment on constraint document_relations_type on public.document_relations is
    'Supported persisted relation taxonomy, including same-template/different-scope review.';

-- Remove only provably redundant chunk metadata.
-- Run after 13_template_scope_conflict.sql.

with compacted as (
    select
        chunks.id,
        chunks.metadata
            - pg_catalog.array_remove(
                array[
                    case
                        when chunks.metadata ->> 'canonical_text' = chunks.content
                        then 'canonical_text'
                    end,
                    case
                        when chunks.metadata -> 'provenance_metadata' = '{}'::jsonb
                        then 'provenance_metadata'
                    end,
                    case
                        when chunks.metadata -> 'authority_metadata' = '{}'::jsonb
                        then 'authority_metadata'
                    end
                ]::text[],
                null
            ) as metadata
    from public.document_chunks as chunks
    where chunks.metadata ->> 'canonical_text' = chunks.content
       or chunks.metadata -> 'provenance_metadata' = '{}'::jsonb
       or chunks.metadata -> 'authority_metadata' = '{}'::jsonb
)
update public.document_chunks as chunks
set metadata = compacted.metadata
from compacted
where chunks.id = compacted.id
  and chunks.metadata is distinct from compacted.metadata;

-- Persist and apply the measured pre-retrieval metadata filter contract.
-- Run after 14_compact_chunk_metadata.sql.

-- Backfill only values already present or deterministically encoded in a heading.
update public.document_chunks as chunks
set metadata = jsonb_set(
    chunks.metadata,
    '{retrieval_metadata}',
    coalesce(chunks.metadata -> 'retrieval_metadata', '{}'::jsonb)
    || jsonb_strip_nulls(jsonb_build_object(
        'document_type', lower(nullif(coalesce(
            chunks.metadata #>> '{retrieval_metadata,document_type}',
            chunks.metadata ->> 'document_type'
        ), '')),
        'content_kind', lower(nullif(coalesce(
            chunks.metadata #>> '{retrieval_metadata,content_kind}',
            chunks.metadata ->> 'content_kind'
        ), '')),
        'project_id', coalesce(
            chunks.metadata #>> '{retrieval_metadata,project_id}',
            chunks.metadata ->> 'project_id'
        ),
        'project_code', upper(nullif(coalesce(
            chunks.metadata #>> '{retrieval_metadata,project_code}',
            chunks.metadata ->> 'project_code',
            substring(
                coalesce(
                    chunks.metadata #>> '{retrieval_metadata,section_title}',
                    chunks.metadata ->> 'section_title',
                    ''
                )
                from '^\s*(P[0-9]{1,6})'
            )
        ), '')),
        'year', coalesce(
            chunks.metadata #>> '{retrieval_metadata,year}',
            chunks.metadata ->> 'year'
        ),
        'data_period', upper(nullif(coalesce(
            chunks.metadata #>> '{retrieval_metadata,data_period}',
            chunks.metadata ->> 'data_period'
        ), '')),
        'effective_status', case lower(nullif(coalesce(
            chunks.metadata #>> '{retrieval_metadata,effective_status}',
            chunks.metadata ->> 'effective_status'
        ), ''))
            when 'latest' then 'current'
            when 'active' then 'current'
            when 'effective' then 'current'
            else lower(nullif(coalesce(
                chunks.metadata #>> '{retrieval_metadata,effective_status}',
                chunks.metadata ->> 'effective_status'
            ), ''))
        end
    )),
    true
)
where jsonb_typeof(chunks.metadata) = 'object';

create index if not exists document_chunks_document_type_filter_idx
    on public.document_chunks (
        owner_id, notebook_id,
        (metadata #>> '{retrieval_metadata,document_type}')
    ) where metadata #>> '{retrieval_metadata,document_type}' is not null;
create index if not exists document_chunks_content_kind_filter_idx
    on public.document_chunks (
        owner_id, notebook_id,
        (metadata #>> '{retrieval_metadata,content_kind}')
    ) where metadata #>> '{retrieval_metadata,content_kind}' is not null;
create index if not exists document_chunks_project_id_filter_idx
    on public.document_chunks (
        owner_id, notebook_id,
        (metadata #>> '{retrieval_metadata,project_id}')
    ) where metadata #>> '{retrieval_metadata,project_id}' is not null;
create index if not exists document_chunks_project_code_filter_idx
    on public.document_chunks (
        owner_id, notebook_id,
        (metadata #>> '{retrieval_metadata,project_code}')
    ) where metadata #>> '{retrieval_metadata,project_code}' is not null;
create index if not exists document_chunks_year_filter_idx
    on public.document_chunks (
        owner_id, notebook_id,
        (metadata #>> '{retrieval_metadata,year}')
    ) where metadata #>> '{retrieval_metadata,year}' is not null;
create index if not exists document_chunks_data_period_filter_idx
    on public.document_chunks (
        owner_id, notebook_id,
        (metadata #>> '{retrieval_metadata,data_period}')
    ) where metadata #>> '{retrieval_metadata,data_period}' is not null;
create index if not exists document_chunks_effective_status_filter_idx
    on public.document_chunks (
        owner_id, notebook_id,
        (metadata #>> '{retrieval_metadata,effective_status}')
    ) where metadata #>> '{retrieval_metadata,effective_status}' is not null;

drop function if exists public.match_document_chunks(
    vector, uuid, uuid, uuid[], integer
);
drop function if exists public.match_document_chunks(
    vector, uuid, uuid, uuid[], integer, text, text, text, text, integer, text, text
);
create function public.match_document_chunks(
    p_query_embedding vector(1536),
    p_owner_id uuid,
    p_notebook_id uuid default null,
    p_document_ids uuid[] default null,
    p_limit integer default 20,
    p_document_type text default null,
    p_content_kind text default null,
    p_project_id text default null,
    p_project_code text default null,
    p_year integer default null,
    p_data_period text default null,
    p_effective_status text default null
)
returns table (
    chunk_id uuid, document_id uuid, document_version integer,
    chunk_index integer, content text, metadata jsonb,
    normalized_content_hash text, exact_duplicate_group_id uuid,
    score double precision
)
language plpgsql stable security definer set search_path = ''
as $$
begin
    if auth.role() <> 'service_role'
       and auth.uid() is distinct from p_owner_id then
        raise exception 'Cannot retrieve another owner''s document chunks'
            using errcode = '42501';
    end if;
    return query
    select chunks.id, chunks.document_id,
        case when chunks.metadata ->> 'document_version' ~ '^[1-9][0-9]*$'
             then (chunks.metadata ->> 'document_version')::integer else 1 end,
        chunks.chunk_index, chunks.content, chunks.metadata,
        chunks.normalized_content_hash, chunks.exact_duplicate_group_id,
        1 - (chunks.embedding OPERATOR(public.<=>) p_query_embedding)
    from public.document_chunks as chunks
    where chunks.owner_id = p_owner_id
      and (p_notebook_id is null or chunks.notebook_id = p_notebook_id)
      and (p_document_ids is null or chunks.document_id = any(p_document_ids))
      and chunks.embedding is not null
      and (p_document_type is null or chunks.metadata #>> '{retrieval_metadata,document_type}' = p_document_type)
      and (p_content_kind is null or chunks.metadata #>> '{retrieval_metadata,content_kind}' = p_content_kind)
      and (p_project_id is null or chunks.metadata #>> '{retrieval_metadata,project_id}' = p_project_id)
      and (p_project_code is null or chunks.metadata #>> '{retrieval_metadata,project_code}' = p_project_code)
      and (p_year is null or chunks.metadata #>> '{retrieval_metadata,year}' = p_year::text)
      and (p_data_period is null or chunks.metadata #>> '{retrieval_metadata,data_period}' = p_data_period)
      and (p_effective_status is null or chunks.metadata #>> '{retrieval_metadata,effective_status}' = p_effective_status)
    order by chunks.embedding OPERATOR(public.<=>) p_query_embedding
    limit greatest(1, least(coalesce(p_limit, 20), 200));
end;
$$;
revoke all on function public.match_document_chunks(
    vector, uuid, uuid, uuid[], integer, text, text, text, text, integer, text, text
) from public, anon;
grant execute on function public.match_document_chunks(
    vector, uuid, uuid, uuid[], integer, text, text, text, text, integer, text, text
) to authenticated, service_role;

drop function if exists public.search_document_chunks_keyword(
    text, uuid, uuid, uuid[], integer
);
drop function if exists public.search_document_chunks_keyword(
    text, uuid, uuid, uuid[], integer, text, text, text, text, integer, text, text
);
create function public.search_document_chunks_keyword(
    p_query text,
    p_owner_id uuid,
    p_notebook_id uuid default null,
    p_document_ids uuid[] default null,
    p_limit integer default 20,
    p_document_type text default null,
    p_content_kind text default null,
    p_project_id text default null,
    p_project_code text default null,
    p_year integer default null,
    p_data_period text default null,
    p_effective_status text default null
)
returns table (
    chunk_id uuid, document_id uuid, document_version integer,
    chunk_index integer, content text, metadata jsonb,
    normalized_content_hash text, exact_duplicate_group_id uuid,
    score double precision
)
language plpgsql stable security definer set search_path = ''
as $$
declare search_query tsquery;
begin
    if auth.role() <> 'service_role'
       and auth.uid() is distinct from p_owner_id then
        raise exception 'Cannot retrieve another owner''s document chunks'
            using errcode = '42501';
    end if;
    if p_query is null or btrim(p_query) = '' then return; end if;
    search_query := websearch_to_tsquery('simple'::regconfig, btrim(p_query));
    if numnode(search_query) = 0 then return; end if;
    return query
    select chunks.id, chunks.document_id,
        case when chunks.metadata ->> 'document_version' ~ '^[1-9][0-9]*$'
             then (chunks.metadata ->> 'document_version')::integer else 1 end,
        chunks.chunk_index, chunks.content, chunks.metadata,
        chunks.normalized_content_hash, chunks.exact_duplicate_group_id,
        ts_rank_cd(chunks.search_vector, search_query, 32)::double precision
    from public.document_chunks as chunks
    where chunks.owner_id = p_owner_id
      and (p_notebook_id is null or chunks.notebook_id = p_notebook_id)
      and (p_document_ids is null or chunks.document_id = any(p_document_ids))
      and (p_document_type is null or chunks.metadata #>> '{retrieval_metadata,document_type}' = p_document_type)
      and (p_content_kind is null or chunks.metadata #>> '{retrieval_metadata,content_kind}' = p_content_kind)
      and (p_project_id is null or chunks.metadata #>> '{retrieval_metadata,project_id}' = p_project_id)
      and (p_project_code is null or chunks.metadata #>> '{retrieval_metadata,project_code}' = p_project_code)
      and (p_year is null or chunks.metadata #>> '{retrieval_metadata,year}' = p_year::text)
      and (p_data_period is null or chunks.metadata #>> '{retrieval_metadata,data_period}' = p_data_period)
      and (p_effective_status is null or chunks.metadata #>> '{retrieval_metadata,effective_status}' = p_effective_status)
      and chunks.search_vector @@ search_query
    order by ts_rank_cd(chunks.search_vector, search_query, 32) desc, chunks.id
    limit greatest(1, least(coalesce(p_limit, 20), 200));
end;
$$;
revoke all on function public.search_document_chunks_keyword(
    text, uuid, uuid, uuid[], integer, text, text, text, text, integer, text, text
) from public, anon;
grant execute on function public.search_document_chunks_keyword(
    text, uuid, uuid, uuid[], integer, text, text, text, text, integer, text, text
) to authenticated, service_role;

-- Additive structured-fact persistence for row-level duplicate, version, and
-- conflict analysis. Run after 15_structured_retrieval_filters.sql.

-- ---------------------------------------------------------------------------
-- Extracted table snapshots
-- ---------------------------------------------------------------------------

create table public.table_snapshots (
    id uuid primary key default gen_random_uuid(),
    owner_id uuid not null references auth.users (id) on delete cascade,
    notebook_id uuid not null,
    document_id uuid not null,
    source_chunk_id uuid
        references public.document_chunks (id) on delete set null,
    snapshot_key text not null,
    input_content_hash text not null,
    schema_fingerprint text not null,
    template_fingerprint text,
    table_index integer not null,
    page_from integer,
    page_to integer,
    source_locator jsonb not null default '{}'::jsonb,
    normalized_schema jsonb not null default '{}'::jsonb,
    row_count integer not null default 0,
    column_count integer not null default 0,
    extractor_name text not null default 'structured-fact-analyzer',
    extractor_version text not null,
    publication_time timestamptz,
    effective_from timestamptz,
    effective_to timestamptz,
    observed_at timestamptz,
    ingested_at timestamptz not null default now(),
    source_publisher text,
    source_type text not null default 'unknown',
    authority_level integer,
    authority_metadata jsonb not null default '{}'::jsonb,
    warnings jsonb not null default '[]'::jsonb,
    extraction_confidence double precision not null default 0,
    created_at timestamptz not null default now(),
    updated_at timestamptz not null default now(),
    constraint table_snapshots_document_owner_fk
        foreign key (document_id, notebook_id, owner_id)
        references public.documents (id, notebook_id, owner_id)
        on delete cascade,
    constraint table_snapshots_id_document_notebook_owner_key
        unique (id, document_id, notebook_id, owner_id),
    constraint table_snapshots_id_notebook_owner_key
        unique (id, notebook_id, owner_id),
    constraint table_snapshots_extractor_key
        unique (
            document_id,
            snapshot_key,
            extractor_version,
            input_content_hash
        ),
    constraint table_snapshots_snapshot_key
        check (char_length(btrim(snapshot_key)) between 1 and 500),
    constraint table_snapshots_input_content_hash
        check (input_content_hash ~ '^[0-9a-f]{64}$'),
    constraint table_snapshots_schema_fingerprint
        check (schema_fingerprint ~ '^[0-9a-f]{64}$'),
    constraint table_snapshots_template_fingerprint
        check (
            template_fingerprint is null
            or template_fingerprint ~ '^[0-9a-f]{64}$'
        ),
    constraint table_snapshots_location
        check (
            table_index >= 0
            and (page_from is null or page_from > 0)
            and (page_to is null or page_to > 0)
            and (
                page_from is null
                or page_to is null
                or page_to >= page_from
            )
        ),
    constraint table_snapshots_provenance
        check (
            jsonb_typeof(source_locator) = 'object'
            and jsonb_typeof(normalized_schema) in ('object', 'array')
        ),
    constraint table_snapshots_shape
        check (row_count >= 0 and column_count >= 0),
    constraint table_snapshots_extractor
        check (
            char_length(btrim(extractor_name)) between 1 and 100
            and char_length(btrim(extractor_version)) between 1 and 100
        ),
    constraint table_snapshots_temporal_interval
        check (
            effective_from is null
            or effective_to is null
            or effective_to >= effective_from
        ),
    constraint table_snapshots_source
        check (
            char_length(btrim(source_type)) between 1 and 100
            and (
                source_publisher is null
                or char_length(btrim(source_publisher)) between 1 and 500
            )
            and (
                authority_level is null
                or authority_level between 0 and 100
            )
            and jsonb_typeof(authority_metadata) = 'object'
        ),
    constraint table_snapshots_warnings
        check (jsonb_typeof(warnings) = 'array'),
    constraint table_snapshots_confidence
        check (extraction_confidence between 0 and 1)
);

comment on table public.table_snapshots is
    'Versioned structured-table extractions with source, temporal, authority, and schema provenance.';
comment on column public.table_snapshots.snapshot_key is
    'Extractor-stable table identity within one document.';
comment on column public.table_snapshots.source_chunk_id is
    'Optional citation anchor; cleared safely when a replaceable chunk is removed during re-indexing.';

create index table_snapshots_document_extractor_idx
    on public.table_snapshots (
        owner_id,
        notebook_id,
        document_id,
        extractor_version,
        snapshot_key
    );
create index table_snapshots_template_idx
    on public.table_snapshots (
        owner_id,
        notebook_id,
        template_fingerprint,
        schema_fingerprint
    )
    where template_fingerprint is not null;
create index table_snapshots_schema_idx
    on public.table_snapshots (
        owner_id,
        notebook_id,
        schema_fingerprint,
        document_id
    );
create index table_snapshots_effective_time_idx
    on public.table_snapshots (
        owner_id,
        notebook_id,
        effective_from,
        effective_to,
        publication_time
    );

-- ---------------------------------------------------------------------------
-- Structured claims with row/cell provenance and business qualifiers
-- ---------------------------------------------------------------------------

create table public.structured_claims (
    id uuid primary key default gen_random_uuid(),
    owner_id uuid not null references auth.users (id) on delete cascade,
    notebook_id uuid not null,
    document_id uuid not null,
    snapshot_id uuid not null,
    source_chunk_id uuid
        references public.document_chunks (id) on delete set null,
    claim_key text not null,
    row_identity text not null,
    row_identity_hash text not null,
    row_index integer not null,
    data_row_ordinal integer,
    page_number integer,
    source_text text,
    source_cells jsonb not null default '[]'::jsonb,
    provenance jsonb not null default '{}'::jsonb,
    subject_identity jsonb not null,
    subject_identity_hash text not null,
    candidate_identity_hash text not null,
    predicate text not null,
    value_type text not null,
    normalized_value jsonb not null,
    numeric_value numeric,
    unit text,
    currency text,
    qualifiers jsonb not null default '{}'::jsonb,
    qualifier_hash text not null,
    publication_time timestamptz,
    effective_from timestamptz,
    effective_to timestamptz,
    observed_at timestamptz,
    ingested_at timestamptz not null default now(),
    source_publisher text,
    source_type text not null default 'unknown',
    authority_level integer,
    authority_metadata jsonb not null default '{}'::jsonb,
    confidence double precision not null default 0,
    is_derived boolean not null default false,
    derivation jsonb not null default '{}'::jsonb,
    extractor_version text not null,
    created_at timestamptz not null default now(),
    updated_at timestamptz not null default now(),
    constraint structured_claims_snapshot_owner_fk
        foreign key (snapshot_id, document_id, notebook_id, owner_id)
        references public.table_snapshots (
            id,
            document_id,
            notebook_id,
            owner_id
        )
        on delete cascade,
    constraint structured_claims_id_snapshot_notebook_owner_key
        unique (id, snapshot_id, notebook_id, owner_id),
    constraint structured_claims_snapshot_claim_extractor_key
        unique (snapshot_id, claim_key, extractor_version),
    constraint structured_claims_claim_key
        check (char_length(btrim(claim_key)) between 1 and 500),
    constraint structured_claims_row_provenance
        check (
            char_length(btrim(row_identity)) between 1 and 2000
            and row_identity_hash ~ '^[0-9a-f]{64}$'
            and row_index >= 0
            and (data_row_ordinal is null or data_row_ordinal >= 0)
            and (page_number is null or page_number > 0)
            and (source_text is null or char_length(btrim(source_text)) > 0)
            and jsonb_typeof(source_cells) = 'array'
            and jsonb_typeof(provenance) = 'object'
        ),
    constraint structured_claims_subject
        check (
            jsonb_typeof(subject_identity) = 'object'
            and subject_identity_hash ~ '^[0-9a-f]{64}$'
            and candidate_identity_hash ~ '^[0-9a-f]{64}$'
            and char_length(btrim(predicate)) between 1 and 200
        ),
    constraint structured_claims_value
        check (
            value_type in (
                'money',
                'number',
                'percentage',
                'quantity',
                'date',
                'datetime',
                'boolean',
                'text',
                'category',
                'identifier'
            )
            and jsonb_typeof(normalized_value) = 'object'
            and (unit is null or char_length(btrim(unit)) between 1 and 100)
            and (currency is null or currency ~ '^[A-Z]{3}$')
        ),
    constraint structured_claims_qualifiers
        check (
            jsonb_typeof(qualifiers) = 'object'
            and qualifier_hash ~ '^[0-9a-f]{64}$'
        ),
    constraint structured_claims_temporal_interval
        check (
            effective_from is null
            or effective_to is null
            or effective_to >= effective_from
        ),
    constraint structured_claims_authority
        check (
            char_length(btrim(source_type)) between 1 and 100
            and (
                source_publisher is null
                or char_length(btrim(source_publisher)) between 1 and 500
            )
            and (
                authority_level is null
                or authority_level between 0 and 100
            )
            and jsonb_typeof(authority_metadata) = 'object'
        ),
    constraint structured_claims_confidence
        check (confidence between 0 and 1),
    constraint structured_claims_derivation
        check (jsonb_typeof(derivation) = 'object'),
    constraint structured_claims_extractor_version
        check (char_length(btrim(extractor_version)) between 1 and 100)
);

comment on table public.structured_claims is
    'Row-level business claims keyed by subject, predicate, qualifier set, and effective time.';
comment on column public.structured_claims.source_cells is
    'Ordered cell-level provenance, including source column and raw/normalized values.';
comment on column public.structured_claims.provenance is
    'Page/table/row/column/cell locator used to open the exact source evidence.';
comment on column public.structured_claims.derivation is
    'Formula and input claim keys for derived values; never replaces original provenance.';

create index structured_claims_subject_predicate_qualifier_idx
    on public.structured_claims (
        owner_id,
        notebook_id,
        subject_identity_hash,
        predicate,
        qualifier_hash
    );
create index structured_claims_candidate_identity_idx
    on public.structured_claims (
        notebook_id,
        candidate_identity_hash,
        predicate,
        document_id
    );
create index structured_claims_row_predicate_idx
    on public.structured_claims (
        owner_id,
        notebook_id,
        snapshot_id,
        row_identity_hash,
        predicate
    );
create index structured_claims_effective_time_idx
    on public.structured_claims (
        owner_id,
        notebook_id,
        predicate,
        effective_from,
        effective_to,
        publication_time
    );
create index structured_claims_qualifiers_gin_idx
    on public.structured_claims using gin (qualifiers jsonb_path_ops);
create index structured_claims_subject_gin_idx
    on public.structured_claims using gin (subject_identity jsonb_path_ops);

-- ---------------------------------------------------------------------------
-- Directional row/claim relationships and immutable review audit
-- ---------------------------------------------------------------------------

create table public.claim_relations (
    id uuid primary key default gen_random_uuid(),
    owner_id uuid not null references auth.users (id) on delete cascade,
    notebook_id uuid not null,
    source_snapshot_id uuid not null,
    target_snapshot_id uuid not null,
    source_claim_id uuid,
    target_claim_id uuid,
    relation_type text not null,
    scope_relation text not null default 'unknown',
    qualifier_compatibility text not null default 'unknown',
    temporal_compatibility text not null default 'unknown',
    confidence double precision not null default 0,
    evidence jsonb not null default '{}'::jsonb,
    reason text,
    detector_name text not null default 'structured-fact-analyzer',
    detector_version text not null,
    review_status text not null default 'pending',
    resolved_by uuid references auth.users (id) on delete set null,
    resolved_at timestamptz,
    created_at timestamptz not null default now(),
    updated_at timestamptz not null default now(),
    constraint claim_relations_source_snapshot_owner_fk
        foreign key (source_snapshot_id, notebook_id, owner_id)
        references public.table_snapshots (id, notebook_id, owner_id)
        on delete cascade,
    constraint claim_relations_target_snapshot_owner_fk
        foreign key (target_snapshot_id, notebook_id, owner_id)
        references public.table_snapshots (id, notebook_id, owner_id)
        on delete cascade,
    constraint claim_relations_source_claim_owner_fk
        foreign key (
            source_claim_id,
            source_snapshot_id,
            notebook_id,
            owner_id
        )
        references public.structured_claims (
            id,
            snapshot_id,
            notebook_id,
            owner_id
        )
        on delete cascade,
    constraint claim_relations_target_claim_owner_fk
        foreign key (
            target_claim_id,
            target_snapshot_id,
            notebook_id,
            owner_id
        )
        references public.structured_claims (
            id,
            snapshot_id,
            notebook_id,
            owner_id
        )
        on delete cascade,
    constraint claim_relations_id_notebook_owner_key
        unique (id, notebook_id, owner_id),
    constraint claim_relations_distinct_claims
        check (
            source_claim_id is null
            or target_claim_id is null
            or source_claim_id <> target_claim_id
        ),
    constraint claim_relations_type
        check (
            relation_type in (
                'unchanged',
                'updated',
                'added',
                'removed',
                'equivalent',
                'source_updates_target',
                'target_updates_source',
                'source_supersedes_target',
                'target_supersedes_source',
                'source_contains_target',
                'target_contains_source',
                'source_only',
                'target_only',
                'conflict_candidate',
                'conflict',
                'conditional_variant',
                'distinct',
                'uncertain'
            )
        ),
    constraint claim_relations_endpoints
        check (
            (
                relation_type in ('source_only', 'removed')
                and source_claim_id is not null
                and target_claim_id is null
            )
            or (
                relation_type in ('target_only', 'added')
                and source_claim_id is null
                and target_claim_id is not null
            )
            or (
                relation_type = 'uncertain'
                and (
                    source_claim_id is not null
                    or target_claim_id is not null
                )
            )
            or (
                relation_type not in (
                    'source_only',
                    'target_only',
                    'removed',
                    'added',
                    'uncertain'
                )
                and source_claim_id is not null
                and target_claim_id is not null
            )
        ),
    constraint claim_relations_scope
        check (
            scope_relation in (
                'same',
                'source_contains_target',
                'target_contains_source',
                'overlaps',
                'disjoint',
                'unknown'
            )
        ),
    constraint claim_relations_qualifiers
        check (
            qualifier_compatibility in (
                'equal',
                'compatible',
                'disjoint',
                'unknown'
            )
        ),
    constraint claim_relations_temporal
        check (
            temporal_compatibility in (
                'same',
                'same_interval',
                'source_contains_target',
                'target_contains_source',
                'before',
                'after',
                'overlaps',
                'non_overlapping',
                'unknown'
            )
        ),
    constraint claim_relations_confidence
        check (confidence between 0 and 1),
    constraint claim_relations_evidence
        check (jsonb_typeof(evidence) = 'object'),
    constraint claim_relations_reason
        check (reason is null or char_length(btrim(reason)) between 1 and 2000),
    constraint claim_relations_detector
        check (
            char_length(btrim(detector_name)) between 1 and 100
            and char_length(btrim(detector_version)) between 1 and 100
        ),
    constraint claim_relations_review_status
        check (
            review_status in (
                'pending',
                'auto_confirmed',
                'confirmed',
                'dismissed'
            )
        ),
    constraint claim_relations_resolution
        check (
            (
                review_status = 'pending'
                and resolved_by is null
                and resolved_at is null
            )
            or (
                review_status = 'auto_confirmed'
                and resolved_by is null
                and resolved_at is not null
            )
            or (
                review_status in ('confirmed', 'dismissed')
                and resolved_by is not null
                and resolved_at is not null
            )
        )
);

comment on table public.claim_relations is
    'Directional row/claim comparisons; source_only and target_only preserve full-table diff semantics.';

create unique index claim_relations_detector_key
    on public.claim_relations (
        source_snapshot_id,
        target_snapshot_id,
        coalesce(
            source_claim_id,
            '00000000-0000-0000-0000-000000000000'::uuid
        ),
        coalesce(
            target_claim_id,
            '00000000-0000-0000-0000-000000000000'::uuid
        ),
        detector_name,
        detector_version
    );
create index claim_relations_review_queue_idx
    on public.claim_relations (
        owner_id,
        notebook_id,
        review_status,
        confidence desc,
        created_at desc
    );
create index claim_relations_target_idx
    on public.claim_relations (
        owner_id,
        notebook_id,
        target_claim_id,
        relation_type
    );
create index claim_relations_source_idx
    on public.claim_relations (
        owner_id,
        notebook_id,
        source_claim_id,
        relation_type
    );

create table public.structured_claim_audit (
    id bigint generated always as identity primary key,
    owner_id uuid not null references auth.users (id) on delete cascade,
    notebook_id uuid not null,
    document_id uuid,
    relation_id uuid references public.claim_relations (id) on delete set null,
    actor_id uuid references auth.users (id) on delete set null,
    action text not null,
    reason text,
    before_state jsonb not null default '{}'::jsonb,
    after_state jsonb not null default '{}'::jsonb,
    created_at timestamptz not null default now(),
    constraint structured_claim_audit_notebook_owner_fk
        foreign key (notebook_id, owner_id)
        references public.notebooks (id, owner_id)
        on delete cascade,
    constraint structured_claim_audit_document_owner_fk
        foreign key (document_id, notebook_id, owner_id)
        references public.documents (id, notebook_id, owner_id)
        on delete cascade,
    constraint structured_claim_audit_action
        check (char_length(btrim(action)) between 1 and 100),
    constraint structured_claim_audit_reason
        check (reason is null or char_length(btrim(reason)) between 1 and 2000),
    constraint structured_claim_audit_states
        check (
            jsonb_typeof(before_state) = 'object'
            and jsonb_typeof(after_state) = 'object'
        )
);

comment on table public.structured_claim_audit is
    'Append-only audit trail for structured extraction replacement and claim-relation review.';

create index structured_claim_audit_owner_created_idx
    on public.structured_claim_audit (
        owner_id,
        notebook_id,
        created_at desc,
        id desc
    );

create function public.prevent_structured_claim_audit_mutation()
returns trigger
language plpgsql
set search_path = ''
as $$
begin
    if pg_trigger_depth() > 1 then
        return null;
    end if;
    raise exception 'structured_claim_audit is append-only'
        using errcode = '42501';
end;
$$;

create trigger structured_claim_audit_immutable
before update or delete on public.structured_claim_audit
for each statement execute function public.prevent_structured_claim_audit_mutation();

-- ---------------------------------------------------------------------------
-- RLS: owners can inspect derived facts but cannot write them directly.
-- Service workers persist through the guarded RPC below.
-- ---------------------------------------------------------------------------

alter table public.table_snapshots enable row level security;
alter table public.structured_claims enable row level security;
alter table public.claim_relations enable row level security;
alter table public.structured_claim_audit enable row level security;

create policy table_snapshots_select_own
on public.table_snapshots for select to authenticated
using ((select auth.uid()) = owner_id);

create policy structured_claims_select_own
on public.structured_claims for select to authenticated
using ((select auth.uid()) = owner_id);

create policy claim_relations_select_own
on public.claim_relations for select to authenticated
using ((select auth.uid()) = owner_id);

create policy structured_claim_audit_select_own
on public.structured_claim_audit for select to authenticated
using ((select auth.uid()) = owner_id);

revoke all on table public.table_snapshots from public, anon, authenticated;
revoke all on table public.structured_claims from public, anon, authenticated;
revoke all on table public.claim_relations from public, anon, authenticated;
revoke all on table public.structured_claim_audit from public, anon, authenticated;

grant select on table public.table_snapshots to authenticated;
grant select on table public.structured_claims to authenticated;
grant select on table public.claim_relations to authenticated;
grant select on table public.structured_claim_audit to authenticated;

grant all privileges on table public.table_snapshots to service_role;
grant all privileges on table public.structured_claims to service_role;
grant all privileges on table public.claim_relations to service_role;
grant all privileges on table public.structured_claim_audit to service_role;

-- ---------------------------------------------------------------------------
-- Atomic, idempotent worker persistence.
--
-- Snapshot payloads require snapshot_key/input_content_hash/schema_fingerprint.
-- Claim payloads address a snapshot by snapshot_key. Relation payloads address
-- the new source claim by source_snapshot_key/source_claim_key and an existing
-- target by target_snapshot_id plus target_claim_id (or target_claim_key).
-- ---------------------------------------------------------------------------

create function public.replace_structured_facts_for_document(
    p_job_id uuid,
    p_document_id uuid,
    p_extractor_version text,
    p_table_snapshots jsonb,
    p_claims jsonb,
    p_relations jsonb default '[]'::jsonb
)
returns jsonb
language plpgsql
security definer
set search_path = ''
as $$
declare
    selected_job public.ingestion_jobs;
    selected_document public.documents;
    selected_snapshot public.table_snapshots;
    target_snapshot public.table_snapshots;
    snapshot_payload jsonb;
    claim_payload jsonb;
    relation_payload jsonb;
    selected_source_claim_id uuid;
    selected_target_claim_id uuid;
    snapshot_key_value text;
    snapshot_input_hash text;
    snapshot_schema_hash text;
    claim_snapshot_key text;
    claim_key_value text;
    claim_row_identity text;
    claim_row_identity_hash text;
    claim_subject_identity jsonb;
    claim_subject_identity_hash text;
    claim_candidate_identity_hash text;
    claim_qualifiers jsonb;
    claim_qualifier_hash text;
    claim_normalized_value jsonb;
    claim_provenance jsonb;
    claim_source_chunk_id uuid;
    claim_value_type text;
    normalized_extractor_version text;
    relation_review_status text;
    before_snapshot_count integer;
    before_claim_count integer;
    snapshot_count integer := 0;
    claim_count integer := 0;
    relation_count integer := 0;
begin
    if auth.role() <> 'service_role' then
        raise exception 'Service role is required'
            using errcode = '42501';
    end if;

    normalized_extractor_version := nullif(btrim(p_extractor_version), '');
    if normalized_extractor_version is null
       or char_length(normalized_extractor_version) > 100 then
        raise exception 'Invalid extractor version'
            using errcode = '22023';
    end if;
    if jsonb_typeof(p_table_snapshots) <> 'array'
       or jsonb_typeof(p_claims) <> 'array'
       or jsonb_typeof(p_relations) <> 'array' then
        raise exception 'Structured fact payloads must be JSON arrays'
            using errcode = '22023';
    end if;

    select jobs.*
    into selected_job
    from public.ingestion_jobs as jobs
    where jobs.id = p_job_id
      and jobs.document_id = p_document_id
    for update;

    if not found then
        raise exception 'Ingestion job was not found for this document'
            using errcode = 'P0002';
    end if;
    if selected_job.status <> 'succeeded' then
        raise exception 'Structured facts require a succeeded ingestion job'
            using errcode = '55000';
    end if;
    if selected_job.completion_disposition = 'duplicate_suppressed' then
        raise exception 'Cannot persist facts for a duplicate-suppressed job'
            using errcode = '55000';
    end if;
    if exists (
        select 1
        from public.ingestion_jobs as newer_job
        where newer_job.document_id = selected_job.document_id
          and newer_job.notebook_id = selected_job.notebook_id
          and newer_job.owner_id = selected_job.owner_id
          and newer_job.attempt_number > selected_job.attempt_number
          and newer_job.status = 'succeeded'
          and newer_job.completion_disposition
                is distinct from 'duplicate_suppressed'
    ) then
        raise exception 'A newer successful ingestion supersedes this job'
            using errcode = '40001';
    end if;

    select documents.*
    into selected_document
    from public.documents as documents
    where documents.id = p_document_id
      and documents.notebook_id = selected_job.notebook_id
      and documents.owner_id = selected_job.owner_id
      and documents.status = 'ready'
      and documents.canonical_document_id is null
    for update;

    if not found then
        raise exception 'Ready canonical document was not found'
            using errcode = 'P0002';
    end if;

    perform pg_catalog.pg_advisory_xact_lock(
        pg_catalog.hashtextextended(
            selected_job.owner_id::text
                || ':' || selected_job.notebook_id::text
                || ':' || selected_job.document_id::text
                || ':' || normalized_extractor_version,
            0
        )
    );

    select count(*)::integer
    into before_snapshot_count
    from public.table_snapshots as snapshots
    where snapshots.document_id = selected_document.id
      and snapshots.notebook_id = selected_document.notebook_id
      and snapshots.owner_id = selected_document.owner_id
      and snapshots.extractor_version = normalized_extractor_version;

    select count(*)::integer
    into before_claim_count
    from public.structured_claims as claims
    where claims.document_id = selected_document.id
      and claims.notebook_id = selected_document.notebook_id
      and claims.owner_id = selected_document.owner_id
      and claims.extractor_version = normalized_extractor_version;

    -- This delete is deliberately scoped to one document and one extractor
    -- version. Any exception later in the function rolls the transaction back.
    delete from public.table_snapshots
    where table_snapshots.document_id = selected_document.id
      and table_snapshots.notebook_id = selected_document.notebook_id
      and table_snapshots.owner_id = selected_document.owner_id
      and table_snapshots.extractor_version = normalized_extractor_version;

    for snapshot_payload in
        select payload.value
        from jsonb_array_elements(p_table_snapshots) as payload(value)
    loop
        snapshot_key_value := coalesce(
            nullif(btrim(snapshot_payload ->> 'snapshot_key'), ''),
            nullif(btrim(snapshot_payload ->> 'table_id'), '')
        );
        snapshot_input_hash := coalesce(
            nullif(snapshot_payload ->> 'input_content_hash', ''),
            pg_catalog.encode(
                public.knowledge_digest(
                    pg_catalog.convert_to(snapshot_payload::text, 'UTF8'),
                    'sha256'
                ),
                'hex'
            )
        );
        snapshot_schema_hash := coalesce(
            nullif(snapshot_payload ->> 'schema_fingerprint', ''),
            pg_catalog.encode(
                public.knowledge_digest(
                    pg_catalog.convert_to(
                        coalesce(
                            snapshot_payload -> 'normalized_schema',
                            snapshot_payload -> 'header_mapping',
                            '{}'::jsonb
                        )::text,
                        'UTF8'
                    ),
                    'sha256'
                ),
                'hex'
            )
        );
        if jsonb_typeof(snapshot_payload) <> 'object'
           or snapshot_key_value is null
           or snapshot_input_hash !~ '^[0-9a-f]{64}$'
           or snapshot_schema_hash !~ '^[0-9a-f]{64}$' then
            raise exception 'Invalid table snapshot payload'
                using errcode = '22023';
        end if;
        if nullif(snapshot_payload ->> 'source_chunk_id', '') is not null
           and not exists (
                select 1
                from public.document_chunks as chunks
                where chunks.id = (
                    snapshot_payload ->> 'source_chunk_id'
                )::uuid
                  and chunks.document_id = selected_document.id
                  and chunks.notebook_id = selected_document.notebook_id
                  and chunks.owner_id = selected_document.owner_id
           ) then
            raise exception 'Snapshot source chunk is outside this document'
                using errcode = '23503';
        end if;

        insert into public.table_snapshots (
            owner_id,
            notebook_id,
            document_id,
            source_chunk_id,
            snapshot_key,
            input_content_hash,
            schema_fingerprint,
            template_fingerprint,
            table_index,
            page_from,
            page_to,
            source_locator,
            normalized_schema,
            row_count,
            column_count,
            extractor_name,
            extractor_version,
            publication_time,
            effective_from,
            effective_to,
            observed_at,
            ingested_at,
            source_publisher,
            source_type,
            authority_level,
            authority_metadata,
            warnings,
            extraction_confidence
        )
        values (
            selected_document.owner_id,
            selected_document.notebook_id,
            selected_document.id,
            nullif(snapshot_payload ->> 'source_chunk_id', '')::uuid,
            snapshot_key_value,
            snapshot_input_hash,
            snapshot_schema_hash,
            nullif(snapshot_payload ->> 'template_fingerprint', ''),
            coalesce((snapshot_payload ->> 'table_index')::integer, 0),
            nullif(snapshot_payload ->> 'page_from', '')::integer,
            nullif(snapshot_payload ->> 'page_to', '')::integer,
            coalesce(
                snapshot_payload -> 'source_locator',
                jsonb_build_object('table_id', snapshot_key_value)
            ),
            coalesce(snapshot_payload -> 'normalized_schema', '{}'::jsonb),
            coalesce((snapshot_payload ->> 'row_count')::integer, 0),
            coalesce(
                (snapshot_payload ->> 'column_count')::integer,
                case
                    when jsonb_typeof(
                        snapshot_payload -> 'normalized_schema'
                    ) = 'array'
                    then jsonb_array_length(
                        snapshot_payload -> 'normalized_schema'
                    )
                    else 0
                end
            ),
            coalesce(
                nullif(btrim(snapshot_payload ->> 'extractor_name'), ''),
                'structured-fact-analyzer'
            ),
            normalized_extractor_version,
            nullif(snapshot_payload ->> 'publication_time', '')::timestamptz,
            nullif(snapshot_payload ->> 'effective_from', '')::timestamptz,
            nullif(snapshot_payload ->> 'effective_to', '')::timestamptz,
            coalesce(
                nullif(snapshot_payload ->> 'observed_at', '')::timestamptz,
                now()
            ),
            coalesce(
                nullif(snapshot_payload ->> 'ingested_at', '')::timestamptz,
                now()
            ),
            nullif(btrim(snapshot_payload ->> 'source_publisher'), ''),
            coalesce(
                nullif(btrim(snapshot_payload ->> 'source_type'), ''),
                'unknown'
            ),
            nullif(snapshot_payload ->> 'authority_level', '')::integer,
            coalesce(snapshot_payload -> 'authority_metadata', '{}'::jsonb),
            coalesce(snapshot_payload -> 'warnings', '[]'::jsonb),
            coalesce(
                (snapshot_payload ->> 'extraction_confidence')::double precision,
                (snapshot_payload ->> 'confidence')::double precision,
                0
            )
        );
        snapshot_count := snapshot_count + 1;
    end loop;

    for claim_payload in
        select payload.value
        from jsonb_array_elements(p_claims) as payload(value)
    loop
        claim_provenance := coalesce(
            claim_payload -> 'provenance',
            '{}'::jsonb
        );
        claim_snapshot_key := coalesce(
            nullif(btrim(claim_payload ->> 'snapshot_key'), ''),
            nullif(btrim(claim_provenance ->> 'table_id'), '')
        );
        claim_key_value := coalesce(
            nullif(btrim(claim_payload ->> 'claim_key'), ''),
            nullif(btrim(claim_payload ->> 'claim_identity_hash'), '')
        );
        claim_row_identity := coalesce(
            nullif(btrim(claim_payload ->> 'row_identity'), ''),
            nullif(btrim(claim_payload ->> 'subject_key'), '')
        );
        claim_row_identity_hash := coalesce(
            nullif(claim_payload ->> 'row_identity_hash', ''),
            case
                when claim_row_identity is not null then pg_catalog.encode(
                    public.knowledge_digest(
                        pg_catalog.convert_to(claim_row_identity, 'UTF8'),
                        'sha256'
                    ),
                    'hex'
                )
                else null
            end
        );
        claim_subject_identity := coalesce(
            claim_payload -> 'subject_identity',
            jsonb_build_object('subject_key', claim_row_identity)
                || coalesce(claim_payload -> 'scope', '{}'::jsonb)
        );
        claim_subject_identity_hash := coalesce(
            nullif(claim_payload ->> 'subject_identity_hash', ''),
            nullif(claim_payload #>> '{scope,scope_identity_hash}', ''),
            pg_catalog.encode(
                public.knowledge_digest(
                    pg_catalog.convert_to(claim_subject_identity::text, 'UTF8'),
                    'sha256'
                ),
                'hex'
            )
        );
        claim_candidate_identity_hash := nullif(
            claim_payload ->> 'candidate_identity_hash',
            ''
        );
        claim_qualifiers := coalesce(
            claim_payload -> 'qualifiers',
            '{}'::jsonb
        );
        claim_qualifier_hash := coalesce(
            nullif(claim_payload ->> 'qualifier_hash', ''),
            nullif(
                claim_payload #>> '{qualifiers,stable_identity_hash}',
                ''
            )
        );
        claim_normalized_value := coalesce(
            claim_payload -> 'normalized_value',
            claim_payload -> 'value'
        );
        claim_source_chunk_id := coalesce(
            nullif(claim_payload ->> 'source_chunk_id', '')::uuid,
            nullif(claim_provenance ->> 'chunk_id', '')::uuid
        );
        claim_value_type := coalesce(
            nullif(btrim(claim_payload ->> 'value_type'), ''),
            case
                when nullif(
                    claim_normalized_value ->> 'currency',
                    ''
                ) is not null then 'money'
                when jsonb_typeof(claim_normalized_value -> 'value')
                    = 'number' then 'number'
                when jsonb_typeof(claim_normalized_value -> 'value')
                    = 'boolean' then 'boolean'
                else 'text'
            end
        );
        if jsonb_typeof(claim_payload) <> 'object'
           or claim_snapshot_key is null
           or claim_key_value is null
           or claim_row_identity is null
           or jsonb_typeof(claim_subject_identity) <> 'object'
           or nullif(btrim(claim_payload ->> 'predicate'), '') is null
           or claim_value_type is null
           or jsonb_typeof(claim_normalized_value) <> 'object'
           or claim_row_identity_hash !~ '^[0-9a-f]{64}$'
           or claim_subject_identity_hash !~ '^[0-9a-f]{64}$'
           or claim_candidate_identity_hash !~ '^[0-9a-f]{64}$'
           or claim_qualifier_hash !~ '^[0-9a-f]{64}$' then
            raise exception 'Invalid structured claim payload'
                using errcode = '22023';
        end if;
        if claim_source_chunk_id is not null
           and not exists (
                select 1
                from public.document_chunks as chunks
                where chunks.id = claim_source_chunk_id
                  and chunks.document_id = selected_document.id
                  and chunks.notebook_id = selected_document.notebook_id
                  and chunks.owner_id = selected_document.owner_id
           ) then
            raise exception 'Claim source chunk is outside this document'
                using errcode = '23503';
        end if;

        select snapshots.*
        into selected_snapshot
        from public.table_snapshots as snapshots
        where snapshots.document_id = selected_document.id
          and snapshots.notebook_id = selected_document.notebook_id
          and snapshots.owner_id = selected_document.owner_id
          and snapshots.extractor_version = normalized_extractor_version
          and snapshots.snapshot_key = claim_snapshot_key;

        if not found then
            raise exception 'Claim references an unknown snapshot key'
                using errcode = '23503';
        end if;

        insert into public.structured_claims (
            owner_id,
            notebook_id,
            document_id,
            snapshot_id,
            source_chunk_id,
            claim_key,
            row_identity,
            row_identity_hash,
            row_index,
            data_row_ordinal,
            page_number,
            source_text,
            source_cells,
            provenance,
            subject_identity,
            subject_identity_hash,
            candidate_identity_hash,
            predicate,
            value_type,
            normalized_value,
            numeric_value,
            unit,
            currency,
            qualifiers,
            qualifier_hash,
            publication_time,
            effective_from,
            effective_to,
            observed_at,
            ingested_at,
            source_publisher,
            source_type,
            authority_level,
            authority_metadata,
            confidence,
            is_derived,
            derivation,
            extractor_version
        )
        values (
            selected_document.owner_id,
            selected_document.notebook_id,
            selected_document.id,
            selected_snapshot.id,
            claim_source_chunk_id,
            claim_key_value,
            claim_row_identity,
            claim_row_identity_hash,
            coalesce(
                (claim_payload ->> 'row_index')::integer,
                (claim_provenance ->> 'row_index')::integer,
                0
            ),
            coalesce(
                nullif(claim_payload ->> 'data_row_ordinal', '')::integer,
                nullif(claim_provenance ->> 'data_row_ordinal', '')::integer
            ),
            coalesce(
                nullif(claim_payload ->> 'page_number', '')::integer,
                nullif(claim_provenance ->> 'page_number', '')::integer
            ),
            coalesce(
                nullif(btrim(claim_payload ->> 'source_text'), ''),
                nullif(btrim(claim_normalized_value ->> 'raw_value'), '')
            ),
            coalesce(
                claim_payload -> 'source_cells',
                case
                    when claim_provenance = '{}'::jsonb then '[]'::jsonb
                    else jsonb_build_array(claim_provenance)
                end
            ),
            claim_provenance,
            claim_subject_identity,
            claim_subject_identity_hash,
            claim_candidate_identity_hash,
            btrim(claim_payload ->> 'predicate'),
            claim_value_type,
            claim_normalized_value,
            coalesce(
                nullif(claim_payload ->> 'numeric_value', '')::numeric,
                case
                    when claim_normalized_value ->> 'value'
                        ~ '^[+-]?[0-9]+([.][0-9]+)?$'
                    then (claim_normalized_value ->> 'value')::numeric
                    else null
                end
            ),
            coalesce(
                nullif(btrim(claim_payload ->> 'unit'), ''),
                nullif(btrim(claim_normalized_value ->> 'unit'), '')
            ),
            nullif(
                upper(
                    btrim(
                        coalesce(
                            claim_payload ->> 'currency',
                            claim_normalized_value ->> 'currency'
                        )
                    )
                ),
                ''
            ),
            claim_qualifiers,
            claim_qualifier_hash,
            coalesce(
                nullif(claim_payload ->> 'publication_time', '')::timestamptz,
                nullif(
                    claim_payload #>> '{temporal,publication_time}',
                    ''
                )::timestamptz,
                selected_snapshot.publication_time
            ),
            coalesce(
                nullif(claim_payload ->> 'effective_from', '')::timestamptz,
                nullif(
                    claim_payload #>> '{temporal,effective_from}',
                    ''
                )::timestamptz,
                selected_snapshot.effective_from
            ),
            coalesce(
                nullif(claim_payload ->> 'effective_to', '')::timestamptz,
                nullif(
                    claim_payload #>> '{temporal,effective_to}',
                    ''
                )::timestamptz,
                selected_snapshot.effective_to
            ),
            coalesce(
                nullif(claim_payload ->> 'observed_at', '')::timestamptz,
                nullif(
                    claim_payload #>> '{temporal,observed_at}',
                    ''
                )::timestamptz,
                selected_snapshot.observed_at,
                now()
            ),
            coalesce(
                nullif(claim_payload ->> 'ingested_at', '')::timestamptz,
                nullif(
                    claim_payload #>> '{temporal,ingested_at}',
                    ''
                )::timestamptz,
                selected_snapshot.ingested_at,
                now()
            ),
            coalesce(
                nullif(btrim(claim_payload ->> 'source_publisher'), ''),
                nullif(
                    btrim(claim_payload #>> '{authority,publisher}'),
                    ''
                ),
                selected_snapshot.source_publisher
            ),
            coalesce(
                nullif(btrim(claim_payload ->> 'source_type'), ''),
                nullif(
                    btrim(claim_payload #>> '{authority,source_type}'),
                    ''
                ),
                selected_snapshot.source_type
            ),
            coalesce(
                nullif(claim_payload ->> 'authority_level', '')::integer,
                nullif(
                    claim_payload #>> '{authority,authority_level}',
                    ''
                )::integer,
                selected_snapshot.authority_level
            ),
            coalesce(
                claim_payload -> 'authority_metadata',
                claim_payload -> 'authority',
                selected_snapshot.authority_metadata
            ),
            coalesce(
                (claim_payload ->> 'confidence')::double precision,
                (claim_payload ->> 'extraction_confidence')::double precision,
                0
            ),
            coalesce(
                (claim_payload ->> 'is_derived')::boolean,
                jsonb_typeof(claim_payload -> 'derivation') = 'object',
                false
            ),
            case
                when jsonb_typeof(claim_payload -> 'derivation') = 'object'
                then claim_payload -> 'derivation'
                else '{}'::jsonb
            end,
            normalized_extractor_version
        );
        claim_count := claim_count + 1;
    end loop;

    for relation_payload in
        select payload.value
        from jsonb_array_elements(p_relations) as payload(value)
    loop
        if jsonb_typeof(relation_payload) <> 'object'
           or nullif(
                btrim(relation_payload ->> 'source_snapshot_key'),
                ''
           ) is null
           or nullif(relation_payload ->> 'target_snapshot_id', '') is null then
            raise exception 'Invalid claim relation payload'
                using errcode = '22023';
        end if;

        select snapshots.*
        into selected_snapshot
        from public.table_snapshots as snapshots
        where snapshots.document_id = selected_document.id
          and snapshots.notebook_id = selected_document.notebook_id
          and snapshots.owner_id = selected_document.owner_id
          and snapshots.extractor_version = normalized_extractor_version
          and snapshots.snapshot_key = btrim(
              relation_payload ->> 'source_snapshot_key'
          );

        if not found then
            raise exception 'Relation references an unknown source snapshot'
                using errcode = '23503';
        end if;

        select snapshots.*
        into target_snapshot
        from public.table_snapshots as snapshots
        where snapshots.id = (relation_payload ->> 'target_snapshot_id')::uuid
          and snapshots.notebook_id = selected_document.notebook_id
          and snapshots.owner_id = selected_document.owner_id;

        if not found then
            raise exception 'Relation target snapshot is outside this tenant'
                using errcode = '23503';
        end if;

        selected_source_claim_id := null;
        if nullif(relation_payload ->> 'source_claim_key', '') is not null then
            select claims.id
            into selected_source_claim_id
            from public.structured_claims as claims
            where claims.snapshot_id = selected_snapshot.id
              and claims.notebook_id = selected_document.notebook_id
              and claims.owner_id = selected_document.owner_id
              and claims.claim_key = relation_payload ->> 'source_claim_key';
            if not found then
                raise exception 'Relation references an unknown source claim'
                    using errcode = '23503';
            end if;
        end if;

        selected_target_claim_id := nullif(
            relation_payload ->> 'target_claim_id',
            ''
        )::uuid;
        if selected_target_claim_id is null
           and nullif(relation_payload ->> 'target_claim_key', '') is not null then
            select claims.id
            into selected_target_claim_id
            from public.structured_claims as claims
            where claims.snapshot_id = target_snapshot.id
              and claims.notebook_id = selected_document.notebook_id
              and claims.owner_id = selected_document.owner_id
              and claims.claim_key = relation_payload ->> 'target_claim_key';
            if not found then
                raise exception 'Relation references an unknown target claim'
                    using errcode = '23503';
            end if;
        end if;

        relation_review_status := coalesce(
            nullif(btrim(relation_payload ->> 'review_status'), ''),
            'pending'
        );
        if relation_review_status not in ('pending', 'auto_confirmed') then
            raise exception 'Worker may only create pending or auto-confirmed relations'
                using errcode = '22023';
        end if;

        insert into public.claim_relations (
            owner_id,
            notebook_id,
            source_snapshot_id,
            target_snapshot_id,
            source_claim_id,
            target_claim_id,
            relation_type,
            scope_relation,
            qualifier_compatibility,
            temporal_compatibility,
            confidence,
            evidence,
            reason,
            detector_name,
            detector_version,
            review_status,
            resolved_at
        )
        values (
            selected_document.owner_id,
            selected_document.notebook_id,
            selected_snapshot.id,
            target_snapshot.id,
            selected_source_claim_id,
            selected_target_claim_id,
            btrim(relation_payload ->> 'relation_type'),
            case coalesce(
                nullif(btrim(relation_payload ->> 'scope_relation'), ''),
                'unknown'
            )
                when 'left_contains_right' then 'source_contains_target'
                when 'right_contains_left' then 'target_contains_source'
                else coalesce(
                    nullif(
                        btrim(relation_payload ->> 'scope_relation'),
                        ''
                    ),
                    'unknown'
                )
            end,
            coalesce(
                nullif(
                    btrim(
                        relation_payload ->> 'qualifier_compatibility'
                    ),
                    ''
                ),
                'unknown'
            ),
            case coalesce(
                nullif(
                    btrim(
                        relation_payload ->> 'temporal_compatibility'
                    ),
                    ''
                ),
                nullif(
                    btrim(relation_payload ->> 'temporal_relation'),
                    ''
                ),
                'unknown'
            )
                when 'left_contains_right' then 'source_contains_target'
                when 'right_contains_left' then 'target_contains_source'
                else coalesce(
                    nullif(
                        btrim(
                            relation_payload ->> 'temporal_compatibility'
                        ),
                        ''
                    ),
                    nullif(
                        btrim(relation_payload ->> 'temporal_relation'),
                        ''
                    ),
                    'unknown'
                )
            end,
            coalesce(
                (relation_payload ->> 'confidence')::double precision,
                0
            ),
            coalesce(
                relation_payload -> 'evidence',
                jsonb_build_object(
                    'reason_codes',
                    coalesce(
                        relation_payload -> 'reason_codes',
                        '[]'::jsonb
                    )
                )
            ),
            nullif(btrim(relation_payload ->> 'reason'), ''),
            coalesce(
                nullif(btrim(relation_payload ->> 'detector_name'), ''),
                'structured-fact-analyzer'
            ),
            coalesce(
                nullif(btrim(relation_payload ->> 'detector_version'), ''),
                normalized_extractor_version
            ),
            relation_review_status,
            case
                when relation_review_status = 'auto_confirmed' then now()
                else null
            end
        );
        relation_count := relation_count + 1;
    end loop;

    insert into public.structured_claim_audit (
        owner_id,
        notebook_id,
        document_id,
        actor_id,
        action,
        reason,
        before_state,
        after_state
    )
    values (
        selected_document.owner_id,
        selected_document.notebook_id,
        selected_document.id,
        null,
        'replace_document_facts',
        'Atomic worker replacement for one extractor version',
        jsonb_build_object(
            'job_id', selected_job.id,
            'extractor_version', normalized_extractor_version,
            'snapshot_count', before_snapshot_count,
            'claim_count', before_claim_count
        ),
        jsonb_build_object(
            'job_id', selected_job.id,
            'extractor_version', normalized_extractor_version,
            'snapshot_count', snapshot_count,
            'claim_count', claim_count,
            'relation_count', relation_count
        )
    );

    return jsonb_build_object(
        'document_id', selected_document.id,
        'job_id', selected_job.id,
        'extractor_version', normalized_extractor_version,
        'table_count', snapshot_count,
        'snapshot_count', snapshot_count,
        'claim_count', claim_count,
        'relation_count', relation_count
    );
end;
$$;

revoke all on function public.replace_structured_facts_for_document(
    uuid, uuid, text, jsonb, jsonb, jsonb
) from public, anon, authenticated;
grant execute on function public.replace_structured_facts_for_document(
    uuid, uuid, text, jsonb, jsonb, jsonb
) to service_role;

-- Human review is owner-scoped and uses optimistic concurrency. Direct table
-- updates remain unavailable to authenticated clients.
create function public.resolve_structured_claim_relation(
    p_relation_id uuid,
    p_notebook_id uuid,
    p_action text,
    p_expected_updated_at timestamptz,
    p_reason text
)
returns setof public.claim_relations
language plpgsql
security definer
set search_path = ''
as $$
declare
    actor uuid;
    selected_relation public.claim_relations;
    before_state jsonb;
    source_document_id uuid;
begin
    actor := auth.uid();
    if actor is null then
        raise exception 'Authentication is required'
            using errcode = '42501';
    end if;
    if p_action not in (
        'confirm',
        'confirm_equivalent',
        'confirm_update',
        'confirm_conflict',
        'confirm_conditional_variant',
        'dismiss'
    ) then
        raise exception 'Unsupported structured relation action'
            using errcode = '22023';
    end if;
    if p_reason is null
       or char_length(btrim(p_reason)) not between 1 and 2000 then
        raise exception 'Invalid resolution reason'
            using errcode = '22023';
    end if;

    select relations.*
    into selected_relation
    from public.claim_relations as relations
    where relations.id = p_relation_id
      and relations.notebook_id = p_notebook_id
      and relations.owner_id = actor
    for update;

    if not found then
        raise exception 'Structured claim relation was not found'
            using errcode = 'P0002';
    end if;
    if p_expected_updated_at is null
       or selected_relation.updated_at <> p_expected_updated_at then
        raise exception 'Structured claim relation changed before resolution'
            using errcode = '40001';
    end if;

    before_state := to_jsonb(selected_relation);

    update public.claim_relations
    set
        relation_type = case p_action
            when 'confirm_equivalent' then 'equivalent'
            when 'confirm_update' then 'source_updates_target'
            when 'confirm_conflict' then 'conflict'
            when 'confirm_conditional_variant' then 'conditional_variant'
            else claim_relations.relation_type
        end,
        review_status = case
            when p_action = 'dismiss' then 'dismissed'
            else 'confirmed'
        end,
        reason = btrim(p_reason),
        resolved_by = actor,
        resolved_at = now(),
        updated_at = now()
    where claim_relations.id = selected_relation.id
    returning * into selected_relation;

    select snapshots.document_id
    into source_document_id
    from public.table_snapshots as snapshots
    where snapshots.id = selected_relation.source_snapshot_id
      and snapshots.notebook_id = p_notebook_id
      and snapshots.owner_id = actor;

    insert into public.structured_claim_audit (
        owner_id,
        notebook_id,
        document_id,
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
        source_document_id,
        selected_relation.id,
        actor,
        p_action,
        btrim(p_reason),
        before_state,
        to_jsonb(selected_relation)
    );

    return next selected_relation;
end;
$$;

revoke all on function public.resolve_structured_claim_relation(
    uuid, uuid, text, timestamptz, text
) from public, anon;
grant execute on function public.resolve_structured_claim_relation(
    uuid, uuid, text, timestamptz, text
) to authenticated;

-- Exact structured lookup runs before vector retrieval. Time-qualified queries
-- fail closed for claims without an effective start, and only citable claims
-- backed by a live document chunk are returned.
create function public.search_structured_claims(
    p_notebook_id uuid,
    p_document_ids uuid[],
    p_predicate text,
    p_subject_query text,
    p_valid_from timestamptz default null,
    p_valid_to timestamptz default null,
    p_limit integer default 20,
    p_qualifiers jsonb default '{}'::jsonb
)
returns table (
    claim_id uuid,
    document_id uuid,
    document_version integer,
    snapshot_id uuid,
    source_chunk_id uuid,
    candidate_identity_hash text,
    subject_key text,
    subject_identity jsonb,
    predicate text,
    normalized_value jsonb,
    qualifiers jsonb,
    temporal jsonb,
    publication_time timestamptz,
    effective_from timestamptz,
    effective_to timestamptz,
    observed_at timestamptz,
    provenance jsonb,
    source_cells jsonb,
    authority_metadata jsonb,
    confidence double precision,
    source_text text,
    relation_warnings jsonb
)
language plpgsql
stable
security definer
set search_path = ''
as $$
declare
    actor uuid;
    selected_owner_id uuid;
    normalized_predicate text;
    normalized_subject_query text;
    normalized_qualifiers jsonb;
    query_start timestamptz;
    query_end timestamptz;
begin
    actor := auth.uid();
    select notebooks.owner_id
    into selected_owner_id
    from public.notebooks
    where notebooks.id = p_notebook_id;

    if not found then
        raise exception 'Notebook was not found'
            using errcode = 'P0002';
    end if;
    if auth.role() <> 'service_role'
       and actor is distinct from selected_owner_id then
        raise exception 'Cannot search another owner''s structured claims'
            using errcode = '42501';
    end if;

    normalized_predicate := nullif(btrim(p_predicate), '');
    normalized_subject_query := nullif(btrim(p_subject_query), '');
    if normalized_predicate is null or normalized_subject_query is null then
        raise exception 'Predicate and subject query are required'
            using errcode = '22023';
    end if;
    if p_limit is null or p_limit < 1 then
        raise exception 'Search limit must be positive'
            using errcode = '22023';
    end if;
    normalized_qualifiers := coalesce(p_qualifiers, '{}'::jsonb);
    if jsonb_typeof(normalized_qualifiers) <> 'object' then
        raise exception 'Qualifier filters must be an object'
            using errcode = '22023';
    end if;
    if exists (
        select 1
        from jsonb_object_keys(normalized_qualifiers) as qualifier_group(name)
        where qualifier_group.name not in ('stable', 'optional')
    ) then
        raise exception 'Unsupported qualifier filter group'
            using errcode = '22023';
    end if;
    if (
        normalized_qualifiers ? 'stable'
        and jsonb_typeof(normalized_qualifiers -> 'stable') <> 'object'
    ) or (
        normalized_qualifiers ? 'optional'
        and jsonb_typeof(normalized_qualifiers -> 'optional') <> 'object'
    ) then
        raise exception 'Qualifier filter groups must be objects'
            using errcode = '22023';
    end if;
    if p_valid_from is not null
       and p_valid_to is not null
       and p_valid_to < p_valid_from then
        raise exception 'Search validity interval is reversed'
            using errcode = '22023';
    end if;

    query_start := coalesce(p_valid_from, p_valid_to);
    query_end := coalesce(p_valid_to, p_valid_from);

    return query
    select
        claims.id,
        claims.document_id,
        documents.version_number,
        claims.snapshot_id,
        claims.source_chunk_id,
        claims.candidate_identity_hash,
        claims.row_identity,
        claims.subject_identity,
        claims.predicate,
        claims.normalized_value,
        claims.qualifiers,
        jsonb_build_object(
            'publication_time', claims.publication_time,
            'effective_from', claims.effective_from,
            'effective_to', claims.effective_to,
            'observed_at', claims.observed_at,
            'ingested_at', claims.ingested_at
        ),
        claims.publication_time,
        claims.effective_from,
        claims.effective_to,
        claims.observed_at,
        claims.provenance,
        claims.source_cells,
        case
            when jsonb_typeof(claims.authority_metadata -> 'metadata') = 'object'
            then claims.authority_metadata
            else jsonb_strip_nulls(jsonb_build_object(
                'source_type', claims.source_type,
                'publisher', claims.source_publisher,
                'approval_status', claims.authority_metadata -> 'approval_status',
                'officiality', claims.authority_metadata -> 'officiality',
                'authority_level', claims.authority_level,
                'metadata', claims.authority_metadata
                    - array['approval_status', 'officiality']::text[]
            ))
        end,
        claims.confidence,
        coalesce(claims.source_text, claims.normalized_value ->> 'raw_value', ''),
        coalesce(warnings.items, '[]'::jsonb)
    from public.structured_claims as claims
    join public.documents as documents
      on documents.id = claims.document_id
     and documents.notebook_id = claims.notebook_id
     and documents.owner_id = claims.owner_id
    left join lateral (
        select jsonb_agg(
            jsonb_build_object(
                'relation_id', relations.id,
                'relation_type', relations.relation_type,
                'review_status', relations.review_status,
                'confidence', relations.confidence,
                'reason', relations.reason
            )
            order by relations.confidence desc, relations.id
        ) as items
        from public.claim_relations as relations
        where relations.owner_id = claims.owner_id
          and relations.notebook_id = claims.notebook_id
          and (
              relations.source_claim_id = claims.id
              or relations.target_claim_id = claims.id
          )
          and relations.relation_type in (
              'conflict_candidate',
              'conflict',
              'uncertain'
          )
          and relations.review_status <> 'dismissed'
    ) as warnings on true
    where claims.owner_id = selected_owner_id
      and claims.notebook_id = p_notebook_id
      and claims.source_chunk_id is not null
      and claims.predicate = normalized_predicate
      and claims.qualifiers @> normalized_qualifiers
      and (
          p_document_ids is null
          or claims.document_id = any(p_document_ids)
      )
      and (
          claims.candidate_identity_hash = lower(normalized_subject_query)
          or lower(claims.row_identity) = lower(normalized_subject_query)
          or exists (
              select 1
              from pg_catalog.unnest(
                  pg_catalog.string_to_array(lower(claims.row_identity), '|')
              ) as subject_segment(value)
              where pg_catalog.split_part(subject_segment.value, '=', 2)
                  = lower(normalized_subject_query)
          )
      )
      and (
          query_start is null
          or (
              claims.effective_from is not null
              and claims.effective_from <= query_end
              and coalesce(
                  claims.effective_to,
                  'infinity'::timestamptz
              ) >= query_start
          )
      )
    order by
        (
            claims.candidate_identity_hash
                = lower(normalized_subject_query)
        ) desc,
        claims.confidence desc,
        claims.effective_from desc nulls last,
        claims.id
    limit least(p_limit, 200);
end;
$$;

revoke all on function public.search_structured_claims(
    uuid, uuid[], text, text, timestamptz, timestamptz, integer, jsonb
) from public, anon;
grant execute on function public.search_structured_claims(
    uuid, uuid[], text, text, timestamptz, timestamptz, integer, jsonb
) to authenticated, service_role;

-- Worker-only indexed candidate loading for deterministic O(n+m) table diff.
-- The nested claim JSON matches the application StructuredClaim payload.
create function public.load_structured_claim_candidates(
    p_notebook_id uuid,
    p_document_id uuid,
    p_candidate_hashes text[],
    p_limit integer default 10000,
    p_schema_fingerprints text[] default '{}'::text[]
)
returns table (
    claim_id uuid,
    snapshot_id uuid,
    document_id uuid,
    document_version integer,
    snapshot_key text,
    schema_fingerprint text,
    template_fingerprint text,
    normalized_schema jsonb,
    candidate_identity_hash text,
    claim jsonb
)
language plpgsql
stable
security definer
set search_path = ''
as $$
declare
    selected_document public.documents;
    normalized_hashes text[];
    normalized_schema_hashes text[];
    matched_snapshot_ids uuid[];
    candidate_claim_count integer;
begin
    if auth.role() <> 'service_role' then
        raise exception 'Service role is required'
            using errcode = '42501';
    end if;
    if p_limit is null or p_limit < 1 or p_limit > 10000 then
        raise exception 'Candidate limit must be between 1 and 10000'
            using errcode = '22023';
    end if;
    if p_candidate_hashes is null
       or (
           pg_catalog.cardinality(p_candidate_hashes) = 0
           and pg_catalog.cardinality(p_schema_fingerprints) = 0
       )
       or exists (
            select 1
            from unnest(p_candidate_hashes) as candidate_hash(value)
            where candidate_hash.value is null
               or btrim(candidate_hash.value) !~ '^[0-9a-fA-F]{64}$'
       ) then
        raise exception 'Candidate hashes must be non-empty SHA-256 values'
            using errcode = '22023';
    end if;
    if p_schema_fingerprints is null
       or exists (
            select 1
            from unnest(p_schema_fingerprints) as schema_hash(value)
            where schema_hash.value is null
               or btrim(schema_hash.value) !~ '^[0-9a-fA-F]{64}$'
       ) then
        raise exception 'Schema fingerprints must be SHA-256 values'
            using errcode = '22023';
    end if;

    normalized_hashes := array(
        select lower(btrim(candidate_hash.value))
        from unnest(p_candidate_hashes) as candidate_hash(value)
    );
    normalized_schema_hashes := array(
        select lower(btrim(schema_hash.value))
        from unnest(p_schema_fingerprints) as schema_hash(value)
    );

    select documents.*
    into selected_document
    from public.documents
    where documents.id = p_document_id
      and documents.notebook_id = p_notebook_id
      and documents.status = 'ready'
      and documents.canonical_document_id is null;

    if not found then
        raise exception 'Ready canonical source document was not found'
            using errcode = 'P0002';
    end if;

    select pg_catalog.array_agg(matched.id order by matched.id)
    into matched_snapshot_ids
    from (
        select distinct snapshots.id
        from public.table_snapshots as snapshots
        join public.documents as documents
          on documents.id = snapshots.document_id
         and documents.notebook_id = snapshots.notebook_id
         and documents.owner_id = snapshots.owner_id
        where snapshots.owner_id = selected_document.owner_id
          and snapshots.notebook_id = selected_document.notebook_id
          and snapshots.document_id <> selected_document.id
          and documents.status = 'ready'
          and documents.is_active
          and documents.is_current
          and documents.canonical_document_id is null
          and (
              snapshots.schema_fingerprint
                    = any(normalized_schema_hashes)
              or exists (
                  select 1
                  from public.structured_claims as seed_claims
                  where seed_claims.snapshot_id = snapshots.id
                    and seed_claims.notebook_id = snapshots.notebook_id
                    and seed_claims.owner_id = snapshots.owner_id
                    and seed_claims.candidate_identity_hash
                        = any(normalized_hashes)
              )
          )
    ) as matched;

    select count(*)::integer
    into candidate_claim_count
    from public.structured_claims as claims
    where claims.owner_id = selected_document.owner_id
      and claims.notebook_id = selected_document.notebook_id
      and claims.snapshot_id = any(matched_snapshot_ids);

    if candidate_claim_count > p_limit then
        raise exception 'Structured candidate set exceeds safe claim limit'
            using errcode = '54000',
                  detail = jsonb_build_object(
                      'candidate_claim_count', candidate_claim_count,
                      'limit', p_limit
                  )::text;
    end if;

    return query
    select
        claims.id,
        claims.snapshot_id,
        claims.document_id,
        documents.version_number,
        snapshots.snapshot_key,
        snapshots.schema_fingerprint,
        snapshots.template_fingerprint,
        snapshots.normalized_schema,
        claims.candidate_identity_hash,
        jsonb_build_object(
            'id', claims.claim_key,
            'owner_id', claims.owner_id,
            'notebook_id', claims.notebook_id,
            'document_id', claims.document_id,
            'subject_key', claims.row_identity,
            'predicate', claims.predicate,
            'value', claims.normalized_value,
            'scope', claims.subject_identity - 'subject_key',
            'qualifiers', claims.qualifiers,
            'temporal', jsonb_build_object(
                'publication_time', claims.publication_time,
                'effective_from', claims.effective_from,
                'effective_to', claims.effective_to,
                'observed_at', claims.observed_at,
                'ingested_at', claims.ingested_at
            ),
            'provenance', claims.provenance,
            'extraction_confidence', claims.confidence,
            'extractor_version', claims.extractor_version,
            'derivation', case
                when claims.is_derived then claims.derivation
                else null
            end,
            'authority', case
                when jsonb_typeof(claims.authority_metadata -> 'metadata')
                    = 'object'
                then claims.authority_metadata
                else jsonb_build_object(
                    'source_type', claims.source_type,
                    'publisher', claims.source_publisher,
                    'approval_status', claims.authority_metadata -> 'approval_status',
                    'officiality', claims.authority_metadata -> 'officiality',
                    'authority_level', claims.authority_level,
                    'metadata', claims.authority_metadata
                        - array['approval_status', 'officiality']::text[]
                )
            end,
            'candidate_identity_hash', claims.candidate_identity_hash,
            'claim_identity_hash', claims.claim_key
        )
    from public.structured_claims as claims
    join public.table_snapshots as snapshots
      on snapshots.id = claims.snapshot_id
     and snapshots.document_id = claims.document_id
     and snapshots.notebook_id = claims.notebook_id
     and snapshots.owner_id = claims.owner_id
    join public.documents as documents
      on documents.id = claims.document_id
     and documents.notebook_id = claims.notebook_id
     and documents.owner_id = claims.owner_id
    where claims.owner_id = selected_document.owner_id
      and claims.notebook_id = selected_document.notebook_id
      and claims.document_id <> selected_document.id
      and claims.snapshot_id = any(matched_snapshot_ids)
      and documents.status = 'ready'
      and documents.is_active
      and documents.is_current
      and documents.canonical_document_id is null
    order by
        claims.candidate_identity_hash,
        documents.updated_at desc,
        snapshots.snapshot_key,
        claims.confidence desc,
        claims.id;
end;
$$;

revoke all on function public.load_structured_claim_candidates(
    uuid, uuid, text[], integer, text[]
) from public, anon, authenticated;
grant execute on function public.load_structured_claim_candidates(
    uuid, uuid, text[], integer, text[]
) to service_role;

-- Enterprise IAM/RBAC foundation (expand phase).
--
-- This migration is intentionally additive.  public.profiles remains the
-- compatibility profile used by the legacy notebook application and JWT hook;
-- public.user_profiles is the enterprise business profile.

create table if not exists public.user_profiles (
    user_id uuid primary key
        references auth.users (id) on delete cascade,
    company_user_id text unique,
    full_name text,
    status text not null default 'ACTIVE',
    created_at timestamptz not null default now(),
    updated_at timestamptz not null default now(),
    constraint user_profiles_company_user_id_length
        check (
            company_user_id is null
            or char_length(btrim(company_user_id)) between 1 and 100
        ),
    constraint user_profiles_full_name_length
        check (
            full_name is null
            or char_length(btrim(full_name)) between 1 and 200
        ),
    constraint user_profiles_status
        check (status in ('ACTIVE', 'LOCKED', 'DISABLED'))
);

create table if not exists public.roles (
    id uuid primary key default gen_random_uuid(),
    code text not null unique,
    name text not null,
    description text not null default '',
    status text not null default 'ACTIVE',
    created_at timestamptz not null default now(),
    updated_at timestamptz not null default now(),
    constraint roles_code_format
        check (code ~ '^[A-Z][A-Z0-9_]{1,99}$'),
    constraint roles_name_length
        check (char_length(btrim(name)) between 1 and 200),
    constraint roles_status
        check (status in ('ACTIVE', 'DISABLED'))
);

create table if not exists public.functional_permissions (
    id uuid primary key default gen_random_uuid(),
    code text not null unique,
    name text not null,
    description text not null default '',
    created_at timestamptz not null default now(),
    constraint functional_permissions_code_format
        check (code ~ '^[A-Z][A-Z0-9_]{1,99}$'),
    constraint functional_permissions_name_length
        check (char_length(btrim(name)) between 1 and 200)
);

create table if not exists public.user_roles (
    id uuid primary key default gen_random_uuid(),
    user_id uuid not null
        references auth.users (id) on delete cascade,
    role_id uuid not null
        references public.roles (id) on delete cascade,
    assigned_by uuid
        references auth.users (id) on delete set null,
    assigned_at timestamptz not null default now(),
    constraint user_roles_assignment_key unique (user_id, role_id)
);

create table if not exists public.role_permissions (
    id uuid primary key default gen_random_uuid(),
    role_id uuid not null
        references public.roles (id) on delete cascade,
    permission_id uuid not null
        references public.functional_permissions (id) on delete cascade,
    assigned_by uuid
        references auth.users (id) on delete set null,
    assigned_at timestamptz not null default now(),
    constraint role_permissions_assignment_key
        unique (role_id, permission_id)
);

create table if not exists public.groups (
    id uuid primary key default gen_random_uuid(),
    code text not null unique,
    name text not null,
    description text not null default '',
    status text not null default 'ACTIVE',
    created_at timestamptz not null default now(),
    updated_at timestamptz not null default now(),
    constraint groups_code_format
        check (code ~ '^[A-Z][A-Z0-9_]{1,99}$'),
    constraint groups_name_length
        check (char_length(btrim(name)) between 1 and 200),
    constraint groups_status
        check (status in ('ACTIVE', 'DISABLED'))
);

create table if not exists public.user_groups (
    id uuid primary key default gen_random_uuid(),
    user_id uuid not null
        references auth.users (id) on delete cascade,
    group_id uuid not null
        references public.groups (id) on delete cascade,
    added_by uuid
        references auth.users (id) on delete set null,
    joined_at timestamptz not null default now(),
    constraint user_groups_membership_key unique (user_id, group_id)
);

create table if not exists public.departments (
    id uuid primary key default gen_random_uuid(),
    code text not null unique,
    name text not null,
    description text not null default '',
    parent_department_id uuid
        references public.departments (id) on delete restrict,
    status text not null default 'ACTIVE',
    created_at timestamptz not null default now(),
    updated_at timestamptz not null default now(),
    constraint departments_code_format
        check (code ~ '^[A-Z][A-Z0-9_]{1,99}$'),
    constraint departments_name_length
        check (char_length(btrim(name)) between 1 and 200),
    constraint departments_not_self
        check (parent_department_id is null or parent_department_id <> id),
    constraint departments_status
        check (status in ('ACTIVE', 'DISABLED'))
);

create table if not exists public.user_departments (
    id uuid primary key default gen_random_uuid(),
    user_id uuid not null
        references auth.users (id) on delete cascade,
    department_id uuid not null
        references public.departments (id) on delete restrict,
    is_primary boolean not null default false,
    start_at timestamptz not null default now(),
    end_at timestamptz,
    assigned_by uuid
        references auth.users (id) on delete set null,
    constraint user_departments_effective_range
        check (end_at is null or start_at < end_at),
    constraint user_departments_membership_key
        unique (user_id, department_id, start_at)
);

create unique index if not exists user_departments_one_current_primary_idx
    on public.user_departments (user_id)
    where is_primary and end_at is null;
create index if not exists user_roles_user_idx
    on public.user_roles (user_id, role_id);
create index if not exists user_groups_user_idx
    on public.user_groups (user_id, group_id);
create index if not exists user_departments_user_effective_idx
    on public.user_departments (user_id, start_at, end_at);

-- A typed subject row preserves referential integrity for document ACLs.
create table if not exists public.access_subjects (
    id uuid primary key default gen_random_uuid(),
    subject_type text not null,
    user_id uuid references auth.users (id) on delete cascade,
    role_id uuid references public.roles (id) on delete cascade,
    group_id uuid references public.groups (id) on delete cascade,
    department_id uuid references public.departments (id) on delete cascade,
    created_at timestamptz not null default now(),
    constraint access_subjects_typed_identity check (
        (
            subject_type = 'USER'
            and user_id is not null
            and role_id is null and group_id is null and department_id is null
        )
        or (
            subject_type = 'ROLE'
            and role_id is not null
            and user_id is null and group_id is null and department_id is null
        )
        or (
            subject_type = 'GROUP'
            and group_id is not null
            and user_id is null and role_id is null and department_id is null
        )
        or (
            subject_type = 'DEPARTMENT'
            and department_id is not null
            and user_id is null and role_id is null and group_id is null
        )
    )
);

create unique index if not exists access_subjects_user_key
    on public.access_subjects (user_id) where subject_type = 'USER';
create unique index if not exists access_subjects_role_key
    on public.access_subjects (role_id) where subject_type = 'ROLE';
create unique index if not exists access_subjects_group_key
    on public.access_subjects (group_id) where subject_type = 'GROUP';
create unique index if not exists access_subjects_department_key
    on public.access_subjects (department_id) where subject_type = 'DEPARTMENT';

create or replace function public.set_enterprise_updated_at()
returns trigger
language plpgsql
set search_path = ''
as $$
begin
    new.updated_at = now();
    return new;
end;
$$;

revoke all on function public.set_enterprise_updated_at() from public, anon, authenticated;

drop trigger if exists user_profiles_set_updated_at on public.user_profiles;
create trigger user_profiles_set_updated_at
before update on public.user_profiles
for each row execute function public.set_enterprise_updated_at();

drop trigger if exists roles_set_updated_at on public.roles;
create trigger roles_set_updated_at
before update on public.roles
for each row execute function public.set_enterprise_updated_at();

drop trigger if exists groups_set_updated_at on public.groups;
create trigger groups_set_updated_at
before update on public.groups
for each row execute function public.set_enterprise_updated_at();

drop trigger if exists departments_set_updated_at on public.departments;
create trigger departments_set_updated_at
before update on public.departments
for each row execute function public.set_enterprise_updated_at();

-- A direct-parent check is not enough for an organizational tree: A -> B -> C
-- followed by A.parent = C would otherwise create a multi-node cycle.  Reject
-- the write before it can poison recursive ACL expansion.
create or replace function public.guard_enterprise_department_cycle()
returns trigger
language plpgsql
security definer
set search_path = ''
as $$
begin
    if new.parent_department_id is null then
        return new;
    end if;

    -- Serialize hierarchy-edge writes so two concurrent updates cannot each
    -- validate against a pre-cycle snapshot and then commit a cycle together.
    perform pg_catalog.pg_advisory_xact_lock(
        pg_catalog.hashtextextended('enterprise_department_hierarchy', 0)
    );

    if exists (
        with recursive ancestors(id, parent_department_id) as (
            select departments.id, departments.parent_department_id
            from public.departments
            where departments.id = new.parent_department_id

            union

            select departments.id, departments.parent_department_id
            from public.departments as departments
            join ancestors
              on departments.id = ancestors.parent_department_id
        )
        select 1
        from ancestors
        where ancestors.id = new.id
    ) then
        raise exception 'Department hierarchy cannot contain a cycle'
            using errcode = '23514';
    end if;
    return new;
end;
$$;

revoke all on function public.guard_enterprise_department_cycle()
from public, anon, authenticated;

drop trigger if exists departments_guard_cycle on public.departments;
create trigger departments_guard_cycle
before insert or update of parent_department_id on public.departments
for each row execute function public.guard_enterprise_department_cycle();

-- Existing identities are expanded into the enterprise profile without
-- changing the legacy JWT role contract.
insert into public.user_profiles (user_id, full_name)
select users.id, profiles.display_name
from auth.users as users
left join public.profiles as profiles on profiles.id = users.id
on conflict (user_id) do nothing;

insert into public.roles (code, name, description)
values
    ('ADMIN', 'Administrator', 'Enterprise administration capabilities.'),
    ('EMPLOYEE', 'Employee', 'Knowledge consumer capabilities.'),
    ('DOCUMENT_REVIEWER', 'Document reviewer', 'Document review capabilities.')
on conflict (code) do nothing;

insert into public.functional_permissions (code, name, description)
values
    ('ASK_KNOWLEDGE', 'Ask knowledge', 'Search and ask grounded questions.'),
    ('MANAGE_DOCUMENT', 'Manage document', 'Create and maintain logical documents.'),
    ('UPLOAD_DOCUMENT', 'Upload document', 'Upload document source files.'),
    ('REVIEW_DOCUMENT', 'Review document', 'Approve, reject or request reprocessing.'),
    ('PUBLISH_DOCUMENT', 'Publish document', 'Activate reviewed document versions.'),
    ('ARCHIVE_DOCUMENT', 'Archive document', 'Archive published or draft documents.'),
    ('MANAGE_USER', 'Manage user', 'Manage enterprise user profiles.'),
    ('MANAGE_ROLE', 'Manage role', 'Manage roles and functional permissions.'),
    ('MANAGE_GROUP', 'Manage group', 'Manage groups and membership.'),
    ('MANAGE_DEPARTMENT', 'Manage department', 'Manage department hierarchy.'),
    ('MANAGE_ACCESS_POLICY', 'Manage access policy', 'Grant and revoke document ACLs.'),
    ('VIEW_AUDIT', 'View audit', 'View enterprise governance audit records.')
on conflict (code) do nothing;

insert into public.role_permissions (role_id, permission_id)
select roles.id, permissions.id
from public.roles as roles
cross join public.functional_permissions as permissions
where roles.code = 'ADMIN'
on conflict (role_id, permission_id) do nothing;

insert into public.role_permissions (role_id, permission_id)
select roles.id, permissions.id
from public.roles as roles
join public.functional_permissions as permissions
  on permissions.code = 'ASK_KNOWLEDGE'
where roles.code = 'EMPLOYEE'
on conflict (role_id, permission_id) do nothing;

insert into public.role_permissions (role_id, permission_id)
select roles.id, permissions.id
from public.roles as roles
join public.functional_permissions as permissions
  on permissions.code in ('ASK_KNOWLEDGE', 'REVIEW_DOCUMENT')
where roles.code = 'DOCUMENT_REVIEWER'
on conflict (role_id, permission_id) do nothing;

-- Preserve the legacy admin/user assignment as an initial RBAC assignment.
insert into public.user_roles (user_id, role_id)
select profiles.id, roles.id
from public.profiles as profiles
join public.roles as roles
  on roles.code = case when profiles.role = 'admin' then 'ADMIN' else 'EMPLOYEE' end
on conflict (user_id, role_id) do nothing;

insert into public.user_roles (user_id, role_id)
select user_profiles.user_id, roles.id
from public.user_profiles
cross join public.roles
where roles.code = 'EMPLOYEE'
  and not exists (
      select 1
      from public.user_roles
      where user_roles.user_id = user_profiles.user_id
  )
on conflict (user_id, role_id) do nothing;

-- System roles are stable identifiers used by the compatibility bridge and by
-- recovery procedures. They may be renamed descriptively, but their code,
-- active state and identity must not be destroyed through an application API.
create or replace function public.protect_enterprise_system_role()
returns trigger
language plpgsql
security definer
set search_path = ''
as $$
begin
    if old.code in ('ADMIN', 'EMPLOYEE', 'DOCUMENT_REVIEWER') then
        if tg_op = 'DELETE' then
            raise exception 'Enterprise system roles cannot be deleted, recoded or disabled'
                using errcode = '55000';
        end if;
        if new.id is distinct from old.id
           or new.code is distinct from old.code
           or new.status <> 'ACTIVE' then
            raise exception 'Enterprise system roles cannot be deleted, recoded or disabled'
                using errcode = '55000';
        end if;
    end if;
    if tg_op = 'DELETE' then
        return old;
    end if;
    return new;
end;
$$;

revoke all on function public.protect_enterprise_system_role()
from public, anon, authenticated;

drop trigger if exists roles_protect_system_role on public.roles;
create trigger roles_protect_system_role
before update or delete on public.roles
for each row execute function public.protect_enterprise_system_role();

create or replace function public.prevent_enterprise_iam_root_delete()
returns trigger
language plpgsql
security definer
set search_path = ''
as $$
begin
    raise exception 'Enterprise IAM root entities must be disabled, not deleted'
        using errcode = '55000';
end;
$$;

revoke all on function public.prevent_enterprise_iam_root_delete()
from public, anon, authenticated;

drop trigger if exists roles_prevent_root_delete on public.roles;
create trigger roles_prevent_root_delete
before delete on public.roles
for each row execute function public.prevent_enterprise_iam_root_delete();

drop trigger if exists groups_prevent_root_delete on public.groups;
create trigger groups_prevent_root_delete
before delete on public.groups
for each row execute function public.prevent_enterprise_iam_root_delete();

drop trigger if exists departments_prevent_root_delete on public.departments;
create trigger departments_prevent_root_delete
before delete on public.departments
for each row execute function public.prevent_enterprise_iam_root_delete();

-- The ADMIN role is the recovery root. Removing one of its permission edges
-- can silently lock every administrator out, so those seeded edges are fixed.
create or replace function public.protect_enterprise_admin_permissions()
returns trigger
language plpgsql
security definer
set search_path = ''
as $$
begin
    if exists (
        select 1
        from public.roles
        where roles.id = old.role_id
          and roles.code = 'ADMIN'
    ) then
        raise exception 'ADMIN permissions cannot be removed or reassigned'
            using errcode = '55000';
    end if;
    if tg_op = 'DELETE' then
        return old;
    end if;
    return new;
end;
$$;

revoke all on function public.protect_enterprise_admin_permissions()
from public, anon, authenticated;

drop trigger if exists role_permissions_protect_admin
on public.role_permissions;
create trigger role_permissions_protect_admin
before update or delete on public.role_permissions
for each row execute function public.protect_enterprise_admin_permissions();

-- Preserve at least one ACTIVE identity assigned to ADMIN. This guard covers
-- both assignment removal and profile lock/disable, including service-role
-- maintenance paths that bypass RLS.
create or replace function public.protect_last_enterprise_admin_assignment()
returns trigger
language plpgsql
security definer
set search_path = ''
as $$
declare
    old_is_active_admin boolean;
    new_is_active_admin boolean := false;
begin
    select exists (
        select 1
        from public.roles
        join public.user_profiles
          on user_profiles.user_id = old.user_id
        where roles.id = old.role_id
          and roles.code = 'ADMIN'
          and user_profiles.status = 'ACTIVE'
    ) into old_is_active_admin;

    if not old_is_active_admin then
        if tg_op = 'DELETE' then
            return old;
        end if;
        return new;
    end if;

    perform 1
    from public.roles
    where roles.code = 'ADMIN'
    for update;

    if tg_op = 'UPDATE' then
        select exists (
            select 1
            from public.roles
            join public.user_profiles
              on user_profiles.user_id = new.user_id
            where roles.id = new.role_id
              and roles.code = 'ADMIN'
              and user_profiles.status = 'ACTIVE'
        ) into new_is_active_admin;
    end if;

    if not new_is_active_admin and not exists (
        select 1
        from public.user_roles as assignments
        join public.roles as roles
          on roles.id = assignments.role_id
         and roles.code = 'ADMIN'
        join public.user_profiles as profiles
          on profiles.user_id = assignments.user_id
         and profiles.status = 'ACTIVE'
        where assignments.id <> old.id
    ) then
        raise exception 'At least one ACTIVE enterprise administrator is required'
            using errcode = '55000';
    end if;

    if tg_op = 'DELETE' then
        return old;
    end if;
    return new;
end;
$$;

revoke all on function public.protect_last_enterprise_admin_assignment()
from public, anon, authenticated;

drop trigger if exists user_roles_protect_last_admin on public.user_roles;
create trigger user_roles_protect_last_admin
before update or delete on public.user_roles
for each row execute function public.protect_last_enterprise_admin_assignment();

create or replace function public.protect_last_enterprise_admin_profile()
returns trigger
language plpgsql
security definer
set search_path = ''
as $$
declare
    loses_active_status boolean;
begin
    if tg_op = 'DELETE' then
        loses_active_status := true;
    else
        loses_active_status := new.status <> 'ACTIVE';
    end if;

    if old.status = 'ACTIVE'
       and loses_active_status
       and exists (
           select 1
           from public.user_roles
           join public.roles on roles.id = user_roles.role_id
           where user_roles.user_id = old.user_id
             and roles.code = 'ADMIN'
       ) then
        perform 1
        from public.roles
        where roles.code = 'ADMIN'
        for update;

        if not exists (
           select 1
           from public.user_roles
           join public.roles on roles.id = user_roles.role_id
           join public.user_profiles
             on user_profiles.user_id = user_roles.user_id
           where roles.code = 'ADMIN'
             and user_profiles.status = 'ACTIVE'
             and user_profiles.user_id <> old.user_id
        ) then
            raise exception 'At least one ACTIVE enterprise administrator is required'
                using errcode = '55000';
        end if;
    end if;
    if tg_op = 'DELETE' then
        return old;
    end if;
    return new;
end;
$$;

revoke all on function public.protect_last_enterprise_admin_profile()
from public, anon, authenticated;

drop trigger if exists user_profiles_protect_last_admin on public.user_profiles;
create trigger user_profiles_protect_last_admin
before update of status on public.user_profiles
for each row execute function public.protect_last_enterprise_admin_profile();

drop trigger if exists user_profiles_protect_last_admin_delete
on public.user_profiles;
create trigger user_profiles_protect_last_admin_delete
before delete on public.user_profiles
for each row execute function public.protect_last_enterprise_admin_profile();

insert into public.access_subjects (subject_type, user_id)
select 'USER', user_profiles.user_id
from public.user_profiles
on conflict (user_id) where subject_type = 'USER' do nothing;

insert into public.access_subjects (subject_type, role_id)
select 'ROLE', roles.id from public.roles
on conflict (role_id) where subject_type = 'ROLE' do nothing;

insert into public.access_subjects (subject_type, group_id)
select 'GROUP', groups.id from public.groups
on conflict (group_id) where subject_type = 'GROUP' do nothing;

insert into public.access_subjects (subject_type, department_id)
select 'DEPARTMENT', departments.id from public.departments
on conflict (department_id) where subject_type = 'DEPARTMENT' do nothing;

create or replace function public.ensure_enterprise_access_subject()
returns trigger
language plpgsql
security definer
set search_path = ''
as $$
begin
    if tg_table_name = 'user_profiles' then
        insert into public.access_subjects (subject_type, user_id)
        values ('USER', new.user_id)
        on conflict (user_id) where subject_type = 'USER' do nothing;
    elsif tg_table_name = 'roles' then
        insert into public.access_subjects (subject_type, role_id)
        values ('ROLE', new.id)
        on conflict (role_id) where subject_type = 'ROLE' do nothing;
    elsif tg_table_name = 'groups' then
        insert into public.access_subjects (subject_type, group_id)
        values ('GROUP', new.id)
        on conflict (group_id) where subject_type = 'GROUP' do nothing;
    elsif tg_table_name = 'departments' then
        insert into public.access_subjects (subject_type, department_id)
        values ('DEPARTMENT', new.id)
        on conflict (department_id) where subject_type = 'DEPARTMENT' do nothing;
    end if;
    return new;
end;
$$;

revoke all on function public.ensure_enterprise_access_subject()
from public, anon, authenticated;

drop trigger if exists user_profiles_ensure_access_subject on public.user_profiles;
create trigger user_profiles_ensure_access_subject
after insert on public.user_profiles
for each row execute function public.ensure_enterprise_access_subject();

drop trigger if exists roles_ensure_access_subject on public.roles;
create trigger roles_ensure_access_subject
after insert on public.roles
for each row execute function public.ensure_enterprise_access_subject();

drop trigger if exists groups_ensure_access_subject on public.groups;
create trigger groups_ensure_access_subject
after insert on public.groups
for each row execute function public.ensure_enterprise_access_subject();

drop trigger if exists departments_ensure_access_subject on public.departments;
create trigger departments_ensure_access_subject
after insert on public.departments
for each row execute function public.ensure_enterprise_access_subject();

-- The legacy signup trigger inserts public.profiles.  Mirroring that row keeps
-- future signups in the enterprise identity model without replacing the
-- existing auth hook during the expand phase.
create or replace function public.sync_legacy_profile_to_enterprise()
returns trigger
language plpgsql
security definer
set search_path = ''
as $$
begin
    insert into public.user_profiles (user_id, full_name)
    values (new.id, new.display_name)
    on conflict (user_id) do update
    set full_name = coalesce(excluded.full_name, public.user_profiles.full_name);

    if tg_op = 'INSERT' or old.role is distinct from new.role then
        if tg_op = 'UPDATE' then
            -- During expand, public.profiles remains the source for its two
            -- legacy roles. Removing the previous mapping prevents a demoted
            -- legacy admin from retaining ADMIN through stale compatibility
            -- data. Display-name-only updates must not restore an assignment
            -- that an Enterprise administrator intentionally removed.
            delete from public.user_roles
            using public.roles
            where user_roles.user_id = new.id
              and user_roles.role_id = roles.id
              and roles.code in ('ADMIN', 'EMPLOYEE');
        end if;

        insert into public.user_roles (user_id, role_id)
        select
            new.id,
            roles.id
        from public.roles
        where roles.code = case when new.role = 'admin' then 'ADMIN' else 'EMPLOYEE' end
        on conflict (user_id, role_id) do nothing;
    end if;
    return new;
end;
$$;

revoke all on function public.sync_legacy_profile_to_enterprise()
from public, anon, authenticated;

drop trigger if exists profiles_sync_enterprise_identity on public.profiles;
create trigger profiles_sync_enterprise_identity
after insert or update of display_name, role on public.profiles
for each row execute function public.sync_legacy_profile_to_enterprise();

create or replace function public.has_functional_permission(
    p_user_id uuid,
    p_permission_code text
)
returns boolean
language sql
stable
security definer
set search_path = ''
as $$
    select coalesce(exists (
        select 1
        from public.user_profiles as user_profiles
        join public.user_roles as user_roles
          on user_roles.user_id = user_profiles.user_id
        join public.roles as roles
          on roles.id = user_roles.role_id
         and roles.status = 'ACTIVE'
        join public.role_permissions as role_permissions
          on role_permissions.role_id = roles.id
        join public.functional_permissions as permissions
          on permissions.id = role_permissions.permission_id
        where user_profiles.user_id = p_user_id
          and user_profiles.status = 'ACTIVE'
          and permissions.code = upper(btrim(p_permission_code))
    ), false);
$$;

revoke all on function public.has_functional_permission(uuid, text)
from public, anon;
grant execute on function public.has_functional_permission(uuid, text)
to authenticated, service_role;

create or replace function public.get_principal_context()
returns jsonb
language sql
stable
security definer
set search_path = ''
as $$
    select case
        when auth.uid() is null then null
        when not exists (
            select 1 from public.user_profiles
            where user_id = auth.uid() and status = 'ACTIVE'
        ) then null
        else jsonb_build_object(
            'user_id', auth.uid(),
            'status', 'ACTIVE',
            'roles', coalesce((
                select jsonb_agg(
                    jsonb_build_object(
                        'id', roles.id,
                        'code', roles.code,
                        'name', roles.name,
                        'description', roles.description,
                        'status', roles.status,
                        'created_at', roles.created_at,
                        'updated_at', roles.updated_at
                    ) order by roles.code
                )
                from public.user_roles
                join public.roles on roles.id = user_roles.role_id
                where user_roles.user_id = auth.uid()
                  and roles.status = 'ACTIVE'
            ), '[]'::jsonb),
            'permissions', coalesce((
                select jsonb_agg(distinct permissions.code)
                from public.user_roles
                join public.roles on roles.id = user_roles.role_id
                join public.role_permissions on role_permissions.role_id = roles.id
                join public.functional_permissions as permissions
                  on permissions.id = role_permissions.permission_id
                where user_roles.user_id = auth.uid()
                  and roles.status = 'ACTIVE'
            ), '[]'::jsonb),
            'group_ids', coalesce((
                select jsonb_agg(groups.id order by groups.id)
                from public.user_groups
                join public.groups on groups.id = user_groups.group_id
                where user_groups.user_id = auth.uid()
                  and groups.status = 'ACTIVE'
            ), '[]'::jsonb),
            'department_ids', coalesce((
                select jsonb_agg(user_departments.department_id order by user_departments.department_id)
                from public.user_departments
                join public.departments
                  on departments.id = user_departments.department_id
                where user_departments.user_id = auth.uid()
                  and user_departments.start_at <= now()
                  and (user_departments.end_at is null or user_departments.end_at > now())
                  and departments.status = 'ACTIVE'
            ), '[]'::jsonb)
        )
    end;
$$;

revoke all on function public.get_principal_context() from public, anon;
grant execute on function public.get_principal_context()
to authenticated, service_role;

comment on table public.user_profiles is
    'Enterprise business identity extension; authentication remains in auth.users.';
comment on table public.access_subjects is
    'Typed ACL principal with a real foreign key to exactly one user, role, group or department.';
comment on function public.get_principal_context() is
    'Resolves current DB memberships so JWT role/group claims cannot become stale authorization state.';

-- Enterprise logical-document, version, review/publication and ACL model.
-- Run after 17_enterprise_iam.sql.
--
-- Expand/cutover contract:
--   * public.documents remains the legacy immutable uploaded-file row.
--   * public.knowledge_documents is the new logical document.
--   * public.document_versions.legacy_document_id maps one legacy row to one
--     enterprise version while application code is migrated.
--   * no legacy row is automatically PUBLISHED or ACTIVE during backfill.

create table if not exists public.knowledge_documents (
    id uuid primary key default gen_random_uuid(),
    title text not null,
    description text not null default '',
    document_type text not null default 'GENERAL',
    category text,
    document_number text,
    issued_date date,
    effective_date date,
    expiration_date date,
    source text,
    owner_department_id uuid
        references public.departments (id) on delete restrict,
    status text not null default 'DRAFT',
    metadata jsonb not null default '{}'::jsonb,
    created_by uuid not null default auth.uid()
        references auth.users (id) on delete restrict,
    created_at timestamptz not null default now(),
    updated_at timestamptz not null default now(),
    archived_by uuid references auth.users (id) on delete set null,
    archived_at timestamptz,
    archive_reason text,
    legacy_notebook_id uuid
        references public.notebooks (id) on delete set null,
    legacy_version_group_id uuid,
    constraint knowledge_documents_title_length
        check (char_length(btrim(title)) between 1 and 500),
    constraint knowledge_documents_type_length
        check (char_length(btrim(document_type)) between 1 and 100),
    constraint knowledge_documents_status
        check (status in ('DRAFT', 'PUBLISHED', 'ARCHIVED')),
    constraint knowledge_documents_metadata
        check (jsonb_typeof(metadata) = 'object'),
    constraint knowledge_documents_effective_range
        check (
            effective_date is null
            or expiration_date is null
            or effective_date <= expiration_date
        ),
    constraint knowledge_documents_archive_state check (
        (
            status = 'ARCHIVED'
            and archived_at is not null
            and archived_by is not null
            and archive_reason is not null
            and char_length(btrim(archive_reason)) > 0
        )
        or (
            status <> 'ARCHIVED'
            and archived_at is null
            and archived_by is null
            and archive_reason is null
        )
    )
);

create unique index if not exists knowledge_documents_legacy_lineage_key
    on public.knowledge_documents (
        created_by,
        legacy_notebook_id,
        legacy_version_group_id
    )
    where legacy_notebook_id is not null
      and legacy_version_group_id is not null;
create index if not exists knowledge_documents_status_idx
    on public.knowledge_documents (status, updated_at desc, id);
create index if not exists knowledge_documents_department_idx
    on public.knowledge_documents (owner_department_id, status, id)
    where owner_department_id is not null;

create table if not exists public.source_files (
    id uuid primary key default gen_random_uuid(),
    bucket_name text not null,
    object_path text not null,
    original_file_name text not null,
    mime_type text not null,
    size_bytes bigint not null,
    sha256 text,
    created_by uuid not null default auth.uid()
        references auth.users (id) on delete restrict,
    created_at timestamptz not null default now(),
    legacy_document_id uuid unique
        references public.documents (id) on delete set null,
    constraint source_files_object_key unique (bucket_name, object_path),
    constraint source_files_name_length
        check (char_length(btrim(original_file_name)) between 1 and 500),
    constraint source_files_bucket_length
        check (char_length(btrim(bucket_name)) between 1 and 100),
    constraint source_files_object_path_length
        check (char_length(btrim(object_path)) between 1 and 2048),
    constraint source_files_size check (size_bytes > 0),
    constraint source_files_sha256
        check (sha256 is null or sha256 ~ '^[0-9a-f]{64}$')
);

create index if not exists source_files_sha256_idx
    on public.source_files (sha256) where sha256 is not null;
create index if not exists source_files_created_by_idx
    on public.source_files (created_by, created_at desc, id);

create table if not exists public.document_versions (
    id uuid primary key default gen_random_uuid(),
    document_id uuid not null
        references public.knowledge_documents (id) on delete cascade,
    version_number integer not null,
    source_file_id uuid not null
        references public.source_files (id) on delete restrict,
    status text not null default 'DRAFT',
    previous_version_id uuid,
    change_summary text not null default '',
    effective_date date,
    created_by uuid not null default auth.uid()
        references auth.users (id) on delete restrict,
    created_at timestamptz not null default now(),
    updated_at timestamptz not null default now(),
    legacy_document_id uuid unique
        references public.documents (id) on delete set null,
    constraint document_versions_number check (version_number > 0),
    constraint document_versions_status check (
        status in (
            'DRAFT',
            'READY_FOR_REVIEW',
            'ACTIVE',
            'REJECTED',
            'SUPERSEDED'
        )
    ),
    constraint document_versions_document_number_key
        unique (document_id, version_number),
    constraint document_versions_id_document_key unique (id, document_id),
    constraint document_versions_previous_not_self
        check (previous_version_id is null or previous_version_id <> id),
    constraint document_versions_previous_same_document_fk
        foreign key (previous_version_id, document_id)
        references public.document_versions (id, document_id)
        deferrable initially deferred
);

create unique index if not exists document_versions_one_active_per_document_idx
    on public.document_versions (document_id)
    where status = 'ACTIVE';
create index if not exists document_versions_document_created_idx
    on public.document_versions (document_id, version_number desc, id);
create index if not exists document_versions_source_file_idx
    on public.document_versions (source_file_id);

alter table public.knowledge_documents
    add column if not exists current_version_id uuid;

do $$
begin
    if not exists (
        select 1
        from pg_constraint
        where conrelid = 'public.knowledge_documents'::regclass
          and conname = 'knowledge_documents_current_version_same_document_fk'
    ) then
        alter table public.knowledge_documents
            add constraint knowledge_documents_current_version_same_document_fk
            foreign key (current_version_id, id)
            references public.document_versions (id, document_id)
            deferrable initially deferred;
    end if;
end;
$$;

drop trigger if exists knowledge_documents_set_updated_at
on public.knowledge_documents;
create trigger knowledge_documents_set_updated_at
before update on public.knowledge_documents
for each row execute function public.set_enterprise_updated_at();

drop trigger if exists document_versions_set_updated_at
on public.document_versions;
create trigger document_versions_set_updated_at
before update on public.document_versions
for each row execute function public.set_enterprise_updated_at();

create table if not exists public.document_version_status_history (
    id bigint generated always as identity primary key,
    document_version_id uuid not null
        references public.document_versions (id) on delete cascade,
    old_status text,
    new_status text not null,
    changed_by uuid references auth.users (id) on delete set null,
    changed_at timestamptz not null default now(),
    reason text,
    constraint document_version_status_history_old_status check (
        old_status is null
        or old_status in (
            'DRAFT', 'READY_FOR_REVIEW', 'ACTIVE', 'REJECTED', 'SUPERSEDED'
        )
    ),
    constraint document_version_status_history_new_status check (
        new_status in (
            'DRAFT', 'READY_FOR_REVIEW', 'ACTIVE', 'REJECTED', 'SUPERSEDED'
        )
    ),
    constraint document_version_status_history_changed
        check (old_status is distinct from new_status)
);

create index if not exists document_version_status_history_version_idx
    on public.document_version_status_history (
        document_version_id,
        changed_at desc,
        id desc
    );

create or replace function public.record_document_version_status_change()
returns trigger
language plpgsql
security definer
set search_path = ''
as $$
begin
    if tg_op = 'INSERT' then
        insert into public.document_version_status_history (
            document_version_id, old_status, new_status, changed_by, reason
        ) values (
            new.id,
            null,
            new.status,
            auth.uid(),
            nullif(current_setting('app.status_change_reason', true), '')
        );
    elsif old.status is distinct from new.status then
        insert into public.document_version_status_history (
            document_version_id, old_status, new_status, changed_by, reason
        ) values (
            new.id,
            old.status,
            new.status,
            auth.uid(),
            nullif(current_setting('app.status_change_reason', true), '')
        );
    end if;
    return new;
end;
$$;

revoke all on function public.record_document_version_status_change()
from public, anon, authenticated;

drop trigger if exists document_versions_record_status
on public.document_versions;
create trigger document_versions_record_status
after insert or update of status on public.document_versions
for each row execute function public.record_document_version_status_change();

create table if not exists public.document_reviews (
    id uuid primary key default gen_random_uuid(),
    document_version_id uuid not null
        references public.document_versions (id) on delete cascade,
    reviewed_by uuid not null default auth.uid()
        references auth.users (id) on delete restrict,
    decision text not null,
    review_note text,
    rejection_reason text,
    reviewed_at timestamptz not null default now(),
    constraint document_reviews_decision
        check (decision in ('APPROVE', 'REJECT', 'REPROCESS')),
    constraint document_reviews_rejection_reason check (
        (decision = 'REJECT' and rejection_reason is not null
            and char_length(btrim(rejection_reason)) > 0)
        or (decision <> 'REJECT' and rejection_reason is null)
    )
);

create index if not exists document_reviews_version_reviewed_idx
    on public.document_reviews (document_version_id, reviewed_at desc, id);

create table if not exists public.publications (
    id uuid primary key default gen_random_uuid(),
    document_id uuid not null
        references public.knowledge_documents (id) on delete restrict,
    document_version_id uuid not null,
    previous_active_version_id uuid,
    published_by uuid not null default auth.uid()
        references auth.users (id) on delete restrict,
    published_at timestamptz not null default now(),
    constraint publications_version_same_document_fk
        foreign key (document_version_id, document_id)
        references public.document_versions (id, document_id)
        on delete restrict,
    constraint publications_previous_version_same_document_fk
        foreign key (previous_active_version_id, document_id)
        references public.document_versions (id, document_id)
        on delete restrict,
    constraint publications_target_key unique (document_version_id),
    constraint publications_versions_differ
        check (
            previous_active_version_id is null
            or previous_active_version_id <> document_version_id
        )
);

create index if not exists publications_document_published_idx
    on public.publications (document_id, published_at desc, id);

create table if not exists public.document_permissions (
    id uuid primary key default gen_random_uuid(),
    document_id uuid not null
        references public.knowledge_documents (id) on delete cascade,
    subject_id uuid not null
        references public.access_subjects (id) on delete cascade,
    permission text not null,
    status text not null default 'ACTIVE',
    granted_by uuid not null default auth.uid()
        references auth.users (id) on delete restrict,
    granted_at timestamptz not null default now(),
    revoked_by uuid references auth.users (id) on delete set null,
    revoked_at timestamptz,
    constraint document_permissions_permission check (
        permission in (
            'READ',
            'DOWNLOAD',
            'MANAGE',
            'REVIEW',
            'PUBLISH',
            'ARCHIVE',
            'MANAGE_PERMISSION'
        )
    ),
    constraint document_permissions_status
        check (status in ('ACTIVE', 'REVOKED')),
    constraint document_permissions_revocation_state check (
        (
            status = 'ACTIVE'
            and revoked_by is null
            and revoked_at is null
        )
        or (
            status = 'REVOKED'
            and revoked_by is not null
            and revoked_at is not null
        )
    )
);

create unique index if not exists document_permissions_one_active_assignment_idx
    on public.document_permissions (document_id, subject_id, permission)
    where status = 'ACTIVE';
create index if not exists document_permissions_subject_document_idx
    on public.document_permissions (subject_id, document_id, permission)
    where status = 'ACTIVE';
create index if not exists document_permissions_document_idx
    on public.document_permissions (document_id, status, permission);

-- -------------------------------------------------------------------------
-- Compatibility backfill.  A lineage becomes one logical document.  Every
-- legacy file becomes one source file and one version.  ready files are only
-- READY_FOR_REVIEW; all other states remain DRAFT.  This fail-closed mapping
-- prevents an old private upload from becoming enterprise-searchable.
-- -------------------------------------------------------------------------

insert into public.source_files (
    bucket_name,
    object_path,
    original_file_name,
    mime_type,
    size_bytes,
    sha256,
    created_by,
    created_at,
    legacy_document_id
)
select
    documents.storage_bucket,
    documents.storage_object_path,
    documents.original_filename,
    documents.mime_type,
    documents.size_bytes,
    documents.content_hash,
    documents.owner_id,
    documents.created_at,
    documents.id
from public.documents
on conflict (legacy_document_id) do nothing;

insert into public.knowledge_documents (
    title,
    description,
    document_type,
    effective_date,
    status,
    metadata,
    created_by,
    created_at,
    updated_at,
    legacy_notebook_id,
    legacy_version_group_id
)
select
    (array_agg(
        documents.original_filename
        order by documents.version_number desc, documents.created_at desc, documents.id
    ))[1],
    '',
    coalesce(
        nullif((array_agg(
            documents.quality_metadata ->> 'document_type'
            order by documents.version_number desc, documents.created_at desc, documents.id
        ))[1], ''),
        'GENERAL'
    ),
    max(documents.effective_from),
    'DRAFT',
    jsonb_build_object(
        'migration', 'legacy_documents_expand_v1',
        'legacy_document_count', count(*)
    ),
    documents.owner_id,
    min(documents.created_at),
    max(documents.updated_at),
    documents.notebook_id,
    documents.version_group_id
from public.documents
group by documents.owner_id, documents.notebook_id, documents.version_group_id
on conflict (
    created_by, legacy_notebook_id, legacy_version_group_id
) where legacy_notebook_id is not null
    and legacy_version_group_id is not null
do nothing;

with ranked_legacy_versions as (
    select
        documents.*,
        row_number() over (
            partition by documents.owner_id, documents.notebook_id, documents.version_group_id
            order by documents.version_number, documents.created_at, documents.id
        )::integer as enterprise_version_number
    from public.documents
)
insert into public.document_versions (
    document_id,
    version_number,
    source_file_id,
    status,
    change_summary,
    effective_date,
    created_by,
    created_at,
    updated_at,
    legacy_document_id
)
select
    knowledge_documents.id,
    ranked_legacy_versions.enterprise_version_number,
    source_files.id,
    case
        when ranked_legacy_versions.status = 'ready' then 'READY_FOR_REVIEW'
        else 'DRAFT'
    end,
    case
        when ranked_legacy_versions.version_number
             <> ranked_legacy_versions.enterprise_version_number
        then 'Migrated from legacy version label '
             || ranked_legacy_versions.version_number::text || '.'
        else 'Migrated from the legacy notebook model.'
    end,
    ranked_legacy_versions.effective_from,
    ranked_legacy_versions.owner_id,
    ranked_legacy_versions.created_at,
    ranked_legacy_versions.updated_at,
    ranked_legacy_versions.id
from ranked_legacy_versions
join public.knowledge_documents
  on knowledge_documents.created_by = ranked_legacy_versions.owner_id
 and knowledge_documents.legacy_notebook_id = ranked_legacy_versions.notebook_id
 and knowledge_documents.legacy_version_group_id = ranked_legacy_versions.version_group_id
join public.source_files
  on source_files.legacy_document_id = ranked_legacy_versions.id
on conflict (legacy_document_id) do nothing;

update public.document_versions as versions
set previous_version_id = previous_versions.id
from public.documents as legacy_documents
join public.document_versions as previous_versions
  on previous_versions.legacy_document_id = legacy_documents.supersedes_document_id
where versions.legacy_document_id = legacy_documents.id
  and versions.document_id = previous_versions.document_id
  and versions.previous_version_id is null;

-- Preserve legacy owner access without publishing anything.  This is the
-- only compatibility grant; every other user remains default-denied.
insert into public.document_permissions (
    document_id, subject_id, permission, granted_by
)
select
    knowledge_documents.id,
    access_subjects.id,
    permissions.permission,
    knowledge_documents.created_by
from public.knowledge_documents
join public.access_subjects
  on access_subjects.subject_type = 'USER'
 and access_subjects.user_id = knowledge_documents.created_by
cross join (
    values
        ('READ'),
        ('DOWNLOAD'),
        ('MANAGE'),
        ('REVIEW'),
        ('PUBLISH'),
        ('ARCHIVE'),
        ('MANAGE_PERMISSION')
) as permissions(permission)
on conflict (
    document_id, subject_id, permission
) where status = 'ACTIVE'
do nothing;

comment on table public.knowledge_documents is
    'Enterprise logical documents. public.documents remains the legacy uploaded-file table during cutover.';
comment on table public.document_versions is
    'Immutable-source business versions; at most one ACTIVE version is enforced by a partial unique index.';
comment on column public.document_versions.legacy_document_id is
    'Expand-phase compatibility link; nullable after the application cuts over to enterprise uploads.';
comment on table public.document_permissions is
    'ALLOW-only document ACL history. Absence of an ACTIVE grant means DENY.';

-- Enterprise durable processing and RAG persistence.
-- Run after 18_enterprise_knowledge_acl.sql.

create table if not exists public.processing_jobs (
    id uuid primary key default gen_random_uuid(),
    document_version_id uuid not null
        references public.document_versions (id) on delete cascade,
    job_type text not null,
    status text not null default 'PENDING',
    current_stage text,
    attempt_no integer not null,
    previous_job_id uuid references public.processing_jobs (id) on delete restrict,
    requested_by uuid not null default auth.uid()
        references auth.users (id) on delete restrict,
    requested_at timestamptz not null default now(),
    started_at timestamptz,
    completed_at timestamptz,
    heartbeat_at timestamptz,
    lease_owner text,
    lease_expires_at timestamptz,
    claim_token uuid,
    embedding_model text not null default 'text-embedding-3-small',
    embedding_dimensions integer not null default 1536,
    configuration jsonb not null default '{}'::jsonb,
    error_code text,
    error_message text,
    legacy_ingestion_job_id uuid unique
        references public.ingestion_jobs (id) on delete set null,
    created_at timestamptz not null default now(),
    updated_at timestamptz not null default now(),
    constraint processing_jobs_type
        check (job_type in ('INITIAL_PROCESS', 'NEW_VERSION', 'REPROCESS')),
    constraint processing_jobs_status
        check (status in ('PENDING', 'RUNNING', 'SUCCEEDED', 'FAILED', 'CANCELLED')),
    constraint processing_jobs_stage check (
        current_stage is null
        or current_stage in (
            'FILE_VALIDATION',
            'EXTRACTION',
            'OCR',
            'PARSING',
            'CHUNKING',
            'CONTEXTUAL_ENRICHMENT',
            'EMBEDDING',
            'INDEXING',
            'FINALIZING'
        )
    ),
    constraint processing_jobs_attempt check (attempt_no > 0),
    constraint processing_jobs_attempt_key
        unique (document_version_id, attempt_no),
    constraint processing_jobs_previous_not_self
        check (previous_job_id is null or previous_job_id <> id),
    constraint processing_jobs_embedding_model
        check (char_length(btrim(embedding_model)) between 1 and 200),
    constraint processing_jobs_embedding_dimensions
        check (embedding_dimensions > 0),
    constraint processing_jobs_configuration
        check (jsonb_typeof(configuration) = 'object'),
    constraint processing_jobs_error_code
        check (error_code is null or char_length(btrim(error_code)) between 1 and 100),
    constraint processing_jobs_error_message
        check (error_message is null or char_length(btrim(error_message)) between 1 and 1000),
    constraint processing_jobs_lease_state check (
        (
            status = 'RUNNING'
            and lease_owner is not null
            and lease_expires_at is not null
            and claim_token is not null
            and started_at is not null
        )
        or (
            status <> 'RUNNING'
            and lease_owner is null
            and lease_expires_at is null
            and claim_token is null
        )
    ),
    constraint processing_jobs_completion_state check (
        (status in ('SUCCEEDED', 'FAILED', 'CANCELLED') and completed_at is not null)
        or (status in ('PENDING', 'RUNNING') and completed_at is null)
    )
);

create unique index if not exists processing_jobs_one_active_per_version_idx
    on public.processing_jobs (document_version_id)
    where status in ('PENDING', 'RUNNING');
create index if not exists processing_jobs_claimable_idx
    on public.processing_jobs (requested_at, id)
    where status in ('PENDING', 'RUNNING');
create index if not exists processing_jobs_version_created_idx
    on public.processing_jobs (document_version_id, created_at desc, id);

drop trigger if exists processing_jobs_set_updated_at on public.processing_jobs;
create trigger processing_jobs_set_updated_at
before update on public.processing_jobs
for each row execute function public.set_enterprise_updated_at();

create table if not exists public.processing_stage_history (
    id bigint generated always as identity primary key,
    processing_job_id uuid not null
        references public.processing_jobs (id) on delete cascade,
    stage text not null,
    status text not null,
    started_at timestamptz not null default now(),
    completed_at timestamptz,
    message text,
    constraint processing_stage_history_stage check (
        stage in (
            'FILE_VALIDATION',
            'EXTRACTION',
            'OCR',
            'PARSING',
            'CHUNKING',
            'CONTEXTUAL_ENRICHMENT',
            'EMBEDDING',
            'INDEXING',
            'FINALIZING'
        )
    ),
    constraint processing_stage_history_status
        check (status in ('STARTED', 'SUCCEEDED', 'FAILED', 'SKIPPED')),
    constraint processing_stage_history_time_range
        check (completed_at is null or started_at <= completed_at)
);

create index if not exists processing_stage_history_job_idx
    on public.processing_stage_history (processing_job_id, started_at, id);

create table if not exists public.processing_errors (
    id uuid primary key default gen_random_uuid(),
    processing_job_id uuid not null
        references public.processing_jobs (id) on delete cascade,
    stage text,
    error_type text not null,
    error_code text not null,
    safe_message text not null,
    internal_reference text,
    retryable boolean not null default false,
    created_at timestamptz not null default now(),
    constraint processing_errors_stage check (
        stage is null
        or stage in (
            'FILE_VALIDATION',
            'EXTRACTION',
            'OCR',
            'PARSING',
            'CHUNKING',
            'CONTEXTUAL_ENRICHMENT',
            'EMBEDDING',
            'INDEXING',
            'FINALIZING'
        )
    ),
    constraint processing_errors_type_length
        check (char_length(btrim(error_type)) between 1 and 200),
    constraint processing_errors_code_length
        check (char_length(btrim(error_code)) between 1 and 100),
    constraint processing_errors_safe_message_length
        check (char_length(btrim(safe_message)) between 1 and 1000)
);

create index if not exists processing_errors_job_created_idx
    on public.processing_errors (processing_job_id, created_at desc, id);

-- Keep the legacy durable queue operational during expand/cutover while every
-- job gains a version identity.
alter table public.ingestion_jobs
    add column if not exists document_version_id uuid;

update public.ingestion_jobs as jobs
set document_version_id = versions.id
from public.document_versions as versions
where versions.legacy_document_id = jobs.document_id
  and jobs.document_version_id is null;

do $$
begin
    if not exists (
        select 1 from pg_constraint
        where conrelid = 'public.ingestion_jobs'::regclass
          and conname = 'ingestion_jobs_document_version_fk'
    ) then
        alter table public.ingestion_jobs
            add constraint ingestion_jobs_document_version_fk
            foreign key (document_version_id)
            references public.document_versions (id)
            on delete cascade;
    end if;
end;
$$;

create or replace function public.resolve_legacy_ingestion_version()
returns trigger
language plpgsql
security definer
set search_path = ''
as $$
begin
    if new.document_version_id is null then
        select versions.id into new.document_version_id
        from public.document_versions as versions
        where versions.legacy_document_id = new.document_id;
    end if;
    if new.document_version_id is null then
        raise exception 'No enterprise document version maps legacy document %', new.document_id
            using errcode = '23503';
    end if;
    return new;
end;
$$;

revoke all on function public.resolve_legacy_ingestion_version()
from public, anon, authenticated;

drop trigger if exists ingestion_jobs_resolve_enterprise_version
on public.ingestion_jobs;
create trigger ingestion_jobs_resolve_enterprise_version
before insert or update of document_id, document_version_id
on public.ingestion_jobs
for each row execute function public.resolve_legacy_ingestion_version();

alter table public.ingestion_jobs
    alter column document_version_id set not null;

insert into public.processing_jobs (
    id,
    document_version_id,
    job_type,
    status,
    current_stage,
    attempt_no,
    requested_by,
    requested_at,
    started_at,
    completed_at,
    heartbeat_at,
    lease_owner,
    lease_expires_at,
    claim_token,
    embedding_model,
    embedding_dimensions,
    configuration,
    error_code,
    error_message,
    legacy_ingestion_job_id,
    created_at,
    updated_at
)
select
    jobs.id,
    jobs.document_version_id,
    case when jobs.attempt_number = 1 then 'INITIAL_PROCESS' else 'REPROCESS' end,
    upper(jobs.status),
    case
        when jobs.status = 'succeeded' then 'FINALIZING'
        else null
    end,
    jobs.attempt_number,
    jobs.owner_id,
    jobs.created_at,
    jobs.started_at,
    jobs.completed_at,
    case when jobs.status = 'running' then jobs.updated_at else null end,
    jobs.claimed_by,
    jobs.lease_expires_at,
    jobs.claim_token,
    jobs.embedding_model,
    jobs.embedding_dimensions,
    jobs.configuration,
    case when jobs.status = 'failed' then 'LEGACY_JOB_FAILED' else null end,
    case when jobs.status = 'failed' then 'The document could not be processed.' else null end,
    jobs.id,
    jobs.created_at,
    jobs.updated_at
from public.ingestion_jobs as jobs
on conflict (legacy_ingestion_job_id) do nothing;

update public.processing_jobs as jobs
set previous_job_id = previous_jobs.id
from public.processing_jobs as previous_jobs
where jobs.document_version_id = previous_jobs.document_version_id
  and jobs.attempt_no = previous_jobs.attempt_no + 1
  and jobs.previous_job_id is null;

insert into public.processing_errors (
    processing_job_id,
    error_type,
    error_code,
    safe_message,
    internal_reference,
    retryable
)
select
    processing_jobs.id,
    'LEGACY_INGESTION_ERROR',
    'LEGACY_JOB_FAILED',
    'The document could not be processed.',
    'ingestion_jobs/' || ingestion_jobs.id::text,
    true
from public.ingestion_jobs
join public.processing_jobs
  on processing_jobs.legacy_ingestion_job_id = ingestion_jobs.id
where ingestion_jobs.status = 'failed'
  and not exists (
      select 1
      from public.processing_errors
      where processing_errors.processing_job_id = processing_jobs.id
        and processing_errors.error_code = 'LEGACY_JOB_FAILED'
  );

create or replace function public.sync_legacy_ingestion_job_to_enterprise()
returns trigger
language plpgsql
security definer
set search_path = ''
as $$
begin
    insert into public.processing_jobs (
        id,
        document_version_id,
        job_type,
        status,
        current_stage,
        attempt_no,
        requested_by,
        requested_at,
        started_at,
        completed_at,
        heartbeat_at,
        lease_owner,
        lease_expires_at,
        claim_token,
        embedding_model,
        embedding_dimensions,
        configuration,
        error_code,
        error_message,
        legacy_ingestion_job_id,
        created_at,
        updated_at
    ) values (
        new.id,
        new.document_version_id,
        case when new.attempt_number = 1 then 'INITIAL_PROCESS' else 'REPROCESS' end,
        upper(new.status),
        case when new.status = 'succeeded' then 'FINALIZING' else null end,
        new.attempt_number,
        new.owner_id,
        new.created_at,
        new.started_at,
        new.completed_at,
        case when new.status = 'running' then new.updated_at else null end,
        new.claimed_by,
        new.lease_expires_at,
        new.claim_token,
        new.embedding_model,
        new.embedding_dimensions,
        new.configuration,
        case when new.status = 'failed' then 'LEGACY_JOB_FAILED' else null end,
        case when new.status = 'failed' then 'The document could not be processed.' else null end,
        new.id,
        new.created_at,
        new.updated_at
    )
    on conflict (legacy_ingestion_job_id) do update
    set status = excluded.status,
        current_stage = excluded.current_stage,
        started_at = excluded.started_at,
        completed_at = excluded.completed_at,
        heartbeat_at = excluded.heartbeat_at,
        lease_owner = excluded.lease_owner,
        lease_expires_at = excluded.lease_expires_at,
        claim_token = excluded.claim_token,
        configuration = excluded.configuration,
        error_code = excluded.error_code,
        error_message = excluded.error_message,
        updated_at = excluded.updated_at;
    return new;
end;
$$;

revoke all on function public.sync_legacy_ingestion_job_to_enterprise()
from public, anon, authenticated;

drop trigger if exists ingestion_jobs_sync_enterprise
on public.ingestion_jobs;
create trigger ingestion_jobs_sync_enterprise
after insert or update on public.ingestion_jobs
for each row execute function public.sync_legacy_ingestion_job_to_enterprise();

-- Version-qualify canonical chunks while retaining legacy document_id for the
-- old application.  The trigger makes legacy worker inserts forward-compatible.
alter table public.document_chunks
    add column if not exists document_version_id uuid,
    add column if not exists knowledge_document_id uuid;

update public.document_chunks as chunks
set document_version_id = versions.id,
    knowledge_document_id = versions.document_id
from public.document_versions as versions
where versions.legacy_document_id = chunks.document_id
  and (
      chunks.document_version_id is null
      or chunks.knowledge_document_id is null
  );

create or replace function public.resolve_enterprise_chunk_version()
returns trigger
language plpgsql
security definer
set search_path = ''
as $$
begin
    if new.document_version_id is null or new.knowledge_document_id is null then
        select versions.id, versions.document_id
        into new.document_version_id, new.knowledge_document_id
        from public.document_versions as versions
        where versions.legacy_document_id = new.document_id;
    end if;
    if new.document_version_id is null or new.knowledge_document_id is null then
        raise exception 'Chunk must resolve to an enterprise document version'
            using errcode = '23503';
    end if;
    return new;
end;
$$;

revoke all on function public.resolve_enterprise_chunk_version()
from public, anon, authenticated;

drop trigger if exists document_chunks_resolve_enterprise_version
on public.document_chunks;
create trigger document_chunks_resolve_enterprise_version
before insert or update of document_id, document_version_id, knowledge_document_id
on public.document_chunks
for each row execute function public.resolve_enterprise_chunk_version();

alter table public.document_chunks
    alter column document_version_id set not null,
    alter column knowledge_document_id set not null;

do $$
begin
    if not exists (
        select 1 from pg_constraint
        where conrelid = 'public.document_chunks'::regclass
          and conname = 'document_chunks_version_document_fk'
    ) then
        alter table public.document_chunks
            add constraint document_chunks_version_document_fk
            foreign key (document_version_id, knowledge_document_id)
            references public.document_versions (id, document_id)
            on delete cascade;
    end if;
    if not exists (
        select 1 from pg_constraint
        where conrelid = 'public.document_chunks'::regclass
          and conname = 'document_chunks_id_version_document_key'
    ) then
        alter table public.document_chunks
            add constraint document_chunks_id_version_document_key
            unique (id, document_version_id, knowledge_document_id);
    end if;
end;
$$;

create unique index if not exists document_chunks_version_index_key
    on public.document_chunks (document_version_id, chunk_index);
create index if not exists document_chunks_knowledge_version_idx
    on public.document_chunks (
        knowledge_document_id,
        document_version_id,
        chunk_index
    );

-- New enterprise versions do not have (and must not need) a legacy
-- public.documents row.  knowledge_chunks is therefore the canonical
-- Enterprise index; document_chunks remains the notebook compatibility index.
create table if not exists public.knowledge_chunks (
    id uuid primary key default gen_random_uuid(),
    document_id uuid not null,
    document_version_id uuid not null,
    chunk_index integer not null,
    content text not null,
    contextual_content text,
    token_count integer not null,
    content_hash text,
    page_start integer,
    page_end integer,
    section_path text,
    metadata jsonb not null default '{}'::jsonb,
    embedding vector(1536),
    search_vector tsvector generated always as (
        setweight(
            to_tsvector(
                'simple'::regconfig,
                coalesce(metadata #>> '{retrieval_metadata,title}', '')
            ),
            'A'
        )
        || setweight(
            to_tsvector(
                'simple'::regconfig,
                coalesce(
                    section_path,
                    metadata #>> '{retrieval_metadata,section_path}',
                    ''
                )
            ),
            'B'
        )
        || setweight(
            to_tsvector('simple'::regconfig, coalesce(contextual_content, '')),
            'C'
        )
        || setweight(to_tsvector('simple'::regconfig, content), 'D')
    ) stored,
    created_at timestamptz not null default now(),
    constraint knowledge_chunks_version_document_fk
        foreign key (document_version_id, document_id)
        references public.document_versions (id, document_id)
        on delete cascade,
    constraint knowledge_chunks_version_index_key
        unique (document_version_id, chunk_index),
    constraint knowledge_chunks_id_version_document_key
        unique (id, document_version_id, document_id),
    constraint knowledge_chunks_index check (chunk_index >= 0),
    constraint knowledge_chunks_content
        check (char_length(btrim(content)) > 0),
    constraint knowledge_chunks_token_count check (token_count > 0),
    constraint knowledge_chunks_content_hash check (
        content_hash is null or content_hash ~ '^[0-9a-f]{64}$'
    ),
    constraint knowledge_chunks_page_range check (
        (page_start is null or page_start > 0)
        and (page_end is null or page_end > 0)
        and (page_start is null or page_end is null or page_start <= page_end)
    ),
    constraint knowledge_chunks_metadata
        check (jsonb_typeof(metadata) = 'object')
);

create index if not exists knowledge_chunks_document_version_idx
    on public.knowledge_chunks (document_id, document_version_id, chunk_index);
create index if not exists knowledge_chunks_search_vector_idx
    on public.knowledge_chunks using gin (search_vector);
create index if not exists knowledge_chunks_embedding_hnsw_idx
    on public.knowledge_chunks using hnsw (embedding vector_cosine_ops);

insert into public.knowledge_chunks (
    id,
    document_id,
    document_version_id,
    chunk_index,
    content,
    contextual_content,
    token_count,
    content_hash,
    page_start,
    page_end,
    section_path,
    metadata,
    embedding,
    created_at
)
select
    chunks.id,
    chunks.knowledge_document_id,
    chunks.document_version_id,
    chunks.chunk_index,
    chunks.content,
    nullif(chunks.metadata #>> '{retrieval_metadata,contextual_summary}', ''),
    chunks.token_count,
    chunks.normalized_content_hash,
    case
        when coalesce(
            chunks.metadata #>> '{retrieval_metadata,page_start}',
            chunks.metadata ->> 'page_start'
        ) ~ '^[1-9][0-9]*$'
        then coalesce(
            chunks.metadata #>> '{retrieval_metadata,page_start}',
            chunks.metadata ->> 'page_start'
        )::integer
        else null
    end,
    case
        when coalesce(
            chunks.metadata #>> '{retrieval_metadata,page_end}',
            chunks.metadata ->> 'page_end'
        ) ~ '^[1-9][0-9]*$'
        then coalesce(
            chunks.metadata #>> '{retrieval_metadata,page_end}',
            chunks.metadata ->> 'page_end'
        )::integer
        else null
    end,
    coalesce(
        chunks.metadata #>> '{retrieval_metadata,section_path}',
        chunks.metadata ->> 'section_path'
    ),
    chunks.metadata,
    chunks.embedding,
    chunks.created_at
from public.document_chunks as chunks
on conflict (id) do nothing;

create or replace function public.sync_legacy_chunk_to_enterprise()
returns trigger
language plpgsql
security definer
set search_path = ''
as $$
begin
    if tg_op = 'DELETE' then
        delete from public.knowledge_chunks where id = old.id;
        return old;
    end if;

    insert into public.knowledge_chunks (
        id,
        document_id,
        document_version_id,
        chunk_index,
        content,
        contextual_content,
        token_count,
        content_hash,
        page_start,
        page_end,
        section_path,
        metadata,
        embedding,
        created_at
    ) values (
        new.id,
        new.knowledge_document_id,
        new.document_version_id,
        new.chunk_index,
        new.content,
        nullif(new.metadata #>> '{retrieval_metadata,contextual_summary}', ''),
        new.token_count,
        new.normalized_content_hash,
        case
            when coalesce(
                new.metadata #>> '{retrieval_metadata,page_start}',
                new.metadata ->> 'page_start'
            ) ~ '^[1-9][0-9]*$'
            then coalesce(
                new.metadata #>> '{retrieval_metadata,page_start}',
                new.metadata ->> 'page_start'
            )::integer
            else null
        end,
        case
            when coalesce(
                new.metadata #>> '{retrieval_metadata,page_end}',
                new.metadata ->> 'page_end'
            ) ~ '^[1-9][0-9]*$'
            then coalesce(
                new.metadata #>> '{retrieval_metadata,page_end}',
                new.metadata ->> 'page_end'
            )::integer
            else null
        end,
        coalesce(
            new.metadata #>> '{retrieval_metadata,section_path}',
            new.metadata ->> 'section_path'
        ),
        new.metadata,
        new.embedding,
        new.created_at
    )
    on conflict (id) do update
    set document_id = excluded.document_id,
        document_version_id = excluded.document_version_id,
        chunk_index = excluded.chunk_index,
        content = excluded.content,
        contextual_content = excluded.contextual_content,
        token_count = excluded.token_count,
        content_hash = excluded.content_hash,
        page_start = excluded.page_start,
        page_end = excluded.page_end,
        section_path = excluded.section_path,
        metadata = excluded.metadata,
        embedding = excluded.embedding;
    return new;
end;
$$;

revoke all on function public.sync_legacy_chunk_to_enterprise()
from public, anon, authenticated;

drop trigger if exists document_chunks_sync_enterprise
on public.document_chunks;
create trigger document_chunks_sync_enterprise
after insert or update or delete on public.document_chunks
for each row execute function public.sync_legacy_chunk_to_enterprise();

-- Existing message citations become version-addressable without breaking the
-- legacy message/chunk foreign keys.
alter table public.message_citations
    add column if not exists document_version_id uuid,
    add column if not exists knowledge_document_id uuid;

update public.message_citations as citations
set document_version_id = chunks.document_version_id,
    knowledge_document_id = chunks.knowledge_document_id
from public.document_chunks as chunks
where chunks.id = citations.chunk_id
  and (
      citations.document_version_id is null
      or citations.knowledge_document_id is null
  );

create or replace function public.resolve_enterprise_citation_version()
returns trigger
language plpgsql
security definer
set search_path = ''
as $$
begin
    select chunks.document_version_id, chunks.knowledge_document_id
    into new.document_version_id, new.knowledge_document_id
    from public.document_chunks as chunks
    where chunks.id = new.chunk_id;
    if new.document_version_id is null or new.knowledge_document_id is null then
        raise exception 'Citation chunk has no enterprise version identity'
            using errcode = '23503';
    end if;
    return new;
end;
$$;

revoke all on function public.resolve_enterprise_citation_version()
from public, anon, authenticated;

drop trigger if exists message_citations_resolve_enterprise_version
on public.message_citations;
create trigger message_citations_resolve_enterprise_version
before insert or update of chunk_id, document_version_id, knowledge_document_id
on public.message_citations
for each row execute function public.resolve_enterprise_citation_version();

alter table public.message_citations
    alter column document_version_id set not null,
    alter column knowledge_document_id set not null;

do $$
begin
    if not exists (
        select 1 from pg_constraint
        where conrelid = 'public.message_citations'::regclass
          and conname = 'message_citations_enterprise_chunk_fk'
    ) then
        alter table public.message_citations
            add constraint message_citations_enterprise_chunk_fk
            foreign key (chunk_id, document_version_id, knowledge_document_id)
            references public.document_chunks (
                id, document_version_id, knowledge_document_id
            )
            on delete cascade;
    end if;
end;
$$;

-- Notebook-free enterprise conversation persistence.
create table if not exists public.enterprise_conversations (
    id uuid primary key default gen_random_uuid(),
    user_id uuid not null default auth.uid()
        references auth.users (id) on delete cascade,
    title text not null default 'New chat',
    created_at timestamptz not null default now(),
    updated_at timestamptz not null default now(),
    constraint enterprise_conversations_title_length
        check (char_length(btrim(title)) between 1 and 200)
);

create index if not exists enterprise_conversations_user_updated_idx
    on public.enterprise_conversations (user_id, updated_at desc, id);
drop trigger if exists enterprise_conversations_set_updated_at
on public.enterprise_conversations;
create trigger enterprise_conversations_set_updated_at
before update on public.enterprise_conversations
for each row execute function public.set_enterprise_updated_at();

create table if not exists public.enterprise_messages (
    id uuid primary key default gen_random_uuid(),
    conversation_id uuid not null
        references public.enterprise_conversations (id) on delete cascade,
    role text not null,
    content text not null default '',
    answer_status text not null default 'COMPLETED',
    model text,
    input_tokens integer,
    output_tokens integer,
    error_code text,
    trace_id text,
    created_at timestamptz not null default now(),
    updated_at timestamptz not null default now(),
    constraint enterprise_messages_role
        check (role in ('USER', 'ASSISTANT', 'SYSTEM')),
    constraint enterprise_messages_content
        check (role <> 'USER' or char_length(btrim(content)) > 0),
    constraint enterprise_messages_answer_status check (
        answer_status in ('PENDING', 'COMPLETED', 'FAILED', 'CONTROLLED_NO_ANSWER')
    ),
    constraint enterprise_messages_input_tokens
        check (input_tokens is null or input_tokens >= 0),
    constraint enterprise_messages_output_tokens
        check (output_tokens is null or output_tokens >= 0)
);

create index if not exists enterprise_messages_conversation_created_idx
    on public.enterprise_messages (conversation_id, created_at, id);
drop trigger if exists enterprise_messages_set_updated_at
on public.enterprise_messages;
create trigger enterprise_messages_set_updated_at
before update on public.enterprise_messages
for each row execute function public.set_enterprise_updated_at();

create table if not exists public.enterprise_citations (
    id uuid primary key default gen_random_uuid(),
    answer_message_id uuid not null
        references public.enterprise_messages (id) on delete cascade,
    document_id uuid not null,
    document_version_id uuid not null,
    chunk_id uuid not null,
    page_number integer,
    quote_text text not null,
    citation_order integer not null,
    retrieval_score double precision,
    created_at timestamptz not null default now(),
    constraint enterprise_citations_chunk_version_fk
        foreign key (chunk_id, document_version_id, document_id)
        references public.knowledge_chunks (
            id, document_version_id, document_id
        ) on delete restrict,
    constraint enterprise_citations_order check (citation_order > 0),
    constraint enterprise_citations_page check (page_number is null or page_number > 0),
    constraint enterprise_citations_quote
        check (char_length(btrim(quote_text)) > 0),
    constraint enterprise_citations_message_order_key
        unique (answer_message_id, citation_order),
    constraint enterprise_citations_message_chunk_key
        unique (answer_message_id, chunk_id)
);

create index if not exists enterprise_citations_document_version_idx
    on public.enterprise_citations (document_id, document_version_id, chunk_id);

create table if not exists public.answer_feedback (
    id uuid primary key default gen_random_uuid(),
    message_id uuid not null
        references public.enterprise_messages (id) on delete cascade,
    user_id uuid not null default auth.uid()
        references auth.users (id) on delete cascade,
    rating text not null,
    reason text,
    comment text,
    created_at timestamptz not null default now(),
    updated_at timestamptz not null default now(),
    constraint answer_feedback_rating check (rating in ('UP', 'DOWN')),
    constraint answer_feedback_user_answer_key unique (message_id, user_id)
);

create index if not exists answer_feedback_created_idx
    on public.answer_feedback (created_at desc, id);
drop trigger if exists answer_feedback_set_updated_at on public.answer_feedback;
create trigger answer_feedback_set_updated_at
before update on public.answer_feedback
for each row execute function public.set_enterprise_updated_at();

create table if not exists public.answer_reports (
    id uuid primary key default gen_random_uuid(),
    message_id uuid not null
        references public.enterprise_messages (id) on delete cascade,
    reporter_user_id uuid not null default auth.uid()
        references auth.users (id) on delete restrict,
    reason_code text not null,
    details text,
    status text not null default 'OPEN',
    created_at timestamptz not null default now(),
    resolved_by uuid references auth.users (id) on delete set null,
    resolved_at timestamptz,
    resolution_note text,
    constraint answer_reports_type check (
        reason_code in (
            'INCORRECT',
            'MISSING_CITATION',
            'UNAUTHORIZED_CONTENT',
            'OUTDATED_INFORMATION',
            'OTHER'
        )
    ),
    constraint answer_reports_details
        check (details is null or char_length(btrim(details)) between 1 and 4000),
    constraint answer_reports_status
        check (status in ('OPEN', 'INVESTIGATING', 'RESOLVED', 'DISMISSED')),
    constraint answer_reports_resolution_state check (
        (
            status in ('RESOLVED', 'DISMISSED')
            and resolved_by is not null
            and resolved_at is not null
            and resolution_note is not null
            and char_length(btrim(resolution_note)) > 0
        )
        or (
            status in ('OPEN', 'INVESTIGATING')
            and resolved_by is null
            and resolved_at is null
            and resolution_note is null
        )
    )
);

create index if not exists answer_reports_status_created_idx
    on public.answer_reports (status, created_at desc, id);

create table if not exists public.audit_logs (
    id uuid primary key default gen_random_uuid(),
    actor_user_id uuid references auth.users (id) on delete set null,
    action text not null,
    entity_type text not null,
    entity_id uuid,
    before_data jsonb,
    after_data jsonb,
    metadata jsonb not null default '{}'::jsonb,
    request_id text,
    trace_id text,
    ip_address inet,
    note text,
    created_at timestamptz not null default now(),
    constraint audit_logs_action_length
        check (char_length(btrim(action)) between 1 and 200),
    constraint audit_logs_entity_type_length
        check (char_length(btrim(entity_type)) between 1 and 200),
    constraint audit_logs_before_object
        check (before_data is null or jsonb_typeof(before_data) = 'object'),
    constraint audit_logs_after_object
        check (after_data is null or jsonb_typeof(after_data) = 'object'),
    constraint audit_logs_metadata_object
        check (jsonb_typeof(metadata) = 'object')
);

create index if not exists audit_logs_entity_created_idx
    on public.audit_logs (entity_type, entity_id, created_at desc, id desc);
create index if not exists audit_logs_actor_created_idx
    on public.audit_logs (actor_user_id, created_at desc, id desc);

create or replace function public.prevent_enterprise_audit_mutation()
returns trigger
language plpgsql
set search_path = ''
as $$
begin
    raise exception 'audit_logs is append-only' using errcode = '55000';
end;
$$;

revoke all on function public.prevent_enterprise_audit_mutation()
from public, anon, authenticated;

drop trigger if exists audit_logs_immutable on public.audit_logs;
create trigger audit_logs_immutable
before update or delete on public.audit_logs
for each statement execute function public.prevent_enterprise_audit_mutation();

comment on table public.processing_jobs is
    'Version-scoped durable processing queue. Reprocessing creates a new job, never a new version.';
comment on column public.processing_errors.safe_message is
    'Sanitized user-facing failure text; implementation details belong only in internal_reference.';
comment on column public.document_chunks.document_version_id is
    'Enterprise version identity; legacy document_id is retained only for expand-phase compatibility.';
comment on table public.audit_logs is
    'Append-only enterprise business audit trail.';

-- Enterprise authorization helpers and atomic business operations.
-- Run after 19_enterprise_processing_rag.sql.

create or replace function public.enterprise_subject_ids_for_user(p_user_id uuid)
returns setof uuid
language sql
stable
security definer
set search_path = ''
as $$
    with recursive active_departments(department_id) as (
        select user_departments.department_id
        from public.user_departments
        join public.departments
          on departments.id = user_departments.department_id
         and departments.status = 'ACTIVE'
        where user_departments.user_id = p_user_id
          and user_departments.start_at <= now()
          and (user_departments.end_at is null or user_departments.end_at > now())

        union

        select parent_departments.id
        from public.departments as child_departments
        join active_departments
          on child_departments.id = active_departments.department_id
        join public.departments as parent_departments
          on parent_departments.id = child_departments.parent_department_id
         and parent_departments.status = 'ACTIVE'
    ), active_subjects as (
        select access_subjects.id
        from public.access_subjects
        join public.user_profiles
          on user_profiles.user_id = access_subjects.user_id
        where access_subjects.subject_type = 'USER'
          and access_subjects.user_id = p_user_id
          and user_profiles.status = 'ACTIVE'

        union

        select access_subjects.id
        from public.user_roles
        join public.roles
          on roles.id = user_roles.role_id
         and roles.status = 'ACTIVE'
        join public.access_subjects
          on access_subjects.subject_type = 'ROLE'
         and access_subjects.role_id = roles.id
        where user_roles.user_id = p_user_id

        union

        select access_subjects.id
        from public.user_groups
        join public.groups
          on groups.id = user_groups.group_id
         and groups.status = 'ACTIVE'
        join public.access_subjects
          on access_subjects.subject_type = 'GROUP'
         and access_subjects.group_id = groups.id
        where user_groups.user_id = p_user_id

        union

        select access_subjects.id
        from active_departments
        join public.access_subjects
          on access_subjects.subject_type = 'DEPARTMENT'
         and access_subjects.department_id = active_departments.department_id
    )
    select id from active_subjects;
$$;

revoke all on function public.enterprise_subject_ids_for_user(uuid)
from public, anon, authenticated;
grant execute on function public.enterprise_subject_ids_for_user(uuid)
to service_role;

create or replace function public.has_document_permission(
    p_user_id uuid,
    p_document_id uuid,
    p_permission text
)
returns boolean
language sql
stable
security definer
set search_path = ''
as $$
    select coalesce(
        p_user_id is not null
        and upper(btrim(coalesce(p_permission, ''))) in (
            'READ',
            'DOWNLOAD',
            'MANAGE',
            'REVIEW',
            'PUBLISH',
            'ARCHIVE',
            'MANAGE_PERMISSION'
        )
        and exists (
            select 1
            from public.user_profiles
            where user_id = p_user_id and status = 'ACTIVE'
        )
        and exists (
            select 1
            from public.document_permissions
            where document_permissions.document_id = p_document_id
              and document_permissions.subject_id in (
                  select public.enterprise_subject_ids_for_user(p_user_id)
              )
              and document_permissions.status = 'ACTIVE'
              and document_permissions.permission in (
                  upper(btrim(p_permission)),
                  'MANAGE'
              )
        ),
        false
    );
$$;

revoke all on function public.has_document_permission(uuid, uuid, text)
from public, anon;
grant execute on function public.has_document_permission(uuid, uuid, text)
to authenticated, service_role;

create or replace function public.test_document_access(
    p_user_id uuid,
    p_document_id uuid,
    p_permission text default 'READ'
)
returns boolean
language plpgsql
stable
security definer
set search_path = ''
as $$
declare
    actor uuid := auth.uid();
begin
    if actor is null then
        raise exception 'Authentication required' using errcode = '42501';
    end if;
    if actor <> p_user_id
       and not public.has_functional_permission(actor, 'MANAGE_ACCESS_POLICY') then
        raise exception 'Cannot test another principal''s access'
            using errcode = '42501';
    end if;
    return public.has_document_permission(
        p_user_id,
        p_document_id,
        upper(btrim(p_permission))
    );
end;
$$;

revoke all on function public.test_document_access(uuid, uuid, text)
from public, anon;
grant execute on function public.test_document_access(uuid, uuid, text)
to authenticated;

create or replace function public.write_enterprise_audit(
    p_action text,
    p_entity_type text,
    p_entity_id uuid,
    p_before_data jsonb default null,
    p_after_data jsonb default null,
    p_note text default null
)
returns uuid
language plpgsql
security definer
set search_path = ''
as $$
declare
    inserted_id uuid;
begin
    insert into public.audit_logs (
        actor_user_id,
        action,
        entity_type,
        entity_id,
        before_data,
        after_data,
        metadata,
        request_id,
        trace_id,
        note
    ) values (
        auth.uid(),
        p_action,
        p_entity_type,
        p_entity_id,
        p_before_data,
        p_after_data,
        jsonb_strip_nulls(jsonb_build_object(
            'before', p_before_data,
            'after', p_after_data,
            'note', p_note
        )),
        nullif(current_setting('request.headers', true)::jsonb ->> 'x-request-id', ''),
        nullif(current_setting('request.headers', true)::jsonb ->> 'x-trace-id', ''),
        p_note
    )
    returning id into inserted_id;
    return inserted_id;
end;
$$;

revoke all on function public.write_enterprise_audit(
    text, text, uuid, jsonb, jsonb, text
) from public, anon, authenticated;
grant execute on function public.write_enterprise_audit(
    text, text, uuid, jsonb, jsonb, text
) to service_role;

-- Tables intentionally managed through PostgREST still need an immutable
-- audit trail. Lifecycle tables use dedicated atomic RPC audits instead.
create or replace function public.audit_enterprise_table_change()
returns trigger
language plpgsql
security definer
set search_path = ''
as $$
declare
    before_payload jsonb := case when tg_op in ('UPDATE', 'DELETE')
        then to_jsonb(old) else null end;
    after_payload jsonb := case when tg_op in ('INSERT', 'UPDATE')
        then to_jsonb(new) else null end;
    entity_payload jsonb := coalesce(after_payload, before_payload);
    entity_id uuid;
begin
    entity_id := nullif(entity_payload ->> 'id', '')::uuid;
    perform public.write_enterprise_audit(
        'TABLE_' || upper(tg_table_name) || '_' || tg_op,
        tg_table_name,
        entity_id,
        before_payload,
        after_payload,
        null
    );
    if tg_op = 'DELETE' then
        return old;
    end if;
    return new;
end;
$$;

revoke all on function public.audit_enterprise_table_change()
from public, anon, authenticated;

do $audit_triggers$
declare
    audited_table text;
begin
    foreach audited_table in array array[
        'roles',
        'role_permissions',
        'user_roles',
        'groups',
        'user_groups',
        'departments',
        'user_departments',
        'source_files',
        'answer_feedback',
        'answer_reports'
    ]
    loop
        execute format(
            'drop trigger if exists %I on public.%I',
            audited_table || '_enterprise_audit',
            audited_table
        );
        execute format(
            'create trigger %I after insert or update or delete on public.%I '
            || 'for each row execute function public.audit_enterprise_table_change()',
            audited_table || '_enterprise_audit',
            audited_table
        );
    end loop;
end;
$audit_triggers$;

create or replace function public.upsert_user_profile(
    p_user_id uuid,
    p_company_user_id text default null,
    p_full_name text default null,
    p_status text default 'ACTIVE'
)
returns public.user_profiles
language plpgsql
security definer
set search_path = ''
as $$
declare
    actor uuid := auth.uid();
    before_profile jsonb;
    saved_profile public.user_profiles;
begin
    if actor is null
       or not public.has_functional_permission(actor, 'MANAGE_USER') then
        raise exception 'User management is not permitted' using errcode = '42501';
    end if;
    if not exists (select 1 from auth.users where id = p_user_id) then
        raise exception 'Auth user not found' using errcode = '23503';
    end if;

    select to_jsonb(user_profiles) into before_profile
    from public.user_profiles
    where user_id = p_user_id;

    insert into public.user_profiles (
        user_id, company_user_id, full_name, status
    ) values (
        p_user_id,
        nullif(btrim(p_company_user_id), ''),
        nullif(btrim(p_full_name), ''),
        upper(btrim(coalesce(p_status, 'ACTIVE')))
    )
    on conflict (user_id) do update
    set company_user_id = excluded.company_user_id,
        full_name = excluded.full_name,
        status = excluded.status
    returning * into saved_profile;

    perform public.write_enterprise_audit(
        case when before_profile is null then 'USER_PROFILE_CREATED'
             else 'USER_PROFILE_UPDATED' end,
        'user_profile',
        p_user_id,
        before_profile,
        to_jsonb(saved_profile),
        null
    );
    return saved_profile;
end;
$$;

revoke all on function public.upsert_user_profile(uuid, text, text, text)
from public, anon;
grant execute on function public.upsert_user_profile(uuid, text, text, text)
to authenticated;

create or replace function public.update_knowledge_document(
    p_document_id uuid,
    p_changes jsonb
)
returns public.knowledge_documents
language plpgsql
security definer
set search_path = ''
as $$
declare
    actor uuid := auth.uid();
    selected_document public.knowledge_documents;
    updated_document public.knowledge_documents;
begin
    if actor is null
       or not public.has_functional_permission(actor, 'MANAGE_DOCUMENT')
       or not public.has_document_permission(actor, p_document_id, 'MANAGE') then
        raise exception 'Document update is not permitted' using errcode = '42501';
    end if;
    if p_changes is null or jsonb_typeof(p_changes) <> 'object' then
        raise exception 'Changes must be a JSON object' using errcode = '22023';
    end if;
    if exists (
        select 1
        from jsonb_object_keys(p_changes) as keys(key)
        where keys.key not in (
            'title',
            'description',
            'document_type',
            'category',
            'document_number',
            'issued_date',
            'effective_date',
            'expiration_date',
            'source',
            'owner_department_id',
            'metadata'
        )
    ) then
        raise exception 'Changes contain a protected or unknown field'
            using errcode = '22023';
    end if;
    if p_changes ? 'metadata'
       and (
           p_changes -> 'metadata' = 'null'::jsonb
           or jsonb_typeof(p_changes -> 'metadata') <> 'object'
       ) then
        raise exception 'Metadata must be a JSON object' using errcode = '22023';
    end if;

    select * into selected_document
    from public.knowledge_documents
    where id = p_document_id
    for update;
    if not found or selected_document.status = 'ARCHIVED' then
        raise exception 'Document is missing or archived' using errcode = '55000';
    end if;

    update public.knowledge_documents
    set title = case when p_changes ? 'title'
            then btrim(p_changes ->> 'title') else title end,
        description = case when p_changes ? 'description'
            then coalesce(p_changes ->> 'description', '') else description end,
        document_type = case when p_changes ? 'document_type'
            then upper(btrim(p_changes ->> 'document_type')) else document_type end,
        category = case when p_changes ? 'category'
            then nullif(btrim(p_changes ->> 'category'), '') else category end,
        document_number = case when p_changes ? 'document_number'
            then nullif(btrim(p_changes ->> 'document_number'), '') else document_number end,
        issued_date = case when p_changes ? 'issued_date'
            then nullif(p_changes ->> 'issued_date', '')::date else issued_date end,
        effective_date = case when p_changes ? 'effective_date'
            then nullif(p_changes ->> 'effective_date', '')::date else effective_date end,
        expiration_date = case when p_changes ? 'expiration_date'
            then nullif(p_changes ->> 'expiration_date', '')::date else expiration_date end,
        source = case when p_changes ? 'source'
            then nullif(btrim(p_changes ->> 'source'), '') else source end,
        owner_department_id = case when p_changes ? 'owner_department_id'
            then nullif(p_changes ->> 'owner_department_id', '')::uuid
            else owner_department_id end,
        metadata = case when p_changes ? 'metadata'
            then p_changes -> 'metadata' else metadata end
    where id = p_document_id
    returning * into updated_document;

    perform public.write_enterprise_audit(
        'DOCUMENT_UPDATED',
        'knowledge_document',
        p_document_id,
        to_jsonb(selected_document),
        to_jsonb(updated_document),
        null
    );
    return updated_document;
end;
$$;

revoke all on function public.update_knowledge_document(uuid, jsonb)
from public, anon;
grant execute on function public.update_knowledge_document(uuid, jsonb)
to authenticated;

create or replace function public.create_knowledge_document(
    p_title text,
    p_description text default '',
    p_document_type text default 'GENERAL',
    p_category text default null,
    p_metadata jsonb default '{}'::jsonb
)
returns public.knowledge_documents
language plpgsql
security definer
set search_path = ''
as $$
declare
    actor uuid := auth.uid();
    created_document public.knowledge_documents;
    actor_subject_id uuid;
begin
    if actor is null
       or not public.has_functional_permission(actor, 'MANAGE_DOCUMENT') then
        raise exception 'Document creation is not permitted' using errcode = '42501';
    end if;
    if p_metadata is null or jsonb_typeof(p_metadata) <> 'object' then
        raise exception 'Metadata must be a JSON object' using errcode = '22023';
    end if;

    insert into public.knowledge_documents (
        title, description, document_type, category, metadata, created_by
    ) values (
        btrim(p_title),
        coalesce(p_description, ''),
        upper(btrim(coalesce(p_document_type, 'GENERAL'))),
        nullif(btrim(p_category), ''),
        p_metadata,
        actor
    ) returning * into created_document;

    select id into actor_subject_id
    from public.access_subjects
    where subject_type = 'USER' and user_id = actor;
    if actor_subject_id is null then
        raise exception 'Current user has no ACL subject' using errcode = '23503';
    end if;

    insert into public.document_permissions (
        document_id, subject_id, permission, granted_by
    )
    select created_document.id, actor_subject_id, permission, actor
    from (
        values
            ('READ'),
            ('DOWNLOAD'),
            ('MANAGE'),
            ('REVIEW'),
            ('PUBLISH'),
            ('ARCHIVE'),
            ('MANAGE_PERMISSION')
    ) as grants(permission);

    perform public.write_enterprise_audit(
        'DOCUMENT_CREATED',
        'knowledge_document',
        created_document.id,
        null,
        jsonb_build_object('status', created_document.status, 'title', created_document.title),
        null
    );
    return created_document;
end;
$$;

revoke all on function public.create_knowledge_document(
    text, text, text, text, jsonb
) from public, anon;
grant execute on function public.create_knowledge_document(
    text, text, text, text, jsonb
) to authenticated;

create or replace function public.create_document_version(
    p_document_id uuid,
    p_source_file_id uuid,
    p_change_summary text default '',
    p_effective_date date default null
)
returns public.document_versions
language plpgsql
security definer
set search_path = ''
as $$
declare
    actor uuid := auth.uid();
    selected_document public.knowledge_documents;
    selected_source public.source_files;
    created_version public.document_versions;
    previous_version uuid;
    next_version integer;
begin
    if actor is null
       or not public.has_document_permission(actor, p_document_id, 'MANAGE')
       or not public.has_functional_permission(actor, 'MANAGE_DOCUMENT') then
        raise exception 'Version creation is not permitted' using errcode = '42501';
    end if;

    select * into selected_document
    from public.knowledge_documents
    where id = p_document_id
    for update;
    if not found or selected_document.status = 'ARCHIVED' then
        raise exception 'Document is missing or archived' using errcode = '55000';
    end if;
    select files.* into selected_source
    from public.source_files as files
    where files.id = p_source_file_id
      and files.created_by = actor
    for update;
    if not found then
        raise exception 'Source file is not available' using errcode = '42501';
    end if;
    if exists (
        select 1
        from public.document_versions as versions
        where versions.source_file_id = p_source_file_id
    ) then
        raise exception 'Source file is already linked to a document version'
            using errcode = '23505';
    end if;
    if selected_source.sha256 is not null then
        perform pg_catalog.pg_advisory_xact_lock(
            pg_catalog.hashtextextended(selected_source.sha256, 0)
        );
        if exists (
            select 1
            from public.document_versions as versions
            join public.source_files as existing_sources
              on existing_sources.id = versions.source_file_id
            where existing_sources.sha256 = selected_source.sha256
        ) then
            raise exception 'An identical source file is already registered'
                using errcode = '23505';
        end if;
    end if;

    select coalesce(max(version_number), 0) + 1,
           (array_agg(id order by version_number desc))[1]
    into next_version, previous_version
    from public.document_versions
    where document_id = p_document_id;

    insert into public.document_versions (
        document_id,
        version_number,
        source_file_id,
        status,
        previous_version_id,
        change_summary,
        effective_date,
        created_by
    ) values (
        p_document_id,
        next_version,
        p_source_file_id,
        'DRAFT',
        previous_version,
        coalesce(p_change_summary, ''),
        p_effective_date,
        actor
    ) returning * into created_version;

    insert into public.processing_jobs (
        document_version_id,
        job_type,
        status,
        attempt_no,
        requested_by
    ) values (
        created_version.id,
        case when next_version = 1 then 'INITIAL_PROCESS' else 'NEW_VERSION' end,
        'PENDING',
        1,
        actor
    );

    perform public.write_enterprise_audit(
        'DOCUMENT_VERSION_CREATED',
        'document_version',
        created_version.id,
        null,
        jsonb_build_object(
            'document_id', p_document_id,
            'version_number', next_version,
            'status', created_version.status
        ),
        null
    );
    return created_version;
end;
$$;

revoke all on function public.create_document_version(
    uuid, uuid, text, date
) from public, anon;
grant execute on function public.create_document_version(
    uuid, uuid, text, date
) to authenticated;

create or replace function public.review_document_version(
    p_version_id uuid,
    p_decision text,
    p_note text default null,
    p_rejection_reason text default null
)
returns public.document_versions
language plpgsql
security definer
set search_path = ''
as $$
declare
    actor uuid := auth.uid();
    selected_version public.document_versions;
    selected_document public.knowledge_documents;
    previous_job public.processing_jobs;
    created_job public.processing_jobs;
    next_attempt integer;
    normalized_decision text := upper(btrim(coalesce(p_decision, '')));
begin
    select * into selected_version
    from public.document_versions
    where id = p_version_id;

    if not found
       or actor is null
       or not public.has_functional_permission(actor, 'REVIEW_DOCUMENT')
       or not public.has_document_permission(
           actor, selected_version.document_id, 'REVIEW'
       ) then
        raise exception 'Version review is not permitted' using errcode = '42501';
    end if;

    -- Lock the parent before the mutable version row so archive/review races
    -- serialize on the document lifecycle boundary.
    select * into selected_document
    from public.knowledge_documents
    where id = selected_version.document_id
    for update;
    if not found or selected_document.status = 'ARCHIVED' then
        raise exception 'Archived documents cannot be reviewed'
            using errcode = '55000';
    end if;

    select * into selected_version
    from public.document_versions
    where id = p_version_id
      and document_id = selected_document.id
    for update;
    if not found then
        raise exception 'Document version not found' using errcode = 'P0002';
    end if;
    if selected_version.status <> 'READY_FOR_REVIEW' then
        raise exception 'Only READY_FOR_REVIEW versions may be reviewed'
            using errcode = '55000';
    end if;
    if normalized_decision not in ('APPROVE', 'REJECT', 'REPROCESS') then
        raise exception 'Invalid review decision' using errcode = '22023';
    end if;
    if normalized_decision = 'REJECT'
       and nullif(btrim(coalesce(p_rejection_reason, '')), '') is null then
        raise exception 'A rejection reason is required' using errcode = '22023';
    end if;

    insert into public.document_reviews (
        document_version_id,
        reviewed_by,
        decision,
        review_note,
        rejection_reason
    ) values (
        p_version_id,
        actor,
        normalized_decision,
        nullif(btrim(p_note), ''),
        case
            when normalized_decision = 'REJECT'
            then nullif(btrim(p_rejection_reason), '')
            else null
        end
    );

    if normalized_decision in ('REJECT', 'REPROCESS') then
        perform set_config(
            'app.status_change_reason',
            'Review decision: ' || normalized_decision,
            true
        );
        update public.document_versions
        set status = case
                when normalized_decision = 'REJECT' then 'REJECTED'
                else 'DRAFT'
            end
        where id = p_version_id
        returning * into selected_version;
    end if;

    if normalized_decision = 'REPROCESS' then
        select jobs.* into previous_job
        from public.processing_jobs as jobs
        where jobs.document_version_id = p_version_id
        order by jobs.attempt_no desc, jobs.id desc
        for update
        limit 1;
        if not found then
            raise exception 'No completed processing job is available to reprocess'
                using errcode = '55000';
        end if;

        select coalesce(max(jobs.attempt_no), 0) + 1 into next_attempt
        from public.processing_jobs as jobs
        where jobs.document_version_id = p_version_id;

        insert into public.processing_jobs (
            document_version_id,
            job_type,
            status,
            attempt_no,
            previous_job_id,
            requested_by,
            embedding_model,
            embedding_dimensions,
            configuration
        ) values (
            p_version_id,
            'REPROCESS',
            'PENDING',
            next_attempt,
            previous_job.id,
            actor,
            previous_job.embedding_model,
            previous_job.embedding_dimensions,
            previous_job.configuration
        ) returning * into created_job;

        perform public.write_enterprise_audit(
            'PROCESSING_JOB_REPROCESSED_FROM_REVIEW',
            'processing_job',
            created_job.id,
            jsonb_build_object('previous_job_id', previous_job.id),
            jsonb_build_object(
                'document_version_id', p_version_id,
                'status', 'PENDING',
                'attempt_no', next_attempt
            ),
            p_note
        );
    end if;

    perform public.write_enterprise_audit(
        'DOCUMENT_VERSION_REVIEWED',
        'document_version',
        p_version_id,
        jsonb_build_object('status', 'READY_FOR_REVIEW'),
        jsonb_build_object(
            'status', selected_version.status,
            'decision', normalized_decision
        ),
        p_note
    );
    return selected_version;
end;
$$;

revoke all on function public.review_document_version(
    uuid, text, text, text
) from public, anon;
grant execute on function public.review_document_version(
    uuid, text, text, text
) to authenticated;

create or replace function public.publish_document_version(p_version_id uuid)
returns public.document_versions
language plpgsql
security definer
set search_path = ''
as $$
declare
    actor uuid := auth.uid();
    selected_version public.document_versions;
    selected_document public.knowledge_documents;
    previous_active_version_id uuid;
    previous_document_status text;
begin
    select * into selected_version
    from public.document_versions
    where id = p_version_id;
    if not found then
        raise exception 'Document version not found' using errcode = 'P0002';
    end if;

    select * into selected_document
    from public.knowledge_documents
    where id = selected_version.document_id
    for update;
    select * into selected_version
    from public.document_versions
    where id = p_version_id
    for update;

    if actor is null
       or not public.has_functional_permission(actor, 'PUBLISH_DOCUMENT')
       or not public.has_document_permission(actor, selected_document.id, 'PUBLISH') then
        raise exception 'Version publication is not permitted' using errcode = '42501';
    end if;
    if selected_document.status = 'ARCHIVED'
       or selected_version.status <> 'READY_FOR_REVIEW' then
        raise exception 'Version is not publishable' using errcode = '55000';
    end if;
    if not exists (
        select 1
        from public.document_reviews as reviews
        where reviews.document_version_id = p_version_id
          and reviews.decision = 'APPROVE'
          and reviews.id = (
              select latest_review.id
              from public.document_reviews as latest_review
              where latest_review.document_version_id = p_version_id
              order by latest_review.reviewed_at desc, latest_review.id desc
              limit 1
          )
          and reviews.reviewed_at >= (
              select max(jobs.completed_at)
              from public.processing_jobs as jobs
              where jobs.document_version_id = p_version_id
                and jobs.status = 'SUCCEEDED'
          )
    ) then
        raise exception 'The latest successful processing attempt requires a later approval'
            using errcode = '55000';
    end if;

    previous_document_status := selected_document.status;

    select id into previous_active_version_id
    from public.document_versions
    where document_id = selected_document.id
      and status = 'ACTIVE'
    for update;

    perform set_config(
        'app.status_change_reason',
        'Superseded by publication of ' || p_version_id::text,
        true
    );
    update public.document_versions
    set status = 'SUPERSEDED'
    where document_id = selected_document.id
      and status = 'ACTIVE';

    perform set_config('app.status_change_reason', 'Published', true);
    update public.document_versions
    set status = 'ACTIVE'
    where id = p_version_id
    returning * into selected_version;

    update public.knowledge_documents
    set status = 'PUBLISHED',
        current_version_id = p_version_id
    where id = selected_document.id
    returning * into selected_document;

    insert into public.publications (
        document_id,
        document_version_id,
        previous_active_version_id,
        published_by
    ) values (
        selected_document.id,
        p_version_id,
        previous_active_version_id,
        actor
    );

    perform public.write_enterprise_audit(
        'DOCUMENT_VERSION_PUBLISHED',
        'knowledge_document',
        selected_document.id,
        jsonb_build_object(
            'status', previous_document_status,
            'current_version_id', previous_active_version_id
        ),
        jsonb_build_object(
            'status', 'PUBLISHED',
            'current_version_id', p_version_id
        ),
        null
    );
    return selected_version;
end;
$$;

revoke all on function public.publish_document_version(uuid)
from public, anon;
grant execute on function public.publish_document_version(uuid)
to authenticated;

create or replace function public.archive_knowledge_document(
    p_document_id uuid,
    p_reason text
)
returns public.knowledge_documents
language plpgsql
security definer
set search_path = ''
as $$
declare
    actor uuid := auth.uid();
    selected_document public.knowledge_documents;
    previous_document_status text;
begin
    select * into selected_document
    from public.knowledge_documents
    where id = p_document_id
    for update;
    if not found
       or actor is null
       or not public.has_functional_permission(actor, 'ARCHIVE_DOCUMENT')
       or not public.has_document_permission(actor, p_document_id, 'ARCHIVE') then
        raise exception 'Document archival is not permitted' using errcode = '42501';
    end if;
    if selected_document.status = 'ARCHIVED' then
        return selected_document;
    end if;
    if nullif(btrim(p_reason), '') is null then
        raise exception 'Archive reason is required' using errcode = '22023';
    end if;

    previous_document_status := selected_document.status;

    update public.knowledge_documents
    set status = 'ARCHIVED',
        archived_by = actor,
        archived_at = now(),
        archive_reason = btrim(p_reason)
    where id = p_document_id
    returning * into selected_document;

    perform public.write_enterprise_audit(
        'DOCUMENT_ARCHIVED',
        'knowledge_document',
        p_document_id,
        jsonb_build_object('status', previous_document_status),
        jsonb_build_object('status', 'ARCHIVED'),
        p_reason
    );
    return selected_document;
end;
$$;

revoke all on function public.archive_knowledge_document(uuid, text)
from public, anon;
grant execute on function public.archive_knowledge_document(uuid, text)
to authenticated;

create or replace function public.grant_document_permission(
    p_document_id uuid,
    p_subject_id uuid,
    p_permission text
)
returns public.document_permissions
language plpgsql
security definer
set search_path = ''
as $$
declare
    actor uuid := auth.uid();
    normalized_permission text := upper(btrim(coalesce(p_permission, '')));
    created_permission public.document_permissions;
begin
    if actor is null
       or not public.has_functional_permission(actor, 'MANAGE_ACCESS_POLICY')
       or not public.has_document_permission(
           actor, p_document_id, 'MANAGE_PERMISSION'
       ) then
        raise exception 'ACL management is not permitted' using errcode = '42501';
    end if;
    if normalized_permission not in (
        'READ',
        'DOWNLOAD',
        'MANAGE',
        'REVIEW',
        'PUBLISH',
        'ARCHIVE',
        'MANAGE_PERMISSION'
    ) then
        raise exception 'Invalid document permission' using errcode = '22023';
    end if;
    if not exists (select 1 from public.access_subjects where id = p_subject_id) then
        raise exception 'Access subject not found' using errcode = '23503';
    end if;

    insert into public.document_permissions (
        document_id, subject_id, permission, status, granted_by
    ) values (
        p_document_id, p_subject_id, normalized_permission, 'ACTIVE', actor
    ) returning * into created_permission;

    perform public.write_enterprise_audit(
        'DOCUMENT_PERMISSION_GRANTED',
        'knowledge_document',
        p_document_id,
        null,
        jsonb_build_object(
            'permission_id', created_permission.id,
            'subject_id', p_subject_id,
            'permission', normalized_permission
        ),
        null
    );
    return created_permission;
exception
    when unique_violation then
        raise exception 'An active assignment already exists'
            using errcode = '23505';
end;
$$;

revoke all on function public.grant_document_permission(uuid, uuid, text)
from public, anon;
grant execute on function public.grant_document_permission(uuid, uuid, text)
to authenticated;

create or replace function public.revoke_document_permission(
    p_document_id uuid,
    p_subject_id uuid,
    p_permission text
)
returns void
language plpgsql
security definer
set search_path = ''
as $$
declare
    actor uuid := auth.uid();
    normalized_permission text := upper(btrim(coalesce(p_permission, '')));
    revoked_permission_id uuid;
begin
    if actor is null
       or not public.has_functional_permission(actor, 'MANAGE_ACCESS_POLICY')
       or not public.has_document_permission(
           actor, p_document_id, 'MANAGE_PERMISSION'
       ) then
        raise exception 'ACL management is not permitted' using errcode = '42501';
    end if;

    update public.document_permissions
    set status = 'REVOKED',
        revoked_by = actor,
        revoked_at = now()
    where id = (
        select id
        from public.document_permissions
        where document_id = p_document_id
          and subject_id = p_subject_id
          and permission = normalized_permission
          and status = 'ACTIVE'
        for update
    )
    returning id into revoked_permission_id;
    if revoked_permission_id is null then
        raise exception 'Active assignment not found' using errcode = 'P0002';
    end if;

    perform public.write_enterprise_audit(
        'DOCUMENT_PERMISSION_REVOKED',
        'knowledge_document',
        p_document_id,
        jsonb_build_object(
            'permission_id', revoked_permission_id,
            'subject_id', p_subject_id,
            'permission', normalized_permission,
            'status', 'ACTIVE'
        ),
        jsonb_build_object('status', 'REVOKED'),
        null
    );
end;
$$;

revoke all on function public.revoke_document_permission(uuid, uuid, text)
from public, anon;
grant execute on function public.revoke_document_permission(uuid, uuid, text)
to authenticated;

create or replace function public.retry_processing_job(p_job_id uuid)
returns public.processing_jobs
language plpgsql
security definer
set search_path = ''
as $$
declare
    actor uuid := auth.uid();
    selected_job public.processing_jobs;
    selected_version public.document_versions;
    selected_document public.knowledge_documents;
    created_job public.processing_jobs;
    next_attempt integer;
begin
    select * into selected_job
    from public.processing_jobs
    where id = p_job_id
    for update;
    if not found then
        raise exception 'Processing job not found' using errcode = 'P0002';
    end if;
    select * into selected_version
    from public.document_versions
    where id = selected_job.document_version_id;
    if actor is null
       or not public.has_functional_permission(actor, 'MANAGE_DOCUMENT')
       or not public.has_document_permission(
           actor, selected_version.document_id, 'MANAGE'
       ) then
        raise exception 'Processing retry is not permitted' using errcode = '42501';
    end if;

    select * into selected_document
    from public.knowledge_documents
    where id = selected_version.document_id
    for update;
    if not found or selected_document.status = 'ARCHIVED' then
        raise exception 'Archived documents cannot be reprocessed'
            using errcode = '55000';
    end if;
    if selected_job.status not in ('FAILED', 'CANCELLED') then
        raise exception 'Only FAILED or CANCELLED jobs may be retried'
            using errcode = '55000';
    end if;

    select coalesce(max(attempt_no), 0) + 1 into next_attempt
    from public.processing_jobs
    where document_version_id = selected_job.document_version_id;

    insert into public.processing_jobs (
        document_version_id,
        job_type,
        status,
        attempt_no,
        previous_job_id,
        requested_by,
        embedding_model,
        embedding_dimensions,
        configuration
    ) values (
        selected_job.document_version_id,
        'REPROCESS',
        'PENDING',
        next_attempt,
        selected_job.id,
        actor,
        selected_job.embedding_model,
        selected_job.embedding_dimensions,
        selected_job.configuration
    ) returning * into created_job;

    perform public.write_enterprise_audit(
        'PROCESSING_JOB_RETRIED',
        'processing_job',
        created_job.id,
        jsonb_build_object('previous_job_id', selected_job.id),
        jsonb_build_object('status', 'PENDING', 'attempt_no', next_attempt),
        null
    );
    return created_job;
end;
$$;

revoke all on function public.retry_processing_job(uuid)
from public, anon;
grant execute on function public.retry_processing_job(uuid)
to authenticated;

create or replace function public.claim_processing_job(
    p_worker_id text,
    p_lease_seconds integer default 120
)
returns public.processing_jobs
language plpgsql
security definer
set search_path = ''
as $$
declare
    selected_job public.processing_jobs;
    next_claim_token uuid := gen_random_uuid();
begin
    if auth.role() <> 'service_role' then
        raise exception 'Service role required' using errcode = '42501';
    end if;
    if nullif(btrim(p_worker_id), '') is null
       or p_lease_seconds < 10 or p_lease_seconds > 3600 then
        raise exception 'Invalid worker lease request' using errcode = '22023';
    end if;

    select * into selected_job
    from public.processing_jobs
    where status = 'PENDING'
       or (status = 'RUNNING' and lease_expires_at <= now())
    order by requested_at, id
    for update skip locked
    limit 1;
    if not found then
        return null;
    end if;

    update public.processing_jobs
    set status = 'RUNNING',
        started_at = coalesce(started_at, now()),
        heartbeat_at = now(),
        lease_owner = btrim(p_worker_id),
        lease_expires_at = now() + make_interval(secs => p_lease_seconds),
        claim_token = next_claim_token,
        error_code = null,
        error_message = null
    where id = selected_job.id
    returning * into selected_job;
    return selected_job;
end;
$$;

revoke all on function public.claim_processing_job(text, integer)
from public, anon, authenticated;
grant execute on function public.claim_processing_job(text, integer)
to service_role;

create or replace function public.renew_processing_job_lease(
    p_job_id uuid,
    p_worker_id text,
    p_claim_token uuid,
    p_lease_seconds integer default 120
)
returns boolean
language plpgsql
security definer
set search_path = ''
as $$
begin
    if auth.role() <> 'service_role' then
        raise exception 'Service role required' using errcode = '42501';
    end if;
    if p_lease_seconds < 10 or p_lease_seconds > 3600 then
        raise exception 'Invalid lease duration' using errcode = '22023';
    end if;
    update public.processing_jobs
    set heartbeat_at = now(),
        lease_expires_at = now() + make_interval(secs => p_lease_seconds)
    where id = p_job_id
      and status = 'RUNNING'
      and lease_owner = btrim(p_worker_id)
      and claim_token = p_claim_token
      and lease_expires_at > now();
    return found;
end;
$$;

revoke all on function public.renew_processing_job_lease(
    uuid, text, uuid, integer
) from public, anon, authenticated;
grant execute on function public.renew_processing_job_lease(
    uuid, text, uuid, integer
) to service_role;

create or replace function public.record_processing_stage(
    p_job_id uuid,
    p_worker_id text,
    p_claim_token uuid,
    p_stage text,
    p_status text,
    p_message text default null
)
returns public.processing_stage_history
language plpgsql
security definer
set search_path = ''
as $$
declare
    normalized_stage text := upper(btrim(coalesce(p_stage, '')));
    normalized_status text := upper(btrim(coalesce(p_status, '')));
    created_history public.processing_stage_history;
begin
    if auth.role() <> 'service_role' then
        raise exception 'Service role required' using errcode = '42501';
    end if;
    if not exists (
        select 1 from public.processing_jobs
        where id = p_job_id
          and status = 'RUNNING'
          and lease_owner = btrim(p_worker_id)
          and claim_token = p_claim_token
          and lease_expires_at > now()
        for update
    ) then
        raise exception 'Processing lease is stale' using errcode = '40001';
    end if;

    update public.processing_jobs
    set current_stage = normalized_stage,
        heartbeat_at = now()
    where id = p_job_id;

    insert into public.processing_stage_history (
        processing_job_id,
        stage,
        status,
        started_at,
        completed_at,
        message
    ) values (
        p_job_id,
        normalized_stage,
        normalized_status,
        now(),
        case when normalized_status = 'STARTED' then null else now() end,
        nullif(btrim(p_message), '')
    ) returning * into created_history;
    return created_history;
end;
$$;

revoke all on function public.record_processing_stage(
    uuid, text, uuid, text, text, text
) from public, anon, authenticated;
grant execute on function public.record_processing_stage(
    uuid, text, uuid, text, text, text
) to service_role;

create or replace function public.complete_processing_job(
    p_job_id uuid,
    p_worker_id text,
    p_claim_token uuid,
    p_chunks jsonb default null
)
returns public.processing_jobs
language plpgsql
security definer
set search_path = ''
as $$
declare
    selected_job public.processing_jobs;
    selected_version public.document_versions;
    completed_job public.processing_jobs;
begin
    if auth.role() <> 'service_role' then
        raise exception 'Service role required' using errcode = '42501';
    end if;

    select * into selected_job
    from public.processing_jobs
    where id = p_job_id
      and status = 'RUNNING'
      and lease_owner = btrim(p_worker_id)
      and claim_token = p_claim_token
      and lease_expires_at > now()
    for update;
    if not found then
        raise exception 'Processing lease is stale' using errcode = '40001';
    end if;
    select * into selected_version
    from public.document_versions
    where id = selected_job.document_version_id;

    if p_chunks is not null then
        if jsonb_typeof(p_chunks) <> 'array'
           or jsonb_array_length(p_chunks) < 1
           or jsonb_array_length(p_chunks) > 20000 then
            raise exception 'Successful processing requires 1..20000 chunks'
                using errcode = '22023';
        end if;
        if exists (
            select 1
            from jsonb_array_elements(p_chunks) as chunk(value)
            where jsonb_typeof(chunk.value) <> 'object'
               or nullif(btrim(chunk.value ->> 'content'), '') is null
               or coalesce(chunk.value ->> 'chunk_index', '') !~ '^[0-9]+$'
               or (
                   chunk.value ? 'metadata'
                   and jsonb_typeof(chunk.value -> 'metadata') <> 'object'
               )
               or (
                   chunk.value ? 'embedding'
                   and chunk.value -> 'embedding' <> 'null'::jsonb
                   and jsonb_typeof(chunk.value -> 'embedding') <> 'array'
               )
        ) then
            raise exception 'Chunk payload is invalid' using errcode = '22023';
        end if;

        delete from public.knowledge_chunks
        where document_version_id = selected_job.document_version_id;

        insert into public.knowledge_chunks (
            id,
            document_id,
            document_version_id,
            chunk_index,
            content,
            contextual_content,
            token_count,
            content_hash,
            page_start,
            page_end,
            section_path,
            metadata,
            embedding
        )
        select
            coalesce(
                nullif(chunk.value ->> 'id', '')::uuid,
                gen_random_uuid()
            ),
            selected_version.document_id,
            selected_version.id,
            (chunk.value ->> 'chunk_index')::integer,
            chunk.value ->> 'content',
            nullif(chunk.value ->> 'contextual_content', ''),
            greatest(coalesce((chunk.value ->> 'token_count')::integer, 1), 1),
            lower(nullif(chunk.value ->> 'content_hash', '')),
            nullif(chunk.value ->> 'page_start', '')::integer,
            nullif(chunk.value ->> 'page_end', '')::integer,
            nullif(chunk.value ->> 'section_path', ''),
            coalesce(chunk.value -> 'metadata', '{}'::jsonb),
            case
                when jsonb_typeof(chunk.value -> 'embedding') = 'array'
                then (chunk.value -> 'embedding')::text::public.vector(1536)
                else null
            end
        from jsonb_array_elements(p_chunks) as chunk(value);
    elsif not exists (
        select 1
        from public.knowledge_chunks
        where document_version_id = selected_job.document_version_id
    ) then
        raise exception 'Successful processing requires indexed chunks'
            using errcode = '55000';
    end if;

    update public.processing_jobs
    set status = 'SUCCEEDED',
        current_stage = 'FINALIZING',
        completed_at = now(),
        heartbeat_at = now(),
        lease_owner = null,
        lease_expires_at = null,
        claim_token = null,
        error_code = null,
        error_message = null
    where id = p_job_id
      and status = 'RUNNING'
      and lease_owner = btrim(p_worker_id)
      and claim_token = p_claim_token
      and lease_expires_at > now()
    returning * into completed_job;
    if completed_job.id is null then
        raise exception 'Processing lease is stale' using errcode = '40001';
    end if;
    return completed_job;
end;
$$;

revoke all on function public.complete_processing_job(uuid, text, uuid, jsonb)
from public, anon, authenticated;
grant execute on function public.complete_processing_job(uuid, text, uuid, jsonb)
to service_role;

create or replace function public.fail_processing_job(
    p_job_id uuid,
    p_worker_id text,
    p_claim_token uuid,
    p_stage text,
    p_error_type text,
    p_error_code text,
    p_safe_message text,
    p_internal_reference text default null,
    p_retryable boolean default false
)
returns public.processing_jobs
language plpgsql
security definer
set search_path = ''
as $$
declare
    failed_job public.processing_jobs;
    normalized_stage text := nullif(upper(btrim(p_stage)), '');
    normalized_code text := upper(btrim(coalesce(p_error_code, 'PROCESSING_FAILED')));
    normalized_message text := btrim(coalesce(p_safe_message, ''));
begin
    if auth.role() <> 'service_role' then
        raise exception 'Service role required' using errcode = '42501';
    end if;
    if normalized_message = '' then
        raise exception 'Safe error message is required' using errcode = '22023';
    end if;

    update public.processing_jobs
    set status = 'FAILED',
        current_stage = coalesce(normalized_stage, current_stage),
        completed_at = now(),
        heartbeat_at = now(),
        lease_owner = null,
        lease_expires_at = null,
        claim_token = null,
        error_code = normalized_code,
        error_message = normalized_message
    where id = p_job_id
      and status = 'RUNNING'
      and lease_owner = btrim(p_worker_id)
      and claim_token = p_claim_token
      and lease_expires_at > now()
    returning * into failed_job;
    if failed_job.id is null then
        raise exception 'Processing lease is stale' using errcode = '40001';
    end if;

    insert into public.processing_errors (
        processing_job_id,
        stage,
        error_type,
        error_code,
        safe_message,
        internal_reference,
        retryable
    ) values (
        p_job_id,
        normalized_stage,
        btrim(p_error_type),
        normalized_code,
        normalized_message,
        nullif(btrim(p_internal_reference), ''),
        coalesce(p_retryable, false)
    );
    return failed_job;
end;
$$;

revoke all on function public.fail_processing_job(
    uuid, text, uuid, text, text, text, text, text, boolean
) from public, anon, authenticated;
grant execute on function public.fail_processing_job(
    uuid, text, uuid, text, text, text, text, text, boolean
) to service_role;

create or replace function public.mark_version_ready_after_processing()
returns trigger
language plpgsql
security definer
set search_path = ''
as $$
begin
    if new.status = 'SUCCEEDED'
       and old.status is distinct from new.status then
        perform set_config(
            'app.status_change_reason',
            'Processing job ' || new.id::text || ' succeeded',
            true
        );
        update public.document_versions
        set status = 'READY_FOR_REVIEW'
        where id = new.document_version_id
          and status = 'DRAFT';
    end if;
    return new;
end;
$$;

revoke all on function public.mark_version_ready_after_processing()
from public, anon, authenticated;

drop trigger if exists processing_jobs_mark_version_ready
on public.processing_jobs;
create trigger processing_jobs_mark_version_ready
after update of status on public.processing_jobs
for each row execute function public.mark_version_ready_after_processing();

create or replace function public.get_document_version_source(
    p_document_id uuid,
    p_version_id uuid
)
returns jsonb
language plpgsql
stable
security definer
set search_path = ''
as $$
declare
    actor uuid := auth.uid();
    selected_version public.document_versions;
    selected_document public.knowledge_documents;
    source_payload jsonb;
begin
    select * into selected_version
    from public.document_versions
    where id = p_version_id and document_id = p_document_id;
    select * into selected_document
    from public.knowledge_documents
    where id = p_document_id;
    if not found or selected_version.id is null then
        return null;
    end if;
    if actor is null
       or not public.has_document_permission(actor, p_document_id, 'READ') then
        raise exception 'Source access is not permitted' using errcode = '42501';
    end if;
    if not (
        selected_document.status = 'PUBLISHED'
        and selected_document.current_version_id = p_version_id
        and selected_version.status = 'ACTIVE'
    ) and not (
        public.has_document_permission(actor, p_document_id, 'MANAGE')
        and public.has_functional_permission(actor, 'MANAGE_DOCUMENT')
    ) then
        raise exception 'Historical source access is not permitted'
            using errcode = '42501';
    end if;

    select jsonb_build_object(
        'bucket_name', source_files.bucket_name,
        'object_path', source_files.object_path,
        'original_file_name', source_files.original_file_name,
        'mime_type', source_files.mime_type,
        'size_bytes', source_files.size_bytes,
        'sha256', source_files.sha256
    ) into source_payload
    from public.source_files
    where source_files.id = selected_version.source_file_id;
    return source_payload;
end;
$$;

revoke all on function public.get_document_version_source(uuid, uuid)
from public, anon;
grant execute on function public.get_document_version_source(uuid, uuid)
to authenticated;

create or replace function public.create_enterprise_conversation(
    p_title text default 'New chat'
)
returns public.enterprise_conversations
language plpgsql
security definer
set search_path = ''
as $$
declare
    actor uuid := auth.uid();
    created_conversation public.enterprise_conversations;
begin
    if actor is null
       or not public.has_functional_permission(actor, 'ASK_KNOWLEDGE') then
        raise exception 'Conversation creation is not permitted' using errcode = '42501';
    end if;
    insert into public.enterprise_conversations (user_id, title)
    values (actor, coalesce(nullif(btrim(p_title), ''), 'New chat'))
    returning * into created_conversation;
    return created_conversation;
end;
$$;

revoke all on function public.create_enterprise_conversation(text)
from public, anon;
grant execute on function public.create_enterprise_conversation(text)
to authenticated;

create or replace function public.get_enterprise_conversation(
    p_conversation_id uuid
)
returns jsonb
language plpgsql
stable
security definer
set search_path = ''
as $$
declare
    actor uuid := auth.uid();
    payload jsonb;
begin
    if actor is null then
        raise exception 'Authentication required' using errcode = '42501';
    end if;
    select jsonb_build_object(
        'conversation', to_jsonb(conversations),
        'messages', coalesce((
            select jsonb_agg(to_jsonb(messages) order by messages.created_at, messages.id)
            from public.enterprise_messages as messages
            where messages.conversation_id = conversations.id
        ), '[]'::jsonb)
    ) into payload
    from public.enterprise_conversations as conversations
    where conversations.id = p_conversation_id
      and conversations.user_id = actor;
    return payload;
end;
$$;

revoke all on function public.get_enterprise_conversation(uuid)
from public, anon;
grant execute on function public.get_enterprise_conversation(uuid)
to authenticated;

create or replace function public.append_enterprise_message(
    p_conversation_id uuid,
    p_role text,
    p_content text
)
returns public.enterprise_messages
language plpgsql
security definer
set search_path = ''
as $$
declare
    actor uuid := auth.uid();
    normalized_role text := upper(btrim(coalesce(p_role, '')));
    created_message public.enterprise_messages;
begin
    if actor is null or not exists (
        select 1
        from public.enterprise_conversations
        where id = p_conversation_id and user_id = actor
    ) then
        raise exception 'Conversation access is not permitted' using errcode = '42501';
    end if;
    if normalized_role not in ('USER', 'ASSISTANT', 'SYSTEM') then
        raise exception 'Invalid message role' using errcode = '22023';
    end if;
    insert into public.enterprise_messages (conversation_id, role, content)
    values (p_conversation_id, normalized_role, coalesce(p_content, ''))
    returning * into created_message;
    update public.enterprise_conversations
    set updated_at = now()
    where id = p_conversation_id;
    return created_message;
end;
$$;

revoke all on function public.append_enterprise_message(uuid, text, text)
from public, anon;
grant execute on function public.append_enterprise_message(uuid, text, text)
to authenticated;

create or replace function public.guard_answer_report_resolution()
returns trigger
language plpgsql
security definer
set search_path = ''
as $$
begin
    if row(
        new.message_id,
        new.reporter_user_id,
        new.reason_code,
        new.details,
        new.created_at
    ) is distinct from row(
        old.message_id,
        old.reporter_user_id,
        old.reason_code,
        old.details,
        old.created_at
    ) then
        raise exception 'Report evidence fields are immutable' using errcode = '55000';
    end if;
    if new.status in ('RESOLVED', 'DISMISSED') then
        new.resolved_by = auth.uid();
        new.resolved_at = now();
    else
        new.resolved_by = null;
        new.resolved_at = null;
        new.resolution_note = null;
    end if;
    return new;
end;
$$;

revoke all on function public.guard_answer_report_resolution()
from public, anon, authenticated;

drop trigger if exists answer_reports_guard_resolution on public.answer_reports;
create trigger answer_reports_guard_resolution
before update on public.answer_reports
for each row execute function public.guard_answer_report_resolution();

create or replace function public.enterprise_analytics_summary()
returns jsonb
language plpgsql
stable
security definer
set search_path = ''
as $$
declare
    actor uuid := auth.uid();
begin
    if actor is null
       or not public.has_functional_permission(actor, 'VIEW_AUDIT') then
        raise exception 'Analytics access is not permitted' using errcode = '42501';
    end if;
    return jsonb_build_object(
        'draft_documents', (
            select count(*) from public.knowledge_documents where status = 'DRAFT'
        ),
        'published_documents', (
            select count(*) from public.knowledge_documents where status = 'PUBLISHED'
        ),
        'archived_documents', (
            select count(*) from public.knowledge_documents where status = 'ARCHIVED'
        ),
        'pending_jobs', (
            select count(*) from public.processing_jobs where status = 'PENDING'
        ),
        'running_jobs', (
            select count(*) from public.processing_jobs where status = 'RUNNING'
        ),
        'failed_jobs', (
            select count(*) from public.processing_jobs where status = 'FAILED'
        ),
        'feedback_up', (
            select count(*) from public.answer_feedback where rating = 'UP'
        ),
        'feedback_down', (
            select count(*) from public.answer_feedback where rating = 'DOWN'
        ),
        'open_reports', (
            select count(*) from public.answer_reports
            where status in ('OPEN', 'INVESTIGATING')
        ),
        'no_answer_rate', (
            select case
                when count(*) = 0 then 0::double precision
                else count(*) filter (
                    where answer_status = 'CONTROLLED_NO_ANSWER'
                )::double precision / count(*)::double precision
            end
            from public.enterprise_messages
            where role = 'ASSISTANT'
        )
    );
end;
$$;

revoke all on function public.enterprise_analytics_summary()
from public, anon;
grant execute on function public.enterprise_analytics_summary()
to authenticated;

comment on function public.publish_document_version(uuid) is
    'Atomic publish transaction: supersede old ACTIVE, activate reviewed candidate, update current_version_id, publication and audit.';
comment on function public.test_document_access(uuid, uuid, text) is
    'Evaluates the current DB membership graph; ACL revoke is effective on the next statement.';

-- Enterprise RLS and fail-closed retrieval entry points.
-- Run after 20_enterprise_operations.sql.

create or replace function public.is_enterprise_document_retrievable(
    p_user_id uuid,
    p_document_id uuid,
    p_document_version_id uuid
)
returns boolean
language sql
stable
security definer
set search_path = ''
as $$
    select coalesce(exists (
        select 1
        from public.knowledge_documents as documents
        join public.document_versions as versions
          on versions.id = p_document_version_id
         and versions.document_id = documents.id
        where documents.id = p_document_id
          and public.has_functional_permission(p_user_id, 'ASK_KNOWLEDGE')
          and documents.status = 'PUBLISHED'
          and documents.current_version_id = versions.id
          and versions.status = 'ACTIVE'
          and public.has_document_permission(
              p_user_id,
              documents.id,
              'READ'
          )
    ), false);
$$;

revoke all on function public.is_enterprise_document_retrievable(
    uuid, uuid, uuid
) from public, anon;
grant execute on function public.is_enterprise_document_retrievable(
    uuid, uuid, uuid
) to authenticated, service_role;

-- RLS policies must not use caller-filtered subqueries to decide whether an
-- immutable source is already referenced. These SECURITY DEFINER helpers see
-- the authoritative relationship and prevent an uploader from regaining
-- read/delete access merely because the referencing version became hidden.
create or replace function public.is_enterprise_source_file_referenced(
    p_source_file_id uuid
)
returns boolean
language sql
stable
security definer
set search_path = ''
as $$
    select coalesce(exists (
        select 1
        from public.document_versions as versions
        where versions.source_file_id = p_source_file_id
    ), false);
$$;

revoke all on function public.is_enterprise_source_file_referenced(uuid)
from public, anon;
grant execute on function public.is_enterprise_source_file_referenced(uuid)
to authenticated, service_role;

create or replace function public.is_enterprise_storage_object_referenced(
    p_bucket_name text,
    p_object_path text
)
returns boolean
language sql
stable
security definer
set search_path = ''
as $$
    select coalesce(exists (
        select 1
        from public.source_files as files
        join public.document_versions as versions
          on versions.source_file_id = files.id
        where files.bucket_name = p_bucket_name
          and files.object_path = p_object_path
    ), false);
$$;

revoke all on function public.is_enterprise_storage_object_referenced(text, text)
from public, anon;
grant execute on function public.is_enterprise_storage_object_referenced(text, text)
to authenticated, service_role;

-- Deleting an object that already has a source_files row would leave durable
-- metadata pointing at missing bytes even when no document version references
-- it yet. Keep that stronger registration check separate from the version
-- reference helper used by uploader read isolation.
create or replace function public.is_enterprise_storage_object_registered(
    p_bucket_name text,
    p_object_path text
)
returns boolean
language sql
stable
security definer
set search_path = ''
as $$
    select coalesce(exists (
        select 1
        from public.source_files as files
        where files.bucket_name = p_bucket_name
          and files.object_path = p_object_path
    ), false);
$$;

revoke all on function public.is_enterprise_storage_object_registered(text, text)
from public, anon;
grant execute on function public.is_enterprise_storage_object_registered(text, text)
to authenticated, service_role;

create or replace function public.authorized_knowledge_document_ids()
returns table (document_id uuid, document_version_id uuid)
language sql
stable
security definer
set search_path = ''
as $$
    select documents.id, versions.id
    from public.knowledge_documents as documents
    join public.document_versions as versions
      on versions.id = documents.current_version_id
     and versions.document_id = documents.id
    where auth.uid() is not null
      and public.has_functional_permission(auth.uid(), 'ASK_KNOWLEDGE')
      and documents.status = 'PUBLISHED'
      and versions.status = 'ACTIVE'
      and public.has_document_permission(auth.uid(), documents.id, 'READ');
$$;

revoke all on function public.authorized_knowledge_document_ids()
from public, anon;
grant execute on function public.authorized_knowledge_document_ids()
to authenticated;

create or replace function public.match_enterprise_document_chunks(
    p_query_embedding vector(1536),
    p_limit integer default 20,
    p_filters jsonb default '{}'::jsonb
)
returns table (
    chunk_id uuid,
    document_id uuid,
    document_version_id uuid,
    title text,
    chunk_index integer,
    content text,
    page_start integer,
    page_end integer,
    section_path text,
    metadata jsonb,
    score double precision
)
language plpgsql
stable
security definer
set search_path = ''
as $$
declare
    actor uuid := auth.uid();
begin
    if actor is null
       or not public.has_functional_permission(actor, 'ASK_KNOWLEDGE') then
        raise exception 'Knowledge search is not permitted' using errcode = '42501';
    end if;
    if p_query_embedding is null then
        raise exception 'Query embedding is required' using errcode = '22023';
    end if;
    if p_filters is null or jsonb_typeof(p_filters) <> 'object' then
        raise exception 'Filters must be a JSON object' using errcode = '22023';
    end if;

    return query
    select
        chunks.id,
        documents.id,
        versions.id,
        documents.title,
        chunks.chunk_index,
        chunks.content,
        chunks.page_start,
        chunks.page_end,
        chunks.section_path,
        chunks.metadata,
        1 - (chunks.embedding operator(public.<=>) p_query_embedding)
    from public.knowledge_chunks as chunks
    join public.document_versions as versions
      on versions.id = chunks.document_version_id
     and versions.document_id = chunks.document_id
    join public.knowledge_documents as documents
      on documents.id = versions.document_id
     and documents.current_version_id = versions.id
    where documents.status = 'PUBLISHED'
      and versions.status = 'ACTIVE'
      and chunks.embedding is not null
      and public.has_document_permission(actor, documents.id, 'READ')
      and (
          not (p_filters ? 'document_type')
          or documents.document_type = upper(p_filters ->> 'document_type')
      )
      and (
          not (p_filters ? 'category')
          or documents.category = p_filters ->> 'category'
      )
      and (
          not (p_filters ? 'document_id')
          or documents.id::text = p_filters ->> 'document_id'
      )
      and (
          not (p_filters ? 'metadata')
          or (
              jsonb_typeof(p_filters -> 'metadata') = 'object'
              and documents.metadata @> (p_filters -> 'metadata')
          )
      )
    order by chunks.embedding operator(public.<=>) p_query_embedding, chunks.id
    limit greatest(1, least(coalesce(p_limit, 20), 200));
end;
$$;

revoke all on function public.match_enterprise_document_chunks(
    vector, integer, jsonb
) from public, anon;
grant execute on function public.match_enterprise_document_chunks(
    vector, integer, jsonb
) to authenticated;

create or replace function public.search_enterprise_document_chunks_keyword(
    p_query text,
    p_limit integer default 20,
    p_filters jsonb default '{}'::jsonb
)
returns table (
    chunk_id uuid,
    document_id uuid,
    document_version_id uuid,
    title text,
    chunk_index integer,
    content text,
    page_start integer,
    page_end integer,
    section_path text,
    metadata jsonb,
    score double precision
)
language plpgsql
stable
security definer
set search_path = ''
as $$
declare
    actor uuid := auth.uid();
    search_query tsquery;
begin
    if actor is null
       or not public.has_functional_permission(actor, 'ASK_KNOWLEDGE') then
        raise exception 'Knowledge search is not permitted' using errcode = '42501';
    end if;
    if p_filters is null or jsonb_typeof(p_filters) <> 'object' then
        raise exception 'Filters must be a JSON object' using errcode = '22023';
    end if;
    if p_query is null or btrim(p_query) = '' then
        return;
    end if;
    search_query := websearch_to_tsquery('simple'::regconfig, btrim(p_query));
    if numnode(search_query) = 0 then
        return;
    end if;

    return query
    select
        chunks.id,
        documents.id,
        versions.id,
        documents.title,
        chunks.chunk_index,
        chunks.content,
        chunks.page_start,
        chunks.page_end,
        chunks.section_path,
        chunks.metadata,
        ts_rank_cd(chunks.search_vector, search_query, 32)::double precision
    from public.knowledge_chunks as chunks
    join public.document_versions as versions
      on versions.id = chunks.document_version_id
     and versions.document_id = chunks.document_id
    join public.knowledge_documents as documents
      on documents.id = versions.document_id
     and documents.current_version_id = versions.id
    where documents.status = 'PUBLISHED'
      and versions.status = 'ACTIVE'
      and public.has_document_permission(actor, documents.id, 'READ')
      and chunks.search_vector @@ search_query
      and (
          not (p_filters ? 'document_type')
          or documents.document_type = upper(p_filters ->> 'document_type')
      )
      and (
          not (p_filters ? 'category')
          or documents.category = p_filters ->> 'category'
      )
      and (
          not (p_filters ? 'document_id')
          or documents.id::text = p_filters ->> 'document_id'
      )
      and (
          not (p_filters ? 'metadata')
          or (
              jsonb_typeof(p_filters -> 'metadata') = 'object'
              and documents.metadata @> (p_filters -> 'metadata')
          )
      )
    order by
        ts_rank_cd(chunks.search_vector, search_query, 32) desc,
        chunks.id
    limit greatest(1, least(coalesce(p_limit, 20), 200));
end;
$$;

revoke all on function public.search_enterprise_document_chunks_keyword(
    text, integer, jsonb
) from public, anon;
grant execute on function public.search_enterprise_document_chunks_keyword(
    text, integer, jsonb
) to authenticated;

create or replace function public.search_enterprise_knowledge(
    p_query text,
    p_limit integer default 20,
    p_filters jsonb default '{}'::jsonb
)
returns table (
    chunk_id uuid,
    document_id uuid,
    document_version_id uuid,
    title text,
    chunk_index integer,
    content text,
    page_start integer,
    page_end integer,
    section_path text,
    metadata jsonb,
    score double precision
)
language sql
stable
security definer
set search_path = ''
as $$
    select *
    from public.search_enterprise_document_chunks_keyword(
        p_query,
        p_limit,
        p_filters
    );
$$;

revoke all on function public.search_enterprise_knowledge(
    text, integer, jsonb
) from public, anon;
grant execute on function public.search_enterprise_knowledge(
    text, integer, jsonb
) to authenticated;

-- -------------------------------------------------------------------------
-- Privileges: anonymous access is denied; mutations of lifecycle and ACL data
-- go through the atomic SECURITY DEFINER operations in migration 20.
-- -------------------------------------------------------------------------

revoke all on table
    public.user_profiles,
    public.roles,
    public.functional_permissions,
    public.user_roles,
    public.role_permissions,
    public.groups,
    public.user_groups,
    public.departments,
    public.user_departments,
    public.access_subjects,
    public.knowledge_documents,
    public.source_files,
    public.document_versions,
    public.document_version_status_history,
    public.document_reviews,
    public.publications,
    public.document_permissions,
    public.processing_jobs,
    public.processing_stage_history,
    public.processing_errors,
    public.knowledge_chunks,
    public.enterprise_conversations,
    public.enterprise_messages,
    public.enterprise_citations,
    public.answer_feedback,
    public.answer_reports,
    public.audit_logs
from anon, authenticated;

-- Root IAM entities have lifecycle status and must be disabled, not deleted.
-- Membership/permission edges remain explicitly removable.
grant select, insert, update on table
    public.roles,
    public.groups,
    public.departments
to authenticated;
grant select, insert, update, delete on table
    public.user_roles,
    public.role_permissions,
    public.user_groups,
    public.user_departments
to authenticated;
grant select on table public.user_profiles to authenticated;
grant select on table public.functional_permissions to authenticated;
grant select on table public.access_subjects to authenticated;
grant select on table
    public.knowledge_documents,
    public.document_versions,
    public.document_version_status_history,
    public.document_reviews,
    public.publications,
    public.document_permissions,
    public.processing_jobs,
    public.processing_stage_history,
    public.processing_errors,
    public.knowledge_chunks,
    public.enterprise_conversations,
    public.enterprise_messages,
    public.enterprise_citations,
    public.audit_logs
to authenticated;
grant select, insert on table public.source_files to authenticated;
grant select, insert, update on table public.answer_feedback to authenticated;
grant select, insert, update on table public.answer_reports to authenticated;

grant all privileges on table
    public.user_profiles,
    public.roles,
    public.functional_permissions,
    public.user_roles,
    public.role_permissions,
    public.groups,
    public.user_groups,
    public.departments,
    public.user_departments,
    public.access_subjects,
    public.knowledge_documents,
    public.source_files,
    public.document_versions,
    public.document_version_status_history,
    public.document_reviews,
    public.publications,
    public.document_permissions,
    public.processing_jobs,
    public.processing_stage_history,
    public.processing_errors,
    public.knowledge_chunks,
    public.enterprise_conversations,
    public.enterprise_messages,
    public.enterprise_citations,
    public.answer_feedback,
    public.answer_reports,
    public.audit_logs
to service_role;

alter table public.user_profiles enable row level security;
alter table public.user_profiles force row level security;
alter table public.roles enable row level security;
alter table public.roles force row level security;
alter table public.functional_permissions enable row level security;
alter table public.functional_permissions force row level security;
alter table public.user_roles enable row level security;
alter table public.user_roles force row level security;
alter table public.role_permissions enable row level security;
alter table public.role_permissions force row level security;
alter table public.groups enable row level security;
alter table public.groups force row level security;
alter table public.user_groups enable row level security;
alter table public.user_groups force row level security;
alter table public.departments enable row level security;
alter table public.departments force row level security;
alter table public.user_departments enable row level security;
alter table public.user_departments force row level security;
alter table public.access_subjects enable row level security;
alter table public.access_subjects force row level security;
alter table public.knowledge_documents enable row level security;
alter table public.knowledge_documents force row level security;
alter table public.source_files enable row level security;
alter table public.source_files force row level security;
alter table public.document_versions enable row level security;
alter table public.document_versions force row level security;
alter table public.document_version_status_history enable row level security;
alter table public.document_version_status_history force row level security;
alter table public.document_reviews enable row level security;
alter table public.document_reviews force row level security;
alter table public.publications enable row level security;
alter table public.publications force row level security;
alter table public.document_permissions enable row level security;
alter table public.document_permissions force row level security;
alter table public.processing_jobs enable row level security;
alter table public.processing_jobs force row level security;
alter table public.processing_stage_history enable row level security;
alter table public.processing_stage_history force row level security;
alter table public.processing_errors enable row level security;
alter table public.processing_errors force row level security;
alter table public.knowledge_chunks enable row level security;
alter table public.knowledge_chunks force row level security;
alter table public.enterprise_conversations enable row level security;
alter table public.enterprise_conversations force row level security;
alter table public.enterprise_messages enable row level security;
alter table public.enterprise_messages force row level security;
alter table public.enterprise_citations enable row level security;
alter table public.enterprise_citations force row level security;
alter table public.answer_feedback enable row level security;
alter table public.answer_feedback force row level security;
alter table public.answer_reports enable row level security;
alter table public.answer_reports force row level security;
alter table public.audit_logs enable row level security;
alter table public.audit_logs force row level security;

-- IAM policies.
drop policy if exists user_profiles_select_enterprise on public.user_profiles;
create policy user_profiles_select_enterprise
on public.user_profiles for select to authenticated
using (
    user_id = (select auth.uid())
    or public.has_functional_permission((select auth.uid()), 'MANAGE_USER')
);
drop policy if exists user_profiles_update_enterprise on public.user_profiles;
create policy user_profiles_update_enterprise
on public.user_profiles for update to authenticated
using (public.has_functional_permission((select auth.uid()), 'MANAGE_USER'))
with check (public.has_functional_permission((select auth.uid()), 'MANAGE_USER'));
drop policy if exists user_profiles_insert_enterprise on public.user_profiles;
create policy user_profiles_insert_enterprise
on public.user_profiles for insert to authenticated
with check (public.has_functional_permission((select auth.uid()), 'MANAGE_USER'));

drop policy if exists roles_select_enterprise on public.roles;
create policy roles_select_enterprise
on public.roles for select to authenticated using (true);
drop policy if exists roles_manage_enterprise on public.roles;
create policy roles_manage_enterprise
on public.roles for all to authenticated
using (public.has_functional_permission((select auth.uid()), 'MANAGE_ROLE'))
with check (public.has_functional_permission((select auth.uid()), 'MANAGE_ROLE'));

drop policy if exists functional_permissions_select_enterprise
on public.functional_permissions;
create policy functional_permissions_select_enterprise
on public.functional_permissions for select to authenticated using (true);

drop policy if exists user_roles_select_enterprise on public.user_roles;
create policy user_roles_select_enterprise
on public.user_roles for select to authenticated
using (
    user_id = (select auth.uid())
    or public.has_functional_permission((select auth.uid()), 'MANAGE_ROLE')
);
drop policy if exists user_roles_manage_enterprise on public.user_roles;
create policy user_roles_manage_enterprise
on public.user_roles for all to authenticated
using (public.has_functional_permission((select auth.uid()), 'MANAGE_ROLE'))
with check (public.has_functional_permission((select auth.uid()), 'MANAGE_ROLE'));

drop policy if exists role_permissions_select_enterprise
on public.role_permissions;
create policy role_permissions_select_enterprise
on public.role_permissions for select to authenticated using (true);
drop policy if exists role_permissions_manage_enterprise
on public.role_permissions;
create policy role_permissions_manage_enterprise
on public.role_permissions for all to authenticated
using (public.has_functional_permission((select auth.uid()), 'MANAGE_ROLE'))
with check (public.has_functional_permission((select auth.uid()), 'MANAGE_ROLE'));

drop policy if exists groups_select_enterprise on public.groups;
create policy groups_select_enterprise
on public.groups for select to authenticated using (true);
drop policy if exists groups_manage_enterprise on public.groups;
create policy groups_manage_enterprise
on public.groups for all to authenticated
using (public.has_functional_permission((select auth.uid()), 'MANAGE_GROUP'))
with check (public.has_functional_permission((select auth.uid()), 'MANAGE_GROUP'));

drop policy if exists user_groups_select_enterprise on public.user_groups;
create policy user_groups_select_enterprise
on public.user_groups for select to authenticated
using (
    user_id = (select auth.uid())
    or public.has_functional_permission((select auth.uid()), 'MANAGE_GROUP')
);
drop policy if exists user_groups_manage_enterprise on public.user_groups;
create policy user_groups_manage_enterprise
on public.user_groups for all to authenticated
using (public.has_functional_permission((select auth.uid()), 'MANAGE_GROUP'))
with check (public.has_functional_permission((select auth.uid()), 'MANAGE_GROUP'));

drop policy if exists departments_select_enterprise on public.departments;
create policy departments_select_enterprise
on public.departments for select to authenticated using (true);
drop policy if exists departments_manage_enterprise on public.departments;
create policy departments_manage_enterprise
on public.departments for all to authenticated
using (public.has_functional_permission((select auth.uid()), 'MANAGE_DEPARTMENT'))
with check (public.has_functional_permission((select auth.uid()), 'MANAGE_DEPARTMENT'));

drop policy if exists user_departments_select_enterprise
on public.user_departments;
create policy user_departments_select_enterprise
on public.user_departments for select to authenticated
using (
    user_id = (select auth.uid())
    or public.has_functional_permission((select auth.uid()), 'MANAGE_DEPARTMENT')
);
drop policy if exists user_departments_manage_enterprise
on public.user_departments;
create policy user_departments_manage_enterprise
on public.user_departments for all to authenticated
using (public.has_functional_permission((select auth.uid()), 'MANAGE_DEPARTMENT'))
with check (public.has_functional_permission((select auth.uid()), 'MANAGE_DEPARTMENT'));

drop policy if exists access_subjects_select_enterprise
on public.access_subjects;
create policy access_subjects_select_enterprise
on public.access_subjects for select to authenticated
using (
    public.has_functional_permission((select auth.uid()), 'MANAGE_ACCESS_POLICY')
);

-- Knowledge/governance policies.  Lifecycle mutation remains RPC-only.
drop policy if exists knowledge_documents_select_access
on public.knowledge_documents;
create policy knowledge_documents_select_access
on public.knowledge_documents for select to authenticated
using (
    (
        status = 'PUBLISHED'
        and current_version_id is not null
        and public.has_document_permission((select auth.uid()), id, 'READ')
    )
    or public.has_document_permission((select auth.uid()), id, 'MANAGE')
    or public.has_document_permission((select auth.uid()), id, 'REVIEW')
    or public.has_document_permission((select auth.uid()), id, 'PUBLISH')
    or public.has_document_permission((select auth.uid()), id, 'ARCHIVE')
    or public.has_document_permission((select auth.uid()), id, 'MANAGE_PERMISSION')
);
drop policy if exists knowledge_documents_update_manager
on public.knowledge_documents;
create policy knowledge_documents_update_manager
on public.knowledge_documents for update to authenticated
using (
    public.has_document_permission((select auth.uid()), id, 'MANAGE')
    and public.has_functional_permission((select auth.uid()), 'MANAGE_DOCUMENT')
)
with check (
    public.has_document_permission((select auth.uid()), id, 'MANAGE')
    and public.has_functional_permission((select auth.uid()), 'MANAGE_DOCUMENT')
);

drop policy if exists source_files_select_access on public.source_files;
create policy source_files_select_access
on public.source_files for select to authenticated
using (
    (
        created_by = (select auth.uid())
        and not public.is_enterprise_source_file_referenced(source_files.id)
        and (
            public.has_functional_permission((select auth.uid()), 'UPLOAD_DOCUMENT')
            or public.has_functional_permission((select auth.uid()), 'MANAGE_DOCUMENT')
        )
    )
    or exists (
        select 1
        from public.document_versions as versions
        join public.knowledge_documents as documents
          on documents.id = versions.document_id
        where versions.source_file_id = source_files.id
          and (
              public.is_enterprise_document_retrievable(
                  (select auth.uid()), documents.id, versions.id
              )
              or (
                  public.has_document_permission(
                      (select auth.uid()), documents.id, 'MANAGE'
                  )
                  and public.has_functional_permission(
                      (select auth.uid()), 'MANAGE_DOCUMENT'
                  )
              )
              or (
                  public.has_document_permission(
                      (select auth.uid()), documents.id, 'REVIEW'
                  )
                  and public.has_functional_permission(
                      (select auth.uid()), 'REVIEW_DOCUMENT'
                  )
              )
              or (
                  public.has_document_permission(
                      (select auth.uid()), documents.id, 'PUBLISH'
                  )
                  and public.has_functional_permission(
                      (select auth.uid()), 'PUBLISH_DOCUMENT'
                  )
              )
          )
    )
);
drop policy if exists source_files_insert_own on public.source_files;
create policy source_files_insert_own
on public.source_files for insert to authenticated
with check (
    created_by = (select auth.uid())
    and (
        public.has_functional_permission((select auth.uid()), 'UPLOAD_DOCUMENT')
        or public.has_functional_permission((select auth.uid()), 'MANAGE_DOCUMENT')
    )
);

drop policy if exists document_versions_select_access
on public.document_versions;
create policy document_versions_select_access
on public.document_versions for select to authenticated
using (
    (
        status = 'ACTIVE'
        and exists (
            select 1
            from public.knowledge_documents as documents
            where documents.id = document_versions.document_id
              and documents.status = 'PUBLISHED'
              and documents.current_version_id = document_versions.id
        )
        and public.has_document_permission((select auth.uid()), document_id, 'READ')
    )
    or public.has_document_permission((select auth.uid()), document_id, 'MANAGE')
    or public.has_document_permission((select auth.uid()), document_id, 'REVIEW')
    or public.has_document_permission((select auth.uid()), document_id, 'PUBLISH')
    or public.has_document_permission((select auth.uid()), document_id, 'ARCHIVE')
);

drop policy if exists document_version_status_history_select_access
on public.document_version_status_history;
create policy document_version_status_history_select_access
on public.document_version_status_history for select to authenticated
using (
    exists (
        select 1 from public.document_versions
        where document_versions.id = document_version_id
          and (
              public.has_document_permission(
                  (select auth.uid()), document_versions.document_id, 'MANAGE'
              )
              or public.has_document_permission(
                  (select auth.uid()), document_versions.document_id, 'REVIEW'
              )
              or public.has_document_permission(
                  (select auth.uid()), document_versions.document_id, 'PUBLISH'
              )
          )
    )
);

drop policy if exists document_reviews_select_access on public.document_reviews;
create policy document_reviews_select_access
on public.document_reviews for select to authenticated
using (
    exists (
        select 1 from public.document_versions
        where document_versions.id = document_version_id
          and (
              public.has_document_permission(
                  (select auth.uid()), document_versions.document_id, 'MANAGE'
              )
              or public.has_document_permission(
                  (select auth.uid()), document_versions.document_id, 'REVIEW'
              )
              or public.has_document_permission(
                  (select auth.uid()), document_versions.document_id, 'PUBLISH'
              )
          )
    )
);

drop policy if exists publications_select_access on public.publications;
create policy publications_select_access
on public.publications for select to authenticated
using (
    public.has_document_permission((select auth.uid()), document_id, 'READ')
);

drop policy if exists document_permissions_select_manager
on public.document_permissions;
create policy document_permissions_select_manager
on public.document_permissions for select to authenticated
using (
    public.has_document_permission(
        (select auth.uid()), document_id, 'MANAGE_PERMISSION'
    )
);

drop policy if exists processing_jobs_select_access on public.processing_jobs;
create policy processing_jobs_select_access
on public.processing_jobs for select to authenticated
using (
    public.has_functional_permission((select auth.uid()), 'MANAGE_DOCUMENT')
    and exists (
        select 1 from public.document_versions
        where document_versions.id = document_version_id
          and public.has_document_permission(
              (select auth.uid()), document_versions.document_id, 'MANAGE'
          )
    )
);

drop policy if exists processing_stage_history_select_access
on public.processing_stage_history;
create policy processing_stage_history_select_access
on public.processing_stage_history for select to authenticated
using (
    public.has_functional_permission((select auth.uid()), 'MANAGE_DOCUMENT')
    and exists (
        select 1
        from public.processing_jobs
        join public.document_versions
          on document_versions.id = processing_jobs.document_version_id
        where processing_jobs.id = processing_job_id
          and public.has_document_permission(
              (select auth.uid()), document_versions.document_id, 'MANAGE'
          )
    )
);

drop policy if exists processing_errors_select_access
on public.processing_errors;
create policy processing_errors_select_access
on public.processing_errors for select to authenticated
using (
    public.has_functional_permission((select auth.uid()), 'MANAGE_DOCUMENT')
    and exists (
        select 1
        from public.processing_jobs
        join public.document_versions
          on document_versions.id = processing_jobs.document_version_id
        where processing_jobs.id = processing_job_id
          and public.has_document_permission(
              (select auth.uid()), document_versions.document_id, 'MANAGE'
          )
    )
);

drop policy if exists knowledge_chunks_select_retrievable
on public.knowledge_chunks;
create policy knowledge_chunks_select_retrievable
on public.knowledge_chunks for select to authenticated
using (
    public.is_enterprise_document_retrievable(
        (select auth.uid()), document_id, document_version_id
    )
);

-- Conversation and response-governance policies.
drop policy if exists enterprise_conversations_select_own
on public.enterprise_conversations;
create policy enterprise_conversations_select_own
on public.enterprise_conversations for select to authenticated
using (
    user_id = (select auth.uid())
    and public.has_functional_permission((select auth.uid()), 'ASK_KNOWLEDGE')
);

drop policy if exists enterprise_messages_select_own
on public.enterprise_messages;

create or replace function public.is_enterprise_message_visible(
    p_user_id uuid,
    p_message_id uuid
)
returns boolean
language sql
stable
security definer
set search_path = ''
as $$
    select coalesce(exists (
        select 1
        from public.enterprise_messages as messages
        join public.enterprise_conversations as conversations
          on conversations.id = messages.conversation_id
        where messages.id = p_message_id
          and conversations.user_id = p_user_id
          and public.has_functional_permission(p_user_id, 'ASK_KNOWLEDGE')
          and (
              messages.role = 'USER'
              or not exists (
                  select 1
                  from public.enterprise_citations as citations
                  where citations.answer_message_id = messages.id
              )
              or not exists (
                  select 1
                  from public.enterprise_citations as citations
                  where citations.answer_message_id = messages.id
                    and not public.is_enterprise_document_retrievable(
                        p_user_id,
                        citations.document_id,
                        citations.document_version_id
                    )
              )
          )
    ), false);
$$;

revoke all on function public.is_enterprise_message_visible(uuid, uuid)
from public, anon;
grant execute on function public.is_enterprise_message_visible(uuid, uuid)
to authenticated, service_role;

create policy enterprise_messages_select_own
on public.enterprise_messages for select to authenticated
using (
    public.is_enterprise_message_visible((select auth.uid()), id)
);

drop policy if exists enterprise_citations_select_own
on public.enterprise_citations;
create policy enterprise_citations_select_own
on public.enterprise_citations for select to authenticated
using (
    exists (
        select 1
        from public.enterprise_messages
        join public.enterprise_conversations
          on enterprise_conversations.id = enterprise_messages.conversation_id
        where enterprise_messages.id = answer_message_id
          and enterprise_conversations.user_id = (select auth.uid())
    )
    and public.is_enterprise_document_retrievable(
        (select auth.uid()), document_id, document_version_id
    )
);

drop policy if exists answer_feedback_select_own_or_governance
on public.answer_feedback;
create policy answer_feedback_select_own_or_governance
on public.answer_feedback for select to authenticated
using (
    (
        user_id = (select auth.uid())
        and public.has_functional_permission((select auth.uid()), 'ASK_KNOWLEDGE')
        and public.is_enterprise_message_visible((select auth.uid()), message_id)
    )
    or public.has_functional_permission((select auth.uid()), 'VIEW_AUDIT')
);
drop policy if exists answer_feedback_insert_own on public.answer_feedback;
create policy answer_feedback_insert_own
on public.answer_feedback for insert to authenticated
with check (
    user_id = (select auth.uid())
    and public.has_functional_permission((select auth.uid()), 'ASK_KNOWLEDGE')
    and public.is_enterprise_message_visible((select auth.uid()), message_id)
    and exists (
        select 1 from public.enterprise_messages
        where enterprise_messages.id = message_id
          and enterprise_messages.role = 'ASSISTANT'
    )
);
drop policy if exists answer_feedback_update_own on public.answer_feedback;
create policy answer_feedback_update_own
on public.answer_feedback for update to authenticated
using (
    user_id = (select auth.uid())
    and public.has_functional_permission((select auth.uid()), 'ASK_KNOWLEDGE')
    and public.is_enterprise_message_visible((select auth.uid()), message_id)
)
with check (
    user_id = (select auth.uid())
    and public.has_functional_permission((select auth.uid()), 'ASK_KNOWLEDGE')
    and public.is_enterprise_message_visible((select auth.uid()), message_id)
    and exists (
        select 1 from public.enterprise_messages
        where enterprise_messages.id = message_id
          and enterprise_messages.role = 'ASSISTANT'
    )
);

drop policy if exists answer_reports_select_own_or_governance
on public.answer_reports;
create policy answer_reports_select_own_or_governance
on public.answer_reports for select to authenticated
using (
    (
        reporter_user_id = (select auth.uid())
        and public.has_functional_permission((select auth.uid()), 'ASK_KNOWLEDGE')
        and public.is_enterprise_message_visible((select auth.uid()), message_id)
    )
    or public.has_functional_permission((select auth.uid()), 'VIEW_AUDIT')
);
drop policy if exists answer_reports_insert_own on public.answer_reports;
create policy answer_reports_insert_own
on public.answer_reports for insert to authenticated
with check (
    reporter_user_id = (select auth.uid())
    and status = 'OPEN'
    and public.has_functional_permission((select auth.uid()), 'ASK_KNOWLEDGE')
    and public.is_enterprise_message_visible((select auth.uid()), message_id)
    and exists (
        select 1 from public.enterprise_messages
        where enterprise_messages.id = message_id
          and enterprise_messages.role = 'ASSISTANT'
    )
);
drop policy if exists answer_reports_update_governance
on public.answer_reports;
create policy answer_reports_update_governance
on public.answer_reports for update to authenticated
using (public.has_functional_permission((select auth.uid()), 'VIEW_AUDIT'))
with check (public.has_functional_permission((select auth.uid()), 'VIEW_AUDIT'));

drop policy if exists audit_logs_select_governance on public.audit_logs;
create policy audit_logs_select_governance
on public.audit_logs for select to authenticated
using (public.has_functional_permission((select auth.uid()), 'VIEW_AUDIT'));

comment on function public.match_enterprise_document_chunks(
    vector, integer, jsonb
) is
    'Dense retrieval gate. Unauthorized, unpublished and non-current versions are excluded before ranking.';
comment on function public.search_enterprise_document_chunks_keyword(
    text, integer, jsonb
) is
    'Sparse retrieval gate. ACL and lifecycle predicates execute before any candidate leaves PostgreSQL.';
comment on function public.authorized_knowledge_document_ids() is
    'Current-user allowlist resolved from live DB membership; empty means default DENY.';

-- Complete the Enterprise RAG cutover: atomic grounded answers and a direct
-- version-scoped ingestion queue bridge. Run after
-- 21_enterprise_security_retrieval.sql.

insert into storage.buckets (
    id,
    name,
    public,
    file_size_limit,
    allowed_mime_types
)
values (
    'knowledge-source-files',
    'knowledge-source-files',
    false,
    10485760,
    array[
        'application/pdf',
        'application/vnd.openxmlformats-officedocument.wordprocessingml.document',
        'application/vnd.openxmlformats-officedocument.presentationml.presentation',
        'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
        'text/csv',
        'text/markdown',
        'text/html',
        'text/plain'
    ]::text[]
)
on conflict (id) do update
set name = excluded.name,
    public = excluded.public,
    file_size_limit = excluded.file_size_limit,
    allowed_mime_types = excluded.allowed_mime_types;

create or replace function public.can_download_enterprise_source(
    p_user_id uuid,
    p_bucket_name text,
    p_object_path text
)
returns boolean
language sql
stable
security definer
set search_path = ''
as $$
    select coalesce(exists (
        select 1
        from public.source_files as files
        join public.document_versions as versions
          on versions.source_file_id = files.id
        join public.knowledge_documents as documents
          on documents.id = versions.document_id
        where files.bucket_name = p_bucket_name
          and files.object_path = p_object_path
          and (
              (
                  documents.status = 'PUBLISHED'
                  and documents.current_version_id = versions.id
                  and versions.status = 'ACTIVE'
                  and public.has_document_permission(
                      p_user_id,
                      documents.id,
                      'DOWNLOAD'
                  )
              )
              or (
                  public.has_document_permission(
                      p_user_id,
                      documents.id,
                      'MANAGE'
                  )
                  and public.has_functional_permission(
                      p_user_id,
                      'MANAGE_DOCUMENT'
                  )
              )
              or (
                  public.has_document_permission(
                      p_user_id,
                      documents.id,
                      'REVIEW'
                  )
                  and public.has_functional_permission(
                      p_user_id,
                      'REVIEW_DOCUMENT'
                  )
              )
              or (
                  public.has_document_permission(
                      p_user_id,
                      documents.id,
                      'PUBLISH'
                  )
                  and public.has_functional_permission(
                      p_user_id,
                      'PUBLISH_DOCUMENT'
                  )
              )
          )
    ), false);
$$;

revoke all on function public.can_download_enterprise_source(uuid, text, text)
from public, anon;
grant execute on function public.can_download_enterprise_source(uuid, text, text)
to authenticated, service_role;

drop policy if exists enterprise_source_storage_insert on storage.objects;
create policy enterprise_source_storage_insert
on storage.objects for insert to authenticated
with check (
    bucket_id = 'knowledge-source-files'
    and (storage.foldername(name))[1] = (select auth.uid())::text
    and (
        public.has_functional_permission((select auth.uid()), 'UPLOAD_DOCUMENT')
        or public.has_functional_permission((select auth.uid()), 'MANAGE_DOCUMENT')
    )
);

drop policy if exists enterprise_source_storage_select on storage.objects;
create policy enterprise_source_storage_select
on storage.objects for select to authenticated
using (
    bucket_id = 'knowledge-source-files'
    and (
        (
            (storage.foldername(name))[1] = (select auth.uid())::text
            and (
                public.has_functional_permission((select auth.uid()), 'UPLOAD_DOCUMENT')
                or public.has_functional_permission((select auth.uid()), 'MANAGE_DOCUMENT')
            )
            and not public.is_enterprise_storage_object_referenced(
                storage.objects.bucket_id,
                storage.objects.name
            )
        )
        or public.can_download_enterprise_source(
            (select auth.uid()),
            bucket_id,
            name
        )
    )
);

drop policy if exists enterprise_source_storage_delete on storage.objects;
create policy enterprise_source_storage_delete
on storage.objects for delete to authenticated
using (
    bucket_id = 'knowledge-source-files'
    and (storage.foldername(name))[1] = (select auth.uid())::text
    and (
        public.has_functional_permission((select auth.uid()), 'UPLOAD_DOCUMENT')
        or public.has_functional_permission((select auth.uid()), 'MANAGE_DOCUMENT')
    )
    and not public.is_enterprise_storage_object_registered(
        storage.objects.bucket_id,
        storage.objects.name
    )
);

create or replace function public.get_document_version_source(
    p_document_id uuid,
    p_version_id uuid
)
returns jsonb
language plpgsql
stable
security definer
set search_path = ''
as $$
declare
    actor uuid := auth.uid();
    selected_version public.document_versions;
    selected_document public.knowledge_documents;
    source_payload jsonb;
begin
    select * into selected_version
    from public.document_versions
    where id = p_version_id and document_id = p_document_id;
    select * into selected_document
    from public.knowledge_documents
    where id = p_document_id;
    if not found or selected_version.id is null then
        return null;
    end if;
    if actor is null then
        raise exception 'Source access is not permitted' using errcode = '42501';
    end if;
    if (
        selected_document.status = 'PUBLISHED'
        and selected_document.current_version_id = p_version_id
        and selected_version.status = 'ACTIVE'
    ) then
        if not public.has_document_permission(actor, p_document_id, 'DOWNLOAD') then
            raise exception 'Source download is not permitted' using errcode = '42501';
        end if;
    elsif not (
        (
            public.has_document_permission(actor, p_document_id, 'MANAGE')
            and public.has_functional_permission(actor, 'MANAGE_DOCUMENT')
        )
        or (
            public.has_document_permission(actor, p_document_id, 'REVIEW')
            and public.has_functional_permission(actor, 'REVIEW_DOCUMENT')
        )
        or (
            public.has_document_permission(actor, p_document_id, 'PUBLISH')
            and public.has_functional_permission(actor, 'PUBLISH_DOCUMENT')
        )
    ) then
        raise exception 'Historical source access is not permitted'
            using errcode = '42501';
    end if;

    select jsonb_build_object(
        'bucket_name', source_files.bucket_name,
        'object_path', source_files.object_path,
        'original_file_name', source_files.original_file_name,
        'mime_type', source_files.mime_type,
        'size_bytes', source_files.size_bytes,
        'sha256', source_files.sha256
    ) into source_payload
    from public.source_files
    where source_files.id = selected_version.source_file_id;
    return source_payload;
end;
$$;

revoke all on function public.get_document_version_source(uuid, uuid)
from public, anon;
grant execute on function public.get_document_version_source(uuid, uuid)
to authenticated;

-- Only the server-side completion RPC may create ASSISTANT/SYSTEM messages.
-- Keeping the historical signature avoids breaking clients during rollout.
create or replace function public.append_enterprise_message(
    p_conversation_id uuid,
    p_role text,
    p_content text
)
returns public.enterprise_messages
language plpgsql
security definer
set search_path = ''
as $$
declare
    actor uuid := auth.uid();
    normalized_role text := upper(btrim(coalesce(p_role, '')));
    created_message public.enterprise_messages;
begin
    if actor is null
       or not public.has_functional_permission(actor, 'ASK_KNOWLEDGE')
       or not exists (
           select 1
           from public.enterprise_conversations
           where id = p_conversation_id and user_id = actor
       ) then
        raise exception 'Conversation access is not permitted' using errcode = '42501';
    end if;
    if normalized_role <> 'USER' then
        raise exception 'Only USER messages may be appended by a client'
            using errcode = '42501';
    end if;
    if nullif(btrim(coalesce(p_content, '')), '') is null then
        raise exception 'Message content is required' using errcode = '22023';
    end if;

    insert into public.enterprise_messages (
        conversation_id,
        role,
        content,
        answer_status
    ) values (
        p_conversation_id,
        'USER',
        btrim(p_content),
        'COMPLETED'
    ) returning * into created_message;

    update public.enterprise_conversations
    set updated_at = now()
    where id = p_conversation_id;
    return created_message;
end;
$$;

revoke all on function public.append_enterprise_message(uuid, text, text)
from public, anon;
grant execute on function public.append_enterprise_message(uuid, text, text)
to authenticated;

-- The public search entry point requires both the functional ASK permission
-- and the row-level READ/lifecycle checks inside the underlying search RPC.
create or replace function public.search_enterprise_knowledge(
    p_query text,
    p_limit integer default 20,
    p_filters jsonb default '{}'::jsonb
)
returns table (
    chunk_id uuid,
    document_id uuid,
    document_version_id uuid,
    title text,
    chunk_index integer,
    content text,
    page_start integer,
    page_end integer,
    section_path text,
    metadata jsonb,
    score double precision
)
language plpgsql
stable
security definer
set search_path = ''
as $$
declare
    actor uuid := auth.uid();
begin
    if actor is null
       or not public.has_functional_permission(actor, 'ASK_KNOWLEDGE') then
        raise exception 'Knowledge search is not permitted' using errcode = '42501';
    end if;
    return query
    select *
    from public.search_enterprise_document_chunks_keyword(
        p_query,
        p_limit,
        p_filters
    );
end;
$$;

revoke all on function public.search_enterprise_knowledge(text, integer, jsonb)
from public, anon;
grant execute on function public.search_enterprise_knowledge(text, integer, jsonb)
to authenticated;

-- Persist the assistant message and its exact version-bound citations in one
-- transaction. Authorization and publication are checked again here to close
-- the retrieval-to-generation race (archive, republish, or ACL revocation).
create or replace function public.write_enterprise_audit_as_actor(
    p_actor_user_id uuid,
    p_action text,
    p_entity_type text,
    p_entity_id uuid,
    p_before_data jsonb default null,
    p_after_data jsonb default null,
    p_note text default null
)
returns uuid
language plpgsql
security definer
set search_path = ''
as $$
declare
    inserted_id uuid;
begin
    if auth.role() <> 'service_role' or p_actor_user_id is null then
        raise exception 'Service role and an explicit actor are required'
            using errcode = '42501';
    end if;
    insert into public.audit_logs (
        actor_user_id,
        action,
        entity_type,
        entity_id,
        before_data,
        after_data,
        metadata,
        request_id,
        trace_id,
        note
    ) values (
        p_actor_user_id,
        p_action,
        p_entity_type,
        p_entity_id,
        p_before_data,
        p_after_data,
        jsonb_strip_nulls(jsonb_build_object(
            'before', p_before_data,
            'after', p_after_data,
            'note', p_note
        )),
        nullif(current_setting('request.headers', true)::jsonb ->> 'x-request-id', ''),
        nullif(current_setting('request.headers', true)::jsonb ->> 'x-trace-id', ''),
        p_note
    ) returning id into inserted_id;
    return inserted_id;
end;
$$;

revoke all on function public.write_enterprise_audit_as_actor(
    uuid, text, text, uuid, jsonb, jsonb, text
) from public, anon, authenticated;
grant execute on function public.write_enterprise_audit_as_actor(
    uuid, text, text, uuid, jsonb, jsonb, text
) to service_role;

drop function if exists public.complete_enterprise_answer(
    uuid, text, text, text, integer, integer, text, text, jsonb
);

create or replace function public.complete_enterprise_answer(
    p_actor_user_id uuid,
    p_conversation_id uuid,
    p_content text,
    p_answer_status text,
    p_model text,
    p_input_tokens integer,
    p_output_tokens integer,
    p_error_code text,
    p_trace_id text,
    p_citations jsonb
)
returns jsonb
language plpgsql
security definer
set search_path = ''
as $$
declare
    actor uuid := p_actor_user_id;
    normalized_status text := upper(btrim(coalesce(p_answer_status, '')));
    created_message public.enterprise_messages;
    citations_payload jsonb := coalesce(p_citations, '[]'::jsonb);
    citation_count integer;
    distinct_order_count integer;
    distinct_chunk_count integer;
    created_citations jsonb := '[]'::jsonb;
begin
    if auth.role() <> 'service_role' then
        raise exception 'Service role required to commit an Enterprise answer'
            using errcode = '42501';
    end if;
    if actor is null
       or not public.has_functional_permission(actor, 'ASK_KNOWLEDGE')
       or not exists (
           select 1
           from public.enterprise_conversations
           where id = p_conversation_id and user_id = actor
       ) then
        raise exception 'Conversation access is not permitted' using errcode = '42501';
    end if;
    if normalized_status not in ('COMPLETED', 'FAILED', 'CONTROLLED_NO_ANSWER') then
        raise exception 'Invalid answer status' using errcode = '22023';
    end if;
    if nullif(btrim(coalesce(p_content, '')), '') is null then
        raise exception 'Answer content is required' using errcode = '22023';
    end if;
    if (p_input_tokens is not null and p_input_tokens < 0)
       or (p_output_tokens is not null and p_output_tokens < 0) then
        raise exception 'Token counts must be non-negative' using errcode = '22023';
    end if;
    if jsonb_typeof(citations_payload) <> 'array' then
        raise exception 'Citations must be an array' using errcode = '22023';
    end if;
    citation_count := jsonb_array_length(citations_payload);
    if citation_count > 100 then
        raise exception 'Too many citations' using errcode = '22023';
    end if;

    if normalized_status = 'COMPLETED' then
        if citation_count = 0 or nullif(btrim(coalesce(p_model, '')), '') is null then
            raise exception 'A completed answer requires a model and citations'
                using errcode = '22023';
        end if;
    elsif citation_count <> 0 or p_model is not null then
        raise exception 'Failed or controlled answers cannot carry citations or a model'
            using errcode = '22023';
    end if;

    if citation_count > 0 and exists (
        select 1
        from jsonb_array_elements(citations_payload) as item(value)
        where jsonb_typeof(item.value) <> 'object'
           or coalesce(item.value ->> 'document_id', '')
              !~* '^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$'
           or coalesce(item.value ->> 'document_version_id', '')
              !~* '^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$'
           or coalesce(item.value ->> 'chunk_id', '')
              !~* '^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$'
           or coalesce(item.value ->> 'citation_order', '') !~ '^[1-9][0-9]*$'
           or nullif(btrim(item.value ->> 'quote_text'), '') is null
           or (
               item.value ? 'page_number'
               and item.value ->> 'page_number' is not null
               and item.value ->> 'page_number' !~ '^[1-9][0-9]*$'
           )
    ) then
        raise exception 'Citation payload is invalid' using errcode = '22023';
    end if;

    if citation_count > 0 then
        select
            count(distinct (item.value ->> 'citation_order')::integer),
            count(distinct (item.value ->> 'chunk_id')::uuid)
        into distinct_order_count, distinct_chunk_count
        from jsonb_array_elements(citations_payload) as item(value);
        if distinct_order_count <> citation_count
           or distinct_chunk_count <> citation_count
           or exists (
               select 1
               from generate_series(1, citation_count) as expected(ordinal)
               where not exists (
                   select 1
                   from jsonb_array_elements(citations_payload) as item(value)
                   where (item.value ->> 'citation_order')::integer = expected.ordinal
               )
           ) then
            raise exception 'Citation order and chunks must be unique and contiguous'
                using errcode = '22023';
        end if;

        if exists (
            select 1
            from jsonb_array_elements(citations_payload) as item(value)
            where not exists (
                select 1
                from public.knowledge_chunks as chunks
                where chunks.id = (item.value ->> 'chunk_id')::uuid
                  and chunks.document_id = (item.value ->> 'document_id')::uuid
                  and chunks.document_version_id =
                      (item.value ->> 'document_version_id')::uuid
                  and chunks.content = item.value ->> 'quote_text'
                  and public.is_enterprise_document_retrievable(
                      actor,
                      chunks.document_id,
                      chunks.document_version_id
                  )
            )
        ) then
            raise exception 'Citation evidence is no longer authorized or current'
                using errcode = '42501';
        end if;
    end if;

    insert into public.enterprise_messages (
        conversation_id,
        role,
        content,
        answer_status,
        model,
        input_tokens,
        output_tokens,
        error_code,
        trace_id
    ) values (
        p_conversation_id,
        'ASSISTANT',
        p_content,
        normalized_status,
        nullif(btrim(p_model), ''),
        p_input_tokens,
        p_output_tokens,
        nullif(btrim(p_error_code), ''),
        nullif(btrim(p_trace_id), '')
    ) returning * into created_message;

    if citation_count > 0 then
        insert into public.enterprise_citations (
            answer_message_id,
            document_id,
            document_version_id,
            chunk_id,
            page_number,
            quote_text,
            citation_order,
            retrieval_score
        )
        select
            created_message.id,
            (item.value ->> 'document_id')::uuid,
            (item.value ->> 'document_version_id')::uuid,
            (item.value ->> 'chunk_id')::uuid,
            nullif(item.value ->> 'page_number', '')::integer,
            item.value ->> 'quote_text',
            (item.value ->> 'citation_order')::integer,
            nullif(item.value ->> 'retrieval_score', '')::double precision
        from jsonb_array_elements(citations_payload) as item(value);

        select coalesce(
            jsonb_agg(to_jsonb(citations) order by citations.citation_order),
            '[]'::jsonb
        ) into created_citations
        from public.enterprise_citations as citations
        where citations.answer_message_id = created_message.id;
    end if;

    update public.enterprise_conversations
    set updated_at = now()
    where id = p_conversation_id;

    perform public.write_enterprise_audit_as_actor(
        actor,
        'ENTERPRISE_ANSWER_COMPLETED',
        'enterprise_message',
        created_message.id,
        null,
        jsonb_build_object(
            'answer_status', normalized_status,
            'citation_count', citation_count,
            'trace_id', p_trace_id
        ),
        null
    );

    return jsonb_build_object(
        'message', to_jsonb(created_message),
        'citations', created_citations
    );
end;
$$;

revoke all on function public.complete_enterprise_answer(
    uuid, uuid, text, text, text, integer, integer, text, text, jsonb
) from public, anon, authenticated;
grant execute on function public.complete_enterprise_answer(
    uuid, uuid, text, text, text, integer, integer, text, text, jsonb
) to service_role;

-- Return citations together with messages. Revoked/archived evidence is
-- omitted at read time as a second line of defence.
create or replace function public.get_enterprise_conversation(
    p_conversation_id uuid
)
returns jsonb
language plpgsql
stable
security definer
set search_path = ''
as $$
declare
    actor uuid := auth.uid();
    payload jsonb;
begin
    if actor is null
       or not public.has_functional_permission(actor, 'ASK_KNOWLEDGE') then
        raise exception 'Conversation access is not permitted' using errcode = '42501';
    end if;
    select jsonb_build_object(
        'conversation', to_jsonb(conversations),
        'messages', coalesce((
            select jsonb_agg(
                case
                    when messages.role = 'ASSISTANT'
                     and exists (
                         select 1
                         from public.enterprise_citations as all_citations
                         where all_citations.answer_message_id = messages.id
                     )
                     and exists (
                         select 1
                         from public.enterprise_citations as denied_citations
                         where denied_citations.answer_message_id = messages.id
                           and not public.is_enterprise_document_retrievable(
                               actor,
                               denied_citations.document_id,
                               denied_citations.document_version_id
                           )
                     )
                    then to_jsonb(messages) || jsonb_build_object(
                        'content',
                        'Nội dung câu trả lời không còn khả dụng vì quyền truy cập nguồn đã thay đổi.',
                        'answer_status', 'CONTROLLED_NO_ANSWER',
                        'model', null,
                        'input_tokens', null,
                        'output_tokens', null,
                        'error_code', 'EVIDENCE_ACCESS_REVOKED',
                        'citations', '[]'::jsonb
                    )
                    else to_jsonb(messages) || jsonb_build_object(
                        'citations', coalesce((
                            select jsonb_agg(
                                to_jsonb(citations) || jsonb_build_object(
                                    'document_title', documents.title,
                                    'section_path', chunks.section_path
                                )
                                order by citations.citation_order
                            )
                            from public.enterprise_citations as citations
                            join public.knowledge_chunks as chunks
                              on chunks.id = citations.chunk_id
                             and chunks.document_id = citations.document_id
                             and chunks.document_version_id = citations.document_version_id
                            join public.knowledge_documents as documents
                              on documents.id = citations.document_id
                            where citations.answer_message_id = messages.id
                              and public.is_enterprise_document_retrievable(
                                  actor,
                                  citations.document_id,
                                  citations.document_version_id
                              )
                        ), '[]'::jsonb)
                    )
                end
                order by messages.created_at, messages.id
            )
            from public.enterprise_messages as messages
            where messages.conversation_id = conversations.id
        ), '[]'::jsonb)
    ) into payload
    from public.enterprise_conversations as conversations
    where conversations.id = p_conversation_id
      and conversations.user_id = actor;
    return payload;
end;
$$;

revoke all on function public.get_enterprise_conversation(uuid)
from public, anon;
grant execute on function public.get_enterprise_conversation(uuid)
to authenticated;

-- Claim only direct Enterprise jobs. Legacy rows are still claimed through
-- claim_ingestion_job and synchronized by migration 19 during the cutover.
create or replace function public.claim_enterprise_ingestion_job(
    p_worker_id text,
    p_lease_seconds integer default 120
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
    document_version integer,
    document_version_id uuid,
    knowledge_document_id uuid,
    source_file_id uuid,
    job_type text
)
language plpgsql
security definer
set search_path = ''
as $$
declare
    selected_job public.processing_jobs;
    next_claim_token uuid := gen_random_uuid();
begin
    if auth.role() <> 'service_role' then
        raise exception 'Service role required' using errcode = '42501';
    end if;
    if nullif(btrim(p_worker_id), '') is null
       or p_lease_seconds < 10 or p_lease_seconds > 3600 then
        raise exception 'Invalid worker lease request' using errcode = '22023';
    end if;

    select jobs.* into selected_job
    from public.processing_jobs as jobs
    where jobs.legacy_ingestion_job_id is null
      and (
          jobs.status = 'PENDING'
          or (jobs.status = 'RUNNING' and jobs.lease_expires_at <= now())
      )
    order by jobs.requested_at, jobs.id
    for update skip locked
    limit 1;
    if not found then
        return;
    end if;

    update public.processing_jobs as jobs
    set status = 'RUNNING',
        started_at = coalesce(jobs.started_at, now()),
        heartbeat_at = now(),
        lease_owner = btrim(p_worker_id),
        lease_expires_at = now() + make_interval(secs => p_lease_seconds),
        claim_token = next_claim_token,
        error_code = null,
        error_message = null
    where jobs.id = selected_job.id
    returning jobs.* into selected_job;

    return query
    select
        selected_job.id,
        documents.created_by,
        coalesce(documents.legacy_notebook_id, documents.id),
        documents.id,
        selected_job.attempt_no,
        selected_job.configuration,
        files.bucket_name,
        files.object_path,
        files.original_file_name,
        files.mime_type,
        files.size_bytes,
        files.sha256,
        selected_job.claim_token,
        versions.version_number,
        versions.id,
        documents.id,
        files.id,
        selected_job.job_type
    from public.document_versions as versions
    join public.knowledge_documents as documents
      on documents.id = versions.document_id
    join public.source_files as files
      on files.id = versions.source_file_id
    where versions.id = selected_job.document_version_id;
end;
$$;

revoke all on function public.claim_enterprise_ingestion_job(text, integer)
from public, anon, authenticated;
grant execute on function public.claim_enterprise_ingestion_job(text, integer)
to service_role;

create or replace function public.record_enterprise_terminal_processing_stage()
returns trigger
language plpgsql
security definer
set search_path = ''
as $$
begin
    if new.status = 'SUCCEEDED'
       and old.status is distinct from new.status
       and not exists (
           select 1
           from public.processing_stage_history
           where processing_job_id = new.id
             and stage = 'FINALIZING'
             and status = 'SUCCEEDED'
       ) then
        insert into public.processing_stage_history (
            processing_job_id,
            stage,
            status,
            started_at,
            completed_at,
            message
        ) values (
            new.id,
            'FINALIZING',
            'SUCCEEDED',
            coalesce(new.heartbeat_at, now()),
            now(),
            'Processing completed and the version is ready for review.'
        );
    end if;
    return new;
end;
$$;

revoke all on function public.record_enterprise_terminal_processing_stage()
from public, anon, authenticated;

drop trigger if exists processing_jobs_record_terminal_stage
on public.processing_jobs;
create trigger processing_jobs_record_terminal_stage
after update of status on public.processing_jobs
for each row execute function public.record_enterprise_terminal_processing_stage();

comment on function public.complete_enterprise_answer(
    uuid, uuid, text, text, text, integer, integer, text, text, jsonb
) is
    'Atomic answer/citation persistence with a live PUBLISHED+ACTIVE+READ recheck.';
comment on function public.claim_enterprise_ingestion_job(text, integer) is
    'Claims direct version-scoped Enterprise jobs with immutable source-file metadata.';

-- Enterprise workflow completion and production authorization alignment.
-- Run after 22_enterprise_answer_ingestion_bridge.sql.

-- Keep read-only governance, analytics, and report mutation as separate
-- capabilities.  ADMIN receives newly introduced permissions through the
-- same data-driven role mapping as every other role.
insert into public.functional_permissions (code, name, description)
values
    ('VIEW_ANALYTICS', 'View analytics', 'View aggregate Enterprise knowledge metrics.'),
    ('MANAGE_REPORT', 'Manage answer reports', 'Resolve or dismiss reported answers.')
on conflict (code) do nothing;

insert into public.role_permissions (role_id, permission_id)
select roles.id, permissions.id
from public.roles as roles
cross join public.functional_permissions as permissions
where roles.code = 'ADMIN'
  and permissions.code in ('VIEW_ANALYTICS', 'MANAGE_REPORT')
on conflict (role_id, permission_id) do nothing;

create or replace function public.enterprise_analytics_summary()
returns jsonb
language plpgsql
stable
security definer
set search_path = ''
as $$
declare
    actor uuid := auth.uid();
begin
    if actor is null
       or not public.has_functional_permission(actor, 'VIEW_ANALYTICS') then
        raise exception 'Analytics access is not permitted' using errcode = '42501';
    end if;
    return jsonb_build_object(
        'draft_documents', (
            select count(*) from public.knowledge_documents where status = 'DRAFT'
        ),
        'published_documents', (
            select count(*) from public.knowledge_documents where status = 'PUBLISHED'
        ),
        'archived_documents', (
            select count(*) from public.knowledge_documents where status = 'ARCHIVED'
        ),
        'pending_jobs', (
            select count(*) from public.processing_jobs where status = 'PENDING'
        ),
        'running_jobs', (
            select count(*) from public.processing_jobs where status = 'RUNNING'
        ),
        'failed_jobs', (
            select count(*) from public.processing_jobs where status = 'FAILED'
        ),
        'feedback_up', (
            select count(*) from public.answer_feedback where rating = 'UP'
        ),
        'feedback_down', (
            select count(*) from public.answer_feedback where rating = 'DOWN'
        ),
        'open_reports', (
            select count(*) from public.answer_reports
            where status in ('OPEN', 'INVESTIGATING')
        ),
        'no_answer_rate', (
            select case
                when count(*) = 0 then 0::double precision
                else count(*) filter (
                    where answer_status = 'CONTROLLED_NO_ANSWER'
                )::double precision / count(*)::double precision
            end
            from public.enterprise_messages
            where role = 'ASSISTANT'
        )
    );
end;
$$;

revoke all on function public.enterprise_analytics_summary()
from public, anon;
grant execute on function public.enterprise_analytics_summary()
to authenticated;

drop policy if exists answer_reports_update_governance
on public.answer_reports;
create policy answer_reports_update_governance
on public.answer_reports for update to authenticated
using (public.has_functional_permission((select auth.uid()), 'MANAGE_REPORT'))
with check (public.has_functional_permission((select auth.uid()), 'MANAGE_REPORT'));

-- Configure one or more ACTIVE domains to make corporate-email enforcement
-- fail closed for every future auth.users insert/email change.  An empty table
-- intentionally keeps local development and an external enterprise IdP viable.
create table if not exists public.enterprise_allowed_email_domains (
    domain text primary key,
    status text not null default 'ACTIVE',
    created_at timestamptz not null default now(),
    constraint enterprise_allowed_email_domains_format check (
        domain = lower(btrim(domain))
        and domain ~ '^[a-z0-9][a-z0-9.-]*[a-z0-9]$'
        and pg_catalog.strpos(domain, '.') > 1
        and domain !~ '\.\.'
    ),
    constraint enterprise_allowed_email_domains_status
        check (status in ('ACTIVE', 'DISABLED'))
);

alter table public.enterprise_allowed_email_domains enable row level security;
alter table public.enterprise_allowed_email_domains force row level security;
revoke all on table public.enterprise_allowed_email_domains from public, anon, authenticated;
grant select, insert, update, delete on table public.enterprise_allowed_email_domains
to service_role;

create or replace function public.enforce_enterprise_email_domain()
returns trigger
language plpgsql
security definer
set search_path = ''
as $$
declare
    normalized_domain text := lower(split_part(coalesce(new.email, ''), '@', 2));
begin
    if exists (
        select 1
        from public.enterprise_allowed_email_domains
        where status = 'ACTIVE'
    ) and not exists (
        select 1
        from public.enterprise_allowed_email_domains
        where status = 'ACTIVE'
          and domain = normalized_domain
    ) then
        raise exception 'Email domain is not permitted for this organization'
            using errcode = '42501';
    end if;
    return new;
end;
$$;

revoke all on function public.enforce_enterprise_email_domain()
from public, anon, authenticated;

drop trigger if exists auth_users_enforce_enterprise_email_domain on auth.users;
create trigger auth_users_enforce_enterprise_email_domain
before insert or update of email on auth.users
for each row execute function public.enforce_enterprise_email_domain();

-- Metadata edits use an explicit version token so two administrators cannot
-- silently overwrite one another's changes.
create or replace function public.update_knowledge_document(
    p_document_id uuid,
    p_changes jsonb
)
returns public.knowledge_documents
language plpgsql
security definer
set search_path = ''
as $$
declare
    actor uuid := auth.uid();
    selected_document public.knowledge_documents;
    updated_document public.knowledge_documents;
    expected_updated_at timestamptz;
begin
    if actor is null
       or not public.has_functional_permission(actor, 'MANAGE_DOCUMENT')
       or not public.has_document_permission(actor, p_document_id, 'MANAGE') then
        raise exception 'Document update is not permitted' using errcode = '42501';
    end if;
    if p_changes is null or jsonb_typeof(p_changes) <> 'object' then
        raise exception 'Changes must be a JSON object' using errcode = '22023';
    end if;
    if not p_changes ? 'expected_updated_at' then
        raise exception 'expected_updated_at is required' using errcode = '22023';
    end if;
    begin
        expected_updated_at := (p_changes ->> 'expected_updated_at')::timestamptz;
    exception when invalid_datetime_format then
        raise exception 'expected_updated_at is invalid' using errcode = '22023';
    end;
    if exists (
        select 1
        from jsonb_object_keys(p_changes) as keys(key)
        where keys.key not in (
            'expected_updated_at',
            'title',
            'description',
            'document_type',
            'category',
            'document_number',
            'issued_date',
            'effective_date',
            'expiration_date',
            'source',
            'owner_department_id',
            'metadata'
        )
    ) then
        raise exception 'Changes contain a protected or unknown field'
            using errcode = '22023';
    end if;
    if p_changes ? 'metadata'
       and (
           p_changes -> 'metadata' = 'null'::jsonb
           or jsonb_typeof(p_changes -> 'metadata') <> 'object'
       ) then
        raise exception 'Metadata must be a JSON object' using errcode = '22023';
    end if;

    select * into selected_document
    from public.knowledge_documents
    where id = p_document_id
    for update;
    if not found or selected_document.status = 'ARCHIVED' then
        raise exception 'Document is missing or archived' using errcode = '55000';
    end if;
    if selected_document.updated_at is distinct from expected_updated_at then
        raise exception 'Document was modified by another request; reload before saving'
            using errcode = '23505';
    end if;

    update public.knowledge_documents
    set title = case when p_changes ? 'title'
            then btrim(p_changes ->> 'title') else title end,
        description = case when p_changes ? 'description'
            then coalesce(p_changes ->> 'description', '') else description end,
        document_type = case when p_changes ? 'document_type'
            then upper(btrim(p_changes ->> 'document_type')) else document_type end,
        category = case when p_changes ? 'category'
            then nullif(btrim(p_changes ->> 'category'), '') else category end,
        document_number = case when p_changes ? 'document_number'
            then nullif(btrim(p_changes ->> 'document_number'), '') else document_number end,
        issued_date = case when p_changes ? 'issued_date'
            then nullif(p_changes ->> 'issued_date', '')::date else issued_date end,
        effective_date = case when p_changes ? 'effective_date'
            then nullif(p_changes ->> 'effective_date', '')::date else effective_date end,
        expiration_date = case when p_changes ? 'expiration_date'
            then nullif(p_changes ->> 'expiration_date', '')::date else expiration_date end,
        source = case when p_changes ? 'source'
            then nullif(btrim(p_changes ->> 'source'), '') else source end,
        owner_department_id = case when p_changes ? 'owner_department_id'
            then nullif(p_changes ->> 'owner_department_id', '')::uuid
            else owner_department_id end,
        metadata = case when p_changes ? 'metadata'
            then p_changes -> 'metadata' else metadata end
    where id = p_document_id
    returning * into updated_document;

    perform public.write_enterprise_audit(
        'DOCUMENT_UPDATED',
        'knowledge_document',
        p_document_id,
        to_jsonb(selected_document),
        to_jsonb(updated_document),
        null
    );
    return updated_document;
end;
$$;

revoke all on function public.update_knowledge_document(uuid, jsonb)
from public, anon;
grant execute on function public.update_knowledge_document(uuid, jsonb)
to authenticated;

-- Initial upload is one database transaction for SourceFile + logical
-- Document + v1 + ProcessingJob.  Object storage is written first by the API;
-- the API compensates by deleting that object if this RPC rolls back.
create or replace function public.create_enterprise_document_upload(
    p_source_id uuid,
    p_bucket_name text,
    p_object_path text,
    p_original_file_name text,
    p_mime_type text,
    p_size_bytes bigint,
    p_sha256 text,
    p_title text,
    p_description text default '',
    p_document_type text default 'GENERAL',
    p_category text default null,
    p_metadata jsonb default '{}'::jsonb,
    p_change_summary text default '',
    p_effective_date date default null
)
returns jsonb
language plpgsql
security definer
set search_path = ''
as $$
declare
    actor uuid := auth.uid();
    actor_subject_id uuid;
    normalized_sha text := lower(btrim(coalesce(p_sha256, '')));
    created_source public.source_files;
    created_document public.knowledge_documents;
    created_version public.document_versions;
    created_job public.processing_jobs;
begin
    if actor is null
       or not (
           public.has_functional_permission(actor, 'UPLOAD_DOCUMENT')
           or public.has_functional_permission(actor, 'MANAGE_DOCUMENT')
       ) then
        raise exception 'Initial document upload is not permitted' using errcode = '42501';
    end if;
    if p_metadata is null or jsonb_typeof(p_metadata) <> 'object' then
        raise exception 'Metadata must be a JSON object' using errcode = '22023';
    end if;
    if normalized_sha !~ '^[0-9a-f]{64}$' then
        raise exception 'Source checksum is invalid' using errcode = '22023';
    end if;

    -- Serialize exact-hash registration without imposing a destructive unique
    -- constraint on legacy/backfilled rows that may already contain duplicates.
    perform pg_catalog.pg_advisory_xact_lock(
        pg_catalog.hashtextextended(normalized_sha, 0)
    );
    if exists (
        select 1
        from public.source_files
        join public.document_versions
          on document_versions.source_file_id = source_files.id
        join public.knowledge_documents as registered_documents
          on registered_documents.id = document_versions.document_id
        where source_files.sha256 = normalized_sha
          and registered_documents.status <> 'ARCHIVED'
    ) then
        raise exception 'An identical source is already registered'
            using errcode = '23505';
    end if;

    select id into actor_subject_id
    from public.access_subjects
    where subject_type = 'USER' and user_id = actor;
    if actor_subject_id is null then
        raise exception 'Current user has no ACL subject' using errcode = '23503';
    end if;

    insert into public.source_files (
        id,
        bucket_name,
        object_path,
        original_file_name,
        mime_type,
        size_bytes,
        sha256,
        created_by
    ) values (
        p_source_id,
        btrim(p_bucket_name),
        btrim(p_object_path),
        btrim(p_original_file_name),
        lower(btrim(p_mime_type)),
        p_size_bytes,
        normalized_sha,
        actor
    ) returning * into created_source;

    insert into public.knowledge_documents (
        title,
        description,
        document_type,
        category,
        metadata,
        created_by
    ) values (
        btrim(p_title),
        coalesce(p_description, ''),
        upper(btrim(coalesce(p_document_type, 'GENERAL'))),
        nullif(btrim(p_category), ''),
        p_metadata,
        actor
    ) returning * into created_document;

    insert into public.document_permissions (
        document_id, subject_id, permission, granted_by
    )
    select created_document.id, actor_subject_id, permission, actor
    from (
        values
            ('READ'),
            ('DOWNLOAD'),
            ('MANAGE'),
            ('REVIEW'),
            ('PUBLISH'),
            ('ARCHIVE'),
            ('MANAGE_PERMISSION')
    ) as grants(permission);

    insert into public.document_versions (
        document_id,
        version_number,
        source_file_id,
        status,
        previous_version_id,
        change_summary,
        effective_date,
        created_by
    ) values (
        created_document.id,
        1,
        created_source.id,
        'DRAFT',
        null,
        coalesce(p_change_summary, ''),
        p_effective_date,
        actor
    ) returning * into created_version;

    insert into public.processing_jobs (
        document_version_id,
        job_type,
        status,
        attempt_no,
        requested_by
    ) values (
        created_version.id,
        'INITIAL_PROCESS',
        'PENDING',
        1,
        actor
    ) returning * into created_job;

    perform public.write_enterprise_audit(
        'DOCUMENT_CREATED',
        'knowledge_document',
        created_document.id,
        null,
        jsonb_build_object(
            'status', created_document.status,
            'title', created_document.title,
            'atomic_upload', true
        ),
        null
    );
    perform public.write_enterprise_audit(
        'DOCUMENT_VERSION_CREATED',
        'document_version',
        created_version.id,
        null,
        jsonb_build_object(
            'document_id', created_document.id,
            'version_number', 1,
            'status', created_version.status,
            'processing_job_id', created_job.id
        ),
        null
    );

    return jsonb_build_object(
        'document', to_jsonb(created_document),
        'version', to_jsonb(created_version),
        'processing_job', to_jsonb(created_job),
        'source_file', to_jsonb(created_source)
    );
end;
$$;

revoke all on function public.create_enterprise_document_upload(
    uuid, text, text, text, text, bigint, text,
    text, text, text, text, jsonb, text, date
) from public, anon;
grant execute on function public.create_enterprise_document_upload(
    uuid, text, text, text, text, bigint, text,
    text, text, text, text, jsonb, text, date
) to authenticated;

-- Explain effective ACL sources without leaking the membership graph to a
-- global policy manager who lacks MANAGE_PERMISSION on the target document.
create or replace function public.explain_document_access(
    p_user_id uuid,
    p_document_id uuid,
    p_permission text default 'READ'
)
returns jsonb
language plpgsql
stable
security definer
set search_path = ''
as $$
declare
    actor uuid := auth.uid();
    normalized_permission text := upper(btrim(coalesce(p_permission, '')));
    source_labels jsonb;
begin
    if actor is null then
        raise exception 'Authentication required' using errcode = '42501';
    end if;
    if actor <> p_user_id and not (
        public.has_functional_permission(actor, 'MANAGE_ACCESS_POLICY')
        and public.has_document_permission(actor, p_document_id, 'MANAGE_PERMISSION')
    ) then
        raise exception 'Access explanation is not permitted' using errcode = '42501';
    end if;
    if normalized_permission not in (
        'READ', 'DOWNLOAD', 'MANAGE', 'REVIEW', 'PUBLISH',
        'ARCHIVE', 'MANAGE_PERMISSION'
    ) then
        raise exception 'Unsupported document permission' using errcode = '22023';
    end if;

    select coalesce(jsonb_agg(source_label order by source_label), '[]'::jsonb)
    into source_labels
    from (
        select distinct concat(
            access_subjects.subject_type,
            ':',
            coalesce(
                roles.code,
                groups.code,
                departments.code,
                access_subjects.user_id::text
            ),
            ':',
            document_permissions.permission
        ) as source_label
        from public.document_permissions
        join public.access_subjects
          on access_subjects.id = document_permissions.subject_id
        left join public.roles on roles.id = access_subjects.role_id
        left join public.groups on groups.id = access_subjects.group_id
        left join public.departments on departments.id = access_subjects.department_id
        where document_permissions.document_id = p_document_id
          and document_permissions.status = 'ACTIVE'
          and document_permissions.permission in (normalized_permission, 'MANAGE')
          and document_permissions.subject_id in (
              select public.enterprise_subject_ids_for_user(p_user_id)
          )
    ) as effective_sources;

    return jsonb_build_object(
        'allowed', public.has_document_permission(
            p_user_id, p_document_id, normalized_permission
        ),
        'sources', source_labels
    );
end;
$$;

revoke all on function public.explain_document_access(uuid, uuid, text)
from public, anon;
grant execute on function public.explain_document_access(uuid, uuid, text)
to authenticated;

create or replace function public.test_document_access(
    p_user_id uuid,
    p_document_id uuid,
    p_permission text default 'READ'
)
returns boolean
language plpgsql
stable
security definer
set search_path = ''
as $$
declare
    actor uuid := auth.uid();
begin
    if actor is null then
        raise exception 'Authentication required' using errcode = '42501';
    end if;
    if actor <> p_user_id and not (
        public.has_functional_permission(actor, 'MANAGE_ACCESS_POLICY')
        and public.has_document_permission(actor, p_document_id, 'MANAGE_PERMISSION')
    ) then
        raise exception 'Cannot test another principal''s access'
            using errcode = '42501';
    end if;
    return public.has_document_permission(
        p_user_id,
        p_document_id,
        upper(btrim(p_permission))
    );
end;
$$;

revoke all on function public.test_document_access(uuid, uuid, text)
from public, anon;
grant execute on function public.test_document_access(uuid, uuid, text)
to authenticated;

create or replace function public.get_document_version_review_context(
    p_version_id uuid
)
returns jsonb
language plpgsql
stable
security definer
set search_path = ''
as $$
declare
    actor uuid := auth.uid();
    selected_document public.knowledge_documents;
    selected_version public.document_versions;
    selected_source public.source_files;
    latest_job public.processing_jobs;
begin
    select versions.* into selected_version
    from public.document_versions as versions
    where versions.id = p_version_id;
    if not found then
        return null;
    end if;

    select documents.* into selected_document
    from public.knowledge_documents as documents
    where documents.id = selected_version.document_id;
    if actor is null or not (
        (
            public.has_functional_permission(actor, 'REVIEW_DOCUMENT')
            and public.has_document_permission(actor, selected_document.id, 'REVIEW')
        )
        or (
            public.has_functional_permission(actor, 'PUBLISH_DOCUMENT')
            and public.has_document_permission(actor, selected_document.id, 'PUBLISH')
        )
        or (
            public.has_functional_permission(actor, 'MANAGE_DOCUMENT')
            and public.has_document_permission(actor, selected_document.id, 'MANAGE')
        )
    ) then
        raise exception 'Version review context is not permitted' using errcode = '42501';
    end if;

    select sources.* into selected_source
    from public.source_files as sources
    where sources.id = selected_version.source_file_id;

    select jobs.* into latest_job
    from public.processing_jobs as jobs
    where jobs.document_version_id = p_version_id
    order by jobs.attempt_no desc, jobs.requested_at desc, jobs.id desc
    limit 1;

    return jsonb_build_object(
        'document', to_jsonb(selected_document),
        'version', to_jsonb(selected_version),
        'source_file', jsonb_build_object(
            'id', selected_source.id,
            'original_file_name', selected_source.original_file_name,
            'mime_type', selected_source.mime_type,
            'size_bytes', selected_source.size_bytes,
            'sha256', selected_source.sha256,
            'created_by', selected_source.created_by,
            'created_at', selected_source.created_at
        ),
        'latest_processing_job', case
            when latest_job.id is null then null
            else to_jsonb(latest_job)
        end,
        'stage_history', case
            when latest_job.id is null then '[]'::jsonb
            else coalesce((
                select jsonb_agg(to_jsonb(history) order by history.started_at, history.id)
                from public.processing_stage_history as history
                where history.processing_job_id = latest_job.id
            ), '[]'::jsonb)
        end,
        'errors', case
            when latest_job.id is null then '[]'::jsonb
            else coalesce((
                select jsonb_agg(
                    jsonb_build_object(
                        'id', errors.id,
                        'processing_job_id', errors.processing_job_id,
                        'stage', errors.stage,
                        'error_type', errors.error_type,
                        'error_code', errors.error_code,
                        'safe_message', errors.safe_message,
                        'retryable', errors.retryable,
                        'created_at', errors.created_at
                    ) order by errors.created_at desc, errors.id
                )
                from public.processing_errors as errors
                where errors.processing_job_id = latest_job.id
            ), '[]'::jsonb)
        end,
        'extracted_chunks', coalesce((
            select jsonb_agg(
                jsonb_build_object(
                    'chunk_id', chunks.id,
                    'chunk_index', chunks.chunk_index,
                    'content', chunks.content,
                    'page_start', chunks.page_start,
                    'page_end', chunks.page_end,
                    'section_path', chunks.section_path,
                    'metadata', chunks.metadata
                ) order by chunks.chunk_index
            )
            from public.knowledge_chunks as chunks
            where chunks.document_version_id = p_version_id
        ), '[]'::jsonb)
    );
end;
$$;

revoke all on function public.get_document_version_review_context(uuid)
from public, anon;
grant execute on function public.get_document_version_review_context(uuid)
to authenticated;

comment on function public.create_enterprise_document_upload(
    uuid, text, text, text, text, bigint, text,
    text, text, text, text, jsonb, text, date
) is
    'Atomic SourceFile + logical Document + v1 + ProcessingJob registration with exact-SHA duplicate protection.';
comment on function public.explain_document_access(uuid, uuid, text) is
    'Returns effective allow/deny plus Direct/Role/Group/Department ACL sources for an authorized policy manager.';
comment on function public.get_document_version_review_context(uuid) is
    'Candidate-only review projection with extracted chunks and safe processing diagnostics; raw chunk RLS remains fail closed.';

-- Keep the legacy notebook upload surface operational after the Enterprise
-- version-scoped ingestion cutover. Run after
-- 23_enterprise_workflow_completion.sql.
--
-- Migration 19 made ingestion_jobs.document_version_id mandatory. Existing
-- legacy documents were backfilled by migration 18, but documents uploaded
-- later through /notebooks/{id}/documents had no Enterprise version mapping.
-- The ingestion trigger therefore rejected their queue rows. This bridge
-- creates the fail-closed Enterprise draft/source/version records lazily in
-- the same transaction that enqueues the legacy document.

create or replace function public.ensure_legacy_document_enterprise_mapping(
    p_legacy_document_id uuid
)
returns uuid
language plpgsql
security definer
set search_path = ''
as $$
declare
    legacy_document public.documents;
    mapped_source public.source_files;
    logical_document public.knowledge_documents;
    mapped_version public.document_versions;
    previous_enterprise_version_id uuid;
    next_enterprise_version_number integer;
    owner_subject_id uuid;
begin
    select documents.*
    into legacy_document
    from public.documents as documents
    where documents.id = p_legacy_document_id
      and documents.is_active
    for update;

    if not found then
        raise exception 'Legacy document is not available for Enterprise mapping'
            using errcode = 'P0002';
    end if;

    -- Different legacy rows in one version family must choose version numbers
    -- serially even when uploads race.
    perform pg_catalog.pg_advisory_xact_lock(
        pg_catalog.hashtextextended(
            'legacy-enterprise-bridge:'
            || legacy_document.owner_id::text || ':'
            || legacy_document.notebook_id::text || ':'
            || legacy_document.version_group_id::text,
            0
        )
    );

    select versions.*
    into mapped_version
    from public.document_versions as versions
    where versions.legacy_document_id = legacy_document.id;

    if mapped_version.id is not null then
        return mapped_version.id;
    end if;

    insert into public.source_files (
        bucket_name,
        object_path,
        original_file_name,
        mime_type,
        size_bytes,
        sha256,
        created_by,
        created_at,
        legacy_document_id
    ) values (
        legacy_document.storage_bucket,
        legacy_document.storage_object_path,
        legacy_document.original_filename,
        legacy_document.mime_type,
        legacy_document.size_bytes,
        legacy_document.content_hash,
        legacy_document.owner_id,
        legacy_document.created_at,
        legacy_document.id
    )
    on conflict (legacy_document_id) do nothing;

    select source_files.*
    into mapped_source
    from public.source_files as source_files
    where source_files.legacy_document_id = legacy_document.id;

    if mapped_source.id is null then
        raise exception 'Legacy source file could not be mapped'
            using errcode = '23503';
    end if;

    insert into public.knowledge_documents (
        title,
        description,
        document_type,
        effective_date,
        status,
        metadata,
        created_by,
        created_at,
        updated_at,
        legacy_notebook_id,
        legacy_version_group_id
    ) values (
        legacy_document.original_filename,
        '',
        'GENERAL',
        legacy_document.effective_from,
        'DRAFT',
        jsonb_build_object(
            'migration', 'legacy_notebook_runtime_bridge_v1'
        ),
        legacy_document.owner_id,
        legacy_document.created_at,
        legacy_document.updated_at,
        legacy_document.notebook_id,
        legacy_document.version_group_id
    )
    on conflict (
        created_by,
        legacy_notebook_id,
        legacy_version_group_id
    ) where legacy_notebook_id is not null
        and legacy_version_group_id is not null
    do nothing;

    select documents.*
    into logical_document
    from public.knowledge_documents as documents
    where documents.created_by = legacy_document.owner_id
      and documents.legacy_notebook_id = legacy_document.notebook_id
      and documents.legacy_version_group_id = legacy_document.version_group_id
    for update;

    if logical_document.id is null then
        raise exception 'Legacy logical document could not be mapped'
            using errcode = '23503';
    end if;

    select versions.id
    into previous_enterprise_version_id
    from public.document_versions as versions
    where versions.legacy_document_id = legacy_document.supersedes_document_id
      and versions.document_id = logical_document.id;

    if previous_enterprise_version_id is null then
        select versions.id
        into previous_enterprise_version_id
        from public.document_versions as versions
        where versions.document_id = logical_document.id
        order by versions.version_number desc, versions.id
        limit 1;
    end if;

    select coalesce(max(versions.version_number), 0) + 1
    into next_enterprise_version_number
    from public.document_versions as versions
    where versions.document_id = logical_document.id;

    insert into public.document_versions (
        document_id,
        version_number,
        source_file_id,
        status,
        previous_version_id,
        change_summary,
        effective_date,
        created_by,
        created_at,
        updated_at,
        legacy_document_id
    ) values (
        logical_document.id,
        next_enterprise_version_number,
        mapped_source.id,
        'DRAFT',
        previous_enterprise_version_id,
        'Uploaded from the legacy notebook interface.',
        legacy_document.effective_from,
        legacy_document.owner_id,
        legacy_document.created_at,
        legacy_document.updated_at,
        legacy_document.id
    )
    returning * into mapped_version;

    select subjects.id
    into owner_subject_id
    from public.access_subjects as subjects
    where subjects.subject_type = 'USER'
      and subjects.user_id = legacy_document.owner_id;

    if owner_subject_id is null then
        raise exception 'Legacy document owner has no Enterprise access subject'
            using errcode = '23503';
    end if;

    insert into public.document_permissions (
        document_id,
        subject_id,
        permission,
        granted_by
    )
    select
        logical_document.id,
        owner_subject_id,
        permissions.permission,
        legacy_document.owner_id
    from (
        values
            ('READ'),
            ('DOWNLOAD'),
            ('MANAGE'),
            ('REVIEW'),
            ('PUBLISH'),
            ('ARCHIVE'),
            ('MANAGE_PERMISSION')
    ) as permissions(permission)
    on conflict (
        document_id,
        subject_id,
        permission
    ) where status = 'ACTIVE'
    do nothing;

    return mapped_version.id;
end;
$$;

revoke all on function public.ensure_legacy_document_enterprise_mapping(uuid)
from public, anon, authenticated;

create or replace function public.resolve_legacy_ingestion_version()
returns trigger
language plpgsql
security definer
set search_path = ''
as $$
begin
    if new.document_version_id is null then
        select versions.id into new.document_version_id
        from public.document_versions as versions
        where versions.legacy_document_id = new.document_id;
    end if;

    if new.document_version_id is null then
        new.document_version_id :=
            public.ensure_legacy_document_enterprise_mapping(new.document_id);
    end if;

    if new.document_version_id is null then
        raise exception 'No enterprise document version maps legacy document %', new.document_id
            using errcode = '23503';
    end if;
    return new;
end;
$$;

revoke all on function public.resolve_legacy_ingestion_version()
from public, anon, authenticated;

comment on function public.ensure_legacy_document_enterprise_mapping(uuid) is
    'Creates the fail-closed Enterprise draft/source/version/owner ACL mapping required before a legacy notebook document can enter ingestion.';

-- Canonical document metadata, evidence assertions, persisted parents and
-- rebuildable retrieval projections. Run after 24_legacy_notebook_enterprise_bridge.sql.

create extension if not exists unaccent with schema extensions;

alter table public.knowledge_documents
    add column if not exists document_number_normalized text,
    add column if not exists domain text,
    add column if not exists project_code text,
    add column if not exists department_code text,
    add column if not exists visibility text not null default 'INTERNAL',
    add column if not exists metadata_revision bigint not null default 1,
    add column if not exists deleted_at timestamptz;

alter table public.knowledge_documents
    drop constraint if exists knowledge_documents_visibility;
alter table public.knowledge_documents
    add constraint knowledge_documents_visibility check (
        visibility in ('PRIVATE', 'INTERNAL', 'RESTRICTED', 'PUBLIC')
    );
alter table public.knowledge_documents
    drop constraint if exists knowledge_documents_metadata_revision;
alter table public.knowledge_documents
    add constraint knowledge_documents_metadata_revision check (metadata_revision > 0);

alter table public.document_versions
    add column if not exists version_label text,
    add column if not exists effective_to date,
    add column if not exists canonical_content_hash text,
    add column if not exists language text,
    add column if not exists page_count integer,
    add column if not exists parser_name text,
    add column if not exists parser_version text,
    add column if not exists ocr_engine text,
    add column if not exists ocr_version text,
    add column if not exists chunker_name text,
    add column if not exists chunker_version text,
    add column if not exists embedding_model text,
    add column if not exists embedding_dimensions integer,
    add column if not exists metadata_revision bigint not null default 1,
    add column if not exists ingested_at timestamptz;

alter table public.document_versions
    drop constraint if exists document_versions_effective_range;
alter table public.document_versions
    add constraint document_versions_effective_range check (
        effective_date is null or effective_to is null or effective_date <= effective_to
    );
alter table public.document_versions
    drop constraint if exists document_versions_page_count;
alter table public.document_versions
    add constraint document_versions_page_count check (page_count is null or page_count >= 0);
alter table public.document_versions
    drop constraint if exists document_versions_embedding_dimensions;
alter table public.document_versions
    add constraint document_versions_embedding_dimensions check (
        embedding_dimensions is null or embedding_dimensions > 0
    );

create or replace function public.normalize_search_text(p_value text)
returns text
language sql
immutable
set search_path = ''
as $$
    select btrim(regexp_replace(
        replace(
            translate(
                coalesce(p_value, ''),
                chr(173) || chr(8203) || chr(8204) || chr(8205) || chr(65279),
                ''
            ),
            chr(160),
            ' '
        ),
        '[[:space:]]+',
        ' ',
        'g'
    ));
$$;

create or replace function public.fold_vietnamese_text(p_value text)
returns text
language sql
stable
set search_path = ''
as $$
    select lower(extensions.unaccent(public.normalize_search_text(coalesce(p_value, ''))));
$$;

create or replace function public.normalize_document_number(p_value text)
returns text
language sql
stable
set search_path = ''
as $$
    select regexp_replace(public.fold_vietnamese_text(p_value), '[^a-z0-9]+', '', 'g');
$$;

create table if not exists public.retrieval_projection_refresh_queue (
    document_id uuid primary key references public.knowledge_documents (id) on delete cascade,
    requested_metadata_revision bigint not null,
    requested_at timestamptz not null default now(),
    processed_at timestamptz,
    last_error text,
    constraint retrieval_projection_refresh_revision check (requested_metadata_revision > 0)
);

create or replace function public.prepare_knowledge_document_metadata()
returns trigger
language plpgsql
set search_path = ''
as $$
begin
    new.document_number_normalized := nullif(
        public.normalize_document_number(new.document_number),
        ''
    );
    if tg_op = 'UPDATE' and row(
        new.document_number, new.title, new.document_type, new.category,
        new.domain, new.project_code, new.department_code, new.owner_department_id,
        new.visibility, new.current_version_id, new.status, new.deleted_at
    ) is distinct from row(
        old.document_number, old.title, old.document_type, old.category,
        old.domain, old.project_code, old.department_code, old.owner_department_id,
        old.visibility, old.current_version_id, old.status, old.deleted_at
    ) then
        new.metadata_revision := old.metadata_revision + 1;
    end if;
    return new;
end;
$$;

drop trigger if exists knowledge_documents_prepare_metadata
on public.knowledge_documents;
create trigger knowledge_documents_prepare_metadata
before insert or update on public.knowledge_documents
for each row execute function public.prepare_knowledge_document_metadata();

create or replace function public.queue_retrieval_projection_refresh()
returns trigger
language plpgsql
security definer
set search_path = ''
as $$
begin
    if tg_op = 'INSERT' or new.metadata_revision is distinct from old.metadata_revision then
        insert into public.retrieval_projection_refresh_queue (
            document_id, requested_metadata_revision, requested_at, processed_at, last_error
        ) values (new.id, new.metadata_revision, now(), null, null)
        on conflict (document_id) do update
        set requested_metadata_revision = excluded.requested_metadata_revision,
            requested_at = excluded.requested_at,
            processed_at = null,
            last_error = null;
    end if;
    return new;
end;
$$;

drop trigger if exists knowledge_documents_queue_projection_refresh
on public.knowledge_documents;
create trigger knowledge_documents_queue_projection_refresh
after insert or update on public.knowledge_documents
for each row execute function public.queue_retrieval_projection_refresh();

-- Backfill normalization without pretending that missing business metadata is known.
update public.knowledge_documents
set document_number_normalized = nullif(
    public.normalize_document_number(document_number),
    ''
)
where document_number_normalized is distinct from nullif(
    public.normalize_document_number(document_number),
    ''
);

create index if not exists knowledge_documents_number_route_idx
    on public.knowledge_documents (document_number_normalized)
    where deleted_at is null and document_number_normalized is not null;
create index if not exists knowledge_documents_retrieval_scope_v2_idx
    on public.knowledge_documents (
        status, current_version_id, document_type, department_code, project_code
    ) where deleted_at is null;

create table if not exists public.knowledge_parent_chunks (
    id uuid primary key,
    document_id uuid not null,
    document_version_id uuid not null,
    parent_index integer not null,
    heading text,
    section_path text[] not null default '{}',
    content text not null,
    content_summary text,
    page_start integer,
    page_end integer,
    source_block_ids text[] not null default '{}',
    token_count integer not null,
    content_hash text not null,
    metadata_revision bigint not null default 1,
    created_at timestamptz not null default now(),
    constraint knowledge_parent_chunks_version_document_fk
        foreign key (document_version_id, document_id)
        references public.document_versions (id, document_id) on delete cascade,
    constraint knowledge_parent_chunks_id_version_document_key
        unique (id, document_version_id, document_id),
    constraint knowledge_parent_chunks_version_index_key
        unique (document_version_id, parent_index),
    constraint knowledge_parent_chunks_content check (char_length(btrim(content)) > 0),
    constraint knowledge_parent_chunks_token_count check (token_count > 0),
    constraint knowledge_parent_chunks_page_range check (
        (page_start is null or page_start > 0)
        and (page_end is null or page_end > 0)
        and (page_start is null or page_end is null or page_start <= page_end)
    ),
    constraint knowledge_parent_chunks_metadata_revision check (metadata_revision > 0)
);

alter table public.knowledge_chunks
    add column if not exists parent_id uuid,
    add column if not exists parent_chunk_index integer,
    add column if not exists content_kind text,
    add column if not exists section_title text,
    add column if not exists char_start integer,
    add column if not exists char_end integer,
    add column if not exists source_block_ids text[] not null default '{}',
    add column if not exists language text,
    add column if not exists metadata_revision bigint not null default 1;

do $$
begin
    if not exists (
        select 1 from pg_constraint
        where conrelid = 'public.knowledge_chunks'::regclass
          and conname = 'knowledge_chunks_parent_same_version_fk'
    ) then
        alter table public.knowledge_chunks
            add constraint knowledge_chunks_parent_same_version_fk
            foreign key (parent_id, document_version_id, document_id)
            references public.knowledge_parent_chunks (
                id, document_version_id, document_id
            ) on delete restrict;
    end if;
end;
$$;

alter table public.knowledge_chunks
    drop constraint if exists knowledge_chunks_character_range;
alter table public.knowledge_chunks
    add constraint knowledge_chunks_character_range check (
        (char_start is null or char_start >= 0)
        and (char_end is null or char_end >= 0)
        and (char_start is null or char_end is null or char_start <= char_end)
    );

create index if not exists knowledge_parent_chunks_document_version_idx
    on public.knowledge_parent_chunks (document_id, document_version_id, parent_index);
create index if not exists knowledge_chunks_parent_child_idx
    on public.knowledge_chunks (parent_id, parent_chunk_index, chunk_index)
    where parent_id is not null;
create index if not exists knowledge_chunks_metadata_revision_idx
    on public.knowledge_chunks (document_id, metadata_revision);

create table if not exists public.document_metadata_assertions (
    id uuid primary key default gen_random_uuid(),
    document_id uuid not null references public.knowledge_documents (id) on delete cascade,
    document_version_id uuid references public.document_versions (id) on delete cascade,
    field_name text not null,
    value text not null,
    normalized_value text not null,
    source_type text not null,
    confidence double precision not null,
    verification_status text not null default 'UNVERIFIED',
    evidence jsonb not null default '[]'::jsonb,
    model text,
    prompt_version text,
    input_checksum text,
    assertion_hash text generated always as (
        encode(public.knowledge_digest(
            pg_catalog.convert_to(
                field_name || chr(31) || normalized_value || chr(31) ||
                source_type || chr(31) || coalesce(prompt_version, ''),
                'UTF8'
            ),
            'sha256'
        ), 'hex')
    ) stored,
    created_at timestamptz not null default now(),
    verified_by uuid references auth.users (id) on delete set null,
    verified_at timestamptz,
    rejection_reason text,
    constraint document_metadata_assertions_source check (
        source_type in (
            'user_confirmed', 'system_record', 'filename_extracted',
            'content_extracted', 'rule_inferred', 'llm_inferred'
        )
    ),
    constraint document_metadata_assertions_confidence check (
        confidence >= 0 and confidence <= 1
    ),
    constraint document_metadata_assertions_verification check (
        verification_status in ('UNVERIFIED', 'VERIFIED', 'REJECTED')
    ),
    constraint document_metadata_assertions_evidence check (
        jsonb_typeof(evidence) = 'array'
    ),
    constraint document_metadata_assertions_unique
        unique (document_id, document_version_id, assertion_hash)
);

create index if not exists document_metadata_assertions_review_idx
    on public.document_metadata_assertions (
        verification_status, field_name, created_at desc
    );
create index if not exists document_metadata_assertions_document_idx
    on public.document_metadata_assertions (document_id, document_version_id, field_name);

create table if not exists public.chunk_retrieval_projections (
    chunk_id uuid primary key references public.knowledge_chunks (id) on delete cascade,
    document_id uuid not null,
    document_version_id uuid not null,
    parent_id uuid,
    projection_version text not null,
    identity_text text not null default '',
    structure_text text not null default '',
    content_text text not null,
    context_text text not null default '',
    alias_text text not null default '',
    embedding_text text not null,
    search_vector_original tsvector not null,
    search_vector_folded tsvector not null,
    embedding vector(1536),
    embedding_model text not null,
    embedding_dimensions integer not null,
    normalization_version text not null,
    source_content_hash text not null,
    source_metadata_revision bigint not null,
    embedding_metadata_revision bigint not null,
    indexed_at timestamptz not null default now(),
    index_status text not null default 'READY',
    constraint chunk_retrieval_projections_chunk_version_document_fk
        foreign key (chunk_id, document_version_id, document_id)
        references public.knowledge_chunks (id, document_version_id, document_id)
        on delete cascade,
    constraint chunk_retrieval_projections_parent_fk
        foreign key (parent_id, document_version_id, document_id)
        references public.knowledge_parent_chunks (id, document_version_id, document_id)
        on delete restrict,
    constraint chunk_retrieval_projections_dimensions check (embedding_dimensions > 0),
    constraint chunk_retrieval_projections_revision check (source_metadata_revision > 0),
    constraint chunk_retrieval_projections_embedding_revision check (
        embedding_metadata_revision > 0
    ),
    constraint chunk_retrieval_projections_status check (
        index_status in ('READY', 'STALE', 'FAILED')
    )
);

create index if not exists chunk_retrieval_projection_scope_idx
    on public.chunk_retrieval_projections (
        document_id, document_version_id, parent_id, indexed_at desc
    );
create index if not exists chunk_retrieval_projection_original_idx
    on public.chunk_retrieval_projections using gin (search_vector_original);
create index if not exists chunk_retrieval_projection_folded_idx
    on public.chunk_retrieval_projections using gin (search_vector_folded);
create index if not exists chunk_retrieval_projection_embedding_hnsw_idx
    on public.chunk_retrieval_projections using hnsw (embedding vector_cosine_ops);
create index if not exists chunk_retrieval_projection_freshness_idx
    on public.chunk_retrieval_projections (
        document_id, source_metadata_revision, embedding_metadata_revision
    );

create or replace function public.refresh_document_lexical_projection()
returns trigger
language plpgsql
security definer
set search_path = ''
as $$
begin
    if new.metadata_revision is distinct from old.metadata_revision then
        update public.chunk_retrieval_projections as projections
        set identity_text = coalesce(new.document_number, ''),
            context_text = concat_ws(' ',
                new.title,
                chunks.section_path,
                chunks.contextual_content
            ),
            search_vector_original =
                setweight(to_tsvector('simple', public.normalize_search_text(
                    concat_ws(' ', new.document_number, projections.structure_text)
                )), 'A')
                || setweight(to_tsvector('simple', public.normalize_search_text(
                    projections.content_text
                )), 'B')
                || setweight(to_tsvector('simple', public.normalize_search_text(
                    concat_ws(' ', new.title, chunks.section_path,
                        chunks.contextual_content)
                )), 'C')
                || setweight(to_tsvector('simple', public.normalize_search_text(
                    concat_ws(' ', new.document_type, new.domain,
                        projections.alias_text)
                )), 'D'),
            search_vector_folded =
                setweight(to_tsvector('simple', public.fold_vietnamese_text(
                    concat_ws(' ', new.document_number, projections.structure_text)
                )), 'A')
                || setweight(to_tsvector('simple', public.fold_vietnamese_text(
                    projections.content_text
                )), 'B')
                || setweight(to_tsvector('simple', public.fold_vietnamese_text(
                    concat_ws(' ', new.title, chunks.section_path,
                        chunks.contextual_content)
                )), 'C')
                || setweight(to_tsvector('simple', public.fold_vietnamese_text(
                    concat_ws(' ', new.document_type, new.domain,
                        projections.alias_text)
                )), 'D'),
            source_metadata_revision = new.metadata_revision,
            indexed_at = now()
        from public.knowledge_chunks as chunks
        where chunks.id = projections.chunk_id
          and projections.document_id = new.id;
    end if;
    return new;
end;
$$;

drop trigger if exists knowledge_documents_refresh_lexical_projection
on public.knowledge_documents;
create trigger knowledge_documents_refresh_lexical_projection
after update of metadata_revision on public.knowledge_documents
for each row execute function public.refresh_document_lexical_projection();

-- The v1 completion RPC remains for old workers. New workers use this wrapper;
-- the call and all derived writes are one transaction, so a projection failure
-- rolls back the underlying completion as well.
create or replace function public.complete_processing_job_v2(
    p_job_id uuid,
    p_worker_id text,
    p_claim_token uuid,
    p_chunks jsonb default null
)
returns public.processing_jobs
language plpgsql
security definer
set search_path = ''
as $$
declare
    selected_job public.processing_jobs;
    selected_version public.document_versions;
    selected_document public.knowledge_documents;
    completed_job public.processing_jobs;
    version_artifact jsonb;
begin
    if auth.role() <> 'service_role' then
        raise exception 'Service role required' using errcode = '42501';
    end if;
    select * into selected_job from public.processing_jobs where id = p_job_id;
    if selected_job.id is null then
        raise exception 'Processing job not found' using errcode = 'P0002';
    end if;
    select * into selected_version
    from public.document_versions where id = selected_job.document_version_id;
    select * into selected_document
    from public.knowledge_documents where id = selected_version.document_id;

    completed_job := public.complete_processing_job(
        p_job_id, p_worker_id, p_claim_token, p_chunks
    );
    if p_chunks is null then
        return completed_job;
    end if;

    select chunk.value -> 'version_artifact' into version_artifact
    from jsonb_array_elements(p_chunks) as chunk(value)
    where jsonb_typeof(chunk.value -> 'version_artifact') = 'object'
    limit 1;
    if version_artifact is not null then
        update public.document_versions
        set canonical_content_hash = nullif(version_artifact ->> 'canonical_content_hash', ''),
            language = nullif(version_artifact ->> 'language', ''),
            page_count = nullif(version_artifact ->> 'page_count', '')::integer,
            parser_name = nullif(version_artifact ->> 'parser_name', ''),
            parser_version = nullif(version_artifact ->> 'parser_version', ''),
            ocr_engine = nullif(version_artifact ->> 'ocr_engine', ''),
            ocr_version = nullif(version_artifact ->> 'ocr_version', ''),
            chunker_name = nullif(version_artifact ->> 'chunker_name', ''),
            chunker_version = nullif(version_artifact ->> 'chunker_version', ''),
            embedding_model = nullif(version_artifact ->> 'embedding_model', ''),
            embedding_dimensions = nullif(
                version_artifact ->> 'embedding_dimensions', ''
            )::integer,
            ingested_at = now(),
            metadata_revision = metadata_revision + 1
        where id = selected_version.id;
    end if;

    delete from public.knowledge_parent_chunks
    where document_version_id = selected_version.id;

    insert into public.knowledge_parent_chunks (
        id, document_id, document_version_id, parent_index, heading,
        section_path, content, content_summary, page_start, page_end,
        source_block_ids, token_count, content_hash, metadata_revision
    )
    select distinct on ((parent.value ->> 'parent_id')::uuid)
        (parent.value ->> 'parent_id')::uuid,
        selected_document.id,
        selected_version.id,
        (row_number() over (order by (chunk.value ->> 'chunk_index')::integer) - 1)::integer,
        nullif(parent.value ->> 'heading', ''),
        coalesce(array(
            select jsonb_array_elements_text(parent.value -> 'section_path')
        ), '{}'),
        parent.value ->> 'content',
        nullif(parent.value ->> 'content_summary', ''),
        nullif(parent.value ->> 'page_start', '')::integer,
        nullif(parent.value ->> 'page_end', '')::integer,
        coalesce(array(
            select jsonb_array_elements_text(parent.value -> 'source_block_ids')
        ), '{}'),
        greatest(coalesce((parent.value ->> 'token_count')::integer, 1), 1),
        lower(parent.value ->> 'content_hash'),
        selected_document.metadata_revision
    from jsonb_array_elements(p_chunks) as chunk(value)
    cross join lateral (select chunk.value -> 'parent' as value) as parent
    where jsonb_typeof(parent.value) = 'object'
      and nullif(parent.value ->> 'parent_id', '') is not null
      and nullif(btrim(parent.value ->> 'content'), '') is not null
    order by (parent.value ->> 'parent_id')::uuid,
             (chunk.value ->> 'chunk_index')::integer;

    update public.knowledge_chunks as chunks
    set parent_id = nullif(item.value #>> '{projection,parent_id}', '')::uuid,
        parent_chunk_index = nullif(
            item.value #>> '{projection,parent_child_index}', ''
        )::integer,
        content_kind = nullif(
            coalesce(
                item.value #>> '{metadata,retrieval_metadata,content_kind}',
                item.value #>> '{metadata,content_kind}'
            ), ''
        ),
        section_title = nullif(
            coalesce(
                item.value #>> '{metadata,retrieval_metadata,section_title}',
                item.value #>> '{metadata,section_title}'
            ), ''
        ),
        char_start = nullif(item.value #>> '{metadata,char_start}', '')::integer,
        char_end = nullif(item.value #>> '{metadata,char_end}', '')::integer,
        source_block_ids = coalesce(array(
            select jsonb_array_elements_text(
                coalesce(item.value #> '{metadata,source_block_ids}', '[]'::jsonb)
            )
        ), '{}'),
        language = nullif(
            coalesce(
                item.value #>> '{metadata,retrieval_metadata,language}',
                selected_version.language
            ), ''
        ),
        metadata_revision = selected_document.metadata_revision,
        metadata = chunks.metadata
            - 'parent_context'
            - 'embedding_text'
            - 'search_text'
    from jsonb_array_elements(p_chunks) as item(value)
    where chunks.id = (item.value ->> 'id')::uuid
      and chunks.document_version_id = selected_version.id;

    insert into public.document_metadata_assertions (
        document_id, document_version_id, field_name, value, normalized_value,
        source_type, confidence, verification_status, evidence, model,
        prompt_version, input_checksum
    )
    select
        selected_document.id,
        selected_version.id,
        assertion.value ->> 'field_name',
        assertion.value ->> 'value',
        assertion.value ->> 'normalized_value',
        assertion.value ->> 'source',
        least(greatest((assertion.value ->> 'confidence')::double precision, 0), 1),
        case when coalesce((assertion.value ->> 'verified')::boolean, false)
             then 'VERIFIED' else 'UNVERIFIED' end,
        coalesce(assertion.value -> 'evidence', '[]'::jsonb),
        nullif(assertion.value ->> 'model', ''),
        nullif(assertion.value ->> 'prompt_version', ''),
        nullif(assertion.value ->> 'input_checksum', '')
    from jsonb_array_elements(p_chunks) as chunk(value)
    cross join lateral jsonb_array_elements(
        coalesce(chunk.value -> 'document_metadata_assertions', '[]'::jsonb)
    ) as assertion(value)
    where jsonb_typeof(assertion.value) = 'object'
      and assertion.value ->> 'source' = 'llm_inferred'
      and coalesce((assertion.value ->> 'verified')::boolean, false) = false
    on conflict (document_id, document_version_id, assertion_hash) do nothing;

    insert into public.chunk_retrieval_projections (
        chunk_id, document_id, document_version_id, parent_id,
        projection_version, identity_text, structure_text, content_text,
        context_text, alias_text, embedding_text,
        search_vector_original, search_vector_folded, embedding,
        embedding_model, embedding_dimensions, normalization_version,
        source_content_hash, source_metadata_revision,
        embedding_metadata_revision, indexed_at, index_status
    )
    select
        chunks.id,
        selected_document.id,
        selected_version.id,
        chunks.parent_id,
        coalesce(nullif(item.value #>> '{projection,projection_version}', ''),
                 'retrieval-projection-v1'),
        coalesce(selected_document.document_number, ''),
        coalesce(item.value #>> '{projection,structure_text}', ''),
        chunks.content,
        concat_ws(' ', selected_document.title, chunks.section_path,
            chunks.contextual_content),
        coalesce(item.value #>> '{projection,alias_text}', ''),
        coalesce(nullif(item.value #>> '{projection,embedding_text}', ''), chunks.content),
        setweight(to_tsvector('simple', public.normalize_search_text(concat_ws(' ',
            selected_document.document_number,
            item.value #>> '{projection,structure_text}'
        ))), 'A')
        || setweight(to_tsvector('simple', public.normalize_search_text(chunks.content)), 'B')
        || setweight(to_tsvector('simple', public.normalize_search_text(concat_ws(' ',
            selected_document.title,
            chunks.section_path,
            chunks.contextual_content
        ))), 'C')
        || setweight(to_tsvector('simple', public.normalize_search_text(concat_ws(' ',
            selected_document.document_type, selected_document.domain,
            item.value #>> '{projection,alias_text}'
        ))), 'D'),
        setweight(to_tsvector('simple', public.fold_vietnamese_text(concat_ws(' ',
            selected_document.document_number,
            item.value #>> '{projection,structure_text}'
        ))), 'A')
        || setweight(to_tsvector('simple', public.fold_vietnamese_text(chunks.content)), 'B')
        || setweight(to_tsvector('simple', public.fold_vietnamese_text(concat_ws(' ',
            selected_document.title,
            chunks.section_path,
            chunks.contextual_content
        ))), 'C')
        || setweight(to_tsvector('simple', public.fold_vietnamese_text(concat_ws(' ',
            selected_document.document_type, selected_document.domain,
            item.value #>> '{projection,alias_text}'
        ))), 'D'),
        chunks.embedding,
        coalesce(nullif(item.value #>> '{projection,embedding_model}', ''),
                 selected_version.embedding_model, 'unknown'),
        coalesce(nullif(item.value #>> '{projection,embedding_dimensions}', '')::integer,
                 selected_version.embedding_dimensions, 1536),
        coalesce(nullif(item.value #>> '{projection,normalization_version}', ''), 'unknown'),
        coalesce(nullif(item.value #>> '{projection,source_content_hash}', ''),
                 chunks.content_hash, encode(public.knowledge_digest(
                     pg_catalog.convert_to(chunks.content, 'UTF8'),
                     'sha256'
                 ), 'hex')),
        selected_document.metadata_revision,
        selected_document.metadata_revision,
        now(),
        'READY'
    from jsonb_array_elements(p_chunks) as item(value)
    join public.knowledge_chunks as chunks
      on chunks.id = (item.value ->> 'id')::uuid
     and chunks.document_version_id = selected_version.id
    where jsonb_typeof(item.value -> 'projection') = 'object'
    on conflict (chunk_id) do update
    set parent_id = excluded.parent_id,
        projection_version = excluded.projection_version,
        identity_text = excluded.identity_text,
        structure_text = excluded.structure_text,
        content_text = excluded.content_text,
        context_text = excluded.context_text,
        alias_text = excluded.alias_text,
        embedding_text = excluded.embedding_text,
        search_vector_original = excluded.search_vector_original,
        search_vector_folded = excluded.search_vector_folded,
        embedding = excluded.embedding,
        embedding_model = excluded.embedding_model,
        embedding_dimensions = excluded.embedding_dimensions,
        normalization_version = excluded.normalization_version,
        source_content_hash = excluded.source_content_hash,
        source_metadata_revision = excluded.source_metadata_revision,
        embedding_metadata_revision = excluded.embedding_metadata_revision,
        indexed_at = excluded.indexed_at,
        index_status = excluded.index_status;

    update public.retrieval_projection_refresh_queue
    set processed_at = now(), last_error = null
    where document_id = selected_document.id
      and requested_metadata_revision <= selected_document.metadata_revision;
    return completed_job;
end;
$$;

revoke all on function public.complete_processing_job_v2(uuid, text, uuid, jsonb)
from public, anon, authenticated;
grant execute on function public.complete_processing_job_v2(uuid, text, uuid, jsonb)
to service_role;

create or replace function public.search_enterprise_retrieval_projection(
    p_query text,
    p_limit integer default 20,
    p_filters jsonb default '{}'::jsonb
)
returns table (
    chunk_id uuid, document_id uuid, document_version_id uuid, title text,
    chunk_index integer, content text, page_start integer, page_end integer,
    section_path text, metadata jsonb, score double precision
)
language plpgsql stable security definer set search_path = ''
as $$
declare
    actor uuid := auth.uid();
    original_query tsquery;
    folded_query tsquery;
begin
    if actor is null or not public.has_functional_permission(actor, 'ASK_KNOWLEDGE') then
        raise exception 'Knowledge search is not permitted' using errcode = '42501';
    end if;
    if p_query is null or btrim(p_query) = '' then return; end if;
    if p_filters is null or jsonb_typeof(p_filters) <> 'object' then
        raise exception 'Filters must be a JSON object' using errcode = '22023';
    end if;
    if exists (
        select 1 from jsonb_object_keys(p_filters) as filter_key(value)
        where filter_key.value not in (
            'document_id', 'document_type', 'category', 'domain',
            'department_code', 'project_code', 'year', 'effective_at'
        )
    ) then
        raise exception 'Unsupported canonical metadata filter' using errcode = '22023';
    end if;
    original_query := websearch_to_tsquery('simple', public.normalize_search_text(p_query));
    folded_query := websearch_to_tsquery('simple', public.fold_vietnamese_text(p_query));
    if numnode(original_query) = 0 and numnode(folded_query) = 0 then return; end if;
    return query
    select chunks.id, documents.id, versions.id, documents.title,
        chunks.chunk_index, chunks.content, chunks.page_start, chunks.page_end,
        chunks.section_path,
        chunks.metadata || jsonb_build_object(
            'parent_id', chunks.parent_id,
            'section_title', chunks.section_title,
            'content_kind', chunks.content_kind,
            'projection_version', projections.projection_version,
            'metadata_revision', projections.source_metadata_revision,
            'embedding_metadata_stale',
                projections.embedding_metadata_revision <> documents.metadata_revision
        ),
        (
            0.80 * ts_rank_cd(projections.search_vector_original, original_query, 32)
            + 0.20 * ts_rank_cd(projections.search_vector_folded, folded_query, 32)
        )::double precision
    from public.chunk_retrieval_projections as projections
    join public.knowledge_chunks as chunks on chunks.id = projections.chunk_id
    join public.document_versions as versions
      on versions.id = chunks.document_version_id
     and versions.document_id = chunks.document_id
    join public.knowledge_documents as documents
      on documents.id = versions.document_id
     and documents.current_version_id = versions.id
    where documents.status = 'PUBLISHED'
      and documents.deleted_at is null
      and versions.status = 'ACTIVE'
      and projections.index_status = 'READY'
      and public.has_document_permission(actor, documents.id, 'READ')
      and (
          projections.search_vector_original @@ original_query
          or projections.search_vector_folded @@ folded_query
      )
      and (not (p_filters ? 'document_id')
           or documents.id = (p_filters ->> 'document_id')::uuid)
      and (not (p_filters ? 'document_type')
           or documents.document_type = upper(p_filters ->> 'document_type'))
      and (not (p_filters ? 'department_code')
           or documents.department_code = upper(p_filters ->> 'department_code'))
      and (not (p_filters ? 'project_code')
           or documents.project_code = upper(p_filters ->> 'project_code'))
      and (not (p_filters ? 'category')
           or documents.category = p_filters ->> 'category')
      and (not (p_filters ? 'domain')
           or documents.domain = p_filters ->> 'domain')
      and (not (p_filters ? 'year')
           or extract(year from versions.effective_date)::integer =
              (p_filters ->> 'year')::integer)
      and (not (p_filters ? 'effective_at') or (
           versions.effective_date <= (p_filters ->> 'effective_at')::date
           and (
               versions.effective_to is null
               or versions.effective_to >= (p_filters ->> 'effective_at')::date
           )
      ))
    order by score desc, chunks.id
    limit greatest(1, least(coalesce(p_limit, 20), 200));
end;
$$;

create or replace function public.match_enterprise_retrieval_projection(
    p_query_embedding vector(1536),
    p_limit integer default 20,
    p_filters jsonb default '{}'::jsonb
)
returns table (
    chunk_id uuid, document_id uuid, document_version_id uuid, title text,
    chunk_index integer, content text, page_start integer, page_end integer,
    section_path text, metadata jsonb, score double precision
)
language plpgsql stable security definer set search_path = ''
as $$
declare actor uuid := auth.uid();
begin
    if actor is null or not public.has_functional_permission(actor, 'ASK_KNOWLEDGE') then
        raise exception 'Knowledge search is not permitted' using errcode = '42501';
    end if;
    if p_query_embedding is null then
        raise exception 'Query embedding is required' using errcode = '22023';
    end if;
    if p_filters is null or jsonb_typeof(p_filters) <> 'object' then
        raise exception 'Filters must be a JSON object' using errcode = '22023';
    end if;
    if exists (
        select 1 from jsonb_object_keys(p_filters) as filter_key(value)
        where filter_key.value not in (
            'document_id', 'document_type', 'category', 'domain',
            'department_code', 'project_code', 'year', 'effective_at'
        )
    ) then
        raise exception 'Unsupported canonical metadata filter' using errcode = '22023';
    end if;
    return query
    select chunks.id, documents.id, versions.id, documents.title,
        chunks.chunk_index, chunks.content, chunks.page_start, chunks.page_end,
        chunks.section_path,
        chunks.metadata || jsonb_build_object(
            'parent_id', chunks.parent_id,
            'section_title', chunks.section_title,
            'content_kind', chunks.content_kind,
            'projection_version', projections.projection_version,
            'metadata_revision', projections.source_metadata_revision,
            'embedding_metadata_stale',
                projections.embedding_metadata_revision <> documents.metadata_revision
        ),
        (1 - (projections.embedding OPERATOR(public.<=>) p_query_embedding))::double precision
    from public.chunk_retrieval_projections as projections
    join public.knowledge_chunks as chunks on chunks.id = projections.chunk_id
    join public.document_versions as versions
      on versions.id = chunks.document_version_id
     and versions.document_id = chunks.document_id
    join public.knowledge_documents as documents
      on documents.id = versions.document_id
     and documents.current_version_id = versions.id
    where documents.status = 'PUBLISHED'
      and documents.deleted_at is null
      and versions.status = 'ACTIVE'
      and projections.embedding is not null
      and projections.index_status = 'READY'
      and public.has_document_permission(actor, documents.id, 'READ')
      and (not (p_filters ? 'document_id')
           or documents.id = (p_filters ->> 'document_id')::uuid)
      and (not (p_filters ? 'document_type')
           or documents.document_type = upper(p_filters ->> 'document_type'))
      and (not (p_filters ? 'department_code')
           or documents.department_code = upper(p_filters ->> 'department_code'))
      and (not (p_filters ? 'project_code')
           or documents.project_code = upper(p_filters ->> 'project_code'))
      and (not (p_filters ? 'category')
           or documents.category = p_filters ->> 'category')
      and (not (p_filters ? 'domain')
           or documents.domain = p_filters ->> 'domain')
      and (not (p_filters ? 'year')
           or extract(year from versions.effective_date)::integer =
              (p_filters ->> 'year')::integer)
      and (not (p_filters ? 'effective_at') or (
           versions.effective_date <= (p_filters ->> 'effective_at')::date
           and (
               versions.effective_to is null
               or versions.effective_to >= (p_filters ->> 'effective_at')::date
           )
      ))
    order by projections.embedding OPERATOR(public.<=>) p_query_embedding
    limit greatest(1, least(coalesce(p_limit, 20), 200));
end;
$$;

create or replace function public.resolve_enterprise_document_number(p_document_number text)
returns table (document_id uuid, document_version_id uuid, title text)
language sql stable security definer set search_path = ''
as $$
    select documents.id, versions.id, documents.title
    from public.knowledge_documents as documents
    join public.document_versions as versions
      on versions.id = documents.current_version_id
     and versions.document_id = documents.id
    where auth.uid() is not null
      and public.has_functional_permission(auth.uid(), 'ASK_KNOWLEDGE')
      and documents.status = 'PUBLISHED'
      and documents.deleted_at is null
      and versions.status = 'ACTIVE'
      and documents.document_number_normalized =
          public.normalize_document_number(p_document_number)
      and public.has_document_permission(auth.uid(), documents.id, 'READ')
    order by documents.id;
$$;

create or replace function public.expand_enterprise_chunk_context(
    p_chunk_ids uuid[],
    p_sibling_window integer default 1,
    p_limit integer default 30
)
returns table (
    chunk_id uuid, document_id uuid, document_version_id uuid, title text,
    chunk_index integer, content text, page_start integer, page_end integer,
    section_path text, metadata jsonb, score double precision
)
language plpgsql stable security definer set search_path = ''
as $$
declare actor uuid := auth.uid();
begin
    if actor is null or not public.has_functional_permission(actor, 'ASK_KNOWLEDGE') then
        raise exception 'Knowledge search is not permitted' using errcode = '42501';
    end if;
    if p_chunk_ids is null or cardinality(p_chunk_ids) = 0 then return; end if;
    return query
    with matched as (
        select chunks.id, chunks.parent_id, chunks.parent_chunk_index, chunks.chunk_index,
               chunks.document_id, chunks.document_version_id
        from public.knowledge_chunks as chunks
        where chunks.id = any(p_chunk_ids)
    ), expanded as (
        select distinct on (siblings.id)
            siblings.id,
            matched.id as matched_id,
            case when siblings.id = matched.id then 1.0 else 0.5 end as expansion_score
        from matched
        join public.knowledge_chunks as siblings
          on siblings.document_id = matched.document_id
         and siblings.document_version_id = matched.document_version_id
         and (
             siblings.id = matched.id
             or (
                 siblings.parent_id = matched.parent_id
                 and matched.parent_id is not null
                 and abs(coalesce(siblings.parent_chunk_index, siblings.chunk_index)
                       - coalesce(matched.parent_chunk_index, matched.chunk_index))
                     <= greatest(0, least(coalesce(p_sibling_window, 1), 3))
             )
         )
        order by siblings.id, expansion_score desc
    )
    select chunks.id, documents.id, versions.id, documents.title,
        chunks.chunk_index, chunks.content, chunks.page_start, chunks.page_end,
        chunks.section_path,
        chunks.metadata || jsonb_build_object(
            'parent_id', chunks.parent_id,
            'parent_heading', parents.heading,
            'parent_summary', parents.content_summary,
            'expanded_from_chunk_id', expanded.matched_id,
            'expansion_kind', case when chunks.id = expanded.matched_id
                                   then 'matched' else 'sibling' end
        ),
        expanded.expansion_score::double precision
    from expanded
    join public.knowledge_chunks as chunks on chunks.id = expanded.id
    left join public.knowledge_parent_chunks as parents on parents.id = chunks.parent_id
    join public.document_versions as versions
      on versions.id = chunks.document_version_id
     and versions.document_id = chunks.document_id
    join public.knowledge_documents as documents
      on documents.id = versions.document_id
     and documents.current_version_id = versions.id
    where documents.status = 'PUBLISHED'
      and documents.deleted_at is null
      and versions.status = 'ACTIVE'
      and public.has_document_permission(actor, documents.id, 'READ')
    order by expanded.expansion_score desc, chunks.chunk_index, chunks.id
    limit greatest(1, least(coalesce(p_limit, 30), 100));
end;
$$;

create or replace function public.review_document_metadata_assertion(
    p_assertion_id uuid,
    p_decision text,
    p_rejection_reason text default null
)
returns public.document_metadata_assertions
language plpgsql
security definer
set search_path = ''
as $$
declare
    actor uuid := auth.uid();
    decision text := upper(btrim(coalesce(p_decision, '')));
    selected_assertion public.document_metadata_assertions;
begin
    if actor is null
       or not public.has_functional_permission(actor, 'REVIEW_DOCUMENT') then
        raise exception 'Document metadata review is not permitted'
            using errcode = '42501';
    end if;
    if decision not in ('VERIFIED', 'REJECTED') then
        raise exception 'Decision must be VERIFIED or REJECTED'
            using errcode = '22023';
    end if;

    select * into selected_assertion
    from public.document_metadata_assertions
    where id = p_assertion_id
    for update;
    if selected_assertion.id is null then
        raise exception 'Metadata assertion not found' using errcode = 'P0002';
    end if;
    if not (
        public.has_document_permission(actor, selected_assertion.document_id, 'REVIEW')
        or public.has_document_permission(actor, selected_assertion.document_id, 'MANAGE')
    ) then
        raise exception 'Document metadata review is not permitted'
            using errcode = '42501';
    end if;
    if selected_assertion.verification_status <> 'UNVERIFIED' then
        raise exception 'Metadata assertion has already been reviewed'
            using errcode = '40001';
    end if;
    if decision = 'REJECTED' and nullif(btrim(p_rejection_reason), '') is null then
        raise exception 'A rejection reason is required' using errcode = '22023';
    end if;

    if decision = 'VERIFIED' then
        if selected_assertion.field_name in (
            'document_number', 'document_type', 'category', 'domain',
            'project_code', 'department_code'
        ) then
            update public.knowledge_documents
            set document_number = case when selected_assertion.field_name = 'document_number'
                    then selected_assertion.value else document_number end,
                document_type = case when selected_assertion.field_name = 'document_type'
                    then upper(selected_assertion.normalized_value) else document_type end,
                category = case when selected_assertion.field_name = 'category'
                    then selected_assertion.normalized_value else category end,
                domain = case when selected_assertion.field_name = 'domain'
                    then selected_assertion.normalized_value else domain end,
                project_code = case when selected_assertion.field_name = 'project_code'
                    then upper(selected_assertion.normalized_value) else project_code end,
                department_code = case when selected_assertion.field_name = 'department_code'
                    then upper(selected_assertion.normalized_value) else department_code end,
                updated_at = now()
            where id = selected_assertion.document_id;
        elsif selected_assertion.field_name in ('effective_from', 'effective_to') then
            if selected_assertion.document_version_id is null then
                raise exception 'Version-bound metadata assertion is required'
                    using errcode = '23514';
            end if;
            update public.document_versions
            set effective_date = case
                    when selected_assertion.field_name = 'effective_from'
                    then selected_assertion.normalized_value::date else effective_date end,
                effective_to = case
                    when selected_assertion.field_name = 'effective_to'
                    then selected_assertion.normalized_value::date else effective_to end,
                metadata_revision = metadata_revision + 1
            where id = selected_assertion.document_version_id
              and document_id = selected_assertion.document_id;
        else
            raise exception 'Unsupported canonical metadata field'
                using errcode = '22023';
        end if;
    end if;

    update public.document_metadata_assertions
    set verification_status = decision,
        verified_by = actor,
        verified_at = now(),
        rejection_reason = case when decision = 'REJECTED'
            then btrim(p_rejection_reason) else null end
    where id = selected_assertion.id
    returning * into selected_assertion;

    perform public.write_enterprise_audit(
        'DOCUMENT_METADATA_ASSERTION_' || decision,
        'document_metadata_assertion',
        selected_assertion.id,
        jsonb_build_object('verification_status', 'UNVERIFIED'),
        to_jsonb(selected_assertion),
        p_rejection_reason
    );
    return selected_assertion;
end;
$$;

revoke all on function public.search_enterprise_retrieval_projection(text, integer, jsonb)
from public, anon;
revoke all on function public.match_enterprise_retrieval_projection(vector, integer, jsonb)
from public, anon;
revoke all on function public.resolve_enterprise_document_number(text)
from public, anon;
revoke all on function public.expand_enterprise_chunk_context(uuid[], integer, integer)
from public, anon;
revoke all on function public.review_document_metadata_assertion(uuid, text, text)
from public, anon;
grant execute on function public.search_enterprise_retrieval_projection(text, integer, jsonb)
to authenticated, service_role;
grant execute on function public.match_enterprise_retrieval_projection(vector, integer, jsonb)
to authenticated, service_role;
grant execute on function public.resolve_enterprise_document_number(text)
to authenticated, service_role;
grant execute on function public.expand_enterprise_chunk_context(uuid[], integer, integer)
to authenticated, service_role;
grant execute on function public.review_document_metadata_assertion(uuid, text, text)
to authenticated, service_role;

alter table public.knowledge_parent_chunks enable row level security;
alter table public.knowledge_parent_chunks force row level security;
alter table public.document_metadata_assertions enable row level security;
alter table public.document_metadata_assertions force row level security;
alter table public.chunk_retrieval_projections enable row level security;
alter table public.chunk_retrieval_projections force row level security;
alter table public.retrieval_projection_refresh_queue enable row level security;
alter table public.retrieval_projection_refresh_queue force row level security;

revoke all on table public.document_metadata_assertions from anon, authenticated;
grant select on table public.document_metadata_assertions to authenticated;

create policy knowledge_parent_chunks_select_access
on public.knowledge_parent_chunks for select to authenticated
using (public.is_enterprise_document_retrievable(
    (select auth.uid()), document_id, document_version_id
));
create policy chunk_retrieval_projections_select_access
on public.chunk_retrieval_projections for select to authenticated
using (public.is_enterprise_document_retrievable(
    (select auth.uid()), document_id, document_version_id
));
create policy document_metadata_assertions_select_manager
on public.document_metadata_assertions for select to authenticated
using (
    public.has_document_permission((select auth.uid()), document_id, 'MANAGE')
    or public.has_document_permission((select auth.uid()), document_id, 'REVIEW')
);

comment on table public.document_metadata_assertions is
    'Append-only metadata candidates with source, confidence and exact evidence. LLM rows stay UNVERIFIED until explicit review.';
comment on table public.chunk_retrieval_projections is
    'Rebuildable read model; never authoritative for ACL, lifecycle or business metadata.';
comment on function public.search_enterprise_retrieval_projection(text, integer, jsonb) is
    'PostgreSQL FTS using ts_rank_cd, not BM25. ACL/current lifecycle predicates are authoritative joins.';

-- Persist temporal-series relation candidates emitted by detector v4.
-- Run after 25_canonical_metadata_parent_projection.sql.

alter table public.document_relations
    drop constraint if exists document_relations_type;

alter table public.document_relations
    add constraint document_relations_type
        check (
            relation_type in (
                'exact_content',
                'near_duplicate',
                'version_candidate',
                'version',
                'conflict_candidate',
                'conflict',
                'related',
                'distinct',
                'technical_duplicate',
                'template_variant',
                'temporal_series'
            )
        );

-- Keep the fenced, audited completion implementation from migration 09 and
-- extend only its relation allowlist. Existing reviewed relations are not
-- rewritten: they require a deliberate re-ingestion/re-detection workflow.
do $$
declare
    completion_signature regprocedure := (
        'public.complete_ingestion_job('
        'uuid,text,uuid,text,integer,jsonb,text,text,text,jsonb,jsonb)'
    )::regprocedure;
    function_definition text;
    patched_definition text;
begin
    select pg_get_functiondef(completion_signature)
    into function_definition;

    if function_definition like '%''temporal_series''%' then
        return;
    end if;

    patched_definition := regexp_replace(
        function_definition,
        '(''template_variant''[[:space:]]*\))',
        E'''template_variant'',\n          ''temporal_series''\n      )',
        'g'
    );

    if patched_definition = function_definition then
        raise exception 'Could not extend complete_ingestion_job temporal relation whitelist';
    end if;

    execute patched_definition;
end;
$$;

comment on constraint document_relations_type on public.document_relations is
    'Supported persisted relation taxonomy, including historical temporal series.';

-- Repair migration 25 on databases where complete_processing_job_v2 was
-- installed with an unqualified pgcrypto.digest call. Run after
-- 26_temporal_scope_series.sql.

do $migration$
declare
    target_function regprocedure := pg_catalog.to_regprocedure(
        'public.complete_processing_job_v2(uuid,text,uuid,jsonb)'
    );
    function_definition text;
    broken_call constant text :=
        'digest(chunks.content, ''sha256'')';
    fixed_call constant text :=
        'public.knowledge_digest(pg_catalog.convert_to(chunks.content, ''UTF8''), ''sha256'')';
begin
    if target_function is null then
        raise exception 'complete_processing_job_v2 is required before migration 27'
            using errcode = '55000';
    end if;

    function_definition := pg_catalog.pg_get_functiondef(target_function);

    -- Fresh databases already contain the corrected migration-25 body.
    if pg_catalog.strpos(function_definition, fixed_call) > 0 then
        return;
    end if;
    if pg_catalog.strpos(function_definition, broken_call) = 0 then
        raise exception 'Unexpected complete_processing_job_v2 definition; refusing blind rewrite'
            using errcode = '55000';
    end if;

    function_definition := pg_catalog.replace(
        function_definition,
        broken_call,
        fixed_call
    );
    execute function_definition;
end;
$migration$;

revoke all on function public.complete_processing_job_v2(uuid, text, uuid, jsonb)
from public, anon, authenticated;
grant execute on function public.complete_processing_job_v2(uuid, text, uuid, jsonb)
to service_role;

-- Guided publication: collapse approval and publication into one safe action
-- while preserving both permission checks and the existing audit trail. Run
-- after 27_fix_complete_processing_job_v2_digest.sql.

create or replace function public.approve_and_publish_document_version(
    p_version_id uuid,
    p_note text default null
)
returns public.document_versions
language plpgsql
security definer
set search_path = ''
as $$
declare
    selected_version public.document_versions;
begin
    select * into selected_version
    from public.document_versions
    where id = p_version_id;
    if not found then
        raise exception 'Document version not found' using errcode = 'P0002';
    end if;

    -- A separately assigned reviewer may already have approved this exact
    -- processing result. Only create an approval when one is still required.
    if not exists (
        select 1
        from public.document_reviews as reviews
        where reviews.document_version_id = p_version_id
          and reviews.decision = 'APPROVE'
          and reviews.id = (
              select latest_review.id
              from public.document_reviews as latest_review
              where latest_review.document_version_id = p_version_id
              order by latest_review.reviewed_at desc, latest_review.id desc
              limit 1
          )
          and reviews.reviewed_at >= (
              select max(jobs.completed_at)
              from public.processing_jobs as jobs
              where jobs.document_version_id = p_version_id
                and jobs.status = 'SUCCEEDED'
          )
    ) then
        perform public.review_document_version(
            p_version_id,
            'APPROVE',
            coalesce(
                nullif(btrim(p_note), ''),
                'Approved through guided publication'
            ),
            null
        );
    end if;

    -- Nested function calls share this transaction. A publication failure
    -- therefore rolls back an approval created above.
    return public.publish_document_version(p_version_id);
end;
$$;

revoke all on function public.approve_and_publish_document_version(uuid, text)
from public, anon;
grant execute on function public.approve_and_publish_document_version(uuid, text)
to authenticated;

comment on function public.approve_and_publish_document_version(uuid, text) is
    'One guided action that reuses atomic review and publish guards; existing fresh approvals are preserved.';

-- Allow an exact source to be uploaded again after every document that uses
-- that checksum has been archived. Active/draft duplicates remain blocked.
-- Run after 28_guided_document_publish.sql.

do $migration$
declare
    target_function regprocedure := pg_catalog.to_regprocedure(
        'public.create_enterprise_document_upload(uuid,text,text,text,text,bigint,text,text,text,text,text,jsonb,text,date)'
    );
    function_definition text;
    broken_fragment constant text :=
        'where source_files.sha256 = normalized_sha';
    fixed_fragment constant text :=
        'join public.knowledge_documents as registered_documents
          on registered_documents.id = document_versions.document_id
        where source_files.sha256 = normalized_sha
          and registered_documents.status <> ''ARCHIVED''';
begin
    if target_function is null then
        raise exception 'create_enterprise_document_upload is required before migration 29'
            using errcode = '55000';
    end if;

    function_definition := pg_catalog.pg_get_functiondef(target_function);

    -- Fresh databases already contain the corrected migration-23 body.
    if pg_catalog.strpos(
        function_definition,
        'registered_documents.status <> ''ARCHIVED'''
    ) > 0 then
        return;
    end if;
    if pg_catalog.strpos(function_definition, broken_fragment) = 0 then
        raise exception 'Unexpected create_enterprise_document_upload definition; refusing blind rewrite'
            using errcode = '55000';
    end if;

    function_definition := pg_catalog.replace(
        function_definition,
        broken_fragment,
        fixed_fragment
    );
    execute function_definition;
end;
$migration$;

revoke all on function public.create_enterprise_document_upload(
    uuid, text, text, text, text, bigint, text, text,
    text, text, text, jsonb, text, date
) from public, anon;
grant execute on function public.create_enterprise_document_upload(
    uuid, text, text, text, text, bigint, text, text,
    text, text, text, jsonb, text, date
) to authenticated;

-- Automatically approve and publish an Enterprise document after all chunks
-- and retrieval projections have been persisted successfully. Run after
-- 29_allow_reupload_after_archive.sql.

create or replace function public.complete_processing_job_v3(
    p_job_id uuid,
    p_worker_id text,
    p_claim_token uuid,
    p_chunks jsonb default null
)
returns public.processing_jobs
language plpgsql
security definer
set search_path = ''
as $$
declare
    selected_job public.processing_jobs;
    selected_version public.document_versions;
    selected_document public.knowledge_documents;
    completed_job public.processing_jobs;
    publication_actor uuid;
    previous_claim_sub text := current_setting('request.jwt.claim.sub', true);
    previous_claim_role text := current_setting('request.jwt.claim.role', true);
    previous_claims text := current_setting('request.jwt.claims', true);
begin
    if auth.role() <> 'service_role' then
        raise exception 'Service role required' using errcode = '42501';
    end if;

    select * into selected_job
    from public.processing_jobs
    where id = p_job_id;
    if not found then
        raise exception 'Processing job not found' using errcode = 'P0002';
    end if;

    -- v2 writes chunks, parents, metadata assertions and retrieval projections
    -- in this transaction. Publication happens only after all those writes pass.
    completed_job := public.complete_processing_job_v2(
        p_job_id,
        p_worker_id,
        p_claim_token,
        p_chunks
    );

    select * into selected_version
    from public.document_versions
    where id = selected_job.document_version_id;
    select * into selected_document
    from public.knowledge_documents
    where id = selected_version.document_id;

    publication_actor := selected_job.requested_by;
    if completed_job.status <> 'SUCCEEDED'
       or selected_version.status <> 'READY_FOR_REVIEW'
       or selected_document.status = 'ARCHIVED'
       or publication_actor is null
       or not public.has_functional_permission(
           publication_actor, 'REVIEW_DOCUMENT'
       )
       or not public.has_functional_permission(
           publication_actor, 'PUBLISH_DOCUMENT'
       )
       or not public.has_document_permission(
           publication_actor, selected_document.id, 'REVIEW'
       )
       or not public.has_document_permission(
           publication_actor, selected_document.id, 'PUBLISH'
       ) then
        return completed_job;
    end if;

    -- Reuse the authenticated review/publication guards as the user who
    -- requested the processing job. This preserves actor attribution and the
    -- existing immutable audit trail instead of introducing a bypass path.
    perform set_config('request.jwt.claim.sub', publication_actor::text, true);
    perform set_config('request.jwt.claim.role', 'authenticated', true);
    perform set_config(
        'request.jwt.claims',
        jsonb_build_object(
            'sub', publication_actor,
            'role', 'authenticated'
        )::text,
        true
    );

    perform public.approve_and_publish_document_version(
        selected_version.id,
        'Tự động duyệt và đưa vào chatbot sau khi xử lý thành công'
    );

    perform set_config(
        'request.jwt.claim.sub', coalesce(previous_claim_sub, ''), true
    );
    perform set_config(
        'request.jwt.claim.role', coalesce(previous_claim_role, ''), true
    );
    perform set_config(
        'request.jwt.claims', coalesce(previous_claims, ''), true
    );
    return completed_job;
end;
$$;

revoke all on function public.complete_processing_job_v3(
    uuid, text, uuid, jsonb
) from public, anon, authenticated;
grant execute on function public.complete_processing_job_v3(
    uuid, text, uuid, jsonb
) to service_role;

comment on function public.complete_processing_job_v3(uuid, text, uuid, jsonb) is
    'Completes ingestion projections, then automatically approves and publishes when the requesting actor retains review and publish permission.';

-- Retrieval reliability hardening. Run after
-- 30_auto_publish_processed_documents.sql.
--
-- This migration is deliberately forward-only:
--   * document metadata edits synchronously refresh the lexical projection;
--   * natural-language sparse search has a bounded OR-recall path after
--     removing common Vietnamese/English filler terms;
--   * published INTERNAL/PUBLIC knowledge receives explicit role-subject READ
--     ACLs (authenticated enterprise roles only, never anon/public grants);
--   * authorized users can inspect why a document is or is not searchable.

-- -------------------------------------------------------------------------
-- 1. Make projection revision changes transactional and repair old drift.
-- -------------------------------------------------------------------------

-- PostgreSQL column-specific UPDATE triggers fire when the column is named in
-- the UPDATE statement, not when a BEFORE trigger changes that column.  The
-- old lexical trigger was `AFTER UPDATE OF metadata_revision`, while
-- prepare_knowledge_document_metadata() normally increments the revision from
-- an UPDATE of title/domain/etc.  Merge queueing and lexical refresh into the
-- existing all-column AFTER trigger so the NEW/OLD revision comparison is the
-- single source of truth.
create or replace function public.queue_retrieval_projection_refresh()
returns trigger
language plpgsql
security definer
set search_path = ''
as $$
declare
    expected_current_chunks bigint := 0;
    refreshed_current_chunks bigint := 0;
begin
    if tg_op = 'INSERT'
       or new.metadata_revision is distinct from old.metadata_revision then
        insert into public.retrieval_projection_refresh_queue (
            document_id,
            requested_metadata_revision,
            requested_at,
            processed_at,
            last_error
        ) values (
            new.id,
            new.metadata_revision,
            now(),
            null,
            null
        )
        on conflict (document_id) do update
        set requested_metadata_revision = excluded.requested_metadata_revision,
            requested_at = excluded.requested_at,
            processed_at = null,
            last_error = null;

        if tg_op = 'UPDATE' then
            update public.chunk_retrieval_projections as projections
            set identity_text = coalesce(new.document_number, ''),
                context_text = concat_ws(
                    ' ',
                    new.title,
                    chunks.section_path,
                    chunks.contextual_content
                ),
                search_vector_original =
                    setweight(to_tsvector(
                        'simple',
                        public.normalize_search_text(concat_ws(
                            ' ', new.document_number, projections.structure_text
                        ))
                    ), 'A')
                    || setweight(to_tsvector(
                        'simple',
                        public.normalize_search_text(projections.content_text)
                    ), 'B')
                    || setweight(to_tsvector(
                        'simple',
                        public.normalize_search_text(concat_ws(
                            ' ', new.title, chunks.section_path,
                            chunks.contextual_content
                        ))
                    ), 'C')
                    || setweight(to_tsvector(
                        'simple',
                        public.normalize_search_text(concat_ws(
                            ' ', new.document_type, new.domain,
                            projections.alias_text
                        ))
                    ), 'D'),
                search_vector_folded =
                    setweight(to_tsvector(
                        'simple',
                        public.fold_vietnamese_text(concat_ws(
                            ' ', new.document_number, projections.structure_text
                        ))
                    ), 'A')
                    || setweight(to_tsvector(
                        'simple',
                        public.fold_vietnamese_text(projections.content_text)
                    ), 'B')
                    || setweight(to_tsvector(
                        'simple',
                        public.fold_vietnamese_text(concat_ws(
                            ' ', new.title, chunks.section_path,
                            chunks.contextual_content
                        ))
                    ), 'C')
                    || setweight(to_tsvector(
                        'simple',
                        public.fold_vietnamese_text(concat_ws(
                            ' ', new.document_type, new.domain,
                            projections.alias_text
                        ))
                    ), 'D'),
                source_metadata_revision = new.metadata_revision,
                indexed_at = now()
            from public.knowledge_chunks as chunks
            where chunks.id = projections.chunk_id
              and projections.document_id = new.id;

            if new.current_version_id is not null then
                select count(*)
                into expected_current_chunks
                from public.knowledge_chunks as chunks
                where chunks.document_id = new.id
                  and chunks.document_version_id = new.current_version_id;

                select count(*)
                into refreshed_current_chunks
                from public.knowledge_chunks as chunks
                join public.chunk_retrieval_projections as projections
                  on projections.chunk_id = chunks.id
                 and projections.document_id = chunks.document_id
                 and projections.document_version_id = chunks.document_version_id
                where chunks.document_id = new.id
                  and chunks.document_version_id = new.current_version_id
                  and projections.source_metadata_revision = new.metadata_revision;

                if expected_current_chunks > 0
                   and refreshed_current_chunks = expected_current_chunks then
                    update public.retrieval_projection_refresh_queue
                    set processed_at = now(),
                        last_error = null
                    where document_id = new.id
                      and requested_metadata_revision <= new.metadata_revision;
                else
                    update public.retrieval_projection_refresh_queue
                    set processed_at = null,
                        last_error = format(
                            'Lexical projection coverage mismatch: refreshed %s of %s current chunks',
                            refreshed_current_chunks,
                            expected_current_chunks
                        )
                    where document_id = new.id;
                end if;
            end if;
        end if;
    end if;
    return new;
end;
$$;

revoke all on function public.queue_retrieval_projection_refresh()
from public, anon, authenticated;

-- The queue trigger from migration 25 already fires AFTER INSERT OR UPDATE and
-- calls the function above. Remove the ineffective column-specific duplicate.
drop trigger if exists knowledge_documents_refresh_lexical_projection
on public.knowledge_documents;

-- Rebuild every existing lexical read model from canonical document metadata
-- and immutable chunk text. Embedding revisions are intentionally not forged:
-- SQL cannot recompute a model embedding, and the diagnostic RPC reports that
-- drift separately as a warning.
update public.chunk_retrieval_projections as projections
set identity_text = coalesce(documents.document_number, ''),
    context_text = concat_ws(
        ' ', documents.title, chunks.section_path, chunks.contextual_content
    ),
    search_vector_original =
        setweight(to_tsvector(
            'simple',
            public.normalize_search_text(concat_ws(
                ' ', documents.document_number, projections.structure_text
            ))
        ), 'A')
        || setweight(to_tsvector(
            'simple', public.normalize_search_text(projections.content_text)
        ), 'B')
        || setweight(to_tsvector(
            'simple',
            public.normalize_search_text(concat_ws(
                ' ', documents.title, chunks.section_path,
                chunks.contextual_content
            ))
        ), 'C')
        || setweight(to_tsvector(
            'simple',
            public.normalize_search_text(concat_ws(
                ' ', documents.document_type, documents.domain,
                projections.alias_text
            ))
        ), 'D'),
    search_vector_folded =
        setweight(to_tsvector(
            'simple',
            public.fold_vietnamese_text(concat_ws(
                ' ', documents.document_number, projections.structure_text
            ))
        ), 'A')
        || setweight(to_tsvector(
            'simple', public.fold_vietnamese_text(projections.content_text)
        ), 'B')
        || setweight(to_tsvector(
            'simple',
            public.fold_vietnamese_text(concat_ws(
                ' ', documents.title, chunks.section_path,
                chunks.contextual_content
            ))
        ), 'C')
        || setweight(to_tsvector(
            'simple',
            public.fold_vietnamese_text(concat_ws(
                ' ', documents.document_type, documents.domain,
                projections.alias_text
            ))
        ), 'D'),
    source_metadata_revision = documents.metadata_revision,
    indexed_at = now()
from public.knowledge_chunks as chunks,
     public.knowledge_documents as documents
where chunks.id = projections.chunk_id
  and documents.id = projections.document_id
  and chunks.document_id = documents.id;

-- A current version with complete lexical coverage has consumed its queued
-- revision. Missing chunks/projections remain visibly pending and must be
-- reprocessed rather than being reported as healthy.
update public.retrieval_projection_refresh_queue as queue
set requested_metadata_revision = documents.metadata_revision,
    processed_at = now(),
    last_error = null
from public.knowledge_documents as documents
where documents.id = queue.document_id
  and documents.current_version_id is not null
  and exists (
      select 1
      from public.knowledge_chunks as chunks
      where chunks.document_id = documents.id
        and chunks.document_version_id = documents.current_version_id
  )
  and not exists (
      select 1
      from public.knowledge_chunks as chunks
      left join public.chunk_retrieval_projections as projections
        on projections.chunk_id = chunks.id
       and projections.document_id = chunks.document_id
       and projections.document_version_id = chunks.document_version_id
      where chunks.document_id = documents.id
        and chunks.document_version_id = documents.current_version_id
        and (
            projections.chunk_id is null
            or projections.source_metadata_revision <> documents.metadata_revision
        )
  );

insert into public.retrieval_projection_refresh_queue (
    document_id,
    requested_metadata_revision,
    requested_at,
    processed_at,
    last_error
)
select
    documents.id,
    documents.metadata_revision,
    now(),
    null,
    'Current version is missing a current lexical retrieval projection'
from public.knowledge_documents as documents
where documents.current_version_id is not null
  and (
      not exists (
          select 1
          from public.knowledge_chunks as chunks
          where chunks.document_id = documents.id
            and chunks.document_version_id = documents.current_version_id
      )
      or exists (
          select 1
          from public.knowledge_chunks as chunks
          left join public.chunk_retrieval_projections as projections
            on projections.chunk_id = chunks.id
           and projections.document_id = chunks.document_id
           and projections.document_version_id = chunks.document_version_id
          where chunks.document_id = documents.id
            and chunks.document_version_id = documents.current_version_id
            and (
                projections.chunk_id is null
                or projections.source_metadata_revision
                   <> documents.metadata_revision
            )
      )
  )
on conflict (document_id) do update
set requested_metadata_revision = excluded.requested_metadata_revision,
    requested_at = excluded.requested_at,
    processed_at = null,
    last_error = excluded.last_error;

comment on table public.retrieval_projection_refresh_queue is
    'Tracks transactional lexical projection refresh. processed_at means current lexical coverage; embedding revision drift remains explicit on chunk_retrieval_projections.';

-- -------------------------------------------------------------------------
-- 2. Natural-language sparse recall without an all-terms-mandatory failure.
-- -------------------------------------------------------------------------

create or replace function public.enterprise_recall_search_terms(p_value text)
returns text[]
language sql
stable
set search_path = ''
as $$
    with tokens as (
        select lower(token.value) as term, token.ordinality as position
        from regexp_split_to_table(
            public.normalize_search_text(coalesce(p_value, '')),
            '[^[:alnum:]_]+'
        ) with ordinality as token(value, ordinality)
    ), meaningful as (
        select term, min(position) as first_position
        from tokens
        where char_length(term) >= 2
          and term not in (
              -- Vietnamese, with and without diacritics.
              'các', 'cac', 'những', 'nhung', 'một', 'mot',
              'này', 'nay', 'kia', 'đó', 'do', 'được', 'duoc',
              'bị', 'bi', 'của', 'cua', 'cho', 'về', 've',
              'với', 'voi', 'và', 'va', 'hoặc', 'hoac',
              'hay', 'trong', 'ngoài', 'ngoai', 'trên', 'tren',
              'dưới', 'duoi', 'tại', 'tai', 'từ', 'tu',
              'đến', 'den', 'theo', 'là', 'la', 'hãy', 'hay',
              'vui', 'lòng', 'long', 'tôi', 'toi', 'bạn', 'ban',
              'biết', 'biet', 'gì', 'gi', 'nào', 'nao',
              -- English question/filler words. `an` is intentionally kept:
              -- it is the folded Vietnamese lexeme for "án" in "dự án".
              'the', 'is', 'are', 'was', 'were', 'be', 'been',
              'being', 'of', 'for', 'to', 'in', 'on', 'at', 'by',
              'with', 'and', 'or', 'what', 'which', 'who', 'where',
              'when', 'how', 'please', 'tell', 'me', 'about'
          )
        group by term
    ), bounded as (
        select term, first_position
        from meaningful
        order by first_position, term
        limit 32
    )
    select coalesce(array_agg(term order by first_position, term), '{}'::text[])
    from bounded;
$$;

create or replace function public.enterprise_recall_tsquery(p_value text)
returns tsquery
language sql
stable
set search_path = ''
as $$
    select to_tsquery(
        'simple',
        coalesce(
            nullif(array_to_string(
                public.enterprise_recall_search_terms(p_value),
                ' | '
            ), ''),
            ''
        )
    );
$$;

revoke all on function public.enterprise_recall_search_terms(text)
from public, anon, authenticated;
revoke all on function public.enterprise_recall_tsquery(text)
from public, anon, authenticated;

-- Effective state is a property of the query date, not immutable ingestion
-- metadata. Keep the interval calculation in the database so a document can
-- become CURRENT/EXPIRED without being re-uploaded or re-embedded.
create or replace function public.enterprise_effective_status(
    p_effective_from date,
    p_effective_to date,
    p_as_of date default current_date
)
returns text
language sql
stable
set search_path = ''
as $$
    select case
        when p_effective_from is null and p_effective_to is null then 'UNDATED'
        when p_effective_from is not null and p_effective_from > p_as_of
            then 'SCHEDULED'
        when p_effective_to is not null and p_effective_to < p_as_of
            then 'EXPIRED'
        else 'CURRENT'
    end;
$$;

revoke all on function public.enterprise_effective_status(date, date, date)
from public, anon, authenticated;

create or replace function public.search_enterprise_retrieval_projection(
    p_query text,
    p_limit integer default 20,
    p_filters jsonb default '{}'::jsonb
)
returns table (
    chunk_id uuid,
    document_id uuid,
    document_version_id uuid,
    title text,
    chunk_index integer,
    content text,
    page_start integer,
    page_end integer,
    section_path text,
    metadata jsonb,
    score double precision
)
language plpgsql
stable
security definer
set search_path = ''
as $$
declare
    actor uuid := auth.uid();
    exact_original_query tsquery;
    exact_folded_query tsquery;
    recall_original_query tsquery;
    recall_folded_query tsquery;
begin
    if actor is null
       or not public.has_functional_permission(actor, 'ASK_KNOWLEDGE') then
        raise exception 'Knowledge search is not permitted'
            using errcode = '42501';
    end if;
    if p_query is null or btrim(p_query) = '' then
        return;
    end if;
    if p_filters is null or jsonb_typeof(p_filters) <> 'object' then
        raise exception 'Filters must be a JSON object'
            using errcode = '22023';
    end if;
    if exists (
        select 1
        from jsonb_object_keys(p_filters) as filter_key(value)
        where filter_key.value not in (
            'document_id', 'document_type', 'category', 'domain',
            'department_code', 'project_code', 'year', 'effective_at',
            'effective_status'
        )
    ) then
        raise exception 'Unsupported canonical metadata filter'
            using errcode = '22023';
    end if;

    -- Preserve the precise all-term/web-search route, then add a bounded OR
    -- route for natural questions. Filler words cannot make every recall
    -- candidate fail, while chunks matching more meaningful terms rank higher.
    exact_original_query := websearch_to_tsquery(
        'simple', public.normalize_search_text(p_query)
    );
    exact_folded_query := websearch_to_tsquery(
        'simple', public.fold_vietnamese_text(p_query)
    );
    recall_original_query := public.enterprise_recall_tsquery(
        public.normalize_search_text(p_query)
    );
    recall_folded_query := public.enterprise_recall_tsquery(
        public.fold_vietnamese_text(p_query)
    );

    if numnode(exact_original_query) = 0
       and numnode(exact_folded_query) = 0
       and numnode(recall_original_query) = 0
       and numnode(recall_folded_query) = 0 then
        return;
    end if;

    return query
    select
        chunks.id,
        documents.id,
        versions.id,
        documents.title,
        chunks.chunk_index,
        chunks.content,
        chunks.page_start,
        chunks.page_end,
        chunks.section_path,
        chunks.metadata || jsonb_build_object(
            'parent_id', chunks.parent_id,
            'section_title', chunks.section_title,
            'content_kind', chunks.content_kind,
            'projection_version', projections.projection_version,
            'metadata_revision', projections.source_metadata_revision,
            'effective_status', public.enterprise_effective_status(
                versions.effective_date,
                versions.effective_to,
                current_date
            ),
            'embedding_metadata_stale',
                projections.embedding_metadata_revision
                <> documents.metadata_revision
        ),
        (
            0.55 * ts_rank_cd(
                projections.search_vector_original,
                exact_original_query,
                32
            )
            + 0.15 * ts_rank_cd(
                projections.search_vector_folded,
                exact_folded_query,
                32
            )
            + 0.20 * ts_rank_cd(
                projections.search_vector_original,
                recall_original_query,
                32
            )
            + 0.10 * ts_rank_cd(
                projections.search_vector_folded,
                recall_folded_query,
                32
            )
        )::double precision
    from public.chunk_retrieval_projections as projections
    join public.knowledge_chunks as chunks
      on chunks.id = projections.chunk_id
    join public.document_versions as versions
      on versions.id = chunks.document_version_id
     and versions.document_id = chunks.document_id
    join public.knowledge_documents as documents
      on documents.id = versions.document_id
     and documents.current_version_id = versions.id
    where documents.status = 'PUBLISHED'
      and documents.deleted_at is null
      and versions.status = 'ACTIVE'
      and projections.index_status = 'READY'
      and projections.source_metadata_revision = documents.metadata_revision
      and public.has_document_permission(actor, documents.id, 'READ')
      and (
          projections.search_vector_original @@ exact_original_query
          or projections.search_vector_folded @@ exact_folded_query
          or projections.search_vector_original @@ recall_original_query
          or projections.search_vector_folded @@ recall_folded_query
      )
      and (
          not (p_filters ? 'document_id')
          or documents.id = (p_filters ->> 'document_id')::uuid
      )
      and (
          not (p_filters ? 'document_type')
          or documents.document_type = upper(p_filters ->> 'document_type')
      )
      and (
          not (p_filters ? 'department_code')
          or documents.department_code = upper(p_filters ->> 'department_code')
      )
      and (
          not (p_filters ? 'project_code')
          or documents.project_code = upper(p_filters ->> 'project_code')
      )
      and (
          not (p_filters ? 'category')
          or documents.category = p_filters ->> 'category'
      )
      and (
          not (p_filters ? 'domain')
          or documents.domain = p_filters ->> 'domain'
      )
      and (
          not (p_filters ? 'year')
          or extract(year from versions.effective_date)::integer
             = (p_filters ->> 'year')::integer
      )
      and (
          not (p_filters ? 'effective_at')
          or (
              (
                  versions.effective_date is null
                  or versions.effective_date
                     <= (p_filters ->> 'effective_at')::date
              )
              and (
                  versions.effective_to is null
                  or versions.effective_to
                     >= (p_filters ->> 'effective_at')::date
              )
          )
      )
      and (
          not (p_filters ? 'effective_status')
          or public.enterprise_effective_status(
              versions.effective_date,
              versions.effective_to,
              current_date
          ) = upper(p_filters ->> 'effective_status')
      )
    order by score desc, chunks.id
    limit greatest(1, least(coalesce(p_limit, 20), 200));
end;
$$;

revoke all on function public.search_enterprise_retrieval_projection(
    text, integer, jsonb
) from public, anon;
grant execute on function public.search_enterprise_retrieval_projection(
    text, integer, jsonb
) to authenticated, service_role;

comment on function public.search_enterprise_retrieval_projection(
    text, integer, jsonb
) is
    'ACL/current-version-gated PostgreSQL FTS with precise websearch ranking plus bounded stopword-filtered OR recall for natural-language questions.';

-- Keep the dense route on exactly the same canonical filter contract. Dense
-- vectors remain usable after a metadata-only edit, but source metadata and
-- lifecycle/ACL joins must be current before a candidate can be returned.
create or replace function public.match_enterprise_retrieval_projection(
    p_query_embedding vector(1536),
    p_limit integer default 20,
    p_filters jsonb default '{}'::jsonb
)
returns table (
    chunk_id uuid,
    document_id uuid,
    document_version_id uuid,
    title text,
    chunk_index integer,
    content text,
    page_start integer,
    page_end integer,
    section_path text,
    metadata jsonb,
    score double precision
)
language plpgsql
stable
security definer
set search_path = ''
as $$
declare
    actor uuid := auth.uid();
begin
    if actor is null
       or not public.has_functional_permission(actor, 'ASK_KNOWLEDGE') then
        raise exception 'Knowledge search is not permitted'
            using errcode = '42501';
    end if;
    if p_query_embedding is null then
        raise exception 'Query embedding is required'
            using errcode = '22023';
    end if;
    if p_filters is null or jsonb_typeof(p_filters) <> 'object' then
        raise exception 'Filters must be a JSON object'
            using errcode = '22023';
    end if;
    if exists (
        select 1
        from jsonb_object_keys(p_filters) as filter_key(value)
        where filter_key.value not in (
            'document_id', 'document_type', 'category', 'domain',
            'department_code', 'project_code', 'year', 'effective_at',
            'effective_status'
        )
    ) then
        raise exception 'Unsupported canonical metadata filter'
            using errcode = '22023';
    end if;

    return query
    select
        chunks.id,
        documents.id,
        versions.id,
        documents.title,
        chunks.chunk_index,
        chunks.content,
        chunks.page_start,
        chunks.page_end,
        chunks.section_path,
        chunks.metadata || jsonb_build_object(
            'parent_id', chunks.parent_id,
            'section_title', chunks.section_title,
            'content_kind', chunks.content_kind,
            'projection_version', projections.projection_version,
            'metadata_revision', projections.source_metadata_revision,
            'effective_status', public.enterprise_effective_status(
                versions.effective_date,
                versions.effective_to,
                current_date
            ),
            'embedding_metadata_stale',
                projections.embedding_metadata_revision
                <> documents.metadata_revision
        ),
        (
            1 - (
                projections.embedding
                operator(public.<=>)
                p_query_embedding
            )
        )::double precision
    from public.chunk_retrieval_projections as projections
    join public.knowledge_chunks as chunks
      on chunks.id = projections.chunk_id
    join public.document_versions as versions
      on versions.id = chunks.document_version_id
     and versions.document_id = chunks.document_id
    join public.knowledge_documents as documents
      on documents.id = versions.document_id
     and documents.current_version_id = versions.id
    where documents.status = 'PUBLISHED'
      and documents.deleted_at is null
      and versions.status = 'ACTIVE'
      and projections.embedding is not null
      and projections.index_status = 'READY'
      and projections.source_metadata_revision = documents.metadata_revision
      and public.has_document_permission(actor, documents.id, 'READ')
      and (
          not (p_filters ? 'document_id')
          or documents.id = (p_filters ->> 'document_id')::uuid
      )
      and (
          not (p_filters ? 'document_type')
          or documents.document_type = upper(p_filters ->> 'document_type')
      )
      and (
          not (p_filters ? 'department_code')
          or documents.department_code = upper(p_filters ->> 'department_code')
      )
      and (
          not (p_filters ? 'project_code')
          or documents.project_code = upper(p_filters ->> 'project_code')
      )
      and (
          not (p_filters ? 'category')
          or documents.category = p_filters ->> 'category'
      )
      and (
          not (p_filters ? 'domain')
          or documents.domain = p_filters ->> 'domain'
      )
      and (
          not (p_filters ? 'year')
          or extract(year from versions.effective_date)::integer
             = (p_filters ->> 'year')::integer
      )
      and (
          not (p_filters ? 'effective_at')
          or (
              (
                  versions.effective_date is null
                  or versions.effective_date
                     <= (p_filters ->> 'effective_at')::date
              )
              and (
                  versions.effective_to is null
                  or versions.effective_to
                     >= (p_filters ->> 'effective_at')::date
              )
          )
      )
      and (
          not (p_filters ? 'effective_status')
          or public.enterprise_effective_status(
              versions.effective_date,
              versions.effective_to,
              current_date
          ) = upper(p_filters ->> 'effective_status')
      )
    order by projections.embedding operator(public.<=>) p_query_embedding
    limit greatest(1, least(coalesce(p_limit, 20), 200));
end;
$$;

revoke all on function public.match_enterprise_retrieval_projection(
    vector, integer, jsonb
) from public, anon;
grant execute on function public.match_enterprise_retrieval_projection(
    vector, integer, jsonb
) to authenticated, service_role;

-- -------------------------------------------------------------------------
-- 3. Organization-readable published knowledge through explicit role ACLs.
-- -------------------------------------------------------------------------

alter table public.document_permissions
    add column if not exists grant_source text not null default 'MANUAL';

alter table public.document_permissions
    drop constraint if exists document_permissions_grant_source;
alter table public.document_permissions
    add constraint document_permissions_grant_source check (
        grant_source in ('MANUAL', 'PUBLISHED_ROLE_DEFAULT')
    );

create index if not exists document_permissions_published_role_default_idx
    on public.document_permissions (document_id, subject_id)
    where status = 'ACTIVE'
      and permission = 'READ'
      and grant_source = 'PUBLISHED_ROLE_DEFAULT';

create or replace function public.sync_published_knowledge_reader_acl()
returns trigger
language plpgsql
security definer
set search_path = ''
as $$
declare
    grant_actor uuid := coalesce(auth.uid(), new.created_by);
begin
    if new.status = 'PUBLISHED'
       and new.deleted_at is null
       and new.visibility in ('INTERNAL', 'PUBLIC') then
        insert into public.document_permissions (
            document_id,
            subject_id,
            permission,
            status,
            granted_by,
            grant_source
        )
        select
            new.id,
            subjects.id,
            'READ',
            'ACTIVE',
            grant_actor,
            'PUBLISHED_ROLE_DEFAULT'
        from public.roles as roles
        join public.access_subjects as subjects
          on subjects.subject_type = 'ROLE'
         and subjects.role_id = roles.id
        join public.role_permissions as role_permissions
          on role_permissions.role_id = roles.id
        join public.functional_permissions as permissions
          on permissions.id = role_permissions.permission_id
         and permissions.code = 'ASK_KNOWLEDGE'
        where roles.status = 'ACTIVE'
        on conflict (
            document_id, subject_id, permission
        ) where status = 'ACTIVE'
        do nothing;
    else
        -- PRIVATE/RESTRICTED, archived, or soft-deleted knowledge remains
        -- explicit-ACL-only. Never revoke a manually assigned role grant.
        update public.document_permissions
        set status = 'REVOKED',
            revoked_by = grant_actor,
            revoked_at = now()
        where document_id = new.id
          and permission = 'READ'
          and status = 'ACTIVE'
          and grant_source = 'PUBLISHED_ROLE_DEFAULT';
    end if;
    return new;
end;
$$;

revoke all on function public.sync_published_knowledge_reader_acl()
from public, anon, authenticated;

drop trigger if exists knowledge_documents_sync_published_reader_acl
on public.knowledge_documents;
create trigger knowledge_documents_sync_published_reader_acl
after insert or update of status, visibility, deleted_at
on public.knowledge_documents
for each row execute function public.sync_published_knowledge_reader_acl();

-- Repair already-published documents. Existing manual READ rows win the
-- partial unique conflict and are never relabelled or later auto-revoked.
insert into public.document_permissions (
    document_id,
    subject_id,
    permission,
    status,
    granted_by,
    grant_source
)
select
    documents.id,
    subjects.id,
    'READ',
    'ACTIVE',
    documents.created_by,
    'PUBLISHED_ROLE_DEFAULT'
from public.knowledge_documents as documents
cross join public.roles as roles
join public.access_subjects as subjects
  on subjects.subject_type = 'ROLE'
 and subjects.role_id = roles.id
join public.role_permissions as role_permissions
  on role_permissions.role_id = roles.id
join public.functional_permissions as permissions
  on permissions.id = role_permissions.permission_id
 and permissions.code = 'ASK_KNOWLEDGE'
where documents.status = 'PUBLISHED'
  and documents.deleted_at is null
  and documents.visibility in ('INTERNAL', 'PUBLIC')
  and roles.status = 'ACTIVE'
on conflict (
    document_id, subject_id, permission
) where status = 'ACTIVE'
do nothing;

comment on column public.document_permissions.grant_source is
    'MANUAL grants are administrator-owned. PUBLISHED_ROLE_DEFAULT grants make INTERNAL/PUBLIC published knowledge readable by authenticated ASK_KNOWLEDGE roles and are safely revoked when visibility/lifecycle closes.';

-- -------------------------------------------------------------------------
-- 4. Read-only, authorization-aware searchability diagnostics.
-- -------------------------------------------------------------------------

create or replace function public.get_enterprise_document_searchability(
    p_document_id uuid default null
)
returns table (
    document_id uuid,
    title text,
    document_status text,
    visibility text,
    current_version_id uuid,
    version_status text,
    metadata_revision bigint,
    chunk_count bigint,
    ready_projection_count bigint,
    lexical_ready_projection_count bigint,
    lexical_stale_count bigint,
    embedding_stale_count bigint,
    refresh_requested_revision bigint,
    refresh_processed_at timestamptz,
    refresh_error text,
    searchable_for_actor boolean,
    fully_indexed boolean,
    blocking_reasons text[],
    warnings text[]
)
language plpgsql
stable
security definer
set search_path = ''
as $$
declare
    actor uuid := auth.uid();
    actor_can_ask boolean;
    actor_can_manage_access boolean;
begin
    if actor is null then
        raise exception 'Authentication required' using errcode = '42501';
    end if;

    actor_can_ask := public.has_functional_permission(
        actor, 'ASK_KNOWLEDGE'
    );
    actor_can_manage_access := public.has_functional_permission(
        actor, 'MANAGE_ACCESS_POLICY'
    );

    return query
    select
        documents.id,
        documents.title,
        documents.status,
        documents.visibility,
        documents.current_version_id,
        versions.status,
        documents.metadata_revision,
        coverage.chunk_count,
        coverage.ready_projection_count,
        coverage.lexical_ready_projection_count,
        coverage.lexical_stale_count,
        coverage.embedding_stale_count,
        queue.requested_metadata_revision,
        queue.processed_at,
        queue.last_error,
        (
            documents.status = 'PUBLISHED'
            and documents.deleted_at is null
            and versions.status = 'ACTIVE'
            and actor_can_ask
            and access.can_read
            and coverage.lexical_ready_projection_count > 0
        ),
        (
            coverage.chunk_count > 0
            and coverage.ready_projection_count = coverage.chunk_count
            and coverage.lexical_ready_projection_count = coverage.chunk_count
            and coverage.lexical_stale_count = 0
        ),
        array_remove(array[
            case when documents.status <> 'PUBLISHED'
                 then 'DOCUMENT_NOT_PUBLISHED' end,
            case when documents.deleted_at is not null
                 then 'DOCUMENT_DELETED' end,
            case when documents.current_version_id is null
                 then 'NO_CURRENT_VERSION' end,
            case when versions.status is distinct from 'ACTIVE'
                 then 'VERSION_NOT_ACTIVE' end,
            case when not actor_can_ask
                 then 'ASK_KNOWLEDGE_DENIED' end,
            case when not access.can_read
                 then 'READ_DENIED' end,
            case when coverage.chunk_count = 0
                 then 'NO_CHUNKS' end,
            case when coverage.ready_projection_count = 0
                 then 'NO_READY_PROJECTIONS' end,
            case when coverage.lexical_stale_count > 0
                 then 'LEXICAL_PROJECTION_STALE' end
        ], null)::text[],
        array_remove(array[
            case when coverage.embedding_stale_count > 0
                 then 'EMBEDDING_METADATA_STALE' end,
            case when queue.document_id is not null
                       and queue.processed_at is null
                 then 'PROJECTION_REFRESH_PENDING' end,
            case when queue.last_error is not null
                 then 'PROJECTION_REFRESH_ERROR' end
        ], null)::text[]
    from public.knowledge_documents as documents
    left join public.document_versions as versions
      on versions.id = documents.current_version_id
     and versions.document_id = documents.id
    left join public.retrieval_projection_refresh_queue as queue
      on queue.document_id = documents.id
    cross join lateral (
        select
            public.has_document_permission(
                actor, documents.id, 'READ'
            ) as can_read,
            public.has_document_permission(
                actor, documents.id, 'MANAGE'
            ) as can_manage
    ) as access
    cross join lateral (
        select
            count(chunks.id) as chunk_count,
            count(chunks.id) filter (
                where projections.index_status = 'READY'
            ) as ready_projection_count,
            count(chunks.id) filter (
                where projections.index_status = 'READY'
                  and projections.source_metadata_revision
                      = documents.metadata_revision
            ) as lexical_ready_projection_count,
            count(chunks.id) filter (
                where projections.chunk_id is null
                   or projections.source_metadata_revision
                      <> documents.metadata_revision
            ) as lexical_stale_count,
            count(chunks.id) filter (
                where projections.chunk_id is not null
                  and projections.embedding_metadata_revision
                      <> documents.metadata_revision
            ) as embedding_stale_count
        from public.knowledge_chunks as chunks
        left join public.chunk_retrieval_projections as projections
          on projections.chunk_id = chunks.id
         and projections.document_id = chunks.document_id
         and projections.document_version_id = chunks.document_version_id
        where chunks.document_id = documents.id
          and chunks.document_version_id = documents.current_version_id
    ) as coverage
    where (p_document_id is null or documents.id = p_document_id)
      and (
          access.can_read
          or access.can_manage
          or actor_can_manage_access
      )
    order by documents.updated_at desc, documents.id;
end;
$$;

revoke all on function public.get_enterprise_document_searchability(uuid)
from public, anon, service_role;
grant execute on function public.get_enterprise_document_searchability(uuid)
to authenticated;

comment on function public.get_enterprise_document_searchability(uuid) is
    'Read-only lifecycle/ACL/projection diagnostics for an authorized reader, document manager, or access-policy manager. Returns no chunk content and no hidden document to ordinary users.';

-- P1 high-recall chunk candidate generation. Run after
-- 31_retrieval_reliability_hardening.sql.
--
-- This is additive: the v1 RPC and its eight fixed expression indexes remain
-- available for legacy/shadow rollback. The v2 RPC unions exact identity,
-- multi-layout binary keys, and the existing PostgreSQL FTS index. Dense ANN
-- is fused by the worker after embeddings exist.

create or replace function public.knowledge_simhash_multi_keys(p_signature text)
returns text[]
language plpgsql
immutable
strict
set search_path = ''
as $$
declare
    decoded bytea;
    multipliers integer[] := array[1, 3, 5, 7, 11, 13, 17, 21];
    multiplier integer;
    band integer;
    bit_offset integer;
    byte_value integer;
    result text[] := array[]::text[];
begin
    if p_signature !~ '^[0-9a-f]{16}$' then
        raise exception 'SimHash signature must be 16 lowercase hexadecimal characters'
            using errcode = '22023';
    end if;
    decoded := decode(p_signature, 'hex');
    foreach multiplier in array multipliers loop
        for band in 0..7 loop
            byte_value := 0;
            for bit_offset in 0..7 loop
                byte_value := byte_value * 2 + get_bit(
                    decoded,
                    ((band * 8 + bit_offset) * multiplier) % 64
                );
            end loop;
            result := array_append(
                result,
                'm' || multiplier::text || ':b' || band::text || ':'
                    || lpad(to_hex(byte_value), 2, '0')
            );
        end loop;
    end loop;
    return result;
end;
$$;

revoke all on function public.knowledge_simhash_multi_keys(text)
    from public, anon, authenticated;
grant execute on function public.knowledge_simhash_multi_keys(text)
    to service_role;

alter table public.document_chunks
    add column if not exists candidate_binary_keys text[]
    generated always as (
        public.knowledge_simhash_multi_keys(loose_content_signature)
    ) stored;

create index if not exists document_chunks_candidate_binary_keys_idx
    on public.document_chunks using gin (candidate_binary_keys)
    where embedding is not null;

create or replace function public.find_chunk_candidates_v2(
    p_owner_id uuid,
    p_notebook_id uuid,
    p_document_id uuid,
    p_embedding_model text,
    p_probes jsonb,
    p_limit_per_probe integer default 50
)
returns table (
    source_chunk_index integer,
    target_chunk_id uuid,
    target_document_id uuid,
    target_chunk_index integer,
    canonical_text text,
    normalized_content_hash text,
    normalization_version text,
    loose_content_signature text,
    embedding_text_checksum text,
    embedding text,
    embedding_model text,
    lsh_band_matches integer,
    exact_rank integer,
    exact_score double precision,
    binary_rank integer,
    binary_score double precision,
    binary_key_matches integer,
    fts_rank integer,
    fts_score double precision
)
language plpgsql
stable
security definer
set search_path = ''
as $$
begin
    if auth.role() <> 'service_role' then
        raise exception 'Service role is required' using errcode = '42501';
    end if;
    if p_owner_id is null
       or p_notebook_id is null
       or p_document_id is null
       or p_embedding_model is null
       or char_length(btrim(p_embedding_model)) not between 1 and 200 then
        raise exception 'Invalid chunk candidate scope or embedding model'
            using errcode = '22023';
    end if;
    if p_limit_per_probe is null
       or p_limit_per_probe < 1
       or p_limit_per_probe > 50 then
        raise exception 'Chunk candidate limit must be between 1 and 50'
            using errcode = '22023';
    end if;
    if p_probes is null
       or jsonb_typeof(p_probes) <> 'array'
       or jsonb_array_length(p_probes) = 0
       or jsonb_array_length(p_probes) > 128 then
        raise exception 'Chunk probes must contain between 1 and 128 items'
            using errcode = '22023';
    end if;
    if exists (
        select 1
        from jsonb_array_elements(p_probes) as probe(value)
        where jsonb_typeof(probe.value) <> 'object'
           or probe.value ->> 'chunk_index' !~ '^[0-9]+$'
           or probe.value ->> 'normalized_content_hash' !~ '^[0-9a-f]{64}$'
           or char_length(btrim(probe.value ->> 'normalization_version'))
                not between 1 and 100
           or probe.value ->> 'loose_content_signature' !~ '^[0-9a-f]{16}$'
           or jsonb_typeof(probe.value -> 'include_fuzzy') <> 'boolean'
           or jsonb_typeof(probe.value -> 'binary_keys') <> 'array'
           or jsonb_array_length(probe.value -> 'binary_keys') > 64
           or jsonb_typeof(probe.value -> 'fts_terms') <> 'array'
           or jsonb_array_length(probe.value -> 'fts_terms') > 16
    ) then
        raise exception 'A chunk probe has an invalid v2 candidate payload'
            using errcode = '22023';
    end if;

    return query
    select
        (probe.value ->> 'chunk_index')::integer,
        fused.target_chunk_id,
        fused.target_document_id,
        fused.target_chunk_index,
        fused.canonical_text,
        fused.normalized_content_hash,
        fused.normalization_version,
        fused.loose_content_signature,
        fused.embedding_text_checksum,
        fused.embedding::text,
        fused.embedding_model,
        fused.lsh_band_matches,
        fused.exact_rank,
        fused.exact_score,
        fused.binary_rank,
        fused.binary_score,
        fused.binary_key_matches,
        fused.fts_rank,
        fused.fts_score
    from jsonb_array_elements(p_probes) as probe(value)
    cross join lateral (
        with base as (
            select
                chunks.id as target_chunk_id,
                chunks.document_id as target_document_id,
                chunks.chunk_index as target_chunk_index,
                coalesce(nullif(chunks.metadata ->> 'canonical_text', ''), chunks.content)
                    as canonical_text,
                chunks.normalized_content_hash,
                chunks.normalization_version,
                chunks.loose_content_signature,
                nullif(chunks.metadata ->> 'embedding_text_checksum', '')
                    as embedding_text_checksum,
                chunks.embedding,
                chunks.candidate_binary_keys,
                chunks.search_vector,
                latest_job.embedding_model,
                documents.created_at,
                coalesce((
                    select count(*)::integer
                    from unnest(chunks.candidate_binary_keys) as stored(key)
                    where stored.key in (
                        select jsonb_array_elements_text(probe.value -> 'binary_keys')
                    )
                ), 0) as binary_key_matches
            from public.document_chunks as chunks
            join public.documents as documents
              on documents.id = chunks.document_id
             and documents.owner_id = chunks.owner_id
             and documents.notebook_id = chunks.notebook_id
            join lateral (
                select jobs.embedding_model, jobs.embedding_dimensions
                from public.ingestion_jobs as jobs
                where jobs.document_id = chunks.document_id
                  and jobs.owner_id = chunks.owner_id
                  and jobs.notebook_id = chunks.notebook_id
                  and jobs.status = 'succeeded'
                  and jobs.completion_disposition is distinct from 'duplicate_suppressed'
                order by jobs.attempt_number desc, jobs.id desc
                limit 1
            ) as latest_job
              on public.vector_dims(chunks.embedding) = latest_job.embedding_dimensions
            where chunks.owner_id = p_owner_id
              and chunks.notebook_id = p_notebook_id
              and chunks.document_id <> p_document_id
              and chunks.normalization_version =
                    btrim(probe.value ->> 'normalization_version')
              and chunks.embedding is not null
              and documents.status = 'ready'
              and documents.is_active
              and documents.is_current
              and documents.canonical_document_id is null
              and documents.quality_status not in ('duplicate', 'superseded')
        ),
        fts_query as (
            select to_tsquery(
                'simple'::regconfig,
                string_agg(quote_literal(term.value), ' | ' order by term.ordinality)
            ) as value
            from jsonb_array_elements_text(probe.value -> 'fts_terms')
                with ordinality as term(value, ordinality)
        ),
        exact_hits as (
            select ranked.*
            from (
                select
                    base.*,
                    row_number() over (
                        order by base.created_at, base.target_chunk_index,
                            base.target_chunk_id
                    )::integer as channel_rank
                from base
                where base.normalized_content_hash =
                    probe.value ->> 'normalized_content_hash'
            ) as ranked
            where ranked.channel_rank <= p_limit_per_probe
        ),
        binary_hits as (
            select ranked.*
            from (
                select
                    base.*,
                    row_number() over (
                        order by base.binary_key_matches desc,
                            base.created_at,
                            base.target_chunk_index,
                            base.target_chunk_id
                    )::integer as channel_rank
                from base
                where (probe.value ->> 'include_fuzzy')::boolean
                  and base.candidate_binary_keys && array(
                      select jsonb_array_elements_text(probe.value -> 'binary_keys')
                  )
            ) as ranked
            where ranked.channel_rank <= p_limit_per_probe
        ),
        fts_hits as (
            select ranked.*
            from (
                select
                    base.*,
                    ts_rank_cd(base.search_vector, fts_query.value, 32)::double precision
                        as channel_score,
                    row_number() over (
                        order by ts_rank_cd(base.search_vector, fts_query.value, 32) desc,
                            base.target_chunk_id
                    )::integer as channel_rank
                from base
                cross join fts_query
                where (probe.value ->> 'include_fuzzy')::boolean
                  and fts_query.value is not null
                  and numnode(fts_query.value) > 0
                  and base.search_vector @@ fts_query.value
            ) as ranked
            where ranked.channel_rank <= p_limit_per_probe
        ),
        channel_rows as (
            select exact_hits.*, exact_hits.channel_rank as exact_rank,
                1.0::double precision as exact_score,
                null::integer as binary_rank, null::double precision as binary_score,
                null::integer as fts_rank, null::double precision as fts_score
            from exact_hits
            union all
            select binary_hits.*, null, null,
                binary_hits.channel_rank,
                (binary_hits.binary_key_matches::double precision / 64.0),
                null, null
            from binary_hits
            union all
            select fts_hits.target_chunk_id, fts_hits.target_document_id,
                fts_hits.target_chunk_index, fts_hits.canonical_text,
                fts_hits.normalized_content_hash, fts_hits.normalization_version,
                fts_hits.loose_content_signature, fts_hits.embedding_text_checksum,
                fts_hits.embedding, fts_hits.candidate_binary_keys,
                fts_hits.search_vector, fts_hits.embedding_model,
                fts_hits.created_at, fts_hits.binary_key_matches,
                fts_hits.channel_rank, null, null, null, null,
                fts_hits.channel_rank, fts_hits.channel_score
            from fts_hits
        )
        select
            channel_rows.target_chunk_id,
            channel_rows.target_document_id,
            channel_rows.target_chunk_index,
            channel_rows.canonical_text,
            channel_rows.normalized_content_hash,
            channel_rows.normalization_version,
            channel_rows.loose_content_signature,
            channel_rows.embedding_text_checksum,
            channel_rows.embedding::text as embedding,
            channel_rows.embedding_model,
            greatest(0, max(channel_rows.binary_key_matches))::integer as lsh_band_matches,
            min(channel_rows.exact_rank) as exact_rank,
            max(channel_rows.exact_score) as exact_score,
            min(channel_rows.binary_rank) as binary_rank,
            max(channel_rows.binary_score) as binary_score,
            greatest(0, max(channel_rows.binary_key_matches))::integer
                as binary_key_matches,
            min(channel_rows.fts_rank) as fts_rank,
            max(channel_rows.fts_score) as fts_score
        from channel_rows
        group by
            channel_rows.target_chunk_id,
            channel_rows.target_document_id,
            channel_rows.target_chunk_index,
            channel_rows.canonical_text,
            channel_rows.normalized_content_hash,
            channel_rows.normalization_version,
            channel_rows.loose_content_signature,
            channel_rows.embedding_text_checksum,
            channel_rows.embedding::text,
            channel_rows.embedding_model
        order by
            min(channel_rows.exact_rank) nulls last,
            (
                coalesce(1.0 / (60 + min(channel_rows.exact_rank)), 0.0)
                + coalesce(1.0 / (60 + min(channel_rows.binary_rank)), 0.0)
                + coalesce(1.0 / (60 + min(channel_rows.fts_rank)), 0.0)
            ) desc,
            channel_rows.target_chunk_id
    ) as fused;
end;
$$;

comment on function public.find_chunk_candidates_v2(
    uuid, uuid, uuid, text, jsonb, integer
) is
    'Service-role exact/binary/FTS chunk candidate union with per-channel evidence.';

revoke all on function public.find_chunk_candidates_v2(
    uuid, uuid, uuid, text, jsonb, integer
) from public, anon, authenticated;
grant execute on function public.find_chunk_candidates_v2(
    uuid, uuid, uuid, text, jsonb, integer
) to service_role;

-- P2 domain entity/business scope metadata is stored in the existing chunk JSONB.
-- The envelope is optional and versioned so pre-P2 chunks remain valid and are
-- deterministically re-resolved from canonical text/context at read time.

create index if not exists document_chunks_entity_scope_version_idx
    on public.document_chunks ((metadata #>> '{entity_scope,version}'))
    where metadata ? 'entity_scope';

comment on index public.document_chunks_entity_scope_version_idx is
    'Audits versioned P2 entity_scope envelopes without requiring a destructive backfill.';

create index if not exists knowledge_chunks_entity_scope_version_idx
    on public.knowledge_chunks ((metadata #>> '{entity_scope,version}'))
    where metadata ? 'entity_scope';

comment on index public.knowledge_chunks_entity_scope_version_idx is
    'Enterprise chunk index for optional versioned P2 entity_scope metadata.';
