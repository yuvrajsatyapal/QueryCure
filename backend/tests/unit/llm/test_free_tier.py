"""Free-tier-only policy (ADR-0016): config guard, OpenRouter client checks, limits."""

import json
from typing import Any

import httpx
import pytest
from pydantic import SecretStr, ValidationError

from querycure.core.config import Settings, is_free_model
from querycure.core.errors import BudgetExhaustedError
from querycure.llm.openrouter import FreeQuotaExhaustedError, OpenRouterClient, PaidUsageError
from querycure.llm.rate_limit import MinuteRateLimiter
from querycure.llm.structured import (
    LLMPaidUsageBlockedError,
    LLMQuotaExhaustedError,
    RetryPolicy,
    call_structured,
)
from querycure.llm.types import ChatMessage
from tests.unit.llm.test_structured import Verdict

KEY = "sk-or-v1-" + "c" * 64
GOOD = '{"category": "missing_index", "confidence": 0.8}'


@pytest.mark.parametrize(
    ("model", "free"),
    [
        ("openrouter/free", True),
        ("nvidia/nemotron-3-super-120b-a12b:free", True),
        ("google/gemma-4-31b-it:free", True),
        ("openrouter/auto", False),  # listed at $0 but routes to paid models
        ("anthropic/claude-sonnet-5.5", False),
        (":free", False),
    ],
)
def test_free_model_ids(model: str, free: bool) -> None:
    assert is_free_model(model) is free


def test_defaults_are_the_pinned_free_model() -> None:
    s = Settings(_env_file=None)

    assert (s.llm_provider, s.llm_free_only) == ("openrouter", True)
    assert is_free_model(s.llm_model)
    assert s.llm_model == "nvidia/nemotron-3-super-120b-a12b:free"
    assert s.llm_daily_request_limit < 50
    assert s.llm_requests_per_minute < 20


@pytest.mark.parametrize(
    "kwargs",
    [
        {"llm_model": "anthropic/claude-sonnet-5.5"},
        {"llm_model": "openrouter/auto"},
        {"llm_fallback_model": "openai/gpt-5.5"},
        {"llm_provider": "gemini", "llm_model": "gemini-2.5-flash"},
    ],
)
def test_paid_configuration_is_refused(kwargs: dict[str, Any]) -> None:
    with pytest.raises(ValidationError, match="free"):
        Settings(_env_file=None, **kwargs)


def test_paid_models_need_an_explicit_opt_out() -> None:
    s = Settings(_env_file=None, llm_free_only=False, llm_model="anthropic/claude-sonnet-5.5")

    assert s.llm_model == "anthropic/claude-sonnet-5.5"


def response(cost: float | None = 0, **extra: Any) -> dict[str, Any]:
    usage: dict[str, Any] = {"prompt_tokens": 120, "completion_tokens": 30}
    if cost is not None:
        usage["cost"] = cost
    return {
        "id": "gen-123",
        "object": "chat.completion",
        "created": 0,
        "model": "nvidia/nemotron-3-super-120b-a12b:free",
        "provider": "Nvidia",
        "choices": [
            {"index": 0, "finish_reason": "stop", "message": {"role": "assistant", "content": GOOD}}
        ],
        "usage": usage,
        **extra,
    }


def client_returning(
    *replies: tuple[int, dict[str, Any]], free_only: bool = True
) -> tuple[OpenRouterClient, list[dict[str, Any]]]:
    sent: list[dict[str, Any]] = []
    queue = list(replies)

    def handler(request: httpx.Request) -> httpx.Response:
        sent.append(json.loads(request.content))
        status, body = queue.pop(0)
        return httpx.Response(status, json=body)

    client = OpenRouterClient(
        api_key=SecretStr(KEY),
        model="openrouter/free",
        base_url="https://openrouter.test/api/v1",
        free_only=free_only,
        http_client=httpx.AsyncClient(transport=httpx.MockTransport(handler)),
    )
    return client, sent


MESSAGES = [ChatMessage(role="user", content="go")]


