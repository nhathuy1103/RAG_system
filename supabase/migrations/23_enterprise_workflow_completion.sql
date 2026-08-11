-- Enterprise workflow completion and production authorization alignment.
-- Run after 22_enterprise_answer_ingestion_bridge.sql.

-- Keep read-only governance, analytics, and report mutation as separate
-- capabilities.  ADMIN receives newly introduced permissions through the
-- same data-driven role mapping as every other role.
insert into public.functional_permissions (code, name, description)
values
    ('VIEW_ANALYTICS', 'View analytics', 'View aggregate Enterprise knowledge metrics.'),
    ('MANAGE_REPORT', 'Manage answer reports', 'Resolve or dismiss reported answers.')
on conflict (code) do nothing;

insert into public.role_permissions (role_id, permission_id)
select roles.id, permissions.id
from public.roles as roles
cross join public.functional_permissions as permissions
where roles.code = 'ADMIN'
  and permissions.code in ('VIEW_ANALYTICS', 'MANAGE_REPORT')
on conflict (role_id, permission_id) do nothing;

create or replace function public.enterprise_analytics_summary()
returns jsonb
language plpgsql
stable
security definer
set search_path = ''
as $$
declare
    actor uuid := auth.uid();
begin
    if actor is null
       or not public.has_functional_permission(actor, 'VIEW_ANALYTICS') then
        raise exception 'Analytics access is not permitted' using errcode = '42501';
    end if;
    return jsonb_build_object(
        'draft_documents', (
            select count(*) from public.knowledge_documents where status = 'DRAFT'
        ),
        'published_documents', (
            select count(*) from public.knowledge_documents where status = 'PUBLISHED'
        ),
        'archived_documents', (
            select count(*) from public.knowledge_documents where status = 'ARCHIVED'
        ),
        'pending_jobs', (
            select count(*) from public.processing_jobs where status = 'PENDING'
        ),
        'running_jobs', (
            select count(*) from public.processing_jobs where status = 'RUNNING'
        ),
        'failed_jobs', (
            select count(*) from public.processing_jobs where status = 'FAILED'
        ),
        'feedback_up', (
            select count(*) from public.answer_feedback where rating = 'UP'
        ),
        'feedback_down', (
            select count(*) from public.answer_feedback where rating = 'DOWN'
        ),
        'open_reports', (
            select count(*) from public.answer_reports
            where status in ('OPEN', 'INVESTIGATING')
        ),
        'no_answer_rate', (
            select case
                when count(*) = 0 then 0::double precision
                else count(*) filter (
                    where answer_status = 'CONTROLLED_NO_ANSWER'
                )::double precision / count(*)::double precision
            end
            from public.enterprise_messages
            where role = 'ASSISTANT'
        )
    );
end;
$$;

revoke all on function public.enterprise_analytics_summary()
from public, anon;
grant execute on function public.enterprise_analytics_summary()
to authenticated;

drop policy if exists answer_reports_update_governance
on public.answer_reports;
create policy answer_reports_update_governance
on public.answer_reports for update to authenticated
using (public.has_functional_permission((select auth.uid()), 'MANAGE_REPORT'))
with check (public.has_functional_permission((select auth.uid()), 'MANAGE_REPORT'));

-- Configure one or more ACTIVE domains to make corporate-email enforcement
-- fail closed for every future auth.users insert/email change.  An empty table
-- intentionally keeps local development and an external enterprise IdP viable.
create table if not exists public.enterprise_allowed_email_domains (
    domain text primary key,
    status text not null default 'ACTIVE',
    created_at timestamptz not null default now(),
    constraint enterprise_allowed_email_domains_format check (
        domain = lower(btrim(domain))
        and domain ~ '^[a-z0-9][a-z0-9.-]*[a-z0-9]$'
        and pg_catalog.strpos(domain, '.') > 1
        and domain !~ '\.\.'
    ),
    constraint enterprise_allowed_email_domains_status
        check (status in ('ACTIVE', 'DISABLED'))
);

alter table public.enterprise_allowed_email_domains enable row level security;
alter table public.enterprise_allowed_email_domains force row level security;
revoke all on table public.enterprise_allowed_email_domains from public, anon, authenticated;
grant select, insert, update, delete on table public.enterprise_allowed_email_domains
to service_role;

create or replace function public.enforce_enterprise_email_domain()
returns trigger
language plpgsql
security definer
set search_path = ''
as $$
declare
    normalized_domain text := lower(split_part(coalesce(new.email, ''), '@', 2));
