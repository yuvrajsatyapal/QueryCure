"""Domain models for investigations (AGENT_SYSTEM §4). Graph state stores their JSON dumps."""

from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, StringConstraints

JsonScalar = str | int | float | bool | None

AgentName = Literal[
    "supervisor",
    "query_analyzer",
    "index_strategist",
    "workload_investigator",
    "optimization_engineer",
]
ANALYST_AGENTS: tuple[AgentName, ...] = (
    "query_analyzer",
    "index_strategist",
    "workload_investigator",
)

EvidenceKind = Literal[
    "plan_node",
    "plan_summary",
    "table_stat",
    "column_stat",
    "index_def",
    "schema_fact",
    "query_fact",
    "workload_stat",
    "lock_sample",
    "benchmark_metric",
    "correctness_check",
    "tool_error",
    "user_input",
]
Provenance = Literal["measured", "prerecorded", "imported", "derived"]
Severity = Literal["info", "low", "medium", "high"]
Confidence = Literal["low", "medium", "high"]
HypothesisCategory = Literal[
    "missing_index",
    "poor_index_order",
    "cardinality_misestimate",
    "stale_statistics",
    "inefficient_sort",
    "join_strategy",
    "query_shape",
    "lock_contention",
    "io_pressure",
    "workload_change",
    "other",
]
VerificationMethod = Literal[
    "benchmark", "explain_compare", "stats_refresh", "workload_observation", "not_verifiable"
]
EvidenceId = Annotated[str, StringConstraints(pattern=r"^ev_[0-9a-f]{12}$")]
StopReason = Literal["budget_exhausted", "cancelled", "invalid_input", "failed"]


class Frozen(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")


class ArtifactRef(Frozen):
    sha256: str
    kind: str


class Evidence(Frozen):
    id: EvidenceId
    kind: EvidenceKind
    artifact_sha256: str | None
    locator: str
    summary: str = Field(max_length=300)
    data: dict[str, JsonScalar]
    provenance: Provenance


class Finding(Frozen):
    agent: AgentName
    title: str = Field(min_length=1, max_length=200)
    detail: str = Field(min_length=1, max_length=2000)
    severity: Severity
    evidence_ids: list[EvidenceId] = Field(min_length=1)


class Hypothesis(Frozen):
    key: Annotated[str, StringConstraints(pattern=r"^hy_[0-9a-f]{12}$")]
    rank: int = Field(ge=1)
    statement: str = Field(min_length=1, max_length=1000)
    category: HypothesisCategory
    supporting_evidence: list[EvidenceId] = Field(min_length=1)
    contradicting_evidence: list[EvidenceId] = []
    confidence: Confidence
    uncertainty_notes: str = Field(max_length=1000)
    verification_method: VerificationMethod
    proposed_by: list[AgentName] = Field(min_length=1)


class InvestigationPlan(Frozen):
    agents: list[Literal["query_analyzer", "index_strategist", "workload_investigator"]] = Field(
        min_length=1
    )
    focus: list[str] = Field(default_factory=list, max_length=8)
    rationale: str = Field(max_length=1000)


class NodeError(Frozen):
    node: str
    code: str
    message: str = Field(max_length=500)
    recoverable: bool


class RunBudget(Frozen):
    llm_calls: int = Field(ge=1)
    total_tokens: int = Field(ge=1)
    tool_calls: int = Field(ge=1)
    tool_calls_per_agent: int = Field(ge=1)
    wall_clock_seconds: int = Field(ge=1)
    # Phase 3 (AGENT_SYSTEM §11). Defaults keep Phase 2 budgets readable.
    candidates_per_round: int = Field(default=4, ge=1, le=4)
    max_optimization_rounds: int = Field(default=2, ge=0, le=5)  # extra rounds after the first
    benchmark_seconds: int = Field(default=8 * 60, ge=30)


class BudgetUsage(Frozen):
    llm_calls: int = 0
    input_tokens: int = 0
    output_tokens: int = 0
    tool_calls: int = 0

    @property
    def total_tokens(self) -> int:
        return self.input_tokens + self.output_tokens
