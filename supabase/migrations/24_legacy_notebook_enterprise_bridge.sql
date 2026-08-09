-- Keep the legacy notebook upload surface operational after the Enterprise
-- version-scoped ingestion cutover. Run after
-- 23_enterprise_workflow_completion.sql.
--
-- Migration 19 made ingestion_jobs.document_version_id mandatory. Existing
-- legacy documents were backfilled by migration 18, but documents uploaded
-- later through /notebooks/{id}/documents had no Enterprise version mapping.
-- The ingestion trigger therefore rejected their queue rows. This bridge
-- creates the fail-closed Enterprise draft/source/version records lazily in
-- the same transaction that enqueues the legacy document.

create or replace function public.ensure_legacy_document_enterprise_mapping(
    p_legacy_document_id uuid
)
returns uuid
language plpgsql
security definer
set search_path = ''
as $$
declare
    legacy_document public.documents;
    mapped_source public.source_files;
    logical_document public.knowledge_documents;
    mapped_version public.document_versions;
    previous_enterprise_version_id uuid;
    next_enterprise_version_number integer;
    owner_subject_id uuid;
begin
    select documents.*
    into legacy_document
    from public.documents as documents
    where documents.id = p_legacy_document_id
      and documents.is_active
    for update;

    if not found then
        raise exception 'Legacy document is not available for Enterprise mapping'
            using errcode = 'P0002';
    end if;

    -- Different legacy rows in one version family must choose version numbers
    -- serially even when uploads race.
    perform pg_catalog.pg_advisory_xact_lock(
        pg_catalog.hashtextextended(
            'legacy-enterprise-bridge:'
            || legacy_document.owner_id::text || ':'
            || legacy_document.notebook_id::text || ':'
            || legacy_document.version_group_id::text,
            0
        )
    );

    select versions.*
    into mapped_version
    from public.document_versions as versions
    where versions.legacy_document_id = legacy_document.id;

    if mapped_version.id is not null then
        return mapped_version.id;
    end if;

    insert into public.source_files (
        bucket_name,
        object_path,
        original_file_name,
        mime_type,
        size_bytes,
        sha256,
        created_by,
        created_at,
        legacy_document_id
    ) values (
        legacy_document.storage_bucket,
        legacy_document.storage_object_path,
        legacy_document.original_filename,
        legacy_document.mime_type,
        legacy_document.size_bytes,
        legacy_document.content_hash,
        legacy_document.owner_id,
        legacy_document.created_at,
        legacy_document.id
    )
    on conflict (legacy_document_id) do nothing;

    select source_files.*
    into mapped_source
    from public.source_files as source_files
    where source_files.legacy_document_id = legacy_document.id;

    if mapped_source.id is null then
        raise exception 'Legacy source file could not be mapped'
            using errcode = '23503';
    end if;

    insert into public.knowledge_documents (
        title,
        description,
        document_type,
        effective_date,
        status,
        metadata,
        created_by,
        created_at,
        updated_at,
        legacy_notebook_id,
        legacy_version_group_id
    ) values (
        legacy_document.original_filename,
        '',
        'GENERAL',
        legacy_document.effective_from,
        'DRAFT',
        jsonb_build_object(
            'migration', 'legacy_notebook_runtime_bridge_v1'
        ),
        legacy_document.owner_id,
        legacy_document.created_at,
        legacy_document.updated_at,
        legacy_document.notebook_id,
        legacy_document.version_group_id
    )
    on conflict (
        created_by,
        legacy_notebook_id,
        legacy_version_group_id
    ) where legacy_notebook_id is not null
        and legacy_version_group_id is not null
    do nothing;

    select documents.*
    into logical_document
    from public.knowledge_documents as documents
    where documents.created_by = legacy_document.owner_id
      and documents.legacy_notebook_id = legacy_document.notebook_id
      and documents.legacy_version_group_id = legacy_document.version_group_id
    for update;

    if logical_document.id is null then
        raise exception 'Legacy logical document could not be mapped'
            using errcode = '23503';
    end if;

    select versions.id
    into previous_enterprise_version_id
    from public.document_versions as versions
    where versions.legacy_document_id = legacy_document.supersedes_document_id
      and versions.document_id = logical_document.id;

    if previous_enterprise_version_id is null then
        select versions.id
        into previous_enterprise_version_id
        from public.document_versions as versions
        where versions.document_id = logical_document.id
        order by versions.version_number desc, versions.id
        limit 1;
    end if;

    select coalesce(max(versions.version_number), 0) + 1
    into next_enterprise_version_number
    from public.document_versions as versions
    where versions.document_id = logical_document.id;

    insert into public.document_versions (
        document_id,
        version_number,
        source_file_id,
        status,
        previous_version_id,
        change_summary,
        effective_date,
        created_by,
        created_at,
        updated_at,
        legacy_document_id
    ) values (
        logical_document.id,
        next_enterprise_version_number,
        mapped_source.id,
        'DRAFT',
        previous_enterprise_version_id,
        'Uploaded from the legacy notebook interface.',
        legacy_document.effective_from,
        legacy_document.owner_id,
        legacy_document.created_at,
        legacy_document.updated_at,
        legacy_document.id
    )
    returning * into mapped_version;

    select subjects.id
    into owner_subject_id
    from public.access_subjects as subjects
    where subjects.subject_type = 'USER'
      and subjects.user_id = legacy_document.owner_id;

    if owner_subject_id is null then
        raise exception 'Legacy document owner has no Enterprise access subject'
            using errcode = '23503';
    end if;

    insert into public.document_permissions (
        document_id,
        subject_id,
        permission,
        granted_by
    )
    select
        logical_document.id,
        owner_subject_id,
        permissions.permission,
        legacy_document.owner_id
    from (
        values
            ('READ'),
            ('DOWNLOAD'),
            ('MANAGE'),
            ('REVIEW'),
            ('PUBLISH'),
            ('ARCHIVE'),
            ('MANAGE_PERMISSION')
    ) as permissions(permission)
    on conflict (
        document_id,
        subject_id,
        permission
    ) where status = 'ACTIVE'
    do nothing;

    return mapped_version.id;
end;
$$;

revoke all on function public.ensure_legacy_document_enterprise_mapping(uuid)
from public, anon, authenticated;

create or replace function public.resolve_legacy_ingestion_version()
returns trigger
language plpgsql
security definer
set search_path = ''
as $$
begin
    if new.document_version_id is null then
        select versions.id into new.document_version_id
        from public.document_versions as versions
        where versions.legacy_document_id = new.document_id;
    end if;

    if new.document_version_id is null then
        new.document_version_id :=
            public.ensure_legacy_document_enterprise_mapping(new.document_id);
    end if;

    if new.document_version_id is null then
        raise exception 'No enterprise document version maps legacy document %', new.document_id
            using errcode = '23503';
    end if;
    return new;
end;
$$;

revoke all on function public.resolve_legacy_ingestion_version()
from public, anon, authenticated;

comment on function public.ensure_legacy_document_enterprise_mapping(uuid) is
    'Creates the fail-closed Enterprise draft/source/version/owner ACL mapping required before a legacy notebook document can enter ingestion.';
