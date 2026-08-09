-- Additive structured-fact persistence for row-level duplicate, version, and
-- conflict analysis. Run after 15_structured_retrieval_filters.sql.

-- ---------------------------------------------------------------------------
-- Extracted table snapshots
-- ---------------------------------------------------------------------------

create table public.table_snapshots (
    id uuid primary key default gen_random_uuid(),
    owner_id uuid not null references auth.users (id) on delete cascade,
    notebook_id uuid not null,
    document_id uuid not null,
    source_chunk_id uuid
        references public.document_chunks (id) on delete set null,
    snapshot_key text not null,
    input_content_hash text not null,
    schema_fingerprint text not null,
    template_fingerprint text,
    table_index integer not null,
    page_from integer,
    page_to integer,
    source_locator jsonb not null default '{}'::jsonb,
    normalized_schema jsonb not null default '{}'::jsonb,
    row_count integer not null default 0,
    column_count integer not null default 0,
    extractor_name text not null default 'structured-fact-analyzer',
    extractor_version text not null,
    publication_time timestamptz,
    effective_from timestamptz,
    effective_to timestamptz,
    observed_at timestamptz,
    ingested_at timestamptz not null default now(),
    source_publisher text,
    source_type text not null default 'unknown',
    authority_level integer,
    authority_metadata jsonb not null default '{}'::jsonb,
    warnings jsonb not null default '[]'::jsonb,
    extraction_confidence double precision not null default 0,
    created_at timestamptz not null default now(),
    updated_at timestamptz not null default now(),
    constraint table_snapshots_document_owner_fk
        foreign key (document_id, notebook_id, owner_id)
        references public.documents (id, notebook_id, owner_id)
        on delete cascade,
    constraint table_snapshots_id_document_notebook_owner_key
        unique (id, document_id, notebook_id, owner_id),
    constraint table_snapshots_id_notebook_owner_key
        unique (id, notebook_id, owner_id),
    constraint table_snapshots_extractor_key
        unique (
            document_id,
            snapshot_key,
            extractor_version,
            input_content_hash
        ),
    constraint table_snapshots_snapshot_key
        check (char_length(btrim(snapshot_key)) between 1 and 500),
    constraint table_snapshots_input_content_hash
        check (input_content_hash ~ '^[0-9a-f]{64}$'),
    constraint table_snapshots_schema_fingerprint
        check (schema_fingerprint ~ '^[0-9a-f]{64}$'),
    constraint table_snapshots_template_fingerprint
        check (
            template_fingerprint is null
            or template_fingerprint ~ '^[0-9a-f]{64}$'
        ),
    constraint table_snapshots_location
        check (
            table_index >= 0
            and (page_from is null or page_from > 0)
            and (page_to is null or page_to > 0)
            and (
                page_from is null
                or page_to is null
                or page_to >= page_from
            )
        ),
    constraint table_snapshots_provenance
        check (
            jsonb_typeof(source_locator) = 'object'
            and jsonb_typeof(normalized_schema) in ('object', 'array')
        ),
    constraint table_snapshots_shape
        check (row_count >= 0 and column_count >= 0),
    constraint table_snapshots_extractor
        check (
            char_length(btrim(extractor_name)) between 1 and 100
            and char_length(btrim(extractor_version)) between 1 and 100
        ),
    constraint table_snapshots_temporal_interval
        check (
            effective_from is null
            or effective_to is null
            or effective_to >= effective_from
        ),
    constraint table_snapshots_source
        check (
            char_length(btrim(source_type)) between 1 and 100
            and (
                source_publisher is null
                or char_length(btrim(source_publisher)) between 1 and 500
            )
            and (
                authority_level is null
                or authority_level between 0 and 100
            )
            and jsonb_typeof(authority_metadata) = 'object'
        ),
    constraint table_snapshots_warnings
        check (jsonb_typeof(warnings) = 'array'),
    constraint table_snapshots_confidence
        check (extraction_confidence between 0 and 1)
);

comment on table public.table_snapshots is
    'Versioned structured-table extractions with source, temporal, authority, and schema provenance.';
comment on column public.table_snapshots.snapshot_key is
    'Extractor-stable table identity within one document.';
comment on column public.table_snapshots.source_chunk_id is
    'Optional citation anchor; cleared safely when a replaceable chunk is removed during re-indexing.';

create index table_snapshots_document_extractor_idx
    on public.table_snapshots (
        owner_id,
        notebook_id,
        document_id,
        extractor_version,
        snapshot_key
    );
create index table_snapshots_template_idx
    on public.table_snapshots (
        owner_id,
        notebook_id,
        template_fingerprint,
        schema_fingerprint
    )
    where template_fingerprint is not null;
create index table_snapshots_schema_idx
    on public.table_snapshots (
        owner_id,
        notebook_id,
        schema_fingerprint,
        document_id
    );
create index table_snapshots_effective_time_idx
    on public.table_snapshots (
        owner_id,
        notebook_id,
        effective_from,
        effective_to,
        publication_time
    );

-- ---------------------------------------------------------------------------
-- Structured claims with row/cell provenance and business qualifiers
-- ---------------------------------------------------------------------------

create table public.structured_claims (
    id uuid primary key default gen_random_uuid(),
    owner_id uuid not null references auth.users (id) on delete cascade,
    notebook_id uuid not null,
    document_id uuid not null,
    snapshot_id uuid not null,
    source_chunk_id uuid
        references public.document_chunks (id) on delete set null,
    claim_key text not null,
    row_identity text not null,
    row_identity_hash text not null,
    row_index integer not null,
    data_row_ordinal integer,
    page_number integer,
    source_text text,
    source_cells jsonb not null default '[]'::jsonb,
    provenance jsonb not null default '{}'::jsonb,
    subject_identity jsonb not null,
    subject_identity_hash text not null,
    candidate_identity_hash text not null,
    predicate text not null,
    value_type text not null,
    normalized_value jsonb not null,
    numeric_value numeric,
    unit text,
    currency text,
    qualifiers jsonb not null default '{}'::jsonb,
    qualifier_hash text not null,
    publication_time timestamptz,
    effective_from timestamptz,
    effective_to timestamptz,
    observed_at timestamptz,
    ingested_at timestamptz not null default now(),
    source_publisher text,
    source_type text not null default 'unknown',
    authority_level integer,
    authority_metadata jsonb not null default '{}'::jsonb,
    confidence double precision not null default 0,
    is_derived boolean not null default false,
    derivation jsonb not null default '{}'::jsonb,
    extractor_version text not null,
    created_at timestamptz not null default now(),
    updated_at timestamptz not null default now(),
    constraint structured_claims_snapshot_owner_fk
        foreign key (snapshot_id, document_id, notebook_id, owner_id)
        references public.table_snapshots (
            id,
            document_id,
            notebook_id,
            owner_id
        )
        on delete cascade,
    constraint structured_claims_id_snapshot_notebook_owner_key
        unique (id, snapshot_id, notebook_id, owner_id),
    constraint structured_claims_snapshot_claim_extractor_key
        unique (snapshot_id, claim_key, extractor_version),
    constraint structured_claims_claim_key
        check (char_length(btrim(claim_key)) between 1 and 500),
    constraint structured_claims_row_provenance
        check (
            char_length(btrim(row_identity)) between 1 and 2000
            and row_identity_hash ~ '^[0-9a-f]{64}$'
            and row_index >= 0
            and (data_row_ordinal is null or data_row_ordinal >= 0)
            and (page_number is null or page_number > 0)
            and (source_text is null or char_length(btrim(source_text)) > 0)
            and jsonb_typeof(source_cells) = 'array'
            and jsonb_typeof(provenance) = 'object'
        ),
    constraint structured_claims_subject
        check (
            jsonb_typeof(subject_identity) = 'object'
            and subject_identity_hash ~ '^[0-9a-f]{64}$'
            and candidate_identity_hash ~ '^[0-9a-f]{64}$'
            and char_length(btrim(predicate)) between 1 and 200
        ),
    constraint structured_claims_value
        check (
            value_type in (
                'money',
                'number',
                'percentage',
                'quantity',
                'date',
                'datetime',
                'boolean',
                'text',
                'category',
                'identifier'
            )
            and jsonb_typeof(normalized_value) = 'object'
            and (unit is null or char_length(btrim(unit)) between 1 and 100)
            and (currency is null or currency ~ '^[A-Z]{3}$')
        ),
    constraint structured_claims_qualifiers
        check (
            jsonb_typeof(qualifiers) = 'object'
            and qualifier_hash ~ '^[0-9a-f]{64}$'
        ),
    constraint structured_claims_temporal_interval
        check (
            effective_from is null
            or effective_to is null
            or effective_to >= effective_from
        ),
    constraint structured_claims_authority
        check (
            char_length(btrim(source_type)) between 1 and 100
            and (
                source_publisher is null
                or char_length(btrim(source_publisher)) between 1 and 500
            )
            and (
                authority_level is null
                or authority_level between 0 and 100
            )
            and jsonb_typeof(authority_metadata) = 'object'
        ),
    constraint structured_claims_confidence
        check (confidence between 0 and 1),
    constraint structured_claims_derivation
        check (jsonb_typeof(derivation) = 'object'),
    constraint structured_claims_extractor_version
        check (char_length(btrim(extractor_version)) between 1 and 100)
);

