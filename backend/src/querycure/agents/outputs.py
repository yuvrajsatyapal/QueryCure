"""What agents return (LLM-facing drafts) and how each draft is checked against evidence.

Drafts accept any string as an evidence ID so that invented IDs reach the citation validator
(stripped and reported) rather than failing JSON validation and burning a repair attempt.
"""

from collections.abc import Mapping

from pydantic import BaseModel, ConfigDict, Field

from querycure.agents.citations import CitationReport, Claim, judge_claims
from querycure.domain.investigation import (
    Confidence,
    HypothesisCategory,
    Severity,
    VerificationMethod,
)


class Draft(BaseModel):
    model_config = ConfigDict(extra="forbid")


class FindingDraft(Draft):
    title: str = Field(min_length=1, max_length=200)
    detail: str = Field(min_length=1, max_length=2000)
    severity: Severity
    evidence_ids: list[str] = Field(max_length=20)


class AgentAnalysis(Draft):
    """Output of every analyst: a short summary plus cited findings."""

    summary: str = Field(max_length=600)
    findings: list[FindingDraft] = Field(max_length=12)


def judge_analysis(
    output: AgentAnalysis, evidence_kinds: Mapping[str, str]
) -> tuple[AgentAnalysis, CitationReport]:
    verdicts, report = judge_claims(
        [Claim(f"{f.title}. {f.detail}", f.evidence_ids) for f in output.findings],
        evidence_kinds,
    )
    kept = [
        f.model_copy(update={"evidence_ids": v.valid_ids})
        for f, v in zip(output.findings, verdicts, strict=True)
        if v.keep
    ]
    return output.model_copy(update={"findings": kept}), report


class HypothesisDraft(Draft):
    statement: str = Field(min_length=1, max_length=1000)
    category: HypothesisCategory
    supporting_evidence: list[str] = Field(max_length=20)
    contradicting_evidence: list[str] = Field(default_factory=list, max_length=20)
    confidence: Confidence
    uncertainty_notes: str = Field(max_length=1000)
    verification_method: VerificationMethod


class HypothesisSet(Draft):
    """Supervisor synthesis. Ordered most likely first; disagreements stay separate."""

    hypotheses: list[HypothesisDraft] = Field(max_length=8)
    summary: str = Field(max_length=600)


def judge_hypotheses(
    output: HypothesisSet, evidence_kinds: Mapping[str, str]
) -> tuple[HypothesisSet, CitationReport]:
    verdicts, report = judge_claims(
        [Claim(h.statement, h.supporting_evidence) for h in output.hypotheses], evidence_kinds
    )
    kept = [
        h.model_copy(
            update={
                "supporting_evidence": v.valid_ids,
                "contradicting_evidence": [
                    i for i in dict.fromkeys(h.contradicting_evidence) if i in evidence_kinds
                ],
            }
        )
        for h, v in zip(output.hypotheses, verdicts, strict=True)
        if v.keep
    ]
    return output.model_copy(update={"hypotheses": kept}), report
