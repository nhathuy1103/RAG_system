-- Retrieval reliability hardening. Run after
-- 30_auto_publish_processed_documents.sql.
--
-- This migration is deliberately forward-only:
--   * document metadata edits synchronously refresh the lexical projection;
--   * natural-language sparse search has a bounded OR-recall path after
--     removing common Vietnamese/English filler terms;
--   * published INTERNAL/PUBLIC knowledge receives explicit role-subject READ
--     ACLs (authenticated enterprise roles only, never anon/public grants);
--   * authorized users can inspect why a document is or is not searchable.

-- -------------------------------------------------------------------------
-- 1. Make projection revision changes transactional and repair old drift.
-- -------------------------------------------------------------------------

-- PostgreSQL column-specific UPDATE triggers fire when the column is named in
-- the UPDATE statement, not when a BEFORE trigger changes that column.  The
-- old lexical trigger was `AFTER UPDATE OF metadata_revision`, while
-- prepare_knowledge_document_metadata() normally increments the revision from
-- an UPDATE of title/domain/etc.  Merge queueing and lexical refresh into the
-- existing all-column AFTER trigger so the NEW/OLD revision comparison is the
-- single source of truth.
create or replace function public.queue_retrieval_projection_refresh()
returns trigger
language plpgsql
security definer
set search_path = ''
as $$
declare
    expected_current_chunks bigint := 0;
    refreshed_current_chunks bigint := 0;
begin
    if tg_op = 'INSERT'
       or new.metadata_revision is distinct from old.metadata_revision then
        insert into public.retrieval_projection_refresh_queue (
            document_id,
            requested_metadata_revision,
            requested_at,
            processed_at,
            last_error
        ) values (
            new.id,
            new.metadata_revision,
            now(),
            null,
            null
        )
        on conflict (document_id) do update
        set requested_metadata_revision = excluded.requested_metadata_revision,
            requested_at = excluded.requested_at,
            processed_at = null,
            last_error = null;

        if tg_op = 'UPDATE' then
            update public.chunk_retrieval_projections as projections
            set identity_text = coalesce(new.document_number, ''),
                context_text = concat_ws(
                    ' ',
                    new.title,
                    chunks.section_path,
                    chunks.contextual_content
                ),
                search_vector_original =
                    setweight(to_tsvector(
                        'simple',
                        public.normalize_search_text(concat_ws(
                            ' ', new.document_number, projections.structure_text
                        ))
                    ), 'A')
                    || setweight(to_tsvector(
                        'simple',
                        public.normalize_search_text(projections.content_text)
                    ), 'B')
                    || setweight(to_tsvector(
                        'simple',
                        public.normalize_search_text(concat_ws(
                            ' ', new.title, chunks.section_path,
                            chunks.contextual_content
                        ))
                    ), 'C')
                    || setweight(to_tsvector(
                        'simple',
                        public.normalize_search_text(concat_ws(
                            ' ', new.document_type, new.domain,
                            projections.alias_text
                        ))
                    ), 'D'),
                search_vector_folded =
                    setweight(to_tsvector(
                        'simple',
                        public.fold_vietnamese_text(concat_ws(
                            ' ', new.document_number, projections.structure_text
                        ))
                    ), 'A')
                    || setweight(to_tsvector(
                        'simple',
                        public.fold_vietnamese_text(projections.content_text)
                    ), 'B')
                    || setweight(to_tsvector(
                        'simple',
                        public.fold_vietnamese_text(concat_ws(
                            ' ', new.title, chunks.section_path,
                            chunks.contextual_content
                        ))
                    ), 'C')
                    || setweight(to_tsvector(
                        'simple',
                        public.fold_vietnamese_text(concat_ws(
                            ' ', new.document_type, new.domain,
                            projections.alias_text
                        ))
                    ), 'D'),
                source_metadata_revision = new.metadata_revision,
                indexed_at = now()
            from public.knowledge_chunks as chunks
            where chunks.id = projections.chunk_id
              and projections.document_id = new.id;

            if new.current_version_id is not null then
                select count(*)
                into expected_current_chunks
                from public.knowledge_chunks as chunks
                where chunks.document_id = new.id
                  and chunks.document_version_id = new.current_version_id;

                select count(*)
                into refreshed_current_chunks
                from public.knowledge_chunks as chunks
                join public.chunk_retrieval_projections as projections
                  on projections.chunk_id = chunks.id
                 and projections.document_id = chunks.document_id
                 and projections.document_version_id = chunks.document_version_id
                where chunks.document_id = new.id
                  and chunks.document_version_id = new.current_version_id
                  and projections.source_metadata_revision = new.metadata_revision;

                if expected_current_chunks > 0
                   and refreshed_current_chunks = expected_current_chunks then
                    update public.retrieval_projection_refresh_queue
                    set processed_at = now(),
                        last_error = null
                    where document_id = new.id
                      and requested_metadata_revision <= new.metadata_revision;
                else
                    update public.retrieval_projection_refresh_queue
                    set processed_at = null,
                        last_error = format(
                            'Lexical projection coverage mismatch: refreshed %s of %s current chunks',
                            refreshed_current_chunks,
                            expected_current_chunks
                        )
                    where document_id = new.id;
                end if;
            end if;
        end if;
    end if;
    return new;
