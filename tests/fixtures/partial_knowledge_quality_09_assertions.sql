-- Assertions for disposable PostgreSQL semantic testing of the partial-09 repair.

do $assert$
declare
    missing_items text;
    claim_definition text;
    complete_result text;
begin
    with required_columns(table_name, column_name) as (
        values
            ('documents', 'normalized_content_hash'),
            ('documents', 'quality_status'),
            ('documents', 'version_group_id'),
            ('ingestion_jobs', 'claim_token'),
            ('ingestion_jobs', 'completion_disposition'),
            ('ingestion_jobs', 'repair_request_key'),
            ('document_chunks', 'normalized_content_hash'),
            ('document_chunks', 'normalization_version'),
            ('document_chunks', 'loose_content_signature'),
            ('document_chunks', 'exact_duplicate_group_id'),
            ('knowledge_quality_audit', 'reverts_audit_id')
    )
    select string_agg(
        format('%I.%I', required.table_name, required.column_name),
        ', '
    )
    into missing_items
    from required_columns as required
    left join information_schema.columns as actual
      on actual.table_schema = 'public'
     and actual.table_name = required.table_name
     and actual.column_name = required.column_name
    where actual.column_name is null;

    if missing_items is not null then
        raise exception 'partial-09 assertion failed, missing columns: %',
            missing_items;
    end if;

    with required_objects(name) as (
        values
            ('documents_active_exact_content_key'),
            ('documents_active_normalized_identity_key'),
            ('documents_canonical_family_version_key'),
            ('documents_one_current_canonical_per_family'),
            ('document_chunks_exact_identity_idx'),
            ('document_chunks_exact_group_idx'),
            ('document_chunks_loose_candidate_idx'),
            ('document_chunks_simhash_band_1_idx'),
            ('ingestion_jobs_repair_request_key')
    )
    select string_agg(required.name, ', ' order by required.name)
    into missing_items
    from required_objects as required
    where to_regclass('public.' || required.name) is null;

    if missing_items is not null then
        raise exception 'partial-09 assertion failed, missing objects: %',
            missing_items;
    end if;

    if to_regprocedure(
        'public.match_document_chunks(vector,uuid[],integer)'
    ) is not null
       or to_regprocedure(
           'public.match_document_chunks(vector,uuid,uuid[],integer)'
       ) is not null then
        raise exception 'partial-09 assertion failed, legacy dense overload remains';
    end if;

    select lower(
        pg_get_functiondef(
            to_regprocedure('public.claim_ingestion_job(text,integer)')
        )
    )
    into claim_definition;

    if claim_definition not like '%public.ingestion_control%'
       or claim_definition not like '%claim_token = gen_random_uuid()%' then
        raise exception 'partial-09 assertion failed, claim RPC is not fenced';
    end if;

    select lower(
        pg_get_function_result(
            to_regprocedure(
                'public.complete_ingestion_job(uuid,text,uuid,text,integer,jsonb,text,text,text,jsonb,jsonb)'
            )
        )
    )
    into complete_result;

    if complete_result <> 'text' then
        raise exception 'partial-09 assertion failed, completion RPC result is %',
            complete_result;
    end if;

    if to_regprocedure(
        'public.requeue_document_ingestion_repair(uuid,uuid,uuid,uuid,timestamptz,text,public.ingestion_repair_issue_kind,text)'
    ) is null
       or to_regprocedure(
           'public.find_chunk_dedup_candidates(uuid,uuid,uuid,text,jsonb,integer)'
       ) is null then
        raise exception 'partial-09 assertion failed, final 09/10 repair RPCs missing';
    end if;
end;
$assert$;
