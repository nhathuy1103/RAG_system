-- Complete the Enterprise RAG cutover: atomic grounded answers and a direct
-- version-scoped ingestion queue bridge. Run after
-- 21_enterprise_security_retrieval.sql.

insert into storage.buckets (
    id,
    name,
    public,
    file_size_limit,
    allowed_mime_types
)
values (
    'knowledge-source-files',
    'knowledge-source-files',
    false,
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
set name = excluded.name,
    public = excluded.public,
    file_size_limit = excluded.file_size_limit,
    allowed_mime_types = excluded.allowed_mime_types;

create or replace function public.can_download_enterprise_source(
    p_user_id uuid,
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
        join public.knowledge_documents as documents
          on documents.id = versions.document_id
        where files.bucket_name = p_bucket_name
          and files.object_path = p_object_path
          and (
              (
                  documents.status = 'PUBLISHED'
                  and documents.current_version_id = versions.id
                  and versions.status = 'ACTIVE'
                  and public.has_document_permission(
                      p_user_id,
                      documents.id,
                      'DOWNLOAD'
                  )
              )
              or (
                  public.has_document_permission(
                      p_user_id,
                      documents.id,
                      'MANAGE'
                  )
                  and public.has_functional_permission(
                      p_user_id,
                      'MANAGE_DOCUMENT'
                  )
              )
              or (
                  public.has_document_permission(
                      p_user_id,
                      documents.id,
                      'REVIEW'
                  )
                  and public.has_functional_permission(
                      p_user_id,
                      'REVIEW_DOCUMENT'
                  )
              )
              or (
                  public.has_document_permission(
                      p_user_id,
                      documents.id,
                      'PUBLISH'
                  )
                  and public.has_functional_permission(
                      p_user_id,
                      'PUBLISH_DOCUMENT'
                  )
              )
          )
    ), false);
$$;

revoke all on function public.can_download_enterprise_source(uuid, text, text)
from public, anon;
grant execute on function public.can_download_enterprise_source(uuid, text, text)
to authenticated, service_role;

drop policy if exists enterprise_source_storage_insert on storage.objects;
create policy enterprise_source_storage_insert
on storage.objects for insert to authenticated
with check (
    bucket_id = 'knowledge-source-files'
    and (storage.foldername(name))[1] = (select auth.uid())::text
    and (
        public.has_functional_permission((select auth.uid()), 'UPLOAD_DOCUMENT')
        or public.has_functional_permission((select auth.uid()), 'MANAGE_DOCUMENT')
    )
);

drop policy if exists enterprise_source_storage_select on storage.objects;
create policy enterprise_source_storage_select
on storage.objects for select to authenticated
using (
    bucket_id = 'knowledge-source-files'
    and (
        (
            (storage.foldername(name))[1] = (select auth.uid())::text
            and (
                public.has_functional_permission((select auth.uid()), 'UPLOAD_DOCUMENT')
                or public.has_functional_permission((select auth.uid()), 'MANAGE_DOCUMENT')
            )
            and not public.is_enterprise_storage_object_referenced(
                storage.objects.bucket_id,
                storage.objects.name
            )
        )
        or public.can_download_enterprise_source(
            (select auth.uid()),
            bucket_id,
            name
        )
    )
);

