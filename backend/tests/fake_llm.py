"""A ChatClient that replays a script of responses; shared by unit and integration tests."""

from collections.abc import Callable, Sequence

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
