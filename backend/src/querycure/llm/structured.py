"""Structured LLM output with retries, fallback and one repair attempt (AGENT_SYSTEM §10).

The schema goes into the prompt and providers run in JSON mode; Pydantic validation here is
the only gate. Logs carry model, status, tokens and latency, never prompt or output text.
"""

import asyncio
import json
import random
import re
import time
from collections.abc import Awaitable, Callable, Sequence
from dataclasses import dataclass

from langchain_core.exceptions import (
    ModelAPIError,
    ModelAuthenticationError,
    ModelConnectionError,
    ModelError,
    ModelPermissionDeniedError,
    ModelRateLimitError,
    ModelTimeoutError,
)
from pydantic import BaseModel, ValidationError

from querycure.core.errors import QueryCureError
from querycure.core.logging import get_logger
from querycure.llm.openrouter import FreeQuotaExhaustedError, PaidUsageError
from querycure.llm.types import CallRecord, CallStatus, ChatClient, ChatMessage, RawCompletion

log = get_logger(__name__)

Hook = Callable[[], Awaitable[None]]
RecordHook = Callable[[CallRecord], Awaitable[None]]
Sleep = Callable[[float], Awaitable[None]]

_RETRYABLE: dict[type[Exception], str] = {
    ModelRateLimitError: "LLM_RATE_LIMITED",
    ModelAPIError: "LLM_PROVIDER_ERROR",
    ModelTimeoutError: "LLM_TIMEOUT",
    ModelConnectionError: "LLM_CONNECTION_ERROR",
}
_FENCE = re.compile(r"^\s*```(?:json)?\s*(.*?)\s*```\s*$", re.DOTALL)
MAX_REPAIR_ERRORS = 20


@dataclass(frozen=True)
class RetryPolicy:
    max_retries: int = 3
    backoff_base: float = 2.0
    max_delay_seconds: float = 30.0
    jitter_seconds: float = 1.0
    call_timeout_seconds: float = 60.0
    repair_attempts: int = 1


class LLMError(QueryCureError):
    code = "LLM_ERROR"
    status = 502

    def __init__(self, message: str, *, calls: Sequence[CallRecord] = ()) -> None:
        super().__init__(message)
        self.calls = list(calls)


class LLMUnavailableError(LLMError):
    code = "LLM_UNAVAILABLE"


class LLMRequestError(LLMError):
    """Retrying cannot help: bad key, forbidden model, invalid request."""

    code = "LLM_REQUEST_REJECTED"


class LLMAuthFailedError(LLMRequestError):
    code = "LLM_AUTH_FAILED"


class InvalidStructuredOutputError(LLMError):
    code = "LLM_INVALID_OUTPUT"


class LLMQuotaExhaustedError(LLMError):
    """Free-tier allowance used up. Never retried and never sent to a fallback (ADR-0016)."""

    code = "LLM_FREE_QUOTA_EXHAUSTED"


class LLMPaidUsageBlockedError(LLMError):
    """A response was not free while free-only mode is on: stop before anything else runs."""

    code = "LLM_PAID_USAGE_BLOCKED"


@dataclass(frozen=True)
class StructuredResult[T: BaseModel]:
    value: T
    model: str
    raw_text: str
    calls: list[CallRecord]


def _classify(exc: ModelError | TimeoutError) -> tuple[str, bool]:
    """(error code, retryable). Our own call timeout counts as a provider timeout."""
    if isinstance(exc, TimeoutError):
        return "LLM_TIMEOUT", True
    for kind, code in _RETRYABLE.items():
        if isinstance(exc, kind):
            return code, True
    if isinstance(exc, ModelAuthenticationError | ModelPermissionDeniedError):
        return "LLM_AUTH_FAILED", False
    return "LLM_REQUEST_REJECTED", False


def _schema_instruction(output: type[BaseModel]) -> ChatMessage:
    schema = json.dumps(output.model_json_schema(), separators=(",", ":"))
    return ChatMessage(
        role="system",
        content=(
            "Respond with a single JSON object and nothing else. It must validate against "
            f"this JSON Schema:\n{schema}"
        ),
    )


def _parse[T: BaseModel](text: str, output: type[T]) -> T:
    match = _FENCE.match(text)
    return output.model_validate_json(match.group(1) if match else text)


def _repair_message(error: ValidationError | ValueError) -> ChatMessage:
    if isinstance(error, ValidationError):
        problems = [
            f"- {'.'.join(str(p) for p in e['loc']) or '(root)'}: {e['msg']}"
            for e in error.errors(include_input=False, include_url=False)[:MAX_REPAIR_ERRORS]
        ]
    else:
        problems = ["- the output was not valid JSON"]
    return ChatMessage(
        role="user",
        content=(
            "Your previous output failed validation:\n"
            + "\n".join(problems)
            + "\nReturn the corrected JSON object only."
        ),
    )


