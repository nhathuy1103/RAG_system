-- Canonical Enterprise duplicate/conflict ingestion support.
-- Run after 34_p4_relation_replacement.sql.

alter table public.processing_jobs
    alter column configuration set default
        '{"knowledge_quality_mode":"on","structured_fact_mode":"on"}'::jsonb;

-- Existing direct Enterprise jobs were created with an empty configuration.
-- Only unclaimed work is opted in; an in-flight attempt keeps its original
-- execution contract.
update public.processing_jobs
set configuration = jsonb_build_object(
        'knowledge_quality_mode', 'on',
        'structured_fact_mode', 'on'
    ) || configuration
where status = 'PENDING'
  and (
      configuration ->> 'knowledge_quality_mode' is null
      or configuration ->> 'structured_fact_mode' is null
  );

alter table public.document_versions
    add column if not exists normalized_content_hash text,
    add column if not exists normalization_version text,
    add column if not exists loose_content_signature text,
    add column if not exists quality_metadata jsonb not null default '{}'::jsonb;

alter table public.document_versions
    drop constraint if exists document_versions_normalized_content_hash;
alter table public.document_versions
    add constraint document_versions_normalized_content_hash check (
        normalized_content_hash is null
        or normalized_content_hash ~ '^[0-9a-f]{64}$'
    );
alter table public.document_versions
    drop constraint if exists document_versions_normalization_version;
alter table public.document_versions
    add constraint document_versions_normalization_version check (
        normalization_version is null
        or char_length(btrim(normalization_version)) between 1 and 100
    );
alter table public.document_versions
    drop constraint if exists document_versions_loose_content_signature;
alter table public.document_versions
    add constraint document_versions_loose_content_signature check (
        loose_content_signature is null
        or loose_content_signature ~ '^[0-9a-f]{16}$'
    );
alter table public.document_versions
    drop constraint if exists document_versions_quality_metadata;
alter table public.document_versions
    add constraint document_versions_quality_metadata check (
        jsonb_typeof(quality_metadata) = 'object'
    );

create index if not exists document_versions_normalized_identity_idx
    on public.document_versions (normalized_content_hash, normalization_version)
    where normalized_content_hash is not null;

-- Migration 32 normally owns this helper. Define it idempotently here as well
-- so Enterprise-only deployments and databases upgraded from an incomplete
-- migration history can still create the canonical chunk generated column.
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

-- The worker already stores these canonical fingerprints in chunk metadata.
-- Generated columns expose them to indexed SQL candidate generation without
-- duplicating ownership of the values.
alter table public.knowledge_chunks
    add column if not exists normalized_content_hash text
        generated always as (
            nullif(metadata ->> 'normalized_content_hash', '')
        ) stored,
    add column if not exists normalization_version text
        generated always as (
            nullif(metadata ->> 'normalization_version', '')
        ) stored,
    add column if not exists loose_content_signature text
        generated always as (
            nullif(metadata ->> 'loose_content_signature', '')
        ) stored,
    add column if not exists embedding_text_checksum text
        generated always as (
            nullif(metadata ->> 'embedding_text_checksum', '')
        ) stored;

alter table public.knowledge_chunks
    add column if not exists candidate_binary_keys text[]
        generated always as (
            public.knowledge_simhash_multi_keys(
                nullif(metadata ->> 'loose_content_signature', '')
            )
        ) stored;

create index if not exists knowledge_chunks_normalized_identity_idx
    on public.knowledge_chunks (
        normalized_content_hash,
        normalization_version,
        document_id
    )
    where embedding is not null;
create index if not exists knowledge_chunks_candidate_binary_keys_idx
    on public.knowledge_chunks using gin (candidate_binary_keys)
    where embedding is not null;

