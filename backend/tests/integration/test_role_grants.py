"""Append-only grants (DATABASE_DESIGN §5, TESTING_STRATEGY §3). Runs with qd_app privileges."""

import psycopg
import pytest

pytestmark = pytest.mark.integration


def _insert_artifact(conn: psycopg.Connection, digest: str) -> object:
    row = conn.execute(
        "INSERT INTO artifacts (sha256, kind, media_type, content, canonicalization) "
        "VALUES (%s, 'query', 'text/sql', %s, 'qd-raw-v1') RETURNING id",
        (digest, b"SELECT 1"),
    ).fetchone()
    assert row is not None
    return row[0]


def test_app_can_insert_and_read_artifacts(as_app: psycopg.Connection) -> None:
    artifact_id = _insert_artifact(as_app, "b" * 64)

    row = as_app.execute("SELECT content FROM artifacts WHERE id = %s", (artifact_id,)).fetchone()

    assert row == (b"SELECT 1",)


@pytest.mark.parametrize(
    "statement",
    [
        "UPDATE artifacts SET kind = 'plan'",
        "DELETE FROM artifacts",
        "SELECT * FROM artifacts FOR UPDATE",
        "SELECT * FROM artifacts FOR SHARE",
        "TRUNCATE artifacts",
    ],
)
def test_app_cannot_mutate_or_lock_artifacts(as_app: psycopg.Connection, statement: str) -> None:
    with pytest.raises(psycopg.errors.InsufficientPrivilege):
        as_app.execute(statement)


def test_app_cannot_change_schema(as_app: psycopg.Connection) -> None:
    with pytest.raises(psycopg.errors.InsufficientPrivilege):
        as_app.execute("CREATE TABLE sneaky (id int)")


def test_app_soft_deletes_but_never_hard_deletes_users(as_app: psycopg.Connection) -> None:
    user_id = as_app.execute(
        "INSERT INTO users (kind) VALUES ('anonymous') RETURNING id"
    ).fetchone()[0]  # type: ignore[index]

    as_app.execute("UPDATE users SET deleted_at = now() WHERE id = %s", (user_id,))
    with pytest.raises(psycopg.errors.InsufficientPrivilege):
        as_app.execute("DELETE FROM users WHERE id = %s", (user_id,))


def test_retention_role_can_delete_append_only_rows(
    as_app: psycopg.Connection, as_retention: psycopg.Connection
) -> None:
    artifact_id = _insert_artifact(as_app, "c" * 64)

    deleted = as_retention.execute("DELETE FROM artifacts WHERE id = %s", (artifact_id,)).rowcount

    assert deleted == 1


def test_retention_role_cannot_insert(as_retention: psycopg.Connection) -> None:
    with pytest.raises(psycopg.errors.InsufficientPrivilege):
        _insert_artifact(as_retention, "d" * 64)


def test_app_can_read_but_not_change_migration_state(as_app: psycopg.Connection) -> None:
    assert as_app.execute("SELECT version_num FROM alembic_version").fetchone() is not None
    with pytest.raises(psycopg.errors.InsufficientPrivilege):
        as_app.execute("UPDATE alembic_version SET version_num = 'x'")


def test_only_one_active_local_user_can_exist(as_app: psycopg.Connection) -> None:
    as_app.execute("INSERT INTO users (kind) VALUES ('local') ON CONFLICT DO NOTHING")

    with pytest.raises(psycopg.errors.UniqueViolation):
        as_app.execute("INSERT INTO users (kind) VALUES ('local')")
