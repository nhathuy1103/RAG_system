-- Allow an exact source to be uploaded again after every document that uses
-- that checksum has been archived. Active/draft duplicates remain blocked.
-- Run after 28_guided_document_publish.sql.

do $migration$
declare
    target_function regprocedure := pg_catalog.to_regprocedure(
        'public.create_enterprise_document_upload(uuid,text,text,text,text,bigint,text,text,text,text,text,jsonb,text,date)'
    );
    function_definition text;
    broken_fragment constant text :=
        'where source_files.sha256 = normalized_sha';
    fixed_fragment constant text :=
        'join public.knowledge_documents as registered_documents
          on registered_documents.id = document_versions.document_id
        where source_files.sha256 = normalized_sha
          and registered_documents.status <> ''ARCHIVED''';
begin
    if target_function is null then
        raise exception 'create_enterprise_document_upload is required before migration 29'
            using errcode = '55000';
    end if;

    function_definition := pg_catalog.pg_get_functiondef(target_function);

    -- Fresh databases already contain the corrected migration-23 body.
    if pg_catalog.strpos(
        function_definition,
        'registered_documents.status <> ''ARCHIVED'''
    ) > 0 then
        return;
    end if;
    if pg_catalog.strpos(function_definition, broken_fragment) = 0 then
        raise exception 'Unexpected create_enterprise_document_upload definition; refusing blind rewrite'
            using errcode = '55000';
    end if;

    function_definition := pg_catalog.replace(
        function_definition,
        broken_fragment,
        fixed_fragment
    );
    execute function_definition;
end;
$migration$;

revoke all on function public.create_enterprise_document_upload(
    uuid, text, text, text, text, bigint, text, text,
    text, text, text, jsonb, text, date
) from public, anon;
grant execute on function public.create_enterprise_document_upload(
    uuid, text, text, text, text, bigint, text, text,
    text, text, text, jsonb, text, date
) to authenticated;
