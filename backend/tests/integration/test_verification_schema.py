"""Phase 4 tables (T4.1): grants follow the per-table rule, and the database itself refuses an
auditor upgrade (ADR-0009)."""

import uuid

import psycopg
import pytest

pytestmark = pytest.mark.integration

APPEND_ONLY = ("verification_results", "investigation_reports", "replay_manifests")


def _verification(
    conn: psycopg.Connection,
    *,
    engine_verdict: str = "verified",
    verdict: str = "verified",
    downgraded: bool = False,
) -> uuid.UUID:
    row = conn.execute(
        "INSERT INTO verification_results (run_id, experiment_id, candidate_id, candidate_key, "
        "round, engine_verdict, verdict, auditor_downgraded, auditor_status) "
        "VALUES (%s, %s, %s, 'oc_0123456789ab', 0, %s, %s, %s, 'deterministic_only') "
        "RETURNING id",
        (uuid.uuid4(), uuid.uuid4(), uuid.uuid4(), engine_verdict, verdict, downgraded),
    ).fetchone()
    assert row is not None
    return uuid.UUID(str(row[0]))


def _report(conn: psycopg.Connection) -> uuid.UUID:
    run_id = uuid.uuid4()
    conn.execute(
        "INSERT INTO investigation_reports (run_id, report_json_artifact_id, "
        "report_md_artifact_id, report_json_sha256, report_md_sha256, final_status, outcome, "
        "report_schema_version, builder_version, md_renderer_version) "
        "VALUES (%s, %s, %s, 'a', 'b', 'completed', 'inconclusive', 1, 'report-builder@1', "
        "'report-md@1')",
        (run_id, uuid.uuid4(), uuid.uuid4()),
    )
    return run_id


def _manifest(conn: psycopg.Connection) -> uuid.UUID:
    run_id = uuid.uuid4()
    conn.execute(
        "INSERT INTO replay_manifests (run_id, manifest_artifact_id, manifest_sha256, "
        "manifest_schema_version, events_cutoff_seq, events_digest) "
        "VALUES (%s, %s, 'c', 1, 3, 'sha256:d')",
        (run_id, uuid.uuid4()),
    )
    return run_id


@pytest.mark.parametrize(
    ("engine_verdict", "verdict"),
    [
        ("verified", "verified"),
        ("verified_with_noise_warning", "verified_with_noise_warning"),
        ("rejected", "rejected"),
        ("inconclusive", "inconclusive"),
    ],
)
def test_unchanged_verdicts_are_accepted(
    as_app: psycopg.Connection, engine_verdict: str, verdict: str
) -> None:
    _verification(as_app, engine_verdict=engine_verdict, verdict=verdict)


@pytest.mark.parametrize("engine_verdict", ["verified", "verified_with_noise_warning"])
def test_downgrade_to_inconclusive_is_accepted(
    as_app: psycopg.Connection, engine_verdict: str
) -> None:
    _verification(as_app, engine_verdict=engine_verdict, verdict="inconclusive", downgraded=True)


@pytest.mark.parametrize(
    ("engine_verdict", "verdict"),
    [
        ("inconclusive", "verified"),
        ("rejected", "verified"),
        ("inconclusive", "verified_with_noise_warning"),
        ("verified_with_noise_warning", "verified"),
        ("rejected", "inconclusive"),
        ("verified", "rejected"),
    ],
)
def test_the_database_refuses_an_upgrade_or_a_change_of_kind(
    as_app: psycopg.Connection, engine_verdict: str, verdict: str
) -> None:
    with pytest.raises(psycopg.errors.CheckViolation):
        _verification(as_app, engine_verdict=engine_verdict, verdict=verdict, downgraded=True)


def test_downgraded_flag_must_match_the_verdicts(as_app: psycopg.Connection) -> None:
    with pytest.raises(psycopg.errors.CheckViolation):
        _verification(as_app, engine_verdict="verified", verdict="verified", downgraded=True)
    with pytest.raises(psycopg.errors.CheckViolation):
        _verification(as_app, engine_verdict="verified", verdict="inconclusive", downgraded=False)


