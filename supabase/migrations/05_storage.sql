-- Storage bucket + policies for uploaded document bytes. Run after
-- 02_tables.sql (policies reference public.documents).

insert into storage.buckets (
    id,
    name,
    public,
    file_size_limit,
    allowed_mime_types
)
values (
    'documents',
    'documents',
    false,
    -- 10 MiB, matches documents_size and MAX_FILE_SIZE_BYTES.
    10485760,
    array[
        'application/pdf',
        'application/vnd.openxmlformats-officedocument.wordprocessingml.document',
        'application/vnd.openxmlformats-officedocument.presentationml.presentation',
        'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
        'text/csv',
        'text/markdown',
        'text/html',
        'text/plain'
    ]::text[]
)
on conflict (id) do update
set
    name = excluded.name,
    public = excluded.public,
    file_size_limit = excluded.file_size_limit,
    allowed_mime_types = excluded.allowed_mime_types;

create policy documents_storage_insert_own
on storage.objects
for insert
to authenticated
with check (
    bucket_id = 'documents'
    and (storage.foldername(name))[1] = (select auth.uid())::text
    and exists (
        select 1
        from public.documents
        where documents.owner_id = (select auth.uid())
          and documents.storage_bucket = storage.objects.bucket_id
          and documents.storage_object_path = storage.objects.name
    )
);

create policy documents_storage_select_own
on storage.objects
for select
to authenticated
using (
    bucket_id = 'documents'
    and (storage.foldername(name))[1] = (select auth.uid())::text
);

create policy documents_storage_delete_own
on storage.objects
for delete
to authenticated
using (
    bucket_id = 'documents'
    and (storage.foldername(name))[1] = (select auth.uid())::text
);
