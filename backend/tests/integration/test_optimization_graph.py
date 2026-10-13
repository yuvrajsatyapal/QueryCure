"""Mode C end to end (T3.9-T3.11): scripted LLM, real metadata DB, real sandbox PostgreSQL.

Covers ROADMAP Phase 3 acceptance #5 (no sandbox DDL without an approved approval_requests
row), the approval interrupt/resume, decline, expiry, pre-authorization, the bounded
optimization loop, and cancellation during measurement.
"""

import asyncio
import json
import re
import uuid
from collections.abc import Sequence
from typing import Any

import psycopg
import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine

from querycure.agents.run import RunServices, execute_run
from querycure.agents.runtime import LlmClients
from querycure.db.repositories.investigations import RunInputs
from querycure.db.repositories.optimization import get_approval_for_round
from querycure.domain.investigation import RunBudget
from querycure.domain.optimization import ApprovalDecision
from querycure.domain.runs import RunStatus
from querycure.events.emitter import change_status
from querycure.jobs.approvals import expire_approvals, record_decision
from querycure.llm.types import ChatMessage
from querycure.replay import artifact_store as store
from querycure.sandbox.provisioner import SandboxProvisioner
from tests.fake_llm import RoleClient, Step
from tests.integration.sandbox_fixtures import clone_names
from tests.integration.test_context_nodes import SETTINGS
from tests.integration.test_investigation_graph import (
    analyst_final,
    plan,
    report,
    run_row,
    statuses,
    synthesis,
)

pytestmark = pytest.mark.integration

ORDERS = "orders_ecommerce@v1:sf=0.1:seed=42"
RECENT = "SELECT * FROM orders WHERE customer_id = $1 ORDER BY created_at DESC LIMIT 20"
TRAP = "rewrite_trap@v1:sf=0.1:seed=42"
TRAP_SQL = (
    "SELECT count(*) FROM accounts "
    "WHERE region_code NOT IN (SELECT region_code FROM closed_regions)"
)
BUDGET = RunBudget(
    llm_calls=20,
    total_tokens=200_000,
    tool_calls=20,
    tool_calls_per_agent=6,
    wall_clock_seconds=600,
    max_optimization_rounds=1,
)
HY = re.compile(r"- (hy_[0-9a-f]{12}) rank")


def candidates(*items: dict[str, Any]) -> Step:
    """Optimization Engineer reply addressing the top hypothesis named in the prompt."""

    def step(messages: Sequence[ChatMessage]) -> str:
        match = HY.search("\n".join(m.content for m in messages))
        assert match is not None, "no hypothesis in the OE prompt"
        return json.dumps(
            {
                "candidates": [
                    {"addresses_hypotheses": [match.group(1)], "expected_benefit": "b", **c}
                    for c in items
                ],
                "summary": "proposal",
            }
        )

    return step


INDEX = {"kind": "create_index", "ddl": ["CREATE INDEX ON orders (customer_id, created_at)"]}
# A round-2 reply: on a noisy host round 1 can end inconclusive and the loop asks again.
NOTHING_MORE = json.dumps({"candidates": [], "summary": "Nothing else worth testing."})


def scripts(oe: list[Step], pattern: str = r"^Seq Scan on orders") -> dict[str, list[Step]]:
    return {
        "plan": [plan("query_analyzer")],
        "query_analyzer": [analyst_final(pattern, "Seq Scan dominates")],
        "synthesis": [synthesis("missing_index", pattern)],
        "optimization_engineer": oe,
    }


