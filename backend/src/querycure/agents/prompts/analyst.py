"""Message layout shared by the three tool-using analysts."""

from querycure.agents.fencing import Fence
from querycure.agents.prompts.common import system_prompt
from querycure.llm.types import ChatMessage

PROTOCOL = (
    "Work in turns. Each reply is exactly one JSON object, either a tool request "
    '{{"action": "call_tool", "tool": "<name>", "args": {{...}}}} or your final answer '
    '{{"action": "final", "analysis": {{"summary": "...", "findings": [{{"title": "...", '
    '"detail": "...", "severity": "info|low|medium|high", "evidence_ids": ["ev_..."]}}]}}}}. '
    "Call a tool only when the evidence block lacks something you need; you may make at most "
    "{max_tools} tool calls. Tool results arrive as data blocks and their evidence IDs can be "
    "cited. Report findings, not fixes: do not write SQL."
)


def analyst_messages(
    *,
    role: str,
    task: str,
    objective: str,
    focus: list[str],
    sql: str | None,
    context_summary: str,
    tools: str,
    max_tools: int,
    fence: Fence,
) -> list[ChatMessage]:
    parts = ["User objective:\n" + fence.objective(objective)]
    if focus:
        # Focus points are supervisor (model) output: fenced like any derived text.
        parts.append("Supervisor focus:\n" + fence.block("focus", "\n".join(focus)))
    if sql is not None:
        parts.append("Query under investigation:\n" + fence.block("query", sql))
    parts.append("Evidence:\n" + fence.block("evidence", context_summary))
    parts.append("Available tools:\n" + tools)
    return [
        ChatMessage(
            role="system",
            content=system_prompt(role, task)
            + "\n\n# Protocol\n"
            + PROTOCOL.format(max_tools=max_tools),
        ),
        ChatMessage(role="user", content="\n\n".join(parts)),
    ]
