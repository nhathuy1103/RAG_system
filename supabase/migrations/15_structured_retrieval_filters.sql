-- Persist and apply the measured pre-retrieval metadata filter contract.
-- Run after 14_compact_chunk_metadata.sql.

-- Backfill only values already present or deterministically encoded in a heading.
update public.document_chunks as chunks
set metadata = jsonb_set(
    chunks.metadata,
    '{retrieval_metadata}',
    coalesce(chunks.metadata -> 'retrieval_metadata', '{}'::jsonb)
    || jsonb_strip_nulls(jsonb_build_object(
        'document_type', lower(nullif(coalesce(
            chunks.metadata #>> '{retrieval_metadata,document_type}',
            chunks.metadata ->> 'document_type'
        ), '')),
        'content_kind', lower(nullif(coalesce(
            chunks.metadata #>> '{retrieval_metadata,content_kind}',
            chunks.metadata ->> 'content_kind'
        ), '')),
        'project_id', coalesce(
            chunks.metadata #>> '{retrieval_metadata,project_id}',
            chunks.metadata ->> 'project_id'
        ),
        'project_code', upper(nullif(coalesce(
            chunks.metadata #>> '{retrieval_metadata,project_code}',
            chunks.metadata ->> 'project_code',
            substring(
                coalesce(
                    chunks.metadata #>> '{retrieval_metadata,section_title}',
                    chunks.metadata ->> 'section_title',
                    ''
                )
                from '^\s*(P[0-9]{1,6})'
            )
        ), '')),
        'year', coalesce(
            chunks.metadata #>> '{retrieval_metadata,year}',
            chunks.metadata ->> 'year'
        ),
        'data_period', upper(nullif(coalesce(
            chunks.metadata #>> '{retrieval_metadata,data_period}',
            chunks.metadata ->> 'data_period'
        ), '')),
        'effective_status', case lower(nullif(coalesce(
            chunks.metadata #>> '{retrieval_metadata,effective_status}',
            chunks.metadata ->> 'effective_status'
        ), ''))
            when 'latest' then 'current'
            when 'active' then 'current'
            when 'effective' then 'current'
            else lower(nullif(coalesce(
                chunks.metadata #>> '{retrieval_metadata,effective_status}',
                chunks.metadata ->> 'effective_status'
            ), ''))
        end
    )),
    true
)
where jsonb_typeof(chunks.metadata) = 'object';

