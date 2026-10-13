"""Load everything the Benchmark Auditor reads from persisted records (no sandbox, no LLM).

Artifacts are fetched through the digest-verifying store, so a corrupted config, result or
plan surfaces as an integrity error rather than as a quietly different audit.
"""

import uuid
from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

from querycure.audit.checks import ApprovalFacts, AuditInputs, CandidateFacts
from querycure.benchmark.engine import BlockRecord
from querycure.db.repositories.optimization import (
    ExperimentRow,
    get_approval_for_round,
    get_experiment_row,
    list_benchmark_runs,
    list_candidates,
    list_experiments,
)
from querycure.domain.benchmark import (
    EnvironmentFingerprint,
    ExperimentConfig,
    ExperimentResult,
    ReplicationResult,
)
from querycure.evidence.ids import evidence_id
from querycure.plans.models import PlanTree
from querycure.plans.parser import parse_plan
from querycure.replay.artifact_store import get_artifact_by_id, load_json


class AuditUnavailable(Exception):
    """The experiment has no stored result to audit (failed, cancelled or still running)."""


def _record(row: dict[str, Any]) -> BlockRecord:
    return BlockRecord(
        arm=row["arm"],
        candidate_id=str(row["candidate_id"]) if row["candidate_id"] else None,
        param_set=row["param_set"],
        phase=row["phase"],
        block=row["block"],
        latencies_ns=list(row["latencies_ns"]),
        sample_errors=list(row["sample_errors"]),
        rows_returned=row["rows_returned"],
        result_fingerprint=row["result_fingerprint"],
        ordered_fingerprint=row["ordered_fingerprint"],
        truncated=row["truncated"],
        buffers=row["buffers"],
        index_size_bytes=row["index_size_bytes"],
        index_build_ns=row["index_build_ns"],
        build_error=row["build_error"],
    )


async def _result(conn: AsyncConnection, experiment: ExperimentRow) -> tuple[ExperimentResult, str]:
    if experiment.status != "completed" or experiment.result_artifact_id is None:
        raise AuditUnavailable(f"experiment {experiment.id} is {experiment.status}")
    artifact = await get_artifact_by_id(conn, experiment.result_artifact_id)
    if artifact is None:
        raise AuditUnavailable("result artifact missing")
    return ExperimentResult.model_validate_json(artifact.content), artifact.sha256


async def load_audit_inputs(
    conn: AsyncConnection, run_id: uuid.UUID, experiment_id: uuid.UUID
) -> tuple[AuditInputs, str]:
    """(inputs, result artifact digest)."""
    experiment = await get_experiment_row(conn, experiment_id)
    if experiment is None or experiment.run_id != run_id:
        raise AuditUnavailable("experiment not found for this run")
    result, result_sha = await _result(conn, experiment)
    config = ExperimentConfig.model_validate(await load_json(conn, experiment.config_artifact_id))
    rows = await list_benchmark_runs(conn, experiment_id)
    plans: dict[tuple[str, str], PlanTree] = {}
    for row in rows:
        if row["phase"] == "plan" and row["plan_artifact_id"] is not None:
            plan = await get_artifact_by_id(conn, row["plan_artifact_id"])
            if plan is not None:
                plans[(row["arm"], row["param_set"])] = parse_plan(plan.content)
    approval = await get_approval_for_round(conn, run_id, experiment.round)
    candidates = {
        c.key: CandidateFacts(key=c.key, id=c.id, kind=c.kind, sql_sha256=c.sql_sha256)
        for c in await list_candidates(conn, run_id, round=experiment.round)
    }
    replication = None
    if experiment.replication_artifact_id is not None:
        replication = ReplicationResult.model_validate(
            await load_json(conn, experiment.replication_artifact_id)
        )
    replicates: list[tuple[ExperimentResult, str | None]] = []
    for other in await list_experiments(conn, run_id):
        if other.round == experiment.round and other.replicate > 0 and other.status == "completed":
            replicates.append(((await _result(conn, other))[0], other.environment_digest))
    existing = set(
        (
            await conn.execute(
                text(
                    "SELECT id FROM evidence WHERE run_id = :run AND kind IN "
                    "('benchmark_metric', 'correctness_check')"
                ),
                {"run": run_id},
            )
        ).scalars()
    )
    pairs = [(c.arm, p.name) for c in config.candidates for p in config.param_sets]

    def ids(kind: str, prefix: str) -> dict[tuple[str, str], str]:
        out = {}
        for arm, ps in pairs:
            eid = evidence_id(run_id, kind, result_sha, f"/{prefix}/{arm}/{ps}")
            if eid in existing:
                out[(arm, ps)] = eid
        return out

    env = experiment.environment
    return (
        AuditInputs(
            round=experiment.round,
            config=config,
            result=result,
            records=[_record(r) for r in rows],
            record_provenance=sorted({r["provenance"] for r in rows}),
            environment=EnvironmentFingerprint.model_validate(env) if env else None,
            environment_digest=experiment.environment_digest,
            approval=None
            if approval is None
            else ApprovalFacts(
                status=approval.status,
                approved_candidate_ids=frozenset(
                    approval.decision.approved_candidate_ids if approval.decision else []
                ),
                digests={c.key: c.sql_sha256 for c in approval.payload.candidates},
                baseline_query=approval.payload.baseline_query,
                param_sets=list(approval.payload.param_sets),
            ),
            candidates=candidates,
            replication=replication,
            replicates=replicates,
            plans=plans,
            metric_ids=ids("benchmark_metric", "stats"),
            correctness_ids=ids("correctness_check", "correctness"),
        ),
        result_sha,
    )
