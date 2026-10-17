"""What agents return (LLM-facing drafts) and how each draft is checked against evidence.

Drafts accept any string as an evidence ID so that invented IDs reach the citation validator
(stripped and reported) rather than failing JSON validation and burning a repair attempt.
"""

import dataclasses
from collections.abc import Mapping
from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field, RootModel

from querycure.agents.citations import CitationReport, Claim, judge_claims
from querycure.agents.claims import ClaimContext, Mode, filter_text
from querycure.domain.investigation import (
    Confidence,
    HypothesisCategory,
    Severity,
    VerificationMethod,
)


class Draft(BaseModel):
    model_config = ConfigDict(extra="forbid")


class _Grounding:
    """Collects what the deterministic claim checks removed from one output."""

    def __init__(self, claims: ClaimContext | None) -> None:
        self.claims = claims
        self.removed = 0
        self.problems: list[str] = []

    def text(self, text: str, mode: Mode = "fact") -> str:
        if self.claims is None or not text:
            return text
        out = filter_text(text, self.claims, mode=mode)
        self.problems += out.problems
        return out.text

    def drop(self) -> None:
        self.removed += 1

    def report(self, report: CitationReport) -> CitationReport:
        return dataclasses.replace(
            report, claims_removed=self.removed, claim_problems=self.problems
        )


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
    output: AgentAnalysis, evidence_kinds: Mapping[str, str], claims: ClaimContext | None = None
) -> tuple[AgentAnalysis, CitationReport]:
    verdicts, report = judge_claims(
        [Claim(f"{f.title}. {f.detail}", f.evidence_ids) for f in output.findings],
        evidence_kinds,
    )
    grounding = _Grounding(claims)
    kept = []
    for f, v in zip(output.findings, verdicts, strict=True):
        if not v.keep:
            continue
        title, detail = grounding.text(f.title), grounding.text(f.detail)
        if not title or not detail:
            grounding.drop()
            continue
        kept.append(
            f.model_copy(update={"evidence_ids": v.valid_ids, "title": title, "detail": detail})
        )
    summary = grounding.text(output.summary)
    cleaned = output.model_copy(update={"findings": kept, "summary": summary})
    return cleaned, grounding.report(report)


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
    # Only when no hypothesis is returned: evidence that the query is already efficient.
    no_action_evidence: list[str] = Field(default_factory=list, max_length=10)


def judge_hypotheses(
    output: HypothesisSet, evidence_kinds: Mapping[str, str], claims: ClaimContext | None = None
) -> tuple[HypothesisSet, CitationReport]:
    verdicts, report = judge_claims(
        [Claim(h.statement, h.supporting_evidence) for h in output.hypotheses], evidence_kinds
    )
    grounding = _Grounding(claims)
    kept = []
    for h, v in zip(output.hypotheses, verdicts, strict=True):
        if not v.keep:
            continue
        statement = grounding.text(h.statement, "hypothesis")
        if not statement:
            grounding.drop()
            continue
        kept.append(
            h.model_copy(
                update={
                    "statement": statement,
                    "uncertainty_notes": grounding.text(h.uncertainty_notes, "hypothesis"),
                    "supporting_evidence": v.valid_ids,
                    "contradicting_evidence": [
                        i for i in dict.fromkeys(h.contradicting_evidence) if i in evidence_kinds
                    ],
                }
            )
        )
    no_action = [i for i in dict.fromkeys(output.no_action_evidence) if i in evidence_kinds]
    cleaned = output.model_copy(
        update={
            "hypotheses": kept,
            "no_action_evidence": no_action,
            "summary": grounding.text(output.summary),
        }
    )
    return cleaned, grounding.report(report)


class ToolCallTurn(Draft):
    action: Literal["call_tool"]
    tool: str = Field(min_length=1, max_length=64)
    args: dict[str, Any] = Field(default_factory=dict)


class FinalTurn(Draft):
    action: Literal["final"]
    analysis: AgentAnalysis


class AgentTurn(RootModel[Annotated[ToolCallTurn | FinalTurn, Field(discriminator="action")]]):
    """One step of a tool-using analyst: request a tool, or give the final analysis."""


class CandidateDraft(Draft):
    """One proposed change. Only the SQL and the hypotheses it addresses are trusted after
    deterministic checks; prose is cleaned and never decides anything."""

    kind: Literal["create_index", "query_rewrite", "analyze_statistics", "extended_statistics"]
    addresses_hypotheses: list[str] = Field(max_length=8)
    ddl: list[str] = Field(default_factory=list, max_length=4)
    query: str | None = Field(default=None, max_length=20_000)
    expected_benefit: str = Field(max_length=500)
    risks: list[str] = Field(default_factory=list, max_length=5)
    write_overhead: Literal["low", "medium", "high", "unknown"] = "unknown"


class CandidateSet(Draft):
    """Output of the Optimization Engineer for one round."""

    candidates: list[CandidateDraft] = Field(max_length=6)
    summary: str = Field(max_length=600)


class ConcernDraft(Draft):
    """One cited concern about an experiment. `downgrade` asks to move a verified arm to
    inconclusive; nothing the auditor says can verify or reject anything (ADR-0009)."""

    arm: str = Field(min_length=1, max_length=40)
    severity: Literal["info", "warning", "downgrade"]
    text: str = Field(min_length=1, max_length=600)
    evidence_ids: list[str] = Field(max_length=12)


class AuditNarrative(Draft):
    """Output of the Benchmark Auditor for one round."""

    summary: str = Field(max_length=800)
    concerns: list[ConcernDraft] = Field(default_factory=list, max_length=12)


def judge_audit(
    output: AuditNarrative,
    evidence_kinds: Mapping[str, str],
    arms: frozenset[str],
    claims: ClaimContext | None = None,
) -> tuple[AuditNarrative, CitationReport]:
    """Concerns about unknown arms or without valid citations are dropped. Speed-up numbers
    need cited benchmark evidence like everywhere else, and every figure, status and
    recommendation must agree with the recorded measurements and verdicts (ADR-0026)."""
    verdicts, report = judge_claims(
        [Claim(c.text, c.evidence_ids) for c in output.concerns], evidence_kinds
    )
    grounding = _Grounding(claims)
    kept = []
    for c, v in zip(output.concerns, verdicts, strict=True):
        if not v.keep or c.arm not in arms:
            continue
        text = grounding.text(c.text)
        if not text:
            grounding.drop()
            continue
        kept.append(c.model_copy(update={"evidence_ids": v.valid_ids, "text": text}))
    cleaned = output.model_copy(
        update={"concerns": kept, "summary": grounding.text(output.summary)}
    )
    return cleaned, grounding.report(report)
