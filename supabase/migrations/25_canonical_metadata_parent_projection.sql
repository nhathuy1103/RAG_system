-- Canonical document metadata, evidence assertions, persisted parents and
-- rebuildable retrieval projections. Run after 24_legacy_notebook_enterprise_bridge.sql.

create extension if not exists unaccent with schema extensions;

alter table public.knowledge_documents
    add column if not exists document_number_normalized text,
    add column if not exists domain text,
    add column if not exists project_code text,
    add column if not exists department_code text,
    add column if not exists visibility text not null default 'INTERNAL',
    add column if not exists metadata_revision bigint not null default 1,
    add column if not exists deleted_at timestamptz;

alter table public.knowledge_documents
    drop constraint if exists knowledge_documents_visibility;
alter table public.knowledge_documents
    add constraint knowledge_documents_visibility check (
        visibility in ('PRIVATE', 'INTERNAL', 'RESTRICTED', 'PUBLIC')
    );
alter table public.knowledge_documents
    drop constraint if exists knowledge_documents_metadata_revision;
alter table public.knowledge_documents
    add constraint knowledge_documents_metadata_revision check (metadata_revision > 0);

alter table public.document_versions
    add column if not exists version_label text,
    add column if not exists effective_to date,
    add column if not exists canonical_content_hash text,
    add column if not exists language text,
    add column if not exists page_count integer,
    add column if not exists parser_name text,
    add column if not exists parser_version text,
    add column if not exists ocr_engine text,
    add column if not exists ocr_version text,
    add column if not exists chunker_name text,
    add column if not exists chunker_version text,
    add column if not exists embedding_model text,
    add column if not exists embedding_dimensions integer,
    add column if not exists metadata_revision bigint not null default 1,
    add column if not exists ingested_at timestamptz;

alter table public.document_versions
    drop constraint if exists document_versions_effective_range;
alter table public.document_versions
    add constraint document_versions_effective_range check (
        effective_date is null or effective_to is null or effective_date <= effective_to
    );
alter table public.document_versions
    drop constraint if exists document_versions_page_count;
alter table public.document_versions
    add constraint document_versions_page_count check (page_count is null or page_count >= 0);
alter table public.document_versions
    drop constraint if exists document_versions_embedding_dimensions;
alter table public.document_versions
    add constraint document_versions_embedding_dimensions check (
        embedding_dimensions is null or embedding_dimensions > 0
    );

create or replace function public.normalize_search_text(p_value text)
returns text
language sql
immutable
set search_path = ''
as $$
    select btrim(regexp_replace(
        replace(
            translate(
                coalesce(p_value, ''),
                chr(173) || chr(8203) || chr(8204) || chr(8205) || chr(65279),
                ''
            ),
            chr(160),
            ' '
        ),
        '[[:space:]]+',
        ' ',
        'g'
    ));
$$;

create or replace function public.fold_vietnamese_text(p_value text)
returns text
language sql
stable
set search_path = ''
as $$
    select lower(extensions.unaccent(public.normalize_search_text(coalesce(p_value, ''))));
$$;

create or replace function public.normalize_document_number(p_value text)
returns text
language sql
stable
set search_path = ''
as $$
    select regexp_replace(public.fold_vietnamese_text(p_value), '[^a-z0-9]+', '', 'g');
$$;

create table if not exists public.retrieval_projection_refresh_queue (
    document_id uuid primary key references public.knowledge_documents (id) on delete cascade,
    requested_metadata_revision bigint not null,
    requested_at timestamptz not null default now(),
    processed_at timestamptz,
    last_error text,
    constraint retrieval_projection_refresh_revision check (requested_metadata_revision > 0)
);

create or replace function public.prepare_knowledge_document_metadata()
returns trigger
language plpgsql
set search_path = ''
as $$
begin
    new.document_number_normalized := nullif(
        public.normalize_document_number(new.document_number),
        ''
    );
    if tg_op = 'UPDATE' and row(
        new.document_number, new.title, new.document_type, new.category,
        new.domain, new.project_code, new.department_code, new.owner_department_id,
        new.visibility, new.current_version_id, new.status, new.deleted_at
    ) is distinct from row(
        old.document_number, old.title, old.document_type, old.category,
        old.domain, old.project_code, old.department_code, old.owner_department_id,
        old.visibility, old.current_version_id, old.status, old.deleted_at
    ) then
        new.metadata_revision := old.metadata_revision + 1;
    end if;
    return new;
end;
$$;

drop trigger if exists knowledge_documents_prepare_metadata
on public.knowledge_documents;
create trigger knowledge_documents_prepare_metadata
before insert or update on public.knowledge_documents
for each row execute function public.prepare_knowledge_document_metadata();

create or replace function public.queue_retrieval_projection_refresh()
returns trigger
language plpgsql
security definer
set search_path = ''
as $$
begin
    if tg_op = 'INSERT' or new.metadata_revision is distinct from old.metadata_revision then
        insert into public.retrieval_projection_refresh_queue (
            document_id, requested_metadata_revision, requested_at, processed_at, last_error
        ) values (new.id, new.metadata_revision, now(), null, null)
        on conflict (document_id) do update
        set requested_metadata_revision = excluded.requested_metadata_revision,
            requested_at = excluded.requested_at,
            processed_at = null,
            last_error = null;
    end if;
    return new;
end;
$$;

drop trigger if exists knowledge_documents_queue_projection_refresh
on public.knowledge_documents;
create trigger knowledge_documents_queue_projection_refresh
after insert or update on public.knowledge_documents
for each row execute function public.queue_retrieval_projection_refresh();

