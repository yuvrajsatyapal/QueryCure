"""The assembled graph end to end (T2.10): checkpointing, resume, budgets, cancellation,
and secrets kept out of checkpoints. LLM responses are scripted; everything else is real."""

import asyncio
import base64
import json
import os
import re
import uuid
from collections.abc import Sequence
from pathlib import Path
from typing import Any

import psycopg
import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine

from querycure.agents.run import RunServices, execute_run
from querycure.agents.runtime import LlmClients
from querycure.core.config import Settings
from querycure.core.errors import ConfigurationError
from querycure.db.repositories.investigations import RunInputs
from querycure.domain.investigation import RunBudget
from querycure.jobs import queue
from querycure.jobs.handlers import dead_job_handler, run_handler
from querycure.llm.types import ChatMessage
from querycure.replay import artifact_store as store
from querycure.worker.runner import Worker, WorkerTimings
from tests.fake_llm import RoleClient, Step
from tests.integration.test_context_nodes import SETTINGS, _connection

pytestmark = pytest.mark.integration

PLANS = Path(__file__).parents[1] / "fixtures" / "plans"
SQL = "SELECT * FROM orders WHERE customer_id = $1 ORDER BY created_at DESC LIMIT 20"
EV = re.compile(r"(ev_[0-9a-f]{12})\] \([a-z_]+\) ([^\n]*)")
BUDGET = RunBudget(
    llm_calls=20,
    total_tokens=200_000,
    tool_calls=20,
    tool_calls_per_agent=6,
    wall_clock_seconds=600,
)
FAKE_API_KEY = "AIza" + "S" * 35


def cite(pattern: str) -> str:
    """Evidence ID of the first evidence line whose summary matches `pattern`."""
    return pattern


def _id_for(messages: Sequence[ChatMessage], pattern: str) -> str:
    for match in EV.finditer("\n".join(m.content for m in messages)):
        if re.search(pattern, match.group(2)):
            return match.group(1)
    raise AssertionError(f"no evidence line matches {pattern!r}")


def plan(*agents: str) -> str:
    return json.dumps({"agents": list(agents), "focus": [], "rationale": "plan"})


def analyst_final(pattern: str, title: str) -> Step:
    def step(messages: Sequence[ChatMessage]) -> str:
        return json.dumps(
            {
                "action": "final",
                "analysis": {
                    "summary": title,
                    "findings": [
                        {
                            "title": title,
                            "detail": title,
                            "severity": "high",
                            "evidence_ids": [_id_for(messages, pattern)],
                        }
                    ],
                },
            }
        )

    return step


def synthesis(category: str, pattern: str) -> Step:
    def step(messages: Sequence[ChatMessage]) -> str:
        return json.dumps(
            {
                "hypotheses": [
                    {
                        "statement": f"{category} explains the slow scan",
                        "category": category,
                        "supporting_evidence": [_id_for(messages, pattern)],
                        "contradicting_evidence": [],
                        "confidence": "high",
                        "uncertainty_notes": "not benchmarked",
                        "verification_method": "benchmark",
                    }
                ],
                "summary": "A composite index is the likely fix.",
            }
        )

    return step


def happy_scripts() -> dict[str, list[Step]]:
    return {
        "plan": [plan("query_analyzer", "index_strategist")],
        "query_analyzer": [analyst_final(r"Seq Scan on orders", "Seq Scan dominates")],
        "index_strategist": [analyst_final(r"Query orders by", "No index serves the ordering")],
        "synthesis": [synthesis("missing_index", r"Seq Scan on orders")],
    }


