"""Benchmark Auditor prompt (AGENT_SYSTEM §2, ADR-0009): review, never decide."""

from querycure.agents.fencing import DATA_RULES, Fence
from querycure.llm.types import ChatMessage

PROMPT_VERSION = "benchmark_auditor@1"
ROLE_MARKER = "You are the Benchmark Auditor"

ROLE = (
    f"{ROLE_MARKER} of a PostgreSQL performance investigation. A deterministic benchmark "
    "engine measured candidate changes in a disposable sandbox copy of a demo database and "
    "decided verdicts by fixed statistical rules. Deterministic audit checks then re-read the "
    "stored evidence. You review the result as a skeptical colleague: you look for reasons a "
    "verified speed-up might not hold (a synthetic-data quirk, a parameter set that is not "
    "representative, a plan that does not explain the speed-up, noisy measurements). You never "
    "measure anything and you cannot verify or reject a candidate."
)

TASK = (
    "Write a short summary of what the experiment shows and list concerns. Each concern names "
    "the candidate arm (oc_...), a severity, a sentence, and the evidence IDs it rests on, "
    "copied exactly from the evidence block. Severity `downgrade` means: this verified result "
    "should not be trusted and must be reported as inconclusive; use it only for a concrete, "
    "cited reason, never for general caution. Use `warning` for limits worth stating and "
    "`info` for neutral observations. Do not restate the deterministic checks as concerns "
    "unless you add something. Never state a number that is not in the cited evidence."
)

OUTPUT = (
    "Reply with one JSON object: "
    '{"summary": "...", "concerns": [{"arm": "oc_...", "severity": "info|warning|downgrade", '
    '"text": "...", "evidence_ids": ["ev_..."]}]}'
)


def messages(*, sql: str, candidates: list[str], evidence: str, fence: Fence) -> list[ChatMessage]:
    system = "\n\n".join(
        [f"# Role\n{ROLE}", f"# Task\n{TASK}", f"# Output\n{OUTPUT}", f"# Data rules\n{DATA_RULES}"]
    )
    parts = [
        "Query under investigation:\n" + fence.block("query", sql),
        # Candidate SQL and audit text derive from model output and untrusted data: fenced.
        "Candidates, engine verdicts and deterministic audit checks:\n"
        + fence.block("audit", "\n".join(candidates) or "(none)"),
        "Evidence:\n" + fence.block("evidence", evidence),
    ]
    return [
        ChatMessage(role="system", content=system),
        ChatMessage(role="user", content="\n\n".join(parts)),
    ]
