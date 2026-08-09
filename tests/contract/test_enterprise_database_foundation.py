"""Static contracts for the additive Enterprise knowledge schema.

These checks deliberately point only at migrations 17+ so the expand phase
cannot accidentally require rewriting the stable 01-16 notebook migrations.
"""

from pathlib import Path


def _normalized(path: str) -> str:
    return " ".join(Path(path).read_text(encoding="utf-8").lower().split())


IAM = _normalized("supabase/migrations/17_enterprise_iam.sql")
KNOWLEDGE = _normalized("supabase/migrations/18_enterprise_knowledge_acl.sql")
PROCESSING = _normalized("supabase/migrations/19_enterprise_processing_rag.sql")
OPERATIONS = _normalized("supabase/migrations/20_enterprise_operations.sql")


def test_iam_rbac_and_typed_acl_subjects_have_referential_integrity() -> None:
    for table in (
        "user_profiles",
        "roles",
        "functional_permissions",
        "user_roles",
        "role_permissions",
        "groups",
        "user_groups",
        "departments",
        "user_departments",
        "access_subjects",
    ):
        assert f"create table if not exists public.{table}" in IAM

    assert "unique (user_id, role_id)" in IAM
    assert "unique (role_id, permission_id)" in IAM
    assert "unique (user_id, group_id)" in IAM
    assert "access_subjects_typed_identity" in IAM
    for subject_type in ("user", "role", "group", "department"):
        assert f"subject_type = '{subject_type}'" in IAM
        assert f"access_subjects_{subject_type}_key" in IAM


def test_logical_document_is_separate_from_source_and_version() -> None:
    assert "create table if not exists public.knowledge_documents" in KNOWLEDGE
    assert "create table if not exists public.source_files" in KNOWLEDGE
    assert "create table if not exists public.document_versions" in KNOWLEDGE
    assert "references public.knowledge_documents (id)" in KNOWLEDGE
    assert "references public.source_files (id)" in KNOWLEDGE
    assert "unique (document_id, version_number)" in KNOWLEDGE
    assert "knowledge_documents_current_version_same_document_fk" in KNOWLEDGE
    assert "foreign key (current_version_id, id)" in KNOWLEDGE
    assert "references public.document_versions (id, document_id)" in KNOWLEDGE


def test_database_enforces_one_active_version_and_atomic_publish_history_model() -> None:
    assert "document_versions_one_active_per_document_idx" in KNOWLEDGE
    assert "on public.document_versions (document_id) where status = 'active'" in KNOWLEDGE
    assert "create table if not exists public.document_reviews" in KNOWLEDGE
    assert "create table if not exists public.publications" in KNOWLEDGE
    assert "create table if not exists public.document_version_status_history" in KNOWLEDGE
    assert "document_versions_previous_same_document_fk" in KNOWLEDGE


def test_acl_is_allow_only_with_active_assignment_history() -> None:
    assert "create table if not exists public.document_permissions" in KNOWLEDGE
    assert "status in ('active', 'revoked')" in KNOWLEDGE
    assert "document_permissions_one_active_assignment_idx" in KNOWLEDGE
    assert "where status = 'active'" in KNOWLEDGE
    assert "absence of an active grant means deny" in KNOWLEDGE
    assert "'deny'" not in KNOWLEDGE


def test_backfill_is_fail_closed_and_preserves_legacy_links() -> None:
    assert "legacy_version_group_id" in KNOWLEDGE
    assert "legacy_document_id uuid unique" in KNOWLEDGE
    assert "from public.documents" in KNOWLEDGE
    assert "when ranked_legacy_versions.status = 'ready' then 'ready_for_review'" in KNOWLEDGE
    assert "else 'draft'" in KNOWLEDGE
    # There must be no backfill that silently publishes or activates legacy data.
    backfill = KNOWLEDGE.split("compatibility backfill", maxsplit=1)[1]
    assert "then 'active'" not in backfill
    assert "then 'published'" not in backfill


def test_processing_is_version_scoped_and_reprocess_is_a_new_job() -> None:
    assert "create table if not exists public.processing_jobs" in PROCESSING
    assert "document_version_id uuid not null" in PROCESSING
    assert "job_type in ('initial_process', 'new_version', 'reprocess')" in PROCESSING
    assert "unique (document_version_id, attempt_no)" in PROCESSING
    assert "processing_jobs_one_active_per_version_idx" in PROCESSING
    assert "where status in ('pending', 'running')" in PROCESSING
    assert "create table if not exists public.processing_stage_history" in PROCESSING
    assert "create table if not exists public.processing_errors" in PROCESSING
    assert "safe_message text not null" in PROCESSING
    assert "internal_reference text" in PROCESSING


def test_review_reprocess_creates_a_new_version_scoped_attempt() -> None:
    review_body = OPERATIONS.split(
        "create or replace function public.review_document_version", maxsplit=1
    )[1].split("$$;", maxsplit=1)[0]
    assert "a rejection reason is required" in review_body
    assert "normalized_decision = 'reprocess'" in review_body
    assert "'reprocess', 'pending'" in " ".join(review_body.split())
    assert "previous_job_id" in review_body
    assert "processing_job_reprocessed_from_review" in review_body


def test_chunks_and_citations_are_bound_to_the_exact_version() -> None:
    assert (
        "alter table public.document_chunks "
        "add column if not exists document_version_id uuid"
    ) in PROCESSING
    assert "document_chunks_version_document_fk" in PROCESSING
    assert "document_chunks_version_index_key" in PROCESSING
    assert "on public.document_chunks (document_version_id, chunk_index)" in PROCESSING
    assert (
        "alter table public.message_citations "
        "add column if not exists document_version_id uuid"
    ) in PROCESSING
    assert "message_citations_enterprise_chunk_fk" in PROCESSING
    assert "foreign key (chunk_id, document_version_id, knowledge_document_id)" in PROCESSING


def test_feedback_reports_and_append_only_audit_are_persisted() -> None:
    for table in (
        "enterprise_conversations",
        "enterprise_messages",
        "enterprise_citations",
        "answer_feedback",
        "answer_reports",
        "audit_logs",
    ):
        assert f"create table if not exists public.{table}" in PROCESSING
    assert "audit_logs_immutable" in PROCESSING
    assert "before update or delete on public.audit_logs" in PROCESSING
    assert "audit_logs is append-only" in PROCESSING
