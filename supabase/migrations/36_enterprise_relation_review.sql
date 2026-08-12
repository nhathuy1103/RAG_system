-- Reliable Enterprise duplicate/conflict candidates and review workflow.
-- Run after 35_enterprise_knowledge_quality.sql.

-- Migration 35 ranked every eligible chunk before applying its result limit.
-- Build a small ID-only pool per indexed channel first, fuse it, and fetch the
-- large vector/text payload only for the final candidates.
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
        coalesce(
            nullif(candidate.metadata ->> 'canonical_text', ''),
            candidate.content
        ),
        candidate.normalized_content_hash,
        candidate.normalization_version,
        candidate.loose_content_signature,
        candidate.embedding_text_checksum,
        candidate.embedding::text,
        candidate.embedding_model,
        candidate.binary_key_matches,
        candidate.exact_rank,
        candidate.exact_score,
        candidate.binary_rank,
        candidate.binary_score,
        candidate.binary_key_matches,
        candidate.fts_rank,
        candidate.fts_score,
        candidate.metadata -> 'claim_scope',
        candidate.original_file_name,
        candidate.document_version_id
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
        exact_limited as (
            select
                chunks.id as target_chunk_id,
                row_number() over (
                    order by documents.created_at, chunks.chunk_index, chunks.id
                )::integer as channel_rank
            from public.knowledge_chunks as chunks
            join public.document_versions as versions
              on versions.id = chunks.document_version_id
             and versions.document_id = chunks.document_id
             and versions.status = 'ACTIVE'
             and versions.embedding_model = btrim(p_embedding_model)
            join public.knowledge_documents as documents
              on documents.id = chunks.document_id
             and documents.current_version_id = versions.id
             and documents.status = 'PUBLISHED'
            where chunks.document_id <> p_document_id
              and chunks.embedding is not null
              and chunks.normalization_version =
                    btrim(probe.value ->> 'normalization_version')
              and chunks.normalized_content_hash =
                    probe.value ->> 'normalized_content_hash'
              and public.has_document_permission(p_actor_id, documents.id, 'READ')
            order by documents.created_at, chunks.chunk_index, chunks.id
            limit p_limit_per_probe
        ),
        binary_scored as (
            select
                chunks.id as target_chunk_id,
                documents.created_at,
                chunks.chunk_index,
                coalesce((
                    select count(*)::integer
                    from unnest(chunks.candidate_binary_keys) as stored(key)
                    where stored.key in (
                        select jsonb_array_elements_text(
                            probe.value -> 'binary_keys'
                        )
                    )
                ), 0) as binary_key_matches
            from public.knowledge_chunks as chunks
            join public.document_versions as versions
              on versions.id = chunks.document_version_id
             and versions.document_id = chunks.document_id
             and versions.status = 'ACTIVE'
             and versions.embedding_model = btrim(p_embedding_model)
            join public.knowledge_documents as documents
              on documents.id = chunks.document_id
             and documents.current_version_id = versions.id
             and documents.status = 'PUBLISHED'
            where (probe.value ->> 'include_fuzzy')::boolean
              and chunks.document_id <> p_document_id
              and chunks.embedding is not null
              and chunks.normalization_version =
                    btrim(probe.value ->> 'normalization_version')
              and chunks.candidate_binary_keys && array(
                    select jsonb_array_elements_text(
                        probe.value -> 'binary_keys'
                    )
              )
              and public.has_document_permission(p_actor_id, documents.id, 'READ')
        ),
        binary_limited as (
            select
                limited.target_chunk_id,
                limited.binary_key_matches,
                row_number() over (
                    order by limited.binary_key_matches desc,
                        limited.created_at, limited.chunk_index,
                        limited.target_chunk_id
                )::integer as channel_rank
            from (
                select binary_scored.*
                from binary_scored
                order by binary_scored.binary_key_matches desc,
                    binary_scored.created_at,
                    binary_scored.chunk_index,
                    binary_scored.target_chunk_id
                limit p_limit_per_probe
            ) as limited
        ),
        fts_scored as (
            select
                chunks.id as target_chunk_id,
                ts_rank_cd(
                    chunks.search_vector,
                    fts_query.value,
                    32
                )::double precision as channel_score
            from public.knowledge_chunks as chunks
            join public.document_versions as versions
              on versions.id = chunks.document_version_id
             and versions.document_id = chunks.document_id
             and versions.status = 'ACTIVE'
             and versions.embedding_model = btrim(p_embedding_model)
            join public.knowledge_documents as documents
              on documents.id = chunks.document_id
             and documents.current_version_id = versions.id
             and documents.status = 'PUBLISHED'
            cross join fts_query
            where (probe.value ->> 'include_fuzzy')::boolean
              and fts_query.value is not null
              and numnode(fts_query.value) > 0
              and chunks.document_id <> p_document_id
              and chunks.embedding is not null
              and chunks.normalization_version =
                    btrim(probe.value ->> 'normalization_version')
              and chunks.search_vector @@ fts_query.value
              and public.has_document_permission(p_actor_id, documents.id, 'READ')
        ),
        fts_limited as (
            select
                limited.target_chunk_id,
                limited.channel_score,
                row_number() over (
                    order by limited.channel_score desc, limited.target_chunk_id
                )::integer as channel_rank
            from (
                select fts_scored.*
                from fts_scored
                order by fts_scored.channel_score desc, fts_scored.target_chunk_id
                limit p_limit_per_probe
            ) as limited
        ),
        channel_rows as (
            select
                exact_limited.target_chunk_id,
                exact_limited.channel_rank as exact_rank,
                1.0::double precision as exact_score,
                null::integer as binary_rank,
                null::double precision as binary_score,
                0::integer as binary_key_matches,
                null::integer as fts_rank,
                null::double precision as fts_score
            from exact_limited
            union all
            select
                binary_limited.target_chunk_id,
                null, null,
                binary_limited.channel_rank,
                binary_limited.binary_key_matches::double precision / 64.0,
                binary_limited.binary_key_matches,
                null, null
            from binary_limited
            union all
            select
                fts_limited.target_chunk_id,
                null, null, null, null, 0,
                fts_limited.channel_rank,
                fts_limited.channel_score
            from fts_limited
        ),
        fused_limited as (
            select
                channel_rows.target_chunk_id,
                min(channel_rows.exact_rank) as exact_rank,
                max(channel_rows.exact_score) as exact_score,
                min(channel_rows.binary_rank) as binary_rank,
                max(channel_rows.binary_score) as binary_score,
                max(channel_rows.binary_key_matches)::integer as binary_key_matches,
                min(channel_rows.fts_rank) as fts_rank,
                max(channel_rows.fts_score) as fts_score
            from channel_rows
            group by channel_rows.target_chunk_id
            order by
                min(channel_rows.exact_rank) nulls last,
                (
                    coalesce(1.0 / (60 + min(channel_rows.exact_rank)), 0.0)
                    + coalesce(1.0 / (60 + min(channel_rows.binary_rank)), 0.0)
                    + coalesce(1.0 / (60 + min(channel_rows.fts_rank)), 0.0)
                ) desc,
                channel_rows.target_chunk_id
            limit p_limit_per_probe
        )
        select
            chunks.id as target_chunk_id,
            chunks.document_id as target_document_id,
            chunks.chunk_index as target_chunk_index,
            chunks.content,
            chunks.metadata,
            chunks.normalized_content_hash,
            chunks.normalization_version,
            chunks.loose_content_signature,
            chunks.embedding_text_checksum,
            chunks.embedding,
            versions.embedding_model,
            versions.id as document_version_id,
            files.original_file_name,
            fused_limited.exact_rank,
            fused_limited.exact_score,
            fused_limited.binary_rank,
            fused_limited.binary_score,
            fused_limited.binary_key_matches,
            fused_limited.fts_rank,
            fused_limited.fts_score
        from fused_limited
        join public.knowledge_chunks as chunks
          on chunks.id = fused_limited.target_chunk_id
        join public.document_versions as versions
          on versions.id = chunks.document_version_id
        join public.source_files as files
          on files.id = versions.source_file_id
        order by
            fused_limited.exact_rank nulls last,
            (
                coalesce(1.0 / (60 + fused_limited.exact_rank), 0.0)
                + coalesce(1.0 / (60 + fused_limited.binary_rank), 0.0)
                + coalesce(1.0 / (60 + fused_limited.fts_rank), 0.0)
            ) desc,
            chunks.id
    ) as candidate;
