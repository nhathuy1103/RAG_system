-- Scope-aware legal-template relation support.
-- Run after 12_llm_contextual_retrieval.sql.

alter table public.document_relations
    drop constraint document_relations_type;

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
                'template_variant'
            )
        );

-- Migration 09 owns the fenced completion RPC. Patch its relation whitelist
-- in place so deployed databases keep the exact audited/fenced implementation.
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

    if function_definition like '%''template_variant''%' then
        return;
    end if;

    patched_definition := regexp_replace(
        function_definition,
        '(''technical_duplicate''[[:space:]]*\))',
        E'''technical_duplicate'',\n          ''template_variant''\n      )',
        'g'
    );

    if patched_definition = function_definition then
        raise exception 'Could not extend complete_ingestion_job relation whitelist';
    end if;

    execute patched_definition;
end;
$$;

comment on constraint document_relations_type on public.document_relations is
    'Supported persisted relation taxonomy, including same-template/different-scope review.';
