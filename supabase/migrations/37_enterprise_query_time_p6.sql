-- P6 canonical temporal retrieval metadata for Enterprise search and Q&A.
-- Run after 36_enterprise_relation_review.sql.

create or replace function public.enterprise_chunk_reference_year(
    p_metadata jsonb
)
returns integer
language sql
immutable
set search_path = ''
as $$
    select case
        when coalesce(
            p_metadata #>> '{retrieval_metadata,year}',
            p_metadata #>> '{claim_scope,reference_year}',
            p_metadata #>> '{structured_temporal,reference_year}',
            p_metadata ->> 'reference_year',
            p_metadata ->> 'year'
        ) ~ '^(19|20)[0-9]{2}$'
        then coalesce(
            p_metadata #>> '{retrieval_metadata,year}',
            p_metadata #>> '{claim_scope,reference_year}',
            p_metadata #>> '{structured_temporal,reference_year}',
            p_metadata ->> 'reference_year',
            p_metadata ->> 'year'
        )::integer
        else null
    end;
$$;

revoke all on function public.enterprise_chunk_reference_year(jsonb)
from public, anon, authenticated;
grant execute on function public.enterprise_chunk_reference_year(jsonb)
to service_role;

alter table public.knowledge_chunks
    add column if not exists canonical_reference_year integer
        generated always as (
            public.enterprise_chunk_reference_year(metadata)
        ) stored;

alter table public.knowledge_chunks
    drop constraint if exists knowledge_chunks_canonical_reference_year;
alter table public.knowledge_chunks
    add constraint knowledge_chunks_canonical_reference_year check (
        canonical_reference_year is null
        or canonical_reference_year between 1900 and 2100
    );

create index if not exists knowledge_chunks_reference_year_idx
    on public.knowledge_chunks (
        canonical_reference_year,
        document_id,
        document_version_id
    )
    where canonical_reference_year is not null;

