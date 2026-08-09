-- Behavioral assertions for:
--   knowledge_quality_migration_base.sql
--   08_knowledge_quality.sql
--   09_knowledge_quality_hardening.sql
\set ON_ERROR_STOP on

insert into auth.users (id)
values
    ('21000000-0000-0000-0000-000000000021'),
    ('22000000-0000-0000-0000-000000000022');

insert into public.notebooks (id, owner_id, title)
values
(
    '11000000-0000-0000-0000-000000000011',
    '21000000-0000-0000-0000-000000000021',
    'Hardening test'
),
(
    '12000000-0000-0000-0000-000000000012',
    '22000000-0000-0000-0000-000000000022',
    'Other tenant'
);

insert into public.documents (
    id,
    owner_id,
    notebook_id,
    original_filename,
    storage_object_path,
    mime_type,
    size_bytes,
    content_hash,
    status
)
values
(
    '31000000-0000-0000-0000-000000000031',
    '21000000-0000-0000-0000-000000000021',
    '11000000-0000-0000-0000-000000000011',
    'canonical.txt',
    '21000000-0000-0000-0000-000000000021/11000000-0000-0000-0000-000000000011/31000000-0000-0000-0000-000000000031/canonical.txt',
    'text/plain',
    101,
    repeat('1', 64),
    'uploading'
),
(
    '32000000-0000-0000-0000-000000000032',
    '21000000-0000-0000-0000-000000000021',
    '11000000-0000-0000-0000-000000000011',
    'version.txt',
    '21000000-0000-0000-0000-000000000021/11000000-0000-0000-0000-000000000011/32000000-0000-0000-0000-000000000032/version.txt',
    'text/plain',
    102,
    repeat('2', 64),
    'uploading'
),
(
    '33000000-0000-0000-0000-000000000033',
    '21000000-0000-0000-0000-000000000021',
    '11000000-0000-0000-0000-000000000011',
    'normalized-duplicate.txt',
    '21000000-0000-0000-0000-000000000021/11000000-0000-0000-0000-000000000011/33000000-0000-0000-0000-000000000033/normalized-duplicate.txt',
    'text/plain',
    103,
    repeat('3', 64),
    'uploading'
),
(
    '34000000-0000-0000-0000-000000000034',
    '21000000-0000-0000-0000-000000000021',
    '11000000-0000-0000-0000-000000000011',
    'rollback-shadow.txt',
    '21000000-0000-0000-0000-000000000021/11000000-0000-0000-0000-000000000011/34000000-0000-0000-0000-000000000034/rollback-shadow.txt',
    'text/plain',
    104,
    repeat('4', 64),
    'uploading'
);

select set_config(
    'request.jwt.claim.sub',
    '21000000-0000-0000-0000-000000000021',
    false
);
select set_config('request.jwt.claim.role', 'authenticated', false);

do $$
declare
    enqueued_document_id uuid;
begin
    select id
    into enqueued_document_id
    from public.enqueue_document_ingestion(
        '31000000-0000-0000-0000-000000000031',
        '11000000-0000-0000-0000-000000000011',
        'embed-v1',
        1536,
        '{"chunker":"v1","knowledge_quality_mode":"on"}'::jsonb
    );

    perform public.enqueue_document_ingestion(
        '31000000-0000-0000-0000-000000000031',
        '11000000-0000-0000-0000-000000000011',
        'embed-v1',
        1536,
        '{"chunker":"v1","knowledge_quality_mode":"on"}'::jsonb
    );

    if enqueued_document_id is null or (
        select count(*)
        from public.ingestion_jobs
        where ingestion_jobs.document_id = enqueued_document_id
    ) <> 1 then
        raise exception 'enqueue retry created more than one attempt';
    end if;

    begin
        perform public.enqueue_document_ingestion(
            enqueued_document_id,
            '11000000-0000-0000-0000-000000000011',
            'embed-v2',
            1536,
            '{"chunker":"v1","knowledge_quality_mode":"on"}'::jsonb
        );
        raise exception 'enqueue accepted a mismatched profile';
    exception
        when invalid_parameter_value then null;
    end;

    perform public.enqueue_document_ingestion(
        '32000000-0000-0000-0000-000000000032',
        '11000000-0000-0000-0000-000000000011',
        'embed-v1',
        1536,
        '{"chunker":"v1","knowledge_quality_mode":"shadow"}'::jsonb
    );
    perform public.enqueue_document_ingestion(
        '33000000-0000-0000-0000-000000000033',
        '11000000-0000-0000-0000-000000000011',
        'embed-v1',
        1536,
        '{"chunker":"v1","knowledge_quality_mode":"on"}'::jsonb
    );
    perform public.enqueue_document_ingestion(
        '34000000-0000-0000-0000-000000000034',
        '11000000-0000-0000-0000-000000000011',
        'embed-v1',
        1536,
        '{"chunker":"v1","knowledge_quality_mode":"on"}'::jsonb
    );