end;
$$;

revoke all on function public.find_enterprise_chunk_candidates_v2(
    uuid, uuid, text, jsonb, integer
) from public, anon, authenticated;
grant execute on function public.find_enterprise_chunk_candidates_v2(
    uuid, uuid, text, jsonb, integer
) to service_role;

-- Deferred is a durable human review state. It must not be overwritten by a
-- later automatic detector run.
alter table public.knowledge_document_relations
    drop constraint if exists knowledge_document_relations_status;
alter table public.knowledge_document_relations
    add constraint knowledge_document_relations_status check (
        status in (
            'pending', 'deferred', 'auto_confirmed', 'confirmed', 'dismissed'
        )
    );

alter table public.knowledge_document_relations
    drop constraint if exists knowledge_document_relations_resolution;
alter table public.knowledge_document_relations
    add constraint knowledge_document_relations_resolution check (
        (
            status in ('pending', 'deferred', 'auto_confirmed')
            and resolved_by is null
        )
        or (
            status in ('confirmed', 'dismissed')
            and resolved_by is not null
        )
    );

create or replace function public.list_enterprise_document_relations(
    p_status text default null,
    p_limit integer default 200,
    p_offset integer default 0
)
returns jsonb
language plpgsql
stable
security definer
set search_path = ''
as $$
declare
    actor uuid := auth.uid();
    result jsonb;
