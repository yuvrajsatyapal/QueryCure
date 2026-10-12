"""Optimization candidates and approvals (AGENT_SYSTEM §4, §8; DATABASE_DESIGN §4)."""

import uuid
from typing import Annotated, Literal

from pydantic import Field, StringConstraints

from querycure.domain.benchmark import CandidateKind, Frozen, ReasonCode, WriteOverhead

CandidateKey = Annotated[str, StringConstraints(pattern=r"^oc_[0-9a-f]{12}$")]
HypothesisKey = Annotated[str, StringConstraints(pattern=r"^hy_[0-9a-f]{12}$")]
CandidateStatus = Literal[
    "proposed",
    "approved",
    "declined",
    "expired",
    "benchmarked",
    "verified",
    "rejected",
    "inconclusive",
]
ApprovalStatus = Literal["pending", "approved", "partially_approved", "declined", "expired"]
APPROVAL_TTL_SECONDS = 24 * 3600


class CandidateCost(Frozen):
    write_overhead: WriteOverhead = "unknown"
    index_size_estimate_bytes: int | None = None


class OptimizationCandidate(Frozen):
    id: uuid.UUID | None = None
    key: CandidateKey
    round: int = Field(ge=0)
    kind: CandidateKind
    addresses_hypotheses: list[HypothesisKey] = Field(min_length=1)
    ddl: list[str] = Field(max_length=4)
    query_sql: str | None
    sql_sha256: str  # engine.sql_digest of exactly what will run; pinned by the approval
    rollback_sql: str | None
    expected_benefit: str = Field(max_length=500)
    risks: list[str] = Field(max_length=5)
    estimated_cost: CandidateCost
    proposed_by: str = "optimization_engineer"
    status: CandidateStatus = "proposed"
    verdict_reasons: list[dict[str, str]] | None = None


class ApprovalCandidate(Frozen):
    """Exactly what the human sees and approves (SECURITY §6.6)."""

    candidate_id: uuid.UUID
    key: CandidateKey
    kind: CandidateKind
    ddl: list[str]
    query_sql: str | None
    sql_sha256: str
    expected_benefit: str
    risks: list[str]


class ApprovalPayload(Frozen):
    schema_version: Literal[1] = 1
    workload_id: str
    sandbox: str  # human-readable target: never a DSN
    baseline_query: str
    param_sets: list[dict[str, object]]
    candidates: list[ApprovalCandidate] = Field(min_length=1)


class ApprovalDecision(Frozen):
    approved_candidate_ids: list[uuid.UUID]
    comment: str = Field(default="", max_length=1000)


class CandidateVerdictReason(Frozen):
    code: ReasonCode | Literal["approval_declined", "approval_expired", "experiment_failed"]
    detail: str = ""