def test_one_verification_per_candidate_and_experiment(as_app: psycopg.Connection) -> None:
    experiment, candidate = uuid.uuid4(), uuid.uuid4()
    sql = (
        "INSERT INTO verification_results (run_id, experiment_id, candidate_id, candidate_key, "
        "round, engine_verdict, verdict, auditor_downgraded, auditor_status) "
        "VALUES (%s, %s, %s, 'oc_0123456789ab', 0, 'verified', 'verified', false, "
        "'deterministic_only')"
    )
    as_app.execute(sql, (uuid.uuid4(), experiment, candidate))
    with pytest.raises(psycopg.errors.UniqueViolation):
        as_app.execute(sql, (uuid.uuid4(), experiment, candidate))


@pytest.mark.parametrize("table", APPEND_ONLY)
@pytest.mark.parametrize(
    "template",
    [
        "UPDATE {t} SET created_at = now()",
        "DELETE FROM {t}",
        "SELECT * FROM {t} FOR UPDATE",
        "SELECT * FROM {t} FOR SHARE",
        "TRUNCATE {t}",
    ],
)
def test_app_cannot_mutate_or_lock_sealed_tables(
    as_app: psycopg.Connection, table: str, template: str
) -> None:
    with pytest.raises(psycopg.errors.InsufficientPrivilege):
        as_app.execute(template.format(t=table))


def test_app_inserts_and_reads_reports_and_manifests(as_app: psycopg.Connection) -> None:
    report_run, manifest_run = _report(as_app), _manifest(as_app)

    assert as_app.execute(
        "SELECT builder_version FROM investigation_reports WHERE run_id = %s", (report_run,)
    ).fetchone() == ("report-builder@1",)
    assert as_app.execute(
        "SELECT events_cutoff_seq FROM replay_manifests WHERE run_id = %s", (manifest_run,)
    ).fetchone() == (3,)


def test_one_report_and_one_manifest_per_run(as_app: psycopg.Connection) -> None:
    run_id = _report(as_app)
    with pytest.raises(psycopg.errors.UniqueViolation):
        as_app.execute(
            "INSERT INTO investigation_reports (run_id, report_json_artifact_id, "
            "report_md_artifact_id, report_json_sha256, report_md_sha256, final_status, "
            "report_schema_version, builder_version, md_renderer_version) "
            "VALUES (%s, %s, %s, 'a', 'b', 'failed', 1, 'report-builder@1', 'report-md@1')",
            (run_id, uuid.uuid4(), uuid.uuid4()),
        )


def test_replay_attempts_are_mutable_but_not_deletable(as_app: psycopg.Connection) -> None:
    row = as_app.execute(
        "INSERT INTO replay_attempts (user_id, kind, source_run_id, status) "
        "VALUES (%s, 'report', %s, 'verifying') RETURNING id",
        (uuid.uuid4(), uuid.uuid4()),
    ).fetchone()
    assert row is not None
    as_app.execute(
        "UPDATE replay_attempts SET status = 'verified', finished_at = now() WHERE id = %s",
        (row[0],),
    )
    with pytest.raises(psycopg.errors.InsufficientPrivilege):
        as_app.execute("DELETE FROM replay_attempts")


@pytest.mark.parametrize(
    ("kind", "status"),
    [("report", "reproduced"), ("experiment", "verified_stored_only"), ("report", "bogus")],
)
def test_replay_attempt_status_must_fit_its_kind(
    as_app: psycopg.Connection, kind: str, status: str
) -> None:
    with pytest.raises(psycopg.errors.CheckViolation):
        as_app.execute(
            "INSERT INTO replay_attempts (user_id, kind, source_run_id, status) "
            "VALUES (%s, %s, %s, %s)",
            (uuid.uuid4(), kind, uuid.uuid4(), status),
        )


def test_experiment_replay_attempt_needs_a_source_experiment(as_app: psycopg.Connection) -> None:
    with pytest.raises(psycopg.errors.CheckViolation):
        as_app.execute(
            "INSERT INTO replay_attempts (user_id, kind, source_run_id, status) "
            "VALUES (%s, 'experiment', %s, 'checking')",
            (uuid.uuid4(), uuid.uuid4()),
        )


@pytest.mark.parametrize("table", [*APPEND_ONLY, "replay_attempts"])
def test_retention_can_delete_phase4_rows(as_retention: psycopg.Connection, table: str) -> None:
    as_retention.execute(f"DELETE FROM {table} WHERE false")
