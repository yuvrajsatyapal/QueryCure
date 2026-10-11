"""intake + collect_context (T2.6) against the metadata DB (as qc_app) and a seeded target."""

import base64
import os
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import psycopg
import pytest
from langgraph.runtime import Runtime
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine

from querycure.agents.budgets import BudgetGuard, default_budget
from querycure.agents.nodes.collect_context import collect_context
from querycure.agents.nodes.intake import intake
from querycure.agents.runtime import RunContext
from querycure.agents.services import GatewayInspectorFactory
from querycure.agents.state import InvestigationState
from querycure.connectors.credentials import connection_aad, secret_box
from querycure.core.config import Profile, Settings
from querycure.db.repositories.connections import insert_connection
from querycure.events.emitter import RunEventSink
from querycure.replay import artifact_store as store

pytestmark = pytest.mark.integration

PLANS = Path(__file__).parents[1] / "fixtures" / "plans"
SQL = "SELECT * FROM orders WHERE customer_id = $1 ORDER BY created_at DESC LIMIT 20"
SETTINGS = Settings(_env_file=None, master_key=base64.b64encode(os.urandom(32)).decode())


@dataclass
class Run:
    id: uuid.UUID
    user_id: uuid.UUID
    ctx: RunContext


async def make_run(
    engine: AsyncEngine,
    *,
    modes: tuple[str, ...] = ("offline",),
    sql: str | None = SQL,
    plan: str | None = "pg17_canonical_hot_analyze.json",
    connection_id: uuid.UUID | None = None,
    user_id: uuid.UUID | None = None,
) -> Run:
    user_id = user_id or uuid.uuid4()
    async with engine.begin() as conn:
        inv = (
            await conn.execute(
                text(
                    "INSERT INTO investigations (user_id, title, objective, modes, connection_id) "
                    "VALUES (:u, 't', 'Why is this slow?', :modes, :c) RETURNING id"
                ),
                {"u": user_id, "modes": list(modes), "c": connection_id},
            )
        ).scalar_one()
        run_id: uuid.UUID = (
            await conn.execute(
                text(
                    "INSERT INTO investigation_runs (investigation_id, run_number, kind, status, "
                    "budget, usage, started_at) "
                    "VALUES (:inv, 1, 'initial', 'running', '{}', '{}', now()) RETURNING id"
                ),
                {"inv": inv},
            )
        ).scalar_one()
        if sql is not None:
            art = await store.store_raw_sql(conn, sql)
            await store.link(conn, run_id=run_id, artifact_id=art.id, role="input.query")
        if plan is not None:
            art = await store.store_json(conn, kind="plan_analyze", value=_load_json(PLANS / plan))
            await store.link(conn, run_id=run_id, artifact_id=art.id, role="input.plan")
    ctx = RunContext(
        run_id=run_id,
        guard=BudgetGuard(engine, run_id, default_budget(Profile.LOCAL)),
        events=RunEventSink(engine, run_id),
        engine=engine,
        inspectors=GatewayInspectorFactory(engine, SETTINGS, user_id),
    )
    return Run(run_id, user_id, ctx)


def _load_json(path: Path) -> Any:
    import json

    return json.loads(path.read_text())


async def run_nodes(run: Run) -> InvestigationState:
    runtime = Runtime(context=run.ctx)
    state: dict[str, Any] = {}
    for node in (intake, collect_context):
        update = await node(state, runtime)  # type: ignore[arg-type]
        for key, value in update.items():
            if key in ("evidence_ids", "errors"):
                state[key] = state.get(key, []) + value
            else:
                state[key] = value
    return state  # type: ignore[return-value]


def evidence_rows(owner: psycopg.Connection, run_id: uuid.UUID) -> list[tuple[Any, ...]]:
    return owner.execute(
        "SELECT e.id, e.kind, e.provenance, a.sha256 FROM evidence e "
        "LEFT JOIN artifacts a ON a.id = e.artifact_id WHERE e.run_id = %s ORDER BY e.id",
        (run_id,),
    ).fetchall()


def event_types(owner: psycopg.Connection, run_id: uuid.UUID) -> list[str]:
    return [
        r[0]
        for r in owner.execute(
            "SELECT type FROM investigation_events WHERE run_id = %s ORDER BY seq", (run_id,)
        )
    ]


async def test_offline_run_builds_query_and_plan_evidence(
    app_engine: AsyncEngine, owner: psycopg.Connection
) -> None:
    run = await make_run(app_engine)

    state = await run_nodes(run)

    assert state.get("stop_reason") is None
    assert state["query"]["order_by"] == ["created_at DESC"]  # type: ignore[index]
    assert state["query"]["limit"] == 20  # type: ignore[index]
    rows = evidence_rows(owner, run.id)
    kinds = [r[1] for r in rows]
    assert kinds.count("query_fact") == 5
    assert kinds.count("plan_node") == 4
    assert {r[2] for r in rows if r[1] == "plan_node"} == {"imported"}
    assert all(r[3] is not None for r in rows)  # every row points at its source artifact
    assert sorted(state["evidence_ids"]) == sorted(r[0] for r in rows)
    assert "Seq Scan on orders" in state["context_summary"]
    assert "hottest node" in state["context_summary"]
    types = event_types(owner, run.id)
    assert types.count("evidence.created") == 2
    assert types[0] == "node.started"


