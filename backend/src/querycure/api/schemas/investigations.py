import datetime as dt
import uuid
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from querycure.domain.investigation import (
    Evidence,
    Finding,
    Hypothesis,
    JsonScalar,
    RunBudget,
)
from querycure.plans.metrics import NodeMetrics
from querycure.plans.models import PlanTree

Mode = Literal["offline", "live_inspection", "sandbox_benchmark"]
Sha256 = str


class Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


class ParamSet(Strict):
    name: str = Field(min_length=1, max_length=64, pattern=r"^[A-Za-z0-9_\-]+$")
    values: list[JsonScalar] = Field(max_length=100)
    edge_case: bool = False  # NULL-bearing or empty-result set (required to verify rewrites)


class LlmChoice(Strict):
    credential_id: uuid.UUID | None = None  # BYOK, Phase 5
    model: str | None = Field(default=None, max_length=100)


class CreateInvestigationRequest(Strict):
    title: str = Field(min_length=1, max_length=200)
    objective: str = Field(min_length=1, max_length=2000)
    modes: list[Mode] = Field(min_length=1, max_length=3)
    query: str | None = Field(default=None, max_length=100_000)
    param_sets: list[ParamSet] = Field(default_factory=list, max_length=20)
    connection_id: uuid.UUID | None = None
    workload_id: str | None = Field(default=None, max_length=200)
    plan_artifact_sha256: Sha256 | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")
    schema_artifact_sha256: Sha256 | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")
    llm: LlmChoice | None = None
    budget_profile: Literal["standard"] = "standard"
    pre_authorize_demo_sandbox: bool = False


class RunSummary(BaseModel):
    id: uuid.UUID
    investigation_id: uuid.UUID
    run_number: int
    kind: str
    status: str
    outcome: str | None
    created_at: dt.datetime
    started_at: dt.datetime | None
    finished_at: dt.datetime | None


class RunDetail(RunSummary):
    budget: RunBudget
    usage: dict[str, int]
    llm_provider: str | None
    llm_model: str | None
    error_code: str | None
    last_event_seq: int
    cancel_requested_at: dt.datetime | None


class InvestigationSummary(BaseModel):
    id: uuid.UUID
    title: str
    objective: str
    modes: list[str]
    created_at: dt.datetime
    latest_run: RunSummary | None


class InvestigationDetail(InvestigationSummary):
    connection_id: uuid.UUID | None
    workload_id: str | None
    runs: list[RunSummary]


class InvestigationPage(BaseModel):
    items: list[InvestigationSummary]
    next_cursor: str | None


class CreateInvestigationResponse(BaseModel):
    investigation: InvestigationDetail
    run: RunDetail


class FindingOut(Finding):
    key: str


class FindingsResponse(BaseModel):
    findings: list[FindingOut]
    hypotheses: list[Hypothesis]


class ArtifactRefOut(BaseModel):
    sha256: str
    kind: str


class EvidenceDetail(BaseModel):
    evidence: Evidence
    artifact: ArtifactRefOut | None
    cited_by_findings: list[str]
    cited_by_hypotheses: list[str]


class RunPlan(BaseModel):
    sha256: str
    kind: str
    role: str
    plan: PlanTree
    metrics: list[NodeMetrics]


class RunPlanList(BaseModel):
    items: list[RunPlan]


class ModelsResponse(BaseModel):
    provider: str
    model: str
    fallback_model: str | None
    configured: bool


def run_detail(row: Any) -> RunDetail:
    error = row.error or {}
    return RunDetail(
        id=row.id,
        investigation_id=row.investigation_id,
        run_number=row.run_number,
        kind=row.kind,
        status=row.status,
        outcome=row.outcome,
        created_at=row.created_at,
        started_at=row.started_at,
        finished_at=row.finished_at,
        budget=RunBudget.model_validate(row.budget),
        usage={k: int(v) for k, v in (row.usage or {}).items()},
        llm_provider=row.llm_provider,
        llm_model=row.llm_model,
        error_code=error.get("code"),
        last_event_seq=row.last_event_seq,
        cancel_requested_at=row.cancel_requested_at,
    )


class ReinvestigateRequest(Strict):
    """A new LLM run on the same inputs (REPLAY_ENGINE §1 "AI re-investigation"). The flag is
    the caller's explicit consent to new model calls: replays never make any."""

    confirm_new_llm_run: Literal[True]
