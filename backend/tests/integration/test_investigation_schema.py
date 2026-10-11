"""Phase 2 tables (T2.1): conventions, CHECKs, and qc_app / qc_retention grants."""

import uuid

import psycopg
import pytest

pytestmark = pytest.mark.integration

UUID_ID_TABLES = {
    "investigations",
    "investigation_runs",
    "agent_executions",
    "tool_executions",
    "findings",
    "hypotheses",
    "jobs",
}
# Documented exceptions (DATABASE_DESIGN §4): the event log is ordered by an identity column,
# and evidence IDs are short deterministic text that agents cite in prompts.
OTHER_TABLES = {"investigation_events", "evidence"}
APPEND_ONLY = {
    "investigation_events",
    "agent_executions",
    "tool_executions",
    "evidence",
    "findings",
}
MUTABLE = {"investigations", "investigation_runs", "hypotheses", "jobs"}


def _new_run(conn: psycopg.Connection) -> uuid.UUID:
    inv = conn.execute(
        "INSERT INTO investigations (user_id, title, objective, modes) "
        "VALUES (uuid_generate_v4(), 't', 'o', ARRAY['offline']) RETURNING id"
    ).fetchone()
    assert inv is not None
    row = conn.execute(
        "INSERT INTO investigation_runs (investigation_id, run_number, kind, status, budget, "
        "usage) VALUES (%s, 1, 'initial', 'queued', '{}', '{}') RETURNING id",
        (inv[0],),
    ).fetchone()
    assert row is not None
    return row[0]  # type: ignore[no-any-return]


def test_phase2_tables_exist(owner: psycopg.Connection) -> None:
    rows = owner.execute(
        "SELECT table_name FROM information_schema.tables WHERE table_schema = 'public'"
    ).fetchall()

    assert {r[0] for r in rows} >= UUID_ID_TABLES | OTHER_TABLES


def test_standard_columns(owner: psycopg.Connection) -> None:
    for table in UUID_ID_TABLES | OTHER_TABLES:
        cols = {
            r[0]: (r[1], r[2])
            for r in owner.execute(
                "SELECT column_name, data_type, column_default FROM information_schema.columns "
                "WHERE table_schema = 'public' AND table_name = %s",
                (table,),
            )
        }
        if table in UUID_ID_TABLES:
            assert cols["id"][0] == "uuid", table
            assert "uuid_generate_v4()" in (cols["id"][1] or ""), table
        for ts in ("created_at", "updated_at", "deleted_at"):
            assert cols[ts][0] == "timestamp with time zone", (table, ts)


@pytest.mark.parametrize(
    ("sql", "params"),
    [
        (
            "INSERT INTO investigations (user_id, title, objective, modes) "
            "VALUES (uuid_generate_v4(), 't', 'o', ARRAY['mode_z'])",
            (),
        ),
        (
            "INSERT INTO investigations (user_id, title, objective, modes) "
            "VALUES (uuid_generate_v4(), 't', repeat('x', 2001), ARRAY['offline'])",
            (),
        ),
        (
            "INSERT INTO investigation_runs (investigation_id, run_number, kind, status, budget, "
            "usage) VALUES (uuid_generate_v4(), 1, 'initial', 'paused', '{}', '{}')",
            (),
        ),
        (
            "INSERT INTO jobs (kind, payload, status) VALUES ('run_start', '{}', 'sleeping')",
            (),
        ),
    ],
)
def test_checks_reject_unknown_values(
    owner: psycopg.Connection, sql: str, params: tuple[()]
) -> None:
    with pytest.raises(psycopg.errors.CheckViolation):
        owner.execute(sql, params)


def test_run_number_unique_per_investigation(owner: psycopg.Connection) -> None:
    run_id = _new_run(owner)
    inv = owner.execute(
        "SELECT investigation_id FROM investigation_runs WHERE id = %s", (run_id,)
    ).fetchone()
    assert inv is not None

    with pytest.raises(psycopg.errors.UniqueViolation):
        owner.execute(
            "INSERT INTO investigation_runs (investigation_id, run_number, kind, status, budget, "
            "usage) VALUES (%s, 1, 'initial', 'queued', '{}', '{}')",
            (inv[0],),
        )


def test_event_seq_unique_per_run(owner: psycopg.Connection) -> None:
    run_id = _new_run(owner)
    insert = (
        "INSERT INTO investigation_events (run_id, seq, type, payload) "
        "VALUES (%s, 1, 'node.started', '{}')"
    )
    owner.execute(insert, (run_id,))

    with pytest.raises(psycopg.errors.UniqueViolation):
        owner.execute(insert, (run_id,))


