-- Enterprise IAM/RBAC foundation (expand phase).
--
-- This migration is intentionally additive.  public.profiles remains the
-- compatibility profile used by the legacy notebook application and JWT hook;
-- public.user_profiles is the enterprise business profile.

create table if not exists public.user_profiles (
    user_id uuid primary key
        references auth.users (id) on delete cascade,
    company_user_id text unique,
    full_name text,
    status text not null default 'ACTIVE',
    created_at timestamptz not null default now(),
    updated_at timestamptz not null default now(),
    constraint user_profiles_company_user_id_length
        check (
            company_user_id is null
            or char_length(btrim(company_user_id)) between 1 and 100
        ),
    constraint user_profiles_full_name_length
        check (
            full_name is null
            or char_length(btrim(full_name)) between 1 and 200
        ),
    constraint user_profiles_status
        check (status in ('ACTIVE', 'LOCKED', 'DISABLED'))
);

create table if not exists public.roles (
    id uuid primary key default gen_random_uuid(),
    code text not null unique,
    name text not null,
    description text not null default '',
    status text not null default 'ACTIVE',
    created_at timestamptz not null default now(),
    updated_at timestamptz not null default now(),
    constraint roles_code_format
        check (code ~ '^[A-Z][A-Z0-9_]{1,99}$'),
    constraint roles_name_length
        check (char_length(btrim(name)) between 1 and 200),
    constraint roles_status
        check (status in ('ACTIVE', 'DISABLED'))
);

create table if not exists public.functional_permissions (
    id uuid primary key default gen_random_uuid(),
    code text not null unique,
    name text not null,
    description text not null default '',
    created_at timestamptz not null default now(),
    constraint functional_permissions_code_format
        check (code ~ '^[A-Z][A-Z0-9_]{1,99}$'),
    constraint functional_permissions_name_length
        check (char_length(btrim(name)) between 1 and 200)
);

create table if not exists public.user_roles (
    id uuid primary key default gen_random_uuid(),
    user_id uuid not null
        references auth.users (id) on delete cascade,
    role_id uuid not null
        references public.roles (id) on delete cascade,
    assigned_by uuid
        references auth.users (id) on delete set null,
    assigned_at timestamptz not null default now(),
    constraint user_roles_assignment_key unique (user_id, role_id)
);

create table if not exists public.role_permissions (
    id uuid primary key default gen_random_uuid(),
    role_id uuid not null
        references public.roles (id) on delete cascade,
    permission_id uuid not null
        references public.functional_permissions (id) on delete cascade,
    assigned_by uuid
        references auth.users (id) on delete set null,
    assigned_at timestamptz not null default now(),
    constraint role_permissions_assignment_key
        unique (role_id, permission_id)
);

create table if not exists public.groups (
    id uuid primary key default gen_random_uuid(),
    code text not null unique,
    name text not null,
    description text not null default '',
    status text not null default 'ACTIVE',
    created_at timestamptz not null default now(),
    updated_at timestamptz not null default now(),
    constraint groups_code_format
        check (code ~ '^[A-Z][A-Z0-9_]{1,99}$'),
    constraint groups_name_length
        check (char_length(btrim(name)) between 1 and 200),
    constraint groups_status
        check (status in ('ACTIVE', 'DISABLED'))
);

create table if not exists public.user_groups (
    id uuid primary key default gen_random_uuid(),
    user_id uuid not null
        references auth.users (id) on delete cascade,
    group_id uuid not null
        references public.groups (id) on delete cascade,
    added_by uuid
        references auth.users (id) on delete set null,
    joined_at timestamptz not null default now(),
    constraint user_groups_membership_key unique (user_id, group_id)
);