-- Sparse and dense search retain their public signatures. P6 adds only
-- backward-compatible filter keys and enriches the returned metadata object.
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
            'department_code', 'project_code', 'year', 'reference_years',
            'year_from', 'year_to', 'effective_at', 'effective_status'
        )
    ) then
        raise exception 'Unsupported canonical metadata filter'
            using errcode = '22023';
    end if;
    if p_filters ? 'reference_years' and (
        jsonb_typeof(p_filters -> 'reference_years') <> 'array'
        or jsonb_array_length(p_filters -> 'reference_years') not between 1 and 20
        or exists (
            select 1
            from jsonb_array_elements_text(p_filters -> 'reference_years') as year(value)
            where year.value !~ '^(19|20)[0-9]{2}$'
        )
    ) then
        raise exception 'reference_years must contain between 1 and 20 valid years'
            using errcode = '22023';
    end if;

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
        chunks.metadata || jsonb_strip_nulls(jsonb_build_object(
            'parent_id', chunks.parent_id,
            'section_title', chunks.section_title,
            'content_kind', chunks.content_kind,
            'projection_version', projections.projection_version,
            'metadata_revision', projections.source_metadata_revision,
            'normalized_content_hash', chunks.normalized_content_hash,
            'normalization_version', chunks.normalization_version,
            'exact_duplicate_group_id',
                nullif(chunks.metadata ->> 'exact_duplicate_group_id', ''),
            'canonical_reference_year', chunks.canonical_reference_year,
            'reference_year', chunks.canonical_reference_year,
            'document_status', lower(documents.status),
            'version_number', versions.version_number,
            'effective_from', versions.effective_date,
            'effective_to', versions.effective_to,
            'effective_status', public.enterprise_effective_status(
                versions.effective_date,
                versions.effective_to,
                current_date
            ),
            'is_current', case
                when public.enterprise_effective_status(
                    versions.effective_date,
                    versions.effective_to,
                    current_date
                ) = 'CURRENT' then true
                when versions.effective_date is null and versions.effective_to is null
                    then null
                else false
            end,
            'original_file_name', files.original_file_name,
            'embedding_metadata_stale',
                projections.embedding_metadata_revision
                <> documents.metadata_revision
        )),
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
    join public.source_files as files on files.id = versions.source_file_id
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
          or chunks.canonical_reference_year = (p_filters ->> 'year')::integer
      )
      and (
          not (p_filters ? 'reference_years')
          or chunks.canonical_reference_year in (
              select year.value::integer
              from jsonb_array_elements_text(
                  p_filters -> 'reference_years'
              ) as year(value)
          )
      )
      and (
          not (p_filters ? 'year_from')
          or chunks.canonical_reference_year >= (p_filters ->> 'year_from')::integer
      )
      and (
          not (p_filters ? 'year_to')
          or chunks.canonical_reference_year <= (p_filters ->> 'year_to')::integer
      )
      and (
          not (p_filters ? 'effective_at')
          or (
              (versions.effective_date is null
               or versions.effective_date <= (p_filters ->> 'effective_at')::date)
              and (versions.effective_to is null
                   or versions.effective_to >= (p_filters ->> 'effective_at')::date)
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
            'department_code', 'project_code', 'year', 'reference_years',
            'year_from', 'year_to', 'effective_at', 'effective_status'
        )
    ) then
        raise exception 'Unsupported canonical metadata filter'
            using errcode = '22023';
    end if;
    if p_filters ? 'reference_years' and (
        jsonb_typeof(p_filters -> 'reference_years') <> 'array'
        or jsonb_array_length(p_filters -> 'reference_years') not between 1 and 20
        or exists (
            select 1
            from jsonb_array_elements_text(p_filters -> 'reference_years') as year(value)
            where year.value !~ '^(19|20)[0-9]{2}$'
        )
    ) then
        raise exception 'reference_years must contain between 1 and 20 valid years'
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
        chunks.metadata || jsonb_strip_nulls(jsonb_build_object(
            'parent_id', chunks.parent_id,
            'section_title', chunks.section_title,
            'content_kind', chunks.content_kind,
            'projection_version', projections.projection_version,
            'metadata_revision', projections.source_metadata_revision,
            'normalized_content_hash', chunks.normalized_content_hash,
            'normalization_version', chunks.normalization_version,
            'exact_duplicate_group_id',
                nullif(chunks.metadata ->> 'exact_duplicate_group_id', ''),
            'canonical_reference_year', chunks.canonical_reference_year,
            'reference_year', chunks.canonical_reference_year,
            'document_status', lower(documents.status),
            'version_number', versions.version_number,
            'effective_from', versions.effective_date,
            'effective_to', versions.effective_to,
            'effective_status', public.enterprise_effective_status(
                versions.effective_date,
                versions.effective_to,
                current_date
            ),
            'is_current', case
                when public.enterprise_effective_status(
                    versions.effective_date,
                    versions.effective_to,
                    current_date
                ) = 'CURRENT' then true
                when versions.effective_date is null and versions.effective_to is null
                    then null
                else false
            end,
            'original_file_name', files.original_file_name,
            'embedding_metadata_stale',
                projections.embedding_metadata_revision
                <> documents.metadata_revision
        )),
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
    join public.source_files as files on files.id = versions.source_file_id
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
          or chunks.canonical_reference_year = (p_filters ->> 'year')::integer
      )
      and (
          not (p_filters ? 'reference_years')
          or chunks.canonical_reference_year in (
              select year.value::integer
              from jsonb_array_elements_text(
                  p_filters -> 'reference_years'
              ) as year(value)
          )
      )
      and (
          not (p_filters ? 'year_from')
          or chunks.canonical_reference_year >= (p_filters ->> 'year_from')::integer
      )
      and (
          not (p_filters ? 'year_to')
          or chunks.canonical_reference_year <= (p_filters ->> 'year_to')::integer
      )
      and (
          not (p_filters ? 'effective_at')
          or (
              (versions.effective_date is null
               or versions.effective_date <= (p_filters ->> 'effective_at')::date)
              and (versions.effective_to is null
                   or versions.effective_to >= (p_filters ->> 'effective_at')::date)
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
    order by projections.embedding operator(public.<=>) p_query_embedding,
        chunks.id
    limit greatest(1, least(coalesce(p_limit, 20), 200));
end;
$$;

revoke all on function public.search_enterprise_retrieval_projection(
    text, integer, jsonb
) from public, anon;
grant execute on function public.search_enterprise_retrieval_projection(
    text, integer, jsonb
) to authenticated, service_role;

revoke all on function public.match_enterprise_retrieval_projection(
    vector, integer, jsonb
) from public, anon;
grant execute on function public.match_enterprise_retrieval_projection(
    vector, integer, jsonb
) to authenticated, service_role;

comment on function public.enterprise_chunk_reference_year(jsonb) is
    'Returns the canonical claim/chunk reference year without treating effective date as universal reference time.';
comment on function public.search_enterprise_retrieval_projection(
    text, integer, jsonb
) is
    'P6 ACL-gated sparse Enterprise retrieval with canonical reference-year filters and duplicate/relation-ready metadata.';
comment on function public.match_enterprise_retrieval_projection(
    vector, integer, jsonb
) is
    'P6 ACL-gated dense Enterprise retrieval with canonical reference-year filters and duplicate/relation-ready metadata.';