begin
    if exists (
        select 1
        from public.enterprise_allowed_email_domains
        where status = 'ACTIVE'
    ) and not exists (
        select 1
        from public.enterprise_allowed_email_domains
        where status = 'ACTIVE'
          and domain = normalized_domain
    ) then
        raise exception 'Email domain is not permitted for this organization'
            using errcode = '42501';
    end if;
    return new;
end;
$$;

revoke all on function public.enforce_enterprise_email_domain()
from public, anon, authenticated;

drop trigger if exists auth_users_enforce_enterprise_email_domain on auth.users;
create trigger auth_users_enforce_enterprise_email_domain
before insert or update of email on auth.users
for each row execute function public.enforce_enterprise_email_domain();

-- Metadata edits use an explicit version token so two administrators cannot
-- silently overwrite one another's changes.
create or replace function public.update_knowledge_document(
    p_document_id uuid,
    p_changes jsonb
)
returns public.knowledge_documents
language plpgsql
security definer
set search_path = ''
as $$
declare
    actor uuid := auth.uid();
    selected_document public.knowledge_documents;
    updated_document public.knowledge_documents;
    expected_updated_at timestamptz;
begin
    if actor is null
       or not public.has_functional_permission(actor, 'MANAGE_DOCUMENT')
       or not public.has_document_permission(actor, p_document_id, 'MANAGE') then
        raise exception 'Document update is not permitted' using errcode = '42501';
    end if;
    if p_changes is null or jsonb_typeof(p_changes) <> 'object' then
        raise exception 'Changes must be a JSON object' using errcode = '22023';
    end if;
    if not p_changes ? 'expected_updated_at' then
        raise exception 'expected_updated_at is required' using errcode = '22023';
    end if;
    begin
        expected_updated_at := (p_changes ->> 'expected_updated_at')::timestamptz;
    exception when invalid_datetime_format then
        raise exception 'expected_updated_at is invalid' using errcode = '22023';
    end;
    if exists (
        select 1
        from jsonb_object_keys(p_changes) as keys(key)
        where keys.key not in (
            'expected_updated_at',
            'title',
            'description',
            'document_type',
            'category',
            'document_number',
            'issued_date',
            'effective_date',
            'expiration_date',
            'source',
            'owner_department_id',
            'metadata'
        )
    ) then
        raise exception 'Changes contain a protected or unknown field'
            using errcode = '22023';
    end if;
    if p_changes ? 'metadata'
       and (
           p_changes -> 'metadata' = 'null'::jsonb
           or jsonb_typeof(p_changes -> 'metadata') <> 'object'
       ) then
        raise exception 'Metadata must be a JSON object' using errcode = '22023';
    end if;

    select * into selected_document
    from public.knowledge_documents
    where id = p_document_id
    for update;
    if not found or selected_document.status = 'ARCHIVED' then
        raise exception 'Document is missing or archived' using errcode = '55000';
    end if;
    if selected_document.updated_at is distinct from expected_updated_at then
        raise exception 'Document was modified by another request; reload before saving'
            using errcode = '23505';
    end if;

    update public.knowledge_documents
    set title = case when p_changes ? 'title'
            then btrim(p_changes ->> 'title') else title end,
        description = case when p_changes ? 'description'
            then coalesce(p_changes ->> 'description', '') else description end,
        document_type = case when p_changes ? 'document_type'
            then upper(btrim(p_changes ->> 'document_type')) else document_type end,
        category = case when p_changes ? 'category'
            then nullif(btrim(p_changes ->> 'category'), '') else category end,
        document_number = case when p_changes ? 'document_number'
            then nullif(btrim(p_changes ->> 'document_number'), '') else document_number end,
        issued_date = case when p_changes ? 'issued_date'
            then nullif(p_changes ->> 'issued_date', '')::date else issued_date end,
        effective_date = case when p_changes ? 'effective_date'
            then nullif(p_changes ->> 'effective_date', '')::date else effective_date end,
        expiration_date = case when p_changes ? 'expiration_date'
            then nullif(p_changes ->> 'expiration_date', '')::date else expiration_date end,
        source = case when p_changes ? 'source'
            then nullif(btrim(p_changes ->> 'source'), '') else source end,
        owner_department_id = case when p_changes ? 'owner_department_id'
            then nullif(p_changes ->> 'owner_department_id', '')::uuid
            else owner_department_id end,
        metadata = case when p_changes ? 'metadata'
            then p_changes -> 'metadata' else metadata end
    where id = p_document_id
    returning * into updated_document;

    perform public.write_enterprise_audit(
        'DOCUMENT_UPDATED',
        'knowledge_document',
        p_document_id,
        to_jsonb(selected_document),
        to_jsonb(updated_document),
        null
    );
    return updated_document;
