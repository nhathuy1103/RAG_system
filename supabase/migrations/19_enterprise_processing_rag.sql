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