comment on table public.structured_claims is
    'Row-level business claims keyed by subject, predicate, qualifier set, and effective time.';
comment on column public.structured_claims.source_cells is
    'Ordered cell-level provenance, including source column and raw/normalized values.';
comment on column public.structured_claims.provenance is
    'Page/table/row/column/cell locator used to open the exact source evidence.';
comment on column public.structured_claims.derivation is
    'Formula and input claim keys for derived values; never replaces original provenance.';

create index structured_claims_subject_predicate_qualifier_idx
    on public.structured_claims (
        owner_id,
        notebook_id,
        subject_identity_hash,
        predicate,
        qualifier_hash
    );
create index structured_claims_candidate_identity_idx
    on public.structured_claims (
        notebook_id,
        candidate_identity_hash,
        predicate,
        document_id
    );
create index structured_claims_row_predicate_idx
    on public.structured_claims (
        owner_id,
        notebook_id,
        snapshot_id,
        row_identity_hash,
        predicate
    );
create index structured_claims_effective_time_idx
    on public.structured_claims (
        owner_id,
        notebook_id,
        predicate,
        effective_from,
        effective_to,
        publication_time
    );
create index structured_claims_qualifiers_gin_idx
    on public.structured_claims using gin (qualifiers jsonb_path_ops);
create index structured_claims_subject_gin_idx
    on public.structured_claims using gin (subject_identity jsonb_path_ops);

-- ---------------------------------------------------------------------------
-- Directional row/claim relationships and immutable review audit
-- ---------------------------------------------------------------------------

create table public.claim_relations (
    id uuid primary key default gen_random_uuid(),
    owner_id uuid not null references auth.users (id) on delete cascade,
    notebook_id uuid not null,
    source_snapshot_id uuid not null,
    target_snapshot_id uuid not null,
    source_claim_id uuid,
    target_claim_id uuid,
    relation_type text not null,
    scope_relation text not null default 'unknown',
    qualifier_compatibility text not null default 'unknown',
    temporal_compatibility text not null default 'unknown',
    confidence double precision not null default 0,
    evidence jsonb not null default '{}'::jsonb,
    reason text,
    detector_name text not null default 'structured-fact-analyzer',
    detector_version text not null,
    review_status text not null default 'pending',
    resolved_by uuid references auth.users (id) on delete set null,
    resolved_at timestamptz,
    created_at timestamptz not null default now(),
    updated_at timestamptz not null default now(),
    constraint claim_relations_source_snapshot_owner_fk
        foreign key (source_snapshot_id, notebook_id, owner_id)
        references public.table_snapshots (id, notebook_id, owner_id)
        on delete cascade,
    constraint claim_relations_target_snapshot_owner_fk
        foreign key (target_snapshot_id, notebook_id, owner_id)
        references public.table_snapshots (id, notebook_id, owner_id)
        on delete cascade,
    constraint claim_relations_source_claim_owner_fk
        foreign key (
            source_claim_id,
            source_snapshot_id,
            notebook_id,
            owner_id
        )
        references public.structured_claims (
            id,
            snapshot_id,
            notebook_id,
            owner_id
        )
        on delete cascade,
    constraint claim_relations_target_claim_owner_fk
        foreign key (
            target_claim_id,
            target_snapshot_id,
            notebook_id,
            owner_id
        )
        references public.structured_claims (
            id,
            snapshot_id,
            notebook_id,
            owner_id
        )
        on delete cascade,
    constraint claim_relations_id_notebook_owner_key
        unique (id, notebook_id, owner_id),
    constraint claim_relations_distinct_claims
        check (
            source_claim_id is null
            or target_claim_id is null
            or source_claim_id <> target_claim_id
        ),
    constraint claim_relations_type
        check (
            relation_type in (
                'unchanged',
                'updated',
                'added',
                'removed',
                'equivalent',
                'source_updates_target',
                'target_updates_source',
                'source_supersedes_target',
                'target_supersedes_source',
                'source_contains_target',
                'target_contains_source',
                'source_only',
                'target_only',
                'conflict_candidate',
                'conflict',
                'conditional_variant',
                'distinct',
                'uncertain'
            )
        ),
    constraint claim_relations_endpoints
        check (
            (
                relation_type in ('source_only', 'removed')
                and source_claim_id is not null
                and target_claim_id is null
            )
            or (
                relation_type in ('target_only', 'added')
                and source_claim_id is null
                and target_claim_id is not null
            )
            or (
                relation_type = 'uncertain'
                and (
                    source_claim_id is not null
                    or target_claim_id is not null
                )
            )
            or (
                relation_type not in (
                    'source_only',
                    'target_only',
                    'removed',
                    'added',
                    'uncertain'
                )
                and source_claim_id is not null
                and target_claim_id is not null
            )
        ),
    constraint claim_relations_scope
        check (
            scope_relation in (
                'same',
                'source_contains_target',
                'target_contains_source',
                'overlaps',
                'disjoint',
                'unknown'
            )
        ),
    constraint claim_relations_qualifiers
        check (
            qualifier_compatibility in (
                'equal',
                'compatible',
                'disjoint',
                'unknown'
            )
        ),
    constraint claim_relations_temporal
        check (
            temporal_compatibility in (
                'same',
                'same_interval',
                'source_contains_target',
                'target_contains_source',
                'before',
                'after',
                'overlaps',
                'non_overlapping',
                'unknown'
            )
        ),
    constraint claim_relations_confidence
        check (confidence between 0 and 1),
    constraint claim_relations_evidence
        check (jsonb_typeof(evidence) = 'object'),
    constraint claim_relations_reason
        check (reason is null or char_length(btrim(reason)) between 1 and 2000),
    constraint claim_relations_detector
        check (
            char_length(btrim(detector_name)) between 1 and 100
            and char_length(btrim(detector_version)) between 1 and 100
        ),
    constraint claim_relations_review_status
        check (
            review_status in (
                'pending',
                'auto_confirmed',
                'confirmed',
                'dismissed'
            )
        ),
    constraint claim_relations_resolution
        check (
            (
                review_status = 'pending'
                and resolved_by is null
                and resolved_at is null
            )
            or (
                review_status = 'auto_confirmed'
                and resolved_by is null
                and resolved_at is not null
            )
            or (
                review_status in ('confirmed', 'dismissed')
                and resolved_by is not null
                and resolved_at is not null
            )
        )
);

comment on table public.claim_relations is
    'Directional row/claim comparisons; source_only and target_only preserve full-table diff semantics.';

create unique index claim_relations_detector_key
    on public.claim_relations (
        source_snapshot_id,
        target_snapshot_id,
        coalesce(
            source_claim_id,
            '00000000-0000-0000-0000-000000000000'::uuid
        ),
        coalesce(
            target_claim_id,
            '00000000-0000-0000-0000-000000000000'::uuid
        ),
        detector_name,
        detector_version
    );
create index claim_relations_review_queue_idx
    on public.claim_relations (
        owner_id,
        notebook_id,
        review_status,
        confidence desc,
        created_at desc
    );