async def test_served_model_provider_and_cost_are_captured() -> None:
    client, sent = client_returning((200, response()))

    out = await client.complete_json(MESSAGES)

    assert out.model == "nvidia/nemotron-3-super-120b-a12b:free"
    assert (out.served_by, out.generation_id, out.cost) == ("Nvidia", "gen-123", 0.0)
    assert (out.input_tokens, out.output_tokens) == (120, 30)
    body = sent[0]
    assert body["model"] == "openrouter/free"
    assert body["response_format"] == {"type": "json_object"}
    assert body["usage"] == {"include": True}
    assert body["provider"] == {"require_parameters": True}


@pytest.mark.parametrize("cost", [0.0004, None])
async def test_non_zero_or_missing_cost_is_blocked(cost: float | None) -> None:
    client, _ = client_returning((200, response(cost=cost)))

    with pytest.raises(PaidUsageError):
        await client.complete_json(MESSAGES)


async def test_daily_limit_429_is_quota_exhaustion_not_a_retry() -> None:
    client, _ = client_returning(
        (429, {"error": {"message": "Rate limit exceeded: free-models-per-day", "code": 429}})
    )

    with pytest.raises(FreeQuotaExhaustedError):
        await client.complete_json(MESSAGES)


async def test_quota_exhaustion_stops_without_retry_or_fallback() -> None:
    primary, _ = client_returning(
        (429, {"error": {"message": "free-models-per-day exceeded", "code": 429}})
    )
    fallback, fallback_sent = client_returning((200, response()))

    with pytest.raises(LLMQuotaExhaustedError):
        await call_structured(
            primary, MESSAGES, Verdict, fallback=fallback, policy=RetryPolicy(jitter_seconds=0)
        )

    assert fallback_sent == []


async def test_paid_response_stops_without_fallback() -> None:
    primary, _ = client_returning((200, response(cost=0.01)))
    fallback, fallback_sent = client_returning((200, response()))

    with pytest.raises(LLMPaidUsageBlockedError):
        await call_structured(primary, MESSAGES, Verdict, fallback=fallback)

    assert fallback_sent == []


async def test_minute_429_is_retried() -> None:
    client, sent = client_returning(
        (429, {"error": {"message": "Rate limit exceeded: 20 per minute", "code": 429}}),
        (200, response()),
    )

    async def no_sleep(_: float) -> None:
        return None

    result = await call_structured(
        client, MESSAGES, Verdict, policy=RetryPolicy(jitter_seconds=0), sleep=no_sleep
    )

    assert result.value.category == "missing_index"
    assert len(sent) == 2
    assert result.calls[-1].served_by == "Nvidia"
    assert result.calls[-1].requested_model == "openrouter/free"


async def test_402_payment_required_is_quota_exhaustion() -> None:
    client, _ = client_returning((402, {"error": {"message": "Insufficient credits", "code": 402}}))

    with pytest.raises(FreeQuotaExhaustedError):
        await client.complete_json(MESSAGES)


def test_key_is_not_in_the_client_repr() -> None:
    client, _ = client_returning((200, response()))

    assert KEY not in repr(client)


async def test_minute_limiter_waits_when_the_window_is_full() -> None:
    now = 0.0
    slept: list[float] = []

    async def fake_sleep(seconds: float) -> None:
        nonlocal now
        slept.append(seconds)
        now += seconds

    limiter = MinuteRateLimiter(2, clock=lambda: now, sleep=fake_sleep)
    await limiter.acquire()
    now = 10.0
    await limiter.acquire()
    now = 20.0
    await limiter.acquire()  # third request in the same minute waits for the first to age out

    assert slept == [40.0]


def test_budget_error_shape_for_daily_quota() -> None:
    err = BudgetExhaustedError("x", details=[{"budget": "llm_daily_requests", "limit": 45}])

    assert err.details[0]["budget"] == "llm_daily_requests"


def test_call_timeout_defaults_to_two_minutes_for_slow_free_models() -> None:
    assert Settings(_env_file=None).llm_call_timeout_seconds == 120.0
