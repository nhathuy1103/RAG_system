from __future__ import annotations

from pathlib import Path

MIGRATION = Path(
    "supabase/migrations/30_auto_publish_processed_documents.sql"
).read_text(encoding="utf-8")


def test_auto_publish_runs_after_atomic_projection_completion() -> None:
    assert "create or replace function public.complete_processing_job_v3" in MIGRATION
    completion = MIGRATION.index("public.complete_processing_job_v2(")
    publication = MIGRATION.index("public.approve_and_publish_document_version(")
    assert completion < publication
    assert "completed_job.status <> 'SUCCEEDED'" in MIGRATION
    assert "selected_version.status <> 'READY_FOR_REVIEW'" in MIGRATION
    assert "selected_document.status = 'ARCHIVED'" in MIGRATION


def test_auto_publish_preserves_actor_permissions_and_audit_path() -> None:
    assert "if auth.role() <> 'service_role'" in MIGRATION
    assert "publication_actor := selected_job.requested_by" in MIGRATION
    assert "publication_actor, 'REVIEW_DOCUMENT'" in MIGRATION
    assert "publication_actor, 'PUBLISH_DOCUMENT'" in MIGRATION
    assert "selected_document.id, 'REVIEW'" in MIGRATION
    assert "selected_document.id, 'PUBLISH'" in MIGRATION
    assert "'request.jwt.claim.sub', publication_actor::text" in MIGRATION
    assert "to service_role" in MIGRATION
    assert "from public, anon, authenticated" in MIGRATION