end;
$$;

do $$
begin
    if has_table_privilege(
        'authenticated',
        'public.document_chunks',
        'INSERT'
    ) or has_table_privilege(
        'authenticated',
        'public.document_chunks',
        'UPDATE'
    ) or has_table_privilege(
        'authenticated',
        'public.document_chunks',
        'DELETE'
    ) then
        raise exception 'authenticated retained a direct chunk mutation privilege';
    end if;

    if not has_column_privilege(
        'authenticated',
        'public.documents',
        'status',
        'UPDATE'
    ) or has_column_privilege(
        'authenticated',
        'public.documents',
        'normalized_content_hash',
        'UPDATE'
    ) or has_column_privilege(
        'authenticated',
        'public.documents',
        'canonical_document_id',
        'UPDATE'
    ) then
        raise exception 'document protected-column grants are incorrect';
    end if;
end;
$$;

select set_config('request.jwt.claim.role', 'service_role', false);

update public.ingestion_jobs
set
    status = 'running',
    claimed_by = 'hardening-worker',
    claim_token = case document_id
        when '31000000-0000-0000-0000-000000000031'::uuid
            then '51000000-0000-0000-0000-000000000051'::uuid
        when '32000000-0000-0000-0000-000000000032'::uuid
            then '52000000-0000-0000-0000-000000000052'::uuid
        when '33000000-0000-0000-0000-000000000033'::uuid
            then '53000000-0000-0000-0000-000000000053'::uuid
        else '54000000-0000-0000-0000-000000000054'::uuid
    end,
    lease_expires_at = now() + interval '5 minutes',
    started_at = now(),
    updated_at = now();

do $$
begin
    begin
        perform public.begin_ingestion_maintenance(
            'hardening-reconciler',
            60,
            'fixture must not race a running worker'
        );
        raise exception 'maintenance started while a job was running';
    exception
        when lock_not_available then null;
    end;
end;
$$;

do $$
declare
    embedding jsonb;
    chunk_payload jsonb;
    canonical_job_id uuid;
    version_job_id uuid;
    duplicate_job_id uuid;
    rollback_job_id uuid;
    completion_disposition text;