async def create_run(
    engine: AsyncEngine,
    *,
    budget: RunBudget = BUDGET,
    modes: tuple[str, ...] = ("offline",),
    sql: str = SQL,
    plan_file: str | None = "pg17_canonical_hot_analyze.json",
    user_id: uuid.UUID | None = None,
    connection_id: uuid.UUID | None = None,
) -> uuid.UUID:
    async with engine.begin() as conn:
        inv = (
            await conn.execute(
                text(
                    "INSERT INTO investigations (user_id, title, objective, modes, connection_id) "
                    "VALUES (:u, 't', 'Why is the orders page slow?', :m, :c) RETURNING id"
                ),
                {"u": user_id or uuid.uuid4(), "m": list(modes), "c": connection_id},
            )
        ).scalar_one()
        run_id: uuid.UUID = (
            await conn.execute(
                text(
                    "INSERT INTO investigation_runs (investigation_id, run_number, kind, status, "
                    "budget, usage) VALUES (:inv, 1, 'initial', 'queued', CAST(:b AS JSONB), '{}') "
                    "RETURNING id"
                ),
                {"inv": inv, "b": budget.model_dump_json()},
            )
        ).scalar_one()
        art = await store.store_raw_sql(conn, sql)
        await store.link(conn, run_id=run_id, artifact_id=art.id, role="input.query")
        if plan_file:
            doc = json.loads((PLANS / plan_file).read_text())
            art = await store.store_json(conn, kind="plan_analyze", value=doc)
            await store.link(conn, run_id=run_id, artifact_id=art.id, role="input.plan")
    return run_id


def services(engine: AsyncEngine, migrated_db: str, client: Any) -> RunServices:
    def clients(inputs: RunInputs) -> LlmClients:
        return LlmClients(primary=client)

    return RunServices(
        engine=engine,
        settings=SETTINGS,
        checkpoint_url=migrated_db,
        clients=clients,
        checkpoint_role="qc_app",
    )


def run_row(owner: psycopg.Connection, run_id: uuid.UUID) -> tuple[Any, ...]:
    row = owner.execute(
        "SELECT status, outcome, error->>'code' FROM investigation_runs WHERE id = %s", (run_id,)
    ).fetchone()
    assert row is not None
    return tuple(row)


def report(owner: psycopg.Connection, run_id: uuid.UUID) -> dict[str, Any]:
    row = owner.execute(
        "SELECT convert_from(a.content, 'UTF8') FROM run_artifacts ra "
        "JOIN artifacts a ON a.id = ra.artifact_id "
        "WHERE ra.run_id = %s AND ra.role = 'output.report_json'",
        (run_id,),
    ).fetchone()
    assert row is not None, "no report"
    return json.loads(row[0])  # type: ignore[no-any-return]


def statuses(owner: psycopg.Connection, run_id: uuid.UUID) -> list[str]:
    return [
        r[0]["to"]
        for r in owner.execute(
            "SELECT payload FROM investigation_events WHERE run_id = %s "
            "AND type = 'run.status_changed' ORDER BY seq",
            (run_id,),
        )
    ]


def job_status(owner: psycopg.Connection, run_id: uuid.UUID) -> str | None:
    row = owner.execute("SELECT status FROM jobs WHERE run_id = %s", (run_id,)).fetchone()
    return None if row is None else str(row[0])


async def wait_for_job(owner: psycopg.Connection, run_id: uuid.UUID, status: str) -> None:
    async with asyncio.timeout(20):
        # Polls database state written by the worker; there is no in-process event.
        while job_status(owner, run_id) != status:  # noqa: ASYNC110
            await asyncio.sleep(0.05)


async def test_offline_investigation_runs_end_to_end(
    app_engine: AsyncEngine, owner: psycopg.Connection, migrated_db: str
) -> None:
    run_id = await create_run(app_engine)
    client = RoleClient(happy_scripts())

    await execute_run(services(app_engine, migrated_db, client), run_id, attempt=1, reclaimed=False)

    assert run_row(owner, run_id) == ("completed", "unverified_recommendations", None)
    assert statuses(owner, run_id) == ["running", "completed"]
    body = report(owner, run_id)
    assert body["hypotheses"][0]["category"] == "missing_index"
    assert {f["agent"] for f in body["findings"]} == {"query_analyzer", "index_strategist"}
    assert body["partial"] is False
    assert any("Seq Scan on orders" in e["summary"] for e in body["evidence"])
    checkpoints = owner.execute(
        "SELECT count(*) FROM langgraph.checkpoints WHERE thread_id = %s", (str(run_id),)
    ).fetchone()
    assert checkpoints is not None
    assert checkpoints[0] >= 5
    md = owner.execute(
        "SELECT convert_from(a.content, 'UTF8') FROM run_artifacts ra JOIN artifacts a "
        "ON a.id = ra.artifact_id WHERE ra.run_id = %s AND ra.role = 'output.report_md'",
        (run_id,),
    ).fetchone()
    assert md is not None
    assert "Nothing in this report has been benchmarked" in md[0]


