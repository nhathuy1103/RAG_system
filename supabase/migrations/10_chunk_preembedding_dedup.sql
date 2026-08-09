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
