"""Phase 3 API models: candidates, approvals, experiments (API_DESIGN §2)."""

import datetime as dt
import uuid
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from querycure.domain.benchmark import ExperimentResult, ReplicationResult
from querycure.domain.optimization import ApprovalPayload, OptimizationCandidate


class CandidateList(BaseModel):
    items: list[OptimizationCandidate]


class ApprovalOut(BaseModel):
    id: uuid.UUID
    run_id: uuid.UUID
    round: int
    kind: str
    status: str
    payload: ApprovalPayload
    decided_by: str | None
    decided_at: dt.datetime | None
    expires_at: dt.datetime
    approved_candidate_ids: list[uuid.UUID]
    comment: str
    created_at: dt.datetime


class ApprovalList(BaseModel):
    items: list[ApprovalOut]


class DecisionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    decision: Literal["approve", "decline", "partial"]
    candidate_ids: list[uuid.UUID] = Field(default_factory=list, max_length=10)
    comment: str = Field(default="", max_length=1000)


class ExperimentSummary(BaseModel):
    id: uuid.UUID
    run_id: uuid.UUID
    round: int
    replicate: int  # 0 = the approved experiment; > 0 = independent re-measurement (ADR-0019)
    kind: str
    status: str
    engine_version: str
    row_profile: str
    environment_digest: str | None
    started_at: dt.datetime | None
    finished_at: dt.datetime | None
    winner: str | None
    error_code: str | None
    # On replicate 0 of a noisy round: verdicts across the independent experiments.
    replication: ReplicationResult | None = None


class ExperimentList(BaseModel):
    items: list[ExperimentSummary]


class BlockOut(BaseModel):
    arm: str
    param_set: str
    phase: str
    block: int
    latencies_ns: list[int]
    sample_errors: list[str]
    rows_returned: int | None
    index_size_bytes: int | None
    index_build_ns: int | None
    plan_sha256: str | None


class ExperimentDetail(ExperimentSummary):
    environment: dict[str, Any] | None
    config: dict[str, Any] | None
    result: ExperimentResult | None
    blocks: list[BlockOut]
    provenance: Literal["measured", "prerecorded"] = "measured"
