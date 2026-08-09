# Ingestion To Embedding Flow

This repository keeps the original ingest-to-embedding logic from the
source project, but maps it to the hexagonal layout used here.

Public flow:

1. The upload API stores immutable bytes and transactionally creates a
   `pending` ingestion job while moving the document to `processing`.
2. The service-role worker claims one job with a renewable lease and downloads
   the private Storage object. A database maintenance lease can temporarily
   prevent new claims during guarded Qdrant reconciliation.
3. The worker verifies object size and SHA-256 before constructing a
   `DocumentSource`.
4. `documents.application.validation` validates the incoming
   `DocumentSource`.
5. `documents.adapters.parsers.ParserRegistry` chooses a parser by
   extension and returns a `ParsedDocument`. Every supported parser also
   projects its output into the versioned, format-neutral
   `ParsedDocument.content_markdown` representation. Headings, prose, lists,
   code, formulas, page/slide/sheet sections, and structured tables use
   Markdown syntax while page and source-block metadata remain typed fields.
6. Advanced Extraction applies quality, canonical IR, layout, table,
   verification, and multimodal phases.
7. `indexing.application.pipeline.sanitize_parsed_document` normalizes
   text and rebuilds the logical document contract.
8. `documents.application.content_identity` projects parser-specific blocks
   into a versioned format-neutral identity. Adjacent prose is merged and
   structured tables retain row/cell boundaries.
9. `indexing.application.chunker.Chunker` converts
   `ParsedDocument -> LogicalDocument -> ChunkData`. Logical blocks use their
   Markdown rendering for chunk text and retain canonical source text in block
   metadata for provenance.
10. `indexing.ports.embedding_provider.EmbeddingProvider` embeds
   `ChunkData.embedding_text`.
11. `indexing.domain.embedded_chunk.EmbeddedChunk` carries vector,
   provenance, parser, checksum, and retrieval metadata.
12. For Qdrant, `indexing.ports.vector_index.VectorIndex` stages the embedded
    chunks under the current claim-token generation. For pgvector, vectors are
    committed with the canonical Postgres chunks.
13. The fenced completion RPC atomically replaces canonical Postgres chunks,
    succeeds the job, moves the document to `ready`, persists
    `completion_disposition`, and returns either `completed` or
    `duplicate_suppressed`.
14. After `completed`, the worker publishes the staged Qdrant generation. After
    `duplicate_suppressed`, it deletes only that attempt's generation. A lost
    RPC response is resolved by reading the durable disposition instead of
    replaying completion.

An exact-content race may be discovered inside the completion transaction even
after Qdrant staging. The database remains authoritative: it aliases the losing
document only when both durable and effective knowledge-quality modes are `on`,
returns `duplicate_suppressed`, and lets the worker remove the losing
generation. Any accepted failure similarly fences cleanup to the failed claim
token; an expired worker lease can be claimed again.

## Chunk data contracts

The pipeline uses separate contracts for separate lifecycle stages:

- `ChunkData` retains rich chunking metadata such as offsets, block type,
  overlap, table handling, and content-aware embedding context.
- `EmbeddedChunk` promotes stable identity, access control, citation location,
  canonical text, token count, vector, and embedding model to typed fields.
- `EmbeddedChunk.metadata` is limited to source lineage and reproducibility:
  `source_block_ids`, parser name/version, strategy name/version, chunking
  config checksum, and embedding-text checksum.
- `embedding_text` is still used to create the vector but is not persisted in
  `EmbeddedChunk.metadata`. Content-aware retrieval therefore keeps its
  embedding behavior without duplicating the potentially long text.
- Qdrant stores the vector with a compact retrieval payload. Postgres remains
  the canonical chunk store and receives the citation fields required to trace
  a result back to a document version, page, section, and source blocks.

Dependency direction:

- `domain` contains data contracts and pure policy.
- `ports` contain protocols only.
- `application` orchestrates use cases through ports.
- `adapters` contain parser/model/vector-index implementations.
- `bootstrap` wires concrete adapters together.

The application pipeline intentionally does not import concrete parser,
embedding, or vector-index adapters.
