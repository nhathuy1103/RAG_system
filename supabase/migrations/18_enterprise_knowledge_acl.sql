-- Enterprise logical-document, version, review/publication and ACL model.
-- Run after 17_enterprise_iam.sql.
--
-- Expand/cutover contract:
--   * public.documents remains the legacy immutable uploaded-file row.
--   * public.knowledge_documents is the new logical document.
--   * public.document_versions.legacy_document_id maps one legacy row to one
--     enterprise version while application code is migrated.
--   * no legacy row is automatically PUBLISHED or ACTIVE during backfill.

create table if not exists public.knowledge_documents (
    id uuid primary key default gen_random_uuid(),
    title text not null,
    description text not null default '',
    document_type text not null default 'GENERAL',
    category text,
    document_number text,
    issued_date date,
    effective_date date,
    expiration_date date,
    source text,
    owner_department_id uuid
        references public.departments (id) on delete restrict,
    status text not null default 'DRAFT',
    metadata jsonb not null default '{}'::jsonb,
    created_by uuid not null default auth.uid()
        references auth.users (id) on delete restrict,
    created_at timestamptz not null default now(),
    updated_at timestamptz not null default now(),
    archived_by uuid references auth.users (id) on delete set null,
    archived_at timestamptz,
    archive_reason text,
    legacy_notebook_id uuid
        references public.notebooks (id) on delete set null,
    legacy_version_group_id uuid,
    constraint knowledge_documents_title_length
        check (char_length(btrim(title)) between 1 and 500),
    constraint knowledge_documents_type_length
        check (char_length(btrim(document_type)) between 1 and 100),
    constraint knowledge_documents_status
        check (status in ('DRAFT', 'PUBLISHED', 'ARCHIVED')),
    constraint knowledge_documents_metadata
        check (jsonb_typeof(metadata) = 'object'),
    constraint knowledge_documents_effective_range
        check (
            effective_date is null
            or expiration_date is null
            or effective_date <= expiration_date
        ),
    constraint knowledge_documents_archive_state check (
        (
            status = 'ARCHIVED'
            and archived_at is not null
            and archived_by is not null
            and archive_reason is not null
            and char_length(btrim(archive_reason)) > 0
        )
        or (
            status <> 'ARCHIVED'
            and archived_at is null
            and archived_by is null
            and archive_reason is null
        )
    )
);

create unique index if not exists knowledge_documents_legacy_lineage_key
    on public.knowledge_documents (
        created_by,
        legacy_notebook_id,
        legacy_version_group_id
    )
    where legacy_notebook_id is not null
      and legacy_version_group_id is not null;
create index if not exists knowledge_documents_status_idx
    on public.knowledge_documents (status, updated_at desc, id);
create index if not exists knowledge_documents_department_idx
    on public.knowledge_documents (owner_department_id, status, id)
    where owner_department_id is not null;

create table if not exists public.source_files (
    id uuid primary key default gen_random_uuid(),
    bucket_name text not null,
    object_path text not null,
    original_file_name text not null,
    mime_type text not null,
    size_bytes bigint not null,
    sha256 text,
    created_by uuid not null default auth.uid()
        references auth.users (id) on delete restrict,
    created_at timestamptz not null default now(),
    legacy_document_id uuid unique
        references public.documents (id) on delete set null,
    constraint source_files_object_key unique (bucket_name, object_path),
    constraint source_files_name_length
        check (char_length(btrim(original_file_name)) between 1 and 500),
    constraint source_files_bucket_length
        check (char_length(btrim(bucket_name)) between 1 and 100),
    constraint source_files_object_path_length
        check (char_length(btrim(object_path)) between 1 and 2048),
    constraint source_files_size check (size_bytes > 0),
    constraint source_files_sha256
        check (sha256 is null or sha256 ~ '^[0-9a-f]{64}$')
);

create index if not exists source_files_sha256_idx
    on public.source_files (sha256) where sha256 is not null;
create index if not exists source_files_created_by_idx
    on public.source_files (created_by, created_at desc, id);