create table if not exists public.departments (
    id uuid primary key default gen_random_uuid(),
    code text not null unique,
    name text not null,
    description text not null default '',
    parent_department_id uuid
        references public.departments (id) on delete restrict,
    status text not null default 'ACTIVE',
    created_at timestamptz not null default now(),
    updated_at timestamptz not null default now(),
    constraint departments_code_format
        check (code ~ '^[A-Z][A-Z0-9_]{1,99}$'),
    constraint departments_name_length
        check (char_length(btrim(name)) between 1 and 200),
    constraint departments_not_self
        check (parent_department_id is null or parent_department_id <> id),
    constraint departments_status
        check (status in ('ACTIVE', 'DISABLED'))
);

create table if not exists public.user_departments (
    id uuid primary key default gen_random_uuid(),
    user_id uuid not null
        references auth.users (id) on delete cascade,
    department_id uuid not null
        references public.departments (id) on delete restrict,
    is_primary boolean not null default false,
    start_at timestamptz not null default now(),
    end_at timestamptz,
    assigned_by uuid
        references auth.users (id) on delete set null,
    constraint user_departments_effective_range
        check (end_at is null or start_at < end_at),
    constraint user_departments_membership_key
        unique (user_id, department_id, start_at)
);

create unique index if not exists user_departments_one_current_primary_idx
    on public.user_departments (user_id)
    where is_primary and end_at is null;
create index if not exists user_roles_user_idx
    on public.user_roles (user_id, role_id);
create index if not exists user_groups_user_idx
    on public.user_groups (user_id, group_id);
create index if not exists user_departments_user_effective_idx
    on public.user_departments (user_id, start_at, end_at);

-- A typed subject row preserves referential integrity for document ACLs.
create table if not exists public.access_subjects (
    id uuid primary key default gen_random_uuid(),
    subject_type text not null,
    user_id uuid references auth.users (id) on delete cascade,
    role_id uuid references public.roles (id) on delete cascade,
    group_id uuid references public.groups (id) on delete cascade,
    department_id uuid references public.departments (id) on delete cascade,
    created_at timestamptz not null default now(),
    constraint access_subjects_typed_identity check (
        (
            subject_type = 'USER'
            and user_id is not null
            and role_id is null and group_id is null and department_id is null
        )
        or (
            subject_type = 'ROLE'
            and role_id is not null
            and user_id is null and group_id is null and department_id is null
        )
        or (
            subject_type = 'GROUP'
            and group_id is not null
            and user_id is null and role_id is null and department_id is null
        )
        or (
            subject_type = 'DEPARTMENT'
            and department_id is not null
            and user_id is null and role_id is null and group_id is null
        )
    )
);

create unique index if not exists access_subjects_user_key
    on public.access_subjects (user_id) where subject_type = 'USER';
create unique index if not exists access_subjects_role_key
    on public.access_subjects (role_id) where subject_type = 'ROLE';
create unique index if not exists access_subjects_group_key
    on public.access_subjects (group_id) where subject_type = 'GROUP';
create unique index if not exists access_subjects_department_key
    on public.access_subjects (department_id) where subject_type = 'DEPARTMENT';

create or replace function public.set_enterprise_updated_at()
returns trigger
language plpgsql
set search_path = ''
as $$
begin
    new.updated_at = now();
    return new;
end;
$$;

revoke all on function public.set_enterprise_updated_at() from public, anon, authenticated;

drop trigger if exists user_profiles_set_updated_at on public.user_profiles;
create trigger user_profiles_set_updated_at
before update on public.user_profiles
for each row execute function public.set_enterprise_updated_at();

drop trigger if exists roles_set_updated_at on public.roles;
create trigger roles_set_updated_at
before update on public.roles
for each row execute function public.set_enterprise_updated_at();

drop trigger if exists groups_set_updated_at on public.groups;
create trigger groups_set_updated_at
before update on public.groups
for each row execute function public.set_enterprise_updated_at();

drop trigger if exists departments_set_updated_at on public.departments;
create trigger departments_set_updated_at
before update on public.departments
for each row execute function public.set_enterprise_updated_at();

