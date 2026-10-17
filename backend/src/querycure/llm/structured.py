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
from querycure.llm.openrouter import (
    FreeQuotaExhaustedError,
    ModelUnavailableError,
    PaidUsageError,
)
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
    # A model that ran into the full call timeout tends to do it again: one retry only, so a
    # hanging free model costs at most two timeouts per logical call (E2E audit O1).
    max_timeout_retries: int = 1
    backoff_base: float = 2.0
    max_delay_seconds: float = 30.0
    jitter_seconds: float = 1.0
    call_timeout_seconds: float = 60.0
    repair_attempts: int = 1


class LLMError(QueryCureError):
    code = "LLM_ERROR"
    status = 502

    def __init__(
        self, message: str, *, calls: Sequence[CallRecord] = (), cause: str | None = None
    ) -> None:
        super().__init__(message)
        self.calls = list(calls)
        # The transport code behind a generic failure (LLM_TIMEOUT, LLM_RATE_LIMITED, ...).
        self.cause = cause


class LLMUnavailableError(LLMError):
    code = "LLM_UNAVAILABLE"


class LLMRequestError(LLMError):
    """Retrying cannot help: bad key, forbidden model, invalid request."""

    code = "LLM_REQUEST_REJECTED"


class LLMAuthFailedError(LLMRequestError):
    code = "LLM_AUTH_FAILED"


class LLMModelUnavailableError(LLMRequestError):
    """The provider has no endpoint for this model: not retried, but a fallback may help."""

    code = "LLM_MODEL_UNAVAILABLE"


class LLMCircuitOpenError(LLMUnavailableError):
    """Every configured model failed repeatedly in this run: no further call is made."""

    code = "LLM_CIRCUIT_OPEN"


class ModelHealth:
    """Per-run circuit breaker over models (E2E audit O1).

    After `threshold` consecutive failed logical calls (transport exhausted, invalid structured
    output after repair, or an unknown model, which trips at once) a model is skipped for the
    rest of the run: later agents go straight to the fallback, or fail fast without spending
    calls, wall-clock time and the daily free allowance on a model that already proved
    incompatible. A success resets the count. In memory only: a resumed run starts fresh."""

    def __init__(self, threshold: int = 2) -> None:
        self.threshold = threshold
        self._failures: dict[str, int] = {}

    def is_open(self, model: str) -> bool:
        return self._failures.get(model, 0) >= self.threshold

    def failure(self, model: str, *, immediate: bool = False) -> None:
        count = self.threshold if immediate else self._failures.get(model, 0) + 1
        self._failures[model] = count
        if count == self.threshold:
            log.warning("llm_circuit_open", model=model, failures=count)

    def success(self, model: str) -> None:
        self._failures.pop(model, None)


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
        retry = timeouts = 0
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
            except ModelUnavailableError:
                await self.record(
                    CallRecord(
                        provider=client.provider,
                        model=client.model,
                        requested_model=client.model,
                        status="failed",
                        latency_ms=int((time.monotonic() - started) * 1000),
                        error_code=LLMModelUnavailableError.code,
                    )
                )
                raise LLMModelUnavailableError(
                    "The model is not available from the provider.", calls=self.calls
                ) from None
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
                timeouts += code == "LLM_TIMEOUT"
                if retry >= self.policy.max_retries or timeouts > self.policy.max_timeout_retries:
                    raise LLMUnavailableError(
                        "The model provider is unavailable.", calls=self.calls, cause=code
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
    health: ModelHealth | None = None,
) -> StructuredResult[T]:
    """Primary, then at most one fallback model (bounded, never paid, ADR-0016/0026).

    The fallback gets one full attempt (its own transient retries and repair) when the primary
    is unavailable (retries exhausted or unknown model) or still returns invalid structured
    output after repair. Quota exhaustion, paid usage and rejected keys never reach it. A model
    whose circuit is open (`health`) is skipped without a call."""
    policy = policy or RetryPolicy()
    caller = _Caller(policy, sleep, rng or random.Random(), before_call, after_call)  # noqa: S311
    conversation = [*messages, _schema_instruction(output)]
    clients = [c for c in (client, fallback) if c is not None]
    if health is not None:
        clients = [c for c in clients if not health.is_open(c.model)]
        if not clients:
            raise LLMCircuitOpenError(
                "The configured models failed repeatedly in this run; no further call is made.",
                cause=LLMCircuitOpenError.code,
            )
    for index, active in enumerate(clients):
        if index > 0:
            log.warning("llm_fallback", provider=active.provider, model=active.model)
        try:
            result = await _attempt(caller, active, conversation, output, policy)
        except (LLMUnavailableError, LLMModelUnavailableError, InvalidStructuredOutputError) as exc:
            if health is not None:
                health.failure(active.model, immediate=isinstance(exc, LLMModelUnavailableError))
            if index + 1 < len(clients):
                continue
            raise
        if health is not None:
            health.success(active.model)
        return result
    raise AssertionError("unreachable")


async def _attempt[T: BaseModel](
    caller: _Caller,
    active: ChatClient,
    conversation: list[ChatMessage],
    output: type[T],
    policy: RetryPolicy,
) -> StructuredResult[T]:
    completion, started = await caller.complete(active, conversation)
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
