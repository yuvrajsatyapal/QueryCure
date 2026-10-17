"""Structured output + repair + retry policy (T2.4, AGENT_SYSTEM §10). No network: fake clients."""

import io
import json
import random
from collections.abc import Sequence

import pytest
from langchain_core.exceptions import (
    ModelAPIError,
    ModelAuthenticationError,
    ModelRateLimitError,
    ModelTimeoutError,
)
from pydantic import BaseModel, Field

from querycure.core.errors import BudgetExhaustedError
from querycure.core.logging import configure_logging
from querycure.llm.openrouter import FreeQuotaExhaustedError, ModelUnavailableError
from querycure.llm.structured import (
    InvalidStructuredOutputError,
    LLMCircuitOpenError,
    LLMModelUnavailableError,
    LLMQuotaExhaustedError,
    LLMRequestError,
    LLMUnavailableError,
    ModelHealth,
    RetryPolicy,
    call_structured,
)
from querycure.llm.types import CallRecord, ChatMessage, RawCompletion


class Verdict(BaseModel):
    category: str
    confidence: float = Field(ge=0, le=1)


class Scripted:
    """A ChatClient that replays a script of texts and exceptions."""

    def __init__(self, script: Sequence[str | Exception], model: str = "fake-1") -> None:
        self.provider = "fake"
        self.model = model
        self._script = list(script)
        self.calls: list[list[ChatMessage]] = []

    async def complete_json(self, messages: Sequence[ChatMessage]) -> RawCompletion:
        self.calls.append(list(messages))
        step = self._script.pop(0)
        if isinstance(step, Exception):
            raise step
        return RawCompletion(text=step, input_tokens=10, output_tokens=5, model=self.model)


class Sleeps:
    def __init__(self) -> None:
        self.delays: list[float] = []

    async def __call__(self, delay: float) -> None:
        self.delays.append(delay)


GOOD = '{"category": "missing_index", "confidence": 0.8}'
PROMPT = [
    ChatMessage(role="system", content="You are an analyst."),
    ChatMessage(role="user", content="<<DATA t>> SELECT secret_column FROM vault <<END t>>"),
]
NO_JITTER = RetryPolicy(jitter_seconds=0.0)


async def run(client: Scripted, **kwargs: object) -> object:
    return await call_structured(
        client,
        PROMPT,
        Verdict,
        sleep=kwargs.pop("sleep", Sleeps()),  # type: ignore[arg-type]
        policy=kwargs.pop("policy", NO_JITTER),  # type: ignore[arg-type]
        **kwargs,  # type: ignore[arg-type]
    )


async def test_valid_output_parses_first_time() -> None:
    client = Scripted([GOOD])

    result = await call_structured(client, PROMPT, Verdict, policy=NO_JITTER)

    assert result.value == Verdict(category="missing_index", confidence=0.8)
    assert [r.status for r in result.calls] == ["succeeded"]
    assert result.calls[0].input_tokens == 10


async def test_schema_instruction_is_appended() -> None:
    client = Scripted([GOOD])

    await call_structured(client, PROMPT, Verdict, policy=NO_JITTER)

    last = client.calls[0][-1]
    assert last.role == "system"
    assert '"confidence"' in last.content
    assert "JSON" in last.content


async def test_markdown_fenced_json_is_accepted() -> None:
    client = Scripted([f"```json\n{GOOD}\n```"])

    result = await call_structured(client, PROMPT, Verdict, policy=NO_JITTER)

    assert result.value.category == "missing_index"


async def test_invalid_output_is_repaired_once_with_the_errors() -> None:
    client = Scripted(['{"category": "missing_index", "confidence": 7}', GOOD])

    result = await call_structured(client, PROMPT, Verdict, policy=NO_JITTER)

    assert result.value.confidence == 0.8
    assert [r.status for r in result.calls] == ["invalid_output", "succeeded"]
    repair = client.calls[1]
    assert repair[-2].role == "assistant"
    assert "confidence" in repair[-1].content
    assert "less than or equal to 1" in repair[-1].content


async def test_second_invalid_output_fails_without_a_third_call() -> None:
    client = Scripted(["not json at all", '{"category": 3}'])

    with pytest.raises(InvalidStructuredOutputError) as info:
        await call_structured(client, PROMPT, Verdict, policy=NO_JITTER)

    assert len(client.calls) == 2
    assert [r.status for r in info.value.calls] == ["invalid_output", "invalid_output"]