def test_evidence_id_shape_is_checked(owner: psycopg.Connection) -> None:
    run_id = _new_run(owner)
    with pytest.raises(psycopg.errors.CheckViolation):
        owner.execute(
            "INSERT INTO evidence (id, run_id, kind, locator, summary, data, provenance) "
            "VALUES ('evidence-1', %s, 'plan_node', '/0', 's', '{}', 'measured')",
            (run_id,),
        )


def test_app_appends_events_using_the_identity_sequence(as_app: psycopg.Connection) -> None:
    run_id = _new_run(as_app)
    seq = as_app.execute(
        "UPDATE investigation_runs SET last_event_seq = last_event_seq + 1 WHERE id = %s "
        "RETURNING last_event_seq",
        (run_id,),
    ).fetchone()
    assert seq == (1,)

    as_app.execute(
        "INSERT INTO investigation_events (run_id, seq, type, payload) "
        "VALUES (%s, %s, 'node.started', '{}')",
        (run_id, seq[0]),
    )

    rows = as_app.execute(
        "SELECT seq FROM investigation_events WHERE run_id = %s", (run_id,)
    ).fetchall()
    assert rows == [(1,)]


@pytest.mark.parametrize("table", sorted(APPEND_ONLY))
@pytest.mark.parametrize("verb", ["UPDATE {t} SET deleted_at = now()", "DELETE FROM {t}"])
def test_app_cannot_mutate_append_only_tables(
    as_app: psycopg.Connection, table: str, verb: str
) -> None:
    with pytest.raises(psycopg.errors.InsufficientPrivilege):
        as_app.execute(verb.format(t=table))


@pytest.mark.parametrize("table", sorted(APPEND_ONLY))
def test_app_cannot_lock_append_only_tables(as_app: psycopg.Connection, table: str) -> None:
    with pytest.raises(psycopg.errors.InsufficientPrivilege):
        as_app.execute(f"SELECT 1 FROM {table} FOR UPDATE")


@pytest.mark.parametrize("table", sorted(MUTABLE))
def test_app_updates_but_never_deletes_mutable_tables(
    as_app: psycopg.Connection, table: str
) -> None:
    as_app.execute(f"UPDATE {table} SET deleted_at = NULL WHERE false")
    with pytest.raises(psycopg.errors.InsufficientPrivilege):
        as_app.execute(f"DELETE FROM {table}")


def test_jobs_claim_query_runs_as_app(as_app: psycopg.Connection) -> None:
    as_app.execute("INSERT INTO jobs (kind, payload) VALUES ('run_start', '{}')")

    row = as_app.execute(
        "UPDATE jobs SET status = 'running', locked_by = 'w1', "
        "locked_until = now() + interval '60 seconds', attempts = attempts + 1 "
        "WHERE id = (SELECT id FROM jobs WHERE status = 'pending' AND run_after <= now() "
        "ORDER BY run_after FOR UPDATE SKIP LOCKED LIMIT 1) RETURNING attempts"
    ).fetchone()

    assert row == (1,)


@pytest.mark.parametrize("table", sorted(UUID_ID_TABLES | OTHER_TABLES))
def test_retention_can_delete(as_retention: psycopg.Connection, table: str) -> None:
    as_retention.execute(f"DELETE FROM {table} WHERE false")


def test_checkpointer_tables_live_in_their_own_schema(owner: psycopg.Connection) -> None:
    tables = {
        r[0]
        for r in owner.execute(
            "SELECT table_name FROM information_schema.tables WHERE table_schema = 'langgraph'"
        )
    }

    assert {
        "checkpoints",
        "checkpoint_blobs",
        "checkpoint_writes",
        "checkpoint_migrations",
    } <= tables


def test_app_uses_checkpointer_tables_but_cannot_create_or_delete(
    as_app: psycopg.Connection,
) -> None:
    as_app.execute("SELECT count(*) FROM langgraph.checkpoints")
    as_app.execute("UPDATE langgraph.checkpoints SET metadata = metadata WHERE false")
    with pytest.raises(psycopg.errors.InsufficientPrivilege):
        as_app.execute("CREATE TABLE langgraph.sneaky (id int)")
    with pytest.raises(psycopg.errors.InsufficientPrivilege):
        as_app.execute("DELETE FROM langgraph.checkpoints")
