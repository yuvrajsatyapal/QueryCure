"""`python -m querycure.ops verify-integrity`: the restore check (DEPLOYMENT §4c), read-only."""

from collections.abc import AsyncIterator

import httpx2 as httpx
import psycopg
import pytest

from querycure.db.engine import make_engine
from querycure.ops.integrity import verify_integrity
from tests.integration.test_investigations_api import client_for
from tests.integration.test_report_replay import (
    _no_active_runs,  # noqa: F401
    no_llm,  # noqa: F401
    report_artifact,
    sealed_run,
)

pytestmark = pytest.mark.integration


@pytest.fixture
async def api(migrated_db: str) -> AsyncIterator[httpx.AsyncClient]:
    async for c in client_for(migrated_db):
        yield c


def _run_artifact_ids(owner: psycopg.Connection, run_id: str) -> set[str]:
    rows = owner.execute(
        "SELECT artifact_id FROM run_artifacts WHERE run_id = %s", (run_id,)
    ).fetchall()
    return {str(r[0]) for r in rows}


# The session database is shared, and other tests tamper with their own runs on purpose, so
# assertions are scoped to the run each test creates.
async def test_an_intact_sealed_run_verifies(
    api: httpx.AsyncClient, migrated_db: str, owner: psycopg.Connection
) -> None:
    run_id = await sealed_run(api)
    artifacts = _run_artifact_ids(owner, run_id)
    engine = make_engine(migrated_db, set_role="qc_app")
    try:
        result = await verify_integrity(engine)
    finally:
        await engine.dispose()

    assert artifacts
    assert result.artifacts_checked >= len(artifacts)
    assert artifacts.isdisjoint(result.artifact_failures)
    assert run_id not in result.report_failures
    assert result.report_statuses.get("verified", 0) >= 1


async def test_a_changed_artifact_and_its_report_are_reported(
    api: httpx.AsyncClient, migrated_db: str, owner: psycopg.Connection
) -> None:
    run_id = await sealed_run(api)
    tampered = report_artifact(owner, run_id, "output.report_md")
    owner.execute(
        "UPDATE artifacts SET content = content || '\\x20'::bytea WHERE id = %s", (tampered,)
    )
    engine = make_engine(migrated_db, set_role="qc_app")
    try:
        result = await verify_integrity(engine)
    finally:
        await engine.dispose()

    assert not result.ok
    assert tampered in result.artifact_failures
    assert run_id in result.report_failures


async def test_verification_writes_nothing(
    api: httpx.AsyncClient, migrated_db: str, owner: psycopg.Connection
) -> None:
    await sealed_run(api)
    tables = ("artifacts", "replay_attempts", "investigation_events", "investigation_runs")

    def counts() -> list[int]:
        return [owner.execute(f"SELECT count(*) FROM {t}").fetchone()[0] for t in tables]  # type: ignore[index]

    before = counts()
    engine = make_engine(migrated_db, set_role="qc_app")
    try:
        await verify_integrity(engine)
    finally:
        await engine.dispose()
    assert counts() == before
