"""Everything a versioned report builder reads, loaded from persisted records (REPLAY_ENGINE §5).

The same loader runs inside `finalize_run` and again during report replay's rebuild check, so
a builder that is a pure function of `ReportInputs` rebuilds byte-identical JSON for as long as
the records stay sealed. Only records and events `1..cutoff_seq` are read; nothing mutable that
can change after finalization (run row usage, status) is used. The terminal decision comes from
the `run.concluded` content event that `finalize_run` writes before the cutoff.
"""

import json
import uuid
from dataclasses import dataclass, field
from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

from querycure.db.repositories.findings import list_findings, list_hypotheses
from querycure.db.repositories.optimization import (
    list_approvals,
    list_candidates,
    list_experiments,
)
from querycure.db.repositories.verification import list_verifications
from querycure.domain.investigation import Evidence, Finding, Hypothesis
from querycure.domain.optimization import OptimizationCandidate
from querycure.events.types import EventType
from querycure.evidence.store import list_evidence
from querycure.replay.artifact_store import get_artifact_by_id, load_json
from querycure.replay.canonical import to_canonical


@dataclass(frozen=True)
class ReportInputs:
    run: dict[str, Any]
    investigation: dict[str, Any]
    conclusion: dict[str, Any] | None
    errors: list[dict[str, Any]]
    query_sql: str | None
    query_sha256: str | None
    param_sets: list[dict[str, Any]] | None
    evidence: list[Evidence]
    findings: list[tuple[str, Finding]]
    hypotheses: list[Hypothesis]
    candidates: list[OptimizationCandidate]
    approvals: list[dict[str, Any]]
    experiments: list[dict[str, Any]]
    verifications: list[dict[str, Any]]
    llm_calls: list[dict[str, Any]]
    comparison: dict[str, Any] | None = None
    replay_of: dict[str, Any] | None = field(default=None)


async def _role(conn: AsyncConnection, run_id: uuid.UUID, role: str) -> Any:
    row = (
        await conn.execute(
            text(
                "SELECT a.id FROM run_artifacts ra JOIN artifacts a ON a.id = ra.artifact_id "
                "WHERE ra.run_id = :run AND ra.role = :role ORDER BY a.sha256 LIMIT 1"
            ),
            {"run": run_id, "role": role},
        )
    ).first()
    return None if row is None else await get_artifact_by_id(conn, row.id)


async def load_report_inputs(
    conn: AsyncConnection, run_id: uuid.UUID, cutoff_seq: int
) -> ReportInputs:
    run = (
        await conn.execute(
            text(
                "SELECT r.id, r.investigation_id, r.run_number, r.kind, r.parent_run_id, "
                "i.title, i.objective, i.modes, i.workload_id, i.connection_id "
                "FROM investigation_runs r JOIN investigations i ON i.id = r.investigation_id "
                "WHERE r.id = :id"
            ),
            {"id": run_id},
        )
    ).one()
    events = (
        await conn.execute(
            text(
                "SELECT type, payload FROM investigation_events WHERE run_id = :run "
                "AND seq <= :cutoff AND type IN ('run.concluded', 'error') ORDER BY seq"
            ),
            {"run": run_id, "cutoff": cutoff_seq},
        )
    ).all()
    concluded = [e.payload for e in events if e.type == EventType.RUN_CONCLUDED.value]
    query = await _role(conn, run_id, "input.query")
    param_sets = await _role(conn, run_id, "input.param_sets")
    experiments: list[dict[str, Any]] = []
    replay_of = None
    for e in await list_experiments(conn, run_id):
        config = await load_json(conn, e.config_artifact_id)
        result_art = (
            None if e.result_artifact_id is None
            else await get_artifact_by_id(conn, e.result_artifact_id)
        )  # fmt: skip
        replication = (
            None if e.replication_artifact_id is None
            else await load_json(conn, e.replication_artifact_id)
        )  # fmt: skip
        experiments.append(
            {
                "id": str(e.id),
                "round": e.round,
                "replicate": e.replicate,
                "status": e.status,
                "engine_version": e.engine_version,
                "row_profile": e.row_profile,
                "seed": e.seed,
                "environment": e.environment,
                "environment_digest": e.environment_digest,
                "replay_of_experiment_id": str(e.replay_of_experiment_id)
                if e.replay_of_experiment_id
                else None,
                "error": e.error,
                "config": config,
                "result": None if result_art is None else json.loads(result_art.content),
                "result_sha256": None if result_art is None else result_art.sha256,
                "replication": replication,
            }
        )
        if e.replay_of_experiment_id is not None:
            src = (
                await conn.execute(
                    text("SELECT run_id FROM experiments WHERE id = :id"),
                    {"id": e.replay_of_experiment_id},
                )
            ).scalar_one_or_none()
            replay_of = {
                "experiment_id": str(e.replay_of_experiment_id),
                "run_id": None if src is None else str(src),
            }
    comparison_art = await _role(conn, run_id, "replay.comparison")
    calls = (
        await conn.execute(
            text(
                "SELECT agent, coalesce(requested_model, model) AS model, served_by, "
                "prompt_version, status, count(*) AS calls FROM agent_executions "
                "WHERE run_id = :run GROUP BY 1, 2, 3, 4, 5 ORDER BY 1, 2, 3, 4, 5"
            ),
            {"run": run_id},
        )
    ).all()
    return ReportInputs(
        run={
            "id": str(run.id),
            "investigation_id": str(run.investigation_id),
            "run_number": run.run_number,
            "kind": run.kind,
            "parent_run_id": str(run.parent_run_id) if run.parent_run_id else None,
        },
        investigation={
            "title": run.title,
            "objective": run.objective,
            "modes": list(run.modes),
            "workload_id": run.workload_id,
            "live_connection": run.connection_id is not None,
        },
        conclusion=concluded[-1] if concluded else None,
        errors=[e.payload for e in events if e.type == EventType.ERROR.value],
        query_sql=None if query is None else query.content.decode("utf-8"),
        query_sha256=None if query is None else query.sha256,
        param_sets=None if param_sets is None else json.loads(param_sets.content),
        evidence=await list_evidence(conn, run_id),
        findings=await list_findings(conn, run_id),
        hypotheses=await list_hypotheses(conn, run_id),
        candidates=await list_candidates(conn, run_id),
        approvals=[
            to_canonical(
                {
                    "id": a.id,
                    "round": a.round,
                    "status": a.status,
                    "decided_by": a.decided_by,
                    "decided_at": a.decided_at,
                    "approved_candidate_ids": sorted(
                        str(i) for i in (a.decision.approved_candidate_ids if a.decision else [])
                    ),
                }
            )
            for a in await list_approvals(conn, run_id)
        ],
        experiments=experiments,
        verifications=[v.model_dump(mode="json") for v in await list_verifications(conn, run_id)],
        llm_calls=[
            {
                "agent": c.agent,
                "model": c.model,
                "served_by": c.served_by,
                "prompt_version": c.prompt_version,
                "status": c.status,
                "calls": int(c.calls),
            }
            for c in calls
        ],
        comparison=None if comparison_art is None else json.loads(comparison_art.content),
        replay_of=replay_of,
    )
