"""Optimization Engineer prompt (AGENT_SYSTEM §2): propose sandbox-testable candidates."""

from querycure.agents.fencing import DATA_RULES, Fence
from querycure.domain.investigation import Hypothesis
from querycure.llm.types import ChatMessage

PROMPT_VERSION = "optimization_engineer@1"
ROLE_MARKER = "You are the Optimization Engineer"

ROLE = (
    f"{ROLE_MARKER} of a PostgreSQL performance investigation. You turn ranked hypotheses "
    "into concrete candidate changes that a deterministic benchmark will test in a disposable "
    "sandbox copy of the database, after a human approves the exact SQL. You never run SQL."
)

TASK = (
    "Propose up to {max_candidates} candidates for this round, each addressing one or more "
    "hypotheses by their keys (hy_...). Allowed kinds and forms:\n"
    "- create_index: 1-4 statements `CREATE INDEX [IF NOT EXISTS] [name] ON table [USING "
    "btree|hash|gin|gist|brin] (columns or expressions) [INCLUDE (columns)] [WHERE "
    "predicate]` on tables the query reads. No UNIQUE, no CONCURRENTLY, no storage options.\n"
    "- analyze_statistics: `ANALYZE table [(columns)]`.\n"
    "- extended_statistics: `CREATE STATISTICS [name] [(ndistinct, dependencies, mcv)] ON "
    "col1, col2 FROM table` followed by `ANALYZE table`.\n"
    "- query_rewrite: no DDL; `query` is one SELECT returning exactly the same rows as the "
    "original for every input, with the same $n parameters. Watch NULL semantics (NOT IN vs "
    "NOT EXISTS), duplicates, and ordering.\n"
    "Prefer the simplest change that could fix the top hypotheses; when hypotheses disagree, "
    "propose a candidate for each so the experiment can settle it. Never repeat a candidate "
    "listed under earlier rounds; use their verdicts to try something different, or return no "
    "candidates when nothing promising remains. Do not predict speed-ups: the benchmark "
    "measures them."
)

OUTPUT = (
    "Reply with one JSON object: "
    '{"candidates": [{"kind": "...", "addresses_hypotheses": ["hy_..."], "ddl": ["..."], '
    '"query": null, "expected_benefit": "...", "risks": ["..."], '
    '"write_overhead": "low|medium|high|unknown"}], "summary": "..."}'
)


def _hypothesis_lines(hypotheses: list[Hypothesis]) -> str:
    return "\n".join(
        f"- {h.key} rank {h.rank} [{h.category}] ({h.confidence}): {h.statement} "
        f"Uncertain: {h.uncertainty_notes} Verify by: {h.verification_method}"
        for h in hypotheses
    )


def messages(
    *,
    objective: str,
    sql: str,
    tables: list[str],
    hypotheses: list[Hypothesis],
    context_summary: str,
    earlier_rounds: list[str],
    max_candidates: int,
    fence: Fence,
) -> list[ChatMessage]:
    system = "\n\n".join(
        [
            f"# Role\n{ROLE}",
            f"# Task\n{TASK.format(max_candidates=max_candidates)}",
            f"# Output\n{OUTPUT}",
            f"# Data rules\n{DATA_RULES}",
        ]
    )
    parts = [
        "User objective:\n" + fence.objective(objective),
        "Query under investigation:\n" + fence.block("query", sql),
        "Tables the query reads: " + (", ".join(tables) or "(none)"),
        # Hypotheses are model output derived from untrusted data: fenced as well.
        "Hypotheses:\n" + fence.block("hypotheses", _hypothesis_lines(hypotheses) or "(none)"),
        "Evidence:\n" + fence.block("evidence", context_summary),
    ]
    if earlier_rounds:
        parts.append("Earlier rounds:\n" + fence.block("verdicts", "\n".join(earlier_rounds)))
    return [
        ChatMessage(role="system", content=system),
        ChatMessage(role="user", content="\n\n".join(parts)),
    ]