create index claim_relations_target_idx
    on public.claim_relations (
        owner_id,
        notebook_id,
        target_claim_id,
        relation_type
    );
create index claim_relations_source_idx
    on public.claim_relations (
        owner_id,
        notebook_id,
        source_claim_id,
        relation_type
    );

create table public.structured_claim_audit (
    id bigint generated always as identity primary key,
    owner_id uuid not null references auth.users (id) on delete cascade,
    notebook_id uuid not null,
    document_id uuid,
    relation_id uuid references public.claim_relations (id) on delete set null,
    actor_id uuid references auth.users (id) on delete set null,
    action text not null,
    reason text,
    before_state jsonb not null default '{}'::jsonb,
    after_state jsonb not null default '{}'::jsonb,
    created_at timestamptz not null default now(),
    constraint structured_claim_audit_notebook_owner_fk
        foreign key (notebook_id, owner_id)
        references public.notebooks (id, owner_id)
        on delete cascade,
    constraint structured_claim_audit_document_owner_fk
        foreign key (document_id, notebook_id, owner_id)
        references public.documents (id, notebook_id, owner_id)
        on delete cascade,
    constraint structured_claim_audit_action
        check (char_length(btrim(action)) between 1 and 100),
    constraint structured_claim_audit_reason
        check (reason is null or char_length(btrim(reason)) between 1 and 2000),
    constraint structured_claim_audit_states
        check (
            jsonb_typeof(before_state) = 'object'
            and jsonb_typeof(after_state) = 'object'
        )
);

comment on table public.structured_claim_audit is
    'Append-only audit trail for structured extraction replacement and claim-relation review.';

create index structured_claim_audit_owner_created_idx
    on public.structured_claim_audit (
        owner_id,
        notebook_id,
        created_at desc,
        id desc
    );

create function public.prevent_structured_claim_audit_mutation()
returns trigger
language plpgsql
set search_path = ''
as $$
begin
    if pg_trigger_depth() > 1 then
        return null;
    end if;
    raise exception 'structured_claim_audit is append-only'
        using errcode = '42501';
end;
$$;

create trigger structured_claim_audit_immutable
before update or delete on public.structured_claim_audit
for each statement execute function public.prevent_structured_claim_audit_mutation();

-- ---------------------------------------------------------------------------
-- RLS: owners can inspect derived facts but cannot write them directly.
-- Service workers persist through the guarded RPC below.
-- ---------------------------------------------------------------------------

alter table public.table_snapshots enable row level security;
alter table public.structured_claims enable row level security;
alter table public.claim_relations enable row level security;
alter table public.structured_claim_audit enable row level security;

create policy table_snapshots_select_own
on public.table_snapshots for select to authenticated
using ((select auth.uid()) = owner_id);

create policy structured_claims_select_own
on public.structured_claims for select to authenticated
using ((select auth.uid()) = owner_id);

create policy claim_relations_select_own
on public.claim_relations for select to authenticated
using ((select auth.uid()) = owner_id);

create policy structured_claim_audit_select_own
on public.structured_claim_audit for select to authenticated
using ((select auth.uid()) = owner_id);

revoke all on table public.table_snapshots from public, anon, authenticated;
revoke all on table public.structured_claims from public, anon, authenticated;
revoke all on table public.claim_relations from public, anon, authenticated;
revoke all on table public.structured_claim_audit from public, anon, authenticated;

grant select on table public.table_snapshots to authenticated;
grant select on table public.structured_claims to authenticated;
grant select on table public.claim_relations to authenticated;
grant select on table public.structured_claim_audit to authenticated;

grant all privileges on table public.table_snapshots to service_role;
grant all privileges on table public.structured_claims to service_role;
grant all privileges on table public.claim_relations to service_role;
grant all privileges on table public.structured_claim_audit to service_role;

-- ---------------------------------------------------------------------------
-- Atomic, idempotent worker persistence.
--
-- Snapshot payloads require snapshot_key/input_content_hash/schema_fingerprint.
-- Claim payloads address a snapshot by snapshot_key. Relation payloads address
-- the new source claim by source_snapshot_key/source_claim_key and an existing
-- target by target_snapshot_id plus target_claim_id (or target_claim_key).
-- ---------------------------------------------------------------------------

create function public.replace_structured_facts_for_document(
    p_job_id uuid,
    p_document_id uuid,
    p_extractor_version text,
    p_table_snapshots jsonb,
    p_claims jsonb,
    p_relations jsonb default '[]'::jsonb
)
returns jsonb
language plpgsql
security definer
set search_path = ''
as $$
declare
    selected_job public.ingestion_jobs;
    selected_document public.documents;
    selected_snapshot public.table_snapshots;
    target_snapshot public.table_snapshots;
    snapshot_payload jsonb;
    claim_payload jsonb;
    relation_payload jsonb;
    selected_source_claim_id uuid;
    selected_target_claim_id uuid;
    snapshot_key_value text;
    snapshot_input_hash text;
    snapshot_schema_hash text;
    claim_snapshot_key text;
    claim_key_value text;
    claim_row_identity text;
    claim_row_identity_hash text;
    claim_subject_identity jsonb;
    claim_subject_identity_hash text;
    claim_candidate_identity_hash text;
    claim_qualifiers jsonb;
    claim_qualifier_hash text;
    claim_normalized_value jsonb;
    claim_provenance jsonb;
    claim_source_chunk_id uuid;
    claim_value_type text;
    normalized_extractor_version text;
    relation_review_status text;
    before_snapshot_count integer;
    before_claim_count integer;
    snapshot_count integer := 0;
    claim_count integer := 0;
    relation_count integer := 0;