async def test_rate_limits_back_off_exponentially_then_succeed() -> None:
    client = Scripted([ModelRateLimitError("429"), ModelAPIError("503"), GOOD])
    sleeps = Sleeps()

    result = await call_structured(client, PROMPT, Verdict, policy=NO_JITTER, sleep=sleeps)

    assert result.value.category == "missing_index"
    assert sleeps.delays == [2.0, 4.0]
    assert [r.status for r in result.calls] == ["failed", "failed", "succeeded"]
    assert [r.error_code for r in result.calls[:2]] == ["LLM_RATE_LIMITED", "LLM_PROVIDER_ERROR"]


async def test_backoff_is_capped_at_thirty_seconds() -> None:
    policy = RetryPolicy(max_retries=6, jitter_seconds=0.0)
    client = Scripted([ModelRateLimitError("429")] * 6 + [GOOD])
    sleeps = Sleeps()

    await call_structured(client, PROMPT, Verdict, policy=policy, sleep=sleeps)

    assert sleeps.delays == [2.0, 4.0, 8.0, 16.0, 30.0, 30.0]


async def test_jitter_stays_within_bounds() -> None:
    client = Scripted([ModelRateLimitError("429"), GOOD])
    sleeps = Sleeps()

    await call_structured(
        client,
        PROMPT,
        Verdict,
        policy=RetryPolicy(jitter_seconds=1.0),
        sleep=sleeps,
        rng=random.Random(7),
    )

    assert 2.0 <= sleeps.delays[0] <= 3.0


async def test_exhausted_retries_without_fallback_raise_unavailable() -> None:
    client = Scripted([ModelRateLimitError("429")] * 4)

    with pytest.raises(LLMUnavailableError):
        await call_structured(client, PROMPT, Verdict, policy=NO_JITTER, sleep=Sleeps())

    assert len(client.calls) == 4  # first try + 3 retries


async def test_exhausted_retries_switch_to_the_fallback_model() -> None:
    primary = Scripted([ModelRateLimitError("429")] * 4, model="primary")
    fallback = Scripted([GOOD], model="fallback")

    result = await call_structured(
        primary, PROMPT, Verdict, policy=NO_JITTER, sleep=Sleeps(), fallback=fallback
    )

    assert result.value.category == "missing_index"
    assert result.model == "fallback"
    assert result.calls[-1].model == "fallback"


async def test_authentication_errors_are_not_retried() -> None:
    client = Scripted([ModelAuthenticationError("bad key"), GOOD])

    with pytest.raises(LLMRequestError) as info:
        await call_structured(client, PROMPT, Verdict, policy=NO_JITTER, sleep=Sleeps())

    assert info.value.code == "LLM_AUTH_FAILED"
    assert len(client.calls) == 1


async def test_budget_hook_runs_before_every_provider_call() -> None:
    client = Scripted([ModelRateLimitError("429"), GOOD])
    allowed = 1

    async def before_call() -> None:
        nonlocal allowed
        if allowed == 0:
            raise BudgetExhaustedError("llm_calls")
        allowed -= 1

    with pytest.raises(BudgetExhaustedError):
        await call_structured(
            client, PROMPT, Verdict, policy=NO_JITTER, sleep=Sleeps(), before_call=before_call
        )

    assert len(client.calls) == 1  # the retry was stopped by the budget, not sent


async def test_after_call_receives_every_record() -> None:
    client = Scripted(["nope", GOOD])
    seen: list[CallRecord] = []

    async def after_call(record: CallRecord) -> None:
        seen.append(record)

    await call_structured(client, PROMPT, Verdict, policy=NO_JITTER, after_call=after_call)

    assert [r.status for r in seen] == ["invalid_output", "succeeded"]


async def test_logs_never_contain_prompt_or_output_text() -> None:
    buf = io.StringIO()
    configure_logging(level="DEBUG", stream=buf)
    client = Scripted([ModelRateLimitError("429"), "garbage secret_column", GOOD])

    await call_structured(client, PROMPT, Verdict, policy=NO_JITTER, sleep=Sleeps())

    lines = [json.loads(line) for line in buf.getvalue().splitlines()]
    assert lines, "expected call logs"
    assert "secret_column" not in buf.getvalue()
    assert "You are an analyst" not in buf.getvalue()
    assert {line["event"] for line in lines} >= {"llm_call"}


