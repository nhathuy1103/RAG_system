-- P2 domain entity/business scope metadata is stored in the existing chunk JSONB.
-- The envelope is optional and versioned so pre-P2 chunks remain valid and are
-- deterministically re-resolved from canonical text/context at read time.

create index if not exists document_chunks_entity_scope_version_idx
    on public.document_chunks ((metadata #>> '{entity_scope,version}'))
    where metadata ? 'entity_scope';

comment on index public.document_chunks_entity_scope_version_idx is
    'Audits versioned P2 entity_scope envelopes without requiring a destructive backfill.';

create index if not exists knowledge_chunks_entity_scope_version_idx
    on public.knowledge_chunks ((metadata #>> '{entity_scope,version}'))
    where metadata ? 'entity_scope';

comment on index public.knowledge_chunks_entity_scope_version_idx is
    'Enterprise chunk index for optional versioned P2 entity_scope metadata.';