-- A direct-parent check is not enough for an organizational tree: A -> B -> C
-- followed by A.parent = C would otherwise create a multi-node cycle.  Reject
-- the write before it can poison recursive ACL expansion.
create or replace function public.guard_enterprise_department_cycle()
returns trigger
language plpgsql
security definer
set search_path = ''
as $$
begin
    if new.parent_department_id is null then
        return new;
    end if;

    -- Serialize hierarchy-edge writes so two concurrent updates cannot each
    -- validate against a pre-cycle snapshot and then commit a cycle together.
    perform pg_catalog.pg_advisory_xact_lock(
        pg_catalog.hashtextextended('enterprise_department_hierarchy', 0)
    );

    if exists (
        with recursive ancestors(id, parent_department_id) as (
            select departments.id, departments.parent_department_id
            from public.departments
            where departments.id = new.parent_department_id

            union

            select departments.id, departments.parent_department_id
            from public.departments as departments
            join ancestors
              on departments.id = ancestors.parent_department_id
        )
        select 1
        from ancestors
        where ancestors.id = new.id
    ) then
        raise exception 'Department hierarchy cannot contain a cycle'
            using errcode = '23514';
    end if;
    return new;
end;
$$;

revoke all on function public.guard_enterprise_department_cycle()
from public, anon, authenticated;

drop trigger if exists departments_guard_cycle on public.departments;
create trigger departments_guard_cycle
before insert or update of parent_department_id on public.departments
for each row execute function public.guard_enterprise_department_cycle();

-- Existing identities are expanded into the enterprise profile without
-- changing the legacy JWT role contract.
insert into public.user_profiles (user_id, full_name)
select users.id, profiles.display_name
from auth.users as users
left join public.profiles as profiles on profiles.id = users.id
on conflict (user_id) do nothing;

insert into public.roles (code, name, description)
values
    ('ADMIN', 'Administrator', 'Enterprise administration capabilities.'),
    ('EMPLOYEE', 'Employee', 'Knowledge consumer capabilities.'),
    ('DOCUMENT_REVIEWER', 'Document reviewer', 'Document review capabilities.')
on conflict (code) do nothing;

insert into public.functional_permissions (code, name, description)
values
    ('ASK_KNOWLEDGE', 'Ask knowledge', 'Search and ask grounded questions.'),
    ('MANAGE_DOCUMENT', 'Manage document', 'Create and maintain logical documents.'),
    ('UPLOAD_DOCUMENT', 'Upload document', 'Upload document source files.'),
    ('REVIEW_DOCUMENT', 'Review document', 'Approve, reject or request reprocessing.'),
    ('PUBLISH_DOCUMENT', 'Publish document', 'Activate reviewed document versions.'),
    ('ARCHIVE_DOCUMENT', 'Archive document', 'Archive published or draft documents.'),
    ('MANAGE_USER', 'Manage user', 'Manage enterprise user profiles.'),
    ('MANAGE_ROLE', 'Manage role', 'Manage roles and functional permissions.'),
    ('MANAGE_GROUP', 'Manage group', 'Manage groups and membership.'),
    ('MANAGE_DEPARTMENT', 'Manage department', 'Manage department hierarchy.'),
    ('MANAGE_ACCESS_POLICY', 'Manage access policy', 'Grant and revoke document ACLs.'),
    ('VIEW_AUDIT', 'View audit', 'View enterprise governance audit records.')
on conflict (code) do nothing;

insert into public.role_permissions (role_id, permission_id)
select roles.id, permissions.id
from public.roles as roles
cross join public.functional_permissions as permissions
where roles.code = 'ADMIN'
on conflict (role_id, permission_id) do nothing;

insert into public.role_permissions (role_id, permission_id)
select roles.id, permissions.id
from public.roles as roles
join public.functional_permissions as permissions
  on permissions.code = 'ASK_KNOWLEDGE'
where roles.code = 'EMPLOYEE'
on conflict (role_id, permission_id) do nothing;