begin
    if actor is null then
        raise exception 'Authentication is required' using errcode = '42501';
    end if;
    if p_status is not null and p_status not in (
        'pending', 'deferred', 'auto_confirmed', 'confirmed', 'dismissed'
    ) then
        raise exception 'Invalid Enterprise relation status'
            using errcode = '22023';
    end if;
    if p_limit is null or p_limit not between 1 and 200
       or p_offset is null or p_offset < 0 then
        raise exception 'Invalid Enterprise relation page'
            using errcode = '22023';
    end if;

    with visible as (
        select
            relations.id,
            relations.source_document_id,
            relations.target_document_id,
            relations.relation_type,
            relations.status,
            relations.confidence,
            relations.reason,
            relations.created_at,
            relations.updated_at,
            nullif(relations.signals ->> 'resolution_action', '')
                as resolution_action,
            source_documents.title as source_document_title,
            target_documents.title as target_document_title
        from public.knowledge_document_relations as relations
        join public.knowledge_documents as source_documents
          on source_documents.id = relations.source_document_id
        join public.knowledge_documents as target_documents
          on target_documents.id = relations.target_document_id
        where (p_status is null or relations.status = p_status)
          and public.has_document_permission(
              actor, relations.source_document_id, 'READ'
          )
          and public.has_document_permission(
              actor, relations.target_document_id, 'READ'
          )
    ),
    page as (
        select visible.*
        from visible
        order by visible.created_at desc, visible.id desc
        limit p_limit offset p_offset
    )
    select jsonb_build_object(
        'items', coalesce(
            (select jsonb_agg(to_jsonb(page) order by page.created_at desc, page.id desc)
             from page),
            '[]'::jsonb
        ),
        'total_count', (select count(*) from visible),
        'limit', p_limit,
        'offset', p_offset
    )
    into result;

    return result;
end;
$$;

revoke all on function public.list_enterprise_document_relations(
    text, integer, integer
) from public, anon;
grant execute on function public.list_enterprise_document_relations(
    text, integer, integer
) to authenticated;

create or replace function public.get_enterprise_document_relation_evidence(
    p_relation_id uuid
)
returns jsonb
language plpgsql
stable
security definer
set search_path = ''
as $$
declare
    actor uuid := auth.uid();
    selected_relation public.knowledge_document_relations;
    source_version_id uuid;
    target_version_id uuid;
    source_title text;
    target_title text;
    source_version_number integer;
    target_version_number integer;
    source_text text;
    target_text text;
    source_overlap text;
    target_overlap text;
    source_chunk_index integer;
    target_chunk_index integer;
