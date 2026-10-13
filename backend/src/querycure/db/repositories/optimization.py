"""Candidates, approval requests, experiments and benchmark runs (Phase 3 tables).

Every relationship is checked here (ADR-0006: no foreign keys). Writes take the run's
finalization guard (`ensure_writable`) so a sealed run cannot gain content.
"""

import datetime as dt
import json
import uuid
from collections.abc import Sequence
from typing import Any

from pydantic import BaseModel, ConfigDict
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

from querycure.domain.optimization import (
    APPROVAL_TTL_SECONDS,
    ApprovalDecision,
    ApprovalPayload,
    ApprovalStatus,
    CandidateStatus,
    OptimizationCandidate,
)
from querycure.evidence.store import ensure_writable


async def insert_candidates(
    conn: AsyncConnection, run_id: uuid.UUID, candidates: Sequence[OptimizationCandidate]
) -> list[OptimizationCandidate]:
    """Idempotent by (run_id, key). Returns every candidate with its id (new or existing)."""
    if not candidates:
        return []
    await ensure_writable(conn, run_id)
    stored: list[OptimizationCandidate] = []
    for c in candidates:
        await conn.execute(
            text(
                "INSERT INTO optimization_candidates (run_id, key, round, kind, "
                "addresses_hypotheses, ddl, query_sql, sql_sha256, rollback_sql, "
                "expected_benefit, risks, estimated_cost, proposed_by, status) VALUES "
                "(:run_id, :key, :round, :kind, :addresses, :ddl, :query_sql, :sha, :rollback, "
                ":benefit, :risks, CAST(:cost AS JSONB), :proposed_by, :status) "
                "ON CONFLICT (run_id, key) DO NOTHING"
            ),
            {
                "run_id": run_id,
                "key": c.key,
                "round": c.round,
                "kind": c.kind,
                "addresses": list(c.addresses_hypotheses),
                "ddl": list(c.ddl),
                "query_sql": c.query_sql,
                "sha": c.sql_sha256,
                "rollback": c.rollback_sql,
                "benefit": c.expected_benefit,
                "risks": list(c.risks),
                "cost": c.estimated_cost.model_dump_json(),
                "proposed_by": c.proposed_by,
                "status": c.status,
            },
        )
    keys = [c.key for c in candidates]
    by_key = {c.key: c for c in await list_candidates(conn, run_id) if c.key in keys}
    for key in keys:
        stored.append(by_key[key])
    return stored


_CANDIDATE_COLUMNS = (
    "id, key, round, kind, addresses_hypotheses, ddl, query_sql, sql_sha256, rollback_sql, "
    "expected_benefit, risks, estimated_cost, proposed_by, status, verdict_reasons"
)


def _candidate(row: Any) -> OptimizationCandidate:
    data = dict(row._mapping)
    return OptimizationCandidate.model_validate(data)


async def list_candidates(
    conn: AsyncConnection, run_id: uuid.UUID, *, round: int | None = None
) -> list[OptimizationCandidate]:
    rows = await conn.execute(
        text(
            f"SELECT {_CANDIDATE_COLUMNS} FROM optimization_candidates "  # noqa: S608
            "WHERE run_id = :run_id AND deleted_at IS NULL "
            "AND (CAST(:round AS INT) IS NULL OR round = :round) ORDER BY round, created_at, key"
        ),
        {"run_id": run_id, "round": round},
    )
    return [_candidate(r) for r in rows]


async def set_candidate_status(
    conn: AsyncConnection,
    run_id: uuid.UUID,
    candidate_ids: Sequence[uuid.UUID],
    status: CandidateStatus,
    *,
    reasons: list[dict[str, str]] | None = None,
) -> None:
    if not candidate_ids:
        return
    await ensure_writable(conn, run_id)
    await conn.execute(
        text(
            "UPDATE optimization_candidates SET status = :status, "
            "verdict_reasons = COALESCE(CAST(:reasons AS JSONB), verdict_reasons) "
            "WHERE run_id = :run_id AND id = ANY(:ids)"
        ),
        {
            "run_id": run_id,
            "ids": list(candidate_ids),
            "status": status,
            "reasons": None if reasons is None else json.dumps(reasons),
        },
    )


class ApprovalRow(BaseModel):
    model_config = ConfigDict(frozen=True)

    id: uuid.UUID
    run_id: uuid.UUID
    user_id: uuid.UUID
    round: int
    kind: str
    payload: ApprovalPayload
    status: ApprovalStatus
    decided_by: str | None
    decided_at: dt.datetime | None
    expires_at: dt.datetime
    decision: ApprovalDecision | None
    created_at: dt.datetime


