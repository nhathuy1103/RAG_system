-- Minimal pre-08 schema used to compile the migration in plain PostgreSQL.
-- Supabase-specific roles/auth helpers are represented by compatible stubs.

create extension if not exists pgcrypto;
create extension if not exists vector;

create role anon;
create role authenticated;
create role service_role;

create schema auth;

create table auth.users (
    id uuid primary key default gen_random_uuid()
);

create function auth.uid()
returns uuid
language sql
stable
as $$
    select nullif(
        current_setting('request.jwt.claim.sub', true),
        ''
    )::uuid
$$;

create function auth.role()
returns text
language sql
stable
as $$
    select nullif(
        current_setting('request.jwt.claim.role', true),
        ''
    )
$$;

create table public.notebooks (
    id uuid primary key default gen_random_uuid(),
    owner_id uuid not null references auth.users (id) on delete cascade,
    title text not null,
    is_active boolean not null default true,
    created_at timestamptz not null default now(),
    updated_at timestamptz not null default now(),
    unique (id, owner_id)
);

create table public.documents (
    id uuid primary key default gen_random_uuid(),
    owner_id uuid not null references auth.users (id) on delete cascade,
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
    foreign key (notebook_id, owner_id)
        references public.notebooks (id, owner_id) on delete cascade,
    unique (id, notebook_id, owner_id)
);

create table public.ingestion_jobs (
    id uuid primary key default gen_random_uuid(),
    owner_id uuid not null references auth.users (id) on delete cascade,
    notebook_id uuid not null,
    document_id uuid not null,
    attempt_number integer not null default 1,
    status text not null default 'pending',
    embedding_model text not null default 'test',
    embedding_dimensions integer not null default 32,
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
    constraint ingestion_jobs_claim
        check (
            (
                status = 'running'
                and claimed_by is not null
                and lease_expires_at is not null
            )
            or (
                status <> 'running'
                and claimed_by is null
                and lease_expires_at is null
            )
        )
);

create table public.document_chunks (
    id uuid primary key default gen_random_uuid(),
    owner_id uuid not null references auth.users (id) on delete cascade,
    notebook_id uuid not null,
    document_id uuid not null,
    chunk_index integer not null,
    content text not null,
    token_count integer not null,
    metadata jsonb not null default '{}'::jsonb,
    embedding vector(1536),
    created_at timestamptz not null default now(),
    foreign key (document_id, notebook_id, owner_id)
        references public.documents (id, notebook_id, owner_id)
        on delete cascade,
    unique (document_id, chunk_index)
);

create function public.claim_ingestion_job(text, integer)
returns void language sql as $$ select $$;

create function public.renew_ingestion_job_lease(uuid, text, integer)
returns boolean language sql as $$ select false $$;

create function public.complete_ingestion_job(uuid, text, text, integer, jsonb)
returns void language sql as $$ select $$;

create function public.fail_ingestion_job(uuid, text, text)
returns void language sql as $$ select $$;

create function public.soft_delete_document(uuid, uuid)
returns setof public.documents language sql as $$ select * from public.documents where false $$;