async def test_budget_exhaustion_ends_inconclusive_with_a_partial_report(
    app_engine: AsyncEngine, owner: psycopg.Connection, migrated_db: str
) -> None:
    # Two LLM calls: the plan and one analyst. The other analyst hits the limit.
    tight = BUDGET.model_copy(update={"llm_calls": 2})
    run_id = await create_run(app_engine, budget=tight)
    scripts = happy_scripts()
    client = RoleClient(scripts)

    await execute_run(services(app_engine, migrated_db, client), run_id, attempt=1, reclaimed=False)

    assert run_row(owner, run_id) == ("completed", "inconclusive", None)
    body = report(owner, run_id)
    assert body["partial"] is True
    assert body["stop_reason"] == "budget_exhausted"
    assert len(body["findings"]) == 1  # the analyst that got the last call
    assert body["hypotheses"] == []
    assert client.calls("synthesis") == []
    assert any(e["code"] == "BUDGET_EXHAUSTED" for e in body["errors"])


async def test_cancelled_run_ends_cancelled_with_a_partial_report(
    app_engine: AsyncEngine, owner: psycopg.Connection, migrated_db: str
) -> None:
    run_id = await create_run(app_engine)
    owner.execute(
        "UPDATE investigation_runs SET status = 'running', started_at = now() WHERE id = %s",
        (run_id,),
    )
    owner.execute(
        "UPDATE investigation_runs SET status = 'cancelling', cancel_requested_at = now() "
        "WHERE id = %s",
        (run_id,),
    )
    client = RoleClient({})

    await execute_run(services(app_engine, migrated_db, client), run_id, attempt=1, reclaimed=False)

    assert run_row(owner, run_id)[0] == "cancelled"
    body = report(owner, run_id)
    assert body["final_status"] == "cancelled"
    assert body["partial"] is True


class Killed(Exception):
    """Stands in for the worker process dying mid-run."""


async def test_crash_after_the_fan_out_resumes_without_redoing_analysis(
    app_engine: AsyncEngine, owner: psycopg.Connection, migrated_db: str
) -> None:
    run_id = await create_run(app_engine)
    first = happy_scripts()
    first["synthesis"] = [Killed("worker died during synthesis")]

    with pytest.raises(Killed):
        await execute_run(
            services(app_engine, migrated_db, RoleClient(first)), run_id, attempt=1, reclaimed=False
        )
    counts_before = owner.execute(
        "SELECT (SELECT count(*) FROM evidence WHERE run_id = %(r)s), "
        "(SELECT count(*) FROM findings WHERE run_id = %(r)s)",
        {"r": run_id},
    ).fetchone()

    # A new worker: analysts have no script, so re-running them would raise.
    second = RoleClient({"synthesis": [synthesis("missing_index", r"Seq Scan on orders")]})
    await execute_run(services(app_engine, migrated_db, second), run_id, attempt=2, reclaimed=True)

    assert run_row(owner, run_id) == ("completed", "unverified_recommendations", None)
    counts_after = owner.execute(
        "SELECT (SELECT count(*) FROM evidence WHERE run_id = %(r)s), "
        "(SELECT count(DISTINCT id) FROM evidence WHERE run_id = %(r)s), "
        "(SELECT count(*) FROM findings WHERE run_id = %(r)s)",
        {"r": run_id},
    ).fetchone()
    assert counts_before is not None
    assert counts_after == (counts_before[0], counts_before[0], counts_before[1])
    assert second.calls("query_analyzer") == []
    assert statuses(owner, run_id) == ["running", "queued", "running", "completed"]


