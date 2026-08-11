"""Contracts for the final Enterprise workflow migration and reset artifact."""

from pathlib import Path

MIGRATION_DIR = Path("supabase/migrations")
WORKFLOW = (
    (MIGRATION_DIR / "23_enterprise_workflow_completion.sql").read_text(encoding="utf-8").lower()
)
RESET = (MIGRATION_DIR / "RESET_AND_REBUILD.sql").read_text(encoding="utf-8")


def _function_body(name: str) -> str:
    marker = f"create or replace function public.{name}"
    return WORKFLOW.split(marker, maxsplit=1)[1].split("$$;", maxsplit=1)[0]


def test_initial_upload_is_one_database_transaction_with_duplicate_protection() -> None:
    body = _function_body("create_enterprise_document_upload")
    assert "has_functional_permission(actor, 'upload_document')" in body
    assert "pg_advisory_xact_lock" in body
    assert "an identical source is already registered" in body
    assert "registered_documents.status <> 'archived'" in body
    for table in (
        "source_files",
        "knowledge_documents",
        "document_permissions",
        "document_versions",
        "processing_jobs",
    ):
        assert f"insert into public.{table}" in body
    assert "'initial_process'" in body
    assert "write_enterprise_audit" in body
    assert "to authenticated" in WORKFLOW


def test_governance_permissions_are_separated_by_capability() -> None:
    assert "'view_analytics'" in WORKFLOW
    assert "'manage_report'" in WORKFLOW
    analytics = _function_body("enterprise_analytics_summary")
    assert "has_functional_permission(actor, 'view_analytics')" in analytics
    report_policy = WORKFLOW.split("create policy answer_reports_update_governance", maxsplit=1)[
        1
    ].split(";", maxsplit=1)[0]
    assert "manage_report" in report_policy
    assert "view_audit" not in report_policy


def test_access_explanation_requires_both_functional_and_resource_management() -> None:
    body = _function_body("explain_document_access")
    assert "has_functional_permission(actor, 'manage_access_policy')" in body
    assert "has_document_permission(actor, p_document_id, 'manage_permission')" in body
    for source_type in ("roles.code", "groups.code", "departments.code"):
        assert source_type in body
    assert "enterprise_subject_ids_for_user(p_user_id)" in body


def test_corporate_email_domain_guard_is_configurable_and_fail_closed_when_configured() -> None:
    assert "create table if not exists public.enterprise_allowed_email_domains" in WORKFLOW
    body = _function_body("enforce_enterprise_email_domain")
    assert "where status = 'active'" in body
    assert "email domain is not permitted" in body
    assert "before insert or update of email on auth.users" in WORKFLOW


def test_review_context_is_candidate_scoped_and_never_exposes_internal_errors() -> None:
    body = _function_body("get_document_version_review_context")
    assert "has_functional_permission(actor, 'review_document')" in body
    assert "has_document_permission(actor, selected_document.id, 'review')" in body
    assert "from public.knowledge_chunks as chunks" in body
    assert "chunks.document_version_id = p_version_id" in body
    assert "safe_message" in body
    assert "internal_reference" not in body


def test_document_metadata_updates_require_an_optimistic_concurrency_token() -> None:
    body = _function_body("update_knowledge_document")
    assert "not p_changes ? 'expected_updated_at'" in body
    assert "for update" in body
    assert "selected_document.updated_at is distinct from expected_updated_at" in body
    assert "reload before saving" in body


def test_reset_contains_every_canonical_migration_verbatim_in_order() -> None:
    canonical = "\n\n".join(
        path.read_text(encoding="utf-8").rstrip()
        for path in sorted(MIGRATION_DIR.glob("[0-9][0-9]_*.sql"))
    )
    marker = "-- Extensions required by the schema."
    reset_canonical = RESET[RESET.index(marker) :].rstrip()
    assert reset_canonical == canonical
