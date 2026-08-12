"""Contracts for canonical Enterprise duplicate/conflict persistence."""

from pathlib import Path

SQL = Path("supabase/migrations/35_enterprise_knowledge_quality.sql").read_text(
    encoding="utf-8"
).lower()


def test_simhash_helper_is_defined_before_enterprise_generated_column() -> None:
    helper = "create or replace function public.knowledge_simhash_multi_keys"
    generated_column = "add column if not exists candidate_binary_keys text[]"

    assert helper in SQL
    assert generated_column in SQL
    assert SQL.index(helper) < SQL.index(generated_column)
    assert "immutable" in SQL[SQL.index(helper) : SQL.index(generated_column)]


def test_enterprise_quality_rpcs_and_relation_store_are_present() -> None:
    assert "create table if not exists public.knowledge_document_relations" in SQL
    assert "create or replace function public.find_enterprise_content_duplicate" in SQL
    assert "create or replace function public.find_enterprise_chunk_candidates_v2" in SQL
    assert "create or replace function public.complete_processing_job_v4" in SQL


def test_completion_lease_lookup_uses_scalar_into_targets() -> None:
    body = SQL.split(
        "create or replace function public.complete_processing_job_v4", maxsplit=1
    )[1].split("$$;", maxsplit=1)[0]

    assert "selected_requested_by uuid" in body
    assert "selected_version_id uuid" in body
    assert "selected_document_id uuid" in body
    assert (
        "into selected_requested_by, selected_version_id, selected_document_id" in body
    )
    assert "into selected_job, selected_version, selected_document" not in body