async def test_worker_retries_a_crashed_run_job_to_completion(
    app_engine: AsyncEngine, owner: psycopg.Connection, migrated_db: str
) -> None:
    owner.execute("DELETE FROM jobs")
    run_id = await create_run(app_engine)
    scripts = happy_scripts()
    scripts["synthesis"] = [
        Killed("first attempt dies"),
        synthesis("missing_index", r"Seq Scan on orders"),
    ]
    svc = services(app_engine, migrated_db, RoleClient(scripts))
    async with app_engine.begin() as conn:
        await queue.enqueue(conn, kind="run_start", run_id=run_id, payload={})
    worker = Worker(
        app_engine,
        {"run_start": run_handler(svc)},
        worker_id="w1",
        timings=WorkerTimings(lease_seconds=30, heartbeat_seconds=1, poll_seconds=0.05),
        on_dead=dead_job_handler(svc),
    )
    task = asyncio.create_task(worker.run())
    try:
        await wait_for_job(owner, run_id, "pending")  # first attempt crashed, retry scheduled
        owner.execute("UPDATE jobs SET run_after = now() WHERE run_id = %s", (run_id,))
        await wait_for_job(owner, run_id, "done")
    finally:
        await worker.stop()
        await task

    assert run_row(owner, run_id) == ("completed", "unverified_recommendations", None)
    job = owner.execute("SELECT status, attempts FROM jobs WHERE run_id = %s", (run_id,)).fetchone()
    assert job == ("done", 2)


async def test_dead_lettered_job_fails_its_run(
    app_engine: AsyncEngine, owner: psycopg.Connection, migrated_db: str
) -> None:
    run_id = await create_run(app_engine)
    svc = services(app_engine, migrated_db, RoleClient({}))

    await dead_job_handler(svc)(queue.ReapedJob(id=uuid.uuid4(), kind="run_start", run_id=run_id))

    assert run_row(owner, run_id) == ("failed", None, "JOB_DEAD_LETTERED")


async def test_missing_llm_key_fails_the_run_with_a_configuration_error(
    app_engine: AsyncEngine, owner: psycopg.Connection, migrated_db: str
) -> None:
    run_id = await create_run(app_engine)

    def no_key(inputs: RunInputs) -> LlmClients:
        raise ConfigurationError("GEMINI_API_KEY is not set for the local profile.")

    svc = services(app_engine, migrated_db, None)
    svc.clients = no_key
    await execute_run(svc, run_id, attempt=1, reclaimed=False)

    assert run_row(owner, run_id) == ("failed", None, "CONFIGURATION_ERROR")


async def test_invalid_input_completes_inconclusive_without_calling_the_model(
    app_engine: AsyncEngine, owner: psycopg.Connection, migrated_db: str
) -> None:
    run_id = await create_run(app_engine, sql="DELETE FROM orders", plan_file=None)
    client = RoleClient({})

    await execute_run(services(app_engine, migrated_db, client), run_id, attempt=1, reclaimed=False)

    assert run_row(owner, run_id) == ("completed", "inconclusive", None)
    assert report(owner, run_id)["stop_reason"] == "invalid_input"


async def test_finished_runs_are_not_executed_again(
    app_engine: AsyncEngine, owner: psycopg.Connection, migrated_db: str
) -> None:
    run_id = await create_run(app_engine)
    await execute_run(
        services(app_engine, migrated_db, RoleClient(happy_scripts())),
        run_id,
        attempt=1,
        reclaimed=False,
    )
    events = owner.execute(
        "SELECT count(*) FROM investigation_events WHERE run_id = %s", (run_id,)
    ).fetchone()

    await execute_run(
        services(app_engine, migrated_db, RoleClient({})), run_id, attempt=2, reclaimed=True
    )

    assert (
        owner.execute(
            "SELECT count(*) FROM investigation_events WHERE run_id = %s", (run_id,)
        ).fetchone()
        == events
    )