async def test_rerunning_the_nodes_after_a_crash_adds_nothing(
    app_engine: AsyncEngine, owner: psycopg.Connection
) -> None:
    run = await make_run(app_engine)
    first = await run_nodes(run)
    rows_before = evidence_rows(owner, run.id)
    evidence_events_before = event_types(owner, run.id).count("evidence.created")

    second = await run_nodes(run)

    assert evidence_rows(owner, run.id) == rows_before
    assert event_types(owner, run.id).count("evidence.created") == evidence_events_before
    assert sorted(second["evidence_ids"]) == sorted(first["evidence_ids"])
    assert second["context_summary"] == first["context_summary"]


@pytest.mark.parametrize(
    ("kwargs", "message"),
    [
        ({"sql": "DELETE FROM orders"}, "DELETE"),
        ({"sql": None, "plan": None}, "Provide a query"),
        ({"modes": ("live_inspection",)}, "needs a connection"),
    ],
)
async def test_invalid_input_stops_the_run_without_evidence(
    app_engine: AsyncEngine, owner: psycopg.Connection, kwargs: dict[str, Any], message: str
) -> None:
    run = await make_run(app_engine, **kwargs)

    update = await intake({}, Runtime(context=run.ctx))  # type: ignore[arg-type]

    assert update["stop_reason"] == "invalid_input"
    assert any(message in e["message"] for e in update["errors"])
    assert evidence_rows(owner, run.id) == []
    assert "error" in event_types(owner, run.id)


async def _connection(
    engine: AsyncEngine,
    user_id: uuid.UUID,
    target: dict[str, Any],
    *,
    port: int | None = None,
    environment: str = "development",
) -> uuid.UUID:
    connection_id = uuid.uuid4()
    sealed = secret_box(SETTINGS).encrypt(
        target["password"], aad=connection_aad(connection_id, user_id)
    )
    async with engine.begin() as conn:
        await insert_connection(
            conn,
            id=connection_id,
            user_id=user_id,
            fields={
                "name": "target",
                "host": target["host"],
                "port": port or target["port"],
                "dbname": target["dbname"],
                "username": target["role"],
                "sslmode": "disable",
                "environment": environment,
                "purpose": "inspection",
            },
            sealed=sealed,
        )
    return connection_id


async def test_live_inspection_collects_measured_plan_and_statistics(
    app_engine: AsyncEngine, owner: psycopg.Connection, target: dict[str, Any]
) -> None:
    user_id = uuid.uuid4()
    connection_id = await _connection(app_engine, user_id, target)
    run = await make_run(
        app_engine,
        modes=("live_inspection",),
        plan=None,
        connection_id=connection_id,
        user_id=user_id,
    )

    state = await run_nodes(run)

    rows = evidence_rows(owner, run.id)
    kinds = {r[1] for r in rows}
    assert {"plan_summary", "plan_node", "table_stat", "column_stat", "index_def"} <= kinds
    assert {r[2] for r in rows if r[1] != "query_fact"} == {"measured"}
    assert state["capabilities"]["is_superuser"] is False  # type: ignore[index]
    assert "estimates only" in state["context_summary"]
    assert "orders_customer_id_idx" in state["context_summary"]
    roles = {
        r[0] for r in owner.execute("SELECT role FROM run_artifacts WHERE run_id = %s", (run.id,))
    }
    assert {"context.plan", "context.schema_snapshot"} <= roles
    # Numeric statistics only: the target's planted e-mail values never reach evidence.
    dumped = owner.execute(
        "SELECT string_agg(summary || data::text, ' ') FROM evidence WHERE run_id = %s",
        (run.id,),
    ).fetchone()
    assert dumped is not None
    assert "customer.example" not in dumped[0]


async def test_unreachable_target_degrades_to_tool_error_evidence(
    app_engine: AsyncEngine, owner: psycopg.Connection, target: dict[str, Any]
) -> None:
    user_id = uuid.uuid4()
    connection_id = await _connection(app_engine, user_id, target, port=1)
    run = await make_run(
        app_engine, modes=("live_inspection",), connection_id=connection_id, user_id=user_id
    )

    state = await run_nodes(run)

    assert state.get("stop_reason") is None  # the run continues on the uploaded plan
    rows = evidence_rows(owner, run.id)
    assert ("tool_error", "measured") in {(r[1], r[2]) for r in rows}
    assert "plan_node" in {r[1] for r in rows}
    assert "Live inspection step 'connect' failed" in state["context_summary"]


async def test_production_connection_is_not_explained_without_approval(
    app_engine: AsyncEngine, owner: psycopg.Connection, target: dict[str, Any]
) -> None:
    user_id = uuid.uuid4()
    connection_id = await _connection(app_engine, user_id, target, environment="production")
    run = await make_run(
        app_engine,
        modes=("live_inspection",),
        plan=None,
        connection_id=connection_id,
        user_id=user_id,
    )

    state = await run_nodes(run)

    assert "APPROVAL_REQUIRED" in state["context_summary"]
    assert "plan_node" not in {r[1] for r in evidence_rows(owner, run.id)}


async def test_another_users_connection_cannot_be_used(
    app_engine: AsyncEngine, owner: psycopg.Connection, target: dict[str, Any]
) -> None:
    connection_id = await _connection(app_engine, uuid.uuid4(), target)
    run = await make_run(
        app_engine, modes=("live_inspection",), plan=None, connection_id=connection_id
    )

    state = await run_nodes(run)

    assert "NOT_FOUND" in state["context_summary"]
    assert "plan_node" not in {r[1] for r in evidence_rows(owner, run.id)}