begin
    if auth.role() <> 'service_role' then
        raise exception 'Service role is required'
            using errcode = '42501';
    end if;

    normalized_extractor_version := nullif(btrim(p_extractor_version), '');
    if normalized_extractor_version is null
       or char_length(normalized_extractor_version) > 100 then
        raise exception 'Invalid extractor version'
            using errcode = '22023';
    end if;
    if jsonb_typeof(p_table_snapshots) <> 'array'
       or jsonb_typeof(p_claims) <> 'array'
       or jsonb_typeof(p_relations) <> 'array' then
        raise exception 'Structured fact payloads must be JSON arrays'
            using errcode = '22023';
    end if;

    select jobs.*
    into selected_job
    from public.ingestion_jobs as jobs
    where jobs.id = p_job_id
      and jobs.document_id = p_document_id
    for update;

    if not found then
        raise exception 'Ingestion job was not found for this document'
            using errcode = 'P0002';
    end if;
    if selected_job.status <> 'succeeded' then
        raise exception 'Structured facts require a succeeded ingestion job'
            using errcode = '55000';
    end if;
    if selected_job.completion_disposition = 'duplicate_suppressed' then
        raise exception 'Cannot persist facts for a duplicate-suppressed job'
            using errcode = '55000';
    end if;
    if exists (
        select 1
        from public.ingestion_jobs as newer_job
        where newer_job.document_id = selected_job.document_id
          and newer_job.notebook_id = selected_job.notebook_id
          and newer_job.owner_id = selected_job.owner_id
          and newer_job.attempt_number > selected_job.attempt_number
          and newer_job.status = 'succeeded'
          and newer_job.completion_disposition
                is distinct from 'duplicate_suppressed'
    ) then
        raise exception 'A newer successful ingestion supersedes this job'
            using errcode = '40001';
    end if;

    select documents.*
    into selected_document
    from public.documents as documents
    where documents.id = p_document_id
      and documents.notebook_id = selected_job.notebook_id
      and documents.owner_id = selected_job.owner_id
      and documents.status = 'ready'
      and documents.canonical_document_id is null
    for update;

    if not found then
        raise exception 'Ready canonical document was not found'
            using errcode = 'P0002';
    end if;

    perform pg_catalog.pg_advisory_xact_lock(
        pg_catalog.hashtextextended(
            selected_job.owner_id::text
                || ':' || selected_job.notebook_id::text
                || ':' || selected_job.document_id::text
                || ':' || normalized_extractor_version,
            0
        )
    );

    select count(*)::integer
    into before_snapshot_count
    from public.table_snapshots as snapshots
    where snapshots.document_id = selected_document.id
      and snapshots.notebook_id = selected_document.notebook_id
      and snapshots.owner_id = selected_document.owner_id
      and snapshots.extractor_version = normalized_extractor_version;

    select count(*)::integer
    into before_claim_count
    from public.structured_claims as claims
    where claims.document_id = selected_document.id
      and claims.notebook_id = selected_document.notebook_id
      and claims.owner_id = selected_document.owner_id
      and claims.extractor_version = normalized_extractor_version;

    -- This delete is deliberately scoped to one document and one extractor
    -- version. Any exception later in the function rolls the transaction back.
    delete from public.table_snapshots
    where table_snapshots.document_id = selected_document.id
      and table_snapshots.notebook_id = selected_document.notebook_id
      and table_snapshots.owner_id = selected_document.owner_id
      and table_snapshots.extractor_version = normalized_extractor_version;

    for snapshot_payload in
        select payload.value
        from jsonb_array_elements(p_table_snapshots) as payload(value)
    loop
        snapshot_key_value := coalesce(
            nullif(btrim(snapshot_payload ->> 'snapshot_key'), ''),
            nullif(btrim(snapshot_payload ->> 'table_id'), '')
        );
        snapshot_input_hash := coalesce(
            nullif(snapshot_payload ->> 'input_content_hash', ''),
            pg_catalog.encode(
                public.knowledge_digest(
                    pg_catalog.convert_to(snapshot_payload::text, 'UTF8'),
                    'sha256'
                ),
                'hex'
            )
        );
        snapshot_schema_hash := coalesce(
            nullif(snapshot_payload ->> 'schema_fingerprint', ''),
            pg_catalog.encode(
                public.knowledge_digest(
                    pg_catalog.convert_to(
                        coalesce(
                            snapshot_payload -> 'normalized_schema',
                            snapshot_payload -> 'header_mapping',
                            '{}'::jsonb
                        )::text,
                        'UTF8'
                    ),
                    'sha256'
                ),
                'hex'
            )
        );
        if jsonb_typeof(snapshot_payload) <> 'object'
           or snapshot_key_value is null
           or snapshot_input_hash !~ '^[0-9a-f]{64}$'
           or snapshot_schema_hash !~ '^[0-9a-f]{64}$' then
            raise exception 'Invalid table snapshot payload'
                using errcode = '22023';
        end if;
        if nullif(snapshot_payload ->> 'source_chunk_id', '') is not null
           and not exists (
                select 1
                from public.document_chunks as chunks
                where chunks.id = (
                    snapshot_payload ->> 'source_chunk_id'
                )::uuid
                  and chunks.document_id = selected_document.id
                  and chunks.notebook_id = selected_document.notebook_id
                  and chunks.owner_id = selected_document.owner_id
           ) then
            raise exception 'Snapshot source chunk is outside this document'
                using errcode = '23503';
        end if;

        insert into public.table_snapshots (
            owner_id,
            notebook_id,
            document_id,
            source_chunk_id,
            snapshot_key,
            input_content_hash,
            schema_fingerprint,
            template_fingerprint,
            table_index,
            page_from,
            page_to,
            source_locator,
            normalized_schema,
            row_count,
            column_count,
            extractor_name,
            extractor_version,
            publication_time,
            effective_from,
            effective_to,
            observed_at,
            ingested_at,
            source_publisher,
            source_type,
            authority_level,
            authority_metadata,
            warnings,
            extraction_confidence
        )
        values (
            selected_document.owner_id,
            selected_document.notebook_id,
            selected_document.id,
            nullif(snapshot_payload ->> 'source_chunk_id', '')::uuid,
            snapshot_key_value,
            snapshot_input_hash,
            snapshot_schema_hash,
            nullif(snapshot_payload ->> 'template_fingerprint', ''),
            coalesce((snapshot_payload ->> 'table_index')::integer, 0),
            nullif(snapshot_payload ->> 'page_from', '')::integer,
            nullif(snapshot_payload ->> 'page_to', '')::integer,
            coalesce(
                snapshot_payload -> 'source_locator',
                jsonb_build_object('table_id', snapshot_key_value)
            ),
            coalesce(snapshot_payload -> 'normalized_schema', '{}'::jsonb),
            coalesce((snapshot_payload ->> 'row_count')::integer, 0),
            coalesce(
                (snapshot_payload ->> 'column_count')::integer,
                case
                    when jsonb_typeof(
                        snapshot_payload -> 'normalized_schema'
                    ) = 'array'
                    then jsonb_array_length(
                        snapshot_payload -> 'normalized_schema'
                    )
                    else 0
                end
            ),
            coalesce(
                nullif(btrim(snapshot_payload ->> 'extractor_name'), ''),
                'structured-fact-analyzer'
            ),
            normalized_extractor_version,
            nullif(snapshot_payload ->> 'publication_time', '')::timestamptz,
            nullif(snapshot_payload ->> 'effective_from', '')::timestamptz,
            nullif(snapshot_payload ->> 'effective_to', '')::timestamptz,
            coalesce(
                nullif(snapshot_payload ->> 'observed_at', '')::timestamptz,
                now()
            ),
            coalesce(
                nullif(snapshot_payload ->> 'ingested_at', '')::timestamptz,
                now()
            ),
            nullif(btrim(snapshot_payload ->> 'source_publisher'), ''),
            coalesce(
                nullif(btrim(snapshot_payload ->> 'source_type'), ''),
                'unknown'
            ),
            nullif(snapshot_payload ->> 'authority_level', '')::integer,
            coalesce(snapshot_payload -> 'authority_metadata', '{}'::jsonb),
            coalesce(snapshot_payload -> 'warnings', '[]'::jsonb),
            coalesce(
                (snapshot_payload ->> 'extraction_confidence')::double precision,
                (snapshot_payload ->> 'confidence')::double precision,
                0
            )
        );
        snapshot_count := snapshot_count + 1;
    end loop;

    for claim_payload in
        select payload.value
        from jsonb_array_elements(p_claims) as payload(value)
    loop
        claim_provenance := coalesce(
            claim_payload -> 'provenance',
            '{}'::jsonb
        );
        claim_snapshot_key := coalesce(
            nullif(btrim(claim_payload ->> 'snapshot_key'), ''),
            nullif(btrim(claim_provenance ->> 'table_id'), '')
        );
        claim_key_value := coalesce(
            nullif(btrim(claim_payload ->> 'claim_key'), ''),
            nullif(btrim(claim_payload ->> 'claim_identity_hash'), '')
        );
        claim_row_identity := coalesce(
            nullif(btrim(claim_payload ->> 'row_identity'), ''),
            nullif(btrim(claim_payload ->> 'subject_key'), '')
        );
        claim_row_identity_hash := coalesce(
            nullif(claim_payload ->> 'row_identity_hash', ''),
            case
                when claim_row_identity is not null then pg_catalog.encode(
                    public.knowledge_digest(
                        pg_catalog.convert_to(claim_row_identity, 'UTF8'),
                        'sha256'
                    ),
                    'hex'
                )
                else null
            end
        );
        claim_subject_identity := coalesce(
            claim_payload -> 'subject_identity',
            jsonb_build_object('subject_key', claim_row_identity)
                || coalesce(claim_payload -> 'scope', '{}'::jsonb)
        );
        claim_subject_identity_hash := coalesce(
            nullif(claim_payload ->> 'subject_identity_hash', ''),
            nullif(claim_payload #>> '{scope,scope_identity_hash}', ''),
            pg_catalog.encode(
                public.knowledge_digest(
                    pg_catalog.convert_to(claim_subject_identity::text, 'UTF8'),
                    'sha256'
                ),
                'hex'
            )
        );
        claim_candidate_identity_hash := nullif(
            claim_payload ->> 'candidate_identity_hash',
            ''
        );
        claim_qualifiers := coalesce(
            claim_payload -> 'qualifiers',
            '{}'::jsonb
        );
        claim_qualifier_hash := coalesce(
            nullif(claim_payload ->> 'qualifier_hash', ''),
            nullif(
                claim_payload #>> '{qualifiers,stable_identity_hash}',
                ''
            )
        );
        claim_normalized_value := coalesce(
            claim_payload -> 'normalized_value',
            claim_payload -> 'value'
        );
        claim_source_chunk_id := coalesce(
            nullif(claim_payload ->> 'source_chunk_id', '')::uuid,
            nullif(claim_provenance ->> 'chunk_id', '')::uuid
        );
        claim_value_type := coalesce(
            nullif(btrim(claim_payload ->> 'value_type'), ''),
            case
                when nullif(
                    claim_normalized_value ->> 'currency',
                    ''
                ) is not null then 'money'
                when jsonb_typeof(claim_normalized_value -> 'value')
                    = 'number' then 'number'
                when jsonb_typeof(claim_normalized_value -> 'value')
                    = 'boolean' then 'boolean'
                else 'text'
            end
        );
        if jsonb_typeof(claim_payload) <> 'object'
           or claim_snapshot_key is null
           or claim_key_value is null
           or claim_row_identity is null
           or jsonb_typeof(claim_subject_identity) <> 'object'
           or nullif(btrim(claim_payload ->> 'predicate'), '') is null
           or claim_value_type is null
           or jsonb_typeof(claim_normalized_value) <> 'object'
           or claim_row_identity_hash !~ '^[0-9a-f]{64}$'
           or claim_subject_identity_hash !~ '^[0-9a-f]{64}$'
           or claim_candidate_identity_hash !~ '^[0-9a-f]{64}$'
           or claim_qualifier_hash !~ '^[0-9a-f]{64}$' then
            raise exception 'Invalid structured claim payload'
                using errcode = '22023';
        end if;
        if claim_source_chunk_id is not null
           and not exists (
                select 1
                from public.document_chunks as chunks
                where chunks.id = claim_source_chunk_id
                  and chunks.document_id = selected_document.id
                  and chunks.notebook_id = selected_document.notebook_id
                  and chunks.owner_id = selected_document.owner_id
           ) then
            raise exception 'Claim source chunk is outside this document'
                using errcode = '23503';
        end if;

        select snapshots.*
        into selected_snapshot
        from public.table_snapshots as snapshots
        where snapshots.document_id = selected_document.id
          and snapshots.notebook_id = selected_document.notebook_id
          and snapshots.owner_id = selected_document.owner_id
          and snapshots.extractor_version = normalized_extractor_version
          and snapshots.snapshot_key = claim_snapshot_key;

        if not found then
            raise exception 'Claim references an unknown snapshot key'
                using errcode = '23503';
        end if;

        insert into public.structured_claims (
            owner_id,
            notebook_id,
            document_id,
            snapshot_id,
            source_chunk_id,
            claim_key,
            row_identity,
            row_identity_hash,
            row_index,
            data_row_ordinal,
            page_number,
            source_text,
            source_cells,
            provenance,
            subject_identity,
            subject_identity_hash,
            candidate_identity_hash,
            predicate,
            value_type,
            normalized_value,
            numeric_value,
            unit,
            currency,
            qualifiers,
            qualifier_hash,
            publication_time,
            effective_from,
            effective_to,
            observed_at,
            ingested_at,
            source_publisher,
            source_type,
            authority_level,
            authority_metadata,
            confidence,
            is_derived,
            derivation,
            extractor_version
        )
        values (
            selected_document.owner_id,
            selected_document.notebook_id,
            selected_document.id,
            selected_snapshot.id,
            claim_source_chunk_id,
            claim_key_value,
            claim_row_identity,
            claim_row_identity_hash,
            coalesce(
                (claim_payload ->> 'row_index')::integer,
                (claim_provenance ->> 'row_index')::integer,
                0
            ),
            coalesce(
                nullif(claim_payload ->> 'data_row_ordinal', '')::integer,
                nullif(claim_provenance ->> 'data_row_ordinal', '')::integer
            ),
            coalesce(
                nullif(claim_payload ->> 'page_number', '')::integer,
                nullif(claim_provenance ->> 'page_number', '')::integer
            ),
            coalesce(
                nullif(btrim(claim_payload ->> 'source_text'), ''),
                nullif(btrim(claim_normalized_value ->> 'raw_value'), '')
            ),
            coalesce(
                claim_payload -> 'source_cells',
                case
                    when claim_provenance = '{}'::jsonb then '[]'::jsonb
                    else jsonb_build_array(claim_provenance)
                end
            ),
            claim_provenance,
            claim_subject_identity,
            claim_subject_identity_hash,
            claim_candidate_identity_hash,
            btrim(claim_payload ->> 'predicate'),
            claim_value_type,
            claim_normalized_value,
            coalesce(
                nullif(claim_payload ->> 'numeric_value', '')::numeric,
                case
                    when claim_normalized_value ->> 'value'
                        ~ '^[+-]?[0-9]+([.][0-9]+)?$'
                    then (claim_normalized_value ->> 'value')::numeric
                    else null
                end
            ),
            coalesce(
                nullif(btrim(claim_payload ->> 'unit'), ''),
                nullif(btrim(claim_normalized_value ->> 'unit'), '')
            ),
            nullif(
                upper(
                    btrim(
                        coalesce(
                            claim_payload ->> 'currency',
                            claim_normalized_value ->> 'currency'
                        )
                    )
                ),
                ''
            ),
            claim_qualifiers,
            claim_qualifier_hash,
            coalesce(
                nullif(claim_payload ->> 'publication_time', '')::timestamptz,
                nullif(
                    claim_payload #>> '{temporal,publication_time}',
                    ''
                )::timestamptz,
                selected_snapshot.publication_time
            ),
            coalesce(
                nullif(claim_payload ->> 'effective_from', '')::timestamptz,
                nullif(
                    claim_payload #>> '{temporal,effective_from}',
                    ''
                )::timestamptz,
                selected_snapshot.effective_from
            ),
            coalesce(
                nullif(claim_payload ->> 'effective_to', '')::timestamptz,
                nullif(
                    claim_payload #>> '{temporal,effective_to}',
                    ''
                )::timestamptz,
                selected_snapshot.effective_to
            ),
            coalesce(
                nullif(claim_payload ->> 'observed_at', '')::timestamptz,
                nullif(
                    claim_payload #>> '{temporal,observed_at}',
                    ''
                )::timestamptz,
                selected_snapshot.observed_at,
                now()
            ),
            coalesce(
                nullif(claim_payload ->> 'ingested_at', '')::timestamptz,
                nullif(
                    claim_payload #>> '{temporal,ingested_at}',
                    ''
                )::timestamptz,
                selected_snapshot.ingested_at,
                now()
            ),
            coalesce(
                nullif(btrim(claim_payload ->> 'source_publisher'), ''),
                nullif(
                    btrim(claim_payload #>> '{authority,publisher}'),
                    ''
                ),
                selected_snapshot.source_publisher
            ),
            coalesce(
                nullif(btrim(claim_payload ->> 'source_type'), ''),
                nullif(
                    btrim(claim_payload #>> '{authority,source_type}'),
                    ''
                ),
                selected_snapshot.source_type
            ),
            coalesce(
                nullif(claim_payload ->> 'authority_level', '')::integer,
                nullif(
                    claim_payload #>> '{authority,authority_level}',
                    ''
                )::integer,
                selected_snapshot.authority_level
            ),
            coalesce(
                claim_payload -> 'authority_metadata',
                claim_payload -> 'authority',
                selected_snapshot.authority_metadata
            ),
            coalesce(
                (claim_payload ->> 'confidence')::double precision,
                (claim_payload ->> 'extraction_confidence')::double precision,
                0
            ),
            coalesce(
                (claim_payload ->> 'is_derived')::boolean,
                jsonb_typeof(claim_payload -> 'derivation') = 'object',
                false
            ),
            case
                when jsonb_typeof(claim_payload -> 'derivation') = 'object'
                then claim_payload -> 'derivation'
                else '{}'::jsonb
            end,
            normalized_extractor_version
        );
        claim_count := claim_count + 1;
    end loop;

    for relation_payload in
        select payload.value
        from jsonb_array_elements(p_relations) as payload(value)
    loop
        if jsonb_typeof(relation_payload) <> 'object'
           or nullif(
                btrim(relation_payload ->> 'source_snapshot_key'),
                ''
           ) is null
           or nullif(relation_payload ->> 'target_snapshot_id', '') is null then
            raise exception 'Invalid claim relation payload'
                using errcode = '22023';
        end if;

        select snapshots.*
        into selected_snapshot
        from public.table_snapshots as snapshots
        where snapshots.document_id = selected_document.id
          and snapshots.notebook_id = selected_document.notebook_id
          and snapshots.owner_id = selected_document.owner_id
          and snapshots.extractor_version = normalized_extractor_version
          and snapshots.snapshot_key = btrim(
              relation_payload ->> 'source_snapshot_key'
          );

        if not found then
            raise exception 'Relation references an unknown source snapshot'
                using errcode = '23503';
        end if;

        select snapshots.*
        into target_snapshot
        from public.table_snapshots as snapshots
        where snapshots.id = (relation_payload ->> 'target_snapshot_id')::uuid
          and snapshots.notebook_id = selected_document.notebook_id
          and snapshots.owner_id = selected_document.owner_id;

        if not found then
            raise exception 'Relation target snapshot is outside this tenant'
                using errcode = '23503';
        end if;

        selected_source_claim_id := null;
        if nullif(relation_payload ->> 'source_claim_key', '') is not null then
            select claims.id
            into selected_source_claim_id
            from public.structured_claims as claims
            where claims.snapshot_id = selected_snapshot.id
              and claims.notebook_id = selected_document.notebook_id
              and claims.owner_id = selected_document.owner_id
              and claims.claim_key = relation_payload ->> 'source_claim_key';
            if not found then
                raise exception 'Relation references an unknown source claim'
                    using errcode = '23503';
            end if;
        end if;

        selected_target_claim_id := nullif(
            relation_payload ->> 'target_claim_id',
            ''
        )::uuid;
        if selected_target_claim_id is null
           and nullif(relation_payload ->> 'target_claim_key', '') is not null then
            select claims.id
            into selected_target_claim_id
            from public.structured_claims as claims
            where claims.snapshot_id = target_snapshot.id
              and claims.notebook_id = selected_document.notebook_id
              and claims.owner_id = selected_document.owner_id
              and claims.claim_key = relation_payload ->> 'target_claim_key';
            if not found then
                raise exception 'Relation references an unknown target claim'
                    using errcode = '23503';
            end if;
        end if;

        relation_review_status := coalesce(
            nullif(btrim(relation_payload ->> 'review_status'), ''),
            'pending'
        );
        if relation_review_status not in ('pending', 'auto_confirmed') then
            raise exception 'Worker may only create pending or auto-confirmed relations'
                using errcode = '22023';
        end if;

        insert into public.claim_relations (
            owner_id,
            notebook_id,
            source_snapshot_id,
            target_snapshot_id,
            source_claim_id,
            target_claim_id,
            relation_type,
            scope_relation,
            qualifier_compatibility,
            temporal_compatibility,
            confidence,
            evidence,
            reason,
            detector_name,
            detector_version,
            review_status,
            resolved_at
        )
        values (
            selected_document.owner_id,
            selected_document.notebook_id,
            selected_snapshot.id,
            target_snapshot.id,
            selected_source_claim_id,
            selected_target_claim_id,
            btrim(relation_payload ->> 'relation_type'),
            case coalesce(
                nullif(btrim(relation_payload ->> 'scope_relation'), ''),
                'unknown'
            )
                when 'left_contains_right' then 'source_contains_target'
                when 'right_contains_left' then 'target_contains_source'
                else coalesce(
                    nullif(
                        btrim(relation_payload ->> 'scope_relation'),
                        ''
                    ),
                    'unknown'
                )
            end,
            coalesce(
                nullif(
                    btrim(
                        relation_payload ->> 'qualifier_compatibility'
                    ),
                    ''
                ),
                'unknown'
            ),
            case coalesce(
                nullif(
                    btrim(
                        relation_payload ->> 'temporal_compatibility'
                    ),
                    ''
                ),
                nullif(
                    btrim(relation_payload ->> 'temporal_relation'),
                    ''
                ),
                'unknown'
            )
                when 'left_contains_right' then 'source_contains_target'
                when 'right_contains_left' then 'target_contains_source'
                else coalesce(
                    nullif(
                        btrim(
                            relation_payload ->> 'temporal_compatibility'
                        ),
                        ''
                    ),
                    nullif(
                        btrim(relation_payload ->> 'temporal_relation'),
                        ''
                    ),
                    'unknown'
                )
            end,
            coalesce(
                (relation_payload ->> 'confidence')::double precision,
                0
            ),
            coalesce(
                relation_payload -> 'evidence',
                jsonb_build_object(
                    'reason_codes',
                    coalesce(
                        relation_payload -> 'reason_codes',
                        '[]'::jsonb
                    )
                )
            ),
            nullif(btrim(relation_payload ->> 'reason'), ''),
            coalesce(
                nullif(btrim(relation_payload ->> 'detector_name'), ''),
                'structured-fact-analyzer'
            ),
            coalesce(
                nullif(btrim(relation_payload ->> 'detector_version'), ''),
                normalized_extractor_version
            ),
            relation_review_status,
            case
                when relation_review_status = 'auto_confirmed' then now()
                else null
            end
        );
        relation_count := relation_count + 1;
    end loop;

    insert into public.structured_claim_audit (
        owner_id,
        notebook_id,
        document_id,
        actor_id,
        action,
        reason,
        before_state,
        after_state
    )
    values (
        selected_document.owner_id,
        selected_document.notebook_id,
        selected_document.id,
        null,
        'replace_document_facts',
        'Atomic worker replacement for one extractor version',
        jsonb_build_object(
            'job_id', selected_job.id,
            'extractor_version', normalized_extractor_version,
            'snapshot_count', before_snapshot_count,
            'claim_count', before_claim_count
        ),
        jsonb_build_object(
            'job_id', selected_job.id,
            'extractor_version', normalized_extractor_version,
            'snapshot_count', snapshot_count,
            'claim_count', claim_count,
            'relation_count', relation_count
        )
    );

    return jsonb_build_object(
        'document_id', selected_document.id,
        'job_id', selected_job.id,
        'extractor_version', normalized_extractor_version,
        'table_count', snapshot_count,
        'snapshot_count', snapshot_count,
        'claim_count', claim_count,
        'relation_count', relation_count
    );
end;
$$;

revoke all on function public.replace_structured_facts_for_document(
    uuid, uuid, text, jsonb, jsonb, jsonb
) from public, anon, authenticated;
grant execute on function public.replace_structured_facts_for_document(
    uuid, uuid, text, jsonb, jsonb, jsonb
) to service_role;

-- Human review is owner-scoped and uses optimistic concurrency. Direct table
-- updates remain unavailable to authenticated clients.
create function public.resolve_structured_claim_relation(
    p_relation_id uuid,
    p_notebook_id uuid,
    p_action text,
    p_expected_updated_at timestamptz,
    p_reason text
)
returns setof public.claim_relations
language plpgsql
security definer
set search_path = ''
as $$
declare
    actor uuid;
    selected_relation public.claim_relations;
    before_state jsonb;
    source_document_id uuid;
begin
    actor := auth.uid();
    if actor is null then
        raise exception 'Authentication is required'
            using errcode = '42501';
    end if;
    if p_action not in (
        'confirm',
        'confirm_equivalent',
        'confirm_update',
        'confirm_conflict',
        'confirm_conditional_variant',
        'dismiss'
    ) then
        raise exception 'Unsupported structured relation action'
            using errcode = '22023';
    end if;
    if p_reason is null
       or char_length(btrim(p_reason)) not between 1 and 2000 then
        raise exception 'Invalid resolution reason'
            using errcode = '22023';
    end if;

    select relations.*
    into selected_relation
    from public.claim_relations as relations
    where relations.id = p_relation_id
      and relations.notebook_id = p_notebook_id
      and relations.owner_id = actor
    for update;

    if not found then
        raise exception 'Structured claim relation was not found'
            using errcode = 'P0002';
    end if;
    if p_expected_updated_at is null
       or selected_relation.updated_at <> p_expected_updated_at then
        raise exception 'Structured claim relation changed before resolution'
            using errcode = '40001';
    end if;

    before_state := to_jsonb(selected_relation);

    update public.claim_relations
    set
        relation_type = case p_action
            when 'confirm_equivalent' then 'equivalent'
            when 'confirm_update' then 'source_updates_target'
            when 'confirm_conflict' then 'conflict'
            when 'confirm_conditional_variant' then 'conditional_variant'
            else claim_relations.relation_type
        end,
        review_status = case
            when p_action = 'dismiss' then 'dismissed'
            else 'confirmed'
        end,
        reason = btrim(p_reason),
        resolved_by = actor,
        resolved_at = now(),
        updated_at = now()
    where claim_relations.id = selected_relation.id
    returning * into selected_relation;

    select snapshots.document_id
    into source_document_id
    from public.table_snapshots as snapshots
    where snapshots.id = selected_relation.source_snapshot_id
      and snapshots.notebook_id = p_notebook_id
      and snapshots.owner_id = actor;

    insert into public.structured_claim_audit (
        owner_id,
        notebook_id,
        document_id,
        relation_id,
        actor_id,
        action,
        reason,
        before_state,
        after_state
    )
    values (
        actor,
        p_notebook_id,
        source_document_id,
        selected_relation.id,
        actor,
        p_action,
        btrim(p_reason),
        before_state,
        to_jsonb(selected_relation)
    );

    return next selected_relation;
end;
$$;

revoke all on function public.resolve_structured_claim_relation(
    uuid, uuid, text, timestamptz, text
) from public, anon;
grant execute on function public.resolve_structured_claim_relation(
    uuid, uuid, text, timestamptz, text
) to authenticated;

-- Exact structured lookup runs before vector retrieval. Time-qualified queries
-- fail closed for claims without an effective start, and only citable claims
-- backed by a live document chunk are returned.
create function public.search_structured_claims(
    p_notebook_id uuid,
    p_document_ids uuid[],
    p_predicate text,
    p_subject_query text,
    p_valid_from timestamptz default null,
    p_valid_to timestamptz default null,
    p_limit integer default 20,
    p_qualifiers jsonb default '{}'::jsonb
)
returns table (
    claim_id uuid,
    document_id uuid,
    document_version integer,
    snapshot_id uuid,
    source_chunk_id uuid,
    candidate_identity_hash text,
    subject_key text,
    subject_identity jsonb,
    predicate text,
    normalized_value jsonb,
    qualifiers jsonb,
    temporal jsonb,
    publication_time timestamptz,
    effective_from timestamptz,
    effective_to timestamptz,
    observed_at timestamptz,
    provenance jsonb,
    source_cells jsonb,
    authority_metadata jsonb,
    confidence double precision,
    source_text text,
    relation_warnings jsonb
)
language plpgsql
stable
security definer
set search_path = ''
as $$
declare
    actor uuid;
    selected_owner_id uuid;
    normalized_predicate text;
    normalized_subject_query text;
    normalized_qualifiers jsonb;
    query_start timestamptz;
    query_end timestamptz;
begin
    actor := auth.uid();
    select notebooks.owner_id
    into selected_owner_id
    from public.notebooks
    where notebooks.id = p_notebook_id;

    if not found then
        raise exception 'Notebook was not found'
            using errcode = 'P0002';
    end if;
    if auth.role() <> 'service_role'
       and actor is distinct from selected_owner_id then
        raise exception 'Cannot search another owner''s structured claims'
            using errcode = '42501';
    end if;

    normalized_predicate := nullif(btrim(p_predicate), '');
    normalized_subject_query := nullif(btrim(p_subject_query), '');
    if normalized_predicate is null or normalized_subject_query is null then
        raise exception 'Predicate and subject query are required'
            using errcode = '22023';
    end if;
    if p_limit is null or p_limit < 1 then
        raise exception 'Search limit must be positive'
            using errcode = '22023';
    end if;
    normalized_qualifiers := coalesce(p_qualifiers, '{}'::jsonb);
    if jsonb_typeof(normalized_qualifiers) <> 'object' then
        raise exception 'Qualifier filters must be an object'
            using errcode = '22023';
    end if;
    if exists (
        select 1
        from jsonb_object_keys(normalized_qualifiers) as qualifier_group(name)
        where qualifier_group.name not in ('stable', 'optional')
    ) then
        raise exception 'Unsupported qualifier filter group'
            using errcode = '22023';
    end if;
    if (
        normalized_qualifiers ? 'stable'
        and jsonb_typeof(normalized_qualifiers -> 'stable') <> 'object'
    ) or (
        normalized_qualifiers ? 'optional'
        and jsonb_typeof(normalized_qualifiers -> 'optional') <> 'object'
    ) then
        raise exception 'Qualifier filter groups must be objects'
            using errcode = '22023';
    end if;
    if p_valid_from is not null
       and p_valid_to is not null
       and p_valid_to < p_valid_from then
        raise exception 'Search validity interval is reversed'
            using errcode = '22023';
    end if;

    query_start := coalesce(p_valid_from, p_valid_to);
    query_end := coalesce(p_valid_to, p_valid_from);

    return query
    select
        claims.id,
        claims.document_id,
        documents.version_number,
        claims.snapshot_id,
        claims.source_chunk_id,
        claims.candidate_identity_hash,
        claims.row_identity,
        claims.subject_identity,
        claims.predicate,
        claims.normalized_value,
        claims.qualifiers,
        jsonb_build_object(
            'publication_time', claims.publication_time,
            'effective_from', claims.effective_from,
            'effective_to', claims.effective_to,
            'observed_at', claims.observed_at,
            'ingested_at', claims.ingested_at
        ),
        claims.publication_time,
        claims.effective_from,
        claims.effective_to,
        claims.observed_at,
        claims.provenance,
        claims.source_cells,
        case
            when jsonb_typeof(claims.authority_metadata -> 'metadata') = 'object'
            then claims.authority_metadata
            else jsonb_strip_nulls(jsonb_build_object(
                'source_type', claims.source_type,
                'publisher', claims.source_publisher,
                'approval_status', claims.authority_metadata -> 'approval_status',
                'officiality', claims.authority_metadata -> 'officiality',
                'authority_level', claims.authority_level,
                'metadata', claims.authority_metadata
                    - array['approval_status', 'officiality']::text[]
            ))
        end,
        claims.confidence,
        coalesce(claims.source_text, claims.normalized_value ->> 'raw_value', ''),
        coalesce(warnings.items, '[]'::jsonb)
    from public.structured_claims as claims
    join public.documents as documents
      on documents.id = claims.document_id
     and documents.notebook_id = claims.notebook_id
     and documents.owner_id = claims.owner_id
    left join lateral (
        select jsonb_agg(
            jsonb_build_object(
                'relation_id', relations.id,
                'relation_type', relations.relation_type,
                'review_status', relations.review_status,
                'confidence', relations.confidence,
                'reason', relations.reason
            )
            order by relations.confidence desc, relations.id
        ) as items
        from public.claim_relations as relations
        where relations.owner_id = claims.owner_id
          and relations.notebook_id = claims.notebook_id
          and (
              relations.source_claim_id = claims.id
              or relations.target_claim_id = claims.id
          )
          and relations.relation_type in (
              'conflict_candidate',
              'conflict',
              'uncertain'
          )
          and relations.review_status <> 'dismissed'
    ) as warnings on true
    where claims.owner_id = selected_owner_id
      and claims.notebook_id = p_notebook_id
      and claims.source_chunk_id is not null
      and claims.predicate = normalized_predicate
      and claims.qualifiers @> normalized_qualifiers
      and (
          p_document_ids is null
          or claims.document_id = any(p_document_ids)
      )
      and (
          claims.candidate_identity_hash = lower(normalized_subject_query)
          or lower(claims.row_identity) = lower(normalized_subject_query)
          or exists (
              select 1
              from pg_catalog.unnest(
                  pg_catalog.string_to_array(lower(claims.row_identity), '|')
              ) as subject_segment(value)
              where pg_catalog.split_part(subject_segment.value, '=', 2)
                  = lower(normalized_subject_query)
          )
      )
      and (
          query_start is null
          or (
              claims.effective_from is not null
              and claims.effective_from <= query_end
              and coalesce(
                  claims.effective_to,
                  'infinity'::timestamptz
              ) >= query_start
          )
      )
    order by
        (
            claims.candidate_identity_hash
                = lower(normalized_subject_query)
        ) desc,
        claims.confidence desc,
        claims.effective_from desc nulls last,
        claims.id
    limit least(p_limit, 200);
end;
$$;

revoke all on function public.search_structured_claims(
    uuid, uuid[], text, text, timestamptz, timestamptz, integer, jsonb
) from public, anon;
grant execute on function public.search_structured_claims(
    uuid, uuid[], text, text, timestamptz, timestamptz, integer, jsonb
) to authenticated, service_role;

-- Worker-only indexed candidate loading for deterministic O(n+m) table diff.
-- The nested claim JSON matches the application StructuredClaim payload.
create function public.load_structured_claim_candidates(
    p_notebook_id uuid,
    p_document_id uuid,
    p_candidate_hashes text[],
    p_limit integer default 10000,
    p_schema_fingerprints text[] default '{}'::text[]
)
returns table (
    claim_id uuid,
    snapshot_id uuid,
    document_id uuid,
    document_version integer,
    snapshot_key text,
    schema_fingerprint text,
    template_fingerprint text,
    normalized_schema jsonb,
    candidate_identity_hash text,
    claim jsonb
)
language plpgsql
stable
security definer
set search_path = ''
as $$
declare
    selected_document public.documents;
    normalized_hashes text[];
    normalized_schema_hashes text[];
    matched_snapshot_ids uuid[];
    candidate_claim_count integer;
begin
    if auth.role() <> 'service_role' then
        raise exception 'Service role is required'
            using errcode = '42501';
    end if;
    if p_limit is null or p_limit < 1 or p_limit > 10000 then
        raise exception 'Candidate limit must be between 1 and 10000'
            using errcode = '22023';
    end if;
    if p_candidate_hashes is null
       or (
           pg_catalog.cardinality(p_candidate_hashes) = 0
           and pg_catalog.cardinality(p_schema_fingerprints) = 0
       )
       or exists (
            select 1
            from unnest(p_candidate_hashes) as candidate_hash(value)
            where candidate_hash.value is null
               or btrim(candidate_hash.value) !~ '^[0-9a-fA-F]{64}$'
       ) then
        raise exception 'Candidate hashes must be non-empty SHA-256 values'
            using errcode = '22023';
    end if;
    if p_schema_fingerprints is null
       or exists (
            select 1
            from unnest(p_schema_fingerprints) as schema_hash(value)
            where schema_hash.value is null
               or btrim(schema_hash.value) !~ '^[0-9a-fA-F]{64}$'
       ) then
        raise exception 'Schema fingerprints must be SHA-256 values'
            using errcode = '22023';
    end if;

    normalized_hashes := array(
        select lower(btrim(candidate_hash.value))
        from unnest(p_candidate_hashes) as candidate_hash(value)
    );
    normalized_schema_hashes := array(
        select lower(btrim(schema_hash.value))
        from unnest(p_schema_fingerprints) as schema_hash(value)
    );

    select documents.*
    into selected_document
    from public.documents
    where documents.id = p_document_id
      and documents.notebook_id = p_notebook_id
      and documents.status = 'ready'
      and documents.canonical_document_id is null;

    if not found then
        raise exception 'Ready canonical source document was not found'
            using errcode = 'P0002';
    end if;

    select pg_catalog.array_agg(matched.id order by matched.id)
    into matched_snapshot_ids
    from (
        select distinct snapshots.id
        from public.table_snapshots as snapshots
        join public.documents as documents
          on documents.id = snapshots.document_id
         and documents.notebook_id = snapshots.notebook_id
         and documents.owner_id = snapshots.owner_id
        where snapshots.owner_id = selected_document.owner_id
          and snapshots.notebook_id = selected_document.notebook_id
          and snapshots.document_id <> selected_document.id
          and documents.status = 'ready'
          and documents.is_active
          and documents.is_current
          and documents.canonical_document_id is null
          and (
              snapshots.schema_fingerprint
                    = any(normalized_schema_hashes)
              or exists (
                  select 1
                  from public.structured_claims as seed_claims
                  where seed_claims.snapshot_id = snapshots.id
                    and seed_claims.notebook_id = snapshots.notebook_id
                    and seed_claims.owner_id = snapshots.owner_id
                    and seed_claims.candidate_identity_hash
                        = any(normalized_hashes)
              )
          )
    ) as matched;

    select count(*)::integer
    into candidate_claim_count
    from public.structured_claims as claims
    where claims.owner_id = selected_document.owner_id
      and claims.notebook_id = selected_document.notebook_id
      and claims.snapshot_id = any(matched_snapshot_ids);

    if candidate_claim_count > p_limit then
        raise exception 'Structured candidate set exceeds safe claim limit'
            using errcode = '54000',
                  detail = jsonb_build_object(
                      'candidate_claim_count', candidate_claim_count,
                      'limit', p_limit
                  )::text;
    end if;

    return query
    select
        claims.id,
        claims.snapshot_id,
        claims.document_id,
        documents.version_number,
        snapshots.snapshot_key,
        snapshots.schema_fingerprint,
        snapshots.template_fingerprint,
        snapshots.normalized_schema,
        claims.candidate_identity_hash,
        jsonb_build_object(
            'id', claims.claim_key,
            'owner_id', claims.owner_id,
            'notebook_id', claims.notebook_id,
            'document_id', claims.document_id,
            'subject_key', claims.row_identity,
            'predicate', claims.predicate,
            'value', claims.normalized_value,
            'scope', claims.subject_identity - 'subject_key',
            'qualifiers', claims.qualifiers,
            'temporal', jsonb_build_object(
                'publication_time', claims.publication_time,
                'effective_from', claims.effective_from,
                'effective_to', claims.effective_to,
                'observed_at', claims.observed_at,
                'ingested_at', claims.ingested_at
            ),
            'provenance', claims.provenance,
            'extraction_confidence', claims.confidence,
            'extractor_version', claims.extractor_version,
            'derivation', case
                when claims.is_derived then claims.derivation
                else null
            end,
            'authority', case
                when jsonb_typeof(claims.authority_metadata -> 'metadata')
                    = 'object'
                then claims.authority_metadata
                else jsonb_build_object(
                    'source_type', claims.source_type,
                    'publisher', claims.source_publisher,
                    'approval_status', claims.authority_metadata -> 'approval_status',
                    'officiality', claims.authority_metadata -> 'officiality',
                    'authority_level', claims.authority_level,
                    'metadata', claims.authority_metadata
                        - array['approval_status', 'officiality']::text[]
                )
            end,
            'candidate_identity_hash', claims.candidate_identity_hash,
            'claim_identity_hash', claims.claim_key
        )
    from public.structured_claims as claims
    join public.table_snapshots as snapshots
      on snapshots.id = claims.snapshot_id
     and snapshots.document_id = claims.document_id
     and snapshots.notebook_id = claims.notebook_id
     and snapshots.owner_id = claims.owner_id
    join public.documents as documents
      on documents.id = claims.document_id
     and documents.notebook_id = claims.notebook_id
     and documents.owner_id = claims.owner_id
    where claims.owner_id = selected_document.owner_id
      and claims.notebook_id = selected_document.notebook_id
      and claims.document_id <> selected_document.id
      and claims.snapshot_id = any(matched_snapshot_ids)
      and documents.status = 'ready'
      and documents.is_active
      and documents.is_current
      and documents.canonical_document_id is null
    order by
        claims.candidate_identity_hash,
        documents.updated_at desc,
        snapshots.snapshot_key,
        claims.confidence desc,
        claims.id;
end;
$$;

revoke all on function public.load_structured_claim_candidates(
    uuid, uuid, text[], integer, text[]
) from public, anon, authenticated;
grant execute on function public.load_structured_claim_candidates(
    uuid, uuid, text[], integer, text[]
) to service_role;
