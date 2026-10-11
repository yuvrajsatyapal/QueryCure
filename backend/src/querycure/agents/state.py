"""InvestigationState (AGENT_SYSTEM §4).

Values are JSON only (str/int/bool/None/lists/dicts): domain models are dumped on write and
validated on read. The checkpointer then never has to revive a Python class from database
content, and secrets can be ruled out by scanning plain JSON. References only: IDs, digests
and short summaries; never DSNs, keys, result rows, full plans or DDL.
"""

import operator
from typing import Annotated, Any, TypedDict

from querycure.domain.investigation import Finding, Hypothesis, InvestigationPlan, StopReason

Json = dict[str, Any]

# Higher wins when parallel branches stop for different reasons in the same step.
_STOP_PRIORITY: dict[str | None, int] = {
    None: 0,
    "invalid_input": 1,
    "budget_exhausted": 2,
    "failed": 3,
    "cancelled": 4,
}


def merge_stop_reason(current: StopReason | None, new: StopReason | None) -> StopReason | None:
    return current if _STOP_PRIORITY[current] >= _STOP_PRIORITY[new] else new


class InvestigationState(TypedDict, total=False):
    # identity & inputs (immutable after intake)
    investigation_id: str
    run_id: str
    objective: str
    modes: list[str]
    connection_id: str | None
    workload_id: str | None
    query_sql_sha256: str | None
    plan_sha256: str | None
    schema_sha256: str | None
    # context (refs + compact deterministic summaries)
    query: Json | None
    capabilities: Json | None
    context_summary: str
    evidence_ids: Annotated[list[str], operator.add]
    # reasoning
    plan: Json | None
    findings: Annotated[list[Json], operator.add]
    hypotheses: list[Json]
    synthesis_summary: str
    no_action_evidence: list[str]
    # control
    errors: Annotated[list[Json], operator.add]
    stop_reason: Annotated[StopReason | None, merge_stop_reason]
    outcome: str | None


def findings_of(state: InvestigationState) -> list[Finding]:
    return [Finding.model_validate(f) for f in state.get("findings", [])]


def hypotheses_of(state: InvestigationState) -> list[Hypothesis]:
    return [Hypothesis.model_validate(h) for h in state.get("hypotheses", [])]


def plan_of(state: InvestigationState) -> InvestigationPlan | None:
    raw = state.get("plan")
    return None if raw is None else InvestigationPlan.model_validate(raw)
