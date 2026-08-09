-- Remove only provably redundant chunk metadata.
-- Run after 13_template_scope_conflict.sql.

with compacted as (
    select
        chunks.id,
        chunks.metadata
            - pg_catalog.array_remove(
                array[
                    case
                        when chunks.metadata ->> 'canonical_text' = chunks.content
                        then 'canonical_text'
                    end,
                    case
                        when chunks.metadata -> 'provenance_metadata' = '{}'::jsonb
                        then 'provenance_metadata'
                    end,
                    case
                        when chunks.metadata -> 'authority_metadata' = '{}'::jsonb
                        then 'authority_metadata'
                    end
                ]::text[],
                null
            ) as metadata
    from public.document_chunks as chunks
    where chunks.metadata ->> 'canonical_text' = chunks.content
       or chunks.metadata -> 'provenance_metadata' = '{}'::jsonb
       or chunks.metadata -> 'authority_metadata' = '{}'::jsonb
)
update public.document_chunks as chunks
set metadata = compacted.metadata
from compacted
where chunks.id = compacted.id
  and chunks.metadata is distinct from compacted.metadata;