create table if not exists public.document_versions (
    id uuid primary key default gen_random_uuid(),
    document_id uuid not null
        references public.knowledge_documents (id) on delete cascade,
    version_number integer not null,
    source_file_id uuid not null
        references public.source_files (id) on delete restrict,
    status text not null default 'DRAFT',
    previous_version_id uuid,
    change_summary text not null default '',
    effective_date date,
    created_by uuid not null default auth.uid()
        references auth.users (id) on delete restrict,
    created_at timestamptz not null default now(),
    updated_at timestamptz not null default now(),
    legacy_document_id uuid unique
        references public.documents (id) on delete set null,
    constraint document_versions_number check (version_number > 0),
    constraint document_versions_status check (
        status in (
            'DRAFT',
            'READY_FOR_REVIEW',
            'ACTIVE',
            'REJECTED',
            'SUPERSEDED'
        )
    ),
    constraint document_versions_document_number_key
        unique (document_id, version_number),
    constraint document_versions_id_document_key unique (id, document_id),
    constraint document_versions_previous_not_self
        check (previous_version_id is null or previous_version_id <> id),
    constraint document_versions_previous_same_document_fk
        foreign key (previous_version_id, document_id)
        references public.document_versions (id, document_id)
        deferrable initially deferred
);

create unique index if not exists document_versions_one_active_per_document_idx
    on public.document_versions (document_id)
    where status = 'ACTIVE';
create index if not exists document_versions_document_created_idx
    on public.document_versions (document_id, version_number desc, id);
create index if not exists document_versions_source_file_idx
    on public.document_versions (source_file_id);

alter table public.knowledge_documents
    add column if not exists current_version_id uuid;

do $$
begin
    if not exists (
        select 1
        from pg_constraint
        where conrelid = 'public.knowledge_documents'::regclass
          and conname = 'knowledge_documents_current_version_same_document_fk'
    ) then
        alter table public.knowledge_documents
            add constraint knowledge_documents_current_version_same_document_fk
            foreign key (current_version_id, id)
            references public.document_versions (id, document_id)
            deferrable initially deferred;
    end if;
end;
$$;

drop trigger if exists knowledge_documents_set_updated_at
on public.knowledge_documents;
create trigger knowledge_documents_set_updated_at
before update on public.knowledge_documents
for each row execute function public.set_enterprise_updated_at();

drop trigger if exists document_versions_set_updated_at
on public.document_versions;
create trigger document_versions_set_updated_at
before update on public.document_versions
for each row execute function public.set_enterprise_updated_at();

create table if not exists public.document_version_status_history (
    id bigint generated always as identity primary key,
    document_version_id uuid not null
        references public.document_versions (id) on delete cascade,
    old_status text,
    new_status text not null,
    changed_by uuid references auth.users (id) on delete set null,
    changed_at timestamptz not null default now(),
    reason text,
    constraint document_version_status_history_old_status check (
        old_status is null
        or old_status in (
            'DRAFT', 'READY_FOR_REVIEW', 'ACTIVE', 'REJECTED', 'SUPERSEDED'
        )
    ),
    constraint document_version_status_history_new_status check (
        new_status in (
            'DRAFT', 'READY_FOR_REVIEW', 'ACTIVE', 'REJECTED', 'SUPERSEDED'
        )
    ),
    constraint document_version_status_history_changed
        check (old_status is distinct from new_status)
);

create index if not exists document_version_status_history_version_idx
    on public.document_version_status_history (
        document_version_id,
        changed_at desc,
        id desc
    );

create or replace function public.record_document_version_status_change()
returns trigger
language plpgsql
security definer
set search_path = ''
as $$
begin
    if tg_op = 'INSERT' then
        insert into public.document_version_status_history (
            document_version_id, old_status, new_status, changed_by, reason
        ) values (
            new.id,
            null,
            new.status,
            auth.uid(),
            nullif(current_setting('app.status_change_reason', true), '')
        );
    elsif old.status is distinct from new.status then
        insert into public.document_version_status_history (
            document_version_id, old_status, new_status, changed_by, reason
        ) values (
            new.id,
            old.status,
            new.status,
            auth.uid(),
            nullif(current_setting('app.status_change_reason', true), '')
        );
    end if;
    return new;
end;
$$;

