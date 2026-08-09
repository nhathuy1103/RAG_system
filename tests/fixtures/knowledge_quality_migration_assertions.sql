\set ON_ERROR_STOP on

insert into auth.users (id)
values ('20000000-0000-0000-0000-000000000002');

insert into public.notebooks (id, owner_id, title)
values (
    '10000000-0000-0000-0000-000000000001',
    '20000000-0000-0000-0000-000000000002',
    'Quality test'
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
    '30000000-0000-0000-0000-000000000003',
    '20000000-0000-0000-0000-000000000002',
    '10000000-0000-0000-0000-000000000001',
    'canonical.txt',
    '20000000-0000-0000-0000-000000000002/10000000-0000-0000-0000-000000000001/30000000-0000-0000-0000-000000000003/canonical.txt',
    'text/plain',
    100,
    repeat('a', 64),
    'ready'
),
(
    '40000000-0000-0000-0000-000000000004',
    '20000000-0000-0000-0000-000000000002',
    '10000000-0000-0000-0000-000000000001',
    'updated.txt',
    '20000000-0000-0000-0000-000000000002/10000000-0000-0000-0000-000000000001/40000000-0000-0000-0000-000000000004/updated.txt',
    'text/plain',
    110,
    repeat('b', 64),
    'processing'
),
(
    '60000000-0000-0000-0000-000000000006',
    '20000000-0000-0000-0000-000000000002',
    '10000000-0000-0000-0000-000000000001',
    'duplicate.txt',
    '20000000-0000-0000-0000-000000000002/10000000-0000-0000-0000-000000000001/60000000-0000-0000-0000-000000000006/duplicate.txt',
    'text/plain',
    120,
    repeat('c', 64),
    'processing'
);

do $$
begin
    begin
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
        values (
            '50000000-0000-0000-0000-000000000005',
            '20000000-0000-0000-0000-000000000002',
            '10000000-0000-0000-0000-000000000001',
            'raw-race.txt',
            '20000000-0000-0000-0000-000000000002/10000000-0000-0000-0000-000000000001/60000000-0000-0000-0000-000000000006/raw-race.txt',
            'text/plain',
            100,
            repeat('a', 64),
            'uploading'
        );
        raise exception 'exact-content unique index did not reject a race';
    exception
        when unique_violation then null;
    end;
end;
$$;

insert into public.ingestion_jobs (
    id,
    owner_id,
    notebook_id,
    document_id,
    status
)
values
(
    '70000000-0000-0000-0000-000000000007',
    '20000000-0000-0000-0000-000000000002',
    '10000000-0000-0000-0000-000000000001',
    '40000000-0000-0000-0000-000000000004',
    'pending'
),
(
    '80000000-0000-0000-0000-000000000008',
    '20000000-0000-0000-0000-000000000002',
    '10000000-0000-0000-0000-000000000001',
    '60000000-0000-0000-0000-000000000006',
    'pending'
);

select set_config('request.jwt.claim.role', 'service_role', false);

do $$
declare
    claimed record;
begin
    select *
    into claimed
    from public.claim_ingestion_job('worker-a', 60);

    if claimed.id <> '70000000-0000-0000-0000-000000000007'::uuid
       or claimed.claim_token is null then
        raise exception 'claim did not return a fenced generation';
    end if;

    if public.renew_ingestion_job_lease(
        claimed.id,
        'worker-a',
        gen_random_uuid(),
        60
    ) then
        raise exception 'wrong generation renewed a lease';
    end if;

    if not public.renew_ingestion_job_lease(
        claimed.id,
        'worker-a',
        claimed.claim_token,
        60
    ) then
        raise exception 'current generation could not renew its lease';
    end if;

    perform public.complete_ingestion_job(
        claimed.id,
        'worker-a',
        claimed.claim_token,
        'test-embedding',
        32,
        jsonb_build_array(
            jsonb_build_object(
                'id', '90000000-0000-0000-0000-000000000009',
                'chunk_index', 0,
                'content', 'Updated policy text.',
                'token_count', 3,
                'metadata', jsonb_build_object('checksum', repeat('d', 64))
            )
        ),
        repeat('e', 64),
        'knowledge-identity-v1',
        repeat('f', 16),
        jsonb_build_object('token_count', 10),
        jsonb_build_array(
            jsonb_build_object(
                'target_document_id',
                '30000000-0000-0000-0000-000000000003',
                'relation_type',
                'version_candidate',
                'confidence',
                0.91,
                'signals',
                jsonb_build_object('document_probe_coverage', 0.8),
                'reason',
                'high_content_containment',
                'detector_version',
                'knowledge-quality-v1'
            )
        )
    );

    if public.fail_ingestion_job(
        claimed.id,
        'worker-a',
        claimed.claim_token,
        'stale failure'
    ) then
        raise exception 'completed generation was allowed to fail again';
    end if;
end;
$$;

do $$
declare
    claimed record;
begin
    select *
    into claimed
    from public.claim_ingestion_job('worker-b', 60);

    if claimed.id <> '80000000-0000-0000-0000-000000000008'::uuid then
        raise exception 'second pending job was not claimed';
    end if;

    perform public.complete_duplicate_ingestion_job(
        claimed.id,
        'worker-b',
        claimed.claim_token,
        '30000000-0000-0000-0000-000000000003',
        repeat('e', 64),
        'knowledge-identity-v1',
        repeat('f', 16),
        jsonb_build_object('token_count', 10)
    );
end;
$$;

select set_config(
    'request.jwt.claim.sub',
    '20000000-0000-0000-0000-000000000002',
    false
);
select set_config('request.jwt.claim.role', 'authenticated', false);

do $$
declare
    relation_id uuid;
    relation_updated_at timestamptz;
begin
    select id, updated_at
    into relation_id, relation_updated_at
    from public.document_relations
    where source_document_id = '40000000-0000-0000-0000-000000000004'
      and relation_type = 'version_candidate';

    perform public.resolve_document_relation(
        relation_id,
        '10000000-0000-0000-0000-000000000001',
        'mark_version',
        relation_updated_at,
        'Confirmed by migration test'
    );

    if not exists (
        select 1
        from public.documents
        where id = '40000000-0000-0000-0000-000000000004'
          and version_number = 2
          and is_current
          and supersedes_document_id =
              '30000000-0000-0000-0000-000000000003'
    ) then
        raise exception 'version resolution did not advance lineage';
    end if;

    if not exists (
        select 1
        from public.documents
        where id = '60000000-0000-0000-0000-000000000006'
          and canonical_document_id =
              '30000000-0000-0000-0000-000000000003'
          and quality_status = 'duplicate'
          and not is_current
    ) then
        raise exception 'strict duplicate was not aliased to its canonical row';
    end if;

    if not exists (
        select 1
        from public.knowledge_quality_audit
        where action = 'mark_version'
    ) then
        raise exception 'human decision was not audited';
    end if;

    begin
        update public.knowledge_quality_audit
        set action = 'tampered'
        where action = 'mark_version';
        raise exception 'append-only audit accepted an update';
    exception
        when insufficient_privilege then null;
    end;
end;
$$;

select 'knowledge-quality migration behavior passed' as result;
