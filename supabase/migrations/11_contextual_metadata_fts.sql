-- Context-weighted PostgreSQL full-text retrieval over canonical chunk content.
-- Run after 10_chunk_preembedding_dedup.sql.

-- Chunks indexed before contextual metadata existed still need a stable title.
-- Preserve every existing retrieval field and fill only a missing/blank title
-- from the authoritative documents row.
update public.document_chunks as chunks
set metadata = jsonb_set(
    chunks.metadata,
    '{retrieval_metadata}',
    jsonb_set(
        case
            when jsonb_typeof(chunks.metadata -> 'retrieval_metadata') = 'object'
            then chunks.metadata -> 'retrieval_metadata'
            else '{}'::jsonb
        end,
        '{title}',
        to_jsonb(
            coalesce(
                nullif(chunks.metadata #>> '{retrieval_metadata,title}', ''),
                nullif(chunks.metadata ->> 'title', ''),
                documents.original_filename
            )
        ),
        true
    ),
    true
)
from public.documents as documents
where documents.id = chunks.document_id
  and documents.owner_id = chunks.owner_id
  and documents.notebook_id = chunks.notebook_id
  and coalesce(
      chunks.metadata #>> '{retrieval_metadata,title}',
      chunks.metadata ->> 'title',
      ''
  ) = '';

alter table public.document_chunks
    add column if not exists search_vector tsvector
    generated always as (
        setweight(
            to_tsvector(
                'simple'::regconfig,
                coalesce(
                    metadata #>> '{retrieval_metadata,title}',
                    metadata ->> 'title',
                    ''
                )
            ),
            'A'
        )
        || setweight(
            to_tsvector(
                'simple'::regconfig,
                coalesce(
                    metadata #>> '{retrieval_metadata,section_title}',
                    metadata ->> 'section_title',
                    ''
                )
            ),
            'B'
        )
        || setweight(
            to_tsvector(
                'simple'::regconfig,
                coalesce(
                    metadata #>> '{retrieval_metadata,section_path}',
                    ''
                )
            ),
            'B'
        )
        || setweight(
            to_tsvector(
                'simple'::regconfig,
                coalesce(
                    metadata #>> '{retrieval_metadata,table_header}',
                    ''
                )
            ),
            'B'
        )
        || setweight(
            to_tsvector(
                'simple'::regconfig,
                coalesce(
                    metadata #>> '{retrieval_metadata,document_type}',
                    metadata ->> 'document_type',
                    ''
                )
            ),
            'C'
        )
        || setweight(
            to_tsvector(
                'simple'::regconfig,
                coalesce(
                    metadata #>> '{retrieval_metadata,content_kind}',
                    metadata ->> 'content_kind',
                    ''
                )
            ),
            'C'
        )
        || setweight(
            to_tsvector(
                'simple'::regconfig,
                coalesce(
                    metadata #>> '{retrieval_metadata,keyword_aliases}',
                    ''
                )
            ),
            'C'
        )
        || setweight(to_tsvector('simple'::regconfig, content), 'D')
    ) stored;

create index if not exists document_chunks_search_vector_idx
    on public.document_chunks using gin (search_vector);

create or replace function public.search_document_chunks_keyword(
    p_query text,
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
    normalized_content_hash text,
    exact_duplicate_group_id uuid,
    score double precision
)
language plpgsql
stable
security definer
set search_path = ''
as $$
declare
    search_query tsquery;
begin
    if auth.role() <> 'service_role'
       and auth.uid() is distinct from p_owner_id then
        raise exception 'Cannot retrieve another owner''s document chunks'
            using errcode = '42501';
    end if;

    if p_query is null or btrim(p_query) = '' then
        return;
    end if;
    search_query := websearch_to_tsquery('simple'::regconfig, btrim(p_query));
    if numnode(search_query) = 0 then
        return;
    end if;

    return query
    select
        chunks.id,
        chunks.document_id,
        case
            when chunks.metadata ->> 'document_version' ~ '^[1-9][0-9]*$'
            then (chunks.metadata ->> 'document_version')::integer
            else 1
        end,
        chunks.chunk_index,
        chunks.content,
        chunks.metadata,
        chunks.normalized_content_hash,
        chunks.exact_duplicate_group_id,
        ts_rank_cd(chunks.search_vector, search_query, 32)::double precision
    from public.document_chunks as chunks
    where chunks.owner_id = p_owner_id
      and (p_notebook_id is null or chunks.notebook_id = p_notebook_id)
      and (p_document_ids is null or chunks.document_id = any(p_document_ids))
      and chunks.search_vector @@ search_query
    order by
        ts_rank_cd(chunks.search_vector, search_query, 32) desc,
        chunks.id
    limit greatest(1, least(coalesce(p_limit, 20), 200));
end;
$$;

revoke all on function public.search_document_chunks_keyword(
    text, uuid, uuid, uuid[], integer
) from public, anon;
grant execute on function public.search_document_chunks_keyword(
    text, uuid, uuid, uuid[], integer
) to authenticated, service_role;