create table if not exists public.knowledge_document_relations (
    id uuid primary key default gen_random_uuid(),
    source_document_id uuid not null
        references public.knowledge_documents (id) on delete cascade,
    target_document_id uuid not null
        references public.knowledge_documents (id) on delete cascade,
    source_document_version_id uuid
        references public.document_versions (id) on delete set null,
    target_document_version_id uuid
        references public.document_versions (id) on delete set null,
    relation_type text not null,
    status text not null default 'pending',
    confidence double precision not null,
    signals jsonb not null default '{}'::jsonb,
    reason text,
    detector_version text not null,
    preferred_document_id uuid
        references public.knowledge_documents (id) on delete set null,
    resolved_by uuid references auth.users (id) on delete set null,
    resolved_at timestamptz,
    created_at timestamptz not null default now(),
    updated_at timestamptz not null default now(),
    constraint knowledge_document_relations_distinct_documents
        check (source_document_id <> target_document_id),
    constraint knowledge_document_relations_type check (
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
    ),
    constraint knowledge_document_relations_status check (
        status in ('pending', 'auto_confirmed', 'confirmed', 'dismissed')
    ),
    constraint knowledge_document_relations_confidence
        check (confidence between 0 and 1),
    constraint knowledge_document_relations_signals
        check (jsonb_typeof(signals) = 'object'),
    constraint knowledge_document_relations_detector_version
        check (char_length(btrim(detector_version)) between 1 and 100),
    constraint knowledge_document_relations_resolution check (
        (status in ('pending', 'auto_confirmed') and resolved_by is null)
        or (status in ('confirmed', 'dismissed') and resolved_by is not null)
    ),
    constraint knowledge_document_relations_detector_key unique (
        source_document_id,
        target_document_id,
        detector_version
    )
);

drop trigger if exists knowledge_document_relations_set_updated_at
on public.knowledge_document_relations;
create trigger knowledge_document_relations_set_updated_at
before update on public.knowledge_document_relations
for each row execute function public.set_enterprise_updated_at();

create index if not exists knowledge_document_relations_source_idx
    on public.knowledge_document_relations (
        source_document_id,
        status,
        relation_type,
        confidence desc
    );
create index if not exists knowledge_document_relations_target_idx
    on public.knowledge_document_relations (
        target_document_id,
        status,
        relation_type
    );

alter table public.knowledge_document_relations enable row level security;
alter table public.knowledge_document_relations force row level security;

drop policy if exists knowledge_document_relations_select_visible
on public.knowledge_document_relations;
create policy knowledge_document_relations_select_visible
on public.knowledge_document_relations
for select to authenticated
using (
    public.has_document_permission(auth.uid(), source_document_id, 'READ')
    and public.has_document_permission(auth.uid(), target_document_id, 'READ')
);

revoke all on table public.knowledge_document_relations
from public, anon, authenticated;
grant select on table public.knowledge_document_relations to authenticated;
grant all privileges on table public.knowledge_document_relations to service_role;

create or replace function public.find_enterprise_content_duplicate(
    p_actor_id uuid,
    p_document_id uuid,
    p_normalized_content_hash text,
    p_normalization_version text
)
returns uuid
language plpgsql
stable
security definer
set search_path = ''
as $$
declare
    duplicate_document_id uuid;
begin
    if auth.role() <> 'service_role' then
        raise exception 'Service role is required' using errcode = '42501';
    end if;
    if p_actor_id is null
       or p_document_id is null
       or p_normalized_content_hash !~ '^[0-9a-f]{64}$'
       or char_length(btrim(coalesce(p_normalization_version, '')))
            not between 1 and 100 then
        raise exception 'Invalid Enterprise document identity lookup'
            using errcode = '22023';
    end if;

    select documents.id
    into duplicate_document_id
    from public.knowledge_documents as documents
    join public.document_versions as versions
      on versions.id = documents.current_version_id
     and versions.document_id = documents.id
     and versions.status = 'ACTIVE'
    where documents.id <> p_document_id
      and documents.status = 'PUBLISHED'
      and versions.normalized_content_hash = p_normalized_content_hash
      and versions.normalization_version = btrim(p_normalization_version)
      and public.has_document_permission(p_actor_id, documents.id, 'READ')
    order by documents.created_at, documents.id
    limit 1;

    return duplicate_document_id;
end;
$$;

revoke all on function public.find_enterprise_content_duplicate(
    uuid, uuid, text, text
) from public, anon, authenticated;
grant execute on function public.find_enterprise_content_duplicate(
    uuid, uuid, text, text
) to service_role;