end;
$$;

revoke all on function public.update_knowledge_document(uuid, jsonb)
from public, anon;
grant execute on function public.update_knowledge_document(uuid, jsonb)
to authenticated;

-- Initial upload is one database transaction for SourceFile + logical
-- Document + v1 + ProcessingJob.  Object storage is written first by the API;
-- the API compensates by deleting that object if this RPC rolls back.
create or replace function public.create_enterprise_document_upload(
    p_source_id uuid,
    p_bucket_name text,
    p_object_path text,
    p_original_file_name text,
    p_mime_type text,
    p_size_bytes bigint,
    p_sha256 text,
    p_title text,
    p_description text default '',
    p_document_type text default 'GENERAL',
    p_category text default null,
    p_metadata jsonb default '{}'::jsonb,
    p_change_summary text default '',
    p_effective_date date default null
)
returns jsonb
language plpgsql
security definer
set search_path = ''
as $$
declare
    actor uuid := auth.uid();
    actor_subject_id uuid;
    normalized_sha text := lower(btrim(coalesce(p_sha256, '')));
    created_source public.source_files;
    created_document public.knowledge_documents;
    created_version public.document_versions;
    created_job public.processing_jobs;
begin
    if actor is null
       or not (
           public.has_functional_permission(actor, 'UPLOAD_DOCUMENT')
           or public.has_functional_permission(actor, 'MANAGE_DOCUMENT')
       ) then
        raise exception 'Initial document upload is not permitted' using errcode = '42501';
    end if;
    if p_metadata is null or jsonb_typeof(p_metadata) <> 'object' then
        raise exception 'Metadata must be a JSON object' using errcode = '22023';
    end if;
    if normalized_sha !~ '^[0-9a-f]{64}$' then
        raise exception 'Source checksum is invalid' using errcode = '22023';
    end if;

    -- Serialize exact-hash registration without imposing a destructive unique
    -- constraint on legacy/backfilled rows that may already contain duplicates.
    perform pg_catalog.pg_advisory_xact_lock(
        pg_catalog.hashtextextended(normalized_sha, 0)
    );
    if exists (
        select 1
        from public.source_files
        join public.document_versions
          on document_versions.source_file_id = source_files.id
        join public.knowledge_documents as registered_documents
          on registered_documents.id = document_versions.document_id
        where source_files.sha256 = normalized_sha
          and registered_documents.status <> 'ARCHIVED'
    ) then
        raise exception 'An identical source is already registered'
            using errcode = '23505';
    end if;

    select id into actor_subject_id
    from public.access_subjects
    where subject_type = 'USER' and user_id = actor;
    if actor_subject_id is null then
        raise exception 'Current user has no ACL subject' using errcode = '23503';
    end if;

    insert into public.source_files (
        id,
        bucket_name,
        object_path,
        original_file_name,
        mime_type,
        size_bytes,
        sha256,
        created_by
    ) values (
        p_source_id,
        btrim(p_bucket_name),
        btrim(p_object_path),
        btrim(p_original_file_name),
        lower(btrim(p_mime_type)),
        p_size_bytes,
        normalized_sha,
        actor
    ) returning * into created_source;

    insert into public.knowledge_documents (
        title,
        description,
        document_type,
        category,
        metadata,
        created_by
    ) values (
        btrim(p_title),
        coalesce(p_description, ''),
        upper(btrim(coalesce(p_document_type, 'GENERAL'))),
        nullif(btrim(p_category), ''),
        p_metadata,
        actor
    ) returning * into created_document;

    insert into public.document_permissions (
        document_id, subject_id, permission, granted_by
    )
    select created_document.id, actor_subject_id, permission, actor
    from (
        values
            ('READ'),
            ('DOWNLOAD'),
            ('MANAGE'),
            ('REVIEW'),
            ('PUBLISH'),
            ('ARCHIVE'),
            ('MANAGE_PERMISSION')
    ) as grants(permission);

    insert into public.document_versions (
        document_id,
        version_number,
        source_file_id,
        status,
        previous_version_id,
        change_summary,
        effective_date,
        created_by
    ) values (
        created_document.id,
        1,
        created_source.id,
        'DRAFT',
        null,
        coalesce(p_change_summary, ''),
        p_effective_date,
        actor
    ) returning * into created_version;

    insert into public.processing_jobs (
        document_version_id,
        job_type,
        status,
        attempt_no,
        requested_by
    ) values (
        created_version.id,
        'INITIAL_PROCESS',
        'PENDING',
        1,
        actor
    ) returning * into created_job;

    perform public.write_enterprise_audit(
        'DOCUMENT_CREATED',
        'knowledge_document',
        created_document.id,
        null,
        jsonb_build_object(
            'status', created_document.status,
            'title', created_document.title,
            'atomic_upload', true
        ),
        null
    );
    perform public.write_enterprise_audit(
        'DOCUMENT_VERSION_CREATED',
        'document_version',
        created_version.id,
        null,
        jsonb_build_object(
            'document_id', created_document.id,
            'version_number', 1,
            'status', created_version.status,
            'processing_job_id', created_job.id
        ),
        null
    );

    return jsonb_build_object(
        'document', to_jsonb(created_document),
        'version', to_jsonb(created_version),
        'processing_job', to_jsonb(created_job),
        'source_file', to_jsonb(created_source)
    );
