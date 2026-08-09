-- Enterprise authorization helpers and atomic business operations.
-- Run after 19_enterprise_processing_rag.sql.

create or replace function public.enterprise_subject_ids_for_user(p_user_id uuid)
returns setof uuid
language sql
stable
security definer
set search_path = ''
as $$
    with recursive active_departments(department_id) as (
        select user_departments.department_id
        from public.user_departments
        join public.departments
          on departments.id = user_departments.department_id
         and departments.status = 'ACTIVE'
        where user_departments.user_id = p_user_id
          and user_departments.start_at <= now()
          and (user_departments.end_at is null or user_departments.end_at > now())

        union

        select parent_departments.id
        from public.departments as child_departments
        join active_departments
          on child_departments.id = active_departments.department_id
        join public.departments as parent_departments
          on parent_departments.id = child_departments.parent_department_id
         and parent_departments.status = 'ACTIVE'
    ), active_subjects as (
        select access_subjects.id
        from public.access_subjects
        join public.user_profiles
          on user_profiles.user_id = access_subjects.user_id
        where access_subjects.subject_type = 'USER'
          and access_subjects.user_id = p_user_id
          and user_profiles.status = 'ACTIVE'

        union

        select access_subjects.id
        from public.user_roles
        join public.roles
          on roles.id = user_roles.role_id
         and roles.status = 'ACTIVE'
        join public.access_subjects
          on access_subjects.subject_type = 'ROLE'
         and access_subjects.role_id = roles.id
        where user_roles.user_id = p_user_id

        union

        select access_subjects.id
        from public.user_groups
        join public.groups
          on groups.id = user_groups.group_id
         and groups.status = 'ACTIVE'
        join public.access_subjects
          on access_subjects.subject_type = 'GROUP'
         and access_subjects.group_id = groups.id
        where user_groups.user_id = p_user_id

        union

        select access_subjects.id
        from active_departments
        join public.access_subjects
          on access_subjects.subject_type = 'DEPARTMENT'
         and access_subjects.department_id = active_departments.department_id
    )
    select id from active_subjects;
$$;

revoke all on function public.enterprise_subject_ids_for_user(uuid)
from public, anon, authenticated;
grant execute on function public.enterprise_subject_ids_for_user(uuid)
to service_role;

create or replace function public.has_document_permission(
    p_user_id uuid,
    p_document_id uuid,
    p_permission text
)
returns boolean
language sql
stable
security definer
set search_path = ''
as $$
    select coalesce(
        p_user_id is not null
        and upper(btrim(coalesce(p_permission, ''))) in (
            'READ',
            'DOWNLOAD',
            'MANAGE',
            'REVIEW',
            'PUBLISH',
            'ARCHIVE',
            'MANAGE_PERMISSION'
        )
        and exists (
            select 1
            from public.user_profiles
            where user_id = p_user_id and status = 'ACTIVE'
        )
        and exists (
            select 1
            from public.document_permissions
            where document_permissions.document_id = p_document_id
              and document_permissions.subject_id in (
                  select public.enterprise_subject_ids_for_user(p_user_id)
              )
              and document_permissions.status = 'ACTIVE'
              and document_permissions.permission in (
                  upper(btrim(p_permission)),
                  'MANAGE'
              )
        ),
        false
    );
$$;

revoke all on function public.has_document_permission(uuid, uuid, text)
from public, anon;
grant execute on function public.has_document_permission(uuid, uuid, text)
to authenticated, service_role;

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
    if actor <> p_user_id
       and not public.has_functional_permission(actor, 'MANAGE_ACCESS_POLICY') then
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

create or replace function public.write_enterprise_audit(
    p_action text,
    p_entity_type text,
    p_entity_id uuid,
    p_before_data jsonb default null,
    p_after_data jsonb default null,
    p_note text default null
)
returns uuid
language plpgsql
security definer
set search_path = ''
as $$
declare
    inserted_id uuid;
begin
    insert into public.audit_logs (
        actor_user_id,
        action,
        entity_type,
        entity_id,
        before_data,
        after_data,
        metadata,
        request_id,
        trace_id,
        note
    ) values (
        auth.uid(),
        p_action,
        p_entity_type,
        p_entity_id,
        p_before_data,
        p_after_data,
        jsonb_strip_nulls(jsonb_build_object(
            'before', p_before_data,
            'after', p_after_data,
            'note', p_note
        )),
        nullif(current_setting('request.headers', true)::jsonb ->> 'x-request-id', ''),
        nullif(current_setting('request.headers', true)::jsonb ->> 'x-trace-id', ''),
        p_note
    )
    returning id into inserted_id;
    return inserted_id;
end;
$$;

revoke all on function public.write_enterprise_audit(
    text, text, uuid, jsonb, jsonb, text
) from public, anon, authenticated;
grant execute on function public.write_enterprise_audit(
    text, text, uuid, jsonb, jsonb, text
) to service_role;

-- Tables intentionally managed through PostgREST still need an immutable
-- audit trail. Lifecycle tables use dedicated atomic RPC audits instead.
create or replace function public.audit_enterprise_table_change()
returns trigger
language plpgsql
security definer
set search_path = ''
as $$
declare
    before_payload jsonb := case when tg_op in ('UPDATE', 'DELETE')
        then to_jsonb(old) else null end;
    after_payload jsonb := case when tg_op in ('INSERT', 'UPDATE')
        then to_jsonb(new) else null end;
    entity_payload jsonb := coalesce(after_payload, before_payload);
    entity_id uuid;
begin
    entity_id := nullif(entity_payload ->> 'id', '')::uuid;
    perform public.write_enterprise_audit(
        'TABLE_' || upper(tg_table_name) || '_' || tg_op,
        tg_table_name,
        entity_id,
        before_payload,
        after_payload,
        null
    );
    if tg_op = 'DELETE' then
        return old;
    end if;
    return new;
