"""Security/lifecycle contracts for Enterprise database operations."""

from pathlib import Path


def _normalized(path: str) -> str:
    return " ".join(Path(path).read_text(encoding="utf-8").lower().split())


OPERATIONS = _normalized("supabase/migrations/20_enterprise_operations.sql")
IAM = _normalized("supabase/migrations/17_enterprise_iam.sql")
SECURITY = _normalized("supabase/migrations/21_enterprise_security_retrieval.sql")
BRIDGE = _normalized("supabase/migrations/22_enterprise_answer_ingestion_bridge.sql")


def test_live_membership_graph_drives_effective_access() -> None:
    assert "create or replace function public.enterprise_subject_ids_for_user" in OPERATIONS
    assert "with recursive active_departments" in OPERATIONS
    assert "create or replace function public.has_document_permission" in OPERATIONS
    assert "document_permissions.status = 'active'" in OPERATIONS
    assert "select public.enterprise_subject_ids_for_user(p_user_id)" in OPERATIONS
    assert "create or replace function public.test_document_access" in OPERATIONS
    assert "manage_access_policy" in OPERATIONS


def test_lifecycle_mutations_are_security_definer_and_audited() -> None:
    rpc_names = (
        "create_knowledge_document",
        "create_document_version",
        "review_document_version",
        "publish_document_version",
        "archive_knowledge_document",
        "grant_document_permission",
        "revoke_document_permission",
        "retry_processing_job",
    )
    for name in rpc_names:
        marker = f"create or replace function public.{name}"
        assert marker in OPERATIONS
        body = OPERATIONS.split(marker, maxsplit=1)[1].split("$$;", maxsplit=1)[0]
        assert "security definer" in body
        assert "set search_path = ''" in body
        assert "auth.uid()" in body

    assert OPERATIONS.count("write_enterprise_audit(") >= 7


def test_direct_postgrest_mutations_are_audited_and_rpc_tables_are_read_only() -> None:
    assert "create or replace function public.audit_enterprise_table_change" in OPERATIONS
    for table in (
        "roles",
        "role_permissions",
        "user_roles",
        "groups",
        "user_groups",
        "departments",
        "user_departments",
        "source_files",
        "answer_feedback",
        "answer_reports",
    ):
        assert f"'{table}'" in OPERATIONS
    assert "grant select on table public.user_profiles to authenticated" in SECURITY
    assert "on public.knowledge_documents to authenticated" not in SECURITY


def test_upload_permission_cannot_mutate_logical_documents_or_versions() -> None:
    for name in ("create_knowledge_document", "create_document_version"):
        body = OPERATIONS.split(
            f"create or replace function public.{name}", maxsplit=1
        )[1].split("$$;", maxsplit=1)[0]
        assert "has_functional_permission(actor, 'manage_document')" in body
        assert "upload_document" not in body


def test_publish_is_one_atomic_database_operation() -> None:
    publish = OPERATIONS.split(
        "create or replace function public.publish_document_version", maxsplit=1
    )[1].split("$$;", maxsplit=1)[0]
    assert "for update" in publish
    assert "decision = 'approve'" in publish
    assert "set status = 'superseded'" in publish
    assert "set status = 'active'" in publish
    assert "set status = 'published', current_version_id = p_version_id" in publish
    assert "insert into public.publications" in publish
    assert "write_enterprise_audit" in publish


def test_publish_uses_only_a_fresh_latest_approval() -> None:
    publish = OPERATIONS.split(
        "create or replace function public.publish_document_version", maxsplit=1
    )[1].split("$$;", maxsplit=1)[0]
    assert "order by latest_review.reviewed_at desc, latest_review.id desc" in publish
    assert "reviews.id = (" in publish
    assert "select max(jobs.completed_at)" in publish
    assert "jobs.status = 'succeeded'" in publish
    assert "reviews.reviewed_at >= (" in publish


