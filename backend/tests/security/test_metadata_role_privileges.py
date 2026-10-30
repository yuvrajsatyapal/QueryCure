"""The application roles hold the minimum the app needs; the same audit was run against the
hosted Neon database and matched a fresh migration exactly. No owner-level privilege may be
granted to qc_app or qc_retention."""

import psycopg
import pytest

ROLES = ("qc_app", "qc_retention")


@pytest.mark.parametrize("role", ROLES)
def test_roles_are_plain_login_roles(owner: psycopg.Connection, role: str) -> None:
    row = owner.execute(
        "SELECT rolsuper, rolcreatedb, rolcreaterole, rolreplication, rolbypassrls "
        "FROM pg_roles WHERE rolname = %s",
        (role,),
    ).fetchone()

    assert row == (False, False, False, False, False)


@pytest.mark.parametrize("role", ROLES)
def test_roles_cannot_create_in_schemas_or_database_and_own_nothing(
    owner: psycopg.Connection, role: str
) -> None:
    create = owner.execute(
        "SELECT bool_or(has_schema_privilege(%s, n.oid, 'CREATE')), "
        "has_database_privilege(%s, current_database(), 'CREATE') "
        "FROM pg_namespace n WHERE n.nspname IN ('public', 'langgraph')",
        (role, role),
    ).fetchone()
    owned = owner.execute(
        "SELECT count(*) FROM pg_class c JOIN pg_roles o ON o.oid = c.relowner "
        "WHERE o.rolname = %s",
        (role,),
    ).fetchone()

    assert create == (False, False)
    assert owned == (0,)


def _tables_with(owner: psycopg.Connection, role: str, privilege: str) -> list[str]:
    rows = owner.execute(
        "SELECT n.nspname || '.' || c.relname FROM pg_class c "
        "JOIN pg_namespace n ON n.oid = c.relnamespace "
        "WHERE c.relkind IN ('r', 'p') AND n.nspname IN ('public', 'langgraph') "
        "AND has_table_privilege(%s, c.oid, %s)",
        (role, privilege),
    ).fetchall()
    return [r[0] for r in rows]


@pytest.mark.parametrize("privilege", ["DELETE", "TRUNCATE", "REFERENCES", "TRIGGER"])
def test_the_app_role_cannot_delete_truncate_or_alter_structure(
    owner: psycopg.Connection, privilege: str
) -> None:
    assert _tables_with(owner, "qc_app", privilege) == []


@pytest.mark.parametrize("privilege", ["INSERT", "UPDATE", "TRUNCATE", "REFERENCES", "TRIGGER"])
def test_the_retention_role_can_only_select_and_delete(
    owner: psycopg.Connection, privilege: str
) -> None:
    assert _tables_with(owner, "qc_retention", privilege) == []


def test_the_roles_do_have_the_access_they_need(owner: psycopg.Connection) -> None:
    assert _tables_with(owner, "qc_app", "SELECT")
    assert _tables_with(owner, "qc_app", "INSERT")
    assert _tables_with(owner, "qc_retention", "DELETE")


def test_the_app_role_cannot_run_ddl(owner: psycopg.Connection) -> None:
    owner.execute("SET ROLE qc_app")
    try:
        with pytest.raises(psycopg.errors.InsufficientPrivilege):
            owner.execute("CREATE TABLE qc_should_not_exist (x int)")
    finally:
        owner.execute("RESET ROLE")


@pytest.mark.parametrize("table", ["artifacts", "run_artifacts", "investigation_events"])
@pytest.mark.parametrize("privilege", ["UPDATE", "DELETE", "TRUNCATE"])
def test_the_app_role_cannot_change_or_remove_artifacts_or_links(
    owner: psycopg.Connection, table: str, privilege: str
) -> None:
    """Replay snapshots link the source's sealed artifacts (REPLAY_OUTCOME_AUDIT §14), and the
    replay's creation event marks that a snapshot is required (§16): the app can neither
    soft-delete (UPDATE deleted_at), rewrite nor remove an artifact, a link or an event."""
    allowed = owner.execute(
        "SELECT has_table_privilege('qc_app', %s, %s)", (f"public.{table}", privilege)
    ).fetchone()
    assert allowed == (False,)