end;
$$;

revoke all on function public.audit_enterprise_table_change()
from public, anon, authenticated;

do $audit_triggers$
declare
    audited_table text;
begin
    foreach audited_table in array array[
        'roles',
        'role_permissions',
        'user_roles',
        'groups',
        'user_groups',
        'departments',
        'user_departments',
        'source_files',
        'answer_feedback',
        'answer_reports'
    ]
    loop
        execute format(
            'drop trigger if exists %I on public.%I',
            audited_table || '_enterprise_audit',
            audited_table
        );
        execute format(
            'create trigger %I after insert or update or delete on public.%I '
            || 'for each row execute function public.audit_enterprise_table_change()',
            audited_table || '_enterprise_audit',
            audited_table
        );
    end loop;
end;
$audit_triggers$;

create or replace function public.upsert_user_profile(
    p_user_id uuid,
    p_company_user_id text default null,
    p_full_name text default null,
    p_status text default 'ACTIVE'
)
returns public.user_profiles
language plpgsql
security definer
set search_path = ''
as $$
declare
    actor uuid := auth.uid();
    before_profile jsonb;
    saved_profile public.user_profiles;
begin
    if actor is null
       or not public.has_functional_permission(actor, 'MANAGE_USER') then
        raise exception 'User management is not permitted' using errcode = '42501';
    end if;
    if not exists (select 1 from auth.users where id = p_user_id) then
        raise exception 'Auth user not found' using errcode = '23503';
    end if;

    select to_jsonb(user_profiles) into before_profile
    from public.user_profiles
    where user_id = p_user_id;

    insert into public.user_profiles (
        user_id, company_user_id, full_name, status
    ) values (
        p_user_id,
        nullif(btrim(p_company_user_id), ''),
        nullif(btrim(p_full_name), ''),
        upper(btrim(coalesce(p_status, 'ACTIVE')))
    )
    on conflict (user_id) do update
    set company_user_id = excluded.company_user_id,
        full_name = excluded.full_name,
        status = excluded.status
    returning * into saved_profile;

    perform public.write_enterprise_audit(
        case when before_profile is null then 'USER_PROFILE_CREATED'
             else 'USER_PROFILE_UPDATED' end,
        'user_profile',
        p_user_id,
        before_profile,
        to_jsonb(saved_profile),
        null
    );
    return saved_profile;
end;
$$;

