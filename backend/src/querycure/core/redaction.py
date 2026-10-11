import re
from collections.abc import Mapping, MutableMapping
from typing import Any

from pydantic import SecretBytes, SecretStr

REDACTED = "[REDACTED]"

_SENSITIVE_KEY = re.compile(
    r"pass(word)?|secret|token|api_?key|authorization|dsn|master_?key|cookie|credential",
    re.IGNORECASE,
)
# user:password@ inside any URL-ish connection string; keeps scheme, user and host readable.
_URL_PASSWORD = re.compile(
    r"(?P<prefix>[a-z][a-z0-9+.-]*://[^:/@\s]+:)(?P<secret>[^@\s]+)(?=@)", re.I
)
_VALUE_PATTERNS = (
    re.compile(r"AIza[0-9A-Za-z_\-]{35}"),  # Google API keys (Gemini)
    re.compile(r"sk-or-v1-[0-9a-f]{64}"),  # OpenRouter keys
    re.compile(r"\bsk-[A-Za-z0-9_\-]{20,}"),  # generic sk- style keys
    re.compile(r"(?<=Bearer )[A-Za-z0-9._~+/=\-]+"),
)


def redact_text(text: str) -> str:
    text = _URL_PASSWORD.sub(lambda m: m.group("prefix") + REDACTED, text)
    for pattern in _VALUE_PATTERNS:
        text = pattern.sub(REDACTED, text)
    return text


def redact_value(value: Any) -> Any:
    if isinstance(value, SecretStr | SecretBytes):
        return REDACTED
    if isinstance(value, str):
        return redact_text(value)
    if isinstance(value, Mapping):
        return {
            k: REDACTED if isinstance(k, str) and _SENSITIVE_KEY.search(k) else redact_value(v)
            for k, v in value.items()
        }
    if isinstance(value, list | tuple):
        return [redact_value(v) for v in value]
    return value


def redaction_processor(
    _logger: Any, _method: str, event_dict: MutableMapping[str, Any]
) -> dict[str, Any]:
    """structlog processor. Runs after exception formatting so tracebacks are scrubbed too."""
    redacted: dict[str, Any] = redact_value(event_dict)
    return redacted