end;
$$;

revoke all on function public.create_enterprise_document_upload(
    uuid, text, text, text, text, bigint, text,
    text, text, text, text, jsonb, text, date
) from public, anon;
grant execute on function public.create_enterprise_document_upload(
    uuid, text, text, text, text, bigint, text,
    text, text, text, text, jsonb, text, date
) to authenticated;

-- Explain effective ACL sources without leaking the membership graph to a
-- global policy manager who lacks MANAGE_PERMISSION on the target document.
create or replace function public.explain_document_access(
    p_user_id uuid,
    p_document_id uuid,
    p_permission text default 'READ'
)
returns jsonb
language plpgsql
stable
security definer
set search_path = ''
as $$
declare
    actor uuid := auth.uid();
    normalized_permission text := upper(btrim(coalesce(p_permission, '')));
    source_labels jsonb;
begin
    if actor is null then
        raise exception 'Authentication required' using errcode = '42501';
    end if;
    if actor <> p_user_id and not (
        public.has_functional_permission(actor, 'MANAGE_ACCESS_POLICY')
        and public.has_document_permission(actor, p_document_id, 'MANAGE_PERMISSION')
    ) then
        raise exception 'Access explanation is not permitted' using errcode = '42501';
    end if;
    if normalized_permission not in (
        'READ', 'DOWNLOAD', 'MANAGE', 'REVIEW', 'PUBLISH',
        'ARCHIVE', 'MANAGE_PERMISSION'
    ) then
        raise exception 'Unsupported document permission' using errcode = '22023';
    end if;

    select coalesce(jsonb_agg(source_label order by source_label), '[]'::jsonb)
    into source_labels
    from (
        select distinct concat(
            access_subjects.subject_type,
            ':',
            coalesce(
                roles.code,
                groups.code,
                departments.code,
                access_subjects.user_id::text
            ),
            ':',
            document_permissions.permission
        ) as source_label
        from public.document_permissions
        join public.access_subjects
          on access_subjects.id = document_permissions.subject_id
        left join public.roles on roles.id = access_subjects.role_id
        left join public.groups on groups.id = access_subjects.group_id
        left join public.departments on departments.id = access_subjects.department_id
        where document_permissions.document_id = p_document_id
          and document_permissions.status = 'ACTIVE'
          and document_permissions.permission in (normalized_permission, 'MANAGE')
          and document_permissions.subject_id in (
              select public.enterprise_subject_ids_for_user(p_user_id)
          )
    ) as effective_sources;

    return jsonb_build_object(
        'allowed', public.has_document_permission(
            p_user_id, p_document_id, normalized_permission
        ),
        'sources', source_labels
    );
end;
$$;

revoke all on function public.explain_document_access(uuid, uuid, text)
from public, anon;
grant execute on function public.explain_document_access(uuid, uuid, text)
to authenticated;

create or replace function public.test_document_access(
    p_user_id uuid,
    p_document_id uuid,
    p_permission text default 'READ'
)
returns boolean
language plpgsql
stable
security definer
set search_path = ''
as $$
declare
    actor uuid := auth.uid();
begin
    if actor is null then
        raise exception 'Authentication required' using errcode = '42501';
    end if;
    if actor <> p_user_id and not (
        public.has_functional_permission(actor, 'MANAGE_ACCESS_POLICY')
        and public.has_document_permission(actor, p_document_id, 'MANAGE_PERMISSION')
    ) then
        raise exception 'Cannot test another principal''s access'
            using errcode = '42501';
    end if;
    return public.has_document_permission(
        p_user_id,
        p_document_id,
        upper(btrim(p_permission))
    );
end;
$$;

