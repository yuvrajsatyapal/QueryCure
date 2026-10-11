"""Typed tools agents may request. Each agent gets an explicit allowlist (AGENT_SYSTEM §2).

Tools are thin async functions over the evidence store or the inspection gateway. They take a
validated Pydantic input and return evidence (persisted, citable) plus an optional note.
None of them accepts SQL.
"""

import json
from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass, field
from typing import Any

from pydantic import BaseModel, ConfigDict

from querycure.agents.runtime import RunContext
from querycure.agents.services import Inspector
from querycure.agents.state import InvestigationState
from querycure.domain.investigation import Evidence


class ToolInput(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


@dataclass
class ToolOutput:
    evidence: list[Evidence] = field(default_factory=list)
    note: str | None = None


@dataclass
class ToolContext:
    run: RunContext
    state: InvestigationState
    inspector: Inspector | None = None


@dataclass(frozen=True)
class Tool:
    name: str
    description: str
    input_model: type[ToolInput]
    run: Callable[[ToolContext, Any], Awaitable[ToolOutput]]

    def describe(self) -> str:
        schema = self.input_model.model_json_schema()
        props = json.dumps(schema.get("properties", {}), separators=(",", ":"))
        return f"- {self.name}: {self.description} Arguments: {props}"


def describe_tools(tools: Mapping[str, Tool]) -> str:
    return "\n".join(tool.describe() for tool in tools.values())
