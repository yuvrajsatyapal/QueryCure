"""Phase 3 tables: append-only grants on benchmark_runs and constraints (T3.1)."""

import uuid

import psycopg
import pytest

pytestmark = pytest.mark.integration


def _insert_block(conn: psycopg.Connection, experiment_id: uuid.UUID, block: int = 0) -> object:
    row = conn.execute(
        "INSERT INTO benchmark_runs (experiment_id, arm, param_set, phase, block, latencies_ns, "
        "provenance) VALUES (%s, 'baseline', 'hot', 'measure', %s, '[1200, 1300]', 'measured') "
        "RETURNING id",
        (experiment_id, block),
    ).fetchone()
    assert row is not None
    return row[0]


def test_app_inserts_and_reads_benchmark_runs(as_app: psycopg.Connection) -> None:
    experiment_id = uuid.uuid4()
    run_id = _insert_block(as_app, experiment_id)

    row = as_app.execute("SELECT latencies_ns FROM benchmark_runs WHERE id = %s", (run_id,))

    assert row.fetchone() == ([1200, 1300],)


def test_block_key_is_unique_for_idempotent_resume(as_app: psycopg.Connection) -> None:
    experiment_id = uuid.uuid4()
    _insert_block(as_app, experiment_id)

    with pytest.raises(psycopg.errors.UniqueViolation):
        _insert_block(as_app, experiment_id)


@pytest.mark.parametrize(
    "statement",
    [
        "UPDATE benchmark_runs SET latencies_ns = '[1]'",
        "DELETE FROM benchmark_runs",
        "SELECT * FROM benchmark_runs FOR UPDATE",
        "SELECT * FROM benchmark_runs FOR SHARE",
        "TRUNCATE benchmark_runs",
    ],
)
def test_app_cannot_mutate_or_lock_benchmark_runs(
    as_app: psycopg.Connection, statement: str
) -> None:
    with pytest.raises(psycopg.errors.InsufficientPrivilege):
        as_app.execute(statement)


def test_retention_can_delete_benchmark_runs(
    as_app: psycopg.Connection, as_retention: psycopg.Connection
) -> None:
    run_id = _insert_block(as_app, uuid.uuid4())

    deleted = as_retention.execute("DELETE FROM benchmark_runs WHERE id = %s", (run_id,))

    assert deleted.rowcount == 1


def test_app_cannot_delete_mutable_phase3_rows(as_app: psycopg.Connection) -> None:
    for table in ("optimization_candidates", "approval_requests", "experiments"):
        with pytest.raises(psycopg.errors.InsufficientPrivilege):
            as_app.execute(f"DELETE FROM {table}")


def test_approval_decided_at_tracks_status(as_app: psycopg.Connection) -> None:
    with pytest.raises(psycopg.errors.CheckViolation):
        as_app.execute(
            "INSERT INTO approval_requests (run_id, user_id, round, kind, payload, status, "
            "expires_at) VALUES (%s, %s, 0, 'sandbox_execution', '{}', 'approved', now())",
            (uuid.uuid4(), uuid.uuid4()),
        )


def test_rewrite_candidates_carry_their_query(as_app: psycopg.Connection) -> None:
    with pytest.raises(psycopg.errors.CheckViolation):
        as_app.execute(
            "INSERT INTO optimization_candidates (run_id, key, round, kind, addresses_hypotheses, "
            "sql_sha256, expected_benefit, estimated_cost, proposed_by) VALUES "
            "(%s, 'oc_000000000000', 0, 'query_rewrite', '{hy_000000000000}', 'x', 'y', '{}', "
            "'optimization_engineer')",
            (uuid.uuid4(),),
        )
