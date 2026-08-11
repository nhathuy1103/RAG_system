-- Guided publication: collapse approval and publication into one safe action
-- while preserving both permission checks and the existing audit trail. Run
-- after 27_fix_complete_processing_job_v2_digest.sql.

create or replace function public.approve_and_publish_document_version(
    p_version_id uuid,
    p_note text default null
)
returns public.document_versions
language plpgsql
security definer
set search_path = ''
as $$
declare
    selected_version public.document_versions;
begin
    select * into selected_version
    from public.document_versions
    where id = p_version_id;
    if not found then
        raise exception 'Document version not found' using errcode = 'P0002';
    end if;

    -- A separately assigned reviewer may already have approved this exact
    -- processing result. Only create an approval when one is still required.
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
        perform public.review_document_version(
            p_version_id,
            'APPROVE',
            coalesce(
                nullif(btrim(p_note), ''),
                'Approved through guided publication'
            ),
            null
        );
    end if;

    -- Nested function calls share this transaction. A publication failure
    -- therefore rolls back an approval created above.
    return public.publish_document_version(p_version_id);
end;
$$;

revoke all on function public.approve_and_publish_document_version(uuid, text)
from public, anon;
grant execute on function public.approve_and_publish_document_version(uuid, text)
to authenticated;

comment on function public.approve_and_publish_document_version(uuid, text) is
    'One guided action that reuses atomic review and publish guards; existing fresh approvals are preserved.';
