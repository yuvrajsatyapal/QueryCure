"""Provider adapters and key resolution (T2.4). No network calls."""

import pytest
from langchain_core.language_models.fake_chat_models import GenericFakeChatModel
from langchain_core.messages import AIMessage, HumanMessage, SystemMessage
from pydantic import SecretStr

from querycure.core.config import Profile, Settings
from querycure.core.errors import ConfigurationError
from querycure.llm.credentials import resolve_api_key
from querycure.llm.providers import LangChainJsonClient, build_client, to_langchain_messages
from querycure.llm.types import ChatMessage

GEMINI_KEY = "AIza" + "Q" * 35
OPENROUTER_KEY = "sk-or-v1-" + "b" * 64


def settings(**kw: object) -> Settings:
    return Settings(_env_file=None, **kw)  # type: ignore[arg-type]


def test_local_profile_uses_the_env_key() -> None:
    key = resolve_api_key(settings(gemini_api_key=GEMINI_KEY), "gemini")

    assert key.get_secret_value() == GEMINI_KEY


def test_missing_key_is_a_configuration_error_naming_the_variable() -> None:
    with pytest.raises(ConfigurationError, match="OPENROUTER_API_KEY"):
        resolve_api_key(settings(), "openrouter")


def test_demo_profile_never_uses_env_keys() -> None:
    demo = settings(
        profile=Profile.DEMO,
        allow_private_targets=False,
        master_key="A" * 43 + "=",
        gemini_api_key=GEMINI_KEY,
    )

    with pytest.raises(ConfigurationError):
        resolve_api_key(demo, "gemini")


@pytest.mark.parametrize(
    ("provider", "key"), [("gemini", GEMINI_KEY), ("openrouter", OPENROUTER_KEY)]
)
def test_built_clients_never_show_the_key(provider: str, key: str) -> None:
    client = build_client(
        provider,  # type: ignore[arg-type]
        "vendor/some-model:free",  # free-only is on: a paid id is refused before dispatch
        SecretStr(key),
        settings=settings(),
    )

    assert client.provider == provider
    assert client.model == "vendor/some-model:free"
    assert key not in repr(client)
    assert key not in str(vars(client))


def test_system_messages_are_merged_to_the_front() -> None:
    messages = [
        ChatMessage(role="system", content="role"),
        ChatMessage(role="user", content="data"),
        ChatMessage(role="assistant", content="{}"),
        ChatMessage(role="system", content="schema"),
        ChatMessage(role="user", content="fix it"),
    ]

    converted = to_langchain_messages(messages)

    assert isinstance(converted[0], SystemMessage)
    assert converted[0].content == "role\n\nschema"
    assert [type(m) for m in converted[1:]] == [HumanMessage, AIMessage, HumanMessage]


async def test_adapter_returns_text_and_usage() -> None:
    reply = AIMessage(
        content='{"ok": true}',
        usage_metadata={"input_tokens": 12, "output_tokens": 3, "total_tokens": 15},
    )
    client = LangChainJsonClient(
        GenericFakeChatModel(messages=iter([reply])), provider="fake", model="fake-1"
    )

    out = await client.complete_json([ChatMessage(role="user", content="hi")])

    assert out.text == '{"ok": true}'
    assert (out.input_tokens, out.output_tokens, out.model) == (12, 3, "fake-1")
