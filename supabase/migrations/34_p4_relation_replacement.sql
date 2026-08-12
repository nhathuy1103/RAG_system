-- Atomic P4 relation materialization after P3 structured facts are committed.
-- Run after 33_domain_entity_scope_metadata.sql.

create function public.replace_p4_document_relations(
    p_source_document_id uuid,
    p_detector_version text,
    p_relations jsonb default '[]'::jsonb
)
returns integer
language plpgsql
security definer
set search_path = ''
as $$
declare
    selected_document public.documents;
    normalized_detector_version text := btrim(p_detector_version);
    deleted_count integer := 0;
    relation_count integer := 0;
begin
    if auth.role() <> 'service_role' then
        raise exception 'Service role is required'
            using errcode = '42501';
    end if;
    if normalized_detector_version is null
       or char_length(normalized_detector_version) not between 1 and 100 then
        raise exception 'P4 detector version is invalid'
            using errcode = '22023';
    end if;
    if jsonb_typeof(p_relations) <> 'array'
       or jsonb_array_length(p_relations) > 1000 then
        raise exception 'P4 relations must be an array of at most 1000 items'
            using errcode = '22023';
    end if;

    select documents.*
    into selected_document
    from public.documents as documents
    where documents.id = p_source_document_id
      and documents.status = 'ready'
      and documents.is_active
      and documents.canonical_document_id is null
    for update;

    if not found then
        raise exception 'Ready canonical P4 source document was not found'
            using errcode = 'P0002';
    end if;

    if exists (
        select 1
        from jsonb_array_elements(p_relations) as relation(value)
        where jsonb_typeof(relation.value) <> 'object'
           or coalesce(relation.value ->> 'target_document_id', '')
                !~ '^[0-9a-fA-F-]{36}$'
           or (relation.value ->> 'target_document_id')::uuid = selected_document.id
           or relation.value ->> 'relation_type' not in (
                'exact_content',
                'near_duplicate',
                'version_candidate',
                'version',
                'conflict_candidate',
                'conflict',
                'related',
                'distinct',
                'technical_duplicate',
                'template_variant',
                'temporal_series'
           )
           or jsonb_typeof(coalesce(relation.value -> 'signals', '{}'::jsonb))
                <> 'object'
           or coalesce(relation.value #>> '{signals,p4_review_status}', 'pending')
                not in ('pending', 'auto_confirmed')
           or (relation.value ->> 'confidence')::double precision not between 0 and 1
    ) then
        raise exception 'Invalid P4 relation payload'
            using errcode = '22023';
    end if;

    if (
        select count(*)
        from jsonb_array_elements(p_relations) as relation(value)
    ) <> (
        select count(distinct relation.value ->> 'target_document_id')
        from jsonb_array_elements(p_relations) as relation(value)
    ) then
        raise exception 'P4 relation targets must be unique'
            using errcode = '22023';
    end if;

    if exists (
        select 1
        from jsonb_array_elements(p_relations) as relation(value)
        left join public.documents as target
          on target.id = (relation.value ->> 'target_document_id')::uuid
         and target.owner_id = selected_document.owner_id
         and target.notebook_id = selected_document.notebook_id
         and target.is_active
        where target.id is null
    ) then
        raise exception 'P4 relation target is outside the active tenant scope'
            using errcode = '23503';
    end if;

    delete from public.document_relations as existing
    where existing.source_document_id = selected_document.id
      and existing.owner_id = selected_document.owner_id
      and existing.notebook_id = selected_document.notebook_id
      and existing.detector_version = normalized_detector_version
      and existing.status in ('pending', 'auto_confirmed');
    get diagnostics deleted_count = row_count;

    insert into public.document_relations (
        owner_id,
        notebook_id,
        source_document_id,
        target_document_id,
        relation_type,
        status,
        confidence,
        signals,
        reason,
        detector_version,
        preferred_document_id,
        resolved_at
    )
    select
        selected_document.owner_id,
        selected_document.notebook_id,
        selected_document.id,
        target.id,
        relation.value ->> 'relation_type',
        coalesce(relation.value #>> '{signals,p4_review_status}', 'pending'),
        (relation.value ->> 'confidence')::double precision,
        coalesce(relation.value -> 'signals', '{}'::jsonb),
        nullif(btrim(relation.value ->> 'reason'), ''),
        normalized_detector_version,
        case
            when coalesce(relation.value #>> '{signals,p4_preference,document_id}', '')
                    in (selected_document.id::text, target.id::text)
            then (relation.value #>> '{signals,p4_preference,document_id}')::uuid
            else null
        end,
        case
            when relation.value #>> '{signals,p4_review_status}' = 'auto_confirmed'
            then now()
            else null
        end
    from jsonb_array_elements(p_relations) as relation(value)
    join public.documents as target
      on target.id = (relation.value ->> 'target_document_id')::uuid
     and target.owner_id = selected_document.owner_id
     and target.notebook_id = selected_document.notebook_id
     and target.is_active
    on conflict (source_document_id, target_document_id, detector_version)
    do nothing;
    get diagnostics relation_count = row_count;

    update public.documents as documents
    set
        quality_status = case
            when exists (
                select 1
                from public.document_relations as relations
                where relations.source_document_id = selected_document.id
                  and relations.status = 'pending'
            ) then 'review_required'
            else documents.quality_status
        end,
        updated_at = now()
    where documents.id = selected_document.id
      and documents.owner_id = selected_document.owner_id
      and documents.notebook_id = selected_document.notebook_id;

    insert into public.knowledge_quality_audit (
        owner_id,
        notebook_id,
        relation_id,
        actor_id,
        action,
        reason,
        before_state,
        after_state
    )
    values (
        selected_document.owner_id,
        selected_document.notebook_id,
        null,
        null,
        'replace_p4_document_relations',
        'Deterministic P4 materialization from persisted P3 claim evidence',
        jsonb_build_object(
            'source_document_id', selected_document.id,
            'detector_version', normalized_detector_version,
            'replaced_relation_count', deleted_count
        ),
        jsonb_build_object(
            'source_document_id', selected_document.id,
            'detector_version', normalized_detector_version,
            'relation_count', relation_count
        )
    );

    return relation_count;
end;
$$;

comment on function public.replace_p4_document_relations(uuid, text, jsonb) is
    'Atomically rematerializes pending/automatic P4 document relations while preserving human-reviewed rows.';

revoke all on function public.replace_p4_document_relations(uuid, text, jsonb)
from public, anon, authenticated;
grant execute on function public.replace_p4_document_relations(uuid, text, jsonb)
to service_role;