begin
    if actor is null then
        raise exception 'Authentication is required' using errcode = '42501';
    end if;

    select relations.*
    into selected_relation
    from public.knowledge_document_relations as relations
    where relations.id = p_relation_id
      and public.has_document_permission(actor, relations.source_document_id, 'READ')
      and public.has_document_permission(actor, relations.target_document_id, 'READ');
    if not found then
        return null;
    end if;

    select
        source_documents.title,
        target_documents.title,
        coalesce(
            selected_relation.source_document_version_id,
            source_documents.current_version_id
        ),
        coalesce(
            selected_relation.target_document_version_id,
            target_documents.current_version_id
        )
    into source_title, target_title, source_version_id, target_version_id
    from public.knowledge_documents as source_documents
    join public.knowledge_documents as target_documents
      on target_documents.id = selected_relation.target_document_id
    where source_documents.id = selected_relation.source_document_id;

    select versions.version_number
    into source_version_number
    from public.document_versions as versions
    where versions.id = source_version_id;

    select versions.version_number
    into target_version_number
    from public.document_versions as versions
    where versions.id = target_version_id;

    select left(
        coalesce(string_agg(chunks.content, E'\n\n' order by chunks.chunk_index), ''),
        100000
    )
    into source_text
    from public.knowledge_chunks as chunks
    where chunks.document_id = selected_relation.source_document_id
      and chunks.document_version_id = source_version_id;

    select left(
        coalesce(string_agg(chunks.content, E'\n\n' order by chunks.chunk_index), ''),
        100000
    )
    into target_text
    from public.knowledge_chunks as chunks
    where chunks.document_id = selected_relation.target_document_id
      and chunks.document_version_id = target_version_id;

    if selected_relation.signals #>> '{selected_chunk_pair,source_chunk_index}'
            ~ '^[0-9]+$' then
        source_chunk_index := (
            selected_relation.signals
            #>> '{selected_chunk_pair,source_chunk_index}'
        )::integer;
    end if;
    if selected_relation.signals #>> '{selected_chunk_pair,target_chunk_index}'
            ~ '^[0-9]+$' then
        target_chunk_index := (
            selected_relation.signals
            #>> '{selected_chunk_pair,target_chunk_index}'
        )::integer;
    end if;

    if source_chunk_index is not null then
        select chunks.content
        into source_overlap
        from public.knowledge_chunks as chunks
        where chunks.document_id = selected_relation.source_document_id
          and chunks.document_version_id = source_version_id
          and chunks.chunk_index = source_chunk_index
        limit 1;
    end if;
    if target_chunk_index is not null then
        select chunks.content
        into target_overlap
        from public.knowledge_chunks as chunks
        where chunks.document_id = selected_relation.target_document_id
          and chunks.document_version_id = target_version_id
          and chunks.chunk_index = target_chunk_index
        limit 1;
    end if;

    return jsonb_build_object(
        'relation_id', selected_relation.id,
        'source_document', jsonb_build_object(
            'id', selected_relation.source_document_id,
            'title', source_title,
            'version_number', coalesce(source_version_number, 1),
            'text_content', source_text
        ),
        'target_document', jsonb_build_object(
            'id', selected_relation.target_document_id,
            'title', target_title,
            'version_number', coalesce(target_version_number, 1),
            'text_content', target_text
        ),
        'overlaps', case
            when source_overlap is not null and target_overlap is not null
            then jsonb_build_array(jsonb_build_object(
                'source_text', source_overlap,
                'target_text', target_overlap
            ))
            else '[]'::jsonb
        end
    );
end;
$$;

revoke all on function public.get_enterprise_document_relation_evidence(uuid)
from public, anon;
grant execute on function public.get_enterprise_document_relation_evidence(uuid)
to authenticated;

create or replace function public.resolve_enterprise_document_relation(
    p_relation_id uuid,
    p_action text,
    p_reason text default null,
    p_expected_updated_at timestamptz default null
)
returns public.knowledge_document_relations
language plpgsql
security definer
set search_path = ''
as $$
declare
    actor uuid := auth.uid();
    selected_relation public.knowledge_document_relations;
    resolved_relation public.knowledge_document_relations;
    normalized_action text := lower(btrim(coalesce(p_action, '')));
    normalized_reason text := nullif(btrim(coalesce(p_reason, '')), '');
    next_type text;
    next_status text;
    preferred_id uuid;