-- Backfill normalization without pretending that missing business metadata is known.
update public.knowledge_documents
set document_number_normalized = nullif(
    public.normalize_document_number(document_number),
    ''
)
where document_number_normalized is distinct from nullif(
    public.normalize_document_number(document_number),
    ''
);

create index if not exists knowledge_documents_number_route_idx
    on public.knowledge_documents (document_number_normalized)
    where deleted_at is null and document_number_normalized is not null;
create index if not exists knowledge_documents_retrieval_scope_v2_idx
    on public.knowledge_documents (
        status, current_version_id, document_type, department_code, project_code
    ) where deleted_at is null;

create table if not exists public.knowledge_parent_chunks (
    id uuid primary key,
    document_id uuid not null,
    document_version_id uuid not null,
    parent_index integer not null,
    heading text,
    section_path text[] not null default '{}',
    content text not null,
    content_summary text,
    page_start integer,
    page_end integer,
    source_block_ids text[] not null default '{}',
    token_count integer not null,
    content_hash text not null,
    metadata_revision bigint not null default 1,
    created_at timestamptz not null default now(),
    constraint knowledge_parent_chunks_version_document_fk
        foreign key (document_version_id, document_id)
        references public.document_versions (id, document_id) on delete cascade,
    constraint knowledge_parent_chunks_id_version_document_key
        unique (id, document_version_id, document_id),
    constraint knowledge_parent_chunks_version_index_key
        unique (document_version_id, parent_index),
    constraint knowledge_parent_chunks_content check (char_length(btrim(content)) > 0),
    constraint knowledge_parent_chunks_token_count check (token_count > 0),
    constraint knowledge_parent_chunks_page_range check (
        (page_start is null or page_start > 0)
        and (page_end is null or page_end > 0)
        and (page_start is null or page_end is null or page_start <= page_end)
    ),
    constraint knowledge_parent_chunks_metadata_revision check (metadata_revision > 0)
);

alter table public.knowledge_chunks
    add column if not exists parent_id uuid,
    add column if not exists parent_chunk_index integer,
    add column if not exists content_kind text,
    add column if not exists section_title text,
    add column if not exists char_start integer,
    add column if not exists char_end integer,
    add column if not exists source_block_ids text[] not null default '{}',
    add column if not exists language text,
    add column if not exists metadata_revision bigint not null default 1;

do $$
begin
    if not exists (
        select 1 from pg_constraint
        where conrelid = 'public.knowledge_chunks'::regclass
          and conname = 'knowledge_chunks_parent_same_version_fk'
    ) then
        alter table public.knowledge_chunks
            add constraint knowledge_chunks_parent_same_version_fk
            foreign key (parent_id, document_version_id, document_id)
            references public.knowledge_parent_chunks (
                id, document_version_id, document_id
            ) on delete restrict;
    end if;
end;
$$;

alter table public.knowledge_chunks
    drop constraint if exists knowledge_chunks_character_range;
alter table public.knowledge_chunks
    add constraint knowledge_chunks_character_range check (
        (char_start is null or char_start >= 0)
        and (char_end is null or char_end >= 0)
        and (char_start is null or char_end is null or char_start <= char_end)
    );

create index if not exists knowledge_parent_chunks_document_version_idx
    on public.knowledge_parent_chunks (document_id, document_version_id, parent_index);
create index if not exists knowledge_chunks_parent_child_idx
    on public.knowledge_chunks (parent_id, parent_chunk_index, chunk_index)
    where parent_id is not null;
create index if not exists knowledge_chunks_metadata_revision_idx
    on public.knowledge_chunks (document_id, metadata_revision);

create table if not exists public.document_metadata_assertions (
    id uuid primary key default gen_random_uuid(),
    document_id uuid not null references public.knowledge_documents (id) on delete cascade,
    document_version_id uuid references public.document_versions (id) on delete cascade,
    field_name text not null,
    value text not null,
    normalized_value text not null,
    source_type text not null,
    confidence double precision not null,
    verification_status text not null default 'UNVERIFIED',
    evidence jsonb not null default '[]'::jsonb,
    model text,
    prompt_version text,
    input_checksum text,
    assertion_hash text generated always as (
        encode(public.knowledge_digest(
            pg_catalog.convert_to(
                field_name || chr(31) || normalized_value || chr(31) ||
                source_type || chr(31) || coalesce(prompt_version, ''),
                'UTF8'
            ),
            'sha256'
        ), 'hex')
    ) stored,
    created_at timestamptz not null default now(),
    verified_by uuid references auth.users (id) on delete set null,
    verified_at timestamptz,
    rejection_reason text,
    constraint document_metadata_assertions_source check (
        source_type in (
            'user_confirmed', 'system_record', 'filename_extracted',
            'content_extracted', 'rule_inferred', 'llm_inferred'
        )
    ),
    constraint document_metadata_assertions_confidence check (
        confidence >= 0 and confidence <= 1
    ),
    constraint document_metadata_assertions_verification check (
        verification_status in ('UNVERIFIED', 'VERIFIED', 'REJECTED')
    ),
    constraint document_metadata_assertions_evidence check (
        jsonb_typeof(evidence) = 'array'
    ),
    constraint document_metadata_assertions_unique
        unique (document_id, document_version_id, assertion_hash)
);

create index if not exists document_metadata_assertions_review_idx
    on public.document_metadata_assertions (
        verification_status, field_name, created_at desc
    );
create index if not exists document_metadata_assertions_document_idx
    on public.document_metadata_assertions (document_id, document_version_id, field_name);

