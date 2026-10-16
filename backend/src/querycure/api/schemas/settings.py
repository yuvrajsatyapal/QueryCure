"""BYOK settings (API_DESIGN §2 Session & settings, T5.2). Responses never carry a key."""

import datetime as dt
import uuid
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, SecretStr, field_validator


class AddLlmCredentialRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    provider: Literal["openrouter", "gemini"] = "openrouter"
    # SecretStr: never echoed in validation errors, reprs or logs.
    api_key: SecretStr = Field(min_length=8, max_length=512)
    default_model: str | None = Field(default=None, max_length=200)

    @field_validator("api_key")
    @classmethod
    def _plain_token(cls, value: SecretStr) -> SecretStr:
        raw = value.get_secret_value()
        if raw != raw.strip() or any(c.isspace() or not c.isprintable() for c in raw):
            raise ValueError("the key must be a single token without spaces")
        return value


class LlmCredentialOut(BaseModel):
    id: uuid.UUID
    provider: str
    key_hint: str
    default_model: str | None
    created_at: dt.datetime
    last_used_at: dt.datetime | None


class LlmCredentialList(BaseModel):
    items: list[LlmCredentialOut]
