"""OpenRouter through its OpenAI-compatible API (ADR-0016).

Called directly with the `openai` SDK rather than through LangChain because the raw response
carries what the free-tier policy needs: the model that actually answered (the free router
picks per request), the upstream provider, and `usage.cost`. With `free_only` every response
must report a cost of exactly 0; anything else stops the run.
"""

from collections.abc import Sequence
from typing import Any

import openai
from langchain_core.exceptions import (
    ModelAPIError,
    ModelAuthenticationError,
    ModelConnectionError,
    ModelInvalidRequestError,
    ModelRateLimitError,
    ModelTimeoutError,
)
from openai.types.chat import ChatCompletionMessageParam
from pydantic import SecretStr

from querycure.llm.types import ChatMessage, RawCompletion

PROVIDER_TIMEOUT_SECONDS = 60.0
_DAILY_MARKERS = ("per-day", "per day", "daily", "free-models-per-day")


class FreeQuotaExhaustedError(Exception):
    """The free tier's daily allowance (or credits) is used up: stop, never pay instead."""


class PaidUsageError(Exception):
    """A response reported a non-zero (or no) cost while free-only mode is on."""


def _classify(exc: openai.APIError) -> Exception:
    """Map SDK errors onto the LangChain classes llm.structured already classifies."""
    message = str(exc).lower()
    if isinstance(exc, openai.RateLimitError):
        if any(marker in message for marker in _DAILY_MARKERS):
            return FreeQuotaExhaustedError("free model quota exhausted")
        return ModelRateLimitError("rate limited")
    if isinstance(exc, openai.APIStatusError) and exc.status_code == 402:
        return FreeQuotaExhaustedError("payment required")
    if isinstance(exc, openai.APITimeoutError):
        return ModelTimeoutError("provider timeout")
    if isinstance(exc, openai.APIConnectionError):
        return ModelConnectionError("provider connection error")
    if isinstance(exc, openai.AuthenticationError | openai.PermissionDeniedError):
        return ModelAuthenticationError("provider rejected the key")
    if isinstance(exc, openai.InternalServerError):
        return ModelAPIError("provider error")
    if isinstance(exc, openai.APIStatusError) and exc.status_code >= 500:
        return ModelAPIError("provider error")
    return ModelInvalidRequestError("provider rejected the request")


def _message(m: ChatMessage) -> ChatCompletionMessageParam:
    if m.role == "system":
        return {"role": "system", "content": m.content}
    if m.role == "assistant":
        return {"role": "assistant", "content": m.content}
    return {"role": "user", "content": m.content}


class OpenRouterClient:
    provider = "openrouter"

    def __init__(
        self,
        *,
        api_key: SecretStr,
        model: str,
        base_url: str,
        free_only: bool,
        http_client: Any = None,
    ) -> None:
        self.model = model
        self._free_only = free_only
        self._client = openai.AsyncOpenAI(
            api_key=api_key.get_secret_value(),
            base_url=base_url,
            max_retries=0,  # llm.structured owns retries
            timeout=PROVIDER_TIMEOUT_SECONDS,
            http_client=http_client,
        )

    def __repr__(self) -> str:
        return f"OpenRouterClient(model={self.model!r}, free_only={self._free_only})"

    async def complete_json(self, messages: Sequence[ChatMessage]) -> RawCompletion:
        try:
            response = await self._client.chat.completions.create(
                model=self.model,
                messages=[_message(m) for m in messages],
                response_format={"type": "json_object"},
                temperature=0,
                extra_body={
                    "usage": {"include": True},
                    # Only route to endpoints that honour response_format.
                    "provider": {"require_parameters": True},
                },
            )
        except openai.APIError as exc:
            raise _classify(exc) from None
        raw = response.model_dump()
        usage = raw.get("usage") or {}
        cost = usage.get("cost")
        if self._free_only and (cost is None or float(cost) != 0.0):
            raise PaidUsageError("response did not report zero cost")
        choices = raw.get("choices") or []
        text = ((choices[0].get("message") or {}).get("content") if choices else None) or ""
        return RawCompletion(
            text=text,
            model=str(raw.get("model") or self.model),
            input_tokens=usage.get("prompt_tokens"),
            output_tokens=usage.get("completion_tokens"),
            served_by=raw.get("provider"),
            generation_id=raw.get("id"),
            cost=float(cost) if cost is not None else None,
        )