revoke all on function public.record_document_version_status_change()
from public, anon, authenticated;

drop trigger if exists document_versions_record_status
on public.document_versions;
create trigger document_versions_record_status
after insert or update of status on public.document_versions
for each row execute function public.record_document_version_status_change();

create table if not exists public.document_reviews (
    id uuid primary key default gen_random_uuid(),
    document_version_id uuid not null
        references public.document_versions (id) on delete cascade,
    reviewed_by uuid not null default auth.uid()
        references auth.users (id) on delete restrict,
    decision text not null,
    review_note text,
    rejection_reason text,
    reviewed_at timestamptz not null default now(),
    constraint document_reviews_decision
        check (decision in ('APPROVE', 'REJECT', 'REPROCESS')),
    constraint document_reviews_rejection_reason check (
        (decision = 'REJECT' and rejection_reason is not null
            and char_length(btrim(rejection_reason)) > 0)
        or (decision <> 'REJECT' and rejection_reason is null)
    )
);

create index if not exists document_reviews_version_reviewed_idx
    on public.document_reviews (document_version_id, reviewed_at desc, id);

create table if not exists public.publications (
    id uuid primary key default gen_random_uuid(),
    document_id uuid not null
        references public.knowledge_documents (id) on delete restrict,
    document_version_id uuid not null,
    previous_active_version_id uuid,
    published_by uuid not null default auth.uid()
        references auth.users (id) on delete restrict,
    published_at timestamptz not null default now(),
    constraint publications_version_same_document_fk
        foreign key (document_version_id, document_id)
        references public.document_versions (id, document_id)
        on delete restrict,
    constraint publications_previous_version_same_document_fk
        foreign key (previous_active_version_id, document_id)
        references public.document_versions (id, document_id)
        on delete restrict,
    constraint publications_target_key unique (document_version_id),
    constraint publications_versions_differ
        check (
            previous_active_version_id is null
            or previous_active_version_id <> document_version_id
        )
);

create index if not exists publications_document_published_idx
    on public.publications (document_id, published_at desc, id);

create table if not exists public.document_permissions (
    id uuid primary key default gen_random_uuid(),
    document_id uuid not null
        references public.knowledge_documents (id) on delete cascade,
    subject_id uuid not null
        references public.access_subjects (id) on delete cascade,
    permission text not null,
    status text not null default 'ACTIVE',
    granted_by uuid not null default auth.uid()
        references auth.users (id) on delete restrict,
    granted_at timestamptz not null default now(),
    revoked_by uuid references auth.users (id) on delete set null,
    revoked_at timestamptz,
    constraint document_permissions_permission check (
        permission in (
            'READ',
            'DOWNLOAD',
            'MANAGE',
            'REVIEW',
            'PUBLISH',
            'ARCHIVE',
            'MANAGE_PERMISSION'
        )
    ),
    constraint document_permissions_status
        check (status in ('ACTIVE', 'REVOKED')),
    constraint document_permissions_revocation_state check (
        (
            status = 'ACTIVE'
            and revoked_by is null
            and revoked_at is null
        )
        or (
            status = 'REVOKED'
            and revoked_by is not null
            and revoked_at is not null
        )
    )
);

create unique index if not exists document_permissions_one_active_assignment_idx
    on public.document_permissions (document_id, subject_id, permission)
    where status = 'ACTIVE';
create index if not exists document_permissions_subject_document_idx
    on public.document_permissions (subject_id, document_id, permission)
    where status = 'ACTIVE';
create index if not exists document_permissions_document_idx
    on public.document_permissions (document_id, status, permission);

-- -------------------------------------------------------------------------
-- Compatibility backfill.  A lineage becomes one logical document.  Every
-- legacy file becomes one source file and one version.  ready files are only
-- READY_FOR_REVIEW; all other states remain DRAFT.  This fail-closed mapping
-- prevents an old private upload from becoming enterprise-searchable.
-- -------------------------------------------------------------------------

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
)
select
    documents.storage_bucket,
    documents.storage_object_path,
    documents.original_filename,
    documents.mime_type,
    documents.size_bytes,
    documents.content_hash,
    documents.owner_id,
    documents.created_at,
    documents.id