_APPROVAL_COLUMNS = (
    "id, run_id, user_id, round, kind, payload, status, decided_by, decided_at, expires_at, "
    "decision, created_at"
)


async def create_approval(
    conn: AsyncConnection,
    *,
    run_id: uuid.UUID,
    user_id: uuid.UUID,
    round: int,
    payload: ApprovalPayload,
    pre_authorized: bool,
) -> ApprovalRow:
    """One sandbox_execution approval per run and round (idempotent on node re-runs)."""
    await ensure_writable(conn, run_id)
    decision = (
        ApprovalDecision(
            approved_candidate_ids=[c.candidate_id for c in payload.candidates],
            comment="Pre-authorized for a demo workload when the investigation was created.",
        )
        if pre_authorized
        else None
    )
    await conn.execute(
        text(
            "INSERT INTO approval_requests (run_id, user_id, round, kind, payload, status, "
            "decided_by, decided_at, expires_at, decision) VALUES (:run_id, :user_id, :round, "
            "'sandbox_execution', CAST(:payload AS JSONB), :status, :decided_by, "
            "CASE WHEN :pre THEN now() END, now() + make_interval(secs => :ttl), "
            "CAST(:decision AS JSONB)) ON CONFLICT (run_id, round, kind) DO NOTHING"
        ),
        {
            "run_id": run_id,
            "user_id": user_id,
            "round": round,
            "payload": payload.model_dump_json(),
            "status": "approved" if pre_authorized else "pending",
            "decided_by": "pre_authorized" if pre_authorized else None,
            "pre": pre_authorized,
            "ttl": APPROVAL_TTL_SECONDS,
            "decision": None if decision is None else decision.model_dump_json(),
        },
    )
    row = await get_approval_for_round(conn, run_id, round)
    if row is None:  # pragma: no cover - inserted or existing above
        raise RuntimeError("approval row missing after insert")
    return row


def _approval(row: Any) -> ApprovalRow:
    return ApprovalRow.model_validate(dict(row._mapping))


async def get_approval_for_round(
    conn: AsyncConnection, run_id: uuid.UUID, round: int
) -> ApprovalRow | None:
    row = (
        await conn.execute(
            text(
                f"SELECT {_APPROVAL_COLUMNS} FROM approval_requests "  # noqa: S608
                "WHERE run_id = :run_id AND round = :round AND kind = 'sandbox_execution'"
            ),
            {"run_id": run_id, "round": round},
        )
    ).first()
    return None if row is None else _approval(row)


async def get_approval(
    conn: AsyncConnection, *, user_id: uuid.UUID, approval_id: uuid.UUID, for_update: bool = False
) -> ApprovalRow | None:
    """User-scoped: another user's approval is indistinguishable from a missing one (404)."""
    row = (
        await conn.execute(
            text(
                f"SELECT {_APPROVAL_COLUMNS} FROM approval_requests "  # noqa: S608
                "WHERE id = :id AND user_id = :user_id AND deleted_at IS NULL"
                + (" FOR UPDATE" if for_update else "")
            ),
            {"id": approval_id, "user_id": user_id},
        )
    ).first()
    return None if row is None else _approval(row)


async def list_approvals(conn: AsyncConnection, run_id: uuid.UUID) -> list[ApprovalRow]:
    rows = await conn.execute(
        text(
            f"SELECT {_APPROVAL_COLUMNS} FROM approval_requests "  # noqa: S608
            "WHERE run_id = :run_id AND deleted_at IS NULL ORDER BY round, created_at"
        ),
        {"run_id": run_id},
    )
    return [_approval(r) for r in rows]


async def decide_approval(
    conn: AsyncConnection,
    *,
    approval_id: uuid.UUID,
    status: ApprovalStatus,
    decided_by: str,
    decision: ApprovalDecision,
) -> bool:
    """Pending → decided, at most once. False when it was no longer pending."""
    updated = await conn.execute(
        text(
            "UPDATE approval_requests SET status = :status, decided_by = :decided_by, "
            "decided_at = now(), decision = CAST(:decision AS JSONB) "
            "WHERE id = :id AND status = 'pending'"
        ),
        {
            "id": approval_id,
            "status": status,
            "decided_by": decided_by,
            "decision": decision.model_dump_json(),
        },
    )
    return updated.rowcount == 1


