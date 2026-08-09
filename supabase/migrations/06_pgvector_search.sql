-- Dense retrieval RPC (pgvector). Run after 02_tables.sql.

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
language plpgsql
stable
security definer
set search_path = ''
as $$
begin
    if auth.role() <> 'service_role'
       and auth.uid() is distinct from p_owner_id then
        raise exception 'Cannot retrieve another owner''s document chunks'
            using errcode = '42501';
    end if;

    return query
    select
        c.id as chunk_id,
        c.document_id,
        coalesce((c.metadata ->> 'document_version')::integer, 1) as document_version,
        c.chunk_index,
        c.content,
        c.metadata,
        1 - (c.embedding OPERATOR(public.<=>) p_query_embedding) as score
    from public.document_chunks c
    where c.owner_id = p_owner_id
      and (p_notebook_id is null or c.notebook_id = p_notebook_id)
      and c.embedding is not null
      and (p_document_ids is null or c.document_id = any(p_document_ids))
    order by c.embedding OPERATOR(public.<=>) p_query_embedding
    limit greatest(1, least(p_limit, 200));
end;
$$;

revoke all on function public.match_document_chunks(
    vector, uuid, uuid, uuid[], integer
)
from public, anon;
grant execute on function public.match_document_chunks(
    vector, uuid, uuid, uuid[], integer
)
to authenticated, service_role;
