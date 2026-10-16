import uuid
from dataclasses import dataclass
from typing import Literal

from pydantic import SecretStr
from sqlalchemy.ext.asyncio import AsyncConnection

from querycure.core.config import Profile, Settings, is_free_model
from querycure.core.crypto import DecryptionError, SecretBox
from querycure.core.errors import ConfigurationError
from querycure.db.repositories import llm_credentials as creds

Provider = Literal["gemini", "openrouter"]

_ENV_NAMES: dict[Provider, str] = {"gemini": "GEMINI_API_KEY", "openrouter": "OPENROUTER_API_KEY"}


def resolve_api_key(settings: Settings, provider: Provider) -> SecretStr:
    """Local-profile server key, resolved per run and kept out of state, events and logs."""
    if settings.profile is not Profile.LOCAL:
        raise ConfigurationError(
            "The public demo has no shared model key: add your own OpenRouter key in Settings."
        )
    key = settings.gemini_api_key if provider == "gemini" else settings.openrouter_api_key
    if key is None or not key.get_secret_value():
        raise ConfigurationError(f"{_ENV_NAMES[provider]} is not set for the local profile.")
    return key


def secret_box(settings: Settings) -> SecretBox:
    if settings.master_key is None:
        raise ConfigurationError("QC_MASTER_KEY is not set, so keys cannot be stored or read.")
    return SecretBox.from_base64(
        settings.master_key.get_secret_value(), version=settings.master_key_version
    )


def allowed_byok_providers(settings: Settings) -> tuple[Provider, ...]:
    """ADR-0016: while LLM_FREE_ONLY is on, only OpenRouter (free models) is allowed."""
    return ("openrouter",) if settings.llm_free_only else ("openrouter", "gemini")


@dataclass(frozen=True)
class UserCredential:
    """A user's own key, decrypted for one run. Never stored in state, events or logs."""

    credential_id: uuid.UUID
    provider: Provider
    model: str
    api_key: SecretStr

    def __repr__(self) -> str:  # never print the key, even by accident
        return f"UserCredential(id={self.credential_id}, provider={self.provider!r})"


async def resolve_user_credential(
    conn: AsyncConnection, settings: Settings, *, user_id: uuid.UUID, credential_id: uuid.UUID
) -> UserCredential:
    found = await creds.sealed_secret(conn, user_id=user_id, credential_id=credential_id)
    if found is None:
        raise ConfigurationError("The model key this run was started with has been removed.")
    summary, sealed = found
    provider: Provider = "gemini" if summary.provider == "gemini" else "openrouter"
    if provider not in allowed_byok_providers(settings):
        raise ConfigurationError("This provider is not allowed on this deployment (free only).")
    model = summary.default_model or settings.llm_model
    if settings.llm_free_only and not is_free_model(model):
        raise ConfigurationError("Only free models are allowed on this deployment (ADR-0016).")
    try:
        key = secret_box(settings).decrypt(sealed, aad=creds.aad(credential_id, user_id))
    except DecryptionError as exc:
        raise ConfigurationError("The stored model key cannot be decrypted.") from exc
    await creds.touch(conn, credential_id)
    return UserCredential(credential_id=credential_id, provider=provider, model=model, api_key=key)


async def move_credentials(
    conn: AsyncConnection, settings: Settings, *, from_user: uuid.UUID, to_user: uuid.UUID
) -> None:
    """Account linking: re-encrypt the anonymous user's keys for the account (the associated
    data binds a ciphertext to its user), unless the account already has a key for that
    provider. The anonymous copies are wiped either way."""
    for summary in await creds.list_credentials(conn, from_user):
        if await creds.get_active(conn, user_id=to_user, provider=summary.provider) is None:
            found = await creds.sealed_secret(conn, user_id=from_user, credential_id=summary.id)
            if found is not None:
                box = secret_box(settings)
                key = box.decrypt(found[1], aad=creds.aad(summary.id, from_user))
                await creds.replace_credential(
                    conn, box=box, user_id=to_user, provider=summary.provider,
                    api_key=key.get_secret_value(), default_model=summary.default_model,
                )  # fmt: skip
        await creds.wipe(conn, user_id=from_user, credential_id=summary.id)