begin
    if actor is null then
        raise exception 'Authentication is required' using errcode = '42501';
    end if;
    if normalized_action not in (
        'confirm_duplicate', 'mark_version', 'confirm_conflict',
        'keep_separate', 'prefer_source', 'prefer_target',
        'dismiss', 'defer_review'
    ) then
        raise exception 'Invalid Enterprise relation resolution action'
            using errcode = '22023';
    end if;
    if normalized_action <> 'defer_review' and normalized_reason is null then
        raise exception 'A resolution reason is required'
            using errcode = '22023';
    end if;
    if char_length(coalesce(normalized_reason, '')) > 2000 then
        raise exception 'Resolution reason is too long'
            using errcode = '22023';
    end if;

    select relations.*
    into selected_relation
    from public.knowledge_document_relations as relations
    where relations.id = p_relation_id
    for update;
    if not found then
        raise exception 'Enterprise relation was not found'
            using errcode = 'P0002';
    end if;
    if not (
        public.has_document_permission(
            actor, selected_relation.source_document_id, 'REVIEW'
        )
        or public.has_document_permission(
            actor, selected_relation.source_document_id, 'PUBLISH'
        )
        or public.has_document_permission(
            actor, selected_relation.source_document_id, 'MANAGE'
        )
    ) or not public.has_document_permission(
        actor, selected_relation.target_document_id, 'READ'
    ) then
        raise exception 'Enterprise relation review is not permitted'
            using errcode = '42501';
    end if;
    if selected_relation.status not in ('pending', 'deferred') then
        raise exception 'Enterprise relation was already resolved'
            using errcode = '40001';
    end if;
    if p_expected_updated_at is not null
       and selected_relation.updated_at <> p_expected_updated_at then
        raise exception 'Enterprise relation changed during review'
            using errcode = '40001';
    end if;

    next_type := case normalized_action
        when 'confirm_duplicate' then 'exact_content'
        when 'mark_version' then 'version'
        when 'confirm_conflict' then 'conflict'
        when 'prefer_source' then 'conflict'
        when 'prefer_target' then 'conflict'
        when 'keep_separate' then 'distinct'
        else selected_relation.relation_type
    end;
    next_status := case normalized_action
        when 'dismiss' then 'dismissed'
        when 'defer_review' then 'deferred'
        else 'confirmed'
    end;
    preferred_id := case normalized_action
        when 'prefer_source' then selected_relation.source_document_id
        when 'prefer_target' then selected_relation.target_document_id
        else null
    end;

    update public.knowledge_document_relations as relations
    set relation_type = next_type,
        status = next_status,
        reason = coalesce(
            normalized_reason,
            case when normalized_action = 'defer_review'
                then 'Deferred for later review' end,
            relations.reason
        ),
        signals = relations.signals || jsonb_strip_nulls(jsonb_build_object(
            'resolution_action', normalized_action,
            'resolution_reason', normalized_reason,
            'resolution_recorded_at', now()
        )),
        preferred_document_id = preferred_id,
        resolved_by = case when next_status in ('confirmed', 'dismissed')
            then actor else null end,
        resolved_at = case when next_status in ('confirmed', 'dismissed')
            then now() else null end
    where relations.id = selected_relation.id
    returning relations.* into resolved_relation;

    update public.knowledge_documents as documents
    set metadata = documents.metadata || jsonb_build_object(
        'knowledge_quality', jsonb_build_object(
            'mode', coalesce(
                documents.metadata #>> '{knowledge_quality,mode}',
                'on'
            ),
            'relation_count', (
                select count(*)
                from public.knowledge_document_relations as relations
                where relations.source_document_id = selected_relation.source_document_id
            ),
            'status', case when exists (
                select 1
                from public.knowledge_document_relations as relations
                where relations.source_document_id = selected_relation.source_document_id
                  and relations.status in ('pending', 'deferred')
            ) then 'review_required' else 'ready' end,
            'updated_at', now()
        )
    )
    where documents.id = selected_relation.source_document_id;

    perform public.write_enterprise_audit(
        'RESOLVE_DOCUMENT_RELATION',
        'knowledge_document_relation',
        selected_relation.id,
        to_jsonb(selected_relation),
        to_jsonb(resolved_relation),
        normalized_reason
    );

    return resolved_relation;
end;
$$;

revoke all on function public.resolve_enterprise_document_relation(
    uuid, text, text, timestamptz
) from public, anon;
grant execute on function public.resolve_enterprise_document_relation(
    uuid, text, text, timestamptz
) to authenticated;

