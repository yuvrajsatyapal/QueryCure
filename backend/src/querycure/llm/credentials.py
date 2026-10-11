from typing import Literal

from pydantic import SecretStr

from querycure.core.config import Profile, Settings
from querycure.core.errors import ConfigurationError

Provider = Literal["gemini", "openrouter"]

_ENV_NAMES: dict[Provider, str] = {"gemini": "GEMINI_API_KEY", "openrouter": "OPENROUTER_API_KEY"}


def resolve_api_key(settings: Settings, provider: Provider) -> SecretStr:
    """Resolved per run by the worker and kept out of graph state, events and logs."""
    if settings.profile is not Profile.LOCAL:
        raise ConfigurationError("The public demo uses your own API key (available in Phase 5).")
    key = settings.gemini_api_key if provider == "gemini" else settings.openrouter_api_key
    if key is None or not key.get_secret_value():
        raise ConfigurationError(f"{_ENV_NAMES[provider]} is not set for the local profile.")
    return key
