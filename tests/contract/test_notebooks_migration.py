"""Contract checks for notebook ownership and RLS.

Points at the consolidated schema files in supabase/migrations/
(02_tables.sql, 04_rls_policies.sql) rather than individual timestamped
migrations - the project replaced the incremental migration history with
these consolidated, always-current files (see database/README.md /
research/feature/note.md for why).
"""

from pathlib import Path

TABLES_SQL = Path("supabase/migrations/02_tables.sql").read_text(encoding="utf-8").lower()
RLS_SQL = Path("supabase/migrations/04_rls_policies.sql").read_text(encoding="utf-8").lower()

# 04_rls_policies.sql covers every table in one file - slice out just the
# notebooks section (between its own grants and the next table's header) so
# assertions here can't accidentally pass by matching a different table.
_NOTEBOOKS_RLS_SQL = RLS_SQL.split("revoke all on table public.notebooks from anon;", 1)[1].split(
    "-- documents / ingestion_jobs", 1
)[0]
_NOTEBOOKS_RLS_SQL = "revoke all on table public.notebooks from anon;" + _NOTEBOOKS_RLS_SQL


def test_notebooks_table_enforces_owner_fk_and_has_a_description() -> None:
    assert "create table public.notebooks" in TABLES_SQL
    assert "owner_id uuid not null default auth.uid()" in TABLES_SQL
    assert "references auth.users (id) on delete cascade" in TABLES_SQL
    assert "description text not null default ''" in TABLES_SQL
    assert "constraint notebooks_id_owner_key" in TABLES_SQL
    assert "unique (id, owner_id)" in TABLES_SQL


def test_notebooks_rls_restricts_every_operation_to_the_owner() -> None:
    assert "enable row level security" in _NOTEBOOKS_RLS_SQL
    assert "force row level security" in _NOTEBOOKS_RLS_SQL
    assert "create policy notebooks_select_own" in _NOTEBOOKS_RLS_SQL
    assert "create policy notebooks_insert_own" in _NOTEBOOKS_RLS_SQL
    assert "create policy notebooks_update_own" in _NOTEBOOKS_RLS_SQL
    assert "create policy notebooks_delete_own" in _NOTEBOOKS_RLS_SQL
    # 5 = one per select/insert/delete policy, plus 2 for update (using + with check).
    assert _NOTEBOOKS_RLS_SQL.count("(select auth.uid()) = owner_id") == 5


def test_notebooks_grants_are_limited_to_crud() -> None:
    assert "revoke all on table public.notebooks from anon" in _NOTEBOOKS_RLS_SQL
    assert "revoke all on table public.notebooks from authenticated" in _NOTEBOOKS_RLS_SQL
    assert (
        "grant select, insert, update, delete on table public.notebooks to authenticated"
        in _NOTEBOOKS_RLS_SQL
    )
