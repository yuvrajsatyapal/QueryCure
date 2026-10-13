"""Candidates, approvals and experiments (API_DESIGN §2, Phase 3).

Every read is scoped to the caller's runs; a foreign or unknown ID is a 404, never a 403.
The decision endpoint is the human-in-the-loop step: nothing reaches the sandbox until it
records an approval for exactly the SQL in the request (AGENT_SYSTEM §8, SECURITY §6.6).
"""

import json
import uuid
from typing import Any

from fastapi import APIRouter, status
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

from querycure.api.deps import ConnDep, CurrentUser
from querycure.api.schemas.optimization import (
    ApprovalList,
    ApprovalOut,
    BlockOut,
    CandidateList,
    DecisionRequest,
    ExperimentDetail,
    ExperimentList,
    ExperimentSummary,
)
from querycure.core.errors import InvalidStateError, NotFoundError, ValidationFailedError
from querycure.db.repositories import investigations
from querycure.db.repositories.optimization import (
    ApprovalRow,
    ExperimentRow,
    get_approval,
    get_user_experiment,
    list_approvals,
    list_benchmark_runs,
    list_candidates,
    list_experiments,
)
from querycure.domain.benchmark import ExperimentResult
from querycure.domain.optimization import ApprovalDecision, ApprovalStatus
from querycure.domain.users import User
from querycure.jobs.approvals import record_decision

router = APIRouter(tags=["optimization"])


async def _own_run(conn: AsyncConnection, user: User, run_id: uuid.UUID) -> None:
    if await investigations.get_run_row(conn, user_id=user.id, run_id=run_id) is None:
        raise NotFoundError("Run not found.")


def _approval_out(row: ApprovalRow) -> ApprovalOut:
    return ApprovalOut(
        id=row.id,
        run_id=row.run_id,
        round=row.round,
        kind=row.kind,
        status=row.status,
        payload=row.payload,
        decided_by=row.decided_by,
        decided_at=row.decided_at,
        expires_at=row.expires_at,
        approved_candidate_ids=row.decision.approved_candidate_ids if row.decision else [],
        comment=row.decision.comment if row.decision else "",
        created_at=row.created_at,
    )


async def _artifact_json(conn: AsyncConnection, artifact_id: uuid.UUID | None) -> Any:
    if artifact_id is None:
        return None
    content = (
        await conn.execute(
            text("SELECT content FROM artifacts WHERE id = :id"), {"id": artifact_id}
        )
    ).scalar_one_or_none()
    return None if content is None else json.loads(content)


async def _summary(conn: AsyncConnection, row: ExperimentRow) -> ExperimentSummary:
    result = await _artifact_json(conn, row.result_artifact_id)
    return ExperimentSummary(
        id=row.id,
        run_id=row.run_id,
        round=row.round,
        replicate=row.replicate,
        kind=row.kind,
        status=row.status,
        engine_version=row.engine_version,
        row_profile=row.row_profile,
        environment_digest=row.environment_digest,
        started_at=row.started_at,
        finished_at=row.finished_at,
        winner=(result or {}).get("winner"),
        error_code=(row.error or {}).get("code"),
        replication=await _artifact_json(conn, row.replication_artifact_id),
    )


@router.get("/runs/{run_id}/candidates")
async def run_candidates(run_id: uuid.UUID, conn: ConnDep, user: CurrentUser) -> CandidateList:
    await _own_run(conn, user, run_id)
    return CandidateList(items=await list_candidates(conn, run_id))


@router.get("/runs/{run_id}/approvals")
async def run_approvals(run_id: uuid.UUID, conn: ConnDep, user: CurrentUser) -> ApprovalList:
    await _own_run(conn, user, run_id)
    return ApprovalList(items=[_approval_out(a) for a in await list_approvals(conn, run_id)])


@router.post("/approvals/{approval_id}/decision", status_code=status.HTTP_202_ACCEPTED)
async def decide(
    approval_id: uuid.UUID, body: DecisionRequest, conn: ConnDep, user: CurrentUser
) -> ApprovalOut:
    row = await get_approval(conn, user_id=user.id, approval_id=approval_id, for_update=True)
    if row is None:
        raise NotFoundError("Approval not found.")
    if row.status != "pending":
        if row.status == "expired":
            raise InvalidStateError("This approval request has expired.")
        return _approval_out(row)  # already decided: idempotent, the first decision stands
    offered = [c.candidate_id for c in row.payload.candidates]
    if body.decision == "approve":
        approved = offered
    elif body.decision == "decline":
        approved = []
    else:
        unknown = [i for i in body.candidate_ids if i not in offered]
        if not body.candidate_ids or unknown:
            raise ValidationFailedError(
                "A partial approval names some of the offered candidates.",
                details=[{"field": "candidate_ids", "message": "must be a non-empty subset"}],
            )
        approved = [i for i in offered if i in body.candidate_ids]
    status_: ApprovalStatus = (
        "declined" if not approved else "approved" if approved == offered else "partially_approved"
    )
    decided = await record_decision(
        conn,
        row,
        status=status_,
        decided_by=f"user:{user.id}",
        decision=ApprovalDecision(approved_candidate_ids=approved, comment=body.comment),
    )
    if decided is None:
        raise InvalidStateError("This approval request was decided concurrently.")
    return _approval_out(decided)


@router.get("/runs/{run_id}/experiments")
async def run_experiments(run_id: uuid.UUID, conn: ConnDep, user: CurrentUser) -> ExperimentList:
    await _own_run(conn, user, run_id)
    return ExperimentList(
        items=[await _summary(conn, e) for e in await list_experiments(conn, run_id)]
    )


@router.get("/experiments/{experiment_id}")
async def experiment_detail(
    experiment_id: uuid.UUID, conn: ConnDep, user: CurrentUser
) -> ExperimentDetail:
    row = await get_user_experiment(conn, user_id=user.id, experiment_id=experiment_id)
    if row is None:
        raise NotFoundError("Experiment not found.")
    summary = await _summary(conn, row)
    result = await _artifact_json(conn, row.result_artifact_id)
    plans = {
        r.id: r.sha256
        for r in await conn.execute(
            text(
                "SELECT a.id, a.sha256 FROM benchmark_runs b JOIN artifacts a "
                "ON a.id = b.plan_artifact_id WHERE b.experiment_id = :id"
            ),
            {"id": experiment_id},
        )
    }
    blocks = [
        BlockOut(
            arm=b["arm"],
            param_set=b["param_set"],
            phase=b["phase"],
            block=b["block"],
            latencies_ns=list(b["latencies_ns"]),
            sample_errors=list(b["sample_errors"]),
            rows_returned=b["rows_returned"],
            index_size_bytes=b["index_size_bytes"],
            index_build_ns=b["index_build_ns"],
            plan_sha256=plans.get(b["plan_artifact_id"]) if b["plan_artifact_id"] else None,
        )
        for b in await list_benchmark_runs(conn, experiment_id)
    ]
    return ExperimentDetail(
        **summary.model_dump(),
        environment=row.environment,
        config=await _artifact_json(conn, row.config_artifact_id),
        result=None if result is None else ExperimentResult.model_validate(result),
        blocks=blocks,
    )