async def create_sandbox_run(
    engine: AsyncEngine,
    *,
    workload: str = ORDERS,
    sql: str = RECENT,
    pre_authorize: bool = False,
    budget: RunBudget = BUDGET,
) -> uuid.UUID:
    async with engine.begin() as conn:
        inv = (
            await conn.execute(
                text(
                    "INSERT INTO investigations (user_id, title, objective, modes, workload_id, "
                    "pre_authorize_sandbox) VALUES (:u, 't', 'Make the orders page fast', "
                    "ARRAY['sandbox_benchmark'], :w, :p) RETURNING id"
                ),
                {"u": uuid.uuid4(), "w": workload, "p": pre_authorize},
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
    return run_id


def services(
    engine: AsyncEngine, migrated_db: str, client: Any, sandbox: SandboxProvisioner
) -> RunServices:
    def clients(inputs: RunInputs) -> LlmClients:
        return LlmClients(primary=client)

    return RunServices(
        engine=engine,
        settings=SETTINGS,
        checkpoint_url=migrated_db,
        clients=clients,
        checkpoint_role="qc_app",
        sandbox=sandbox,
    )


def count(owner: psycopg.Connection, sql: str, *args: object) -> int:
    row = owner.execute(sql, args).fetchone()
    assert row is not None
    return int(row[0])


def candidate_rows(owner: psycopg.Connection, run_id: uuid.UUID) -> list[tuple[Any, ...]]:
    return [
        tuple(r)
        for r in owner.execute(
            "SELECT key, round, status, verdict_reasons FROM optimization_candidates "
            "WHERE run_id = %s ORDER BY round, key",
            (run_id,),
        )
    ]


async def decide(engine: AsyncEngine, run_id: uuid.UUID, *, approve: bool, round: int = 0) -> None:
    async with engine.begin() as conn:
        row = await get_approval_for_round(conn, run_id, round)
        assert row is not None
        ids = [c.candidate_id for c in row.payload.candidates] if approve else []
        decided = await record_decision(
            conn,
            row,
            status="approved" if approve else "declined",
            decided_by="user:test",
            decision=ApprovalDecision(approved_candidate_ids=ids),
        )
        assert decided is not None


async def test_no_sandbox_ddl_before_approval_then_approved_run_is_benchmarked(
    app_engine: AsyncEngine,
    owner: psycopg.Connection,
    migrated_db: str,
    provisioner: SandboxProvisioner,
) -> None:
    run_id = await create_sandbox_run(app_engine)
    client = RoleClient(scripts([candidates(INDEX), NOTHING_MORE]))
    svc = services(app_engine, migrated_db, client, provisioner)

    await execute_run(svc, run_id, attempt=1, reclaimed=False)

    # Acceptance #5: paused for a human, nothing executed in the sandbox.
    assert run_row(owner, run_id)[0] == "awaiting_approval"
    approval = owner.execute(
        "SELECT status, payload FROM approval_requests WHERE run_id = %s", (run_id,)
    ).fetchone()
    assert approval is not None
    assert approval[0] == "pending"
    assert approval[1]["candidates"][0]["ddl"] == INDEX["ddl"]
    assert count(owner, "SELECT count(*) FROM experiments WHERE run_id = %s", run_id) == 0
    runs_of_this_run = (
        "SELECT count(*) FROM benchmark_runs WHERE experiment_id IN "
        "(SELECT id FROM experiments WHERE run_id = %s)"
    )
    assert count(owner, runs_of_this_run, run_id) == 0
    assert clone_names() == []
    # Context came from a real (throwaway) sandbox clone, not an upload.
    assert (
        count(
            owner,
            "SELECT count(*) FROM evidence WHERE run_id = %s AND kind = 'plan_node' "
            "AND provenance = 'measured'",
            run_id,
        )
        > 0
    )

    await decide(app_engine, run_id, approve=True)
    assert run_row(owner, run_id)[0] == "queued"
    await execute_run(svc, run_id, attempt=1, reclaimed=False)

    status, outcome, _ = run_row(owner, run_id)
    assert status == "completed"
    ((_key, _, cand_status, reasons),) = candidate_rows(owner, run_id)
    replicates = count(
        owner, "SELECT count(*) FROM experiments WHERE run_id = %s AND replicate > 0", run_id
    )
    if outcome == "verified_recommendation":
        # Clean on the first experiment, or noisy and confirmed by 3 agreeing ones (ADR-0019).
        assert cand_status in ("verified", "verified_with_noise_warning")
        assert (cand_status == "verified_with_noise_warning") == (replicates == 2)
    else:  # the documented noisy-hardware outcome (ADR-0018/0019), never a rejection
        assert (outcome, cand_status) == ("inconclusive", "inconclusive")
        assert reasons[0]["code"] in ("insufficient_evidence", "replicates_disagree")
    assert replicates <= 2
    assert statuses(owner, run_id) == [
        "running", "awaiting_approval", "queued", "running", "completed"
    ]  # fmt: skip
    experiment = owner.execute(
        "SELECT status, environment->>'pg_version', engine_version, result_artifact_id "
        "FROM experiments WHERE run_id = %s AND replicate = 0",
        (run_id,),
    ).fetchone()
    assert experiment is not None
    assert experiment[0] == "completed"
    assert experiment[1].startswith("17")
    assert experiment[2] == "bench@2"
    assert experiment[3] is not None
    assert count(owner, runs_of_this_run + " AND phase = 'measure'", run_id) > 0
    assert (
        count(
            owner,
            "SELECT count(*) FROM evidence WHERE run_id = %s AND kind = 'benchmark_metric'",
            run_id,
        )
        == 2 * (1 + replicates)  # two param sets per experiment
    )
    body = report(owner, run_id)
    assert body["builder_version"] == ("interim-report@4" if replicates else "interim-report@3")
    if cand_status == "verified_with_noise_warning":
        assert body["verification"] == "verified_with_noise_warning"
        replication = body["optimization"]["rounds"][0]["experiment"]["replication"]
        assert replication["verdicts"][0]["verdict"] == "verified_with_noise_warning"
        assert len(replication["replicates"]) == 2
    assert body["optimization"]["rounds"][0]["experiment"]["status"] == "completed"
    assert clone_names() == []
    usage = owner.execute(
        "SELECT waiting_seconds FROM investigation_runs WHERE id = %s", (run_id,)
    ).fetchone()
    assert usage is not None
    assert usage[0] > 0


async def test_declined_approval_ends_with_unverified_recommendations(
    app_engine: AsyncEngine,
    owner: psycopg.Connection,
    migrated_db: str,
    provisioner: SandboxProvisioner,
) -> None:
    run_id = await create_sandbox_run(app_engine)
    svc = services(app_engine, migrated_db, RoleClient(scripts([candidates(INDEX)])), provisioner)
    await execute_run(svc, run_id, attempt=1, reclaimed=False)

    await decide(app_engine, run_id, approve=False)
    await execute_run(svc, run_id, attempt=1, reclaimed=False)

    assert run_row(owner, run_id)[:2] == ("completed", "unverified_recommendations")
    assert [r[2] for r in candidate_rows(owner, run_id)] == ["declined"]
    assert count(owner, "SELECT count(*) FROM experiments WHERE run_id = %s", run_id) == 0


async def test_expired_approval_ends_inconclusive(
    app_engine: AsyncEngine,
    owner: psycopg.Connection,
    migrated_db: str,
    provisioner: SandboxProvisioner,
) -> None:
    run_id = await create_sandbox_run(app_engine)
    svc = services(app_engine, migrated_db, RoleClient(scripts([candidates(INDEX)])), provisioner)
    await execute_run(svc, run_id, attempt=1, reclaimed=False)
    owner.execute(
        "UPDATE approval_requests SET expires_at = now() - interval '1 second' WHERE run_id = %s",
        (run_id,),
    )

    expired = await expire_approvals(app_engine)
    await execute_run(svc, run_id, attempt=1, reclaimed=False)

    assert len(expired) == 1
    assert run_row(owner, run_id)[:2] == ("completed", "inconclusive")
    assert [r[2] for r in candidate_rows(owner, run_id)] == ["expired"]
    assert count(owner, "SELECT count(*) FROM experiments WHERE run_id = %s", run_id) == 0


async def test_pre_authorized_demo_run_records_the_approval_and_runs_straight_through(
    app_engine: AsyncEngine,
    owner: psycopg.Connection,
    migrated_db: str,
    provisioner: SandboxProvisioner,
) -> None:
    run_id = await create_sandbox_run(app_engine, pre_authorize=True)
    client = RoleClient(scripts([candidates(INDEX), NOTHING_MORE]))
    svc = services(app_engine, migrated_db, client, provisioner)

    await execute_run(svc, run_id, attempt=1, reclaimed=False)

    assert run_row(owner, run_id)[0] == "completed"
    assert "awaiting_approval" not in statuses(owner, run_id)
    approval = owner.execute(
        "SELECT status, decided_by FROM approval_requests WHERE run_id = %s", (run_id,)
    ).fetchone()
    assert approval == ("approved", "pre_authorized")
    approved = "SELECT count(*) FROM experiments WHERE run_id = %s AND replicate = 0"
    assert count(owner, approved, run_id) == 1
    assert count(owner, "SELECT count(*) FROM experiments WHERE run_id = %s", run_id) <= 3


async def test_candidates_outside_the_policy_never_reach_approval(
    app_engine: AsyncEngine,
    owner: psycopg.Connection,
    migrated_db: str,
    provisioner: SandboxProvisioner,
) -> None:
    evil = {"kind": "create_index", "ddl": ["DROP TABLE orders"]}
    client = RoleClient(scripts([candidates(evil), candidates(evil)]))
    run_id = await create_sandbox_run(app_engine)

    await execute_run(
        services(app_engine, migrated_db, client, provisioner), run_id, attempt=1, reclaimed=False
    )

    assert run_row(owner, run_id)[:2] == ("completed", "unverified_recommendations")
    assert len(client.calls("optimization_engineer")) == 2  # one retry with the problems
    retry = "\n".join(m.content for m in client.calls("optimization_engineer")[1])
    assert "sandbox policy" in retry
    assert candidate_rows(owner, run_id) == []
    assert count(owner, "SELECT count(*) FROM approval_requests WHERE run_id = %s", run_id) == 0


async def test_semantics_changing_rewrite_is_rejected_and_the_loop_is_bounded(
    app_engine: AsyncEngine,
    owner: psycopg.Connection,
    migrated_db: str,
    provisioner: SandboxProvisioner,
) -> None:
    rewrite = {
        "kind": "query_rewrite",
        "query": "SELECT count(*) FROM accounts a WHERE NOT EXISTS "
        "(SELECT 1 FROM closed_regions c WHERE c.region_code = a.region_code)",
    }
    stats = {"kind": "analyze_statistics", "ddl": ["ANALYZE accounts"]}
    client = RoleClient(
        scripts([candidates(rewrite), candidates(stats)], pattern=r"^Seq Scan on accounts")
    )
    run_id = await create_sandbox_run(app_engine, workload=TRAP, sql=TRAP_SQL, pre_authorize=True)

    await execute_run(
        services(app_engine, migrated_db, client, provisioner), run_id, attempt=1, reclaimed=False
    )

    rows = candidate_rows(owner, run_id)
    assert (rows[0][1], rows[0][2]) == (0, "rejected")
    assert rows[0][3][0]["code"] == "result_mismatch"
    assert rows[1][1] == 1  # second round ran, then the round budget (1 extra) stopped the loop
    assert len(client.calls("optimization_engineer")) == 2
    round_two_prompt = "\n".join(m.content for m in client.calls("optimization_engineer")[1])
    assert "result_mismatch" in round_two_prompt  # rejection reasons fed back
    status, outcome, _ = run_row(owner, run_id)
    assert status == "completed"
    assert outcome in ("inconclusive", "verified_recommendation")
    approved = "SELECT count(*) FROM experiments WHERE run_id = %s AND replicate = 0"
    assert count(owner, approved, run_id) == 2  # one approved experiment per round


async def test_cancel_during_measurement_stops_and_leaves_no_clones(
    app_engine: AsyncEngine,
    owner: psycopg.Connection,
    migrated_db: str,
    provisioner: SandboxProvisioner,
) -> None:
    run_id = await create_sandbox_run(app_engine, pre_authorize=True)
    svc = services(app_engine, migrated_db, RoleClient(scripts([candidates(INDEX)])), provisioner)

    async def cancel_when_measuring() -> None:
        measured = (
            "SELECT count(*) FROM benchmark_runs WHERE phase = 'measure' "
            "AND experiment_id IN (SELECT id FROM experiments WHERE run_id = %s)"
        )
        async with asyncio.timeout(60):
            # Polls rows the worker thread writes; there is no in-process event to wait on.
            while count(owner, measured, run_id) == 0:  # noqa: ASYNC110
                await asyncio.sleep(0.05)
        async with app_engine.begin() as conn:
            await conn.execute(
                text("UPDATE investigation_runs SET cancel_requested_at = now() WHERE id = :id"),
                {"id": run_id},
            )
            await change_status(conn, run_id, RunStatus.CANCELLING)

    canceller = asyncio.create_task(cancel_when_measuring())
    await execute_run(svc, run_id, attempt=1, reclaimed=False)
    await canceller

    assert run_row(owner, run_id)[0] == "cancelled"
    assert owner.execute(
        "SELECT status FROM experiments WHERE run_id = %s", (run_id,)
    ).fetchone() == ("cancelled",)
    measured = count(
        owner,
        "SELECT count(*) FROM benchmark_runs WHERE phase = 'measure' AND experiment_id IN "
        "(SELECT id FROM experiments WHERE run_id = %s)",
        run_id,
    )
    assert measured < 24  # 2 arms x 2 param sets x 6 blocks when it would have finished
    assert clone_names() == []