begin
    select jsonb_agg(0.01 order by dimensions.value)
    into embedding
    from generate_series(1, 1536) as dimensions(value);

    select id into canonical_job_id
    from public.ingestion_jobs
    where document_id = '31000000-0000-0000-0000-000000000031';

    chunk_payload := jsonb_build_array(
        jsonb_build_object(
            'id', '41000000-0000-0000-0000-000000000041',
            'chunk_index', 0,
            'content', 'The same authoritative policy chunk for grouping.',
            'token_count', 8,
            'metadata', jsonb_build_object(
                'normalized_content_hash', repeat('c', 64),
                'normalization_version', 'knowledge-identity-v1',
                'loose_content_signature', repeat('d', 16),
                'exact_duplicate_group_id',
                    public.knowledge_exact_chunk_group_id(
                        '21000000-0000-0000-0000-000000000021',
                        '11000000-0000-0000-0000-000000000011',
                        'knowledge-identity-v1',
                        repeat('c', 64)
                    )
            ),
            'embedding', embedding
        )
    );

    begin
        perform public.complete_ingestion_job(
            canonical_job_id,
            'hardening-worker',
            gen_random_uuid(),
            'embed-v1',
            1536,
            chunk_payload,
            repeat('a', 64),
            'knowledge-identity-v1',
            repeat('e', 16),
            '{"character_count":80,"token_count":12,"knowledge_quality_mode":"on"}'::jsonb,
            '[]'::jsonb
        );
        raise exception 'a stale claim token activated vectors';
    exception
        when no_data_found then null;
    end;

    completion_disposition := public.complete_ingestion_job(
        canonical_job_id,
        'hardening-worker',
        '51000000-0000-0000-0000-000000000051',
        'embed-v1',
        1536,
        chunk_payload,
        repeat('a', 64),
        'knowledge-identity-v1',
        repeat('e', 16),
        '{"character_count":80,"token_count":12,"knowledge_quality_mode":"on"}'::jsonb,
        '[]'::jsonb
    );
    if completion_disposition <> 'completed' then
        raise exception 'canonical completion returned the wrong disposition';
    end if;

    select id into version_job_id
    from public.ingestion_jobs
    where document_id = '32000000-0000-0000-0000-000000000032';

    chunk_payload := jsonb_set(
        chunk_payload,
        '{0,id}',
        to_jsonb('42000000-0000-0000-0000-000000000042'::text)
    );

    begin
        perform public.complete_duplicate_ingestion_job(
            version_job_id,
            'hardening-worker',
            '52000000-0000-0000-0000-000000000052',
            '31000000-0000-0000-0000-000000000031',
            repeat('a', 64),
            'knowledge-identity-v1',
            repeat('e', 16),
            '{"character_count":80,"token_count":12,"knowledge_quality_mode":"shadow"}'::jsonb
        );
        raise exception 'shadow mode performed direct duplicate suppression';
    exception
        when insufficient_privilege then null;
    end;

    perform public.complete_ingestion_job(
        version_job_id,
        'hardening-worker',
        '52000000-0000-0000-0000-000000000052',
        'embed-v1',
        1536,
        chunk_payload,
        repeat('a', 64),
        'knowledge-identity-v1',
        repeat('e', 16),
        '{"character_count":80,"token_count":12,"knowledge_quality_mode":"shadow"}'::jsonb,
        jsonb_build_array(
            jsonb_build_object(
                'target_document_id',
                '31000000-0000-0000-0000-000000000031',
                'relation_type',
                'exact_content',
                'confidence',
                1,
                'signals',
                '{"strict_content_match":true}'::jsonb,
                'reason',
                'strict_content_match',
                'detector_version',
                'shadow-fixture-v1'
            )
        )
    );

    select id into rollback_job_id
    from public.ingestion_jobs
    where document_id = '34000000-0000-0000-0000-000000000034';

    chunk_payload := jsonb_set(
        chunk_payload,
        '{0,id}',
        to_jsonb('44000000-0000-0000-0000-000000000044'::text)
    );
    perform public.complete_ingestion_job(
        rollback_job_id,
        'hardening-worker',
        '54000000-0000-0000-0000-000000000054',
        'embed-v1',
        1536,
        chunk_payload,
        repeat('a', 64),
        'knowledge-identity-v1',
        repeat('e', 16),
        '{"character_count":80,"token_count":12,"knowledge_quality_mode":"shadow"}'::jsonb,
        jsonb_build_array(
            jsonb_build_object(
                'target_document_id',
                '31000000-0000-0000-0000-000000000031',
                'relation_type',
                'exact_content',
                'confidence',
                1,
                'signals',
                '{"strict_content_match":true}'::jsonb,
                'reason',
                'runtime kill-switch downgrade',
                'detector_version',
                'rollback-fixture-v1'
            )
        )
    );

    select id into duplicate_job_id
    from public.ingestion_jobs
    where document_id = '33000000-0000-0000-0000-000000000033';

    chunk_payload := jsonb_set(
        chunk_payload,
        '{0,id}',
        to_jsonb('43000000-0000-0000-0000-000000000043'::text)
    );

    -- A direct duplicate completion must never hard-delete vectors that were
    -- already materialized by an earlier generation.
    insert into public.document_chunks (
        id,
        owner_id,
        notebook_id,
        document_id,
        chunk_index,
        content,
        token_count,
        metadata,
        normalized_content_hash,
        normalization_version,
        loose_content_signature,
        exact_duplicate_group_id,
        embedding
    )
    values (
        '45000000-0000-0000-0000-000000000045',
        '21000000-0000-0000-0000-000000000021',
        '11000000-0000-0000-0000-000000000011',
        '33000000-0000-0000-0000-000000000033',
        0,
        'A pre-existing duplicate chunk that must remain reversible.',
        9,
        jsonb_build_object(
            'normalized_content_hash',
            repeat('c', 64),
            'normalization_version',
            'knowledge-identity-v1',
            'loose_content_signature',
            repeat('d', 16),
            'exact_duplicate_group_id',
            public.knowledge_exact_chunk_group_id(
                '21000000-0000-0000-0000-000000000021',
                '11000000-0000-0000-0000-000000000011',
                'knowledge-identity-v1',
                repeat('c', 64)
            )
        ),
        repeat('c', 64),
        'knowledge-identity-v1',
        repeat('d', 16),
        public.knowledge_exact_chunk_group_id(
            '21000000-0000-0000-0000-000000000021',
            '11000000-0000-0000-0000-000000000011',
            'knowledge-identity-v1',
            repeat('c', 64)
        ),
        (embedding::text)::public.vector
    );

    completion_disposition := public.complete_ingestion_job(
        duplicate_job_id,
        'hardening-worker',
        '53000000-0000-0000-0000-000000000053',
        'embed-v1',
        1536,
        chunk_payload,
        repeat('a', 64),
        'knowledge-identity-v1',
        repeat('e', 16),
        '{"character_count":80,"token_count":12,"knowledge_quality_mode":"on"}'::jsonb,
        '[]'::jsonb
    );
    if completion_disposition <> 'duplicate_suppressed' then
        raise exception 'duplicate completion returned the wrong disposition';
    end if;
