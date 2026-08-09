-- Reproduces the mixed production state audited on 2026-07-31.
-- Run after knowledge_quality_migration_base.sql on disposable PostgreSQL only.

insert into auth.users (id)
values ('00000000-0000-0000-0000-000000000001');

insert into public.notebooks (id, owner_id, title)
values (
    '10000000-0000-0000-0000-000000000001',
    '00000000-0000-0000-0000-000000000001',
    'Partial repair fixture'
);

insert into public.documents (
    id,
    owner_id,
    notebook_id,
    original_filename,
    storage_object_path,
    mime_type,
    size_bytes,
    content_hash,
    status,
    created_at
)
select
    (
        '20000000-0000-0000-0000-'
        || lpad(document_number::text, 12, '0')
    )::uuid,
    '00000000-0000-0000-0000-000000000001'::uuid,
    '10000000-0000-0000-0000-000000000001'::uuid,
    format('document-%s.txt', document_number),
    format('fixture/document-%s.txt', document_number),
    'text/plain',
    100 + document_number,
    case
        when document_number in (1, 2) then repeat('a', 64)
        else lpad(to_hex(document_number), 64, '0')
    end,
    'ready',
    timestamptz '2026-07-31 00:00:00+00'
        + make_interval(secs => document_number)
from generate_series(1, 7) as document_number;

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
                'technical_duplicate'
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
    raise exception 'knowledge_quality_audit is append-only'
        using errcode = '42501';
end;
$$;

create trigger knowledge_quality_audit_immutable
before update or delete on public.knowledge_quality_audit
for each statement execute function public.prevent_knowledge_quality_audit_mutation();

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

insert into public.document_relations (
    id,
    owner_id,
    notebook_id,
    source_document_id,
    target_document_id,
    relation_type,
    status,
    confidence,
    signals,
    detector_version
)
select
    (
        '30000000-0000-0000-0000-'
        || lpad(source_number::text, 12, '0')
    )::uuid,
    '00000000-0000-0000-0000-000000000001'::uuid,
    '10000000-0000-0000-0000-000000000001'::uuid,
    (
        '20000000-0000-0000-0000-'
        || lpad(source_number::text, 12, '0')
    )::uuid,
    '20000000-0000-0000-0000-000000000001'::uuid,
    'related',
    'auto_confirmed',
    0.75,
    jsonb_build_object('fixture', true),
    'partial-fixture'
from generate_series(2, 7) as source_number;

insert into public.ingestion_jobs (
    id,
    owner_id,
    notebook_id,
    document_id,
    attempt_number,
    status,
    claimed_by,
    lease_expires_at
)
select
    (
        '40000000-0000-0000-0000-'
        || lpad(job_number::text, 12, '0')
    )::uuid,
    '00000000-0000-0000-0000-000000000001'::uuid,
    '10000000-0000-0000-0000-000000000001'::uuid,
    (
        '20000000-0000-0000-0000-'
        || lpad((((job_number - 1) % 7) + 1)::text, 12, '0')
    )::uuid,
    job_number,
    case when job_number <= 2 then 'running' else 'pending' end,
    case when job_number <= 2 then 'legacy-worker' else null end,
    case
        when job_number <= 2 then now() + interval '10 minutes'
        else null
    end
from generate_series(1, 9) as job_number;

-- Migration 06 already owns this exact five-argument signature. Migration 09
-- is distinguishable only by its expanded result shape, not by the signature.
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
begin
    perform 1
    from public.ingestion_jobs
    where ingestion_jobs.claim_token = p_claim_token;
    return false;
end;
$$;

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
begin
    perform 1
    from public.ingestion_jobs
    where ingestion_jobs.claim_token = p_claim_token;
end;
$$;

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
begin
    perform 1
    from public.ingestion_jobs
    where ingestion_jobs.claim_token = p_claim_token;
end;
$$;

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
begin
    perform 1
    from public.ingestion_jobs
    where ingestion_jobs.claim_token = p_claim_token;
    return false;
end;
$$;

create function public.resolve_document_relation(
    uuid, uuid, text, timestamptz, text
)
returns setof public.document_relations
language sql
security definer
set search_path = ''
as $$
    select * from public.document_relations where false
$$;
