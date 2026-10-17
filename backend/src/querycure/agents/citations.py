"""Mechanical citation checks applied to every agent output (AGENT_SYSTEM §5).

A claim is kept only if at least one cited evidence ID exists for this run. Unknown IDs are
stripped and reported. Speed-up numbers need benchmark evidence (none exists before Phase 3),
so "3x faster" style claims are removed. If more than half the claims are removed the agent
gets one retry with the problems listed; after that the remainder is accepted and logged.
"""

import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field

from querycure.evidence.sanitize import clean_text
from querycure.llm.types import ChatMessage

RETRY_THRESHOLD = 0.5
MAX_FEEDBACK_ITEMS = 20

_SPEEDUP = re.compile(
    r"\b\d+(?:\.\d+)?\s*(?:x|\u00d7|times)\s+(?:faster|slower|quicker|speed-?up)"
    r"|\b\d+(?:\.\d+)?\s*%\s+(?:faster|slower|quicker|speed-?up|less time"
    r"|reduction in (?:time|latency))"
    r"|\bspeed-?up of\s+\d",
    re.IGNORECASE,
)


@dataclass(frozen=True)
class Claim:
    text: str
    cited: Sequence[str]


@dataclass(frozen=True)
class ClaimVerdict:
    keep: bool
    valid_ids: list[str]
    problems: list[str]


@dataclass(frozen=True)
class CitationReport:
    total: int
    removed: int
    stripped_ids: int
    problems: list[str]
    # Deterministic grounding (agents/claims.py, ADR-0026): sentences or claims removed because
    # they contradict recorded evidence. Never part of the retry decision: the check is
    # deterministic, so a retry would only spend calls on the same filter.
    claims_removed: int = 0
    claim_problems: list[str] = field(default_factory=list)

    @property
    def removed_fraction(self) -> float:
        return self.removed / self.total if self.total else 0.0

    @property
    def needs_retry(self) -> bool:
        return self.removed_fraction > RETRY_THRESHOLD


def judge_claims(
    claims: Sequence[Claim], evidence_kinds: Mapping[str, str]
) -> tuple[list[ClaimVerdict], CitationReport]:
    verdicts: list[ClaimVerdict] = []
    problems: list[str] = []
    removed = stripped = 0
    for claim in claims:
        label = clean_text(claim.text, 80)
        claim_problems: list[str] = []
        valid = list(dict.fromkeys(i for i in claim.cited if i in evidence_kinds))
        unknown = [i for i in claim.cited if i not in evidence_kinds]
        if unknown:
            stripped += len(unknown)
            claim_problems.append(
                f'"{label}" cites evidence that does not exist: '
                + ", ".join(clean_text(i, 40) for i in unknown[:5])
            )
        keep = bool(valid)
        if not valid:
            claim_problems.append(f'"{label}" has no valid evidence citation')
        if (
            keep
            and _SPEEDUP.search(claim.text)
            and not any(evidence_kinds[i] == "benchmark_metric" for i in valid)
        ):
            keep = False
            claim_problems.append(
                f'"{label}" states a speed-up without benchmark evidence; nothing has been '
                "benchmarked, so do not quantify improvements"
            )
        if not keep:
            removed += 1
        problems += claim_problems
        verdicts.append(ClaimVerdict(keep=keep, valid_ids=valid, problems=claim_problems))
    return verdicts, CitationReport(
        total=len(claims), removed=removed, stripped_ids=stripped, problems=problems
    )


def feedback_message(report: CitationReport) -> ChatMessage:
    listed = "\n".join(f"- {p}" for p in report.problems[:MAX_FEEDBACK_ITEMS])
    return ChatMessage(
        role="user",
        content=(
            "Your previous answer had claims that could not be checked against the evidence:\n"
            f"{listed}\nCite only evidence IDs listed in the evidence block, keep every claim "
            "tied to at least one of them, and return the corrected JSON object."
        ),
    )
