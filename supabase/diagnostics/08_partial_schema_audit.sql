-- Read-only audit for a partially applied knowledge-quality migration 08.
-- Safe to run in the Supabase SQL Editor. This script never mutates data/schema.

with
expected_columns(
    table_name,
    column_name,
    udt_name,
    nullable,
    needs_default,
    needs_identity
) as (
    values
        ('document_relations', 'id', 'uuid', false, true, false),
        ('document_relations', 'owner_id', 'uuid', false, false, false),
        ('document_relations', 'notebook_id', 'uuid', false, false, false),
        ('document_relations', 'source_document_id', 'uuid', false, false, false),
        ('document_relations', 'target_document_id', 'uuid', false, false, false),
        ('document_relations', 'relation_type', 'text', false, false, false),
        ('document_relations', 'status', 'text', false, true, false),
        ('document_relations', 'confidence', 'float8', false, true, false),
        ('document_relations', 'signals', 'jsonb', false, true, false),
        ('document_relations', 'reason', 'text', true, false, false),
        ('document_relations', 'detector_version', 'text', false, true, false),
        ('document_relations', 'preferred_document_id', 'uuid', true, false, false),
        ('document_relations', 'resolved_by', 'uuid', true, false, false),
        ('document_relations', 'resolved_at', 'timestamptz', true, false, false),
        ('document_relations', 'created_at', 'timestamptz', false, true, false),
        ('document_relations', 'updated_at', 'timestamptz', false, true, false),
        ('knowledge_quality_audit', 'id', 'int8', false, false, true),
        ('knowledge_quality_audit', 'owner_id', 'uuid', false, false, false),
        ('knowledge_quality_audit', 'notebook_id', 'uuid', false, false, false),
        ('knowledge_quality_audit', 'relation_id', 'uuid', true, false, false),
        ('knowledge_quality_audit', 'actor_id', 'uuid', true, false, false),
        ('knowledge_quality_audit', 'action', 'text', false, false, false),
        ('knowledge_quality_audit', 'reason', 'text', true, false, false),
        ('knowledge_quality_audit', 'before_state', 'jsonb', false, true, false),
        ('knowledge_quality_audit', 'after_state', 'jsonb', false, true, false),
        ('knowledge_quality_audit', 'created_at', 'timestamptz', false, true, false)
),
column_checks as (
    select
        expected.*,
        columns.column_name is not null
            and columns.udt_name = expected.udt_name
            and (columns.is_nullable = 'YES') = expected.nullable
            and (
                not expected.needs_default
                or columns.column_default is not null
                or columns.is_identity = 'YES'
            )
            and (
                not expected.needs_identity
                or columns.is_identity = 'YES'
            ) as ok,
        columns.udt_name as actual_type,
        columns.is_nullable,
        columns.column_default,
        columns.is_identity
    from expected_columns as expected
    left join information_schema.columns as columns
      on columns.table_schema = 'public'
     and columns.table_name = expected.table_name
     and columns.column_name = expected.column_name
),
expected_constraints(table_name, constraint_name, constraint_type) as (
    values
        ('document_relations', 'document_relations_pkey', 'p'),
        ('document_relations', 'document_relations_owner_id_fkey', 'f'),
        ('document_relations', 'document_relations_source_owner_fk', 'f'),
        ('document_relations', 'document_relations_target_owner_fk', 'f'),
        ('document_relations', 'document_relations_preferred_owner_fk', 'f'),
        ('document_relations', 'document_relations_resolved_by_fkey', 'f'),
        ('document_relations', 'document_relations_source_target', 'c'),
        ('document_relations', 'document_relations_type', 'c'),
        ('document_relations', 'document_relations_status', 'c'),
        ('document_relations', 'document_relations_confidence', 'c'),
        ('document_relations', 'document_relations_signals', 'c'),
        ('document_relations', 'document_relations_reason', 'c'),
        ('document_relations', 'document_relations_detector_version', 'c'),
        ('document_relations', 'document_relations_resolution', 'c'),
        (
            'document_relations',
            'document_relations_source_target_detector_key',
            'u'
        ),
        ('knowledge_quality_audit', 'knowledge_quality_audit_pkey', 'p'),
        (
            'knowledge_quality_audit',
            'knowledge_quality_audit_owner_id_fkey',
            'f'
        ),
        (
            'knowledge_quality_audit',
            'knowledge_quality_audit_relation_id_fkey',
            'f'
        ),
        (
            'knowledge_quality_audit',
            'knowledge_quality_audit_actor_id_fkey',
            'f'
        ),
        (
            'knowledge_quality_audit',
            'knowledge_quality_audit_notebook_owner_fk',
            'f'
        ),
        ('knowledge_quality_audit', 'knowledge_quality_audit_action', 'c'),
        ('knowledge_quality_audit', 'knowledge_quality_audit_reason', 'c'),
        ('knowledge_quality_audit', 'knowledge_quality_audit_states', 'c')
),
constraint_checks as (
    select
        expected.*,
        constraints.oid is not null
            and constraints.contype::text = expected.constraint_type as ok,
        case
            when constraints.oid is null then null
            else pg_get_constraintdef(constraints.oid)
        end as definition
    from expected_constraints as expected
    left join pg_constraint as constraints
      on constraints.conrelid = to_regclass(
          format('public.%I', expected.table_name)
      )
     and constraints.conname = expected.constraint_name
),
expected_indexes(table_name, index_name) as (
    values
        ('document_relations', 'document_relations_pkey'),
        (
            'document_relations',
            'document_relations_source_target_detector_key'
        ),
        ('document_relations', 'document_relations_review_queue_idx'),
        ('document_relations', 'document_relations_target_idx'),
        ('knowledge_quality_audit', 'knowledge_quality_audit_pkey'),
        (
            'knowledge_quality_audit',
            'knowledge_quality_audit_owner_created_idx'
        )
),
index_checks as (
    select
        expected.*,
        indexes.indexname is not null as ok,
        indexes.indexdef
    from expected_indexes as expected
    left join pg_indexes as indexes
      on indexes.schemaname = 'public'
     and indexes.tablename = expected.table_name
     and indexes.indexname = expected.index_name
),
policy_checks as (
    select
        expected.table_name,
        expected.policy_name,
        policies.policyname is not null
            and policies.cmd = 'SELECT'
            and 'authenticated'::name = any(policies.roles)
            and coalesce(policies.qual, '') like '%auth.uid()%'
            and coalesce(policies.qual, '') like '%owner_id%' as ok,
        policies.cmd,
        policies.roles,
        policies.qual
    from (
        values
            ('document_relations', 'document_relations_select_own'),
            (
                'knowledge_quality_audit',
                'knowledge_quality_audit_select_own'
            )
    ) as expected(table_name, policy_name)
    left join pg_policies as policies
      on policies.schemaname = 'public'
     and policies.tablename = expected.table_name
     and policies.policyname = expected.policy_name
),
rls_checks as (
    select
        expected.table_name,
        coalesce(tables.relrowsecurity, false)
            and coalesce(tables.relforcerowsecurity, false) as ok,
        tables.relrowsecurity,
        tables.relforcerowsecurity
    from (
        values ('document_relations'), ('knowledge_quality_audit')
    ) as expected(table_name)
    left join pg_class as tables
      on tables.oid = to_regclass(format('public.%I', expected.table_name))
),
trigger_check as (
    select exists (
        select 1
        from pg_trigger as triggers
        where triggers.tgrelid = to_regclass('public.knowledge_quality_audit')
          and triggers.tgname = 'knowledge_quality_audit_immutable'
          and not triggers.tgisinternal
          and lower(pg_get_triggerdef(triggers.oid)) like '%before%'
          and lower(pg_get_triggerdef(triggers.oid)) like '%update%'
          and lower(pg_get_triggerdef(triggers.oid)) like '%delete%'
          and lower(pg_get_triggerdef(triggers.oid)) like '%for each statement%'
          and lower(pg_get_triggerdef(triggers.oid))
              like '%prevent_knowledge_quality_audit_mutation%'
    ) as ok
),
claim_schema as (
    select
        exists (
            select 1
            from information_schema.columns
            where table_schema = 'public'
              and table_name = 'ingestion_jobs'
              and column_name = 'claim_token'
              and udt_name = 'uuid'
        ) as column_ok,
        coalesce(
            (
                select pg_get_constraintdef(constraints.oid)
                from pg_constraint as constraints
                where constraints.conrelid = to_regclass(
                    'public.ingestion_jobs'
                )
                  and constraints.conname = 'ingestion_jobs_claim'
            ),
            '<missing>'
        ) as claim_constraint
),
expected_claim_functions(function_name, args, marker, result_marker) as (
    values
        ('claim_ingestion_job', 'text, integer', 'claim_token', 'claim_token uuid'),
        (
            'renew_ingestion_job_lease',
            'uuid, text, uuid, integer',
            'claim_token = p_claim_token',
            null
        ),
        (
            'complete_ingestion_job',
            'uuid, text, uuid, text, integer, jsonb, text, text, text, jsonb, jsonb',
            'claim_token = p_claim_token',
            null
        ),
        (
            'complete_duplicate_ingestion_job',
            'uuid, text, uuid, uuid, text, text, text, jsonb',
            'claim_token = p_claim_token',
            null
        ),
        (
            'fail_ingestion_job',
            'uuid, text, uuid, text',
            'claim_token = p_claim_token',
            null
        )
),
claim_function_checks as (
    select
        expected.*,
        functions.oid is not null
            and regexp_replace(
                lower(pg_get_functiondef(functions.oid)),
                '\s+',
                ' ',
                'g'
            ) like '%' || expected.marker || '%'
            and (
                expected.result_marker is null
                or lower(pg_get_function_result(functions.oid))
                    like '%' || expected.result_marker || '%'
            ) as ok
    from expected_claim_functions as expected
    left join lateral (
        select functions.oid
        from pg_proc as functions
        join pg_namespace as namespaces
          on namespaces.oid = functions.pronamespace
        where namespaces.nspname = 'public'
          and functions.proname = expected.function_name
          and oidvectortypes(functions.proargtypes) = expected.args
        limit 1
    ) as functions on true
),
job_state as (
    select
        count(*) as total,
        count(*) filter (where status = 'running') as running,
        count(*) filter (
            where status = 'running'
              and nullif(to_jsonb(jobs) ->> 'claim_token', '') is null
        ) as running_without_token,
        count(*) filter (
            where status <> 'running'
              and nullif(to_jsonb(jobs) ->> 'claim_token', '') is not null
        ) as nonrunning_with_token,
        count(*) filter (
            where status = 'running'
              and (claimed_by is null or lease_expires_at is null)
        ) as running_without_lease,
        count(*) filter (
            where status <> 'running'
              and (claimed_by is not null or lease_expires_at is not null)
        ) as nonrunning_with_lease
    from public.ingestion_jobs as jobs
),
results(section, status, summary, details) as (
    select
        '01 columns: document_relations',
        case when bool_and(ok) then 'PASS' else 'FAIL' end,
        count(*) filter (where ok) || '/' || count(*) || ' correct',
        coalesce(
            jsonb_agg(
                jsonb_build_object(
                    'column', column_name,
                    'expected_type', udt_name,
                    'actual_type', actual_type,
                    'nullable', is_nullable,
                    'default', column_default,
                    'identity', is_identity
                )
            ) filter (where not ok),
            '[]'::jsonb
        )
    from column_checks
    where table_name = 'document_relations'

    union all

    select
        '02 columns: knowledge_quality_audit',
        case when bool_and(ok) then 'PASS' else 'FAIL' end,
        count(*) filter (where ok) || '/' || count(*) || ' correct',
        coalesce(
            jsonb_agg(
                jsonb_build_object(
                    'column', column_name,
                    'expected_type', udt_name,
                    'actual_type', actual_type,
                    'nullable', is_nullable,
                    'default', column_default,
                    'identity', is_identity
                )
            ) filter (where not ok),
            '[]'::jsonb
        )
    from column_checks
    where table_name = 'knowledge_quality_audit'

    union all

    select
        '03 constraints',
        case when bool_and(ok) then 'PASS' else 'FAIL' end,
        count(*) filter (where ok) || '/' || count(*) || ' correct',
        jsonb_object_agg(
            table_name || '.' || constraint_name,
            coalesce(definition, 'MISSING')
        )
    from constraint_checks

    union all

    select
        '04 indexes',
        case when bool_and(ok) then 'PASS' else 'FAIL' end,
        count(*) filter (where ok) || '/' || count(*) || ' correct',
        jsonb_object_agg(
            table_name || '.' || index_name,
            coalesce(indexdef, 'MISSING')
        )
    from index_checks

    union all

    select
        '05 RLS',
        case when bool_and(ok) then 'PASS' else 'FAIL' end,
        count(*) filter (where ok) || '/' || count(*) || ' correct',
        jsonb_object_agg(
            table_name,
            jsonb_build_object(
                'enabled', relrowsecurity,
                'forced', relforcerowsecurity
            )
        )
    from rls_checks

    union all

    select
        '06 policies',
        case when bool_and(ok) then 'PASS' else 'FAIL' end,
        count(*) filter (where ok) || '/' || count(*) || ' correct',
        jsonb_object_agg(
            table_name || '.' || policy_name,
            jsonb_build_object('cmd', cmd, 'roles', roles, 'qual', qual)
        )
    from policy_checks

    union all

    select
        '07 immutable audit trigger',
        case when ok then 'PASS' else 'FAIL' end,
        'knowledge_quality_audit_immutable',
        jsonb_build_object('present_and_correct', ok)
    from trigger_check

    union all

    select
        '08 row counts',
        'INFO',
        'existing rows',
        jsonb_build_object(
            'document_relations', (
                select count(*) from public.document_relations
            ),
            'knowledge_quality_audit', (
                select count(*) from public.knowledge_quality_audit
            )
        )

    union all

    select
        '09 claim schema',
        case
            when column_ok and claim_constraint like '%claim_token%'
                then 'PASS'
            else 'FAIL'
        end,
        'claim_token + ingestion_jobs_claim',
        jsonb_build_object(
            'claim_token_column', column_ok,
            'constraint', claim_constraint
        )
    from claim_schema

    union all

    select
        '10 claim-fenced RPCs',
        case when bool_and(ok) then 'PASS' else 'FAIL' end,
        count(*) filter (where ok) || '/' || count(*) || ' correct',
        jsonb_object_agg(function_name || '(' || args || ')', ok)
    from claim_function_checks

    union all

    select
        '11 ingestion claim rows',
        case
            when running_without_token = 0
             and nonrunning_with_token = 0
             and running_without_lease = 0
             and nonrunning_with_lease = 0
                then 'PASS'
            else 'FAIL'
        end,
        total || ' jobs; ' || running || ' running',
        to_jsonb(job_state)
    from job_state
)
select *
from results
order by section;