def test_archived_documents_reject_review_and_retry_and_archive_audits_truthfully() -> None:
    review = OPERATIONS.split(
        "create or replace function public.review_document_version", maxsplit=1
    )[1].split("$$;", maxsplit=1)[0]
    retry = OPERATIONS.split(
        "create or replace function public.retry_processing_job", maxsplit=1
    )[1].split("$$;", maxsplit=1)[0]
    archive = OPERATIONS.split(
        "create or replace function public.archive_knowledge_document", maxsplit=1
    )[1].split("$$;", maxsplit=1)[0]
    assert "selected_document.status = 'archived'" in review
    assert "archived documents cannot be reviewed" in review
    assert "has_functional_permission(actor, 'manage_document')" in retry
    assert "selected_document.status = 'archived'" in retry
    assert "archived documents cannot be reprocessed" in retry
    assert "previous_document_status := selected_document.status" in archive
    assert "jsonb_build_object('status', previous_document_status)" in archive


def test_version_creation_rejects_identical_content_globally_and_serializes_hash() -> None:
    version = OPERATIONS.split(
        "create or replace function public.create_document_version", maxsplit=1
    )[1].split("$$;", maxsplit=1)[0]
    assert "selected_source.sha256 is not null" in version
    assert "pg_advisory_xact_lock" in version
    assert "existing_sources.sha256 = selected_source.sha256" in version
    assert "versions.document_id = p_document_id" not in version
    assert "identical source file is already registered" in version


def test_secure_retrieval_requires_all_three_invariants_before_ranking() -> None:
    for name in (
        "match_enterprise_document_chunks",
        "search_enterprise_document_chunks_keyword",
    ):
        marker = f"create or replace function public.{name}"
        body = SECURITY.split(marker, maxsplit=1)[1].split("$$;", maxsplit=1)[0]
        assert "documents.status = 'published'" in body
        assert "versions.status = 'active'" in body
        assert "documents.current_version_id = versions.id" in body
        assert "has_document_permission(actor, documents.id, 'read')" in body
        assert "not public.has_functional_permission(actor, 'ask_knowledge')" in body
        assert "auth.uid()" in body
        assert "p_document_ids" not in body
        assert "least(coalesce(p_limit, 20), 200)" in body

    dense = SECURITY.split(
        "create or replace function public.match_enterprise_document_chunks", maxsplit=1
    )[1].split("$$;", maxsplit=1)[0]
    assert "if p_query_embedding is null" in dense
    assert "query embedding is required" in dense


def test_retrieval_rpcs_are_not_executable_by_anonymous_users() -> None:
    for signature in (
        "public.match_enterprise_document_chunks( vector, integer, jsonb )",
        "public.search_enterprise_document_chunks_keyword( text, integer, jsonb )",
        "public.search_enterprise_knowledge( text, integer, jsonb )",
    ):
        assert f"revoke all on function {signature} from public, anon" in SECURITY
        assert f"grant execute on function {signature} to authenticated" in SECURITY


def test_sensitive_enterprise_tables_enable_and_force_rls() -> None:
    for table in (
        "user_profiles",
        "knowledge_documents",
        "source_files",
        "document_versions",
        "document_permissions",
        "processing_jobs",
        "enterprise_conversations",
        "enterprise_messages",
        "enterprise_citations",
        "answer_feedback",
        "answer_reports",
        "audit_logs",
    ):
        assert f"alter table public.{table} enable row level security" in SECURITY
        assert f"alter table public.{table} force row level security" in SECURITY
    assert "from anon, authenticated" in SECURITY
    assert "audit_logs_select_governance" in SECURITY


