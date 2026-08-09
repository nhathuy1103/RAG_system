"""Security contract for the SECURITY DEFINER dense-retrieval RPC."""

from pathlib import Path

SQL = Path("supabase/migrations/06_pgvector_search.sql").read_text(encoding="utf-8")
NORMALIZED_SQL = " ".join(SQL.lower().split())


def test_dense_rpc_rejects_cross_owner_authenticated_calls() -> None:
    assert "auth.uid() is distinct from p_owner_id" in NORMALIZED_SQL
    assert "auth.role() <> 'service_role'" in NORMALIZED_SQL
    assert "using errcode = '42501'" in NORMALIZED_SQL


def test_dense_rpc_supports_notebook_scope_and_bounded_results() -> None:
    assert "p_notebook_id uuid default null" in NORMALIZED_SQL
    assert "c.notebook_id = p_notebook_id" in NORMALIZED_SQL
    assert "least(p_limit, 200)" in NORMALIZED_SQL


def test_dense_rpc_is_not_granted_to_anonymous_users() -> None:
    signature = "vector, uuid, uuid, uuid[], integer"
    assert f"revoke all on function public.match_document_chunks( {signature} )" in (NORMALIZED_SQL)
    assert "from public, anon" in NORMALIZED_SQL
    assert f"grant execute on function public.match_document_chunks( {signature} )" in (
        NORMALIZED_SQL
    )
    assert "to authenticated, service_role" in NORMALIZED_SQL