revoke all on function public.test_document_access(uuid, uuid, text)
from public, anon;
grant execute on function public.test_document_access(uuid, uuid, text)
to authenticated;

create or replace function public.get_document_version_review_context(
    p_version_id uuid
)
returns jsonb
language plpgsql
stable
security definer
set search_path = ''
as $$
declare
    actor uuid := auth.uid();
    selected_document public.knowledge_documents;
    selected_version public.document_versions;
    selected_source public.source_files;
    latest_job public.processing_jobs;
begin
    select versions.* into selected_version
    from public.document_versions as versions
    where versions.id = p_version_id;
    if not found then
        return null;
    end if;

    select documents.* into selected_document
    from public.knowledge_documents as documents
    where documents.id = selected_version.document_id;
    if actor is null or not (
        (
            public.has_functional_permission(actor, 'REVIEW_DOCUMENT')
            and public.has_document_permission(actor, selected_document.id, 'REVIEW')
        )
        or (
            public.has_functional_permission(actor, 'PUBLISH_DOCUMENT')
            and public.has_document_permission(actor, selected_document.id, 'PUBLISH')
        )
        or (
            public.has_functional_permission(actor, 'MANAGE_DOCUMENT')
            and public.has_document_permission(actor, selected_document.id, 'MANAGE')
        )
    ) then
        raise exception 'Version review context is not permitted' using errcode = '42501';
    end if;

    select sources.* into selected_source
    from public.source_files as sources
    where sources.id = selected_version.source_file_id;

    select jobs.* into latest_job
    from public.processing_jobs as jobs
    where jobs.document_version_id = p_version_id
    order by jobs.attempt_no desc, jobs.requested_at desc, jobs.id desc
    limit 1;

    return jsonb_build_object(
        'document', to_jsonb(selected_document),
        'version', to_jsonb(selected_version),
        'source_file', jsonb_build_object(
            'id', selected_source.id,
            'original_file_name', selected_source.original_file_name,
            'mime_type', selected_source.mime_type,
            'size_bytes', selected_source.size_bytes,
            'sha256', selected_source.sha256,
            'created_by', selected_source.created_by,
            'created_at', selected_source.created_at
        ),
        'latest_processing_job', case
            when latest_job.id is null then null
            else to_jsonb(latest_job)
        end,
        'stage_history', case
            when latest_job.id is null then '[]'::jsonb
            else coalesce((
                select jsonb_agg(to_jsonb(history) order by history.started_at, history.id)
                from public.processing_stage_history as history
                where history.processing_job_id = latest_job.id
            ), '[]'::jsonb)
        end,
        'errors', case
            when latest_job.id is null then '[]'::jsonb
            else coalesce((
                select jsonb_agg(
                    jsonb_build_object(
                        'id', errors.id,
                        'processing_job_id', errors.processing_job_id,
                        'stage', errors.stage,
                        'error_type', errors.error_type,
                        'error_code', errors.error_code,
                        'safe_message', errors.safe_message,
                        'retryable', errors.retryable,
                        'created_at', errors.created_at
                    ) order by errors.created_at desc, errors.id
                )
                from public.processing_errors as errors
                where errors.processing_job_id = latest_job.id
            ), '[]'::jsonb)
        end,
        'extracted_chunks', coalesce((
            select jsonb_agg(
                jsonb_build_object(
                    'chunk_id', chunks.id,
                    'chunk_index', chunks.chunk_index,
                    'content', chunks.content,
                    'page_start', chunks.page_start,
                    'page_end', chunks.page_end,
                    'section_path', chunks.section_path,
                    'metadata', chunks.metadata
                ) order by chunks.chunk_index
            )
            from public.knowledge_chunks as chunks
            where chunks.document_version_id = p_version_id
        ), '[]'::jsonb)
    );
end;
$$;

revoke all on function public.get_document_version_review_context(uuid)
from public, anon;
grant execute on function public.get_document_version_review_context(uuid)
to authenticated;

comment on function public.create_enterprise_document_upload(
    uuid, text, text, text, text, bigint, text,
    text, text, text, text, jsonb, text, date
) is
    'Atomic SourceFile + logical Document + v1 + ProcessingJob registration with exact-SHA duplicate protection.';
comment on function public.explain_document_access(uuid, uuid, text) is
    'Returns effective allow/deny plus Direct/Role/Group/Department ACL sources for an authorized policy manager.';
comment on function public.get_document_version_review_context(uuid) is
    'Candidate-only review projection with extracted chunks and safe processing diagnostics; raw chunk RLS remains fail closed.';