create or replace function public.find_enterprise_chunk_candidates_v2(
    p_actor_id uuid,
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
    fts_score double precision,
    target_claim_scope jsonb,
    target_original_filename text,
    target_version_group_id uuid
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
    if p_actor_id is null
       or p_document_id is null
       or char_length(btrim(coalesce(p_embedding_model, '')))
            not between 1 and 200 then
        raise exception 'Invalid Enterprise candidate scope or embedding model'
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
        raise exception 'An Enterprise chunk probe has an invalid candidate payload'
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
        candidate.embedding::text,
        candidate.embedding_model,
        candidate.lsh_band_matches,
        candidate.exact_rank,
        candidate.exact_score,
        candidate.binary_rank,
        candidate.binary_score,
        candidate.binary_key_matches,
        candidate.fts_rank,
        candidate.fts_score,
        candidate.target_claim_scope,
        candidate.target_original_filename,
        candidate.target_version_group_id
    from jsonb_array_elements(p_probes) as probe(value)
    cross join lateral (
        with fts_query as (
            select to_tsquery(
                'simple'::regconfig,
                string_agg(quote_literal(term.value), ' | ' order by term.ordinality)
            ) as value
            from jsonb_array_elements_text(probe.value -> 'fts_terms')
                with ordinality as term(value, ordinality)
        ),
        eligible as (
            select
                chunks.id as target_chunk_id,
                chunks.document_id as target_document_id,
                chunks.chunk_index as target_chunk_index,
                coalesce(nullif(chunks.metadata ->> 'canonical_text', ''), chunks.content)
                    as canonical_text,
                chunks.normalized_content_hash,
                chunks.normalization_version,
                chunks.loose_content_signature,
                chunks.embedding_text_checksum,
                chunks.embedding,
                versions.embedding_model,
                coalesce((
                    select count(*)::integer
                    from unnest(chunks.candidate_binary_keys) as stored(key)
                    where stored.key in (
                        select jsonb_array_elements_text(probe.value -> 'binary_keys')
                    )
                ), 0) as binary_key_matches,
                ts_rank_cd(chunks.search_vector, fts_query.value, 32)::double precision
                    as fts_channel_score,
                chunks.normalized_content_hash =
                    probe.value ->> 'normalized_content_hash' as exact_match,
                chunks.metadata -> 'claim_scope' as target_claim_scope,
                files.original_file_name as target_original_filename,
                versions.id as target_version_group_id,
                documents.created_at
            from public.knowledge_chunks as chunks
            join public.document_versions as versions
              on versions.id = chunks.document_version_id
             and versions.document_id = chunks.document_id
             and versions.status = 'ACTIVE'
            join public.knowledge_documents as documents
              on documents.id = chunks.document_id
             and documents.current_version_id = versions.id
             and documents.status = 'PUBLISHED'
            join public.source_files as files on files.id = versions.source_file_id
            cross join fts_query
            where chunks.document_id <> p_document_id
              and chunks.normalization_version =
                    btrim(probe.value ->> 'normalization_version')
              and chunks.embedding is not null
              and versions.embedding_model = btrim(p_embedding_model)
              and public.has_document_permission(p_actor_id, documents.id, 'READ')
              and (
                  chunks.normalized_content_hash =
                      probe.value ->> 'normalized_content_hash'
                  or (
                      (probe.value ->> 'include_fuzzy')::boolean
                      and (
                          chunks.candidate_binary_keys && array(
                              select jsonb_array_elements_text(
                                  probe.value -> 'binary_keys'
                              )
                          )
                          or (
                              fts_query.value is not null
                              and numnode(fts_query.value) > 0
                              and chunks.search_vector @@ fts_query.value
                          )
                      )
                  )
              )
        ),
        ranked as (
            select
                eligible.*,
                row_number() over (
                    order by eligible.created_at, eligible.target_chunk_id
                )::integer as exact_channel_rank,
                row_number() over (
                    order by eligible.binary_key_matches desc,
                        eligible.created_at, eligible.target_chunk_id
                )::integer as binary_channel_rank,
                row_number() over (
                    order by eligible.fts_channel_score desc,
                        eligible.target_chunk_id
                )::integer as fts_channel_rank
            from eligible
        )
        select
            ranked.target_chunk_id,
            ranked.target_document_id,
            ranked.target_chunk_index,
            ranked.canonical_text,
            ranked.normalized_content_hash,
            ranked.normalization_version,
            ranked.loose_content_signature,
            ranked.embedding_text_checksum,
            ranked.embedding,
            ranked.embedding_model,
            ranked.binary_key_matches as lsh_band_matches,
            case when ranked.exact_match then ranked.exact_channel_rank end as exact_rank,
            case when ranked.exact_match then 1.0::double precision end as exact_score,
            case when ranked.binary_key_matches > 0
                then ranked.binary_channel_rank end as binary_rank,
            case when ranked.binary_key_matches > 0
                then ranked.binary_key_matches::double precision / 64.0 end
                as binary_score,
            ranked.binary_key_matches,
            case when ranked.fts_channel_score > 0
                then ranked.fts_channel_rank end as fts_rank,
            case when ranked.fts_channel_score > 0
                then ranked.fts_channel_score end as fts_score,
            ranked.target_claim_scope,
            ranked.target_original_filename,
            ranked.target_version_group_id
        from ranked
        order by
            ranked.exact_match desc,
            ranked.binary_key_matches desc,
            ranked.fts_channel_score desc,
            ranked.target_chunk_id
        limit p_limit_per_probe
    ) as candidate;
end;
$$;

revoke all on function public.find_enterprise_chunk_candidates_v2(
    uuid, uuid, text, jsonb, integer
) from public, anon, authenticated;
grant execute on function public.find_enterprise_chunk_candidates_v2(
    uuid, uuid, text, jsonb, integer
) to service_role;

create or replace function public.complete_processing_job_v4(
    p_job_id uuid,
    p_worker_id text,
    p_claim_token uuid,
    p_chunks jsonb,
    p_normalized_content_hash text,
    p_normalization_version text,
    p_loose_content_signature text,
    p_quality_metadata jsonb,
    p_quality_mode text,
    p_relations jsonb default '[]'::jsonb
)
returns public.processing_jobs
language plpgsql
security definer
set search_path = ''
as $$
declare
    selected_requested_by uuid;
    selected_version_id uuid;
    selected_document_id uuid;
    completed_job public.processing_jobs;
    relation_count integer := 0;
begin
    if auth.role() <> 'service_role' then
        raise exception 'Service role is required' using errcode = '42501';
    end if;
    if p_quality_mode not in ('off', 'shadow', 'on') then
        raise exception 'Invalid Enterprise knowledge-quality mode'
            using errcode = '22023';
    end if;
    if jsonb_typeof(coalesce(p_quality_metadata, '{}'::jsonb)) <> 'object'
       or jsonb_typeof(coalesce(p_relations, '[]'::jsonb)) <> 'array'
       or jsonb_array_length(coalesce(p_relations, '[]'::jsonb)) > 1000 then
        raise exception 'Invalid Enterprise quality payload'
            using errcode = '22023';
    end if;
    if p_normalized_content_hash is not null and (
        p_normalized_content_hash !~ '^[0-9a-f]{64}$'
        or char_length(btrim(coalesce(p_normalization_version, '')))
            not between 1 and 100
        or p_loose_content_signature !~ '^[0-9a-f]{16}$'
    ) then
        raise exception 'Invalid Enterprise document fingerprint'
            using errcode = '22023';
    end if;

    select jobs.requested_by, versions.id, documents.id
    into selected_requested_by, selected_version_id, selected_document_id
    from public.processing_jobs as jobs
    join public.document_versions as versions
      on versions.id = jobs.document_version_id
    join public.knowledge_documents as documents
      on documents.id = versions.document_id
    where jobs.id = p_job_id
      and jobs.status = 'RUNNING'
      and jobs.lease_owner = btrim(p_worker_id)
      and jobs.claim_token = p_claim_token
      and jobs.lease_expires_at > now();
    if not found then
        raise exception 'Processing lease is stale' using errcode = '40001';
    end if;

    if exists (
        select 1
        from jsonb_array_elements(coalesce(p_relations, '[]'::jsonb))
            as relation(value)
        where jsonb_typeof(relation.value) <> 'object'
           or coalesce(relation.value ->> 'target_document_id', '')
                !~ '^[0-9a-fA-F-]{36}$'
           or (relation.value ->> 'target_document_id')::uuid = selected_document_id
           or relation.value ->> 'relation_type' not in (
                'exact_content', 'near_duplicate', 'version_candidate', 'version',
                'conflict_candidate', 'conflict', 'related', 'distinct',
                'technical_duplicate', 'template_variant', 'temporal_series'
           )
           or (relation.value ->> 'confidence')::double precision not between 0 and 1
           or jsonb_typeof(coalesce(relation.value -> 'signals', '{}'::jsonb))
                <> 'object'
           or char_length(btrim(coalesce(relation.value ->> 'detector_version', '')))
                not between 1 and 100
    ) then
        raise exception 'Invalid Enterprise relation payload'
            using errcode = '22023';
    end if;

    if exists (
        select 1
        from jsonb_array_elements(coalesce(p_relations, '[]'::jsonb))
            as relation(value)
        left join public.knowledge_documents as target
         on target.id = (relation.value ->> 'target_document_id')::uuid
         and target.status = 'PUBLISHED'
         and public.has_document_permission(
             selected_requested_by, target.id, 'READ'
         )
        where target.id is null
    ) then
        raise exception 'Enterprise relation target is outside the visible ACL scope'
            using errcode = '23503';
    end if;

    completed_job := public.complete_processing_job_v3(
        p_job_id,
        p_worker_id,
        p_claim_token,
        p_chunks
    );

    update public.document_versions
    set normalized_content_hash = p_normalized_content_hash,
        normalization_version = p_normalization_version,
        loose_content_signature = p_loose_content_signature,
        quality_metadata = coalesce(p_quality_metadata, '{}'::jsonb)
            || jsonb_build_object('knowledge_quality_mode', p_quality_mode),
        metadata_revision = metadata_revision + 1
    where id = selected_version_id;

    delete from public.knowledge_document_relations as existing
    where existing.source_document_id = selected_document_id
      and existing.status in ('pending', 'auto_confirmed')
      and coalesce(
          (existing.signals ->> 'enterprise_ingestion_managed')::boolean,
          false
      );

    insert into public.knowledge_document_relations (
        source_document_id,
        target_document_id,
        source_document_version_id,
        target_document_version_id,
        relation_type,
        status,
        confidence,
        signals,
        reason,
        detector_version,
        resolved_at
    )
    select
        selected_document_id,
        target.id,
        selected_version_id,
        target.current_version_id,
        relation.value ->> 'relation_type',
        case
            when p_quality_mode = 'on'
             and relation.value ->> 'relation_type' = 'exact_content'
            then 'auto_confirmed'
            else 'pending'
        end,
        (relation.value ->> 'confidence')::double precision,
        coalesce(relation.value -> 'signals', '{}'::jsonb)
            || jsonb_build_object(
                'enterprise_ingestion_managed', true,
                'p4_primary_relation', case relation.value ->> 'relation_type'
                    when 'exact_content' then 'EXACT_DUPLICATE'
                    when 'technical_duplicate' then 'EXACT_DUPLICATE'
                    when 'near_duplicate' then 'NEAR_DUPLICATE'
                    when 'version' then 'VERSION_UPDATE'
                    when 'temporal_series' then 'TEMPORAL_VARIANT'
                    when 'template_variant' then 'TEMPLATE_VARIANT'
                    when 'conflict' then 'CONFLICT'
                    when 'distinct' then 'DISTINCT'
                    else 'UNCERTAIN'
                end,
                'p4_review_status', case
                    when p_quality_mode = 'on'
                     and relation.value ->> 'relation_type' = 'exact_content'
                    then 'auto_confirmed'
                    else 'pending'
                end
            ),
        nullif(btrim(relation.value ->> 'reason'), ''),
        btrim(relation.value ->> 'detector_version'),
        case
            when p_quality_mode = 'on'
             and relation.value ->> 'relation_type' = 'exact_content'
            then now()
            else null
        end
    from jsonb_array_elements(coalesce(p_relations, '[]'::jsonb))
        as relation(value)
    join public.knowledge_documents as target
     on target.id = (relation.value ->> 'target_document_id')::uuid
     and target.status = 'PUBLISHED'
     and public.has_document_permission(
         selected_requested_by, target.id, 'READ'
     )
    on conflict (source_document_id, target_document_id, detector_version)
    do update set
        source_document_version_id = excluded.source_document_version_id,
        target_document_version_id = excluded.target_document_version_id,
        relation_type = excluded.relation_type,
        status = excluded.status,
        confidence = excluded.confidence,
        signals = excluded.signals,
        reason = excluded.reason,
        resolved_by = null,
        resolved_at = excluded.resolved_at
    where public.knowledge_document_relations.status
        in ('pending', 'auto_confirmed');
    get diagnostics relation_count = row_count;

    update public.knowledge_documents
    set metadata = metadata || jsonb_build_object(
            'knowledge_quality', jsonb_build_object(
                'mode', p_quality_mode,
                'relation_count', relation_count,
                'status', case
                    when exists (
                        select 1
                        from public.knowledge_document_relations as relations
                        where relations.source_document_id = selected_document_id
                          and relations.status = 'pending'
                    ) then 'review_required'
                    else 'ready'
                end,
                'updated_at', now()
            )
        )
    where id = selected_document_id;

    return completed_job;
end;
$$;

revoke all on function public.complete_processing_job_v4(
    uuid, text, uuid, jsonb, text, text, text, jsonb, text, jsonb
) from public, anon, authenticated;
grant execute on function public.complete_processing_job_v4(
    uuid, text, uuid, jsonb, text, text, text, jsonb, text, jsonb
) to service_role;

comment on table public.knowledge_document_relations is
    'ACL-safe canonical Enterprise duplicate/version/conflict relations emitted by ingestion.';
comment on function public.complete_processing_job_v4(
    uuid, text, uuid, jsonb, text, text, text, jsonb, text, jsonb
) is
    'Atomically completes Enterprise ingestion and persists canonical identity plus recomputable quality relations.';