end;
$$;

do $$
declare
    maintenance_token uuid;
    claimed_count integer;
begin
    maintenance_token := public.begin_ingestion_maintenance(
        'hardening-reconciler',
        60,
        'fixture maintenance fencing'
    );

    update public.ingestion_jobs
    set
        status = 'pending',
        completed_at = null,
        updated_at = now()
    where document_id = '33000000-0000-0000-0000-000000000033';

    select count(*)
    into claimed_count
    from public.claim_ingestion_job('fenced-worker', 60);

    if claimed_count <> 0 then
        raise exception 'maintenance lease allowed a worker claim';
    end if;
    if not public.renew_ingestion_maintenance(
        maintenance_token,
        60
    ) then
        raise exception 'maintenance lease renewal lost its token fence';
    end if;
    if not public.end_ingestion_maintenance(maintenance_token) then
        raise exception 'maintenance lease release lost its token fence';
    end if;

    update public.ingestion_jobs
    set
        status = 'succeeded',
        completed_at = now(),
        updated_at = now()
    where document_id = '33000000-0000-0000-0000-000000000033'
      and status = 'pending';
end;
$$;

do $$
declare
    exact_group_count integer;
    chunk_count integer;
    first_group uuid;
    other_scope_group uuid;
begin
    select
        count(*),
        count(distinct exact_duplicate_group_id)
    into chunk_count, exact_group_count
    from public.document_chunks
    where normalized_content_hash = repeat('c', 64);

    if chunk_count <> 4 or exact_group_count <> 1 then
        raise exception 'strict-identical chunks were not grouped';
    end if;

    select exact_duplicate_group_id
    into first_group
    from public.document_chunks
    where normalized_content_hash = repeat('c', 64)
    limit 1;

    if first_group <>
       'd6db99a6-8d93-5002-825f-488add1faaba'::uuid then
        raise exception 'database chunk group UUIDv5 differs from the application formula';
    end if;

    other_scope_group := public.knowledge_exact_chunk_group_id(
        '21000000-0000-0000-0000-000000000021',
        '12000000-0000-0000-0000-000000000012',
        'knowledge-identity-v1',
        repeat('c', 64)
    );
    if first_group = other_scope_group then
        raise exception 'exact chunk group leaked across notebook scope';
    end if;

    if not exists (
        select 1
        from public.documents
        where id = '32000000-0000-0000-0000-000000000032'
          and status = 'ready'
          and canonical_document_id is null
          and is_current
          and quality_status = 'review_required'
          and quality_metadata ->> 'knowledge_quality_mode' = 'shadow'
    ) or not exists (
        select 1
        from public.document_chunks
        where document_id =
            '32000000-0000-0000-0000-000000000032'
    ) or not exists (
        select 1
        from public.document_relations
        where source_document_id =
                '32000000-0000-0000-0000-000000000032'
          and target_document_id =
                '31000000-0000-0000-0000-000000000031'
          and detector_version = 'shadow-fixture-v1'
          and status = 'pending'
          and signals ->> 'quality_mode' = 'shadow'
          and signals ->> 'suppression_applied' = 'false'
    ) then
        raise exception 'shadow duplicate was suppressed instead of recorded';
    end if;

    if not exists (
        select 1
        from public.documents
        where id = '34000000-0000-0000-0000-000000000034'
          and status = 'ready'
          and canonical_document_id is null
          and is_current
          and quality_status = 'review_required'
          and quality_metadata ->> 'knowledge_quality_mode' = 'shadow'
    ) or not exists (
        select 1
        from public.document_chunks
        where document_id =
            '34000000-0000-0000-0000-000000000034'
    ) or not exists (
        select 1
        from public.document_relations
        where source_document_id =
                '34000000-0000-0000-0000-000000000034'
          and target_document_id =
                '31000000-0000-0000-0000-000000000031'
          and detector_version = 'rollback-fixture-v1'
          and status = 'pending'
          and signals ->> 'quality_mode' = 'shadow'
          and signals ->> 'suppression_applied' = 'false'
    ) then
        raise exception 'runtime on-to-shadow rollback still suppressed data';
    end if;

    if not exists (
        select 1
        from public.documents
        where id = '33000000-0000-0000-0000-000000000033'
          and canonical_document_id =
              '31000000-0000-0000-0000-000000000031'
          and quality_status = 'duplicate'
          and not is_current
    ) or not exists (
        select 1
        from public.document_chunks
        where id = '45000000-0000-0000-0000-000000000045'
          and document_id =
              '33000000-0000-0000-0000-000000000033'
    ) then
        raise exception
            'normalized identity aliasing was destructive or incomplete';
    end if;

    if not exists (
        select 1
        from public.ingestion_jobs
        where document_id =
                '31000000-0000-0000-0000-000000000031'
          and status = 'succeeded'
          and completion_disposition = 'completed'
    ) or not exists (
        select 1
        from public.ingestion_jobs
        where document_id =
                '33000000-0000-0000-0000-000000000033'
          and status = 'succeeded'
          and completion_disposition = 'duplicate_suppressed'
    ) then
        raise exception 'completion disposition was not durably persisted';
    end if;
