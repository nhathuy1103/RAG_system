from __future__ import annotations

from pathlib import Path

SQL = Path("supabase/migrations/28_guided_document_publish.sql").read_text(
    encoding="utf-8"
).lower()


def _function_body(name: str) -> str:
    marker = f"create or replace function public.{name}"
    return SQL.split(marker, maxsplit=1)[1].split("$$;", maxsplit=1)[0]


def test_guided_publish_reuses_review_and_publish_guards_in_one_transaction() -> None:
    body = _function_body("approve_and_publish_document_version")
    assert "public.review_document_version(" in body
    assert "'approve'" in body
    assert "return public.publish_document_version(p_version_id)" in body
    assert "reviews.reviewed_at >=" in body
    assert "jobs.status = 'succeeded'" in body
    assert "set search_path = ''" in body


def test_guided_publish_is_exposed_only_to_authenticated_callers() -> None:
    assert "from public, anon" in SQL
    assert "to authenticated" in SQL
