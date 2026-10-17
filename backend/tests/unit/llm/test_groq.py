"""Groq provider (ADR-0027): config guard, key resolution, client behaviour. No network calls."""

import json
from typing import Any

import httpx
import pytest
from langchain_core.exceptions import ModelAuthenticationError, ModelRateLimitError
from pydantic import SecretStr, ValidationError
from sqlalchemy.ext.asyncio import create_async_engine

from querycure.core.config import Profile, Settings
from querycure.core.errors import ConfigurationError
from querycure.jobs.handlers import llm_gate
from querycure.llm.credentials import resolve_api_key
from querycure.llm.groq import GroqClient
from querycure.llm.openrouter import FreeQuotaExhaustedError
from querycure.llm.providers import build_client
from querycure.llm.types import ChatMessage

KEY = "gsk_" + "d" * 52
GOOD = '{"category": "missing_index", "confidence": 0.8}'
MESSAGES = [
    ChatMessage(role="system", content="Answer in JSON."),
    ChatMessage(role="user", content="go"),
]


def settings(**kw: object) -> Settings:
    return Settings(_env_file=None, **kw)  # type: ignore[arg-type]


def test_groq_is_allowed_while_free_only_is_on() -> None:
    # The free plan has no billing; ADR-0027 trusts the key to be on it.
    s = settings(llm_provider="groq", llm_model="llama-3.3-70b-versatile")

    assert (s.llm_provider, s.llm_free_only) == ("groq", True)


def test_groq_fallback_model_is_not_held_to_openrouter_ids() -> None:
    s = settings(
        llm_provider="groq",
        llm_model="llama-3.3-70b-versatile",
        llm_fallback_model="qwen/qwen3-32b",
    )

    assert s.llm_fallback_model == "qwen/qwen3-32b"


def test_groq_key_is_refused_in_the_demo_profile() -> None:
    with pytest.raises(ValidationError, match="GROQ_API_KEY"):
        settings(
            profile=Profile.DEMO,
            allow_private_targets=False,
            master_key="A" * 43 + "=",
            groq_api_key=KEY,
        )


def test_groq_key_is_read_from_the_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("GROQ_API_KEY", KEY)

    assert resolve_api_key(Settings(_env_file=None), "groq").get_secret_value() == KEY


def test_missing_groq_key_names_the_variable() -> None:
    with pytest.raises(ConfigurationError, match="GROQ_API_KEY"):
        resolve_api_key(settings(), "groq")


def test_built_groq_client_never_shows_the_key() -> None:
    client = build_client("groq", "llama-3.3-70b-versatile", SecretStr(KEY), settings=settings())

    assert isinstance(client, GroqClient)
    assert (client.provider, client.model) == ("groq", "llama-3.3-70b-versatile")
    assert KEY not in repr(client)
    assert KEY not in str(vars(client))


def response() -> dict[str, Any]:
    return {
        "id": "chatcmpl-1",
        "object": "chat.completion",
        "created": 0,
        "model": "llama-3.3-70b-versatile",
        "choices": [
            {"index": 0, "finish_reason": "stop", "message": {"role": "assistant", "content": GOOD}}
        ],
        "usage": {"prompt_tokens": 90, "completion_tokens": 20},
    }


def client_returning(*replies: tuple[int, dict[str, Any]]) -> tuple[GroqClient, list[Any]]:
    sent: list[Any] = []
    queue = list(replies)

    def handler(request: httpx.Request) -> httpx.Response:
        sent.append((str(request.url), json.loads(request.content)))
        status, body = queue.pop(0)
        return httpx.Response(status, json=body)

    client = GroqClient(
        api_key=SecretStr(KEY),
        model="llama-3.3-70b-versatile",
        base_url="https://groq.test/openai/v1",
        http_client=httpx.AsyncClient(transport=httpx.MockTransport(handler)),
    )
    return client, sent


async def test_json_mode_request_and_usage_are_captured() -> None:
    client, sent = client_returning((200, response()))

    out = await client.complete_json(MESSAGES)

    assert out.text == GOOD
    assert (out.model, out.input_tokens, out.output_tokens) == ("llama-3.3-70b-versatile", 90, 20)
    assert out.served_by == "groq"
    url, body = sent[0]
    assert url == "https://groq.test/openai/v1/chat/completions"
    assert body["response_format"] == {"type": "json_object"}
    assert body["temperature"] == 0
    assert "usage" not in body  # OpenRouter-only extras
    assert "provider" not in body


async def test_daily_limit_429_stops_instead_of_retrying() -> None:
    client, _ = client_returning(
        (429, {"error": {"message": "Rate limit reached for model on requests per day (RPD)"}})
    )

    with pytest.raises(FreeQuotaExhaustedError):
        await client.complete_json(MESSAGES)


async def test_minute_limit_429_is_a_retryable_rate_limit() -> None:
    client, _ = client_returning(
        (429, {"error": {"message": "Rate limit reached for model on requests per minute (RPM)"}})
    )

    with pytest.raises(ModelRateLimitError):
        await client.complete_json(MESSAGES)


async def test_rejected_key_is_an_authentication_error() -> None:
    client, _ = client_returning((401, {"error": {"message": "Invalid API Key"}}))

    with pytest.raises(ModelAuthenticationError):
        await client.complete_json(MESSAGES)


@pytest.mark.parametrize(
    ("provider", "model", "gated", "daily"),
    [
        ("openrouter", "nvidia/nemotron-3-super-120b-a12b:free", True, True),
        ("groq", "llama-3.3-70b-versatile", True, False),
        ("stub", "nvidia/nemotron-3-super-120b-a12b:free", False, False),
    ],
)
def test_minute_limit_applies_to_groq_but_the_openrouter_daily_count_does_not(
    provider: str, model: str, gated: bool, daily: bool
) -> None:
    engine = create_async_engine("postgresql+psycopg://u:pw@127.0.0.1:5432/d")

    gate = llm_gate(engine, settings(llm_provider=provider, llm_model=model))

    assert (gate is not None) is gated
    assert (gate is not None and gate._quota is not None) is daily
