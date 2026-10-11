"""Supervisor prompts: investigation planning and hypothesis synthesis."""

from querycure.agents.fencing import Fence
from querycure.agents.prompts.common import system_prompt
from querycure.domain.investigation import Finding
from querycure.llm.types import ChatMessage

PLAN_PROMPT_VERSION = "supervisor_plan@1"
SYNTHESIS_PROMPT_VERSION = "supervisor_synthesis@1"

ROLE = (
    "You are the supervisor of a PostgreSQL performance investigation. You coordinate "
    "specialist analysts; you never run SQL and you never talk to the database."
)

PLAN_TASK = (
    "Decide which analysts to run for this investigation. Available analysts: "
    "query_analyzer (reads the execution plan and query shape: scans, joins, sorts, row "
    "estimates), index_strategist (existing indexes versus the query's predicates and "
    "ordering), workload_investigator (database-wide statement, activity and I/O statistics). "
    "Choose only analysts listed as eligible. Give 1-4 short focus points that name the "
    "suspicious plan nodes or facts by their evidence IDs, and a one-paragraph rationale."
)

SYNTHESIS_TASK = (
    "Combine the analysts' findings into ranked hypotheses about the root cause, most likely "
    "first. Each hypothesis has one category, cites supporting evidence (and contradicting "
    "evidence when there is some), states its confidence and what remains uncertain, and "
    "names how it could be verified. When analysts disagree, keep each explanation as a "
    "separate hypothesis with its own confidence: disagreements are settled by experiments "
    "later, not by choosing now. Use high confidence only when the cited evidence directly "
    "shows the cause. If the evidence shows the query is already efficient, return no "
    "hypotheses and say so in the summary."
)


def plan_messages(
    *, objective: str, eligible: list[str], context_summary: str, fence: Fence
) -> list[ChatMessage]:
    return [
        ChatMessage(role="system", content=system_prompt(ROLE, PLAN_TASK)),
        ChatMessage(
            role="user",
            content="\n\n".join(
                [
                    "User objective:\n" + fence.objective(objective),
                    "Eligible analysts: " + ", ".join(eligible),
                    "Evidence:\n" + fence.block("evidence", context_summary),
                ]
            ),
        ),
    ]


def _finding_lines(findings: list[Finding]) -> str:
    return "\n".join(
        f"- [{f.agent}] ({f.severity}) {f.title}: {f.detail} cites {', '.join(f.evidence_ids)}"
        for f in findings
    )


def synthesis_messages(
    *, objective: str, findings: list[Finding], context_summary: str, fence: Fence
) -> list[ChatMessage]:
    return [
        ChatMessage(role="system", content=system_prompt(ROLE, SYNTHESIS_TASK)),
        ChatMessage(
            role="user",
            content="\n\n".join(
                [
                    "User objective:\n" + fence.objective(objective),
                    # Findings are model output derived from untrusted data: fenced as well.
                    "Analyst findings:\n"
                    + fence.block("findings", _finding_lines(findings) or "(none)"),
                    "Evidence:\n" + fence.block("evidence", context_summary),
                ]
            ),
        ),
    ]
