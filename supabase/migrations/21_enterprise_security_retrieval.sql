-- Enterprise RLS and fail-closed retrieval entry points.
-- Run after 20_enterprise_operations.sql.

create or replace function public.is_enterprise_document_retrievable(
    p_user_id uuid,
    p_document_id uuid,
    p_document_version_id uuid
)
returns boolean
language sql
stable
security definer
set search_path = ''
as $$
    select coalesce(exists (
        select 1
        from public.knowledge_documents as documents
        join public.document_versions as versions
          on versions.id = p_document_version_id
         and versions.document_id = documents.id
        where documents.id = p_document_id
          and public.has_functional_permission(p_user_id, 'ASK_KNOWLEDGE')
          and documents.status = 'PUBLISHED'
          and documents.current_version_id = versions.id
          and versions.status = 'ACTIVE'
          and public.has_document_permission(
              p_user_id,
              documents.id,
              'READ'
          )
    ), false);
$$;

revoke all on function public.is_enterprise_document_retrievable(
    uuid, uuid, uuid
) from public, anon;
grant execute on function public.is_enterprise_document_retrievable(
    uuid, uuid, uuid
) to authenticated, service_role;

-- RLS policies must not use caller-filtered subqueries to decide whether an
-- immutable source is already referenced. These SECURITY DEFINER helpers see
-- the authoritative relationship and prevent an uploader from regaining
-- read/delete access merely because the referencing version became hidden.
create or replace function public.is_enterprise_source_file_referenced(
    p_source_file_id uuid
)
returns boolean
language sql
stable
security definer
set search_path = ''
as $$
    select coalesce(exists (
        select 1
        from public.document_versions as versions
        where versions.source_file_id = p_source_file_id
    ), false);
$$;

revoke all on function public.is_enterprise_source_file_referenced(uuid)
from public, anon;
grant execute on function public.is_enterprise_source_file_referenced(uuid)
to authenticated, service_role;

create or replace function public.is_enterprise_storage_object_referenced(
    p_bucket_name text,
    p_object_path text
)
returns boolean
language sql
stable
security definer
set search_path = ''
as $$
    select coalesce(exists (
        select 1
        from public.source_files as files
        join public.document_versions as versions
          on versions.source_file_id = files.id
        where files.bucket_name = p_bucket_name
          and files.object_path = p_object_path
    ), false);
$$;

revoke all on function public.is_enterprise_storage_object_referenced(text, text)
from public, anon;
grant execute on function public.is_enterprise_storage_object_referenced(text, text)
to authenticated, service_role;

-- Deleting an object that already has a source_files row would leave durable
-- metadata pointing at missing bytes even when no document version references
-- it yet. Keep that stronger registration check separate from the version
-- reference helper used by uploader read isolation.
create or replace function public.is_enterprise_storage_object_registered(
    p_bucket_name text,
    p_object_path text
)
returns boolean
language sql
stable
security definer
set search_path = ''
as $$
    select coalesce(exists (
        select 1
        from public.source_files as files
        where files.bucket_name = p_bucket_name
          and files.object_path = p_object_path
    ), false);
$$;

revoke all on function public.is_enterprise_storage_object_registered(text, text)
from public, anon;
grant execute on function public.is_enterprise_storage_object_registered(text, text)
to authenticated, service_role;

create or replace function public.authorized_knowledge_document_ids()
returns table (document_id uuid, document_version_id uuid)
language sql
stable
security definer
set search_path = ''
as $$
    select documents.id, versions.id
    from public.knowledge_documents as documents
    join public.document_versions as versions
      on versions.id = documents.current_version_id
     and versions.document_id = documents.id
    where auth.uid() is not null
      and public.has_functional_permission(auth.uid(), 'ASK_KNOWLEDGE')
      and documents.status = 'PUBLISHED'
      and versions.status = 'ACTIVE'
      and public.has_document_permission(auth.uid(), documents.id, 'READ');
$$;

revoke all on function public.authorized_knowledge_document_ids()
from public, anon;
grant execute on function public.authorized_knowledge_document_ids()
to authenticated;