async def expire_due_approvals(conn: AsyncConnection) -> list[tuple[uuid.UUID, uuid.UUID]]:
    """Pending approvals past `expires_at` → expired. Returns (approval_id, run_id) pairs."""
    rows = await conn.execute(
        text(
            "UPDATE approval_requests SET status = 'expired', decided_by = 'system', "
            'decided_at = now(), decision = \'{"approved_candidate_ids": [], '
            '"comment": "Approval expired."}\' '
            "WHERE status = 'pending' AND expires_at < now() "
            # A sealed run (e.g. cancelled while waiting) keeps its approval record as it was.
            "AND run_id IN (SELECT id FROM investigation_runs WHERE finalized_at IS NULL) "
            "RETURNING id, run_id"
        )
    )
    return [(r.id, r.run_id) for r in rows]


class ExperimentRow(BaseModel):
    model_config = ConfigDict(frozen=True)

    id: uuid.UUID
    run_id: uuid.UUID
    round: int
    replicate: int = 0
    kind: str
    status: str
    approval_request_id: uuid.UUID
    config_artifact_id: uuid.UUID
    result_artifact_id: uuid.UUID | None
    environment: dict[str, Any] | None
    environment_digest: str | None
    engine_version: str
    row_profile: str
    seed: int
    replication_artifact_id: uuid.UUID | None = None
    replay_of_experiment_id: uuid.UUID | None = None
    error: dict[str, Any] | None
    started_at: dt.datetime | None
    finished_at: dt.datetime | None
    created_at: dt.datetime


_EXPERIMENT_COLUMNS = (
    "id, run_id, round, replicate, kind, status, approval_request_id, config_artifact_id, "
    "result_artifact_id, environment, environment_digest, engine_version, row_profile, seed, "
    "replication_artifact_id, replay_of_experiment_id, error, started_at, finished_at, "
    "created_at"
)


async def create_experiment(
    conn: AsyncConnection,
    *,
    experiment_id: uuid.UUID,
    run_id: uuid.UUID,
    round: int,
    kind: str,
    approval_request_id: uuid.UUID,
    config_artifact_id: uuid.UUID,
    engine_version: str,
    row_profile: str,
    seed: int,
    replicate: int = 0,
    replay_of_experiment_id: uuid.UUID | None = None,
) -> ExperimentRow:
    await ensure_writable(conn, run_id)
    await conn.execute(
        text(
            "INSERT INTO experiments (id, run_id, round, replicate, kind, approval_request_id, "
            "config_artifact_id, engine_version, row_profile, seed, replay_of_experiment_id) "
            "VALUES (:id, :run_id, :round, :replicate, :kind, :approval, :config, :engine, "
            ":profile, :seed, :replay_of) "
            "ON CONFLICT DO NOTHING"
        ),
        {
            "id": experiment_id,
            "run_id": run_id,
            "round": round,
            "replicate": replicate,
            "kind": kind,
            "approval": approval_request_id,
            "config": config_artifact_id,
            "engine": engine_version,
            "profile": row_profile,
            "seed": seed,
            "replay_of": replay_of_experiment_id,
        },
    )
    row = await get_experiment_row(conn, experiment_id)
    if row is None:  # pragma: no cover
        raise RuntimeError("experiment row missing after insert")
    return row


def _experiment(row: Any) -> ExperimentRow:
    return ExperimentRow.model_validate(dict(row._mapping))


async def get_experiment_row(
    conn: AsyncConnection, experiment_id: uuid.UUID
) -> ExperimentRow | None:
    row = (
        await conn.execute(
            text(
                f"SELECT {_EXPERIMENT_COLUMNS} FROM experiments WHERE id = :id"  # noqa: S608
            ),
            {"id": experiment_id},
        )
    ).first()
    return None if row is None else _experiment(row)


async def get_user_experiment(
    conn: AsyncConnection, *, user_id: uuid.UUID, experiment_id: uuid.UUID
) -> ExperimentRow | None:
    row = (
        await conn.execute(
            text(
                f"SELECT e.{_EXPERIMENT_COLUMNS.replace(', ', ', e.')} FROM experiments e "  # noqa: S608
                "JOIN investigation_runs r ON r.id = e.run_id "
                "JOIN investigations i ON i.id = r.investigation_id "
                "WHERE e.id = :id AND i.user_id = :user_id AND e.deleted_at IS NULL"
            ),
            {"id": experiment_id, "user_id": user_id},
        )
    ).first()
    return None if row is None else _experiment(row)


