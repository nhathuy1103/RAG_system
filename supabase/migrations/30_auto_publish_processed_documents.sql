-- Automatically approve and publish an Enterprise document after all chunks
-- and retrieval projections have been persisted successfully. Run after
-- 29_allow_reupload_after_archive.sql.

create or replace function public.complete_processing_job_v3(
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
    publication_actor uuid;
    previous_claim_sub text := current_setting('request.jwt.claim.sub', true);
    previous_claim_role text := current_setting('request.jwt.claim.role', true);
    previous_claims text := current_setting('request.jwt.claims', true);
begin
    if auth.role() <> 'service_role' then
        raise exception 'Service role required' using errcode = '42501';
    end if;

    select * into selected_job
    from public.processing_jobs
    where id = p_job_id;
    if not found then
        raise exception 'Processing job not found' using errcode = 'P0002';
    end if;

    -- v2 writes chunks, parents, metadata assertions and retrieval projections
    -- in this transaction. Publication happens only after all those writes pass.
    completed_job := public.complete_processing_job_v2(
        p_job_id,
        p_worker_id,
        p_claim_token,
        p_chunks
    );

    select * into selected_version
    from public.document_versions
    where id = selected_job.document_version_id;
    select * into selected_document
    from public.knowledge_documents
    where id = selected_version.document_id;

    publication_actor := selected_job.requested_by;
    if completed_job.status <> 'SUCCEEDED'
       or selected_version.status <> 'READY_FOR_REVIEW'
       or selected_document.status = 'ARCHIVED'
       or publication_actor is null
       or not public.has_functional_permission(
           publication_actor, 'REVIEW_DOCUMENT'
       )
       or not public.has_functional_permission(
           publication_actor, 'PUBLISH_DOCUMENT'
       )
       or not public.has_document_permission(
           publication_actor, selected_document.id, 'REVIEW'
       )
       or not public.has_document_permission(
           publication_actor, selected_document.id, 'PUBLISH'
       ) then
        return completed_job;
    end if;

    -- Reuse the authenticated review/publication guards as the user who
    -- requested the processing job. This preserves actor attribution and the
    -- existing immutable audit trail instead of introducing a bypass path.
    perform set_config('request.jwt.claim.sub', publication_actor::text, true);
    perform set_config('request.jwt.claim.role', 'authenticated', true);
    perform set_config(
        'request.jwt.claims',
        jsonb_build_object(
            'sub', publication_actor,
            'role', 'authenticated'
        )::text,
        true
    );

    perform public.approve_and_publish_document_version(
        selected_version.id,
        'Tự động duyệt và đưa vào chatbot sau khi xử lý thành công'
    );

    perform set_config(
        'request.jwt.claim.sub', coalesce(previous_claim_sub, ''), true
    );
    perform set_config(
        'request.jwt.claim.role', coalesce(previous_claim_role, ''), true
    );
    perform set_config(
        'request.jwt.claims', coalesce(previous_claims, ''), true
    );
    return completed_job;
end;
$$;

revoke all on function public.complete_processing_job_v3(
    uuid, text, uuid, jsonb
) from public, anon, authenticated;
grant execute on function public.complete_processing_job_v3(
    uuid, text, uuid, jsonb
) to service_role;

comment on function public.complete_processing_job_v3(uuid, text, uuid, jsonb) is
    'Completes ingestion projections, then automatically approves and publishes when the requesting actor retains review and publish permission.';