revoke all on function public.upsert_user_profile(uuid, text, text, text)
from public, anon;
grant execute on function public.upsert_user_profile(uuid, text, text, text)
to authenticated;

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
begin
    if actor is null
       or not public.has_functional_permission(actor, 'MANAGE_DOCUMENT')
       or not public.has_document_permission(actor, p_document_id, 'MANAGE') then
        raise exception 'Document update is not permitted' using errcode = '42501';
    end if;
    if p_changes is null or jsonb_typeof(p_changes) <> 'object' then
        raise exception 'Changes must be a JSON object' using errcode = '22023';
    end if;
    if exists (
        select 1
        from jsonb_object_keys(p_changes) as keys(key)
        where keys.key not in (
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

create or replace function public.create_knowledge_document(
    p_title text,
    p_description text default '',
    p_document_type text default 'GENERAL',
    p_category text default null,
    p_metadata jsonb default '{}'::jsonb
)
returns public.knowledge_documents
language plpgsql
security definer
set search_path = ''
as $$
declare
    actor uuid := auth.uid();
    created_document public.knowledge_documents;
    actor_subject_id uuid;
begin
    if actor is null
       or not public.has_functional_permission(actor, 'MANAGE_DOCUMENT') then
        raise exception 'Document creation is not permitted' using errcode = '42501';
    end if;
    if p_metadata is null or jsonb_typeof(p_metadata) <> 'object' then
        raise exception 'Metadata must be a JSON object' using errcode = '22023';
    end if;

    insert into public.knowledge_documents (
        title, description, document_type, category, metadata, created_by
    ) values (
        btrim(p_title),
        coalesce(p_description, ''),
        upper(btrim(coalesce(p_document_type, 'GENERAL'))),
        nullif(btrim(p_category), ''),
        p_metadata,
        actor
    ) returning * into created_document;

    select id into actor_subject_id
    from public.access_subjects
    where subject_type = 'USER' and user_id = actor;
    if actor_subject_id is null then
        raise exception 'Current user has no ACL subject' using errcode = '23503';
    end if;

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

    perform public.write_enterprise_audit(
        'DOCUMENT_CREATED',
        'knowledge_document',
        created_document.id,
        null,
        jsonb_build_object('status', created_document.status, 'title', created_document.title),
        null
    );
    return created_document;
end;
$$;

revoke all on function public.create_knowledge_document(
    text, text, text, text, jsonb
) from public, anon;
grant execute on function public.create_knowledge_document(
    text, text, text, text, jsonb
) to authenticated;

create or replace function public.create_document_version(
    p_document_id uuid,
    p_source_file_id uuid,
    p_change_summary text default '',
    p_effective_date date default null
)
returns public.document_versions
language plpgsql
security definer
set search_path = ''
as $$
declare
    actor uuid := auth.uid();
    selected_document public.knowledge_documents;
    selected_source public.source_files;
    created_version public.document_versions;
    previous_version uuid;
    next_version integer;
begin
    if actor is null
       or not public.has_document_permission(actor, p_document_id, 'MANAGE')
       or not public.has_functional_permission(actor, 'MANAGE_DOCUMENT') then
        raise exception 'Version creation is not permitted' using errcode = '42501';
    end if;

    select * into selected_document
    from public.knowledge_documents
    where id = p_document_id
    for update;
    if not found or selected_document.status = 'ARCHIVED' then
        raise exception 'Document is missing or archived' using errcode = '55000';
    end if;
    select files.* into selected_source
    from public.source_files as files
    where files.id = p_source_file_id
      and files.created_by = actor
    for update;
    if not found then
        raise exception 'Source file is not available' using errcode = '42501';
    end if;
    if exists (
        select 1
        from public.document_versions as versions
        where versions.source_file_id = p_source_file_id
    ) then
        raise exception 'Source file is already linked to a document version'
            using errcode = '23505';
    end if;
    if selected_source.sha256 is not null then
        perform pg_catalog.pg_advisory_xact_lock(
            pg_catalog.hashtextextended(selected_source.sha256, 0)
        );
        if exists (
            select 1
            from public.document_versions as versions
            join public.source_files as existing_sources
              on existing_sources.id = versions.source_file_id
            where existing_sources.sha256 = selected_source.sha256
        ) then
            raise exception 'An identical source file is already registered'
                using errcode = '23505';
        end if;
    end if;

    select coalesce(max(version_number), 0) + 1,
           (array_agg(id order by version_number desc))[1]
    into next_version, previous_version
    from public.document_versions
    where document_id = p_document_id;

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
        p_document_id,
        next_version,
        p_source_file_id,
        'DRAFT',
        previous_version,
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
        case when next_version = 1 then 'INITIAL_PROCESS' else 'NEW_VERSION' end,
        'PENDING',
        1,
        actor
    );

    perform public.write_enterprise_audit(
        'DOCUMENT_VERSION_CREATED',
        'document_version',
        created_version.id,
        null,
        jsonb_build_object(
            'document_id', p_document_id,
            'version_number', next_version,
            'status', created_version.status
        ),
        null
    );
    return created_version;
end;
$$;

revoke all on function public.create_document_version(
    uuid, uuid, text, date
) from public, anon;
grant execute on function public.create_document_version(
    uuid, uuid, text, date
) to authenticated;

create or replace function public.review_document_version(
    p_version_id uuid,
    p_decision text,
    p_note text default null,
    p_rejection_reason text default null
)
returns public.document_versions
language plpgsql
security definer
set search_path = ''
as $$
declare
    actor uuid := auth.uid();
    selected_version public.document_versions;
    selected_document public.knowledge_documents;
    previous_job public.processing_jobs;
    created_job public.processing_jobs;
    next_attempt integer;
    normalized_decision text := upper(btrim(coalesce(p_decision, '')));
begin
    select * into selected_version
    from public.document_versions
    where id = p_version_id;

    if not found
       or actor is null
       or not public.has_functional_permission(actor, 'REVIEW_DOCUMENT')
       or not public.has_document_permission(
           actor, selected_version.document_id, 'REVIEW'
       ) then
        raise exception 'Version review is not permitted' using errcode = '42501';
    end if;

    -- Lock the parent before the mutable version row so archive/review races
    -- serialize on the document lifecycle boundary.
    select * into selected_document
    from public.knowledge_documents
    where id = selected_version.document_id
    for update;
    if not found or selected_document.status = 'ARCHIVED' then
        raise exception 'Archived documents cannot be reviewed'
            using errcode = '55000';
    end if;

    select * into selected_version
    from public.document_versions
    where id = p_version_id
      and document_id = selected_document.id
    for update;
    if not found then
        raise exception 'Document version not found' using errcode = 'P0002';
    end if;
    if selected_version.status <> 'READY_FOR_REVIEW' then
        raise exception 'Only READY_FOR_REVIEW versions may be reviewed'
            using errcode = '55000';
    end if;
    if normalized_decision not in ('APPROVE', 'REJECT', 'REPROCESS') then
        raise exception 'Invalid review decision' using errcode = '22023';
    end if;
    if normalized_decision = 'REJECT'
       and nullif(btrim(coalesce(p_rejection_reason, '')), '') is null then
        raise exception 'A rejection reason is required' using errcode = '22023';
    end if;

    insert into public.document_reviews (
        document_version_id,
        reviewed_by,
        decision,
        review_note,
        rejection_reason
    ) values (
        p_version_id,
        actor,
        normalized_decision,
        nullif(btrim(p_note), ''),
        case
            when normalized_decision = 'REJECT'
            then nullif(btrim(p_rejection_reason), '')
            else null
        end
    );

    if normalized_decision in ('REJECT', 'REPROCESS') then
        perform set_config(
            'app.status_change_reason',
            'Review decision: ' || normalized_decision,
            true
        );
        update public.document_versions
        set status = case
                when normalized_decision = 'REJECT' then 'REJECTED'
                else 'DRAFT'
            end
        where id = p_version_id
        returning * into selected_version;
    end if;

    if normalized_decision = 'REPROCESS' then
        select jobs.* into previous_job
        from public.processing_jobs as jobs
        where jobs.document_version_id = p_version_id
        order by jobs.attempt_no desc, jobs.id desc
        for update
        limit 1;
        if not found then
            raise exception 'No completed processing job is available to reprocess'
                using errcode = '55000';
        end if;

        select coalesce(max(jobs.attempt_no), 0) + 1 into next_attempt
        from public.processing_jobs as jobs
        where jobs.document_version_id = p_version_id;

        insert into public.processing_jobs (
            document_version_id,
            job_type,
            status,
            attempt_no,
            previous_job_id,
            requested_by,
            embedding_model,
            embedding_dimensions,
            configuration
        ) values (
            p_version_id,
            'REPROCESS',
            'PENDING',
            next_attempt,
            previous_job.id,
            actor,
            previous_job.embedding_model,
            previous_job.embedding_dimensions,
            previous_job.configuration
        ) returning * into created_job;

        perform public.write_enterprise_audit(
            'PROCESSING_JOB_REPROCESSED_FROM_REVIEW',
            'processing_job',
            created_job.id,
            jsonb_build_object('previous_job_id', previous_job.id),
            jsonb_build_object(
                'document_version_id', p_version_id,
                'status', 'PENDING',
                'attempt_no', next_attempt
            ),
            p_note
        );
    end if;

    perform public.write_enterprise_audit(
        'DOCUMENT_VERSION_REVIEWED',
        'document_version',
        p_version_id,
        jsonb_build_object('status', 'READY_FOR_REVIEW'),
        jsonb_build_object(
            'status', selected_version.status,
            'decision', normalized_decision
        ),
        p_note
    );
    return selected_version;
end;
$$;

revoke all on function public.review_document_version(
    uuid, text, text, text
) from public, anon;
grant execute on function public.review_document_version(
    uuid, text, text, text
) to authenticated;

create or replace function public.publish_document_version(p_version_id uuid)
returns public.document_versions
language plpgsql
security definer
set search_path = ''
as $$
declare
    actor uuid := auth.uid();
    selected_version public.document_versions;
    selected_document public.knowledge_documents;
    previous_active_version_id uuid;
    previous_document_status text;
begin
    select * into selected_version
    from public.document_versions
    where id = p_version_id;
    if not found then
        raise exception 'Document version not found' using errcode = 'P0002';
    end if;

    select * into selected_document
    from public.knowledge_documents
    where id = selected_version.document_id
    for update;
    select * into selected_version
    from public.document_versions
    where id = p_version_id
    for update;

    if actor is null
       or not public.has_functional_permission(actor, 'PUBLISH_DOCUMENT')
       or not public.has_document_permission(actor, selected_document.id, 'PUBLISH') then
        raise exception 'Version publication is not permitted' using errcode = '42501';
    end if;
    if selected_document.status = 'ARCHIVED'
       or selected_version.status <> 'READY_FOR_REVIEW' then
        raise exception 'Version is not publishable' using errcode = '55000';
    end if;
    if not exists (
        select 1
        from public.document_reviews as reviews
        where reviews.document_version_id = p_version_id
          and reviews.decision = 'APPROVE'
          and reviews.id = (
              select latest_review.id
              from public.document_reviews as latest_review
              where latest_review.document_version_id = p_version_id
              order by latest_review.reviewed_at desc, latest_review.id desc
              limit 1
          )
          and reviews.reviewed_at >= (
              select max(jobs.completed_at)
              from public.processing_jobs as jobs
              where jobs.document_version_id = p_version_id
                and jobs.status = 'SUCCEEDED'
          )
    ) then
        raise exception 'The latest successful processing attempt requires a later approval'
            using errcode = '55000';
    end if;

    previous_document_status := selected_document.status;

    select id into previous_active_version_id
    from public.document_versions
    where document_id = selected_document.id
      and status = 'ACTIVE'
    for update;

    perform set_config(
        'app.status_change_reason',
        'Superseded by publication of ' || p_version_id::text,
        true
    );
    update public.document_versions
    set status = 'SUPERSEDED'
    where document_id = selected_document.id
      and status = 'ACTIVE';

    perform set_config('app.status_change_reason', 'Published', true);
    update public.document_versions
    set status = 'ACTIVE'
    where id = p_version_id
    returning * into selected_version;

    update public.knowledge_documents
    set status = 'PUBLISHED',
        current_version_id = p_version_id
    where id = selected_document.id
    returning * into selected_document;

    insert into public.publications (
        document_id,
        document_version_id,
        previous_active_version_id,
        published_by
    ) values (
        selected_document.id,
        p_version_id,
        previous_active_version_id,
        actor
    );

    perform public.write_enterprise_audit(
        'DOCUMENT_VERSION_PUBLISHED',
        'knowledge_document',
        selected_document.id,
        jsonb_build_object(
            'status', previous_document_status,
            'current_version_id', previous_active_version_id
        ),
        jsonb_build_object(
            'status', 'PUBLISHED',
            'current_version_id', p_version_id
        ),
        null
    );
    return selected_version;
end;
$$;

revoke all on function public.publish_document_version(uuid)
from public, anon;
grant execute on function public.publish_document_version(uuid)
to authenticated;

create or replace function public.archive_knowledge_document(
    p_document_id uuid,
    p_reason text
)
returns public.knowledge_documents
language plpgsql
security definer
set search_path = ''
as $$
declare
    actor uuid := auth.uid();
    selected_document public.knowledge_documents;
    previous_document_status text;
begin
    select * into selected_document
    from public.knowledge_documents
    where id = p_document_id
    for update;
    if not found
       or actor is null
       or not public.has_functional_permission(actor, 'ARCHIVE_DOCUMENT')
       or not public.has_document_permission(actor, p_document_id, 'ARCHIVE') then
        raise exception 'Document archival is not permitted' using errcode = '42501';
    end if;
    if selected_document.status = 'ARCHIVED' then
        return selected_document;
    end if;
    if nullif(btrim(p_reason), '') is null then
        raise exception 'Archive reason is required' using errcode = '22023';
    end if;

    previous_document_status := selected_document.status;

    update public.knowledge_documents
    set status = 'ARCHIVED',
        archived_by = actor,
        archived_at = now(),
        archive_reason = btrim(p_reason)
    where id = p_document_id
    returning * into selected_document;

    perform public.write_enterprise_audit(
        'DOCUMENT_ARCHIVED',
        'knowledge_document',
        p_document_id,
        jsonb_build_object('status', previous_document_status),
        jsonb_build_object('status', 'ARCHIVED'),
        p_reason
    );
    return selected_document;
end;
$$;

revoke all on function public.archive_knowledge_document(uuid, text)
from public, anon;
grant execute on function public.archive_knowledge_document(uuid, text)
to authenticated;

create or replace function public.grant_document_permission(
    p_document_id uuid,
    p_subject_id uuid,
    p_permission text
)
returns public.document_permissions
language plpgsql
security definer
set search_path = ''
as $$
declare
    actor uuid := auth.uid();
    normalized_permission text := upper(btrim(coalesce(p_permission, '')));
    created_permission public.document_permissions;
begin
    if actor is null
       or not public.has_functional_permission(actor, 'MANAGE_ACCESS_POLICY')
       or not public.has_document_permission(
           actor, p_document_id, 'MANAGE_PERMISSION'
       ) then
        raise exception 'ACL management is not permitted' using errcode = '42501';
    end if;
    if normalized_permission not in (
        'READ',
        'DOWNLOAD',
        'MANAGE',
        'REVIEW',
        'PUBLISH',
        'ARCHIVE',
        'MANAGE_PERMISSION'
    ) then
        raise exception 'Invalid document permission' using errcode = '22023';
    end if;
    if not exists (select 1 from public.access_subjects where id = p_subject_id) then
        raise exception 'Access subject not found' using errcode = '23503';
    end if;

    insert into public.document_permissions (
        document_id, subject_id, permission, status, granted_by
    ) values (
        p_document_id, p_subject_id, normalized_permission, 'ACTIVE', actor
    ) returning * into created_permission;

    perform public.write_enterprise_audit(
        'DOCUMENT_PERMISSION_GRANTED',
        'knowledge_document',
        p_document_id,
        null,
        jsonb_build_object(
            'permission_id', created_permission.id,
            'subject_id', p_subject_id,
            'permission', normalized_permission
        ),
        null
    );
    return created_permission;
exception
    when unique_violation then
        raise exception 'An active assignment already exists'
            using errcode = '23505';
end;
$$;

revoke all on function public.grant_document_permission(uuid, uuid, text)
from public, anon;
grant execute on function public.grant_document_permission(uuid, uuid, text)
to authenticated;

create or replace function public.revoke_document_permission(
    p_document_id uuid,
    p_subject_id uuid,
    p_permission text
)
returns void
language plpgsql
security definer
set search_path = ''
as $$
declare
    actor uuid := auth.uid();
    normalized_permission text := upper(btrim(coalesce(p_permission, '')));
    revoked_permission_id uuid;
begin
    if actor is null
       or not public.has_functional_permission(actor, 'MANAGE_ACCESS_POLICY')
       or not public.has_document_permission(
           actor, p_document_id, 'MANAGE_PERMISSION'
       ) then
        raise exception 'ACL management is not permitted' using errcode = '42501';
    end if;

    update public.document_permissions
    set status = 'REVOKED',
        revoked_by = actor,
        revoked_at = now()
    where id = (
        select id
        from public.document_permissions
        where document_id = p_document_id
          and subject_id = p_subject_id
          and permission = normalized_permission
          and status = 'ACTIVE'
        for update
    )
    returning id into revoked_permission_id;
    if revoked_permission_id is null then
        raise exception 'Active assignment not found' using errcode = 'P0002';
    end if;

    perform public.write_enterprise_audit(
        'DOCUMENT_PERMISSION_REVOKED',
        'knowledge_document',
        p_document_id,
        jsonb_build_object(
            'permission_id', revoked_permission_id,
            'subject_id', p_subject_id,
            'permission', normalized_permission,
            'status', 'ACTIVE'
        ),
        jsonb_build_object('status', 'REVOKED'),
        null
    );
end;
$$;

revoke all on function public.revoke_document_permission(uuid, uuid, text)
from public, anon;
grant execute on function public.revoke_document_permission(uuid, uuid, text)
to authenticated;

create or replace function public.retry_processing_job(p_job_id uuid)
returns public.processing_jobs
language plpgsql
security definer
set search_path = ''
as $$
declare
    actor uuid := auth.uid();
    selected_job public.processing_jobs;
    selected_version public.document_versions;
    selected_document public.knowledge_documents;
    created_job public.processing_jobs;
    next_attempt integer;
begin
    select * into selected_job
    from public.processing_jobs
    where id = p_job_id
    for update;
    if not found then
        raise exception 'Processing job not found' using errcode = 'P0002';
    end if;
    select * into selected_version
    from public.document_versions
    where id = selected_job.document_version_id;
    if actor is null
       or not public.has_functional_permission(actor, 'MANAGE_DOCUMENT')
       or not public.has_document_permission(
           actor, selected_version.document_id, 'MANAGE'
       ) then
        raise exception 'Processing retry is not permitted' using errcode = '42501';
    end if;

    select * into selected_document
    from public.knowledge_documents
    where id = selected_version.document_id
    for update;
    if not found or selected_document.status = 'ARCHIVED' then
        raise exception 'Archived documents cannot be reprocessed'
            using errcode = '55000';
    end if;
    if selected_job.status not in ('FAILED', 'CANCELLED') then
        raise exception 'Only FAILED or CANCELLED jobs may be retried'
            using errcode = '55000';
    end if;

    select coalesce(max(attempt_no), 0) + 1 into next_attempt
    from public.processing_jobs
    where document_version_id = selected_job.document_version_id;

    insert into public.processing_jobs (
        document_version_id,
        job_type,
        status,
        attempt_no,
        previous_job_id,
        requested_by,
        embedding_model,
        embedding_dimensions,
        configuration
    ) values (
        selected_job.document_version_id,
        'REPROCESS',
        'PENDING',
        next_attempt,
        selected_job.id,
        actor,
        selected_job.embedding_model,
        selected_job.embedding_dimensions,
        selected_job.configuration
    ) returning * into created_job;

    perform public.write_enterprise_audit(
        'PROCESSING_JOB_RETRIED',
        'processing_job',
        created_job.id,
        jsonb_build_object('previous_job_id', selected_job.id),
        jsonb_build_object('status', 'PENDING', 'attempt_no', next_attempt),
        null
    );
    return created_job;
end;
$$;

revoke all on function public.retry_processing_job(uuid)
from public, anon;
grant execute on function public.retry_processing_job(uuid)
to authenticated;

create or replace function public.claim_processing_job(
    p_worker_id text,
    p_lease_seconds integer default 120
)
returns public.processing_jobs
language plpgsql
security definer
set search_path = ''
as $$
declare
    selected_job public.processing_jobs;
    next_claim_token uuid := gen_random_uuid();
begin
    if auth.role() <> 'service_role' then
        raise exception 'Service role required' using errcode = '42501';
    end if;
    if nullif(btrim(p_worker_id), '') is null
       or p_lease_seconds < 10 or p_lease_seconds > 3600 then
        raise exception 'Invalid worker lease request' using errcode = '22023';
    end if;

    select * into selected_job
    from public.processing_jobs
    where status = 'PENDING'
       or (status = 'RUNNING' and lease_expires_at <= now())
    order by requested_at, id
    for update skip locked
    limit 1;
    if not found then
        return null;
    end if;

    update public.processing_jobs
    set status = 'RUNNING',
        started_at = coalesce(started_at, now()),
        heartbeat_at = now(),
        lease_owner = btrim(p_worker_id),
        lease_expires_at = now() + make_interval(secs => p_lease_seconds),
        claim_token = next_claim_token,
        error_code = null,
        error_message = null
    where id = selected_job.id
    returning * into selected_job;
    return selected_job;
end;
$$;

revoke all on function public.claim_processing_job(text, integer)
from public, anon, authenticated;
grant execute on function public.claim_processing_job(text, integer)
to service_role;

create or replace function public.renew_processing_job_lease(
    p_job_id uuid,
    p_worker_id text,
    p_claim_token uuid,
    p_lease_seconds integer default 120
)
returns boolean
language plpgsql
security definer
set search_path = ''
as $$
begin
    if auth.role() <> 'service_role' then
        raise exception 'Service role required' using errcode = '42501';
    end if;
    if p_lease_seconds < 10 or p_lease_seconds > 3600 then
        raise exception 'Invalid lease duration' using errcode = '22023';
    end if;
    update public.processing_jobs
    set heartbeat_at = now(),
        lease_expires_at = now() + make_interval(secs => p_lease_seconds)
    where id = p_job_id
      and status = 'RUNNING'
      and lease_owner = btrim(p_worker_id)
      and claim_token = p_claim_token
      and lease_expires_at > now();
    return found;
end;
$$;

revoke all on function public.renew_processing_job_lease(
    uuid, text, uuid, integer
) from public, anon, authenticated;
grant execute on function public.renew_processing_job_lease(
    uuid, text, uuid, integer
) to service_role;

create or replace function public.record_processing_stage(
    p_job_id uuid,
    p_worker_id text,
    p_claim_token uuid,
    p_stage text,
    p_status text,
    p_message text default null
)
returns public.processing_stage_history
language plpgsql
security definer
set search_path = ''
as $$
declare
    normalized_stage text := upper(btrim(coalesce(p_stage, '')));
    normalized_status text := upper(btrim(coalesce(p_status, '')));
    created_history public.processing_stage_history;
begin
    if auth.role() <> 'service_role' then
        raise exception 'Service role required' using errcode = '42501';
    end if;
    if not exists (
        select 1 from public.processing_jobs
        where id = p_job_id
          and status = 'RUNNING'
          and lease_owner = btrim(p_worker_id)
          and claim_token = p_claim_token
          and lease_expires_at > now()
        for update
    ) then
        raise exception 'Processing lease is stale' using errcode = '40001';
    end if;

    update public.processing_jobs
    set current_stage = normalized_stage,
        heartbeat_at = now()
    where id = p_job_id;

    insert into public.processing_stage_history (
        processing_job_id,
        stage,
        status,
        started_at,
        completed_at,
        message
    ) values (
        p_job_id,
        normalized_stage,
        normalized_status,
        now(),
        case when normalized_status = 'STARTED' then null else now() end,
        nullif(btrim(p_message), '')
    ) returning * into created_history;
    return created_history;
end;
$$;

revoke all on function public.record_processing_stage(
    uuid, text, uuid, text, text, text
) from public, anon, authenticated;
grant execute on function public.record_processing_stage(
    uuid, text, uuid, text, text, text
) to service_role;

create or replace function public.complete_processing_job(
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
    completed_job public.processing_jobs;
begin
    if auth.role() <> 'service_role' then
        raise exception 'Service role required' using errcode = '42501';
    end if;

    select * into selected_job
    from public.processing_jobs
    where id = p_job_id
      and status = 'RUNNING'
      and lease_owner = btrim(p_worker_id)
      and claim_token = p_claim_token
      and lease_expires_at > now()
    for update;
    if not found then
        raise exception 'Processing lease is stale' using errcode = '40001';
    end if;
    select * into selected_version
    from public.document_versions
    where id = selected_job.document_version_id;

    if p_chunks is not null then
        if jsonb_typeof(p_chunks) <> 'array'
           or jsonb_array_length(p_chunks) < 1
           or jsonb_array_length(p_chunks) > 20000 then
            raise exception 'Successful processing requires 1..20000 chunks'
                using errcode = '22023';
        end if;
        if exists (
            select 1
            from jsonb_array_elements(p_chunks) as chunk(value)
            where jsonb_typeof(chunk.value) <> 'object'
               or nullif(btrim(chunk.value ->> 'content'), '') is null
               or coalesce(chunk.value ->> 'chunk_index', '') !~ '^[0-9]+$'
               or (
                   chunk.value ? 'metadata'
                   and jsonb_typeof(chunk.value -> 'metadata') <> 'object'
               )
               or (
                   chunk.value ? 'embedding'
                   and chunk.value -> 'embedding' <> 'null'::jsonb
                   and jsonb_typeof(chunk.value -> 'embedding') <> 'array'
               )
        ) then
            raise exception 'Chunk payload is invalid' using errcode = '22023';
        end if;

        delete from public.knowledge_chunks
        where document_version_id = selected_job.document_version_id;

        insert into public.knowledge_chunks (
            id,
            document_id,
            document_version_id,
            chunk_index,
            content,
            contextual_content,
            token_count,
            content_hash,
            page_start,
            page_end,
            section_path,
            metadata,
            embedding
        )
        select
            coalesce(
                nullif(chunk.value ->> 'id', '')::uuid,
                gen_random_uuid()
            ),
            selected_version.document_id,
            selected_version.id,
            (chunk.value ->> 'chunk_index')::integer,
            chunk.value ->> 'content',
            nullif(chunk.value ->> 'contextual_content', ''),
            greatest(coalesce((chunk.value ->> 'token_count')::integer, 1), 1),
            lower(nullif(chunk.value ->> 'content_hash', '')),
            nullif(chunk.value ->> 'page_start', '')::integer,
            nullif(chunk.value ->> 'page_end', '')::integer,
            nullif(chunk.value ->> 'section_path', ''),
            coalesce(chunk.value -> 'metadata', '{}'::jsonb),
            case
                when jsonb_typeof(chunk.value -> 'embedding') = 'array'
                then (chunk.value -> 'embedding')::text::public.vector(1536)
                else null
            end
        from jsonb_array_elements(p_chunks) as chunk(value);
    elsif not exists (
        select 1
        from public.knowledge_chunks
        where document_version_id = selected_job.document_version_id
    ) then
        raise exception 'Successful processing requires indexed chunks'
            using errcode = '55000';
    end if;

    update public.processing_jobs
    set status = 'SUCCEEDED',
        current_stage = 'FINALIZING',
        completed_at = now(),
        heartbeat_at = now(),
        lease_owner = null,
        lease_expires_at = null,
        claim_token = null,
        error_code = null,
        error_message = null
    where id = p_job_id
      and status = 'RUNNING'
      and lease_owner = btrim(p_worker_id)
      and claim_token = p_claim_token
      and lease_expires_at > now()
    returning * into completed_job;
    if completed_job.id is null then
        raise exception 'Processing lease is stale' using errcode = '40001';
    end if;
    return completed_job;
end;
$$;

revoke all on function public.complete_processing_job(uuid, text, uuid, jsonb)
from public, anon, authenticated;
grant execute on function public.complete_processing_job(uuid, text, uuid, jsonb)
to service_role;

create or replace function public.fail_processing_job(
    p_job_id uuid,
    p_worker_id text,
    p_claim_token uuid,
    p_stage text,
    p_error_type text,
    p_error_code text,
    p_safe_message text,
    p_internal_reference text default null,
    p_retryable boolean default false
)
returns public.processing_jobs
language plpgsql
security definer
set search_path = ''
as $$
declare
    failed_job public.processing_jobs;
    normalized_stage text := nullif(upper(btrim(p_stage)), '');
    normalized_code text := upper(btrim(coalesce(p_error_code, 'PROCESSING_FAILED')));
    normalized_message text := btrim(coalesce(p_safe_message, ''));
begin
    if auth.role() <> 'service_role' then
        raise exception 'Service role required' using errcode = '42501';
    end if;
    if normalized_message = '' then
        raise exception 'Safe error message is required' using errcode = '22023';
    end if;

    update public.processing_jobs
    set status = 'FAILED',
        current_stage = coalesce(normalized_stage, current_stage),
        completed_at = now(),
        heartbeat_at = now(),
        lease_owner = null,
        lease_expires_at = null,
        claim_token = null,
        error_code = normalized_code,
        error_message = normalized_message
    where id = p_job_id
      and status = 'RUNNING'
      and lease_owner = btrim(p_worker_id)
      and claim_token = p_claim_token
      and lease_expires_at > now()
    returning * into failed_job;
    if failed_job.id is null then
        raise exception 'Processing lease is stale' using errcode = '40001';
    end if;

    insert into public.processing_errors (
        processing_job_id,
        stage,
        error_type,
        error_code,
        safe_message,
        internal_reference,
        retryable
    ) values (
        p_job_id,
        normalized_stage,
        btrim(p_error_type),
        normalized_code,
        normalized_message,
        nullif(btrim(p_internal_reference), ''),
        coalesce(p_retryable, false)
    );
    return failed_job;
end;
$$;

revoke all on function public.fail_processing_job(
    uuid, text, uuid, text, text, text, text, text, boolean
) from public, anon, authenticated;
grant execute on function public.fail_processing_job(
    uuid, text, uuid, text, text, text, text, text, boolean
) to service_role;

create or replace function public.mark_version_ready_after_processing()
returns trigger
language plpgsql
security definer
set search_path = ''
as $$
begin
    if new.status = 'SUCCEEDED'
       and old.status is distinct from new.status then
        perform set_config(
            'app.status_change_reason',
            'Processing job ' || new.id::text || ' succeeded',
            true
        );
        update public.document_versions
        set status = 'READY_FOR_REVIEW'
        where id = new.document_version_id
          and status = 'DRAFT';
    end if;
    return new;
end;
$$;

revoke all on function public.mark_version_ready_after_processing()
from public, anon, authenticated;

drop trigger if exists processing_jobs_mark_version_ready
on public.processing_jobs;
create trigger processing_jobs_mark_version_ready
after update of status on public.processing_jobs
for each row execute function public.mark_version_ready_after_processing();

create or replace function public.get_document_version_source(
    p_document_id uuid,
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
    selected_version public.document_versions;
    selected_document public.knowledge_documents;
    source_payload jsonb;
begin
    select * into selected_version
    from public.document_versions
    where id = p_version_id and document_id = p_document_id;
    select * into selected_document
    from public.knowledge_documents
    where id = p_document_id;
    if not found or selected_version.id is null then
        return null;
    end if;
    if actor is null
       or not public.has_document_permission(actor, p_document_id, 'READ') then
        raise exception 'Source access is not permitted' using errcode = '42501';
    end if;
    if not (
        selected_document.status = 'PUBLISHED'
        and selected_document.current_version_id = p_version_id
        and selected_version.status = 'ACTIVE'
    ) and not (
        public.has_document_permission(actor, p_document_id, 'MANAGE')
        and public.has_functional_permission(actor, 'MANAGE_DOCUMENT')
    ) then
        raise exception 'Historical source access is not permitted'
            using errcode = '42501';
    end if;

    select jsonb_build_object(
        'bucket_name', source_files.bucket_name,
        'object_path', source_files.object_path,
        'original_file_name', source_files.original_file_name,
        'mime_type', source_files.mime_type,
        'size_bytes', source_files.size_bytes,
        'sha256', source_files.sha256
    ) into source_payload
    from public.source_files
    where source_files.id = selected_version.source_file_id;
    return source_payload;
end;
$$;

revoke all on function public.get_document_version_source(uuid, uuid)
from public, anon;
grant execute on function public.get_document_version_source(uuid, uuid)
to authenticated;

create or replace function public.create_enterprise_conversation(
    p_title text default 'New chat'
)
returns public.enterprise_conversations
language plpgsql
security definer
set search_path = ''
as $$
declare
    actor uuid := auth.uid();
    created_conversation public.enterprise_conversations;
begin
    if actor is null
       or not public.has_functional_permission(actor, 'ASK_KNOWLEDGE') then
        raise exception 'Conversation creation is not permitted' using errcode = '42501';
    end if;
    insert into public.enterprise_conversations (user_id, title)
    values (actor, coalesce(nullif(btrim(p_title), ''), 'New chat'))
    returning * into created_conversation;
    return created_conversation;
end;
$$;

revoke all on function public.create_enterprise_conversation(text)
from public, anon;
grant execute on function public.create_enterprise_conversation(text)
to authenticated;

create or replace function public.get_enterprise_conversation(
    p_conversation_id uuid
)
returns jsonb
language plpgsql
stable
security definer
set search_path = ''
as $$
declare
    actor uuid := auth.uid();
    payload jsonb;
begin
    if actor is null then
        raise exception 'Authentication required' using errcode = '42501';
    end if;
    select jsonb_build_object(
        'conversation', to_jsonb(conversations),
        'messages', coalesce((
            select jsonb_agg(to_jsonb(messages) order by messages.created_at, messages.id)
            from public.enterprise_messages as messages
            where messages.conversation_id = conversations.id
        ), '[]'::jsonb)
    ) into payload
    from public.enterprise_conversations as conversations
    where conversations.id = p_conversation_id
      and conversations.user_id = actor;
    return payload;
end;
$$;

revoke all on function public.get_enterprise_conversation(uuid)
from public, anon;
grant execute on function public.get_enterprise_conversation(uuid)
to authenticated;

create or replace function public.append_enterprise_message(
    p_conversation_id uuid,
    p_role text,
    p_content text
)
returns public.enterprise_messages
language plpgsql
security definer
set search_path = ''
as $$
declare
    actor uuid := auth.uid();
    normalized_role text := upper(btrim(coalesce(p_role, '')));
    created_message public.enterprise_messages;
begin
    if actor is null or not exists (
        select 1
        from public.enterprise_conversations
        where id = p_conversation_id and user_id = actor
    ) then
        raise exception 'Conversation access is not permitted' using errcode = '42501';
    end if;
    if normalized_role not in ('USER', 'ASSISTANT', 'SYSTEM') then
        raise exception 'Invalid message role' using errcode = '22023';
    end if;
    insert into public.enterprise_messages (conversation_id, role, content)
    values (p_conversation_id, normalized_role, coalesce(p_content, ''))
    returning * into created_message;
    update public.enterprise_conversations
    set updated_at = now()
    where id = p_conversation_id;
    return created_message;
end;
$$;

revoke all on function public.append_enterprise_message(uuid, text, text)
from public, anon;
grant execute on function public.append_enterprise_message(uuid, text, text)
to authenticated;

create or replace function public.guard_answer_report_resolution()
returns trigger
language plpgsql
security definer
set search_path = ''
as $$
begin
    if row(
        new.message_id,
        new.reporter_user_id,
        new.reason_code,
        new.details,
        new.created_at
    ) is distinct from row(
        old.message_id,
        old.reporter_user_id,
        old.reason_code,
        old.details,
        old.created_at
    ) then
        raise exception 'Report evidence fields are immutable' using errcode = '55000';
    end if;
    if new.status in ('RESOLVED', 'DISMISSED') then
        new.resolved_by = auth.uid();
        new.resolved_at = now();
    else
        new.resolved_by = null;
        new.resolved_at = null;
        new.resolution_note = null;
    end if;
    return new;
end;
$$;

revoke all on function public.guard_answer_report_resolution()
from public, anon, authenticated;

drop trigger if exists answer_reports_guard_resolution on public.answer_reports;
create trigger answer_reports_guard_resolution
before update on public.answer_reports
for each row execute function public.guard_answer_report_resolution();

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
       or not public.has_functional_permission(actor, 'VIEW_AUDIT') then
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

comment on function public.publish_document_version(uuid) is
    'Atomic publish transaction: supersede old ACTIVE, activate reviewed candidate, update current_version_id, publication and audit.';
comment on function public.test_document_access(uuid, uuid, text) is
    'Evaluates the current DB membership graph; ACL revoke is effective on the next statement.';
