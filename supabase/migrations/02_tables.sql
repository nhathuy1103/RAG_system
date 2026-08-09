-- All application tables. Run 01_extensions.sql first.

-- notebooks
create table public.notebooks (
    id uuid primary key default gen_random_uuid(),
    owner_id uuid not null default auth.uid()
        references auth.users (id) on delete cascade,
    title text not null,
    description text not null default '',
    is_active boolean not null default true,
    created_at timestamptz not null default now(),
    updated_at timestamptz not null default now(),
    constraint notebooks_title_length
        check (char_length(btrim(title)) between 1 and 200),
    constraint notebooks_id_owner_key
        unique (id, owner_id)
);

comment on table public.notebooks is
    'User-owned collections of documents and conversations.';
comment on column public.notebooks.owner_id is
    'Supabase Auth user that exclusively owns this notebook.';
comment on column public.notebooks.description is
    'Optional user-provided description of the notebook.';
comment on column public.notebooks.is_active is
    'Soft-delete flag. False = archived by the owner; row and all child data are kept.';

create index notebooks_owner_updated_idx
    on public.notebooks (owner_id, updated_at desc, id);

-- documents
create table public.documents (
    id uuid primary key default gen_random_uuid(),
    owner_id uuid not null default auth.uid()
        references auth.users (id) on delete cascade,
    notebook_id uuid not null,
    original_filename text not null,
    storage_bucket text not null default 'documents',
    storage_object_path text not null,
    mime_type text not null,
    size_bytes bigint not null,
    content_hash text,
    status text not null default 'uploading',
    error_message text,
    is_active boolean not null default true,
    created_at timestamptz not null default now(),
    updated_at timestamptz not null default now(),
    constraint documents_notebook_owner_fk
        foreign key (notebook_id, owner_id)
        references public.notebooks (id, owner_id)
        on delete cascade,
    constraint documents_id_notebook_owner_key
        unique (id, notebook_id, owner_id),
    constraint documents_storage_object_key
        unique (storage_bucket, storage_object_path),
    constraint documents_filename_length
        check (char_length(btrim(original_filename)) between 1 and 255),
    constraint documents_storage_bucket
        check (storage_bucket = 'documents'),
    constraint documents_storage_path
        check (
            storage_object_path like
                owner_id::text || '/' ||
                notebook_id::text || '/' ||
                id::text || '/%'
        ),
    constraint documents_mime_type
        check (
            mime_type in (
                'application/pdf',
                'application/vnd.openxmlformats-officedocument.wordprocessingml.document',
                'application/vnd.openxmlformats-officedocument.presentationml.presentation',
                'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
                'text/csv',
                'text/markdown',
                'text/html',
                'text/plain'
            )
        ),
    -- 10 MiB, matches MAX_FILE_SIZE_BYTES and Storage bucket limit.
    constraint documents_size
        check (size_bytes between 1 and 10485760),
    constraint documents_content_hash
        check (content_hash is null or content_hash ~ '^[0-9a-f]{64}$'),
    constraint documents_status
        check (status in ('uploading', 'uploaded', 'processing', 'ready', 'failed')),
    constraint documents_error_message
        check (error_message is null or char_length(btrim(error_message)) > 0)
);

comment on table public.documents is
    'Metadata for immutable files uploaded to a notebook; file bytes live in Supabase Storage.';
comment on column public.documents.content_hash is
    'Lowercase SHA-256 used to detect duplicate content without rejecting it.';
comment on column public.documents.storage_object_path is
    'Object key: owner_id/notebook_id/document_id/sanitized_filename.';
comment on column public.documents.is_active is
    'Soft-delete flag. False = archived by the owner; storage object, vectors and row are kept.';

create index documents_owner_notebook_updated_idx
    on public.documents (owner_id, notebook_id, updated_at desc, id);
create index documents_owner_content_hash_idx
    on public.documents (owner_id, content_hash)
    where content_hash is not null;

