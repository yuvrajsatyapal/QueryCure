"""A deterministic, offline LLM for end-to-end UI tests (LLM_PROVIDER=stub, local profile only).

It answers each agent with fixed JSON that cites real evidence IDs taken from the prompt, so
the whole pipeline (citations, persistence, events, UI) runs without a model. Its output is
canned, is labelled `stub` in every record, and must never be presented as a diagnosis.
"""

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


class StubClient:
    provider = "stub"
    model = STUB_MODEL

    async def complete_json(self, messages: Sequence[ChatMessage]) -> RawCompletion:
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