create table if not exists public.chunk_retrieval_projections (
    chunk_id uuid primary key references public.knowledge_chunks (id) on delete cascade,
    document_id uuid not null,
    document_version_id uuid not null,
    parent_id uuid,
    projection_version text not null,
    identity_text text not null default '',
    structure_text text not null default '',
    content_text text not null,
    context_text text not null default '',
    alias_text text not null default '',
    embedding_text text not null,
    search_vector_original tsvector not null,
    search_vector_folded tsvector not null,
    embedding vector(1536),
    embedding_model text not null,
    embedding_dimensions integer not null,
    normalization_version text not null,
    source_content_hash text not null,
    source_metadata_revision bigint not null,
    embedding_metadata_revision bigint not null,
    indexed_at timestamptz not null default now(),
    index_status text not null default 'READY',
    constraint chunk_retrieval_projections_chunk_version_document_fk
        foreign key (chunk_id, document_version_id, document_id)
        references public.knowledge_chunks (id, document_version_id, document_id)
        on delete cascade,
    constraint chunk_retrieval_projections_parent_fk
        foreign key (parent_id, document_version_id, document_id)
        references public.knowledge_parent_chunks (id, document_version_id, document_id)
        on delete restrict,
    constraint chunk_retrieval_projections_dimensions check (embedding_dimensions > 0),
    constraint chunk_retrieval_projections_revision check (source_metadata_revision > 0),
    constraint chunk_retrieval_projections_embedding_revision check (
        embedding_metadata_revision > 0
    ),
    constraint chunk_retrieval_projections_status check (
        index_status in ('READY', 'STALE', 'FAILED')
    )
);

create index if not exists chunk_retrieval_projection_scope_idx
    on public.chunk_retrieval_projections (
        document_id, document_version_id, parent_id, indexed_at desc
    );
create index if not exists chunk_retrieval_projection_original_idx
    on public.chunk_retrieval_projections using gin (search_vector_original);
create index if not exists chunk_retrieval_projection_folded_idx
    on public.chunk_retrieval_projections using gin (search_vector_folded);
create index if not exists chunk_retrieval_projection_embedding_hnsw_idx
    on public.chunk_retrieval_projections using hnsw (embedding vector_cosine_ops);
create index if not exists chunk_retrieval_projection_freshness_idx
    on public.chunk_retrieval_projections (
        document_id, source_metadata_revision, embedding_metadata_revision
    );

create or replace function public.refresh_document_lexical_projection()
returns trigger
language plpgsql
security definer
set search_path = ''
as $$
begin
    if new.metadata_revision is distinct from old.metadata_revision then
        update public.chunk_retrieval_projections as projections
        set identity_text = coalesce(new.document_number, ''),
            context_text = concat_ws(' ',
                new.title,
                chunks.section_path,
                chunks.contextual_content
            ),
            search_vector_original =
                setweight(to_tsvector('simple', public.normalize_search_text(
                    concat_ws(' ', new.document_number, projections.structure_text)
                )), 'A')
                || setweight(to_tsvector('simple', public.normalize_search_text(
                    projections.content_text
                )), 'B')
                || setweight(to_tsvector('simple', public.normalize_search_text(
                    concat_ws(' ', new.title, chunks.section_path,
                        chunks.contextual_content)
                )), 'C')
                || setweight(to_tsvector('simple', public.normalize_search_text(
                    concat_ws(' ', new.document_type, new.domain,
                        projections.alias_text)
                )), 'D'),
            search_vector_folded =
                setweight(to_tsvector('simple', public.fold_vietnamese_text(
                    concat_ws(' ', new.document_number, projections.structure_text)
                )), 'A')
                || setweight(to_tsvector('simple', public.fold_vietnamese_text(
                    projections.content_text
                )), 'B')
                || setweight(to_tsvector('simple', public.fold_vietnamese_text(
                    concat_ws(' ', new.title, chunks.section_path,
                        chunks.contextual_content)
                )), 'C')
                || setweight(to_tsvector('simple', public.fold_vietnamese_text(
                    concat_ws(' ', new.document_type, new.domain,
                        projections.alias_text)
                )), 'D'),
            source_metadata_revision = new.metadata_revision,
            indexed_at = now()
        from public.knowledge_chunks as chunks
        where chunks.id = projections.chunk_id
          and projections.document_id = new.id;
    end if;
    return new;
end;
$$;

drop trigger if exists knowledge_documents_refresh_lexical_projection
on public.knowledge_documents;
create trigger knowledge_documents_refresh_lexical_projection
after update of metadata_revision on public.knowledge_documents
for each row execute function public.refresh_document_lexical_projection();

-- The v1 completion RPC remains for old workers. New workers use this wrapper;
-- the call and all derived writes are one transaction, so a projection failure
-- rolls back the underlying completion as well.
create or replace function public.complete_processing_job_v2(
    p_job_id uuid,
    p_worker_id text,
    p_claim_token uuid,
    p_chunks jsonb default null
)
returns public.processing_jobs
language plpgsql
security definer
set search_path = ''
as $$
declare
    selected_job public.processing_jobs;
    selected_version public.document_versions;
    selected_document public.knowledge_documents;
    completed_job public.processing_jobs;
    version_artifact jsonb;