-- ingestion_jobs
create table public.ingestion_jobs (
    id uuid primary key default gen_random_uuid(),
    owner_id uuid not null default auth.uid()
        references auth.users (id) on delete cascade,
    notebook_id uuid not null,
    document_id uuid not null,
    attempt_number integer not null default 1,
    status text not null default 'pending',
    embedding_model text not null default 'text-embedding-3-small',
    embedding_dimensions integer not null default 1536,
    configuration jsonb not null default '{}'::jsonb,
    error_message text,
    claimed_by text,
    lease_expires_at timestamptz,
    started_at timestamptz,
    completed_at timestamptz,
    created_at timestamptz not null default now(),
    updated_at timestamptz not null default now(),
    constraint ingestion_jobs_document_owner_fk
        foreign key (document_id, notebook_id, owner_id)
        references public.documents (id, notebook_id, owner_id)
        on delete cascade,
    constraint ingestion_jobs_attempt
        check (attempt_number > 0),
    constraint ingestion_jobs_status
        check (status in ('pending', 'running', 'succeeded', 'failed', 'cancelled')),
    constraint ingestion_jobs_embedding_model
        check (char_length(btrim(embedding_model)) between 1 and 200),
    constraint ingestion_jobs_embedding_dimensions
        check (embedding_dimensions > 0),
    constraint ingestion_jobs_configuration
        check (jsonb_typeof(configuration) = 'object'),
    constraint ingestion_jobs_error_message
        check (error_message is null or char_length(btrim(error_message)) > 0),
    constraint ingestion_jobs_attempt_key
        unique (document_id, attempt_number),
    constraint ingestion_jobs_claim
        check (
            (status = 'running' and claimed_by is not null and lease_expires_at is not null)
            or
            (status <> 'running' and claimed_by is null and lease_expires_at is null)
        )
);

comment on table public.ingestion_jobs is
    'Retryable attempts that parse, chunk, embed and index one uploaded document.';

create unique index ingestion_jobs_one_active_per_document_idx
    on public.ingestion_jobs (document_id)
    where status in ('pending', 'running');
create index ingestion_jobs_owner_notebook_created_idx
    on public.ingestion_jobs (owner_id, notebook_id, created_at desc, id);
create index ingestion_jobs_claimable_idx
    on public.ingestion_jobs (created_at, id)
    where status in ('pending', 'running');

-- document_chunks
create table public.document_chunks (
    id uuid primary key default gen_random_uuid(),
    owner_id uuid not null default auth.uid()
        references auth.users (id) on delete cascade,
    notebook_id uuid not null,
    document_id uuid not null,
    chunk_index integer not null,
    content text not null,
    token_count integer not null,
    metadata jsonb not null default '{}'::jsonb,
    embedding vector(1536),
    created_at timestamptz not null default now(),
    constraint document_chunks_document_owner_fk
        foreign key (document_id, notebook_id, owner_id)
        references public.documents (id, notebook_id, owner_id)
        on delete cascade,
    constraint document_chunks_id_document_notebook_owner_key
        unique (id, document_id, notebook_id, owner_id),
    constraint document_chunks_document_index_key
        unique (document_id, chunk_index),
    constraint document_chunks_index
        check (chunk_index >= 0),
    constraint document_chunks_content
        check (char_length(btrim(content)) > 0),
    constraint document_chunks_token_count
        check (token_count > 0),
    constraint document_chunks_metadata
        check (jsonb_typeof(metadata) = 'object')
);

comment on table public.document_chunks is
    'Canonical chunk text, metadata and embedding vector (pgvector).';
comment on column public.document_chunks.embedding is
    'text-embedding-3-small vector, 1536 dims. Null until the ingestion worker embeds this chunk.';

create index document_chunks_owner_notebook_document_idx
    on public.document_chunks (owner_id, notebook_id, document_id, chunk_index);

-- HNSW index, cosine distance.
create index document_chunks_embedding_hnsw_idx
    on public.document_chunks
    using hnsw (embedding vector_cosine_ops);

-- conversations
create table public.conversations (
    id uuid primary key default gen_random_uuid(),
    owner_id uuid not null default auth.uid()
        references auth.users (id) on delete cascade,
    notebook_id uuid not null,
    title text not null default 'New chat',
    created_at timestamptz not null default now(),
    updated_at timestamptz not null default now(),
    constraint conversations_notebook_owner_fk
        foreign key (notebook_id, owner_id)
        references public.notebooks (id, owner_id)
        on delete cascade,
    constraint conversations_id_notebook_owner_key
        unique (id, notebook_id, owner_id),
    constraint conversations_title_length
        check (char_length(btrim(title)) between 1 and 200)
);