create or replace function public.match_enterprise_document_chunks(
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
        raise exception 'Knowledge search is not permitted' using errcode = '42501';
    end if;
    if p_query_embedding is null then
        raise exception 'Query embedding is required' using errcode = '22023';
    end if;
    if p_filters is null or jsonb_typeof(p_filters) <> 'object' then
        raise exception 'Filters must be a JSON object' using errcode = '22023';
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
        chunks.metadata,
        1 - (chunks.embedding operator(public.<=>) p_query_embedding)
    from public.knowledge_chunks as chunks
    join public.document_versions as versions
      on versions.id = chunks.document_version_id
     and versions.document_id = chunks.document_id
    join public.knowledge_documents as documents
      on documents.id = versions.document_id
     and documents.current_version_id = versions.id
    where documents.status = 'PUBLISHED'
      and versions.status = 'ACTIVE'
      and chunks.embedding is not null
      and public.has_document_permission(actor, documents.id, 'READ')
      and (
          not (p_filters ? 'document_type')
          or documents.document_type = upper(p_filters ->> 'document_type')
      )
      and (
          not (p_filters ? 'category')
          or documents.category = p_filters ->> 'category'
      )
      and (
          not (p_filters ? 'document_id')
          or documents.id::text = p_filters ->> 'document_id'
      )
      and (
          not (p_filters ? 'metadata')
          or (
              jsonb_typeof(p_filters -> 'metadata') = 'object'
              and documents.metadata @> (p_filters -> 'metadata')
          )
      )
    order by chunks.embedding operator(public.<=>) p_query_embedding, chunks.id
    limit greatest(1, least(coalesce(p_limit, 20), 200));
end;
$$;

revoke all on function public.match_enterprise_document_chunks(
    vector, integer, jsonb
) from public, anon;
grant execute on function public.match_enterprise_document_chunks(
    vector, integer, jsonb
) to authenticated;

create or replace function public.search_enterprise_document_chunks_keyword(
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
    search_query tsquery;
begin
    if actor is null
       or not public.has_functional_permission(actor, 'ASK_KNOWLEDGE') then
        raise exception 'Knowledge search is not permitted' using errcode = '42501';
    end if;
    if p_filters is null or jsonb_typeof(p_filters) <> 'object' then
        raise exception 'Filters must be a JSON object' using errcode = '22023';
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
        documents.id,
        versions.id,
        documents.title,
        chunks.chunk_index,
        chunks.content,
        chunks.page_start,
        chunks.page_end,
        chunks.section_path,
        chunks.metadata,
        ts_rank_cd(chunks.search_vector, search_query, 32)::double precision
    from public.knowledge_chunks as chunks
    join public.document_versions as versions
      on versions.id = chunks.document_version_id
     and versions.document_id = chunks.document_id
    join public.knowledge_documents as documents
      on documents.id = versions.document_id
     and documents.current_version_id = versions.id
    where documents.status = 'PUBLISHED'
      and versions.status = 'ACTIVE'
      and public.has_document_permission(actor, documents.id, 'READ')
      and chunks.search_vector @@ search_query
      and (
          not (p_filters ? 'document_type')
          or documents.document_type = upper(p_filters ->> 'document_type')
      )
      and (
          not (p_filters ? 'category')
          or documents.category = p_filters ->> 'category'
      )
      and (
          not (p_filters ? 'document_id')
          or documents.id::text = p_filters ->> 'document_id'
      )
      and (
          not (p_filters ? 'metadata')
          or (
              jsonb_typeof(p_filters -> 'metadata') = 'object'
              and documents.metadata @> (p_filters -> 'metadata')
          )
      )
    order by
        ts_rank_cd(chunks.search_vector, search_query, 32) desc,
        chunks.id
    limit greatest(1, least(coalesce(p_limit, 20), 200));
end;
$$;

revoke all on function public.search_enterprise_document_chunks_keyword(
    text, integer, jsonb
) from public, anon;
grant execute on function public.search_enterprise_document_chunks_keyword(
    text, integer, jsonb
) to authenticated;

create or replace function public.search_enterprise_knowledge(
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
language sql
stable
security definer
set search_path = ''
as $$
    select *
    from public.search_enterprise_document_chunks_keyword(
        p_query,
        p_limit,
        p_filters
    );
$$;

revoke all on function public.search_enterprise_knowledge(
    text, integer, jsonb
) from public, anon;
grant execute on function public.search_enterprise_knowledge(
    text, integer, jsonb
) to authenticated;

-- -------------------------------------------------------------------------
-- Privileges: anonymous access is denied; mutations of lifecycle and ACL data
-- go through the atomic SECURITY DEFINER operations in migration 20.
-- -------------------------------------------------------------------------

revoke all on table
    public.user_profiles,
    public.roles,
    public.functional_permissions,
    public.user_roles,
    public.role_permissions,
    public.groups,
    public.user_groups,
    public.departments,
    public.user_departments,
    public.access_subjects,
    public.knowledge_documents,
    public.source_files,
    public.document_versions,
    public.document_version_status_history,
    public.document_reviews,
    public.publications,
    public.document_permissions,
    public.processing_jobs,
    public.processing_stage_history,
    public.processing_errors,
    public.knowledge_chunks,
    public.enterprise_conversations,
    public.enterprise_messages,
    public.enterprise_citations,
    public.answer_feedback,
    public.answer_reports,
    public.audit_logs
from anon, authenticated;

-- Root IAM entities have lifecycle status and must be disabled, not deleted.
-- Membership/permission edges remain explicitly removable.
grant select, insert, update on table
    public.roles,
    public.groups,
    public.departments
to authenticated;
grant select, insert, update, delete on table
    public.user_roles,
    public.role_permissions,
    public.user_groups,
    public.user_departments
to authenticated;
grant select on table public.user_profiles to authenticated;
grant select on table public.functional_permissions to authenticated;
grant select on table public.access_subjects to authenticated;
grant select on table
    public.knowledge_documents,
    public.document_versions,
    public.document_version_status_history,
    public.document_reviews,
    public.publications,
    public.document_permissions,
    public.processing_jobs,
    public.processing_stage_history,
    public.processing_errors,
    public.knowledge_chunks,
    public.enterprise_conversations,
    public.enterprise_messages,
    public.enterprise_citations,
    public.audit_logs
to authenticated;
grant select, insert on table public.source_files to authenticated;
grant select, insert, update on table public.answer_feedback to authenticated;
grant select, insert, update on table public.answer_reports to authenticated;

grant all privileges on table
    public.user_profiles,
    public.roles,
    public.functional_permissions,
    public.user_roles,
    public.role_permissions,
    public.groups,
    public.user_groups,
    public.departments,
    public.user_departments,
    public.access_subjects,
    public.knowledge_documents,
    public.source_files,
    public.document_versions,
    public.document_version_status_history,
    public.document_reviews,
    public.publications,
    public.document_permissions,
    public.processing_jobs,
    public.processing_stage_history,
    public.processing_errors,
    public.knowledge_chunks,
    public.enterprise_conversations,
    public.enterprise_messages,
    public.enterprise_citations,
    public.answer_feedback,
    public.answer_reports,
    public.audit_logs
to service_role;

alter table public.user_profiles enable row level security;
alter table public.user_profiles force row level security;
alter table public.roles enable row level security;
alter table public.roles force row level security;
alter table public.functional_permissions enable row level security;
alter table public.functional_permissions force row level security;
alter table public.user_roles enable row level security;
alter table public.user_roles force row level security;
alter table public.role_permissions enable row level security;
alter table public.role_permissions force row level security;
alter table public.groups enable row level security;
alter table public.groups force row level security;
alter table public.user_groups enable row level security;
alter table public.user_groups force row level security;
alter table public.departments enable row level security;
alter table public.departments force row level security;
alter table public.user_departments enable row level security;
alter table public.user_departments force row level security;
alter table public.access_subjects enable row level security;
alter table public.access_subjects force row level security;
alter table public.knowledge_documents enable row level security;
alter table public.knowledge_documents force row level security;
alter table public.source_files enable row level security;
alter table public.source_files force row level security;
alter table public.document_versions enable row level security;
alter table public.document_versions force row level security;
alter table public.document_version_status_history enable row level security;
alter table public.document_version_status_history force row level security;
alter table public.document_reviews enable row level security;
alter table public.document_reviews force row level security;
alter table public.publications enable row level security;
alter table public.publications force row level security;
alter table public.document_permissions enable row level security;
alter table public.document_permissions force row level security;
alter table public.processing_jobs enable row level security;
alter table public.processing_jobs force row level security;
alter table public.processing_stage_history enable row level security;
alter table public.processing_stage_history force row level security;
alter table public.processing_errors enable row level security;
alter table public.processing_errors force row level security;
alter table public.knowledge_chunks enable row level security;
alter table public.knowledge_chunks force row level security;
alter table public.enterprise_conversations enable row level security;
alter table public.enterprise_conversations force row level security;
alter table public.enterprise_messages enable row level security;
alter table public.enterprise_messages force row level security;
alter table public.enterprise_citations enable row level security;
alter table public.enterprise_citations force row level security;
alter table public.answer_feedback enable row level security;
alter table public.answer_feedback force row level security;
alter table public.answer_reports enable row level security;
alter table public.answer_reports force row level security;
alter table public.audit_logs enable row level security;
alter table public.audit_logs force row level security;

-- IAM policies.
drop policy if exists user_profiles_select_enterprise on public.user_profiles;
create policy user_profiles_select_enterprise
on public.user_profiles for select to authenticated
using (
    user_id = (select auth.uid())
    or public.has_functional_permission((select auth.uid()), 'MANAGE_USER')
);
drop policy if exists user_profiles_update_enterprise on public.user_profiles;
create policy user_profiles_update_enterprise
on public.user_profiles for update to authenticated
using (public.has_functional_permission((select auth.uid()), 'MANAGE_USER'))
with check (public.has_functional_permission((select auth.uid()), 'MANAGE_USER'));
drop policy if exists user_profiles_insert_enterprise on public.user_profiles;
create policy user_profiles_insert_enterprise
on public.user_profiles for insert to authenticated
with check (public.has_functional_permission((select auth.uid()), 'MANAGE_USER'));

drop policy if exists roles_select_enterprise on public.roles;
create policy roles_select_enterprise
on public.roles for select to authenticated using (true);
drop policy if exists roles_manage_enterprise on public.roles;
create policy roles_manage_enterprise
on public.roles for all to authenticated
using (public.has_functional_permission((select auth.uid()), 'MANAGE_ROLE'))
with check (public.has_functional_permission((select auth.uid()), 'MANAGE_ROLE'));

drop policy if exists functional_permissions_select_enterprise
on public.functional_permissions;
create policy functional_permissions_select_enterprise
on public.functional_permissions for select to authenticated using (true);

drop policy if exists user_roles_select_enterprise on public.user_roles;
create policy user_roles_select_enterprise
on public.user_roles for select to authenticated
using (
    user_id = (select auth.uid())
    or public.has_functional_permission((select auth.uid()), 'MANAGE_ROLE')
);
drop policy if exists user_roles_manage_enterprise on public.user_roles;
create policy user_roles_manage_enterprise
on public.user_roles for all to authenticated
using (public.has_functional_permission((select auth.uid()), 'MANAGE_ROLE'))
with check (public.has_functional_permission((select auth.uid()), 'MANAGE_ROLE'));

drop policy if exists role_permissions_select_enterprise
on public.role_permissions;
create policy role_permissions_select_enterprise
on public.role_permissions for select to authenticated using (true);
drop policy if exists role_permissions_manage_enterprise
on public.role_permissions;
create policy role_permissions_manage_enterprise
on public.role_permissions for all to authenticated
using (public.has_functional_permission((select auth.uid()), 'MANAGE_ROLE'))
with check (public.has_functional_permission((select auth.uid()), 'MANAGE_ROLE'));

drop policy if exists groups_select_enterprise on public.groups;
create policy groups_select_enterprise
on public.groups for select to authenticated using (true);
drop policy if exists groups_manage_enterprise on public.groups;
create policy groups_manage_enterprise
on public.groups for all to authenticated
using (public.has_functional_permission((select auth.uid()), 'MANAGE_GROUP'))
with check (public.has_functional_permission((select auth.uid()), 'MANAGE_GROUP'));

drop policy if exists user_groups_select_enterprise on public.user_groups;
create policy user_groups_select_enterprise
on public.user_groups for select to authenticated
using (
    user_id = (select auth.uid())
    or public.has_functional_permission((select auth.uid()), 'MANAGE_GROUP')
);
drop policy if exists user_groups_manage_enterprise on public.user_groups;
create policy user_groups_manage_enterprise
on public.user_groups for all to authenticated
using (public.has_functional_permission((select auth.uid()), 'MANAGE_GROUP'))
with check (public.has_functional_permission((select auth.uid()), 'MANAGE_GROUP'));

drop policy if exists departments_select_enterprise on public.departments;
create policy departments_select_enterprise
on public.departments for select to authenticated using (true);
drop policy if exists departments_manage_enterprise on public.departments;
create policy departments_manage_enterprise
on public.departments for all to authenticated
using (public.has_functional_permission((select auth.uid()), 'MANAGE_DEPARTMENT'))
with check (public.has_functional_permission((select auth.uid()), 'MANAGE_DEPARTMENT'));

drop policy if exists user_departments_select_enterprise
on public.user_departments;
create policy user_departments_select_enterprise
on public.user_departments for select to authenticated
using (
    user_id = (select auth.uid())
    or public.has_functional_permission((select auth.uid()), 'MANAGE_DEPARTMENT')
);
drop policy if exists user_departments_manage_enterprise
on public.user_departments;
create policy user_departments_manage_enterprise
on public.user_departments for all to authenticated
using (public.has_functional_permission((select auth.uid()), 'MANAGE_DEPARTMENT'))
with check (public.has_functional_permission((select auth.uid()), 'MANAGE_DEPARTMENT'));

drop policy if exists access_subjects_select_enterprise
on public.access_subjects;
create policy access_subjects_select_enterprise
on public.access_subjects for select to authenticated
using (
    public.has_functional_permission((select auth.uid()), 'MANAGE_ACCESS_POLICY')
);

-- Knowledge/governance policies.  Lifecycle mutation remains RPC-only.
drop policy if exists knowledge_documents_select_access
on public.knowledge_documents;
create policy knowledge_documents_select_access
on public.knowledge_documents for select to authenticated
using (
    (
        status = 'PUBLISHED'
        and current_version_id is not null
        and public.has_document_permission((select auth.uid()), id, 'READ')
    )
    or public.has_document_permission((select auth.uid()), id, 'MANAGE')
    or public.has_document_permission((select auth.uid()), id, 'REVIEW')
    or public.has_document_permission((select auth.uid()), id, 'PUBLISH')
    or public.has_document_permission((select auth.uid()), id, 'ARCHIVE')
    or public.has_document_permission((select auth.uid()), id, 'MANAGE_PERMISSION')
);
drop policy if exists knowledge_documents_update_manager
on public.knowledge_documents;
create policy knowledge_documents_update_manager
on public.knowledge_documents for update to authenticated
using (
    public.has_document_permission((select auth.uid()), id, 'MANAGE')
    and public.has_functional_permission((select auth.uid()), 'MANAGE_DOCUMENT')
)
with check (
    public.has_document_permission((select auth.uid()), id, 'MANAGE')
    and public.has_functional_permission((select auth.uid()), 'MANAGE_DOCUMENT')
);

drop policy if exists source_files_select_access on public.source_files;
create policy source_files_select_access
on public.source_files for select to authenticated
using (
    (
        created_by = (select auth.uid())
        and not public.is_enterprise_source_file_referenced(source_files.id)
        and (
            public.has_functional_permission((select auth.uid()), 'UPLOAD_DOCUMENT')
            or public.has_functional_permission((select auth.uid()), 'MANAGE_DOCUMENT')
        )
    )
    or exists (
        select 1
        from public.document_versions as versions
        join public.knowledge_documents as documents
          on documents.id = versions.document_id
        where versions.source_file_id = source_files.id
          and (
              public.is_enterprise_document_retrievable(
                  (select auth.uid()), documents.id, versions.id
              )
              or (
                  public.has_document_permission(
                      (select auth.uid()), documents.id, 'MANAGE'
                  )
                  and public.has_functional_permission(
                      (select auth.uid()), 'MANAGE_DOCUMENT'
                  )
              )
              or (
                  public.has_document_permission(
                      (select auth.uid()), documents.id, 'REVIEW'
                  )
                  and public.has_functional_permission(
                      (select auth.uid()), 'REVIEW_DOCUMENT'
                  )
              )
              or (
                  public.has_document_permission(
                      (select auth.uid()), documents.id, 'PUBLISH'
                  )
                  and public.has_functional_permission(
                      (select auth.uid()), 'PUBLISH_DOCUMENT'
                  )
              )
          )
    )
);
drop policy if exists source_files_insert_own on public.source_files;
create policy source_files_insert_own
on public.source_files for insert to authenticated
with check (
    created_by = (select auth.uid())
    and (
        public.has_functional_permission((select auth.uid()), 'UPLOAD_DOCUMENT')
        or public.has_functional_permission((select auth.uid()), 'MANAGE_DOCUMENT')
    )
);

drop policy if exists document_versions_select_access
on public.document_versions;
create policy document_versions_select_access
on public.document_versions for select to authenticated
using (
    (
        status = 'ACTIVE'
        and exists (
            select 1
            from public.knowledge_documents as documents
            where documents.id = document_versions.document_id
              and documents.status = 'PUBLISHED'
              and documents.current_version_id = document_versions.id
        )
        and public.has_document_permission((select auth.uid()), document_id, 'READ')
    )
    or public.has_document_permission((select auth.uid()), document_id, 'MANAGE')
    or public.has_document_permission((select auth.uid()), document_id, 'REVIEW')
    or public.has_document_permission((select auth.uid()), document_id, 'PUBLISH')
    or public.has_document_permission((select auth.uid()), document_id, 'ARCHIVE')
);

drop policy if exists document_version_status_history_select_access
on public.document_version_status_history;
create policy document_version_status_history_select_access
on public.document_version_status_history for select to authenticated
using (
    exists (
        select 1 from public.document_versions
        where document_versions.id = document_version_id
          and (
              public.has_document_permission(
                  (select auth.uid()), document_versions.document_id, 'MANAGE'
              )
              or public.has_document_permission(
                  (select auth.uid()), document_versions.document_id, 'REVIEW'
              )
              or public.has_document_permission(
                  (select auth.uid()), document_versions.document_id, 'PUBLISH'
              )
          )
    )
);

drop policy if exists document_reviews_select_access on public.document_reviews;
create policy document_reviews_select_access
on public.document_reviews for select to authenticated
using (
    exists (
        select 1 from public.document_versions
        where document_versions.id = document_version_id
          and (
              public.has_document_permission(
                  (select auth.uid()), document_versions.document_id, 'MANAGE'
              )
              or public.has_document_permission(
                  (select auth.uid()), document_versions.document_id, 'REVIEW'
              )
              or public.has_document_permission(
                  (select auth.uid()), document_versions.document_id, 'PUBLISH'
              )
          )
    )
);

drop policy if exists publications_select_access on public.publications;
create policy publications_select_access
on public.publications for select to authenticated
using (
    public.has_document_permission((select auth.uid()), document_id, 'READ')
);

drop policy if exists document_permissions_select_manager
on public.document_permissions;
create policy document_permissions_select_manager
on public.document_permissions for select to authenticated
using (
    public.has_document_permission(
        (select auth.uid()), document_id, 'MANAGE_PERMISSION'
    )
);

drop policy if exists processing_jobs_select_access on public.processing_jobs;
create policy processing_jobs_select_access
on public.processing_jobs for select to authenticated
using (
    public.has_functional_permission((select auth.uid()), 'MANAGE_DOCUMENT')
    and exists (
        select 1 from public.document_versions
        where document_versions.id = document_version_id
          and public.has_document_permission(
              (select auth.uid()), document_versions.document_id, 'MANAGE'
          )
    )
);

drop policy if exists processing_stage_history_select_access
on public.processing_stage_history;
create policy processing_stage_history_select_access
on public.processing_stage_history for select to authenticated
using (
    public.has_functional_permission((select auth.uid()), 'MANAGE_DOCUMENT')
    and exists (
        select 1
        from public.processing_jobs
        join public.document_versions
          on document_versions.id = processing_jobs.document_version_id
        where processing_jobs.id = processing_job_id
          and public.has_document_permission(
              (select auth.uid()), document_versions.document_id, 'MANAGE'
          )
    )
);

drop policy if exists processing_errors_select_access
on public.processing_errors;
create policy processing_errors_select_access
on public.processing_errors for select to authenticated
using (
    public.has_functional_permission((select auth.uid()), 'MANAGE_DOCUMENT')
    and exists (
        select 1
        from public.processing_jobs
        join public.document_versions
          on document_versions.id = processing_jobs.document_version_id
        where processing_jobs.id = processing_job_id
          and public.has_document_permission(
              (select auth.uid()), document_versions.document_id, 'MANAGE'
          )
    )
);

drop policy if exists knowledge_chunks_select_retrievable
on public.knowledge_chunks;
create policy knowledge_chunks_select_retrievable
on public.knowledge_chunks for select to authenticated
using (
    public.is_enterprise_document_retrievable(
        (select auth.uid()), document_id, document_version_id
    )
);

-- Conversation and response-governance policies.
drop policy if exists enterprise_conversations_select_own
on public.enterprise_conversations;
create policy enterprise_conversations_select_own
on public.enterprise_conversations for select to authenticated
using (
    user_id = (select auth.uid())
    and public.has_functional_permission((select auth.uid()), 'ASK_KNOWLEDGE')
);

drop policy if exists enterprise_messages_select_own
on public.enterprise_messages;

create or replace function public.is_enterprise_message_visible(
    p_user_id uuid,
    p_message_id uuid
)
returns boolean
language sql
stable
security definer
set search_path = ''
as $$
    select coalesce(exists (
        select 1
        from public.enterprise_messages as messages
        join public.enterprise_conversations as conversations
          on conversations.id = messages.conversation_id
        where messages.id = p_message_id
          and conversations.user_id = p_user_id
          and public.has_functional_permission(p_user_id, 'ASK_KNOWLEDGE')
          and (
              messages.role = 'USER'
              or not exists (
                  select 1
                  from public.enterprise_citations as citations
                  where citations.answer_message_id = messages.id
              )
              or not exists (
                  select 1
                  from public.enterprise_citations as citations
                  where citations.answer_message_id = messages.id
                    and not public.is_enterprise_document_retrievable(
                        p_user_id,
                        citations.document_id,
                        citations.document_version_id
                    )
              )
          )
    ), false);
$$;

revoke all on function public.is_enterprise_message_visible(uuid, uuid)
from public, anon;
grant execute on function public.is_enterprise_message_visible(uuid, uuid)
to authenticated, service_role;

create policy enterprise_messages_select_own
on public.enterprise_messages for select to authenticated
using (
    public.is_enterprise_message_visible((select auth.uid()), id)
);

drop policy if exists enterprise_citations_select_own
on public.enterprise_citations;
create policy enterprise_citations_select_own
on public.enterprise_citations for select to authenticated
using (
    exists (
        select 1
        from public.enterprise_messages
        join public.enterprise_conversations
          on enterprise_conversations.id = enterprise_messages.conversation_id
        where enterprise_messages.id = answer_message_id
          and enterprise_conversations.user_id = (select auth.uid())
    )
    and public.is_enterprise_document_retrievable(
        (select auth.uid()), document_id, document_version_id
    )
);

drop policy if exists answer_feedback_select_own_or_governance
on public.answer_feedback;
create policy answer_feedback_select_own_or_governance
on public.answer_feedback for select to authenticated
using (
    (
        user_id = (select auth.uid())
        and public.has_functional_permission((select auth.uid()), 'ASK_KNOWLEDGE')
        and public.is_enterprise_message_visible((select auth.uid()), message_id)
    )
    or public.has_functional_permission((select auth.uid()), 'VIEW_AUDIT')
);
drop policy if exists answer_feedback_insert_own on public.answer_feedback;
create policy answer_feedback_insert_own
on public.answer_feedback for insert to authenticated
with check (
    user_id = (select auth.uid())
    and public.has_functional_permission((select auth.uid()), 'ASK_KNOWLEDGE')
    and public.is_enterprise_message_visible((select auth.uid()), message_id)
    and exists (
        select 1 from public.enterprise_messages
        where enterprise_messages.id = message_id
          and enterprise_messages.role = 'ASSISTANT'
    )
);
drop policy if exists answer_feedback_update_own on public.answer_feedback;
create policy answer_feedback_update_own
on public.answer_feedback for update to authenticated
using (
    user_id = (select auth.uid())
    and public.has_functional_permission((select auth.uid()), 'ASK_KNOWLEDGE')
    and public.is_enterprise_message_visible((select auth.uid()), message_id)
)
with check (
    user_id = (select auth.uid())
    and public.has_functional_permission((select auth.uid()), 'ASK_KNOWLEDGE')
    and public.is_enterprise_message_visible((select auth.uid()), message_id)
    and exists (
        select 1 from public.enterprise_messages
        where enterprise_messages.id = message_id
          and enterprise_messages.role = 'ASSISTANT'
    )
);

drop policy if exists answer_reports_select_own_or_governance
on public.answer_reports;
create policy answer_reports_select_own_or_governance
on public.answer_reports for select to authenticated
using (
    (
        reporter_user_id = (select auth.uid())
        and public.has_functional_permission((select auth.uid()), 'ASK_KNOWLEDGE')
        and public.is_enterprise_message_visible((select auth.uid()), message_id)
    )
    or public.has_functional_permission((select auth.uid()), 'VIEW_AUDIT')
);
drop policy if exists answer_reports_insert_own on public.answer_reports;
create policy answer_reports_insert_own
on public.answer_reports for insert to authenticated
with check (
    reporter_user_id = (select auth.uid())
    and status = 'OPEN'
    and public.has_functional_permission((select auth.uid()), 'ASK_KNOWLEDGE')
    and public.is_enterprise_message_visible((select auth.uid()), message_id)
    and exists (
        select 1 from public.enterprise_messages
        where enterprise_messages.id = message_id
          and enterprise_messages.role = 'ASSISTANT'
    )
);
drop policy if exists answer_reports_update_governance
on public.answer_reports;
create policy answer_reports_update_governance
on public.answer_reports for update to authenticated
using (public.has_functional_permission((select auth.uid()), 'VIEW_AUDIT'))
with check (public.has_functional_permission((select auth.uid()), 'VIEW_AUDIT'));

drop policy if exists audit_logs_select_governance on public.audit_logs;
create policy audit_logs_select_governance
on public.audit_logs for select to authenticated
using (public.has_functional_permission((select auth.uid()), 'VIEW_AUDIT'));

comment on function public.match_enterprise_document_chunks(
    vector, integer, jsonb
) is
    'Dense retrieval gate. Unauthorized, unpublished and non-current versions are excluded before ranking.';
comment on function public.search_enterprise_document_chunks_keyword(
    text, integer, jsonb
) is
    'Sparse retrieval gate. ACL and lifecycle predicates execute before any candidate leaves PostgreSQL.';
comment on function public.authorized_knowledge_document_ids() is
    'Current-user allowlist resolved from live DB membership; empty means default DENY.';