begin
    if auth.role() <> 'service_role' then
        raise exception 'Service role required' using errcode = '42501';
    end if;
    select * into selected_job from public.processing_jobs where id = p_job_id;
    if selected_job.id is null then
        raise exception 'Processing job not found' using errcode = 'P0002';
    end if;
    select * into selected_version
    from public.document_versions where id = selected_job.document_version_id;
    select * into selected_document
    from public.knowledge_documents where id = selected_version.document_id;

    completed_job := public.complete_processing_job(
        p_job_id, p_worker_id, p_claim_token, p_chunks
    );
    if p_chunks is null then
        return completed_job;
    end if;

    select chunk.value -> 'version_artifact' into version_artifact
    from jsonb_array_elements(p_chunks) as chunk(value)
    where jsonb_typeof(chunk.value -> 'version_artifact') = 'object'
    limit 1;
    if version_artifact is not null then
        update public.document_versions
        set canonical_content_hash = nullif(version_artifact ->> 'canonical_content_hash', ''),
            language = nullif(version_artifact ->> 'language', ''),
            page_count = nullif(version_artifact ->> 'page_count', '')::integer,
            parser_name = nullif(version_artifact ->> 'parser_name', ''),
            parser_version = nullif(version_artifact ->> 'parser_version', ''),
            ocr_engine = nullif(version_artifact ->> 'ocr_engine', ''),
            ocr_version = nullif(version_artifact ->> 'ocr_version', ''),
            chunker_name = nullif(version_artifact ->> 'chunker_name', ''),
            chunker_version = nullif(version_artifact ->> 'chunker_version', ''),
            embedding_model = nullif(version_artifact ->> 'embedding_model', ''),
            embedding_dimensions = nullif(
                version_artifact ->> 'embedding_dimensions', ''
            )::integer,
            ingested_at = now(),
            metadata_revision = metadata_revision + 1
        where id = selected_version.id;
    end if;

    delete from public.knowledge_parent_chunks
    where document_version_id = selected_version.id;

    insert into public.knowledge_parent_chunks (
        id, document_id, document_version_id, parent_index, heading,
        section_path, content, content_summary, page_start, page_end,
        source_block_ids, token_count, content_hash, metadata_revision
    )
    select distinct on ((parent.value ->> 'parent_id')::uuid)
        (parent.value ->> 'parent_id')::uuid,
        selected_document.id,
        selected_version.id,
        (row_number() over (order by (chunk.value ->> 'chunk_index')::integer) - 1)::integer,
        nullif(parent.value ->> 'heading', ''),
        coalesce(array(
            select jsonb_array_elements_text(parent.value -> 'section_path')
        ), '{}'),
        parent.value ->> 'content',
        nullif(parent.value ->> 'content_summary', ''),
        nullif(parent.value ->> 'page_start', '')::integer,
        nullif(parent.value ->> 'page_end', '')::integer,
        coalesce(array(
            select jsonb_array_elements_text(parent.value -> 'source_block_ids')
        ), '{}'),
        greatest(coalesce((parent.value ->> 'token_count')::integer, 1), 1),
        lower(parent.value ->> 'content_hash'),
        selected_document.metadata_revision
    from jsonb_array_elements(p_chunks) as chunk(value)
    cross join lateral (select chunk.value -> 'parent' as value) as parent
    where jsonb_typeof(parent.value) = 'object'
      and nullif(parent.value ->> 'parent_id', '') is not null
      and nullif(btrim(parent.value ->> 'content'), '') is not null
    order by (parent.value ->> 'parent_id')::uuid,
             (chunk.value ->> 'chunk_index')::integer;

    update public.knowledge_chunks as chunks
    set parent_id = nullif(item.value #>> '{projection,parent_id}', '')::uuid,
        parent_chunk_index = nullif(
            item.value #>> '{projection,parent_child_index}', ''
        )::integer,
        content_kind = nullif(
            coalesce(
                item.value #>> '{metadata,retrieval_metadata,content_kind}',
                item.value #>> '{metadata,content_kind}'
            ), ''
        ),
        section_title = nullif(
            coalesce(
                item.value #>> '{metadata,retrieval_metadata,section_title}',
                item.value #>> '{metadata,section_title}'
            ), ''
        ),
        char_start = nullif(item.value #>> '{metadata,char_start}', '')::integer,
        char_end = nullif(item.value #>> '{metadata,char_end}', '')::integer,
        source_block_ids = coalesce(array(
            select jsonb_array_elements_text(
                coalesce(item.value #> '{metadata,source_block_ids}', '[]'::jsonb)
            )
        ), '{}'),
        language = nullif(
            coalesce(
                item.value #>> '{metadata,retrieval_metadata,language}',
                selected_version.language
            ), ''
        ),
        metadata_revision = selected_document.metadata_revision,
        metadata = chunks.metadata
            - 'parent_context'
            - 'embedding_text'
            - 'search_text'
    from jsonb_array_elements(p_chunks) as item(value)
    where chunks.id = (item.value ->> 'id')::uuid
      and chunks.document_version_id = selected_version.id;

    insert into public.document_metadata_assertions (
        document_id, document_version_id, field_name, value, normalized_value,
        source_type, confidence, verification_status, evidence, model,
        prompt_version, input_checksum
    )
    select
        selected_document.id,
        selected_version.id,
        assertion.value ->> 'field_name',
        assertion.value ->> 'value',
        assertion.value ->> 'normalized_value',
        assertion.value ->> 'source',
        least(greatest((assertion.value ->> 'confidence')::double precision, 0), 1),
        case when coalesce((assertion.value ->> 'verified')::boolean, false)
             then 'VERIFIED' else 'UNVERIFIED' end,
        coalesce(assertion.value -> 'evidence', '[]'::jsonb),
        nullif(assertion.value ->> 'model', ''),
        nullif(assertion.value ->> 'prompt_version', ''),
        nullif(assertion.value ->> 'input_checksum', '')
    from jsonb_array_elements(p_chunks) as chunk(value)
    cross join lateral jsonb_array_elements(
        coalesce(chunk.value -> 'document_metadata_assertions', '[]'::jsonb)
    ) as assertion(value)
    where jsonb_typeof(assertion.value) = 'object'
      and assertion.value ->> 'source' = 'llm_inferred'
      and coalesce((assertion.value ->> 'verified')::boolean, false) = false
    on conflict (document_id, document_version_id, assertion_hash) do nothing;

    insert into public.chunk_retrieval_projections (
        chunk_id, document_id, document_version_id, parent_id,
        projection_version, identity_text, structure_text, content_text,
        context_text, alias_text, embedding_text,
        search_vector_original, search_vector_folded, embedding,
        embedding_model, embedding_dimensions, normalization_version,
        source_content_hash, source_metadata_revision,
        embedding_metadata_revision, indexed_at, index_status
    )
    select
        chunks.id,
        selected_document.id,
        selected_version.id,
        chunks.parent_id,
        coalesce(nullif(item.value #>> '{projection,projection_version}', ''),
                 'retrieval-projection-v1'),
        coalesce(selected_document.document_number, ''),
        coalesce(item.value #>> '{projection,structure_text}', ''),
        chunks.content,
        concat_ws(' ', selected_document.title, chunks.section_path,
            chunks.contextual_content),
        coalesce(item.value #>> '{projection,alias_text}', ''),
        coalesce(nullif(item.value #>> '{projection,embedding_text}', ''), chunks.content),
        setweight(to_tsvector('simple', public.normalize_search_text(concat_ws(' ',
            selected_document.document_number,
            item.value #>> '{projection,structure_text}'
        ))), 'A')
        || setweight(to_tsvector('simple', public.normalize_search_text(chunks.content)), 'B')
        || setweight(to_tsvector('simple', public.normalize_search_text(concat_ws(' ',
            selected_document.title,
            chunks.section_path,
            chunks.contextual_content
        ))), 'C')
        || setweight(to_tsvector('simple', public.normalize_search_text(concat_ws(' ',
            selected_document.document_type, selected_document.domain,
            item.value #>> '{projection,alias_text}'
        ))), 'D'),
        setweight(to_tsvector('simple', public.fold_vietnamese_text(concat_ws(' ',
            selected_document.document_number,
            item.value #>> '{projection,structure_text}'
        ))), 'A')
        || setweight(to_tsvector('simple', public.fold_vietnamese_text(chunks.content)), 'B')
        || setweight(to_tsvector('simple', public.fold_vietnamese_text(concat_ws(' ',
            selected_document.title,
            chunks.section_path,
            chunks.contextual_content
        ))), 'C')
        || setweight(to_tsvector('simple', public.fold_vietnamese_text(concat_ws(' ',
            selected_document.document_type, selected_document.domain,
            item.value #>> '{projection,alias_text}'
        ))), 'D'),
        chunks.embedding,
        coalesce(nullif(item.value #>> '{projection,embedding_model}', ''),
                 selected_version.embedding_model, 'unknown'),
        coalesce(nullif(item.value #>> '{projection,embedding_dimensions}', '')::integer,
                 selected_version.embedding_dimensions, 1536),
        coalesce(nullif(item.value #>> '{projection,normalization_version}', ''), 'unknown'),
        coalesce(nullif(item.value #>> '{projection,source_content_hash}', ''),
                 chunks.content_hash, encode(public.knowledge_digest(
                     pg_catalog.convert_to(chunks.content, 'UTF8'),
                     'sha256'
                 ), 'hex')),
        selected_document.metadata_revision,
        selected_document.metadata_revision,
        now(),
        'READY'
    from jsonb_array_elements(p_chunks) as item(value)
    join public.knowledge_chunks as chunks
      on chunks.id = (item.value ->> 'id')::uuid
     and chunks.document_version_id = selected_version.id
    where jsonb_typeof(item.value -> 'projection') = 'object'
    on conflict (chunk_id) do update
    set parent_id = excluded.parent_id,
        projection_version = excluded.projection_version,
        identity_text = excluded.identity_text,
        structure_text = excluded.structure_text,
        content_text = excluded.content_text,
        context_text = excluded.context_text,
        alias_text = excluded.alias_text,
        embedding_text = excluded.embedding_text,
        search_vector_original = excluded.search_vector_original,
        search_vector_folded = excluded.search_vector_folded,
        embedding = excluded.embedding,
        embedding_model = excluded.embedding_model,
        embedding_dimensions = excluded.embedding_dimensions,
        normalization_version = excluded.normalization_version,
        source_content_hash = excluded.source_content_hash,
        source_metadata_revision = excluded.source_metadata_revision,
        embedding_metadata_revision = excluded.embedding_metadata_revision,
        indexed_at = excluded.indexed_at,
        index_status = excluded.index_status;

    update public.retrieval_projection_refresh_queue
    set processed_at = now(), last_error = null
    where document_id = selected_document.id
      and requested_metadata_revision <= selected_document.metadata_revision;
    return completed_job;
end;
$$;

revoke all on function public.complete_processing_job_v2(uuid, text, uuid, jsonb)
from public, anon, authenticated;
grant execute on function public.complete_processing_job_v2(uuid, text, uuid, jsonb)
to service_role;

create or replace function public.search_enterprise_retrieval_projection(
    p_query text,
    p_limit integer default 20,
    p_filters jsonb default '{}'::jsonb
)
returns table (
    chunk_id uuid, document_id uuid, document_version_id uuid, title text,
    chunk_index integer, content text, page_start integer, page_end integer,
    section_path text, metadata jsonb, score double precision
)
language plpgsql stable security definer set search_path = ''
as $$
declare
    actor uuid := auth.uid();
    original_query tsquery;
    folded_query tsquery;
begin
    if actor is null or not public.has_functional_permission(actor, 'ASK_KNOWLEDGE') then
        raise exception 'Knowledge search is not permitted' using errcode = '42501';
    end if;
    if p_query is null or btrim(p_query) = '' then return; end if;
    if p_filters is null or jsonb_typeof(p_filters) <> 'object' then
        raise exception 'Filters must be a JSON object' using errcode = '22023';
    end if;
    if exists (
        select 1 from jsonb_object_keys(p_filters) as filter_key(value)
        where filter_key.value not in (
            'document_id', 'document_type', 'category', 'domain',
            'department_code', 'project_code', 'year', 'effective_at'
        )
    ) then
        raise exception 'Unsupported canonical metadata filter' using errcode = '22023';
    end if;
    original_query := websearch_to_tsquery('simple', public.normalize_search_text(p_query));
    folded_query := websearch_to_tsquery('simple', public.fold_vietnamese_text(p_query));
    if numnode(original_query) = 0 and numnode(folded_query) = 0 then return; end if;
    return query
    select chunks.id, documents.id, versions.id, documents.title,
        chunks.chunk_index, chunks.content, chunks.page_start, chunks.page_end,
        chunks.section_path,
        chunks.metadata || jsonb_build_object(
            'parent_id', chunks.parent_id,
            'section_title', chunks.section_title,
            'content_kind', chunks.content_kind,
            'projection_version', projections.projection_version,
            'metadata_revision', projections.source_metadata_revision,
            'embedding_metadata_stale',
                projections.embedding_metadata_revision <> documents.metadata_revision
        ),
        (
            0.80 * ts_rank_cd(projections.search_vector_original, original_query, 32)
            + 0.20 * ts_rank_cd(projections.search_vector_folded, folded_query, 32)
        )::double precision
    from public.chunk_retrieval_projections as projections
    join public.knowledge_chunks as chunks on chunks.id = projections.chunk_id
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
      and public.has_document_permission(actor, documents.id, 'READ')
      and (
          projections.search_vector_original @@ original_query
          or projections.search_vector_folded @@ folded_query
      )
      and (not (p_filters ? 'document_id')
           or documents.id = (p_filters ->> 'document_id')::uuid)
      and (not (p_filters ? 'document_type')
           or documents.document_type = upper(p_filters ->> 'document_type'))
      and (not (p_filters ? 'department_code')
           or documents.department_code = upper(p_filters ->> 'department_code'))
      and (not (p_filters ? 'project_code')
           or documents.project_code = upper(p_filters ->> 'project_code'))
      and (not (p_filters ? 'category')
           or documents.category = p_filters ->> 'category')
      and (not (p_filters ? 'domain')
           or documents.domain = p_filters ->> 'domain')
      and (not (p_filters ? 'year')
           or extract(year from versions.effective_date)::integer =
              (p_filters ->> 'year')::integer)
      and (not (p_filters ? 'effective_at') or (
           versions.effective_date <= (p_filters ->> 'effective_at')::date
           and (
               versions.effective_to is null
               or versions.effective_to >= (p_filters ->> 'effective_at')::date
           )
      ))
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
    chunk_id uuid, document_id uuid, document_version_id uuid, title text,
    chunk_index integer, content text, page_start integer, page_end integer,
    section_path text, metadata jsonb, score double precision
)
language plpgsql stable security definer set search_path = ''
as $$
declare actor uuid := auth.uid();
begin
    if actor is null or not public.has_functional_permission(actor, 'ASK_KNOWLEDGE') then
        raise exception 'Knowledge search is not permitted' using errcode = '42501';
    end if;
    if p_query_embedding is null then
        raise exception 'Query embedding is required' using errcode = '22023';
    end if;
    if p_filters is null or jsonb_typeof(p_filters) <> 'object' then
        raise exception 'Filters must be a JSON object' using errcode = '22023';
    end if;
    if exists (
        select 1 from jsonb_object_keys(p_filters) as filter_key(value)
        where filter_key.value not in (
            'document_id', 'document_type', 'category', 'domain',
            'department_code', 'project_code', 'year', 'effective_at'
        )
    ) then
        raise exception 'Unsupported canonical metadata filter' using errcode = '22023';
    end if;
    return query
    select chunks.id, documents.id, versions.id, documents.title,
        chunks.chunk_index, chunks.content, chunks.page_start, chunks.page_end,
        chunks.section_path,
        chunks.metadata || jsonb_build_object(
            'parent_id', chunks.parent_id,
            'section_title', chunks.section_title,
            'content_kind', chunks.content_kind,
            'projection_version', projections.projection_version,
            'metadata_revision', projections.source_metadata_revision,
            'embedding_metadata_stale',
                projections.embedding_metadata_revision <> documents.metadata_revision
        ),
        (1 - (projections.embedding OPERATOR(public.<=>) p_query_embedding))::double precision
    from public.chunk_retrieval_projections as projections
    join public.knowledge_chunks as chunks on chunks.id = projections.chunk_id
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
      and public.has_document_permission(actor, documents.id, 'READ')
      and (not (p_filters ? 'document_id')
           or documents.id = (p_filters ->> 'document_id')::uuid)
      and (not (p_filters ? 'document_type')
           or documents.document_type = upper(p_filters ->> 'document_type'))
      and (not (p_filters ? 'department_code')
           or documents.department_code = upper(p_filters ->> 'department_code'))
      and (not (p_filters ? 'project_code')
           or documents.project_code = upper(p_filters ->> 'project_code'))
      and (not (p_filters ? 'category')
           or documents.category = p_filters ->> 'category')
      and (not (p_filters ? 'domain')
           or documents.domain = p_filters ->> 'domain')
      and (not (p_filters ? 'year')
           or extract(year from versions.effective_date)::integer =
              (p_filters ->> 'year')::integer)
      and (not (p_filters ? 'effective_at') or (
           versions.effective_date <= (p_filters ->> 'effective_at')::date
           and (
               versions.effective_to is null
               or versions.effective_to >= (p_filters ->> 'effective_at')::date
           )
      ))
    order by projections.embedding OPERATOR(public.<=>) p_query_embedding
    limit greatest(1, least(coalesce(p_limit, 20), 200));
end;
$$;

create or replace function public.resolve_enterprise_document_number(p_document_number text)
returns table (document_id uuid, document_version_id uuid, title text)
language sql stable security definer set search_path = ''
as $$
    select documents.id, versions.id, documents.title
    from public.knowledge_documents as documents
    join public.document_versions as versions
      on versions.id = documents.current_version_id
     and versions.document_id = documents.id
    where auth.uid() is not null
      and public.has_functional_permission(auth.uid(), 'ASK_KNOWLEDGE')
      and documents.status = 'PUBLISHED'
      and documents.deleted_at is null
      and versions.status = 'ACTIVE'
      and documents.document_number_normalized =
          public.normalize_document_number(p_document_number)
      and public.has_document_permission(auth.uid(), documents.id, 'READ')
    order by documents.id;
$$;

create or replace function public.expand_enterprise_chunk_context(
    p_chunk_ids uuid[],
    p_sibling_window integer default 1,
    p_limit integer default 30
)
returns table (
    chunk_id uuid, document_id uuid, document_version_id uuid, title text,
    chunk_index integer, content text, page_start integer, page_end integer,
    section_path text, metadata jsonb, score double precision
)
language plpgsql stable security definer set search_path = ''
as $$
declare actor uuid := auth.uid();
begin
    if actor is null or not public.has_functional_permission(actor, 'ASK_KNOWLEDGE') then
        raise exception 'Knowledge search is not permitted' using errcode = '42501';
    end if;
    if p_chunk_ids is null or cardinality(p_chunk_ids) = 0 then return; end if;
    return query
    with matched as (
        select chunks.id, chunks.parent_id, chunks.parent_chunk_index, chunks.chunk_index,
               chunks.document_id, chunks.document_version_id
        from public.knowledge_chunks as chunks
        where chunks.id = any(p_chunk_ids)
    ), expanded as (
        select distinct on (siblings.id)
            siblings.id,
            matched.id as matched_id,
            case when siblings.id = matched.id then 1.0 else 0.5 end as expansion_score
        from matched
        join public.knowledge_chunks as siblings
          on siblings.document_id = matched.document_id
         and siblings.document_version_id = matched.document_version_id
         and (
             siblings.id = matched.id
             or (
                 siblings.parent_id = matched.parent_id
                 and matched.parent_id is not null
                 and abs(coalesce(siblings.parent_chunk_index, siblings.chunk_index)
                       - coalesce(matched.parent_chunk_index, matched.chunk_index))
                     <= greatest(0, least(coalesce(p_sibling_window, 1), 3))
             )
         )
        order by siblings.id, expansion_score desc
    )
    select chunks.id, documents.id, versions.id, documents.title,
        chunks.chunk_index, chunks.content, chunks.page_start, chunks.page_end,
        chunks.section_path,
        chunks.metadata || jsonb_build_object(
            'parent_id', chunks.parent_id,
            'parent_heading', parents.heading,
            'parent_summary', parents.content_summary,
            'expanded_from_chunk_id', expanded.matched_id,
            'expansion_kind', case when chunks.id = expanded.matched_id
                                   then 'matched' else 'sibling' end
        ),
        expanded.expansion_score::double precision
    from expanded
    join public.knowledge_chunks as chunks on chunks.id = expanded.id
    left join public.knowledge_parent_chunks as parents on parents.id = chunks.parent_id
    join public.document_versions as versions
      on versions.id = chunks.document_version_id
     and versions.document_id = chunks.document_id
    join public.knowledge_documents as documents
      on documents.id = versions.document_id
     and documents.current_version_id = versions.id
    where documents.status = 'PUBLISHED'
      and documents.deleted_at is null
      and versions.status = 'ACTIVE'
      and public.has_document_permission(actor, documents.id, 'READ')
    order by expanded.expansion_score desc, chunks.chunk_index, chunks.id
    limit greatest(1, least(coalesce(p_limit, 30), 100));
end;
$$;

create or replace function public.review_document_metadata_assertion(
    p_assertion_id uuid,
    p_decision text,
    p_rejection_reason text default null
)
returns public.document_metadata_assertions
language plpgsql
security definer
set search_path = ''
as $$
declare
    actor uuid := auth.uid();
    decision text := upper(btrim(coalesce(p_decision, '')));
    selected_assertion public.document_metadata_assertions;
begin
    if actor is null
       or not public.has_functional_permission(actor, 'REVIEW_DOCUMENT') then
        raise exception 'Document metadata review is not permitted'
            using errcode = '42501';
    end if;
    if decision not in ('VERIFIED', 'REJECTED') then
        raise exception 'Decision must be VERIFIED or REJECTED'
            using errcode = '22023';
    end if;

    select * into selected_assertion
    from public.document_metadata_assertions
    where id = p_assertion_id
    for update;
    if selected_assertion.id is null then
        raise exception 'Metadata assertion not found' using errcode = 'P0002';
    end if;
    if not (
        public.has_document_permission(actor, selected_assertion.document_id, 'REVIEW')
        or public.has_document_permission(actor, selected_assertion.document_id, 'MANAGE')
    ) then
        raise exception 'Document metadata review is not permitted'
            using errcode = '42501';
    end if;
    if selected_assertion.verification_status <> 'UNVERIFIED' then
        raise exception 'Metadata assertion has already been reviewed'
            using errcode = '40001';
    end if;
    if decision = 'REJECTED' and nullif(btrim(p_rejection_reason), '') is null then
        raise exception 'A rejection reason is required' using errcode = '22023';
    end if;

    if decision = 'VERIFIED' then
        if selected_assertion.field_name in (
            'document_number', 'document_type', 'category', 'domain',
            'project_code', 'department_code'
        ) then
            update public.knowledge_documents
            set document_number = case when selected_assertion.field_name = 'document_number'
                    then selected_assertion.value else document_number end,
                document_type = case when selected_assertion.field_name = 'document_type'
                    then upper(selected_assertion.normalized_value) else document_type end,
                category = case when selected_assertion.field_name = 'category'
                    then selected_assertion.normalized_value else category end,
                domain = case when selected_assertion.field_name = 'domain'
                    then selected_assertion.normalized_value else domain end,
                project_code = case when selected_assertion.field_name = 'project_code'
                    then upper(selected_assertion.normalized_value) else project_code end,
                department_code = case when selected_assertion.field_name = 'department_code'
                    then upper(selected_assertion.normalized_value) else department_code end,
                updated_at = now()
            where id = selected_assertion.document_id;
        elsif selected_assertion.field_name in ('effective_from', 'effective_to') then
            if selected_assertion.document_version_id is null then
                raise exception 'Version-bound metadata assertion is required'
                    using errcode = '23514';
            end if;
            update public.document_versions
            set effective_date = case
                    when selected_assertion.field_name = 'effective_from'
                    then selected_assertion.normalized_value::date else effective_date end,
                effective_to = case
                    when selected_assertion.field_name = 'effective_to'
                    then selected_assertion.normalized_value::date else effective_to end,
                metadata_revision = metadata_revision + 1
            where id = selected_assertion.document_version_id
              and document_id = selected_assertion.document_id;
        else
            raise exception 'Unsupported canonical metadata field'
                using errcode = '22023';
        end if;
    end if;

    update public.document_metadata_assertions
    set verification_status = decision,
        verified_by = actor,
        verified_at = now(),
        rejection_reason = case when decision = 'REJECTED'
            then btrim(p_rejection_reason) else null end
    where id = selected_assertion.id
    returning * into selected_assertion;

    perform public.write_enterprise_audit(
        'DOCUMENT_METADATA_ASSERTION_' || decision,
        'document_metadata_assertion',
        selected_assertion.id,
        jsonb_build_object('verification_status', 'UNVERIFIED'),
        to_jsonb(selected_assertion),
        p_rejection_reason
    );
    return selected_assertion;
end;
$$;

revoke all on function public.search_enterprise_retrieval_projection(text, integer, jsonb)
from public, anon;
revoke all on function public.match_enterprise_retrieval_projection(vector, integer, jsonb)
from public, anon;
revoke all on function public.resolve_enterprise_document_number(text)
from public, anon;
revoke all on function public.expand_enterprise_chunk_context(uuid[], integer, integer)
from public, anon;
revoke all on function public.review_document_metadata_assertion(uuid, text, text)
from public, anon;
grant execute on function public.search_enterprise_retrieval_projection(text, integer, jsonb)
to authenticated, service_role;
grant execute on function public.match_enterprise_retrieval_projection(vector, integer, jsonb)
to authenticated, service_role;
grant execute on function public.resolve_enterprise_document_number(text)
to authenticated, service_role;
grant execute on function public.expand_enterprise_chunk_context(uuid[], integer, integer)
to authenticated, service_role;
grant execute on function public.review_document_metadata_assertion(uuid, text, text)
to authenticated, service_role;

alter table public.knowledge_parent_chunks enable row level security;
alter table public.knowledge_parent_chunks force row level security;
alter table public.document_metadata_assertions enable row level security;
alter table public.document_metadata_assertions force row level security;
alter table public.chunk_retrieval_projections enable row level security;
alter table public.chunk_retrieval_projections force row level security;
alter table public.retrieval_projection_refresh_queue enable row level security;
alter table public.retrieval_projection_refresh_queue force row level security;

revoke all on table public.document_metadata_assertions from anon, authenticated;
grant select on table public.document_metadata_assertions to authenticated;

create policy knowledge_parent_chunks_select_access
on public.knowledge_parent_chunks for select to authenticated
using (public.is_enterprise_document_retrievable(
    (select auth.uid()), document_id, document_version_id
));
create policy chunk_retrieval_projections_select_access
on public.chunk_retrieval_projections for select to authenticated
using (public.is_enterprise_document_retrievable(
    (select auth.uid()), document_id, document_version_id
));
create policy document_metadata_assertions_select_manager
on public.document_metadata_assertions for select to authenticated
using (
    public.has_document_permission((select auth.uid()), document_id, 'MANAGE')
    or public.has_document_permission((select auth.uid()), document_id, 'REVIEW')
);

comment on table public.document_metadata_assertions is
    'Append-only metadata candidates with source, confidence and exact evidence. LLM rows stay UNVERIFIED until explicit review.';
comment on table public.chunk_retrieval_projections is
    'Rebuildable read model; never authoritative for ACL, lifecycle or business metadata.';
comment on function public.search_enterprise_retrieval_projection(text, integer, jsonb) is
    'PostgreSQL FTS using ts_rank_cd, not BM25. ACL/current lifecycle predicates are authoritative joins.';
