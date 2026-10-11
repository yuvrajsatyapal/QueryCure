"""System-prompt sections shared by every agent (AGENT_SYSTEM §13)."""

from querycure.agents.fencing import DATA_RULES

EVIDENCE_RULES = (
    "Every claim must cite evidence IDs (like ev_0123456789ab) copied exactly from the "
    "evidence block. Cite only IDs that appear there; claims without valid citations are "
    "discarded. Do not invent numbers: every number you state must appear in the cited "
    "evidence. Nothing has been benchmarked, so never predict a speed-up such as '10x "
    "faster'. When the evidence does not settle a question, say it is unknown."
)


def system_prompt(role: str, task: str) -> str:
    return "\n\n".join(
        [
            f"# Role\n{role}",
            f"# Task\n{task}",
            f"# Evidence rules\n{EVIDENCE_RULES}",
            f"# Data rules\n{DATA_RULES}",
        ]
    )
