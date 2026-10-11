from collections.abc import Sequence
from typing import Literal, Protocol

from pydantic import BaseModel, ConfigDict


class ChatMessage(BaseModel):
    model_config = ConfigDict(frozen=True)

    role: Literal["system", "user", "assistant"]
    content: str


class RawCompletion(BaseModel):
    model_config = ConfigDict(frozen=True)

    text: str
    model: str  # the model that actually answered (a router may pick a different one)
    input_tokens: int | None = None
    output_tokens: int | None = None
    served_by: str | None = None  # upstream provider, when the gateway reports it
    generation_id: str | None = None
    cost: float | None = None


class ChatClient(Protocol):
    """A provider that returns raw JSON text. All validation happens in llm.structured, so
    real providers, eval replays and test fakes share one parsing and repair path."""

    provider: str
    model: str

    async def complete_json(self, messages: Sequence[ChatMessage]) -> RawCompletion: ...


CallStatus = Literal["succeeded", "failed", "invalid_output"]


class CallRecord(BaseModel):
    """One provider call: what agent_executions and budget accounting need. Never text."""

    model_config = ConfigDict(frozen=True)

    provider: str
    model: str  # served model when known, otherwise the requested one
    status: CallStatus
    latency_ms: int
    input_tokens: int | None = None
    output_tokens: int | None = None
    error_code: str | None = None
    requested_model: str | None = None
    served_by: str | None = None