create or replace function public.queue_enterprise_quality_reprocess(
    p_document_id uuid
)
returns public.processing_jobs
language plpgsql
security definer
set search_path = ''
as $$
declare
    actor uuid := auth.uid();
    selected_document public.knowledge_documents;
    selected_version public.document_versions;
    previous_job public.processing_jobs;
    created_job public.processing_jobs;
    next_attempt integer;
begin
    if actor is null then
        raise exception 'Authentication is required' using errcode = '42501';
    end if;

    select documents.*
    into selected_document
    from public.knowledge_documents as documents
    where documents.id = p_document_id
      and documents.status = 'PUBLISHED'
    for update;
    if not found then
        raise exception 'Published Enterprise document was not found'
            using errcode = 'P0002';
    end if;
    if not (
        (
            public.has_functional_permission(actor, 'REVIEW_DOCUMENT')
            and public.has_document_permission(actor, p_document_id, 'REVIEW')
        )
        or (
            public.has_functional_permission(actor, 'PUBLISH_DOCUMENT')
            and public.has_document_permission(actor, p_document_id, 'PUBLISH')
        )
        or (
            public.has_functional_permission(actor, 'MANAGE_DOCUMENT')
            and public.has_document_permission(actor, p_document_id, 'MANAGE')
        )
    ) then
        raise exception 'Enterprise quality reprocessing is not permitted'
            using errcode = '42501';
    end if;

    select versions.*
    into selected_version
    from public.document_versions as versions
    where versions.id = selected_document.current_version_id
      and versions.document_id = selected_document.id
      and versions.status = 'ACTIVE'
    for update;
    if not found then
        raise exception 'Active Enterprise document version was not found'
            using errcode = 'P0002';
    end if;
    if exists (
        select 1
        from public.processing_jobs as jobs
        where jobs.document_version_id = selected_version.id
          and jobs.status in ('PENDING', 'RUNNING')
    ) then
        raise exception 'Enterprise document already has an active processing job'
            using errcode = '55000';
    end if;

    select jobs.*
    into previous_job
    from public.processing_jobs as jobs
    where jobs.document_version_id = selected_version.id
      and jobs.status = 'SUCCEEDED'
    order by jobs.attempt_no desc, jobs.id desc
    limit 1;
    if not found then
        raise exception 'No successful Enterprise job is available to reprocess'
            using errcode = '55000';
    end if;

    select coalesce(max(jobs.attempt_no), 0) + 1
    into next_attempt
    from public.processing_jobs as jobs
    where jobs.document_version_id = selected_version.id;

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
        selected_version.id,
        'REPROCESS',
        'PENDING',
        next_attempt,
        previous_job.id,
        actor,
        previous_job.embedding_model,
        previous_job.embedding_dimensions,
        previous_job.configuration || jsonb_build_object(
            'knowledge_quality_mode', 'on',
            'structured_fact_mode', coalesce(
                previous_job.configuration ->> 'structured_fact_mode',
                'on'
            )
        )
    )
    returning * into created_job;

    perform public.write_enterprise_audit(
        'ENTERPRISE_QUALITY_REPROCESS_QUEUED',
        'processing_job',
        created_job.id,
        jsonb_build_object('previous_job_id', previous_job.id),
        jsonb_build_object(
            'document_id', selected_document.id,
            'document_version_id', selected_version.id,
            'attempt_no', next_attempt,
            'knowledge_quality_mode', 'on'
        ),
        'Manual duplicate/conflict quality rescan'
    );

    return created_job;
end;
$$;

revoke all on function public.queue_enterprise_quality_reprocess(uuid)
from public, anon;
grant execute on function public.queue_enterprise_quality_reprocess(uuid)
to authenticated;

comment on function public.list_enterprise_document_relations(
    text, integer, integer
) is 'Lists canonical ACL-visible Enterprise duplicate/conflict review items.';
comment on function public.get_enterprise_document_relation_evidence(uuid) is
    'Returns version-bound, ACL-safe text evidence for one Enterprise relation.';
comment on function public.resolve_enterprise_document_relation(
    uuid, text, text, timestamptz
) is 'Atomically records a reviewer decision with optimistic concurrency and audit.';
comment on function public.queue_enterprise_quality_reprocess(uuid) is
    'Queues a new quality-enabled attempt for the active version of a published Enterprise document.';
