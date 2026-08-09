-- Read-only stage inventory for partially applied migrations 09 and 10.
-- Safe to run in the Supabase SQL Editor; this script never mutates state.

with
function_inventory as (
    select
        functions.proname as function_name,
        pg_get_function_identity_arguments(functions.oid) as arguments,
        pg_get_function_result(functions.oid) as result_type,
        functions.prosecdef as security_definer,
        lower(pg_get_functiondef(functions.oid)) as definition
    from pg_catalog.pg_proc as functions
    join pg_catalog.pg_namespace as namespaces
      on namespaces.oid = functions.pronamespace
    where namespaces.nspname = 'public'
),
expected_functions(stage, object_name, arguments, result_type, body_marker) as (
    values
        (
            '09.01 dense scope',
            'match_document_chunks',
            'p_query_embedding vector, p_owner_id uuid, p_notebook_id uuid, p_document_ids uuid[], p_limit integer',
            'TABLE(chunk_id uuid, document_id uuid, document_version integer, chunk_index integer, content text, metadata jsonb, normalized_content_hash text, exact_duplicate_group_id uuid, score double precision)',
            'p_notebook_id'
        ),
        (
            '09.02 maintenance',
            'begin_ingestion_maintenance',
            'p_maintenance_owner text, p_lease_seconds integer, p_reason text',
            'uuid',
            'maintenance_token'
        ),
        (
            '09.02 maintenance',
            'renew_ingestion_maintenance',
            'p_maintenance_token uuid, p_lease_seconds integer',
            'boolean',
            'maintenance_token'
        ),
        (
            '09.02 maintenance',
            'end_ingestion_maintenance',
            'p_maintenance_token uuid',
            'boolean',
            'maintenance_token'
        ),
        (
            '09.03 claim',
            'claim_ingestion_job',
            'p_worker_id text, p_lease_seconds integer',
            null,
            'maintenance_active'
        ),
        (
            '09.04 enqueue',
            'enqueue_document_ingestion',
            'p_document_id uuid, p_notebook_id uuid, p_embedding_model text, p_embedding_dimensions integer, p_configuration jsonb',
            null,
            'knowledge_quality_mode'
        ),
        (
            '09.05 write guard',
            'guard_authenticated_document_write',
            '',
            'trigger',
            'authenticated clients may only create uploading documents'
        ),
        (
            '09.06 chunk identity',
            'knowledge_exact_chunk_group_id',
            'p_owner_id uuid, p_notebook_id uuid, p_normalization_version text, p_normalized_content_hash text',
            'uuid',
            'rag-chunk-exact-group:'
        ),
        (
            '09.07 exact document identity',
            'complete_duplicate_ingestion_job',
            'p_job_id uuid, p_worker_id text, p_claim_token uuid, p_canonical_document_id uuid, p_normalized_content_hash text, p_normalization_version text, p_loose_content_signature text, p_quality_metadata jsonb',
            'void',
            'duplicate_suppressed'
        ),
        (
            '09.08 atomic completion',
            'complete_ingestion_job',
            'p_job_id uuid, p_worker_id text, p_claim_token uuid, p_embedding_model text, p_embedding_dimensions integer, p_chunks jsonb, p_normalized_content_hash text, p_normalization_version text, p_loose_content_signature text, p_quality_metadata jsonb, p_relations jsonb',
            'text',
            'return ''completed'''
        ),
        (
            '09.09 repair path',
            'requeue_document_ingestion_repair',
            null,
            null,
            'repair_request_key'
        ),
        (
            '09.10 relation resolution',
            'resolve_document_relation',
            'p_relation_id uuid, p_notebook_id uuid, p_action text, p_expected_updated_at timestamp with time zone, p_reason text',
            null,
            'before_documents'
        ),
        (
            '09.11 guarded revert',
            'revert_document_relation_resolution',
            'p_relation_id uuid, p_notebook_id uuid, p_expected_updated_at timestamp with time zone, p_reason text',
            null,
            'reverts_audit_id'
        ),
        (
            '10.02 candidate RPC',
            'find_chunk_dedup_candidates',
            'p_owner_id uuid, p_notebook_id uuid, p_document_id uuid, p_embedding_model text, p_probes jsonb, p_limit_per_probe integer',
            null,
            'lsh_band_matches'
        )
),
function_checks as (
    select
        expected.stage,
        'function'::text as object_type,
        expected.object_name,
        coalesce(bool_or(
            (expected.arguments is null or actual.arguments = expected.arguments)
            and (
                expected.result_type is null
                or actual.result_type = expected.result_type
            )
            and (
                expected.body_marker is null
                or position(expected.body_marker in actual.definition) > 0
            )
        ), false) as present,
        coalesce(
            jsonb_agg(
                jsonb_build_object(
                    'arguments', actual.arguments,
                    'result', actual.result_type,
                    'security_definer', actual.security_definer
                )
            ) filter (where actual.function_name is not null),
            '[]'::jsonb
        ) as details
    from expected_functions as expected
    left join function_inventory as actual
      on actual.function_name = expected.object_name
    group by expected.stage, expected.object_name
),
expected_relations(stage, object_type, object_name) as (
    values
        ('09.02 maintenance', 'table', 'ingestion_control'),
        ('09.06 chunk identity', 'index', 'document_chunks_exact_identity_idx'),
        ('09.06 chunk identity', 'index', 'document_chunks_exact_group_idx'),
        ('09.06 chunk identity', 'index', 'document_chunks_loose_candidate_idx'),
        ('09.07 exact document identity', 'index', 'documents_active_normalized_identity_key'),
        ('09.07 exact document identity', 'index', 'documents_canonical_family_version_key'),
        ('09.07 exact document identity', 'index', 'documents_one_current_canonical_per_family'),
        ('09.09 repair path', 'index', 'ingestion_jobs_repair_request_key'),
        ('09.11 guarded revert', 'index', 'knowledge_quality_audit_one_revert'),
        ('10.01 simhash bands', 'index', 'document_chunks_simhash_band_1_idx'),
        ('10.01 simhash bands', 'index', 'document_chunks_simhash_band_2_idx'),
        ('10.01 simhash bands', 'index', 'document_chunks_simhash_band_3_idx'),
        ('10.01 simhash bands', 'index', 'document_chunks_simhash_band_4_idx'),
        ('10.01 simhash bands', 'index', 'document_chunks_simhash_band_5_idx'),
        ('10.01 simhash bands', 'index', 'document_chunks_simhash_band_6_idx'),
        ('10.01 simhash bands', 'index', 'document_chunks_simhash_band_7_idx'),
        ('10.01 simhash bands', 'index', 'document_chunks_simhash_band_8_idx')
),
relation_checks as (
    select
        expected.stage,
        expected.object_type,
        expected.object_name,
        to_regclass(format('public.%I', expected.object_name)) is not null
            as present,
        case
            when indexes.indexname is null then '{}'::jsonb
            else jsonb_build_object('definition', indexes.indexdef)
        end as details
    from expected_relations as expected
    left join pg_catalog.pg_indexes as indexes
      on indexes.schemaname = 'public'
     and indexes.indexname = expected.object_name
),
expected_columns(stage, table_name, column_name, udt_name) as (
    values
        ('09.03 claim', 'ingestion_jobs', 'completion_disposition', 'text'),
        ('09.06 chunk identity', 'document_chunks', 'normalized_content_hash', 'text'),
        ('09.06 chunk identity', 'document_chunks', 'normalization_version', 'text'),
        ('09.06 chunk identity', 'document_chunks', 'loose_content_signature', 'text'),
        ('09.06 chunk identity', 'document_chunks', 'exact_duplicate_group_id', 'uuid'),
        ('09.09 repair path', 'ingestion_jobs', 'repair_request_key', 'uuid'),
        ('09.11 guarded revert', 'knowledge_quality_audit', 'reverts_audit_id', 'int8')
),
column_checks as (
    select
        expected.stage,
        'column'::text as object_type,
        expected.table_name || '.' || expected.column_name as object_name,
        actual.column_name is not null
            and actual.udt_name = expected.udt_name as present,
        jsonb_build_object(
            'actual_type', actual.udt_name,
            'nullable', actual.is_nullable,
            'default', actual.column_default
        ) as details
    from expected_columns as expected
    left join information_schema.columns as actual
      on actual.table_schema = 'public'
     and actual.table_name = expected.table_name
     and actual.column_name = expected.column_name
),
expected_constraints(stage, table_name, constraint_name) as (
    values
        (
            '09.03 claim',
            'ingestion_jobs',
            'ingestion_jobs_completion_disposition'
        ),
        (
            '09.06 chunk identity',
            'document_chunks',
            'document_chunks_normalized_content_hash_format'
        ),
        (
            '09.06 chunk identity',
            'document_chunks',
            'document_chunks_normalization_version_format'
        ),
        (
            '09.06 chunk identity',
            'document_chunks',
            'document_chunks_loose_content_signature_format'
        ),
        (
            '09.06 chunk identity',
            'document_chunks',
            'document_chunks_exact_group_consistency'
        ),
        (
            '09.11 guarded revert',
            'knowledge_quality_audit',
            'knowledge_quality_audit_reverts_fk'
        )
),
constraint_checks as (
    select
        expected.stage,
        'constraint'::text as object_type,
        expected.table_name || '.' || expected.constraint_name as object_name,
        actual.oid is not null and actual.convalidated as present,
        case
            when actual.oid is null then '{}'::jsonb
            else jsonb_build_object(
                'validated', actual.convalidated,
                'definition', pg_get_constraintdef(actual.oid)
            )
        end as details
    from expected_constraints as expected
    left join pg_catalog.pg_constraint as actual
      on actual.conrelid = to_regclass(format('public.%I', expected.table_name))
     and actual.conname = expected.constraint_name
),
misc_checks as (
    select
        '09.05 write guard'::text as stage,
        'trigger'::text as object_type,
        'documents.documents_authenticated_write_guard'::text as object_name,
        exists (
            select 1
            from pg_catalog.pg_trigger as triggers
            where triggers.tgrelid = to_regclass('public.documents')
              and triggers.tgname = 'documents_authenticated_write_guard'
              and not triggers.tgisinternal
        ) as present,
        '{}'::jsonb as details

    union all

    select
        '09.09 repair path',
        'type',
        'ingestion_repair_issue_kind',
        exists (
            select 1
            from pg_catalog.pg_type as types
            join pg_catalog.pg_namespace as namespaces
              on namespaces.oid = types.typnamespace
            where namespaces.nspname = 'public'
              and types.typname = 'ingestion_repair_issue_kind'
        ),
        '{}'::jsonb
)
select * from function_checks
union all
select * from relation_checks
union all
select * from column_checks
union all
select * from constraint_checks
union all
select * from misc_checks
order by stage, object_type, object_name;