def test_read_does_not_expose_drafts_old_versions_or_internal_review_history() -> None:
    document_policy = SECURITY.split(
        "create policy knowledge_documents_select_access", maxsplit=1
    )[1].split(";", maxsplit=1)[0]
    assert "status = 'published'" in document_policy
    assert "current_version_id is not null" in document_policy

    version_policy = SECURITY.split(
        "create policy document_versions_select_access", maxsplit=1
    )[1].split(";", maxsplit=1)[0]
    assert "status = 'active'" in version_policy
    assert "documents.current_version_id = document_versions.id" in version_policy

    for policy_name in (
        "document_version_status_history_select_access",
        "document_reviews_select_access",
    ):
        policy = SECURITY.split(f"create policy {policy_name}", maxsplit=1)[1].split(
            ";", maxsplit=1
        )[0]
        assert "'read'" not in policy


def test_source_download_and_conversation_rpc_contracts_exist() -> None:
    assert "create or replace function public.get_document_version_source" in OPERATIONS
    source = OPERATIONS.split(
        "create or replace function public.get_document_version_source", maxsplit=1
    )[1].split("$$;", maxsplit=1)[0]
    assert "has_document_permission(actor, p_document_id, 'read')" in source
    assert "selected_document.status = 'published'" in source
    assert "selected_version.status = 'active'" in source
    for rpc in (
        "create_enterprise_conversation",
        "get_enterprise_conversation",
        "append_enterprise_message",
        "enterprise_analytics_summary",
    ):
        assert f"create or replace function public.{rpc}" in OPERATIONS


def test_answer_and_citations_are_atomic_and_reauthorized_at_commit() -> None:
    marker = "create or replace function public.complete_enterprise_answer"
    assert marker in BRIDGE
    body = BRIDGE.split(marker, maxsplit=1)[1].split("$$;", maxsplit=1)[0]
    assert "security definer" in body
    assert "is_enterprise_document_retrievable" in body
    assert "chunks.content = item.value ->> 'quote_text'" in body
    assert "insert into public.enterprise_messages" in body
    assert "insert into public.enterprise_citations" in body
    assert body.index("insert into public.enterprise_messages") < body.index(
        "insert into public.enterprise_citations"
    )
    assert "citation order and chunks must be unique and contiguous" in body


def test_clients_cannot_forge_assistant_messages() -> None:
    marker = "create or replace function public.append_enterprise_message"
    body = BRIDGE.split(marker, maxsplit=1)[1].split("$$;", maxsplit=1)[0]
    assert "normalized_role <> 'user'" in body
    assert "only user messages may be appended by a client" in body


def test_direct_enterprise_jobs_have_a_service_role_claim_bridge() -> None:
    marker = "create or replace function public.claim_enterprise_ingestion_job"
    body = BRIDGE.split(marker, maxsplit=1)[1].split("$$;", maxsplit=1)[0]
    assert "auth.role() <> 'service_role'" in body
    assert "legacy_ingestion_job_id is null" in body
    assert "for update skip locked" in body
    assert "document_version_id uuid" in BRIDGE
    assert "knowledge_document_id uuid" in BRIDGE


def test_enterprise_source_bucket_separates_upload_from_authorized_download() -> None:
    assert "'knowledge-source-files'" in BRIDGE
    assert "enterprise_source_storage_insert" in BRIDGE
    assert "enterprise_source_storage_select" in BRIDGE
    assert "enterprise_source_storage_delete" in BRIDGE
    assert "create or replace function public.can_download_enterprise_source" in BRIDGE
    assert "has_document_permission( p_user_id, documents.id, 'download' )" in BRIDGE
    source_rpc = BRIDGE.split(
        "create or replace function public.get_document_version_source", maxsplit=1
    )[1].split("$$;", maxsplit=1)[0]
    assert "selected_version.status = 'active'" in source_rpc
    assert "selected_document.current_version_id = p_version_id" in source_rpc
    assert "has_document_permission(actor, p_document_id, 'download')" in source_rpc
    storage_select = BRIDGE.split(
        "create policy enterprise_source_storage_select", maxsplit=1
    )[1].split(";", maxsplit=1)[0]
    assert "is_enterprise_storage_object_referenced" in storage_select
    storage_delete = BRIDGE.split(
        "create policy enterprise_source_storage_delete", maxsplit=1
    )[1].split(";", maxsplit=1)[0]
    assert "is_enterprise_storage_object_registered" in storage_delete
    assert "'upload_document'" in storage_delete
    assert "'manage_document'" in storage_delete
    registered = SECURITY.split(
        "create or replace function public.is_enterprise_storage_object_registered",
        maxsplit=1,
    )[1].split("$$;", maxsplit=1)[0]
    assert "from public.source_files as files" in registered
    assert "join public.document_versions" not in registered


