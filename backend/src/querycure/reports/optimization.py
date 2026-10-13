"""The optimization part of the interim report, read from persisted records only."""

import json
import uuid
from collections.abc import Sequence
from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

from querycure.db.repositories.optimization import (
    list_approvals,
    list_candidates,
    list_experiments,
)
from querycure.domain.investigation import Evidence


async def _winner(conn: AsyncConnection, artifact_id: uuid.UUID | None) -> str | None:
    if artifact_id is None:
        return None
    content = (
        await conn.execute(
            text("SELECT content FROM artifacts WHERE id = :id"), {"id": artifact_id}
        )
    ).scalar_one_or_none()
    if content is None:
        return None
    winner = json.loads(content).get("winner")
    return str(winner) if winner else None


async def _artifact(conn: AsyncConnection, artifact_id: uuid.UUID) -> tuple[str, Any] | None:
    row = (
        await conn.execute(
            text("SELECT sha256, content FROM artifacts WHERE id = :id"), {"id": artifact_id}
        )
    ).first()
    return None if row is None else (str(row.sha256), json.loads(row.content))


async def _replication(
    conn: AsyncConnection, primary: Any, replicates: Sequence[Any]
) -> dict[str, Any] | None:
    """ADR-0019: present only for rounds with replicate experiments (interim-report@4)."""
    if primary.replication_artifact_id is None and not replicates:
        return None
    verdicts: list[dict[str, Any]] = []
    winner = None
    if primary.replication_artifact_id is not None:
        stored = await _artifact(conn, primary.replication_artifact_id)
        if stored is not None:
            verdicts = stored[1]["verdicts"]
            winner = stored[1]["winner"]
    return {
        "replicates": [
            {
                "id": str(r.id),
                "replicate": r.replicate,
                "status": r.status,
                "seed": r.seed,
                "environment_digest": r.environment_digest,
            }
            for r in replicates
        ],
        "verdicts": verdicts,
        "winner": winner,
    }


async def optimization_section(
    conn: AsyncConnection, run_id: uuid.UUID, evidence: Sequence[Evidence]
) -> dict[str, Any] | None:
    candidates = await list_candidates(conn, run_id)
    if not candidates:
        return None
    approvals = {a.round: a for a in await list_approvals(conn, run_id)}
    all_experiments = await list_experiments(conn, run_id)
    experiments = {e.round: e for e in all_experiments if e.replicate == 0}
    replicates = {
        r: [e for e in all_experiments if e.round == r and e.replicate > 0] for r in experiments
    }
    metrics = [e for e in evidence if e.kind == "benchmark_metric"]
    rounds: list[dict[str, Any]] = []
    cited: list[str] = []
    verified = False
    noisy = False
    for round_ in sorted({c.round for c in candidates}):
        keys = {c.key for c in candidates if c.round == round_}
        approval = approvals.get(round_)
        experiment = experiments.get(round_)
        experiment_out: dict[str, Any] | None = None
        if experiment is not None:
            winner = await _winner(conn, experiment.result_artifact_id)
            replication = await _replication(conn, experiment, replicates.get(round_, []))
            if replication is not None and replication["winner"]:
                won = next(v for v in replication["verdicts"] if v["arm"] == replication["winner"])
                noisy = noisy or won["verdict"] == "verified_with_noise_warning"
                winner = winner or replication["winner"]
            verified = verified or winner is not None
            round_metrics = sorted(
                (m for m in metrics if m.data.get("arm") in keys), key=lambda m: m.locator
            )
            cited += [m.id for m in round_metrics]
            experiment_out = {
                "id": str(experiment.id),
                "status": experiment.status,
                "engine_version": experiment.engine_version,
                "row_profile": experiment.row_profile,
                "environment_digest": experiment.environment_digest,
                "seed": experiment.seed,
                "winner": winner,
                "metrics": [{"evidence_id": m.id, "summary": m.summary} for m in round_metrics],
            }
            if replication is not None:
                experiment_out = {**experiment_out, "replication": replication}
        rounds.append(
            {
                "round": round_,
                "approval": None
                if approval is None
                else {
                    "id": str(approval.id),
                    "status": approval.status,
                    "decided_by": approval.decided_by,
                },
                "candidates": [
                    {
                        "key": c.key,
                        "kind": c.kind,
                        "ddl": list(c.ddl),
                        "query_sql": c.query_sql,
                        "sql_sha256": c.sql_sha256,
                        "status": c.status,
                        "reasons": c.verdict_reasons,
                        "addresses_hypotheses": list(c.addresses_hypotheses),
                    }
                    for c in candidates
                    if c.round == round_
                ],
                "experiment": experiment_out,
            }
        )
    benchmarked = any(r["experiment"] is not None for r in rounds)
    return {
        "verification": ("verified_with_noise_warning" if noisy else "verified")
        if verified
        else ("not_verified" if benchmarked else "not_run"),
        "benchmarked": benchmarked,
        "rounds": rounds,
        "evidence_ids": cited,
    }