end;
$$;

select set_config('request.jwt.claim.role', 'authenticated', false);

do $$
declare
    query_embedding public.vector(1536);
    matched_count integer;
    matched_group_count integer;
begin
    select (
        '[' || string_agg('0.01', ',') || ']'
    )::public.vector(1536)
    into query_embedding
    from generate_series(1, 1536);

    select count(*), count(distinct exact_duplicate_group_id)
    into matched_count, matched_group_count
    from public.match_document_chunks(
        query_embedding,
        '21000000-0000-0000-0000-000000000021',
        '11000000-0000-0000-0000-000000000011',
        null,
        20
    );

    if matched_count <> 4 or matched_group_count <> 1 then
        raise exception 'retrieval did not expose persisted exact groups';
    end if;

    begin
        perform *
        from public.match_document_chunks(
            query_embedding,
            '22000000-0000-0000-0000-000000000022',
            null,
            null,
            20
        );
        raise exception 'cross-owner dense retrieval was accepted';
    exception
        when insufficient_privilege then null;
    end;
end;
$$;

do $$
declare
    automatic_relation public.document_relations;
begin
    select relations.*
    into automatic_relation
    from public.document_relations as relations
    where relations.source_document_id =
            '33000000-0000-0000-0000-000000000033'
      and relations.target_document_id =
            '31000000-0000-0000-0000-000000000031'
      and relations.detector_version = 'knowledge-quality-v2';

    if automatic_relation.id is null or not exists (
        select 1
        from public.knowledge_quality_audit as audit
        where audit.relation_id = automatic_relation.id
          and audit.action = 'auto_confirm_duplicate'
          and jsonb_array_length(
              audit.before_state -> 'documents'
          ) = 2
          and jsonb_array_length(
              audit.after_state -> 'documents'
          ) = 2
          and audit.before_state -> 'relation' is not null
          and audit.after_state -> 'relation' =
              to_jsonb(automatic_relation)
    ) then
        raise exception
            'automatic exact decision lacks reversible snapshots';
    end if;

    perform public.revert_document_relation_resolution(
        automatic_relation.id,
        automatic_relation.notebook_id,
        automatic_relation.updated_at,
        'fixture false-positive compensation'
    );

    if not exists (
        select 1
        from public.documents
        where id = automatic_relation.source_document_id
          and status = 'ready'
          and canonical_document_id is null
          and is_current
    ) then
        raise exception 'automatic exact revert did not restore a canonical row';
    end if;
