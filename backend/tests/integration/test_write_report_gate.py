"""write_report's audit gate against a real metadata database (no sandbox, LLM or benchmark).

A run holds one candidate that the engine called `verified` and no audit record: what the graph
leaves behind when the budget expires before the Benchmark Auditor starts. The real `write_report`
node runs on it, and `finalize_run`'s existing fault seam makes it fail after the gate has
already downgraded the candidate and emitted its error event.

- A failure at any `finalize_run` step rolls the downgrade, the error event and the partial
  seal back together; the retry then downgrades once, emits once and seals once.
- A sealed run is not touched again: the node's own `node.started` is refused by the sealed
  event log, and a retried job returns before any node runs.

Needs Docker (metadata DB); not run in the environment that wrote it.
"""

import uuid
from types import SimpleNamespace
from typing import Any

import psycopg
import pytest
from sqlalchemy.ext.asyncio import AsyncEngine

from querycure.agents.nodes.write_report import write_report
from querycure.agents.run import execute_run
from querycure.audit.completeness import UnauditedCandidate, unaudited_reasons
from querycure.core.errors import RunFinalizedError
from querycure.db.repositories.optimization import insert_candidates
from querycure.domain.optimization import CandidateCost, OptimizationCandidate
from querycure.replay.finalize import finalize_run as real_finalize_run
from tests.fake_llm import RoleClient
from tests.integration.run_helpers import context, new_run
from tests.integration.test_finalize import STEPS, Boom
from tests.integration.test_investigation_graph import services

pytestmark = pytest.mark.integration

KEY = "oc_" + "a" * 12
STATE: Any = {
    "winner": KEY,  # the engine's winner, still in the graph state when write_report starts
    "stop_reason": "budget_exhausted",
    "approval_status": "approved",
    "materiality": {},
    "no_action_evidence": [],
}


async def run_with_unaudited_verified_candidate(engine: AsyncEngine) -> tuple[uuid.UUID, uuid.UUID]:
    run_id = await new_run(engine)
    candidate = OptimizationCandidate(
        key=KEY,
        round=0,
        kind="create_index",
        addresses_hypotheses=["hy_" + "1" * 12],
        ddl=["CREATE INDEX ON orders (customer_id)"],
        query_sql=None,
        sql_sha256="ab" * 32,
        rollback_sql=None,
        expected_benefit="fewer rows read",
        risks=[],
        estimated_cost=CandidateCost(),
        status="verified",
    )
    async with engine.begin() as conn:
        (stored,) = await insert_candidates(conn, run_id, [candidate])
    assert stored.id is not None
    return run_id, stored.id


def snapshot(owner: psycopg.Connection, run_id: uuid.UUID) -> dict[str, Any]:
    """Everything the gate and the seal write, except the node's own `node.started` events."""
    candidate = owner.execute(
        "SELECT status, verdict_reasons FROM optimization_candidates WHERE run_id = %s", (run_id,)
    ).fetchall()
    run = owner.execute(
        "SELECT status, finalized_at IS NOT NULL, outcome FROM investigation_runs WHERE id = %s",
        (run_id,),
    ).fetchone()
    counts = owner.execute(
        "SELECT "
        "(SELECT count(*) FROM investigation_events WHERE run_id = %(r)s AND type = 'error' "
        " AND payload->>'code' = 'AUDIT_NOT_COMPLETED'), "
        "(SELECT count(*) FROM investigation_events WHERE run_id = %(r)s "
        " AND type <> 'node.started'), "
        "(SELECT count(*) FROM investigation_reports WHERE run_id = %(r)s), "
        "(SELECT count(*) FROM replay_manifests WHERE run_id = %(r)s), "
        "(SELECT count(*) FROM verification_results WHERE run_id = %(r)s)",
        {"r": run_id},
    ).fetchone()
    assert run is not None
    assert counts is not None
    return {
        "candidates": [tuple(c) for c in candidate],
        "run": tuple(run),
        "audit_errors": counts[0],
        "content_events": counts[1],
        "reports": counts[2],
        "manifests": counts[3],
        "verifications": counts[4],
    }


UNSEALED = {
    "candidates": [("verified", None)],
    "run": ("running", False, None),
    "audit_errors": 0,
    "reports": 0,
    "manifests": 0,
    "verifications": 0,
}


async def call(engine: AsyncEngine, run_id: uuid.UUID) -> Any:
    return await write_report(STATE, SimpleNamespace(context=context(engine, run_id)))  # type: ignore[arg-type]


def fail_at(monkeypatch: pytest.MonkeyPatch, step: str) -> None:
    async def finalize_run(conn: Any, run_id: uuid.UUID, conclusion: Any, **kwargs: Any) -> Any:
        def fault(name: str) -> None:
            if name == step:
                raise Boom(name)

        return await real_finalize_run(conn, run_id, conclusion, fault=fault, **kwargs)

    monkeypatch.setattr("querycure.agents.nodes.write_report.finalize_run", finalize_run)


@pytest.mark.parametrize("step", STEPS)
async def test_a_failure_after_the_downgrade_rolls_everything_back_and_the_retry_writes_once(
    app_engine: AsyncEngine,
    owner: psycopg.Connection,
    monkeypatch: pytest.MonkeyPatch,
    step: str,
) -> None:
    run_id, candidate_id = await run_with_unaudited_verified_candidate(app_engine)
    before = snapshot(owner, run_id)
    assert {k: v for k, v in before.items() if k != "content_events"} == UNSEALED

    with monkeypatch.context() as patched:
        fail_at(patched, step)
        with pytest.raises(Boom):
            await call(app_engine, run_id)

    # The downgrade, its error event, RUN_CONCLUDED and any partial report or manifest were one
    # transaction: nothing of it is visible, and the candidate is still the engine's `verified`.
    assert snapshot(owner, run_id) == before

    result = await call(app_engine, run_id)

    reasons = unaudited_reasons(
        UnauditedCandidate(id=candidate_id, key=KEY, round=0, status="verified"),
        "budget_exhausted",
    )
    after = snapshot(owner, run_id)
    assert result == {"outcome": "inconclusive"}
    assert after["candidates"] == [("inconclusive", reasons)]
    assert after["run"] == ("completed", True, "inconclusive")
    assert after["audit_errors"] == 1
    assert (after["reports"], after["manifests"]) == (1, 1)
    assert after["verifications"] == 0  # no audit record is invented for an audit that never ran


async def test_a_sealed_run_is_not_touched_by_a_retry(
    app_engine: AsyncEngine, owner: psycopg.Connection, migrated_db: str
) -> None:
    run_id, _ = await run_with_unaudited_verified_candidate(app_engine)
    await call(app_engine, run_id)
    sealed = snapshot(owner, run_id)
    assert sealed["run"] == ("completed", True, "inconclusive")
    assert sealed["audit_errors"] == 1

    # The node: its own node.started event is refused by the sealed event log, so neither the
    # gate nor the report builder runs again.
    with pytest.raises(RunFinalizedError):
        await call(app_engine, run_id)
    assert snapshot(owner, run_id) == sealed

    # The job: a retried job finds a terminal run and returns before any node runs.
    await execute_run(
        services(app_engine, migrated_db, RoleClient({})), run_id, attempt=2, reclaimed=True
    )
    assert snapshot(owner, run_id) == sealed
