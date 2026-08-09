# Contextual retrieval

## Runtime contract

For every new ingestion job with `contextual_enrichment_enabled=true`, the worker
runs this order:

1. Validate, parse, sanitize, and chunk.
2. Compute document identity and suppress a trusted exact duplicate before any
   contextual LLM cost.
3. Generate one bounded context for every remaining chunk.
4. Build chunk dedup probes from canonical content plus the checksum of the new
   embedding projection.
5. Embed `embedding_text` and persist canonical `content` plus typed metadata.
6. PostgreSQL builds its weighted `search_vector` from content and retrieval
   metadata.

The four logical values are:

```text
content        = canonical chunk content used for answers and deduplication
metadata       = typed source, retrieval, security, and enrichment fields
embedding_text = stable document context + LLM context + content
search_text    = title/section/aliases/LLM terms + content
```

`search_text` is an application projection. PostgreSQL does not duplicate that
full string in JSON; migration 12 builds the equivalent `tsvector` directly from
canonical content and compact metadata fields.

## Trust boundaries

The LLM request contains only title, document type, language, section path,
content kind, table header, a bounded outline/excerpt, and the chunk. It never
receives owner, tenant, ACL, page, hash, document ID, or chunk ID fields.

The LLM may generate only:

- `contextual_summary`
- `contextual_search_terms`

It cannot overwrite content, tenant, permissions, version, status, citation
locators, or duplicate fingerprints. Search terms are retained only when they
are exact substrings of supplied evidence. Numeric claims not present in the
evidence reject the response. Invalid/provider responses retry with bounded
backoff and then use deterministic context when strict mode is off.

## Existing embeddings

Migration 12 rebuilds the PostgreSQL FTS generated column and GIN index. Existing
chunks remain searchable from canonical content and their old metadata, but SQL
cannot generate LLM context or replace dense vectors.

To gain contextual dense and sparse retrieval, an existing document must be
re-ingested from the original object. Identify outstanding chunks with:

```sql
select count(*)
from public.document_chunks
where metadata ->> 'contextual_text_version' is distinct from 'contextual-text-v2'
   or metadata #>> '{context_enrichment,status}' is distinct from 'generated';
```

Drain pending/running ingestion jobs before switching profiles. Re-index in
bounded batches, verify retrieval evaluation and LLM cost/latency, then continue
to the next batch. Do not update only the metadata in SQL: the dense vector must
be regenerated from the same `embedding_text` whose checksum is persisted.