end;
$$;

select set_config('request.jwt.claim.role', 'service_role', false);

update public.document_chunks
set embedding = null
where id = '45000000-0000-0000-0000-000000000045';

do $$
declare
    repair_job public.ingestion_jobs;
    retry_job public.ingestion_jobs;
    expected_updated_at timestamptz;
begin
    select updated_at
    into expected_updated_at
    from public.documents
    where id = '33000000-0000-0000-0000-000000000033';

    select jobs.*
    into repair_job
    from public.requeue_document_ingestion_repair(
        '33000000-0000-0000-0000-000000000033',
        '21000000-0000-0000-0000-000000000021',
        '11000000-0000-0000-0000-000000000011',
        '61000000-0000-0000-0000-000000000061',
        expected_updated_at,
        repeat('f', 64),
        'missing_embedding',
        'fixture vector mismatch repair'
    ) as jobs;

    if repair_job.id is null
       or repair_job.attempt_number <> 2
       or repair_job.status <> 'pending'
       or not exists (
           select 1
           from public.documents
           where id = repair_job.document_id
             and status = 'processing'
             and canonical_document_id is null
       )
       or not exists (
           select 1
           from public.knowledge_quality_audit
           where action = 'repair_requeue'
             and reason = 'fixture vector mismatch repair'
    ) then
        raise exception 'reconciliation repair was not fenced or audited';
    end if;

    select jobs.*
    into retry_job
    from public.requeue_document_ingestion_repair(
        '33000000-0000-0000-0000-000000000033',
        '21000000-0000-0000-0000-000000000021',
        '11000000-0000-0000-0000-000000000011',
        '61000000-0000-0000-0000-000000000061',
        expected_updated_at,
        repeat('f', 64),
        'missing_embedding',
        'response-loss retry returns the original attempt'
    ) as jobs;

    if retry_job.id is distinct from repair_job.id then
        raise exception 'repair request key created a duplicate attempt';
    end if;

    begin
        perform public.requeue_document_ingestion_repair(
            '33000000-0000-0000-0000-000000000033',
            '21000000-0000-0000-0000-000000000021',
            '11000000-0000-0000-0000-000000000011',
            '62000000-0000-0000-0000-000000000062',
            expected_updated_at,
            repeat('e', 64),
            'mismatch',
            'a different active request must conflict'
        );
        raise exception 'repair accepted a second active request';
    exception
        when object_not_in_prerequisite_state then null;
    end;

    select updated_at
    into expected_updated_at
    from public.documents
    where id = '32000000-0000-0000-0000-000000000032';

    begin
        perform public.requeue_document_ingestion_repair(
            '32000000-0000-0000-0000-000000000032',
            '21000000-0000-0000-0000-000000000021',
            '11000000-0000-0000-0000-000000000011',
            '63000000-0000-0000-0000-000000000063',
            expected_updated_at - interval '1 second',
            repeat('d', 64),
            'missing_vector',
            'a stale document CAS must conflict'
        );
        raise exception 'repair accepted a stale document timestamp';
    exception
        when serialization_failure then null;
    end;