end;
$$;

revoke all on function public.queue_retrieval_projection_refresh()
from public, anon, authenticated;

-- The queue trigger from migration 25 already fires AFTER INSERT OR UPDATE and
-- calls the function above. Remove the ineffective column-specific duplicate.
drop trigger if exists knowledge_documents_refresh_lexical_projection
on public.knowledge_documents;

-- Rebuild every existing lexical read model from canonical document metadata
-- and immutable chunk text. Embedding revisions are intentionally not forged:
-- SQL cannot recompute a model embedding, and the diagnostic RPC reports that
-- drift separately as a warning.
update public.chunk_retrieval_projections as projections
set identity_text = coalesce(documents.document_number, ''),
    context_text = concat_ws(
        ' ', documents.title, chunks.section_path, chunks.contextual_content
    ),
    search_vector_original =
        setweight(to_tsvector(
            'simple',
            public.normalize_search_text(concat_ws(
                ' ', documents.document_number, projections.structure_text
            ))
        ), 'A')
        || setweight(to_tsvector(
            'simple', public.normalize_search_text(projections.content_text)
        ), 'B')
        || setweight(to_tsvector(
            'simple',
            public.normalize_search_text(concat_ws(
                ' ', documents.title, chunks.section_path,
                chunks.contextual_content
            ))
        ), 'C')
        || setweight(to_tsvector(
            'simple',
            public.normalize_search_text(concat_ws(
                ' ', documents.document_type, documents.domain,
                projections.alias_text
            ))
        ), 'D'),
    search_vector_folded =
        setweight(to_tsvector(
            'simple',
            public.fold_vietnamese_text(concat_ws(
                ' ', documents.document_number, projections.structure_text
            ))
        ), 'A')
        || setweight(to_tsvector(
            'simple', public.fold_vietnamese_text(projections.content_text)
        ), 'B')
        || setweight(to_tsvector(
            'simple',
            public.fold_vietnamese_text(concat_ws(
                ' ', documents.title, chunks.section_path,
                chunks.contextual_content
            ))
        ), 'C')
        || setweight(to_tsvector(
            'simple',
            public.fold_vietnamese_text(concat_ws(
                ' ', documents.document_type, documents.domain,
                projections.alias_text
            ))
        ), 'D'),
    source_metadata_revision = documents.metadata_revision,
    indexed_at = now()
from public.knowledge_chunks as chunks,
     public.knowledge_documents as documents
where chunks.id = projections.chunk_id
  and documents.id = projections.document_id
  and chunks.document_id = documents.id;

-- A current version with complete lexical coverage has consumed its queued
-- revision. Missing chunks/projections remain visibly pending and must be
-- reprocessed rather than being reported as healthy.
update public.retrieval_projection_refresh_queue as queue
set requested_metadata_revision = documents.metadata_revision,
    processed_at = now(),
    last_error = null
from public.knowledge_documents as documents
where documents.id = queue.document_id
  and documents.current_version_id is not null
  and exists (
      select 1
      from public.knowledge_chunks as chunks
      where chunks.document_id = documents.id
        and chunks.document_version_id = documents.current_version_id
  )
  and not exists (
      select 1
      from public.knowledge_chunks as chunks
      left join public.chunk_retrieval_projections as projections
        on projections.chunk_id = chunks.id
       and projections.document_id = chunks.document_id
       and projections.document_version_id = chunks.document_version_id
      where chunks.document_id = documents.id
        and chunks.document_version_id = documents.current_version_id
        and (
            projections.chunk_id is null
            or projections.source_metadata_revision <> documents.metadata_revision
        )
  );

insert into public.retrieval_projection_refresh_queue (
    document_id,
    requested_metadata_revision,
    requested_at,
    processed_at,
    last_error
)
select
    documents.id,
    documents.metadata_revision,
    now(),
    null,
    'Current version is missing a current lexical retrieval projection'
