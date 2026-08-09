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