end;
$$;

select set_config('request.jwt.claim.role', 'authenticated', false);

insert into public.document_relations (
    id,
    owner_id,
    notebook_id,
    source_document_id,
    target_document_id,
    relation_type,
    status,
    confidence,
    signals,
    detector_version
)
values (
    '61000000-0000-0000-0000-000000000061',
    '21000000-0000-0000-0000-000000000021',
    '11000000-0000-0000-0000-000000000011',
    '32000000-0000-0000-0000-000000000032',
    '31000000-0000-0000-0000-000000000031',
    'version_candidate',
    'pending',
    0.9,
    '{"reason_codes":["high_content_containment"]}'::jsonb,
    'hardening-fixture-v1'
);

do $$
declare
    relation_updated_at timestamptz;
    source_family_before uuid;
    source_family_after uuid;
begin
    select version_group_id
    into source_family_before
    from public.documents
    where id = '32000000-0000-0000-0000-000000000032';

    select updated_at
    into relation_updated_at
    from public.document_relations
    where id = '61000000-0000-0000-0000-000000000061';

    begin
        perform public.resolve_document_relation(
            '61000000-0000-0000-0000-000000000061',
            '11000000-0000-0000-0000-000000000011',
            'mark_version',
            relation_updated_at,
            null
        );
        raise exception 'resolution accepted a null reason';
    exception
        when invalid_parameter_value then null;
    end;

    perform public.resolve_document_relation(
        '61000000-0000-0000-0000-000000000061',
        '11000000-0000-0000-0000-000000000011',
        'mark_version',
        relation_updated_at,
        'Confirmed by hardening fixture'
    );

    if not exists (
        select 1
        from public.documents
        where id = '32000000-0000-0000-0000-000000000032'
          and version_number = 2
          and is_current
          and supersedes_document_id =
              '31000000-0000-0000-0000-000000000031'
    ) then
        raise exception 'serialized version resolution did not advance lineage';
    end if;

    select updated_at
    into relation_updated_at
    from public.document_relations
    where id = '61000000-0000-0000-0000-000000000061';

    begin
        perform public.revert_document_relation_resolution(
            '61000000-0000-0000-0000-000000000061',
            '11000000-0000-0000-0000-000000000011',
            relation_updated_at,
            null
        );
        raise exception 'revert accepted a null reason';
    exception
        when invalid_parameter_value then null;
    end;

    perform public.revert_document_relation_resolution(
        '61000000-0000-0000-0000-000000000061',
        '11000000-0000-0000-0000-000000000011',
        relation_updated_at,
        'Undo fixture decision'
    );

    select version_group_id
    into source_family_after
    from public.documents
    where id = '32000000-0000-0000-0000-000000000032';

    if source_family_after <> source_family_before
       or not exists (
           select 1
           from public.documents
           where id = '32000000-0000-0000-0000-000000000032'
             and version_number = 1
             and is_current
             and supersedes_document_id is null
       )
       or not exists (
           select 1
           from public.document_relations
           where id = '61000000-0000-0000-0000-000000000061'
             and relation_type = 'version_candidate'
             and status = 'pending'
       ) then
        raise exception 'revert did not restore the complete prior snapshot';
    end if;

    if not exists (
        select 1
        from public.knowledge_quality_audit as revert_audit
        join public.knowledge_quality_audit as original_audit
          on original_audit.id = revert_audit.reverts_audit_id
        where revert_audit.action = 'revert_resolution'
          and original_audit.action = 'mark_version'
    ) then
        raise exception 'revert did not append a compensating audit event';
    end if;
end;
$$;

select 'knowledge-quality hardening behavior passed' as result;