class _Caller:
    def __init__(
        self,
        policy: RetryPolicy,
        sleep: Sleep,
        rng: random.Random,
        before_call: Hook | None,
        after_call: RecordHook | None,
    ) -> None:
        self.policy = policy
        self.sleep = sleep
        self.rng = rng
        self.before_call = before_call
        self.after_call = after_call
        self.calls: list[CallRecord] = []

    async def record(self, record: CallRecord) -> None:
        self.calls.append(record)
        log.info(
            "llm_call",
            provider=record.provider,
            model=record.model,
            requested_model=record.requested_model,
            served_by=record.served_by,
            status=record.status,
            latency_ms=record.latency_ms,
            input_tokens=record.input_tokens,
            output_tokens=record.output_tokens,
            error_code=record.error_code,
        )
        if self.after_call is not None:
            await self.after_call(record)

    def _delay(self, retry: int) -> float:
        backoff = self.policy.backoff_base**retry
        jitter = self.rng.uniform(0, self.policy.jitter_seconds)
        return min(backoff + jitter, self.policy.max_delay_seconds)

    async def complete(
        self, client: ChatClient, messages: Sequence[ChatMessage]
    ) -> tuple[RawCompletion, float]:
        """One logical completion with transient-error retries on this client."""
        retry = 0
        while True:
            if self.before_call is not None:
                await self.before_call()
            started = time.monotonic()
            try:
                async with asyncio.timeout(self.policy.call_timeout_seconds):
                    completion = await client.complete_json(messages)
                return completion, started
            except (FreeQuotaExhaustedError, PaidUsageError) as exc:
                quota = isinstance(exc, FreeQuotaExhaustedError)
                stop = LLMQuotaExhaustedError if quota else LLMPaidUsageBlockedError
                await self.record(
                    CallRecord(
                        provider=client.provider,
                        model=client.model,
                        requested_model=client.model,
                        status="failed",
                        latency_ms=int((time.monotonic() - started) * 1000),
                        error_code=stop.code,
                    )
                )
                raise stop("The free model allowance is not available.", calls=self.calls) from None
            except (ModelError, TimeoutError) as exc:
                code, retryable = _classify(exc)
                await self.record(
                    CallRecord(
                        provider=client.provider,
                        model=client.model,
                        requested_model=client.model,
                        status="failed",
                        latency_ms=int((time.monotonic() - started) * 1000),
                        error_code=code,
                    )
                )
                if not retryable:
                    error = (
                        LLMAuthFailedError if code == LLMAuthFailedError.code else LLMRequestError
                    )
                    raise error(
                        "The model provider rejected the request.", calls=self.calls
                    ) from None
                if retry >= self.policy.max_retries:
                    raise LLMUnavailableError(
                        "The model provider is unavailable.", calls=self.calls
                    ) from None
                retry += 1
                await self.sleep(self._delay(retry))


async def call_structured[T: BaseModel](
    client: ChatClient,
    messages: Sequence[ChatMessage],
    output: type[T],
    *,
    policy: RetryPolicy | None = None,
    fallback: ChatClient | None = None,
    before_call: Hook | None = None,
    after_call: RecordHook | None = None,
    sleep: Sleep = asyncio.sleep,
    rng: random.Random | None = None,
) -> StructuredResult[T]:
    policy = policy or RetryPolicy()
    caller = _Caller(policy, sleep, rng or random.Random(), before_call, after_call)  # noqa: S311
    conversation = [*messages, _schema_instruction(output)]

    try:
        completion, started = await caller.complete(client, conversation)
        active = client
    except LLMUnavailableError:
        if fallback is None:
            raise
        log.warning("llm_fallback", provider=fallback.provider, model=fallback.model)
        completion, started = await caller.complete(fallback, conversation)
        active = fallback

    for attempt in range(policy.repair_attempts + 1):
        try:
            value = _parse(completion.text, output)
        except (ValidationError, ValueError) as exc:
            await caller.record(_completed(active, completion, started, "invalid_output"))
            if attempt == policy.repair_attempts:
                raise InvalidStructuredOutputError(
                    "The model did not return valid structured output.", calls=caller.calls
                ) from None
            conversation = [
                *conversation,
                ChatMessage(role="assistant", content=completion.text),
                _repair_message(exc),
            ]
            completion, started = await caller.complete(active, conversation)
            continue
        await caller.record(_completed(active, completion, started, "succeeded"))
        return StructuredResult(
            value=value, model=completion.model, raw_text=completion.text, calls=caller.calls
        )
    raise AssertionError("unreachable")


def _completed(
    client: ChatClient, completion: RawCompletion, started: float, status: CallStatus
) -> CallRecord:
    return CallRecord(
        provider=client.provider,
        model=completion.model,
        requested_model=client.model,
        served_by=completion.served_by,
        status=status,
        latency_ms=int((time.monotonic() - started) * 1000),
        input_tokens=completion.input_tokens,
        output_tokens=completion.output_tokens,
    )