# --- reliability hardening (E2E audit O1/O5, ADR-0026) ---


async def test_timeouts_are_retried_only_once() -> None:
    client = Scripted([ModelTimeoutError("t"), TimeoutError(), GOOD])

    with pytest.raises(LLMUnavailableError) as info:
        await run(client)

    assert len(client.calls) == 2  # a model that hung twice is not given a third chance
    assert info.value.cause == "LLM_TIMEOUT"


async def test_unavailable_error_keeps_the_last_cause() -> None:
    client = Scripted([ModelRateLimitError("429")] * 4)

    with pytest.raises(LLMUnavailableError) as info:
        await run(client)

    assert info.value.cause == "LLM_RATE_LIMITED"


async def test_unknown_model_is_not_retried_and_goes_to_the_fallback() -> None:
    primary = Scripted([ModelUnavailableError("no endpoints"), GOOD], model="primary")
    fallback = Scripted([GOOD], model="fallback:free")

    result = await run(primary, fallback=fallback)

    assert len(primary.calls) == 1
    assert result.model == "fallback:free"  # type: ignore[attr-defined]
    assert result.calls[0].error_code == "LLM_MODEL_UNAVAILABLE"  # type: ignore[attr-defined]


async def test_unknown_model_without_fallback_is_a_distinct_error() -> None:
    with pytest.raises(LLMModelUnavailableError) as info:
        await run(Scripted([ModelUnavailableError("no endpoints")]))
    assert info.value.code == "LLM_MODEL_UNAVAILABLE"


async def test_invalid_output_after_repair_tries_the_fallback_once() -> None:
    primary = Scripted(["nope", "still nope"], model="primary")
    fallback = Scripted([GOOD], model="fallback:free")

    result = await run(primary, fallback=fallback)

    assert result.model == "fallback:free"  # type: ignore[attr-defined]
    assert [r.status for r in result.calls] == [  # type: ignore[attr-defined]
        "invalid_output", "invalid_output", "succeeded",
    ]  # fmt: skip


async def test_fallback_failure_is_final_no_ping_pong() -> None:
    primary = Scripted(["nope", "still nope"], model="primary")
    fallback = Scripted(["bad", "worse"], model="fallback:free")

    with pytest.raises(InvalidStructuredOutputError):
        await run(primary, fallback=fallback)

    assert len(primary.calls) == 2
    assert len(fallback.calls) == 2


async def test_quota_exhaustion_never_reaches_the_fallback() -> None:
    fallback = Scripted([GOOD], model="fallback:free")

    with pytest.raises(LLMQuotaExhaustedError):
        await run(Scripted([FreeQuotaExhaustedError("daily")]), fallback=fallback)

    assert fallback.calls == []


async def test_circuit_opens_after_repeated_failures_and_skips_the_model() -> None:
    health = ModelHealth(threshold=2)
    for _ in range(2):
        with pytest.raises(InvalidStructuredOutputError):
            await run(Scripted(["x", "y"], model="m"), health=health)

    untouched = Scripted([GOOD], model="m")
    with pytest.raises(LLMCircuitOpenError) as info:
        await run(untouched, health=health)

    assert untouched.calls == []
    assert info.value.code == "LLM_CIRCUIT_OPEN"
    assert info.value.calls == []


async def test_open_circuit_on_the_primary_goes_straight_to_the_fallback() -> None:
    health = ModelHealth(threshold=1)
    with pytest.raises(InvalidStructuredOutputError):
        await run(Scripted(["x", "y"], model="m"), health=health)

    primary = Scripted([GOOD], model="m")
    fallback = Scripted([GOOD], model="fallback:free")
    result = await run(primary, fallback=fallback, health=health)

    assert primary.calls == []
    assert result.model == "fallback:free"  # type: ignore[attr-defined]


async def test_a_success_closes_the_circuit_count() -> None:
    health = ModelHealth(threshold=2)
    with pytest.raises(InvalidStructuredOutputError):
        await run(Scripted(["x", "y"], model="m"), health=health)
    await run(Scripted([GOOD], model="m"), health=health)
    with pytest.raises(InvalidStructuredOutputError):
        await run(Scripted(["x", "y"], model="m"), health=health)

    assert not health.is_open("m")