insert into public.role_permissions (role_id, permission_id)
select roles.id, permissions.id
from public.roles as roles
join public.functional_permissions as permissions
  on permissions.code in ('ASK_KNOWLEDGE', 'REVIEW_DOCUMENT')
where roles.code = 'DOCUMENT_REVIEWER'
on conflict (role_id, permission_id) do nothing;

-- Preserve the legacy admin/user assignment as an initial RBAC assignment.
insert into public.user_roles (user_id, role_id)
select profiles.id, roles.id
from public.profiles as profiles
join public.roles as roles
  on roles.code = case when profiles.role = 'admin' then 'ADMIN' else 'EMPLOYEE' end
on conflict (user_id, role_id) do nothing;

insert into public.user_roles (user_id, role_id)
select user_profiles.user_id, roles.id
from public.user_profiles
cross join public.roles
where roles.code = 'EMPLOYEE'
  and not exists (
      select 1
      from public.user_roles
      where user_roles.user_id = user_profiles.user_id
  )
on conflict (user_id, role_id) do nothing;

-- System roles are stable identifiers used by the compatibility bridge and by
-- recovery procedures. They may be renamed descriptively, but their code,
-- active state and identity must not be destroyed through an application API.
create or replace function public.protect_enterprise_system_role()
returns trigger
language plpgsql
security definer
set search_path = ''
as $$
begin
    if old.code in ('ADMIN', 'EMPLOYEE', 'DOCUMENT_REVIEWER') then
        if tg_op = 'DELETE' then
            raise exception 'Enterprise system roles cannot be deleted, recoded or disabled'
                using errcode = '55000';
        end if;
        if new.id is distinct from old.id
           or new.code is distinct from old.code
           or new.status <> 'ACTIVE' then
            raise exception 'Enterprise system roles cannot be deleted, recoded or disabled'
                using errcode = '55000';
        end if;
    end if;
    if tg_op = 'DELETE' then
        return old;
    end if;
    return new;
end;
$$;

revoke all on function public.protect_enterprise_system_role()
from public, anon, authenticated;

drop trigger if exists roles_protect_system_role on public.roles;
create trigger roles_protect_system_role
before update or delete on public.roles
for each row execute function public.protect_enterprise_system_role();

create or replace function public.prevent_enterprise_iam_root_delete()
returns trigger
language plpgsql
security definer
set search_path = ''
as $$
begin
    raise exception 'Enterprise IAM root entities must be disabled, not deleted'
        using errcode = '55000';
end;
$$;

revoke all on function public.prevent_enterprise_iam_root_delete()
from public, anon, authenticated;

drop trigger if exists roles_prevent_root_delete on public.roles;
create trigger roles_prevent_root_delete
before delete on public.roles
for each row execute function public.prevent_enterprise_iam_root_delete();

drop trigger if exists groups_prevent_root_delete on public.groups;
create trigger groups_prevent_root_delete
before delete on public.groups
for each row execute function public.prevent_enterprise_iam_root_delete();

drop trigger if exists departments_prevent_root_delete on public.departments;
create trigger departments_prevent_root_delete
before delete on public.departments
for each row execute function public.prevent_enterprise_iam_root_delete();

-- The ADMIN role is the recovery root. Removing one of its permission edges
-- can silently lock every administrator out, so those seeded edges are fixed.
create or replace function public.protect_enterprise_admin_permissions()
returns trigger
language plpgsql
security definer
set search_path = ''
as $$
begin
    if exists (
        select 1
        from public.roles
        where roles.id = old.role_id
          and roles.code = 'ADMIN'
    ) then
        raise exception 'ADMIN permissions cannot be removed or reassigned'
            using errcode = '55000';
    end if;
    if tg_op = 'DELETE' then
        return old;
    end if;
    return new;
end;
$$;

revoke all on function public.protect_enterprise_admin_permissions()
from public, anon, authenticated;

drop trigger if exists role_permissions_protect_admin
on public.role_permissions;
create trigger role_permissions_protect_admin
before update or delete on public.role_permissions
for each row execute function public.protect_enterprise_admin_permissions();