from public.documents
on conflict (legacy_document_id) do nothing;

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
)
select
    (array_agg(
        documents.original_filename
        order by documents.version_number desc, documents.created_at desc, documents.id
    ))[1],
    '',
    coalesce(
        nullif((array_agg(
            documents.quality_metadata ->> 'document_type'
            order by documents.version_number desc, documents.created_at desc, documents.id
        ))[1], ''),
        'GENERAL'
    ),
    max(documents.effective_from),
    'DRAFT',
    jsonb_build_object(
        'migration', 'legacy_documents_expand_v1',
        'legacy_document_count', count(*)
    ),
    documents.owner_id,
    min(documents.created_at),
    max(documents.updated_at),
    documents.notebook_id,
    documents.version_group_id
from public.documents
group by documents.owner_id, documents.notebook_id, documents.version_group_id
on conflict (
    created_by, legacy_notebook_id, legacy_version_group_id
) where legacy_notebook_id is not null
    and legacy_version_group_id is not null
do nothing;

with ranked_legacy_versions as (
    select
        documents.*,
        row_number() over (
            partition by documents.owner_id, documents.notebook_id, documents.version_group_id
            order by documents.version_number, documents.created_at, documents.id
        )::integer as enterprise_version_number
    from public.documents
)
insert into public.document_versions (
    document_id,
    version_number,
    source_file_id,
    status,
    change_summary,
    effective_date,
    created_by,
    created_at,
    updated_at,
    legacy_document_id
)
select
    knowledge_documents.id,
    ranked_legacy_versions.enterprise_version_number,
    source_files.id,
    case
        when ranked_legacy_versions.status = 'ready' then 'READY_FOR_REVIEW'
        else 'DRAFT'
    end,
    case
        when ranked_legacy_versions.version_number
             <> ranked_legacy_versions.enterprise_version_number
        then 'Migrated from legacy version label '
             || ranked_legacy_versions.version_number::text || '.'
        else 'Migrated from the legacy notebook model.'
    end,
    ranked_legacy_versions.effective_from,
    ranked_legacy_versions.owner_id,
    ranked_legacy_versions.created_at,
    ranked_legacy_versions.updated_at,
    ranked_legacy_versions.id
from ranked_legacy_versions
join public.knowledge_documents
  on knowledge_documents.created_by = ranked_legacy_versions.owner_id
 and knowledge_documents.legacy_notebook_id = ranked_legacy_versions.notebook_id
 and knowledge_documents.legacy_version_group_id = ranked_legacy_versions.version_group_id
join public.source_files
  on source_files.legacy_document_id = ranked_legacy_versions.id
on conflict (legacy_document_id) do nothing;

update public.document_versions as versions
set previous_version_id = previous_versions.id
from public.documents as legacy_documents
join public.document_versions as previous_versions
  on previous_versions.legacy_document_id = legacy_documents.supersedes_document_id
where versions.legacy_document_id = legacy_documents.id
  and versions.document_id = previous_versions.document_id
  and versions.previous_version_id is null;

-- Preserve legacy owner access without publishing anything.  This is the
-- only compatibility grant; every other user remains default-denied.
insert into public.document_permissions (
    document_id, subject_id, permission, granted_by
)
select
    knowledge_documents.id,
    access_subjects.id,
    permissions.permission,
    knowledge_documents.created_by
from public.knowledge_documents
join public.access_subjects
  on access_subjects.subject_type = 'USER'
 and access_subjects.user_id = knowledge_documents.created_by
cross join (
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
    document_id, subject_id, permission
) where status = 'ACTIVE'
do nothing;

comment on table public.knowledge_documents is
    'Enterprise logical documents. public.documents remains the legacy uploaded-file table during cutover.';
comment on table public.document_versions is
    'Immutable-source business versions; at most one ACTIVE version is enforced by a partial unique index.';
comment on column public.document_versions.legacy_document_id is
    'Expand-phase compatibility link; nullable after the application cuts over to enterprise uploads.';
comment on table public.document_permissions is
    'ALLOW-only document ACL history. Absence of an ACTIVE grant means DENY.';