from public.knowledge_documents as documents
where documents.current_version_id is not null
  and (
      not exists (
          select 1
          from public.knowledge_chunks as chunks
          where chunks.document_id = documents.id
            and chunks.document_version_id = documents.current_version_id
      )
      or exists (
          select 1
          from public.knowledge_chunks as chunks
          left join public.chunk_retrieval_projections as projections
            on projections.chunk_id = chunks.id
           and projections.document_id = chunks.document_id
           and projections.document_version_id = chunks.document_version_id
          where chunks.document_id = documents.id
            and chunks.document_version_id = documents.current_version_id
            and (
                projections.chunk_id is null
                or projections.source_metadata_revision
                   <> documents.metadata_revision
            )
      )
  )
on conflict (document_id) do update
set requested_metadata_revision = excluded.requested_metadata_revision,
    requested_at = excluded.requested_at,
    processed_at = null,
    last_error = excluded.last_error;

comment on table public.retrieval_projection_refresh_queue is
    'Tracks transactional lexical projection refresh. processed_at means current lexical coverage; embedding revision drift remains explicit on chunk_retrieval_projections.';

-- -------------------------------------------------------------------------
-- 2. Natural-language sparse recall without an all-terms-mandatory failure.
-- -------------------------------------------------------------------------

create or replace function public.enterprise_recall_search_terms(p_value text)
returns text[]
language sql
stable
set search_path = ''
as $$
    with tokens as (
        select lower(token.value) as term, token.ordinality as position
        from regexp_split_to_table(
            public.normalize_search_text(coalesce(p_value, '')),
            '[^[:alnum:]_]+'
        ) with ordinality as token(value, ordinality)
    ), meaningful as (
        select term, min(position) as first_position
        from tokens
        where char_length(term) >= 2
          and term not in (
              -- Vietnamese, with and without diacritics.
              'các', 'cac', 'những', 'nhung', 'một', 'mot',
              'này', 'nay', 'kia', 'đó', 'do', 'được', 'duoc',
              'bị', 'bi', 'của', 'cua', 'cho', 'về', 've',
              'với', 'voi', 'và', 'va', 'hoặc', 'hoac',
              'hay', 'trong', 'ngoài', 'ngoai', 'trên', 'tren',
              'dưới', 'duoi', 'tại', 'tai', 'từ', 'tu',
              'đến', 'den', 'theo', 'là', 'la', 'hãy', 'hay',
              'vui', 'lòng', 'long', 'tôi', 'toi', 'bạn', 'ban',
              'biết', 'biet', 'gì', 'gi', 'nào', 'nao',
              -- English question/filler words. `an` is intentionally kept:
              -- it is the folded Vietnamese lexeme for "án" in "dự án".
              'the', 'is', 'are', 'was', 'were', 'be', 'been',
              'being', 'of', 'for', 'to', 'in', 'on', 'at', 'by',
              'with', 'and', 'or', 'what', 'which', 'who', 'where',
              'when', 'how', 'please', 'tell', 'me', 'about'
          )
        group by term
    ), bounded as (
        select term, first_position
        from meaningful
        order by first_position, term
        limit 32
    )
    select coalesce(array_agg(term order by first_position, term), '{}'::text[])
    from bounded;
$$;

create or replace function public.enterprise_recall_tsquery(p_value text)
returns tsquery
language sql
stable
set search_path = ''
as $$
    select to_tsquery(
        'simple',
        coalesce(
            nullif(array_to_string(
                public.enterprise_recall_search_terms(p_value),
                ' | '
            ), ''),
            ''
        )
    );
$$;

revoke all on function public.enterprise_recall_search_terms(text)
from public, anon, authenticated;
revoke all on function public.enterprise_recall_tsquery(text)
from public, anon, authenticated;

-- Effective state is a property of the query date, not immutable ingestion
-- metadata. Keep the interval calculation in the database so a document can
-- become CURRENT/EXPIRED without being re-uploaded or re-embedded.
create or replace function public.enterprise_effective_status(
    p_effective_from date,
    p_effective_to date,
    p_as_of date default current_date
)
returns text
language sql
stable
set search_path = ''
as $$
    select case
        when p_effective_from is null and p_effective_to is null then 'UNDATED'
        when p_effective_from is not null and p_effective_from > p_as_of
            then 'SCHEDULED'
        when p_effective_to is not null and p_effective_to < p_as_of
            then 'EXPIRED'
        else 'CURRENT'
    end;