def test_processing_visibility_requires_functional_and_resource_permission() -> None:
    for policy_name in (
        "processing_jobs_select_access",
        "processing_stage_history_select_access",
        "processing_errors_select_access",
    ):
        policy = SECURITY.split(f"create policy {policy_name}", maxsplit=1)[1].split(
            ";", maxsplit=1
        )[0]
        assert "has_functional_permission((select auth.uid()), 'manage_document')" in policy
        assert "has_document_permission(" in policy
        assert "'manage'" in policy


def test_feedback_reports_and_history_fail_closed_for_inactive_consumers() -> None:
    for policy_name in (
        "answer_feedback_select_own_or_governance",
        "answer_feedback_insert_own",
        "answer_feedback_update_own",
        "answer_reports_select_own_or_governance",
        "answer_reports_insert_own",
    ):
        policy = SECURITY.split(f"create policy {policy_name}", maxsplit=1)[1].split(
            ";", maxsplit=1
        )[0]
        assert "has_functional_permission((select auth.uid()), 'ask_knowledge')" in policy
        assert "is_enterprise_message_visible((select auth.uid()), message_id)" in policy

    conversation = BRIDGE.split(
        "create or replace function public.get_enterprise_conversation", maxsplit=1
    )[1].split("$$;", maxsplit=1)[0]
    assert "not public.has_functional_permission(actor, 'ask_knowledge')" in conversation


def test_iam_roots_are_disable_only_and_recovery_guards_are_database_enforced() -> None:
    root_grant = SECURITY.split(
        "root iam entities have lifecycle status", maxsplit=1
    )[1].split("grant select, insert, update on table", maxsplit=1)[1].split(
        "to authenticated;", maxsplit=1
    )[0]
    for root in ("public.roles", "public.groups", "public.departments"):
        assert root in root_grant
    assert "delete" not in root_grant
    assert "guard_enterprise_department_cycle" in IAM
    assert "with recursive ancestors" in IAM
    assert "pg_advisory_xact_lock" in IAM
    assert "prevent_enterprise_iam_root_delete" in IAM
    assert "protect_enterprise_system_role" in IAM
    assert "protect_enterprise_admin_permissions" in IAM
    assert "protect_last_enterprise_admin_assignment" in IAM
    assert "protect_last_enterprise_admin_profile" in IAM


def test_legacy_profile_cosmetic_updates_cannot_restore_removed_roles() -> None:
    sync = IAM.split(
        "create or replace function public.sync_legacy_profile_to_enterprise", maxsplit=1
    )[1].split("$$;", maxsplit=1)[0]
    role_guard = "if tg_op = 'insert' or old.role is distinct from new.role then"
    assert role_guard in sync
    assert sync.index(role_guard) < sync.index("insert into public.user_roles")


def test_reviewers_and_publishers_can_inspect_candidate_sources() -> None:
    source_policy = SECURITY.split(
        "create policy source_files_select_access", maxsplit=1
    )[1].split(";", maxsplit=1)[0]
    source_rpc = BRIDGE.split(
        "create or replace function public.get_document_version_source", maxsplit=1
    )[1].split("$$;", maxsplit=1)[0]
    download_guard = BRIDGE.split(
        "create or replace function public.can_download_enterprise_source", maxsplit=1
    )[1].split("$$;", maxsplit=1)[0]
    for body in (source_policy, source_rpc, download_guard):
        assert "'review'" in body
        assert "'review_document'" in body
        assert "'publish'" in body
        assert "'publish_document'" in body
