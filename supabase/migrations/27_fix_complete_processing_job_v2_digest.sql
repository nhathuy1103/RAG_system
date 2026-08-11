-- Repair migration 25 on databases where complete_processing_job_v2 was
-- installed with an unqualified pgcrypto.digest call. Run after
-- 26_temporal_scope_series.sql.

do $migration$
declare
    target_function regprocedure := pg_catalog.to_regprocedure(
        'public.complete_processing_job_v2(uuid,text,uuid,jsonb)'
    );
    function_definition text;
    broken_call constant text :=
        'digest(chunks.content, ''sha256'')';
    fixed_call constant text :=
        'public.knowledge_digest(pg_catalog.convert_to(chunks.content, ''UTF8''), ''sha256'')';
begin
    if target_function is null then
        raise exception 'complete_processing_job_v2 is required before migration 27'
            using errcode = '55000';
    end if;

    function_definition := pg_catalog.pg_get_functiondef(target_function);

    -- Fresh databases already contain the corrected migration-25 body.
    if pg_catalog.strpos(function_definition, fixed_call) > 0 then
        return;
    end if;
    if pg_catalog.strpos(function_definition, broken_call) = 0 then
        raise exception 'Unexpected complete_processing_job_v2 definition; refusing blind rewrite'
            using errcode = '55000';
    end if;

    function_definition := pg_catalog.replace(
        function_definition,
        broken_call,
        fixed_call
    );
    execute function_definition;
end;
$migration$;

revoke all on function public.complete_processing_job_v2(uuid, text, uuid, jsonb)
from public, anon, authenticated;
grant execute on function public.complete_processing_job_v2(uuid, text, uuid, jsonb)
to service_role;
