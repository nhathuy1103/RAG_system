-- Minimal Supabase-owned objects required to compile RESET_AND_REBUILD.sql
-- against a plain pgvector PostgreSQL image. Production Supabase projects
-- already provide these schemas, roles, tables, and helper functions.
\set ON_ERROR_STOP on

create extension if not exists pgcrypto;
create extension if not exists vector;

do $$
begin
    if not exists (select 1 from pg_roles where rolname = 'anon') then
        create role anon;
    end if;
    if not exists (select 1 from pg_roles where rolname = 'authenticated') then
        create role authenticated;
    end if;
    if not exists (select 1 from pg_roles where rolname = 'service_role') then
        create role service_role;
    end if;
    if not exists (
        select 1 from pg_roles where rolname = 'supabase_auth_admin'
    ) then
        create role supabase_auth_admin;
    end if;
end
$$;

create schema if not exists auth;
create schema if not exists storage;

create table auth.users (
    instance_id uuid,
    id uuid primary key default gen_random_uuid(),
    aud text,
    role text,
    email text unique,
    encrypted_password text,
    email_confirmed_at timestamptz,
    recovery_sent_at timestamptz,
    last_sign_in_at timestamptz,
    raw_app_meta_data jsonb not null default '{}'::jsonb,
    raw_user_meta_data jsonb not null default '{}'::jsonb,
    created_at timestamptz not null default now(),
    updated_at timestamptz not null default now(),
    confirmation_token text,
    email_change text,
    email_change_token_new text,
    recovery_token text
);

create table auth.identities (
    id uuid primary key default gen_random_uuid(),
    user_id uuid not null references auth.users (id) on delete cascade,
    identity_data jsonb not null default '{}'::jsonb,
    provider text not null,
    provider_id text not null,
    last_sign_in_at timestamptz,
    created_at timestamptz not null default now(),
    updated_at timestamptz not null default now()
);

create table auth.audit_log_entries (
    id uuid primary key default gen_random_uuid(),
    payload jsonb not null default '{}'::jsonb,
    created_at timestamptz not null default now()
);

create or replace function auth.uid()
returns uuid
language sql
stable
as $$
    select nullif(
        current_setting('request.jwt.claim.sub', true),
        ''
    )::uuid
$$;

create or replace function auth.role()
returns text
language sql
stable
as $$
    select nullif(
        current_setting('request.jwt.claim.role', true),
        ''
    )
$$;

create table storage.buckets (
    id text primary key,
    name text not null,
    public boolean not null default false,
    file_size_limit bigint,
    allowed_mime_types text[]
);

create table storage.objects (
    id uuid primary key default gen_random_uuid(),
    bucket_id text not null references storage.buckets (id) on delete cascade,
    name text not null
);

create or replace function storage.foldername(name text)
returns text[]
language sql
immutable
as $$
    select string_to_array(name, '/')
$$;