create index if not exists document_chunks_document_type_filter_idx
    on public.document_chunks (
        owner_id, notebook_id,
        (metadata #>> '{retrieval_metadata,document_type}')
    ) where metadata #>> '{retrieval_metadata,document_type}' is not null;
create index if not exists document_chunks_content_kind_filter_idx
    on public.document_chunks (
        owner_id, notebook_id,
        (metadata #>> '{retrieval_metadata,content_kind}')
    ) where metadata #>> '{retrieval_metadata,content_kind}' is not null;
create index if not exists document_chunks_project_id_filter_idx
    on public.document_chunks (
        owner_id, notebook_id,
        (metadata #>> '{retrieval_metadata,project_id}')
    ) where metadata #>> '{retrieval_metadata,project_id}' is not null;
create index if not exists document_chunks_project_code_filter_idx
    on public.document_chunks (
        owner_id, notebook_id,
        (metadata #>> '{retrieval_metadata,project_code}')
    ) where metadata #>> '{retrieval_metadata,project_code}' is not null;
create index if not exists document_chunks_year_filter_idx
    on public.document_chunks (
        owner_id, notebook_id,
        (metadata #>> '{retrieval_metadata,year}')
    ) where metadata #>> '{retrieval_metadata,year}' is not null;
create index if not exists document_chunks_data_period_filter_idx
    on public.document_chunks (
        owner_id, notebook_id,
        (metadata #>> '{retrieval_metadata,data_period}')
    ) where metadata #>> '{retrieval_metadata,data_period}' is not null;
create index if not exists document_chunks_effective_status_filter_idx
    on public.document_chunks (
        owner_id, notebook_id,
        (metadata #>> '{retrieval_metadata,effective_status}')
    ) where metadata #>> '{retrieval_metadata,effective_status}' is not null;

drop function if exists public.match_document_chunks(
    vector, uuid, uuid, uuid[], integer
);
drop function if exists public.match_document_chunks(
    vector, uuid, uuid, uuid[], integer, text, text, text, text, integer, text, text
);
create function public.match_document_chunks(
    p_query_embedding vector(1536),
    p_owner_id uuid,
    p_notebook_id uuid default null,
    p_document_ids uuid[] default null,
    p_limit integer default 20,
    p_document_type text default null,
    p_content_kind text default null,
    p_project_id text default null,
    p_project_code text default null,
    p_year integer default null,
    p_data_period text default null,
    p_effective_status text default null
)
returns table (
    chunk_id uuid, document_id uuid, document_version integer,
    chunk_index integer, content text, metadata jsonb,
    normalized_content_hash text, exact_duplicate_group_id uuid,
    score double precision
)
language plpgsql stable security definer set search_path = ''
as $$
begin
    if auth.role() <> 'service_role'
       and auth.uid() is distinct from p_owner_id then
        raise exception 'Cannot retrieve another owner''s document chunks'
            using errcode = '42501';
    end if;
    return query
    select chunks.id, chunks.document_id,
        case when chunks.metadata ->> 'document_version' ~ '^[1-9][0-9]*$'
             then (chunks.metadata ->> 'document_version')::integer else 1 end,
        chunks.chunk_index, chunks.content, chunks.metadata,
        chunks.normalized_content_hash, chunks.exact_duplicate_group_id,
        1 - (chunks.embedding OPERATOR(public.<=>) p_query_embedding)
    from public.document_chunks as chunks
    where chunks.owner_id = p_owner_id
      and (p_notebook_id is null or chunks.notebook_id = p_notebook_id)
      and (p_document_ids is null or chunks.document_id = any(p_document_ids))
      and chunks.embedding is not null
      and (p_document_type is null or chunks.metadata #>> '{retrieval_metadata,document_type}' = p_document_type)
      and (p_content_kind is null or chunks.metadata #>> '{retrieval_metadata,content_kind}' = p_content_kind)
      and (p_project_id is null or chunks.metadata #>> '{retrieval_metadata,project_id}' = p_project_id)
      and (p_project_code is null or chunks.metadata #>> '{retrieval_metadata,project_code}' = p_project_code)
      and (p_year is null or chunks.metadata #>> '{retrieval_metadata,year}' = p_year::text)
      and (p_data_period is null or chunks.metadata #>> '{retrieval_metadata,data_period}' = p_data_period)
      and (p_effective_status is null or chunks.metadata #>> '{retrieval_metadata,effective_status}' = p_effective_status)
    order by chunks.embedding OPERATOR(public.<=>) p_query_embedding
    limit greatest(1, least(coalesce(p_limit, 20), 200));
end;
$$;
revoke all on function public.match_document_chunks(
    vector, uuid, uuid, uuid[], integer, text, text, text, text, integer, text, text
) from public, anon;
grant execute on function public.match_document_chunks(
    vector, uuid, uuid, uuid[], integer, text, text, text, text, integer, text, text
) to authenticated, service_role;

drop function if exists public.search_document_chunks_keyword(
    text, uuid, uuid, uuid[], integer
);
drop function if exists public.search_document_chunks_keyword(
    text, uuid, uuid, uuid[], integer, text, text, text, text, integer, text, text
);
create function public.search_document_chunks_keyword(
    p_query text,
    p_owner_id uuid,
    p_notebook_id uuid default null,
    p_document_ids uuid[] default null,
    p_limit integer default 20,
    p_document_type text default null,
    p_content_kind text default null,
    p_project_id text default null,
    p_project_code text default null,
    p_year integer default null,
    p_data_period text default null,
    p_effective_status text default null
)
returns table (
    chunk_id uuid, document_id uuid, document_version integer,
    chunk_index integer, content text, metadata jsonb,
    normalized_content_hash text, exact_duplicate_group_id uuid,
    score double precision
)
language plpgsql stable security definer set search_path = ''
as $$
declare search_query tsquery;
begin
    if auth.role() <> 'service_role'
       and auth.uid() is distinct from p_owner_id then
        raise exception 'Cannot retrieve another owner''s document chunks'
            using errcode = '42501';
    end if;
    if p_query is null or btrim(p_query) = '' then return; end if;
    search_query := websearch_to_tsquery('simple'::regconfig, btrim(p_query));
    if numnode(search_query) = 0 then return; end if;
    return query
    select chunks.id, chunks.document_id,
        case when chunks.metadata ->> 'document_version' ~ '^[1-9][0-9]*$'
             then (chunks.metadata ->> 'document_version')::integer else 1 end,
        chunks.chunk_index, chunks.content, chunks.metadata,
        chunks.normalized_content_hash, chunks.exact_duplicate_group_id,
        ts_rank_cd(chunks.search_vector, search_query, 32)::double precision
    from public.document_chunks as chunks
    where chunks.owner_id = p_owner_id
      and (p_notebook_id is null or chunks.notebook_id = p_notebook_id)
      and (p_document_ids is null or chunks.document_id = any(p_document_ids))
      and (p_document_type is null or chunks.metadata #>> '{retrieval_metadata,document_type}' = p_document_type)
      and (p_content_kind is null or chunks.metadata #>> '{retrieval_metadata,content_kind}' = p_content_kind)
      and (p_project_id is null or chunks.metadata #>> '{retrieval_metadata,project_id}' = p_project_id)
      and (p_project_code is null or chunks.metadata #>> '{retrieval_metadata,project_code}' = p_project_code)
      and (p_year is null or chunks.metadata #>> '{retrieval_metadata,year}' = p_year::text)
      and (p_data_period is null or chunks.metadata #>> '{retrieval_metadata,data_period}' = p_data_period)
      and (p_effective_status is null or chunks.metadata #>> '{retrieval_metadata,effective_status}' = p_effective_status)
      and chunks.search_vector @@ search_query
    order by ts_rank_cd(chunks.search_vector, search_query, 32) desc, chunks.id
    limit greatest(1, least(coalesce(p_limit, 20), 200));
end;
$$;
revoke all on function public.search_document_chunks_keyword(
    text, uuid, uuid, uuid[], integer, text, text, text, text, integer, text, text
) from public, anon;
grant execute on function public.search_document_chunks_keyword(
    text, uuid, uuid, uuid[], integer, text, text, text, text, integer, text, text
) to authenticated, service_role;
