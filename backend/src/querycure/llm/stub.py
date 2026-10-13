"""A deterministic, offline LLM for end-to-end UI tests (LLM_PROVIDER=stub, local profile only).

It answers each agent with fixed JSON that cites real evidence IDs taken from the prompt, so
the whole pipeline (citations, persistence, events, UI) runs without a model. Its output is
canned, is labelled `stub` in every record, and must never be presented as a diagnosis.
"""

import asyncio
import json
import re
from collections.abc import Sequence

from querycure.llm.types import ChatMessage, RawCompletion

STUB_MODEL = "stub/canned"
_EVIDENCE_LINE = re.compile(r"\[(ev_[0-9a-f]{12})\] \(([a-z_]+)\) ([^\n]*)")


def _first_evidence(text: str, prefer: Sequence[str]) -> str | None:
    """The first plan node matching the earliest pattern in `prefer`, else any evidence."""
    lines: list[tuple[str, str, str]] = _EVIDENCE_LINE.findall(text)
    for pattern in prefer:
        for evidence_id, kind, summary in lines:
            if kind == "plan_node" and summary.startswith(pattern):
                return evidence_id
    return lines[0][0] if lines else None


_HYPOTHESIS = re.compile(r"- (hy_[0-9a-f]{12}) rank")
_TABLES = re.compile(r"Tables the query reads: ([a-z_][a-z0-9_]*)")
_EQUALITY = re.compile(r"WHERE\s+([a-z_][a-z0-9_]*)\s*=\s*\$1", re.IGNORECASE)
_ORDER = re.compile(r"ORDER BY\s+([a-z_][a-z0-9_]*)", re.IGNORECASE)


def _stub_candidates(prompt: str) -> dict[str, object]:
    """Canned and mechanical: an index on the equality column (+ the sort column) of the first
    table, or ANALYZE of that table. Earlier rounds are never repeated: round 2 proposes
    nothing, so the stub's optimization loop always ends."""
    hypothesis, table = _HYPOTHESIS.search(prompt), _TABLES.search(prompt)
    if hypothesis is None or table is None or "Earlier rounds:" in prompt:
        return {"candidates": [], "summary": "Stub: nothing (more) to propose (canned)."}
    columns = [m.group(1) for m in (_EQUALITY.search(prompt), _ORDER.search(prompt)) if m]
    candidate: dict[str, object] = (
        {
            "kind": "create_index",
            "ddl": [f"CREATE INDEX ON {table.group(1)} ({', '.join(dict.fromkeys(columns))})"],
        }
        if columns
        else {"kind": "analyze_statistics", "ddl": [f"ANALYZE {table.group(1)}"]}
    )
    return {
        "candidates": [
            {
                **candidate,
                "addresses_hypotheses": [hypothesis.group(1)],
                "expected_benefit": "Canned stub candidate for UI tests; not a recommendation.",
                "risks": [],
            }
        ],
        "summary": "Stub candidate (canned).",
    }


class StubClient:
    provider = "stub"
    model = STUB_MODEL

    def __init__(self, delay_seconds: float = 0.0) -> None:
        self._delay = delay_seconds

    async def complete_json(self, messages: Sequence[ChatMessage]) -> RawCompletion:
        if self._delay:
            await asyncio.sleep(self._delay)
        system = messages[0].content if messages else ""
        prompt = "\n".join(m.content for m in messages)
        cited = _first_evidence(prompt, ("Seq Scan", "Index Scan", "Sort"))
        ids = [cited] if cited else []
        if "Decide which analysts to run" in system:
            eligible = re.search(r"Eligible analysts: ([a-z_, ]+)", prompt)
            agents = eligible.group(1).split(", ") if eligible else ["query_analyzer"]
            body: dict[str, object] = {
                "agents": agents,
                "focus": [],
                "rationale": "Stub plan: every eligible analyst.",
            }
        elif "You are the Benchmark Auditor" in system:
            body = {"summary": "Stub audit (canned): no concerns raised.", "concerns": []}
        elif "You are the Optimization Engineer" in system:
            body = _stub_candidates(prompt)
        elif "Combine the analysts' findings" in system:
            body = {
                "hypotheses": [
                    {
                        "statement": "Stub hypothesis: the cited scan dominates the plan.",
                        "category": "missing_index",
                        "supporting_evidence": ids,
                        "contradicting_evidence": [],
                        "confidence": "low",
                        "uncertainty_notes": "Canned stub output for UI tests; not a diagnosis.",
                        "verification_method": "benchmark",
                    }
                ]
                if ids
                else [],
                "summary": "Stub synthesis (canned).",
            }
        else:
            body = {
                "action": "final",
                "analysis": {
                    "summary": "Stub analysis (canned).",
                    "findings": [
                        {
                            "title": "Stub finding",
                            "detail": "Canned stub output citing real evidence.",
                            "severity": "info",
                            "evidence_ids": ids,
                        }
                    ]
                    if ids
                    else [],
                },
            }
        return RawCompletion(
            text=json.dumps(body),
            model=STUB_MODEL,
            input_tokens=0,
            output_tokens=0,
            served_by="stub",
        )