-- Preserve at least one ACTIVE identity assigned to ADMIN. This guard covers
-- both assignment removal and profile lock/disable, including service-role
-- maintenance paths that bypass RLS.
create or replace function public.protect_last_enterprise_admin_assignment()
returns trigger
language plpgsql
security definer
set search_path = ''
as $$
declare
    old_is_active_admin boolean;
    new_is_active_admin boolean := false;
begin
    select exists (
        select 1
        from public.roles
        join public.user_profiles
          on user_profiles.user_id = old.user_id
        where roles.id = old.role_id
          and roles.code = 'ADMIN'
          and user_profiles.status = 'ACTIVE'
    ) into old_is_active_admin;

    if not old_is_active_admin then
        if tg_op = 'DELETE' then
            return old;
        end if;
        return new;
    end if;

    perform 1
    from public.roles
    where roles.code = 'ADMIN'
    for update;

    if tg_op = 'UPDATE' then
        select exists (
            select 1
            from public.roles
            join public.user_profiles
              on user_profiles.user_id = new.user_id
            where roles.id = new.role_id
              and roles.code = 'ADMIN'
              and user_profiles.status = 'ACTIVE'
        ) into new_is_active_admin;
    end if;

    if not new_is_active_admin and not exists (
        select 1
        from public.user_roles as assignments
        join public.roles as roles
          on roles.id = assignments.role_id
         and roles.code = 'ADMIN'
        join public.user_profiles as profiles
          on profiles.user_id = assignments.user_id
         and profiles.status = 'ACTIVE'
        where assignments.id <> old.id
    ) then
        raise exception 'At least one ACTIVE enterprise administrator is required'
            using errcode = '55000';
    end if;

    if tg_op = 'DELETE' then
        return old;
    end if;
    return new;
end;
$$;

revoke all on function public.protect_last_enterprise_admin_assignment()
from public, anon, authenticated;

drop trigger if exists user_roles_protect_last_admin on public.user_roles;
create trigger user_roles_protect_last_admin
before update or delete on public.user_roles
for each row execute function public.protect_last_enterprise_admin_assignment();

create or replace function public.protect_last_enterprise_admin_profile()
returns trigger
language plpgsql
security definer
set search_path = ''
as $$
declare
    loses_active_status boolean;
begin
    if tg_op = 'DELETE' then
        loses_active_status := true;
    else
        loses_active_status := new.status <> 'ACTIVE';
    end if;

    if old.status = 'ACTIVE'
       and loses_active_status
       and exists (
           select 1
           from public.user_roles
           join public.roles on roles.id = user_roles.role_id
           where user_roles.user_id = old.user_id
             and roles.code = 'ADMIN'
       ) then
        perform 1
        from public.roles
        where roles.code = 'ADMIN'
        for update;

        if not exists (
           select 1
           from public.user_roles
           join public.roles on roles.id = user_roles.role_id
           join public.user_profiles
             on user_profiles.user_id = user_roles.user_id
           where roles.code = 'ADMIN'
             and user_profiles.status = 'ACTIVE'
             and user_profiles.user_id <> old.user_id
        ) then
            raise exception 'At least one ACTIVE enterprise administrator is required'
                using errcode = '55000';
        end if;
    end if;
    if tg_op = 'DELETE' then
        return old;
    end if;
    return new;
end;
$$;

revoke all on function public.protect_last_enterprise_admin_profile()
from public, anon, authenticated;

drop trigger if exists user_profiles_protect_last_admin on public.user_profiles;
create trigger user_profiles_protect_last_admin
before update of status on public.user_profiles
for each row execute function public.protect_last_enterprise_admin_profile();

drop trigger if exists user_profiles_protect_last_admin_delete
on public.user_profiles;
create trigger user_profiles_protect_last_admin_delete
before delete on public.user_profiles
for each row execute function public.protect_last_enterprise_admin_profile();

