-- Add validated LLM-generated chunk context to PostgreSQL full-text retrieval.
-- Run after 11_contextual_metadata_fts.sql.

drop index if exists public.document_chunks_search_vector_idx;

alter table public.document_chunks
    drop column if exists search_vector;

alter table public.document_chunks
    add column search_vector tsvector
    generated always as (
        setweight(
            to_tsvector(
                'simple'::regconfig,
                coalesce(
                    metadata #>> '{retrieval_metadata,title}',
                    metadata ->> 'title',
                    ''
                )
            ),
            'A'
        )
        || setweight(
            to_tsvector(
                'simple'::regconfig,
                coalesce(
                    metadata #>> '{retrieval_metadata,section_title}',
                    metadata ->> 'section_title',
                    ''
                )
            ),
            'B'
        )
        || setweight(
            to_tsvector(
                'simple'::regconfig,
                coalesce(
                    metadata #>> '{retrieval_metadata,section_path}',
                    ''
                )
            ),
            'B'
        )
        || setweight(
            to_tsvector(
                'simple'::regconfig,
                coalesce(
                    metadata #>> '{retrieval_metadata,table_header}',
                    ''
                )
            ),
            'B'
        )
        || setweight(
            to_tsvector(
                'simple'::regconfig,
                coalesce(
                    metadata #>> '{retrieval_metadata,contextual_summary}',
                    ''
                )
            ),
            'B'
        )
        || setweight(
            to_tsvector(
                'simple'::regconfig,
                coalesce(
                    metadata #>> '{retrieval_metadata,document_type}',
                    metadata ->> 'document_type',
                    ''
                )
            ),
            'C'
        )
        || setweight(
            to_tsvector(
                'simple'::regconfig,
                coalesce(
                    metadata #>> '{retrieval_metadata,content_kind}',
                    metadata ->> 'content_kind',
                    ''
                )
            ),
            'C'
        )
        || setweight(
            to_tsvector(
                'simple'::regconfig,
                coalesce(
                    metadata #>> '{retrieval_metadata,keyword_aliases}',
                    ''
                )
            ),
            'C'
        )
        || setweight(
            to_tsvector(
                'simple'::regconfig,
                coalesce(
                    metadata #>> '{retrieval_metadata,contextual_search_terms}',
                    ''
                )
            ),
            'C'
        )
        || setweight(to_tsvector('simple'::regconfig, content), 'D')
    ) stored;

create index document_chunks_search_vector_idx
    on public.document_chunks using gin (search_vector);