drop policy if exists enterprise_source_storage_delete on storage.objects;
create policy enterprise_source_storage_delete
on storage.objects for delete to authenticated
using (
    bucket_id = 'knowledge-source-files'
    and (storage.foldername(name))[1] = (select auth.uid())::text
    and (
        public.has_functional_permission((select auth.uid()), 'UPLOAD_DOCUMENT')
        or public.has_functional_permission((select auth.uid()), 'MANAGE_DOCUMENT')
    )
    and not public.is_enterprise_storage_object_registered(
        storage.objects.bucket_id,
        storage.objects.name
    )
);

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
    if actor is null then
        raise exception 'Source access is not permitted' using errcode = '42501';
    end if;
    if (
        selected_document.status = 'PUBLISHED'
        and selected_document.current_version_id = p_version_id
        and selected_version.status = 'ACTIVE'
    ) then
        if not public.has_document_permission(actor, p_document_id, 'DOWNLOAD') then
            raise exception 'Source download is not permitted' using errcode = '42501';
        end if;
    elsif not (
        (
            public.has_document_permission(actor, p_document_id, 'MANAGE')
            and public.has_functional_permission(actor, 'MANAGE_DOCUMENT')
        )
        or (
            public.has_document_permission(actor, p_document_id, 'REVIEW')
            and public.has_functional_permission(actor, 'REVIEW_DOCUMENT')
        )
        or (
            public.has_document_permission(actor, p_document_id, 'PUBLISH')
            and public.has_functional_permission(actor, 'PUBLISH_DOCUMENT')
        )
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

-- Only the server-side completion RPC may create ASSISTANT/SYSTEM messages.
-- Keeping the historical signature avoids breaking clients during rollout.
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
    if actor is null
       or not public.has_functional_permission(actor, 'ASK_KNOWLEDGE')
       or not exists (
           select 1
           from public.enterprise_conversations
           where id = p_conversation_id and user_id = actor
       ) then
        raise exception 'Conversation access is not permitted' using errcode = '42501';
    end if;
    if normalized_role <> 'USER' then
        raise exception 'Only USER messages may be appended by a client'
            using errcode = '42501';
    end if;
    if nullif(btrim(coalesce(p_content, '')), '') is null then
        raise exception 'Message content is required' using errcode = '22023';
    end if;

    insert into public.enterprise_messages (
        conversation_id,
        role,
        content,
        answer_status
    ) values (
        p_conversation_id,
        'USER',
        btrim(p_content),
        'COMPLETED'
    ) returning * into created_message;

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

-- The public search entry point requires both the functional ASK permission
-- and the row-level READ/lifecycle checks inside the underlying search RPC.
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
    return query
    select *
    from public.search_enterprise_document_chunks_keyword(
        p_query,
        p_limit,
        p_filters
    );
end;
$$;

revoke all on function public.search_enterprise_knowledge(text, integer, jsonb)
from public, anon;
grant execute on function public.search_enterprise_knowledge(text, integer, jsonb)
to authenticated;

-- Persist the assistant message and its exact version-bound citations in one
-- transaction. Authorization and publication are checked again here to close
-- the retrieval-to-generation race (archive, republish, or ACL revocation).
create or replace function public.write_enterprise_audit_as_actor(
    p_actor_user_id uuid,
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
    if auth.role() <> 'service_role' or p_actor_user_id is null then
        raise exception 'Service role and an explicit actor are required'
            using errcode = '42501';
    end if;
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
        p_actor_user_id,
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
    ) returning id into inserted_id;
    return inserted_id;
end;
$$;

revoke all on function public.write_enterprise_audit_as_actor(
    uuid, text, text, uuid, jsonb, jsonb, text
) from public, anon, authenticated;
grant execute on function public.write_enterprise_audit_as_actor(
    uuid, text, text, uuid, jsonb, jsonb, text
) to service_role;

drop function if exists public.complete_enterprise_answer(
    uuid, text, text, text, integer, integer, text, text, jsonb
);

create or replace function public.complete_enterprise_answer(
    p_actor_user_id uuid,
    p_conversation_id uuid,
    p_content text,
    p_answer_status text,
    p_model text,
    p_input_tokens integer,
    p_output_tokens integer,
    p_error_code text,
    p_trace_id text,
    p_citations jsonb
)
returns jsonb
language plpgsql
security definer
set search_path = ''
as $$
declare
    actor uuid := p_actor_user_id;
    normalized_status text := upper(btrim(coalesce(p_answer_status, '')));
    created_message public.enterprise_messages;
    citations_payload jsonb := coalesce(p_citations, '[]'::jsonb);
    citation_count integer;
    distinct_order_count integer;
    distinct_chunk_count integer;
    created_citations jsonb := '[]'::jsonb;
begin
    if auth.role() <> 'service_role' then
        raise exception 'Service role required to commit an Enterprise answer'
            using errcode = '42501';
    end if;
    if actor is null
       or not public.has_functional_permission(actor, 'ASK_KNOWLEDGE')
       or not exists (
           select 1
           from public.enterprise_conversations
           where id = p_conversation_id and user_id = actor
       ) then
        raise exception 'Conversation access is not permitted' using errcode = '42501';
    end if;
    if normalized_status not in ('COMPLETED', 'FAILED', 'CONTROLLED_NO_ANSWER') then
        raise exception 'Invalid answer status' using errcode = '22023';
    end if;
    if nullif(btrim(coalesce(p_content, '')), '') is null then
        raise exception 'Answer content is required' using errcode = '22023';
    end if;
    if (p_input_tokens is not null and p_input_tokens < 0)
       or (p_output_tokens is not null and p_output_tokens < 0) then
        raise exception 'Token counts must be non-negative' using errcode = '22023';
    end if;
    if jsonb_typeof(citations_payload) <> 'array' then
        raise exception 'Citations must be an array' using errcode = '22023';
    end if;
    citation_count := jsonb_array_length(citations_payload);
    if citation_count > 100 then
        raise exception 'Too many citations' using errcode = '22023';
    end if;

    if normalized_status = 'COMPLETED' then
        if citation_count = 0 or nullif(btrim(coalesce(p_model, '')), '') is null then
            raise exception 'A completed answer requires a model and citations'
                using errcode = '22023';
        end if;
    elsif citation_count <> 0 or p_model is not null then
        raise exception 'Failed or controlled answers cannot carry citations or a model'
            using errcode = '22023';
    end if;

    if citation_count > 0 and exists (
        select 1
        from jsonb_array_elements(citations_payload) as item(value)
        where jsonb_typeof(item.value) <> 'object'
           or coalesce(item.value ->> 'document_id', '')
              !~* '^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$'
           or coalesce(item.value ->> 'document_version_id', '')
              !~* '^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$'
           or coalesce(item.value ->> 'chunk_id', '')
              !~* '^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$'
           or coalesce(item.value ->> 'citation_order', '') !~ '^[1-9][0-9]*$'
           or nullif(btrim(item.value ->> 'quote_text'), '') is null
           or (
               item.value ? 'page_number'
               and item.value ->> 'page_number' is not null
               and item.value ->> 'page_number' !~ '^[1-9][0-9]*$'
           )
    ) then
        raise exception 'Citation payload is invalid' using errcode = '22023';
    end if;

    if citation_count > 0 then
        select
            count(distinct (item.value ->> 'citation_order')::integer),
            count(distinct (item.value ->> 'chunk_id')::uuid)
        into distinct_order_count, distinct_chunk_count
        from jsonb_array_elements(citations_payload) as item(value);
        if distinct_order_count <> citation_count
           or distinct_chunk_count <> citation_count
           or exists (
               select 1
               from generate_series(1, citation_count) as expected(ordinal)
               where not exists (
                   select 1
                   from jsonb_array_elements(citations_payload) as item(value)
                   where (item.value ->> 'citation_order')::integer = expected.ordinal
               )
           ) then
            raise exception 'Citation order and chunks must be unique and contiguous'
                using errcode = '22023';
        end if;

        if exists (
            select 1
            from jsonb_array_elements(citations_payload) as item(value)
            where not exists (
                select 1
                from public.knowledge_chunks as chunks
                where chunks.id = (item.value ->> 'chunk_id')::uuid
                  and chunks.document_id = (item.value ->> 'document_id')::uuid
                  and chunks.document_version_id =
                      (item.value ->> 'document_version_id')::uuid
                  and chunks.content = item.value ->> 'quote_text'
                  and public.is_enterprise_document_retrievable(
                      actor,
                      chunks.document_id,
                      chunks.document_version_id
                  )
            )
        ) then
            raise exception 'Citation evidence is no longer authorized or current'
                using errcode = '42501';
        end if;
    end if;

    insert into public.enterprise_messages (
        conversation_id,
        role,
        content,
        answer_status,
        model,
        input_tokens,
        output_tokens,
        error_code,
        trace_id
    ) values (
        p_conversation_id,
        'ASSISTANT',
        p_content,
        normalized_status,
        nullif(btrim(p_model), ''),
        p_input_tokens,
        p_output_tokens,
        nullif(btrim(p_error_code), ''),
        nullif(btrim(p_trace_id), '')
    ) returning * into created_message;

    if citation_count > 0 then
        insert into public.enterprise_citations (
            answer_message_id,
            document_id,
            document_version_id,
            chunk_id,
            page_number,
            quote_text,
            citation_order,
            retrieval_score
        )
        select
            created_message.id,
            (item.value ->> 'document_id')::uuid,
            (item.value ->> 'document_version_id')::uuid,
            (item.value ->> 'chunk_id')::uuid,
            nullif(item.value ->> 'page_number', '')::integer,
            item.value ->> 'quote_text',
            (item.value ->> 'citation_order')::integer,
            nullif(item.value ->> 'retrieval_score', '')::double precision
        from jsonb_array_elements(citations_payload) as item(value);

        select coalesce(
            jsonb_agg(to_jsonb(citations) order by citations.citation_order),
            '[]'::jsonb
        ) into created_citations
        from public.enterprise_citations as citations
        where citations.answer_message_id = created_message.id;
    end if;

    update public.enterprise_conversations
    set updated_at = now()
    where id = p_conversation_id;

    perform public.write_enterprise_audit_as_actor(
        actor,
        'ENTERPRISE_ANSWER_COMPLETED',
        'enterprise_message',
        created_message.id,
        null,
        jsonb_build_object(
            'answer_status', normalized_status,
            'citation_count', citation_count,
            'trace_id', p_trace_id
        ),
        null
    );

    return jsonb_build_object(
        'message', to_jsonb(created_message),
        'citations', created_citations
    );
end;
$$;

revoke all on function public.complete_enterprise_answer(
    uuid, uuid, text, text, text, integer, integer, text, text, jsonb
) from public, anon, authenticated;
grant execute on function public.complete_enterprise_answer(
    uuid, uuid, text, text, text, integer, integer, text, text, jsonb
) to service_role;

-- Return citations together with messages. Revoked/archived evidence is
-- omitted at read time as a second line of defence.
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
    if actor is null
       or not public.has_functional_permission(actor, 'ASK_KNOWLEDGE') then
        raise exception 'Conversation access is not permitted' using errcode = '42501';
    end if;
    select jsonb_build_object(
        'conversation', to_jsonb(conversations),
        'messages', coalesce((
            select jsonb_agg(
                case
                    when messages.role = 'ASSISTANT'
                     and exists (
                         select 1
                         from public.enterprise_citations as all_citations
                         where all_citations.answer_message_id = messages.id
                     )
                     and exists (
                         select 1
                         from public.enterprise_citations as denied_citations
                         where denied_citations.answer_message_id = messages.id
                           and not public.is_enterprise_document_retrievable(
                               actor,
                               denied_citations.document_id,
                               denied_citations.document_version_id
                           )
                     )
                    then to_jsonb(messages) || jsonb_build_object(
                        'content',
                        'Nội dung câu trả lời không còn khả dụng vì quyền truy cập nguồn đã thay đổi.',
                        'answer_status', 'CONTROLLED_NO_ANSWER',
                        'model', null,
                        'input_tokens', null,
                        'output_tokens', null,
                        'error_code', 'EVIDENCE_ACCESS_REVOKED',
                        'citations', '[]'::jsonb
                    )
                    else to_jsonb(messages) || jsonb_build_object(
                        'citations', coalesce((
                            select jsonb_agg(
                                to_jsonb(citations) || jsonb_build_object(
                                    'document_title', documents.title,
                                    'section_path', chunks.section_path
                                )
                                order by citations.citation_order
                            )
                            from public.enterprise_citations as citations
                            join public.knowledge_chunks as chunks
                              on chunks.id = citations.chunk_id
                             and chunks.document_id = citations.document_id
                             and chunks.document_version_id = citations.document_version_id
                            join public.knowledge_documents as documents
                              on documents.id = citations.document_id
                            where citations.answer_message_id = messages.id
                              and public.is_enterprise_document_retrievable(
                                  actor,
                                  citations.document_id,
                                  citations.document_version_id
                              )
                        ), '[]'::jsonb)
                    )
                end
                order by messages.created_at, messages.id
            )
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

-- Claim only direct Enterprise jobs. Legacy rows are still claimed through
-- claim_ingestion_job and synchronized by migration 19 during the cutover.
create or replace function public.claim_enterprise_ingestion_job(
    p_worker_id text,
    p_lease_seconds integer default 120
)
returns table (
    id uuid,
    owner_id uuid,
    notebook_id uuid,
    document_id uuid,
    attempt_number integer,
    configuration jsonb,
    storage_bucket text,
    storage_object_path text,
    original_filename text,
    mime_type text,
    size_bytes bigint,
    content_hash text,
    claim_token uuid,
    document_version integer,
    document_version_id uuid,
    knowledge_document_id uuid,
    source_file_id uuid,
    job_type text
)
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

    select jobs.* into selected_job
    from public.processing_jobs as jobs
    where jobs.legacy_ingestion_job_id is null
      and (
          jobs.status = 'PENDING'
          or (jobs.status = 'RUNNING' and jobs.lease_expires_at <= now())
      )
    order by jobs.requested_at, jobs.id
    for update skip locked
    limit 1;
    if not found then
        return;
    end if;

    update public.processing_jobs as jobs
    set status = 'RUNNING',
        started_at = coalesce(jobs.started_at, now()),
        heartbeat_at = now(),
        lease_owner = btrim(p_worker_id),
        lease_expires_at = now() + make_interval(secs => p_lease_seconds),
        claim_token = next_claim_token,
        error_code = null,
        error_message = null
    where jobs.id = selected_job.id
    returning jobs.* into selected_job;

    return query
    select
        selected_job.id,
        documents.created_by,
        coalesce(documents.legacy_notebook_id, documents.id),
        documents.id,
        selected_job.attempt_no,
        selected_job.configuration,
        files.bucket_name,
        files.object_path,
        files.original_file_name,
        files.mime_type,
        files.size_bytes,
        files.sha256,
        selected_job.claim_token,
        versions.version_number,
        versions.id,
        documents.id,
        files.id,
        selected_job.job_type
    from public.document_versions as versions
    join public.knowledge_documents as documents
      on documents.id = versions.document_id
    join public.source_files as files
      on files.id = versions.source_file_id
    where versions.id = selected_job.document_version_id;
end;
$$;

revoke all on function public.claim_enterprise_ingestion_job(text, integer)
from public, anon, authenticated;
grant execute on function public.claim_enterprise_ingestion_job(text, integer)
to service_role;

create or replace function public.record_enterprise_terminal_processing_stage()
returns trigger
language plpgsql
security definer
set search_path = ''
as $$
begin
    if new.status = 'SUCCEEDED'
       and old.status is distinct from new.status
       and not exists (
           select 1
           from public.processing_stage_history
           where processing_job_id = new.id
             and stage = 'FINALIZING'
             and status = 'SUCCEEDED'
       ) then
        insert into public.processing_stage_history (
            processing_job_id,
            stage,
            status,
            started_at,
            completed_at,
            message
        ) values (
            new.id,
            'FINALIZING',
            'SUCCEEDED',
            coalesce(new.heartbeat_at, now()),
            now(),
            'Processing completed and the version is ready for review.'
        );
    end if;
    return new;
end;
$$;

revoke all on function public.record_enterprise_terminal_processing_stage()
from public, anon, authenticated;

drop trigger if exists processing_jobs_record_terminal_stage
on public.processing_jobs;
create trigger processing_jobs_record_terminal_stage
after update of status on public.processing_jobs
for each row execute function public.record_enterprise_terminal_processing_stage();

comment on function public.complete_enterprise_answer(
    uuid, uuid, text, text, text, integer, integer, text, text, jsonb
) is
    'Atomic answer/citation persistence with a live PUBLISHED+ACTIVE+READ recheck.';
comment on function public.claim_enterprise_ingestion_job(text, integer) is
    'Claims direct version-scoped Enterprise jobs with immutable source-file metadata.';