comment on table public.conversations is
    'Independent chat sessions scoped to exactly one user-owned notebook.';

create index conversations_owner_notebook_updated_idx
    on public.conversations (owner_id, notebook_id, updated_at desc, id);

-- messages
create table public.messages (
    id uuid primary key default gen_random_uuid(),
    owner_id uuid not null default auth.uid()
        references auth.users (id) on delete cascade,
    notebook_id uuid not null,
    conversation_id uuid not null,
    role text not null,
    content text not null default '',
    status text not null default 'completed',
    model text,
    input_tokens integer,
    output_tokens integer,
    error_message text,
    created_at timestamptz not null default now(),
    updated_at timestamptz not null default now(),
    constraint messages_conversation_owner_fk
        foreign key (conversation_id, notebook_id, owner_id)
        references public.conversations (id, notebook_id, owner_id)
        on delete cascade,
    constraint messages_id_notebook_owner_key
        unique (id, notebook_id, owner_id),
    constraint messages_role
        check (role in ('user', 'assistant')),
    constraint messages_content
        check (role = 'assistant' or char_length(btrim(content)) > 0),
    constraint messages_status
        check (status in ('pending', 'completed', 'failed')),
    constraint messages_model
        check (model is null or char_length(btrim(model)) between 1 and 200),
    constraint messages_input_tokens
        check (input_tokens is null or input_tokens >= 0),
    constraint messages_output_tokens
        check (output_tokens is null or output_tokens >= 0),
    constraint messages_error_message
        check (error_message is null or char_length(btrim(error_message)) > 0)
);

comment on table public.messages is
    'User prompts and assistant responses ordered within a conversation by created_at and id.';

create index messages_owner_conversation_created_idx
    on public.messages (owner_id, conversation_id, created_at, id);

-- message_citations
create table public.message_citations (
    id uuid primary key default gen_random_uuid(),
    owner_id uuid not null default auth.uid()
        references auth.users (id) on delete cascade,
    notebook_id uuid not null,
    message_id uuid not null,
    document_id uuid not null,
    chunk_id uuid not null,
    ordinal integer not null,
    quote text not null,
    retrieval_score double precision,
    created_at timestamptz not null default now(),
    constraint message_citations_message_owner_fk
        foreign key (message_id, notebook_id, owner_id)
        references public.messages (id, notebook_id, owner_id)
        on delete cascade,
    constraint message_citations_chunk_owner_fk
        foreign key (chunk_id, document_id, notebook_id, owner_id)
        references public.document_chunks (id, document_id, notebook_id, owner_id)
        on delete cascade,
    constraint message_citations_ordinal
        check (ordinal > 0),
    constraint message_citations_quote
        check (char_length(btrim(quote)) > 0),
    constraint message_citations_message_ordinal_key
        unique (message_id, ordinal),
    constraint message_citations_message_chunk_key
        unique (message_id, chunk_id)
);

comment on table public.message_citations is
    'Ordered evidence snapshots linking an assistant response to canonical document chunks.';

create index message_citations_owner_message_ordinal_idx
    on public.message_citations (owner_id, message_id, ordinal);
create index message_citations_chunk_idx
    on public.message_citations (chunk_id);

-- profiles
create table public.profiles (
    id uuid primary key
        references auth.users (id) on delete cascade,
    display_name text,
    avatar_url text,
    role text not null default 'user',
    created_at timestamptz not null default now(),
    updated_at timestamptz not null default now(),
    constraint profiles_role
        check (role in ('user', 'admin')),
    constraint profiles_display_name_length
        check (display_name is null or char_length(btrim(display_name)) between 1 and 200)
);

comment on table public.profiles is
    'App-owned 1:1 extension of auth.users - display name, avatar, admin role.';
comment on column public.profiles.role is
    'Read by the Custom Access Token Hook (see 03_functions_triggers.sql) to inject the user_role JWT claim.';