insert into public.access_subjects (subject_type, user_id)
select 'USER', user_profiles.user_id
from public.user_profiles
on conflict (user_id) where subject_type = 'USER' do nothing;

insert into public.access_subjects (subject_type, role_id)
select 'ROLE', roles.id from public.roles
on conflict (role_id) where subject_type = 'ROLE' do nothing;

insert into public.access_subjects (subject_type, group_id)
select 'GROUP', groups.id from public.groups
on conflict (group_id) where subject_type = 'GROUP' do nothing;

insert into public.access_subjects (subject_type, department_id)
select 'DEPARTMENT', departments.id from public.departments
on conflict (department_id) where subject_type = 'DEPARTMENT' do nothing;

create or replace function public.ensure_enterprise_access_subject()
returns trigger
language plpgsql
security definer
set search_path = ''
as $$
begin
    if tg_table_name = 'user_profiles' then
        insert into public.access_subjects (subject_type, user_id)
        values ('USER', new.user_id)
        on conflict (user_id) where subject_type = 'USER' do nothing;
    elsif tg_table_name = 'roles' then
        insert into public.access_subjects (subject_type, role_id)
        values ('ROLE', new.id)
        on conflict (role_id) where subject_type = 'ROLE' do nothing;
    elsif tg_table_name = 'groups' then
        insert into public.access_subjects (subject_type, group_id)
        values ('GROUP', new.id)
        on conflict (group_id) where subject_type = 'GROUP' do nothing;
    elsif tg_table_name = 'departments' then
        insert into public.access_subjects (subject_type, department_id)
        values ('DEPARTMENT', new.id)
        on conflict (department_id) where subject_type = 'DEPARTMENT' do nothing;
    end if;
    return new;
end;
$$;

revoke all on function public.ensure_enterprise_access_subject()
from public, anon, authenticated;

drop trigger if exists user_profiles_ensure_access_subject on public.user_profiles;
create trigger user_profiles_ensure_access_subject
after insert on public.user_profiles
for each row execute function public.ensure_enterprise_access_subject();

drop trigger if exists roles_ensure_access_subject on public.roles;
create trigger roles_ensure_access_subject
after insert on public.roles
for each row execute function public.ensure_enterprise_access_subject();

drop trigger if exists groups_ensure_access_subject on public.groups;
create trigger groups_ensure_access_subject
after insert on public.groups
for each row execute function public.ensure_enterprise_access_subject();

drop trigger if exists departments_ensure_access_subject on public.departments;
create trigger departments_ensure_access_subject
after insert on public.departments
for each row execute function public.ensure_enterprise_access_subject();

-- The legacy signup trigger inserts public.profiles.  Mirroring that row keeps
-- future signups in the enterprise identity model without replacing the
-- existing auth hook during the expand phase.
create or replace function public.sync_legacy_profile_to_enterprise()
returns trigger
language plpgsql
security definer
set search_path = ''
as $$
begin
    insert into public.user_profiles (user_id, full_name)
    values (new.id, new.display_name)
    on conflict (user_id) do update
    set full_name = coalesce(excluded.full_name, public.user_profiles.full_name);

    if tg_op = 'INSERT' or old.role is distinct from new.role then
        if tg_op = 'UPDATE' then
            -- During expand, public.profiles remains the source for its two
            -- legacy roles. Removing the previous mapping prevents a demoted
            -- legacy admin from retaining ADMIN through stale compatibility
            -- data. Display-name-only updates must not restore an assignment
            -- that an Enterprise administrator intentionally removed.
            delete from public.user_roles
            using public.roles
            where user_roles.user_id = new.id
              and user_roles.role_id = roles.id
              and roles.code in ('ADMIN', 'EMPLOYEE');
        end if;

        insert into public.user_roles (user_id, role_id)
        select
            new.id,
            roles.id
        from public.roles
        where roles.code = case when new.role = 'admin' then 'ADMIN' else 'EMPLOYEE' end
        on conflict (user_id, role_id) do nothing;
    end if;
    return new;