$$;

revoke all on function public.enterprise_effective_status(date, date, date)
from public, anon, authenticated;

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
            'department_code', 'project_code', 'year', 'effective_at',
            'effective_status'
        )
    ) then
        raise exception 'Unsupported canonical metadata filter'
            using errcode = '22023';
    end if;

    -- Preserve the precise all-term/web-search route, then add a bounded OR
    -- route for natural questions. Filler words cannot make every recall
    -- candidate fail, while chunks matching more meaningful terms rank higher.
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
        chunks.metadata || jsonb_build_object(
            'parent_id', chunks.parent_id,
            'section_title', chunks.section_title,
            'content_kind', chunks.content_kind,
            'projection_version', projections.projection_version,
            'metadata_revision', projections.source_metadata_revision,
            'effective_status', public.enterprise_effective_status(
                versions.effective_date,
                versions.effective_to,
                current_date
            ),
            'embedding_metadata_stale',
                projections.embedding_metadata_revision
                <> documents.metadata_revision
        ),
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
          or extract(year from versions.effective_date)::integer
             = (p_filters ->> 'year')::integer
      )
      and (
          not (p_filters ? 'effective_at')
          or (
              (
                  versions.effective_date is null
                  or versions.effective_date
                     <= (p_filters ->> 'effective_at')::date
              )
              and (
                  versions.effective_to is null
                  or versions.effective_to
                     >= (p_filters ->> 'effective_at')::date
              )
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

revoke all on function public.search_enterprise_retrieval_projection(
    text, integer, jsonb
) from public, anon;
grant execute on function public.search_enterprise_retrieval_projection(
    text, integer, jsonb
) to authenticated, service_role;

comment on function public.search_enterprise_retrieval_projection(
    text, integer, jsonb
) is
    'ACL/current-version-gated PostgreSQL FTS with precise websearch ranking plus bounded stopword-filtered OR recall for natural-language questions.';

-- Keep the dense route on exactly the same canonical filter contract. Dense
-- vectors remain usable after a metadata-only edit, but source metadata and
-- lifecycle/ACL joins must be current before a candidate can be returned.
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
            'department_code', 'project_code', 'year', 'effective_at',
            'effective_status'
        )
    ) then
        raise exception 'Unsupported canonical metadata filter'
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
        chunks.metadata || jsonb_build_object(
            'parent_id', chunks.parent_id,
            'section_title', chunks.section_title,
            'content_kind', chunks.content_kind,
            'projection_version', projections.projection_version,
            'metadata_revision', projections.source_metadata_revision,
            'effective_status', public.enterprise_effective_status(
                versions.effective_date,
                versions.effective_to,
                current_date
            ),
            'embedding_metadata_stale',
                projections.embedding_metadata_revision
                <> documents.metadata_revision
        ),
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
          or extract(year from versions.effective_date)::integer
             = (p_filters ->> 'year')::integer
      )
      and (
          not (p_filters ? 'effective_at')
          or (
              (
                  versions.effective_date is null
                  or versions.effective_date
                     <= (p_filters ->> 'effective_at')::date
              )
              and (
                  versions.effective_to is null
                  or versions.effective_to
                     >= (p_filters ->> 'effective_at')::date
              )
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
    order by projections.embedding operator(public.<=>) p_query_embedding
    limit greatest(1, least(coalesce(p_limit, 20), 200));
end;
$$;

revoke all on function public.match_enterprise_retrieval_projection(
    vector, integer, jsonb
) from public, anon;
grant execute on function public.match_enterprise_retrieval_projection(
    vector, integer, jsonb
) to authenticated, service_role;

-- -------------------------------------------------------------------------
-- 3. Organization-readable published knowledge through explicit role ACLs.
-- -------------------------------------------------------------------------

alter table public.document_permissions
    add column if not exists grant_source text not null default 'MANUAL';

alter table public.document_permissions
    drop constraint if exists document_permissions_grant_source;
alter table public.document_permissions
    add constraint document_permissions_grant_source check (
        grant_source in ('MANUAL', 'PUBLISHED_ROLE_DEFAULT')
    );

create index if not exists document_permissions_published_role_default_idx
    on public.document_permissions (document_id, subject_id)
    where status = 'ACTIVE'
      and permission = 'READ'
      and grant_source = 'PUBLISHED_ROLE_DEFAULT';

create or replace function public.sync_published_knowledge_reader_acl()
returns trigger
language plpgsql
security definer
set search_path = ''
as $$
declare
    grant_actor uuid := coalesce(auth.uid(), new.created_by);
begin
    if new.status = 'PUBLISHED'
       and new.deleted_at is null
       and new.visibility in ('INTERNAL', 'PUBLIC') then
        insert into public.document_permissions (
            document_id,
            subject_id,
            permission,
            status,
            granted_by,
            grant_source
        )
        select
            new.id,
            subjects.id,
            'READ',
            'ACTIVE',
            grant_actor,
            'PUBLISHED_ROLE_DEFAULT'
        from public.roles as roles
        join public.access_subjects as subjects
          on subjects.subject_type = 'ROLE'
         and subjects.role_id = roles.id
        join public.role_permissions as role_permissions
          on role_permissions.role_id = roles.id
        join public.functional_permissions as permissions
          on permissions.id = role_permissions.permission_id
         and permissions.code = 'ASK_KNOWLEDGE'
        where roles.status = 'ACTIVE'
        on conflict (
            document_id, subject_id, permission
        ) where status = 'ACTIVE'
        do nothing;
    else
        -- PRIVATE/RESTRICTED, archived, or soft-deleted knowledge remains
        -- explicit-ACL-only. Never revoke a manually assigned role grant.
        update public.document_permissions
        set status = 'REVOKED',
            revoked_by = grant_actor,
            revoked_at = now()
        where document_id = new.id
          and permission = 'READ'
          and status = 'ACTIVE'
          and grant_source = 'PUBLISHED_ROLE_DEFAULT';
    end if;
    return new;
end;
$$;

revoke all on function public.sync_published_knowledge_reader_acl()
from public, anon, authenticated;

drop trigger if exists knowledge_documents_sync_published_reader_acl
on public.knowledge_documents;
create trigger knowledge_documents_sync_published_reader_acl
after insert or update of status, visibility, deleted_at
on public.knowledge_documents
for each row execute function public.sync_published_knowledge_reader_acl();

-- Repair already-published documents. Existing manual READ rows win the
-- partial unique conflict and are never relabelled or later auto-revoked.
insert into public.document_permissions (
    document_id,
    subject_id,
    permission,
    status,
    granted_by,
    grant_source
)
select
    documents.id,
    subjects.id,
    'READ',
    'ACTIVE',
    documents.created_by,
    'PUBLISHED_ROLE_DEFAULT'
from public.knowledge_documents as documents
cross join public.roles as roles
join public.access_subjects as subjects
  on subjects.subject_type = 'ROLE'
 and subjects.role_id = roles.id
join public.role_permissions as role_permissions
  on role_permissions.role_id = roles.id
join public.functional_permissions as permissions
  on permissions.id = role_permissions.permission_id
 and permissions.code = 'ASK_KNOWLEDGE'
where documents.status = 'PUBLISHED'
  and documents.deleted_at is null
  and documents.visibility in ('INTERNAL', 'PUBLIC')
  and roles.status = 'ACTIVE'
on conflict (
    document_id, subject_id, permission
) where status = 'ACTIVE'
do nothing;

comment on column public.document_permissions.grant_source is
    'MANUAL grants are administrator-owned. PUBLISHED_ROLE_DEFAULT grants make INTERNAL/PUBLIC published knowledge readable by authenticated ASK_KNOWLEDGE roles and are safely revoked when visibility/lifecycle closes.';

-- -------------------------------------------------------------------------
-- 4. Read-only, authorization-aware searchability diagnostics.
-- -------------------------------------------------------------------------

create or replace function public.get_enterprise_document_searchability(
    p_document_id uuid default null
)
returns table (
    document_id uuid,
    title text,
    document_status text,
    visibility text,
    current_version_id uuid,
    version_status text,
    metadata_revision bigint,
    chunk_count bigint,
    ready_projection_count bigint,
    lexical_ready_projection_count bigint,
    lexical_stale_count bigint,
    embedding_stale_count bigint,
    refresh_requested_revision bigint,
    refresh_processed_at timestamptz,
    refresh_error text,
    searchable_for_actor boolean,
    fully_indexed boolean,
    blocking_reasons text[],
    warnings text[]
)
language plpgsql
stable
security definer
set search_path = ''
as $$
declare
    actor uuid := auth.uid();
    actor_can_ask boolean;
    actor_can_manage_access boolean;
begin
    if actor is null then
        raise exception 'Authentication required' using errcode = '42501';
    end if;

    actor_can_ask := public.has_functional_permission(
        actor, 'ASK_KNOWLEDGE'
    );
    actor_can_manage_access := public.has_functional_permission(
        actor, 'MANAGE_ACCESS_POLICY'
    );

    return query
    select
        documents.id,
        documents.title,
        documents.status,
        documents.visibility,
        documents.current_version_id,
        versions.status,
        documents.metadata_revision,
        coverage.chunk_count,
        coverage.ready_projection_count,
        coverage.lexical_ready_projection_count,
        coverage.lexical_stale_count,
        coverage.embedding_stale_count,
        queue.requested_metadata_revision,
        queue.processed_at,
        queue.last_error,
        (
            documents.status = 'PUBLISHED'
            and documents.deleted_at is null
            and versions.status = 'ACTIVE'
            and actor_can_ask
            and access.can_read
            and coverage.lexical_ready_projection_count > 0
        ),
        (
            coverage.chunk_count > 0
            and coverage.ready_projection_count = coverage.chunk_count
            and coverage.lexical_ready_projection_count = coverage.chunk_count
            and coverage.lexical_stale_count = 0
        ),
        array_remove(array[
            case when documents.status <> 'PUBLISHED'
                 then 'DOCUMENT_NOT_PUBLISHED' end,
            case when documents.deleted_at is not null
                 then 'DOCUMENT_DELETED' end,
            case when documents.current_version_id is null
                 then 'NO_CURRENT_VERSION' end,
            case when versions.status is distinct from 'ACTIVE'
                 then 'VERSION_NOT_ACTIVE' end,
            case when not actor_can_ask
                 then 'ASK_KNOWLEDGE_DENIED' end,
            case when not access.can_read
                 then 'READ_DENIED' end,
            case when coverage.chunk_count = 0
                 then 'NO_CHUNKS' end,
            case when coverage.ready_projection_count = 0
                 then 'NO_READY_PROJECTIONS' end,
            case when coverage.lexical_stale_count > 0
                 then 'LEXICAL_PROJECTION_STALE' end
        ], null)::text[],
        array_remove(array[
            case when coverage.embedding_stale_count > 0
                 then 'EMBEDDING_METADATA_STALE' end,
            case when queue.document_id is not null
                       and queue.processed_at is null
                 then 'PROJECTION_REFRESH_PENDING' end,
            case when queue.last_error is not null
                 then 'PROJECTION_REFRESH_ERROR' end
        ], null)::text[]
    from public.knowledge_documents as documents
    left join public.document_versions as versions
      on versions.id = documents.current_version_id
     and versions.document_id = documents.id
    left join public.retrieval_projection_refresh_queue as queue
      on queue.document_id = documents.id
    cross join lateral (
        select
            public.has_document_permission(
                actor, documents.id, 'READ'
            ) as can_read,
            public.has_document_permission(
                actor, documents.id, 'MANAGE'
            ) as can_manage
    ) as access
    cross join lateral (
        select
            count(chunks.id) as chunk_count,
            count(chunks.id) filter (
                where projections.index_status = 'READY'
            ) as ready_projection_count,
            count(chunks.id) filter (
                where projections.index_status = 'READY'
                  and projections.source_metadata_revision
                      = documents.metadata_revision
            ) as lexical_ready_projection_count,
            count(chunks.id) filter (
                where projections.chunk_id is null
                   or projections.source_metadata_revision
                      <> documents.metadata_revision
            ) as lexical_stale_count,
            count(chunks.id) filter (
                where projections.chunk_id is not null
                  and projections.embedding_metadata_revision
                      <> documents.metadata_revision
            ) as embedding_stale_count
        from public.knowledge_chunks as chunks
        left join public.chunk_retrieval_projections as projections
          on projections.chunk_id = chunks.id
         and projections.document_id = chunks.document_id
         and projections.document_version_id = chunks.document_version_id
        where chunks.document_id = documents.id
          and chunks.document_version_id = documents.current_version_id
    ) as coverage
    where (p_document_id is null or documents.id = p_document_id)
      and (
          access.can_read
          or access.can_manage
          or actor_can_manage_access
      )
    order by documents.updated_at desc, documents.id;
end;
$$;

revoke all on function public.get_enterprise_document_searchability(uuid)
from public, anon, service_role;
grant execute on function public.get_enterprise_document_searchability(uuid)
to authenticated;

comment on function public.get_enterprise_document_searchability(uuid) is
    'Read-only lifecycle/ACL/projection diagnostics for an authorized reader, document manager, or access-policy manager. Returns no chunk content and no hidden document to ordinary users.';
