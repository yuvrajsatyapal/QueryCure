"""Benchmark Auditor models (AGENT_SYSTEM §2, ADR-0009).

The auditor reviews an experiment *after* the deterministic engine. Its deterministic checks
can only find reasons to doubt a verified result; the LLM narrative can only add cited
concerns. Neither can upgrade: `audited_verdict` is the engine verdict or, after a verified /
verified-with-noise-warning engine verdict, `inconclusive`.
"""

import uuid
from typing import Literal

from pydantic import Field

from querycure.domain.benchmark import Frozen

FinalVerdict = Literal["verified", "verified_with_noise_warning", "rejected", "inconclusive"]
VERIFIED_VERDICTS: frozenset[str] = frozenset({"verified", "verified_with_noise_warning"})
AuditCheckName = Literal[
    "rescore",
    "approval",
    "config",
    "environment",
    "provenance",
    "samples",
    "param_sets",
    "dispersion",
    "correctness",
    "plan_change",
    "replication",
]
AuditStatus = Literal["pass", "warn", "fail", "skip"]
ConcernSeverity = Literal["info", "warning", "downgrade"]


class AuditCheck(Frozen):
    name: AuditCheckName
    status: AuditStatus
    detail: str = ""
    evidence_ids: list[str] = Field(default_factory=list)


class AuditConcern(Frozen):
    """A cited concern from the LLM narrative (validated, never a verdict source)."""

    arm: str
    severity: ConcernSeverity
    text: str = Field(max_length=600)
    evidence_ids: list[str] = Field(min_length=1)


class CandidateAudit(Frozen):
    arm: str
    candidate_id: uuid.UUID | None
    engine_verdict: FinalVerdict
    verdict: FinalVerdict  # after deterministic checks (and later the narrative)
    checks: list[AuditCheck]
    downgrade_reasons: list[str] = Field(default_factory=list)


class AuditAssessment(Frozen):
    schema_version: Literal[1] = 1
    experiment_id: uuid.UUID
    round: int
    engine_version: str
    candidates: list[CandidateAudit]
    winner: str | None  # first audited verified arm in tournament order


def audited(engine_verdict: FinalVerdict, *, doubt: bool) -> FinalVerdict:
    """The only verdict transition the auditor may make (ADR-0009, DB CHECK in 0011)."""
    if doubt and engine_verdict in VERIFIED_VERDICTS:
        return "inconclusive"
    return engine_verdict
