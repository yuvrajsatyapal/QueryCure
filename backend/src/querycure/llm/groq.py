"""Groq through its OpenAI-compatible API (ADR-0027).

Groq reports no per-request cost, so nothing here can prove a call was free: the free-only
policy relies on the key being on Groq's free plan, which has no billing. Its per-day 429s map
to `FreeQuotaExhaustedError` (stop, never pay instead), per-minute 429s to a retryable rate
limit, through the same classifier as OpenRouter.
"""

from collections.abc import Sequence
from typing import Any

import openai
from pydantic import SecretStr

from querycure.llm.openrouter import classify_api_error, to_openai_message
from querycure.llm.types import ChatMessage, RawCompletion


class GroqClient:
    provider = "groq"

    def __init__(
        self,
        *,
        api_key: SecretStr,
        model: str,
        base_url: str,
        timeout_seconds: float = 120.0,
        http_client: Any = None,
    ) -> None:
        self.model = model
        self._client = openai.AsyncOpenAI(
            api_key=api_key.get_secret_value(),
            base_url=base_url,
            max_retries=0,  # llm.structured owns retries
            timeout=timeout_seconds,
            http_client=http_client,
        )

    def __repr__(self) -> str:
        return f"GroqClient(model={self.model!r})"

    async def complete_json(self, messages: Sequence[ChatMessage]) -> RawCompletion:
        try:
            response = await self._client.chat.completions.create(
                model=self.model,
                messages=[to_openai_message(m) for m in messages],
                response_format={"type": "json_object"},
                temperature=0,
            )
        except openai.APIError as exc:
            raise classify_api_error(exc) from None
        choice = response.choices[0] if response.choices else None
        usage = response.usage
        return RawCompletion(
            text=(choice.message.content if choice else None) or "",
            model=response.model or self.model,
            input_tokens=usage.prompt_tokens if usage else None,
            output_tokens=usage.completion_tokens if usage else None,
            served_by=self.provider,
            generation_id=response.id,
        )
