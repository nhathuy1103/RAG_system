# Metadata audit report

- Audit: `metadata-current-baseline` / `v1`
- Input: `evaluation\metadata_baseline\sample_data\metadata_export.jsonl`
- Documents: **3**
- Chunks: **4**
- Generated at: `2026-08-03T08:45:31.400216+00:00`

## Highest valid coverage

- `document.version_number`: 1.0
- `document.version_group_id`: 1.0
- `document.updated_at`: 1.0
- `chunk.token_count`: 1.0
- `chunk.strategy_version`: 1.0

## Lowest valid coverage

- `chunk.analysis_confidence`: 0.0
- `chunk.authority_metadata`: 0.0
- `document.canonical_document_id`: 0.0
- `chunk.canonical_text`: 0.0
- `chunk.children`: 0.0

## Lowest validity

- `chunk.contextual_search_terms`: 0.666667
- `document.effective_from`: 0.666667
- `chunk.language`: 0.75
- `chunk.page_number`: 0.75
- `chunk.character_count`: 1.0

## Structural issue counts

- `conflicts`: 6
- `consistency`: 8
- `critical`: 3
- `duplicate_ids`: 0
- `outliers`: 1
- `referential`: 3
- `temporal`: 2
- `version`: 3

## Critical errors

- `referential.missing_parent_document` on `document_id` record `cccccccc-1111-4111-8111-111111111111`
- `version.multiple_current_versions` on `is_current` record `11111111-1111-4111-8111-111111111111`
- `version.chunk_parent_version_mismatch` on `document_version` record `aaaaaaaa-2222-4222-8222-222222222222`

## Pre-embedding quality candidates

- Candidate chunks: **1** across **1** source documents.
- `near_duplicate`: 1
- These are detector candidates/actions, not confirmed semantic truth.

## Retrieval risks

- `chunk.embedding_context` valid coverage=0.0
- `chunk.contextual_search_terms` valid coverage=0.5
- `chunk.contextual_summary` valid coverage=0.5
- `chunk.keyword_aliases` valid coverage=0.5
- `chunk.table_header` valid coverage=0.5
- `chunk.content_kind` valid coverage=0.75
- `chunk.document_type` valid coverage=0.75
- `chunk.language` valid coverage=0.75
- `chunk.section_path` valid coverage=0.75
- `chunk.section_title` valid coverage=0.75
- `chunk.title` valid coverage=0.75

## Citation risks

- `chunk.authority_metadata` valid coverage=0.0
- `document.canonical_document_id` valid coverage=0.0
- `chunk.offset_end` valid coverage=0.0
- `chunk.offset_start` valid coverage=0.0
- `chunk.page_count` valid coverage=0.0
- `chunk.provenance_metadata` valid coverage=0.0
- `chunk.sheet_count` valid coverage=0.0
- `chunk.source_chunk_id` valid coverage=0.0
- `chunk.table_identity` valid coverage=0.0
- `chunk.table_row_group` valid coverage=0.0
- `chunk.table_row_group_index` valid coverage=0.0
- `chunk.section_id` valid coverage=0.25
- `chunk.source_block_ids` valid coverage=0.25
- `document.supersedes_document_id` valid coverage=0.333333
- `chunk.table_header` valid coverage=0.5
- `document.effective_from` valid coverage=0.666667
- `document.effective_to` valid coverage=0.666667
- `chunk.content_kind` valid coverage=0.75
- `chunk.document_type` valid coverage=0.75
- `chunk.language` valid coverage=0.75

## Version and hard-filter risks

- Version issues: **3**
- Conflict issues: **6**
- Referential issues: **3**
- No incomplete active filter field in this export.

## Manual checks required

- Review semantic correctness of title, document type, section path and LLM context.
- Review synonym and department-name equivalence; this audit does not guess semantics.
- Review all version, conflict and referential rows before trusting hard filters.
- Confirm that the export is a complete, point-in-time corpus snapshot.

## Known limitations

- Semantic synonym equivalence requires a reviewed vocabulary or human annotation.
- Referential checks are bounded to records present in this export snapshot.
- Structural conflict checks do not establish whether natural-language claims agree.
- The bundled sample is a tool smoke test, not a production-corpus result.

## Interpretation boundary

This report measures the current metadata only. It does not propose a replacement schema.