end;
$$;

revoke all on function public.sync_legacy_profile_to_enterprise()
from public, anon, authenticated;

drop trigger if exists profiles_sync_enterprise_identity on public.profiles;
create trigger profiles_sync_enterprise_identity
after insert or update of display_name, role on public.profiles
for each row execute function public.sync_legacy_profile_to_enterprise();

create or replace function public.has_functional_permission(
    p_user_id uuid,
    p_permission_code text
)
returns boolean
language sql
stable
security definer
set search_path = ''
as $$
    select coalesce(exists (
        select 1
        from public.user_profiles as user_profiles
        join public.user_roles as user_roles
          on user_roles.user_id = user_profiles.user_id
        join public.roles as roles
          on roles.id = user_roles.role_id
         and roles.status = 'ACTIVE'
        join public.role_permissions as role_permissions
          on role_permissions.role_id = roles.id
        join public.functional_permissions as permissions
          on permissions.id = role_permissions.permission_id
        where user_profiles.user_id = p_user_id
          and user_profiles.status = 'ACTIVE'
          and permissions.code = upper(btrim(p_permission_code))
    ), false);
$$;

revoke all on function public.has_functional_permission(uuid, text)
from public, anon;
grant execute on function public.has_functional_permission(uuid, text)
to authenticated, service_role;

create or replace function public.get_principal_context()
returns jsonb
language sql
stable
security definer
set search_path = ''
as $$
    select case
        when auth.uid() is null then null
        when not exists (
            select 1 from public.user_profiles
            where user_id = auth.uid() and status = 'ACTIVE'
        ) then null
        else jsonb_build_object(
            'user_id', auth.uid(),
            'status', 'ACTIVE',
            'roles', coalesce((
                select jsonb_agg(
                    jsonb_build_object(
                        'id', roles.id,
                        'code', roles.code,
                        'name', roles.name,
                        'description', roles.description,
                        'status', roles.status,
                        'created_at', roles.created_at,
                        'updated_at', roles.updated_at
                    ) order by roles.code
                )
                from public.user_roles
                join public.roles on roles.id = user_roles.role_id
                where user_roles.user_id = auth.uid()
                  and roles.status = 'ACTIVE'
            ), '[]'::jsonb),
            'permissions', coalesce((
                select jsonb_agg(distinct permissions.code)
                from public.user_roles
                join public.roles on roles.id = user_roles.role_id
                join public.role_permissions on role_permissions.role_id = roles.id
                join public.functional_permissions as permissions
                  on permissions.id = role_permissions.permission_id
                where user_roles.user_id = auth.uid()
                  and roles.status = 'ACTIVE'
            ), '[]'::jsonb),
            'group_ids', coalesce((
                select jsonb_agg(groups.id order by groups.id)
                from public.user_groups
                join public.groups on groups.id = user_groups.group_id
                where user_groups.user_id = auth.uid()
                  and groups.status = 'ACTIVE'
            ), '[]'::jsonb),
            'department_ids', coalesce((
                select jsonb_agg(user_departments.department_id order by user_departments.department_id)
                from public.user_departments
                join public.departments
                  on departments.id = user_departments.department_id
                where user_departments.user_id = auth.uid()
                  and user_departments.start_at <= now()
                  and (user_departments.end_at is null or user_departments.end_at > now())
                  and departments.status = 'ACTIVE'
            ), '[]'::jsonb)
        )
    end;
$$;

revoke all on function public.get_principal_context() from public, anon;
grant execute on function public.get_principal_context()
to authenticated, service_role;

comment on table public.user_profiles is
    'Enterprise business identity extension; authentication remains in auth.users.';
comment on table public.access_subjects is
    'Typed ACL principal with a real foreign key to exactly one user, role, group or department.';
comment on function public.get_principal_context() is
    'Resolves current DB memberships so JWT role/group claims cannot become stale authorization state.';
