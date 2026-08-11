-- Persist temporal-series relation candidates emitted by detector v4.
-- Run after 25_canonical_metadata_parent_projection.sql.

alter table public.document_relations
    drop constraint if exists document_relations_type;

alter table public.document_relations
    add constraint document_relations_type
        check (
            relation_type in (
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
        );

-- Keep the fenced, audited completion implementation from migration 09 and
-- extend only its relation allowlist. Existing reviewed relations are not
-- rewritten: they require a deliberate re-ingestion/re-detection workflow.
do $$
declare
    completion_signature regprocedure := (
        'public.complete_ingestion_job('
        'uuid,text,uuid,text,integer,jsonb,text,text,text,jsonb,jsonb)'
    )::regprocedure;
    function_definition text;
    patched_definition text;
begin
    select pg_get_functiondef(completion_signature)
    into function_definition;

    if function_definition like '%''temporal_series''%' then
        return;
    end if;

    patched_definition := regexp_replace(
        function_definition,
        '(''template_variant''[[:space:]]*\))',
        E'''template_variant'',\n          ''temporal_series''\n      )',
        'g'
    );

    if patched_definition = function_definition then
        raise exception 'Could not extend complete_ingestion_job temporal relation whitelist';
    end if;

    execute patched_definition;
end;
$$;

comment on constraint document_relations_type on public.document_relations is
    'Supported persisted relation taxonomy, including historical temporal series.';