async def list_experiments(conn: AsyncConnection, run_id: uuid.UUID) -> list[ExperimentRow]:
    rows = await conn.execute(
        text(
            f"SELECT {_EXPERIMENT_COLUMNS} FROM experiments "  # noqa: S608
            "WHERE run_id = :run_id AND deleted_at IS NULL ORDER BY round, replicate, created_at"
        ),
        {"run_id": run_id},
    )
    return [_experiment(r) for r in rows]


async def set_replication(
    conn: AsyncConnection, experiment_id: uuid.UUID, artifact_id: uuid.UUID
) -> None:
    """Attach replication verdicts (ADR-0019) to the round's approved experiment."""
    await conn.execute(
        text("UPDATE experiments SET replication_artifact_id = :a WHERE id = :id"),
        {"id": experiment_id, "a": artifact_id},
    )


async def update_experiment(
    conn: AsyncConnection,
    experiment_id: uuid.UUID,
    *,
    status: str | None = None,
    environment: dict[str, Any] | None = None,
    environment_digest: str | None = None,
    result_artifact_id: uuid.UUID | None = None,
    error: dict[str, Any] | None = None,
    started: bool = False,
    finished: bool = False,
) -> None:
    await conn.execute(
        text(
            "UPDATE experiments SET status = COALESCE(:status, status), "
            "environment = COALESCE(CAST(:env AS JSONB), environment), "
            "environment_digest = COALESCE(:env_digest, environment_digest), "
            "result_artifact_id = COALESCE(:result, result_artifact_id), "
            "error = COALESCE(CAST(:error AS JSONB), error), "
            "started_at = CASE WHEN :started THEN COALESCE(started_at, now()) ELSE started_at END, "
            "finished_at = CASE WHEN :finished THEN now() ELSE finished_at END "
            "WHERE id = :id"
        ),
        {
            "id": experiment_id,
            "status": status,
            "env": None if environment is None else json.dumps(environment),
            "env_digest": environment_digest,
            "result": result_artifact_id,
            "error": None if error is None else json.dumps(error),
            "started": started,
            "finished": finished,
        },
    )


_BLOCK_COLUMNS = (
    "candidate_id, arm, param_set, phase, block, latencies_ns, sample_errors, rows_returned, "
    "result_fingerprint, ordered_fingerprint, truncated, plan_artifact_id, buffers, "
    "index_size_bytes, index_build_ns, build_error, provenance"
)


async def insert_benchmark_run(
    conn: AsyncConnection, experiment_id: uuid.UUID, row: dict[str, Any]
) -> None:
    """Append-only; ON CONFLICT DO NOTHING makes a resumed block write a no-op."""
    await conn.execute(
        text(
            "INSERT INTO benchmark_runs (experiment_id, candidate_id, arm, param_set, phase, "
            "block, latencies_ns, sample_errors, rows_returned, result_fingerprint, "
            "ordered_fingerprint, truncated, plan_artifact_id, buffers, index_size_bytes, "
            "index_build_ns, build_error, provenance) VALUES (:experiment_id, :candidate_id, "
            ":arm, :param_set, :phase, :block, CAST(:latencies_ns AS JSONB), "
            "CAST(:sample_errors AS JSONB), :rows_returned, :result_fingerprint, "
            ":ordered_fingerprint, :truncated, :plan_artifact_id, CAST(:buffers AS JSONB), "
            ":index_size_bytes, :index_build_ns, CAST(:build_error AS JSONB), :provenance) "
            "ON CONFLICT (experiment_id, arm, param_set, phase, block) DO NOTHING"
        ),
        {
            "experiment_id": experiment_id,
            **row,
            "latencies_ns": json.dumps(row["latencies_ns"]),
            "sample_errors": json.dumps(row["sample_errors"]),
            "buffers": None if row["buffers"] is None else json.dumps(row["buffers"]),
            "build_error": None if row["build_error"] is None else json.dumps(row["build_error"]),
        },
    )


async def list_benchmark_runs(
    conn: AsyncConnection, experiment_id: uuid.UUID
) -> list[dict[str, Any]]:
    rows = await conn.execute(
        text(
            f"SELECT {_BLOCK_COLUMNS} FROM benchmark_runs "  # noqa: S608
            "WHERE experiment_id = :id ORDER BY phase, arm, param_set, block"
        ),
        {"id": experiment_id},
    )
    return [dict(r._mapping) for r in rows]
