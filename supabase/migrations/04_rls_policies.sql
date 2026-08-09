-- Grants + RLS for every table. Run after 02_tables.sql and 03_functions_triggers.sql.

-- notebooks
revoke all on table public.notebooks from anon;
revoke all on table public.notebooks from authenticated;
grant select, insert, update, delete on table public.notebooks to authenticated;
grant all privileges on table public.notebooks to service_role;

alter table public.notebooks enable row level security;
alter table public.notebooks force row level security;

create policy notebooks_select_own on public.notebooks for select to authenticated
    using ((select auth.uid()) = owner_id);
create policy notebooks_insert_own on public.notebooks for insert to authenticated
    with check ((select auth.uid()) = owner_id);
create policy notebooks_update_own on public.notebooks for update to authenticated
    using ((select auth.uid()) = owner_id) with check ((select auth.uid()) = owner_id);
create policy notebooks_delete_own on public.notebooks for delete to authenticated
    using ((select auth.uid()) = owner_id);

-- documents / ingestion_jobs / document_chunks / conversations / messages / message_citations
revoke all privileges on table public.documents from anon;
revoke all privileges on table public.ingestion_jobs from anon;
revoke all privileges on table public.document_chunks from anon;
revoke all privileges on table public.conversations from anon;
revoke all privileges on table public.messages from anon;
revoke all privileges on table public.message_citations from anon;

revoke all privileges on table public.documents from authenticated;
revoke all privileges on table public.ingestion_jobs from authenticated;
revoke all privileges on table public.document_chunks from authenticated;
revoke all privileges on table public.conversations from authenticated;
revoke all privileges on table public.messages from authenticated;
revoke all privileges on table public.message_citations from authenticated;

grant select, insert, update, delete on table public.documents to authenticated;
-- ingestion_jobs: read-only, writes go through RPCs only.
grant select on table public.ingestion_jobs to authenticated;
grant select, insert, update, delete on table public.document_chunks to authenticated;
grant select, insert, update, delete on table public.conversations to authenticated;
grant select, insert, update, delete on table public.messages to authenticated;
grant select, insert, update, delete on table public.message_citations to authenticated;

grant all privileges on table public.documents to service_role;
grant all privileges on table public.ingestion_jobs to service_role;
grant all privileges on table public.document_chunks to service_role;
grant all privileges on table public.conversations to service_role;
grant all privileges on table public.messages to service_role;
grant all privileges on table public.message_citations to service_role;

alter table public.documents enable row level security;
alter table public.documents force row level security;
alter table public.ingestion_jobs enable row level security;
alter table public.ingestion_jobs force row level security;
alter table public.document_chunks enable row level security;
alter table public.document_chunks force row level security;
alter table public.conversations enable row level security;
alter table public.conversations force row level security;
alter table public.messages enable row level security;
alter table public.messages force row level security;
alter table public.message_citations enable row level security;
alter table public.message_citations force row level security;

create policy documents_select_own on public.documents for select to authenticated
    using ((select auth.uid()) = owner_id);
create policy documents_insert_own on public.documents for insert to authenticated
    with check ((select auth.uid()) = owner_id);
create policy documents_update_own on public.documents for update to authenticated
    using ((select auth.uid()) = owner_id) with check ((select auth.uid()) = owner_id);
create policy documents_delete_own on public.documents for delete to authenticated
    using ((select auth.uid()) = owner_id);

create policy ingestion_jobs_select_own on public.ingestion_jobs for select to authenticated
    using ((select auth.uid()) = owner_id);

create policy document_chunks_select_own on public.document_chunks for select to authenticated
    using ((select auth.uid()) = owner_id);
create policy document_chunks_insert_own on public.document_chunks for insert to authenticated
    with check ((select auth.uid()) = owner_id);
create policy document_chunks_update_own on public.document_chunks for update to authenticated
    using ((select auth.uid()) = owner_id) with check ((select auth.uid()) = owner_id);
create policy document_chunks_delete_own on public.document_chunks for delete to authenticated
    using ((select auth.uid()) = owner_id);

create policy conversations_select_own on public.conversations for select to authenticated
    using ((select auth.uid()) = owner_id);
create policy conversations_insert_own on public.conversations for insert to authenticated
    with check ((select auth.uid()) = owner_id);
create policy conversations_update_own on public.conversations for update to authenticated
    using ((select auth.uid()) = owner_id) with check ((select auth.uid()) = owner_id);
create policy conversations_delete_own on public.conversations for delete to authenticated
    using ((select auth.uid()) = owner_id);

create policy messages_select_own on public.messages for select to authenticated
    using ((select auth.uid()) = owner_id);
create policy messages_insert_own on public.messages for insert to authenticated
    with check ((select auth.uid()) = owner_id);
create policy messages_update_own on public.messages for update to authenticated
    using ((select auth.uid()) = owner_id) with check ((select auth.uid()) = owner_id);
create policy messages_delete_own on public.messages for delete to authenticated
    using ((select auth.uid()) = owner_id);

create policy message_citations_select_own on public.message_citations for select to authenticated
    using ((select auth.uid()) = owner_id);
create policy message_citations_insert_own on public.message_citations for insert to authenticated
    with check ((select auth.uid()) = owner_id);
create policy message_citations_update_own on public.message_citations for update to authenticated
    using ((select auth.uid()) = owner_id) with check ((select auth.uid()) = owner_id);
create policy message_citations_delete_own on public.message_citations for delete to authenticated
    using ((select auth.uid()) = owner_id);

-- profiles
revoke all on table public.profiles from anon;
revoke all on table public.profiles from authenticated;
-- No delete grant; insert allows GET /profile self-heal.
grant select, insert, update on table public.profiles to authenticated;
grant all privileges on table public.profiles to service_role;

alter table public.profiles enable row level security;
alter table public.profiles force row level security;

create policy profiles_select_own on public.profiles for select to authenticated
    using ((select auth.uid()) = id);
create policy profiles_insert_own on public.profiles for insert to authenticated
    -- Self-heal only creates 'user' rows.
    with check ((select auth.uid()) = id and role = 'user');
create policy profiles_update_own on public.profiles for update to authenticated
    using ((select auth.uid()) = id)
    -- Blocks self-promotion to admin.
    with check (
        (select auth.uid()) = id
        and role = public.current_profile_role()
    );
