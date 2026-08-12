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
