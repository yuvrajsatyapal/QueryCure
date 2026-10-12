"""A ChatClient that replays a script of responses; shared by unit and integration tests."""

from collections.abc import Callable, Sequence
from typing import ClassVar

from querycure.llm.types import ChatMessage, RawCompletion

Step = str | Exception | Callable[[Sequence[ChatMessage]], str]


class ScriptedClient:
    def __init__(self, script: Sequence[Step], model: str = "fake-1") -> None:
        self.provider = "fake"
        self.model = model
        self._script = list(script)
        self.calls: list[list[ChatMessage]] = []

    async def complete_json(self, messages: Sequence[ChatMessage]) -> RawCompletion:
        self.calls.append(list(messages))
        if not self._script:
            raise AssertionError("ScriptedClient called more times than scripted")
        step = self._script.pop(0)
        if isinstance(step, Exception):
            raise step
        text = step(messages) if callable(step) else step
        return RawCompletion(text=text, model=self.model, input_tokens=100, output_tokens=20)


class RoleClient:
    """Routes each call to a script by the role sentence in the system prompt, so parallel
    analysts get their own deterministic responses."""

    ROLES: ClassVar[dict[str, str]] = {
        "plan": "Decide which analysts to run",
        "synthesis": "Combine the analysts' findings",
        "query_analyzer": "You are the Query Analyzer",
        "index_strategist": "You are the Index Strategist",
        "workload_investigator": "You are the Workload Investigator",
        "optimization_engineer": "You are the Optimization Engineer",
    }

    def __init__(self, scripts: dict[str, Sequence[Step]], model: str = "fake-1") -> None:
        self.provider = "fake"
        self.model = model
        self.clients = {role: ScriptedClient(script, model) for role, script in scripts.items()}

    def calls(self, role: str) -> list[list[ChatMessage]]:
        return self.clients[role].calls if role in self.clients else []

    async def complete_json(self, messages: Sequence[ChatMessage]) -> RawCompletion:
        system = messages[0].content
        for role, marker in self.ROLES.items():
            if marker in system:
                if role not in self.clients:
                    raise AssertionError(f"no script for role {role}")
                return await self.clients[role].complete_json(messages)
        raise AssertionError("unrecognised agent prompt")
