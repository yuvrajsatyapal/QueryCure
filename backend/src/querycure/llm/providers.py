"""LangChain-backed ChatClients for Gemini and OpenRouter, in JSON mode.

Provider-side retries are disabled (max_retries=0): llm.structured owns the retry policy so
backoff, fallback and budget checks happen in one place.
"""

from collections.abc import Sequence
from typing import Any

from langchain_core.language_models import BaseChatModel
from langchain_core.messages import AIMessage, BaseMessage, HumanMessage, SystemMessage
from pydantic import SecretStr

from querycure.core.config import Settings
from querycure.llm.credentials import Provider
from querycure.llm.types import ChatMessage, RawCompletion

PROVIDER_TIMEOUT_SECONDS = 60.0


def to_langchain_messages(messages: Sequence[ChatMessage]) -> list[BaseMessage]:
    """All system text goes first, as one message: Gemini takes a single system instruction."""
    system = "\n\n".join(m.content for m in messages if m.role == "system")
    out: list[BaseMessage] = [SystemMessage(content=system)] if system else []
    for m in messages:
        if m.role == "user":
            out.append(HumanMessage(content=m.content))
        elif m.role == "assistant":
            out.append(AIMessage(content=m.content))
    return out


class LangChainJsonClient:
    def __init__(self, chat_model: BaseChatModel, *, provider: str, model: str) -> None:
        self.provider = provider
        self.model = model
        self._chat_model = chat_model

    def __repr__(self) -> str:
        return f"LangChainJsonClient(provider={self.provider!r}, model={self.model!r})"

    async def complete_json(self, messages: Sequence[ChatMessage]) -> RawCompletion:
        reply = await self._chat_model.ainvoke(to_langchain_messages(messages))
        usage: dict[str, Any] = dict(getattr(reply, "usage_metadata", None) or {})
        return RawCompletion(
            text=reply.text,
            model=self.model,
            input_tokens=usage.get("input_tokens"),
            output_tokens=usage.get("output_tokens"),
        )


def build_client(
    provider: Provider, model: str, api_key: SecretStr, *, settings: Settings
) -> LangChainJsonClient:
    chat_model: BaseChatModel
    if provider == "gemini":
        from langchain_google_genai import ChatGoogleGenerativeAI

        chat_model = ChatGoogleGenerativeAI(
            model=model,
            google_api_key=api_key,
            temperature=0,
            response_mime_type="application/json",
            max_retries=0,
            timeout=PROVIDER_TIMEOUT_SECONDS,
        )
    else:
        from langchain_openai import ChatOpenAI

        chat_model = ChatOpenAI(
            model=model,
            api_key=api_key,
            base_url=settings.openrouter_base_url,
            temperature=0,
            max_retries=0,
            timeout=PROVIDER_TIMEOUT_SECONDS,
            model_kwargs={"response_format": {"type": "json_object"}},
        )
    return LangChainJsonClient(chat_model, provider=provider, model=model)
