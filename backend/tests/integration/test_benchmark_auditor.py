"""Benchmark Auditor in the real graph (T4.2): scripted LLM, real metadata DB and sandbox.

The engine verdict on a laptop may be verified, verified with a noise warning, or
inconclusive (ADR-0018/0019), so assertions are written against `audited(engine_verdict, …)`
rather than a fixed verdict: the property under test is that the audit never upgrades and
that a cited downgrade concern lands exactly as ADR-0009 allows.
"""

import json
import uuid
from collections.abc import Sequence
from typing import Any

import psycopg
import pytest
from sqlalchemy.ext.asyncio import AsyncEngine

from querycure.agents.run import execute_run
from querycure.domain.audit import VERIFIED_VERDICTS, audited
from querycure.llm.structured import LLMError
from querycure.llm.types import ChatMessage
from querycure.sandbox.provisioner import SandboxProvisioner
from tests.fake_llm import RoleClient
from tests.integration.test_optimization_graph import (
    INDEX,
    NOTHING_MORE,
    candidates,
    create_sandbox_run,
    run_row,
    scripts,
    services,
)

pytestmark = pytest.mark.integration


def verifications(owner: psycopg.Connection, run_id: uuid.UUID) -> list[dict[str, Any]]:
    cur = owner.execute(
        "SELECT candidate_key, engine_verdict, verdict, checks, auditor_status, auditor_notes, "
        "auditor_concerns, auditor_downgraded, auditor_prompt_version FROM verification_results "
        "WHERE run_id = %s ORDER BY candidate_key",
        (run_id,),
    )
    names = [d.name for d in cur.description or []]
    return [dict(zip(names, r, strict=True)) for r in cur.fetchall()]


def downgrade_everything(messages: Sequence[ChatMessage]) -> str:
    prompt = "\n".join(m.content for m in messages)
    arm = prompt.split("- oc_", 1)[1][:12]
    metric = prompt.split("(benchmark_metric)", 1)[0].rsplit("[", 1)[1].rstrip("] ")
    return json.dumps(
        {
            "summary": "The speed-up rests on one synthetic customer distribution.",
            "concerns": [
                {
                    "arm": f"oc_{arm}",
                    "severity": "downgrade",
                    "text": "Measured only on a synthetic distribution; not trustworthy here.",
                    "evidence_ids": [metric],
                },
                {
                    "arm": f"oc_{arm}",
                    "severity": "downgrade",
                    "text": "An uncited concern is dropped.",
                    "evidence_ids": ["ev_000000000000"],
                },
            ],
        }
    )


async def run_to_end(
    engine: AsyncEngine, migrated_db: str, provisioner: SandboxProvisioner, auditor: list[Any]
) -> uuid.UUID:
    run_id = await create_sandbox_run(engine, pre_authorize=True)
    roles = scripts([candidates(INDEX), NOTHING_MORE])
    roles["benchmark_auditor"] = auditor
    client = RoleClient(roles)
    await execute_run(
        services(engine, migrated_db, client, provisioner), run_id, attempt=1, reclaimed=False
    )
    return run_id


async def test_audit_records_checks_and_never_upgrades(
    app_engine: AsyncEngine,
    owner: psycopg.Connection,
    migrated_db: str,
    provisioner: SandboxProvisioner,
) -> None:
    neutral = json.dumps({"summary": "No concerns beyond the checks.", "concerns": []})
    run_id = await run_to_end(app_engine, migrated_db, provisioner, [neutral, neutral])

    rows = verifications(owner, run_id)
    assert rows, "the auditor wrote no verification_results"
    first = rows[0]
    assert first["auditor_status"] == "completed"
    assert first["auditor_prompt_version"] == "benchmark_auditor@1"
    assert first["verdict"] == first["engine_verdict"]
    assert not first["auditor_downgraded"]
    checks = {c["name"]: c["status"] for c in first["checks"]}
    for name in ("rescore", "approval", "config", "environment", "provenance", "correctness"):
        assert checks[name] == "pass", (name, first["checks"])
    if first["engine_verdict"] in VERIFIED_VERDICTS:
        # A real composite index changes the plan: the auditor sees it used.
        assert checks["plan_change"] == "pass"
    status, outcome, _ = run_row(owner, run_id)
    assert status == "completed"
    assert (outcome == "verified_recommendation") == (first["verdict"] in VERIFIED_VERDICTS)


async def test_cited_downgrade_concern_moves_verified_to_inconclusive_only(
    app_engine: AsyncEngine,
    owner: psycopg.Connection,
    migrated_db: str,
    provisioner: SandboxProvisioner,
) -> None:
    run_id = await run_to_end(
        app_engine, migrated_db, provisioner, [downgrade_everything, downgrade_everything]
    )

    first = verifications(owner, run_id)[0]
    assert first["verdict"] == audited(first["engine_verdict"], doubt=True)
    assert first["auditor_downgraded"] == (first["engine_verdict"] in VERIFIED_VERDICTS)
    # Only the cited concern survives the citation check.
    assert len(first["auditor_concerns"]) == 1
    assert first["auditor_concerns"][0]["severity"] == "downgrade"
    status, outcome, _ = run_row(owner, run_id)
    assert status == "completed"
    assert outcome != "verified_recommendation"
    if first["auditor_downgraded"]:
        cand = owner.execute(
            "SELECT status, verdict_reasons FROM optimization_candidates WHERE run_id = %s "
            "AND round = 0",
            (run_id,),
        ).fetchone()
        assert cand is not None
        assert cand[0] == "inconclusive"
        assert any(r["code"] == "audit_downgrade" for r in cand[1])


async def test_failed_narrative_keeps_the_deterministic_audit(
    app_engine: AsyncEngine,
    owner: psycopg.Connection,
    migrated_db: str,
    provisioner: SandboxProvisioner,
) -> None:
    outage = LLMError("provider down")
    run_id = await run_to_end(app_engine, migrated_db, provisioner, [outage] * 8)

    first = verifications(owner, run_id)[0]
    assert first["auditor_status"] == "deterministic_only"
    assert first["verdict"] == first["engine_verdict"]
    assert "unavailable" in (first["auditor_notes"] or "")
    assert run_row(owner, run_id)[0] == "completed"