class KeyHoldingClient(RoleClient):
    """Holds an API key the way a real provider client does."""

    def __init__(self, scripts: dict[str, list[Step]]) -> None:
        super().__init__(scripts)
        self.api_key = FAKE_API_KEY


async def test_secrets_never_reach_checkpoints(
    app_engine: AsyncEngine,
    owner: psycopg.Connection,
    migrated_db: str,
    target: dict[str, Any],
) -> None:
    user_id = uuid.uuid4()
    connection_id = await _connection(app_engine, user_id, target)
    run_id = await create_run(
        app_engine, modes=("live_inspection",), user_id=user_id, connection_id=connection_id
    )
    scripts = happy_scripts()
    scripts["query_analyzer"] = [analyst_final(r"Plain EXPLAIN|Seq Scan|Index Scan", "scan")]
    svc = services(app_engine, migrated_db, KeyHoldingClient(scripts))

    await execute_run(svc, run_id, attempt=1, reclaimed=False)

    assert run_row(owner, run_id)[0] == "completed"
    thread = {"t": str(run_id)}
    parts: list[bytes] = [
        json.dumps(r[0]).encode()
        for r in owner.execute(
            "SELECT checkpoint FROM langgraph.checkpoints WHERE thread_id = %(t)s", thread
        )
    ]
    for table in ("checkpoint_blobs", "checkpoint_writes"):
        parts += [
            bytes(r[0])
            for r in owner.execute(
                f"SELECT blob FROM langgraph.{table} WHERE thread_id = %(t)s AND blob IS NOT NULL",
                thread,
            )
        ]
    dump = b"".join(parts)
    assert len(dump) > 1000  # the scan covered real checkpoint data
    master_key = SETTINGS.master_key.get_secret_value()  # type: ignore[union-attr]
    for secret in (target["password"], FAKE_API_KEY, master_key):
        assert secret.encode() not in dump
    assert b"postgresql://" not in dump
    assert str(connection_id).encode() in dump  # references are fine, never credentials


async def test_undecryptable_credentials_degrade_instead_of_crashing(
    app_engine: AsyncEngine, owner: psycopg.Connection, migrated_db: str, target: dict[str, Any]
) -> None:
    user_id = uuid.uuid4()
    connection_id = await _connection(app_engine, user_id, target)  # sealed with SETTINGS
    run_id = await create_run(
        app_engine, modes=("live_inspection",), user_id=user_id, connection_id=connection_id
    )
    svc = services(app_engine, migrated_db, RoleClient(happy_scripts()))
    svc.settings = Settings(_env_file=None, master_key=base64.b64encode(os.urandom(32)).decode())

    await execute_run(svc, run_id, attempt=1, reclaimed=False)

    assert run_row(owner, run_id) == ("completed", "unverified_recommendations", None)
    tool_error = owner.execute(
        "SELECT data->>'code' FROM evidence WHERE run_id = %s AND kind = 'tool_error'", (run_id,)
    ).fetchone()
    assert tool_error == ("CONFIGURATION_ERROR",)


async def test_daily_free_quota_stops_the_run_gracefully(
    app_engine: AsyncEngine, owner: psycopg.Connection, migrated_db: str
) -> None:
    from querycure.llm.rate_limit import DailyQuota, LlmGate, MinuteRateLimiter

    run_id = await create_run(app_engine)
    quota = DailyQuota(app_engine, limit=1)
    quota.limit = await quota.used_today() + 1  # exactly one free request left today
    svc = services(app_engine, migrated_db, RoleClient(happy_scripts()))
    svc.llm_gate = LlmGate(MinuteRateLimiter(100), quota)

    await execute_run(svc, run_id, attempt=1, reclaimed=False)

    assert run_row(owner, run_id) == ("completed", "inconclusive", None)
    body = report(owner, run_id)
    assert body["stop_reason"] == "budget_exhausted"
    assert body["partial"] is True
    assert any("free model requests are used up" in e["message"] for e in body["errors"])
