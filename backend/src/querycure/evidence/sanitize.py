"""Rendering untrusted names and text into evidence summaries and prompts (SECURITY §6.2)."""

import re

_PLAIN_IDENT = re.compile(r"^[a-z_][a-z0-9_$]*$")
_CONTROL = re.compile("[\\x00-\\x1f\\x7f-\\x9f\\u2028\\u2029]")
MAX_IDENT_CHARS = 63
MAX_TEXT_CHARS = 200


def clean_text(value: str, limit: int = MAX_TEXT_CHARS) -> str:
    """Control characters (newlines included) become spaces; long text is cut with an ellipsis."""
    flat = _CONTROL.sub(" ", value)
    return flat if len(flat) <= limit else flat[: limit - 1] + "…"


def quote_ident(name: str) -> str:
    """PostgreSQL-style: plain lower-case names stay bare, anything else is double-quoted."""
    # PostgreSQL truncates identifiers to NAMEDATALEN-1 bytes without a marker; so do we.
    name = clean_text(name, len(name) + 1)[:MAX_IDENT_CHARS]
    if _PLAIN_IDENT.match(name):
        return name
    return '"' + name.replace('"', '""') + '"'


def qualified(schema: str | None, name: str) -> str:
    return f"{quote_ident(schema)}.{quote_ident(name)}" if schema else quote_ident(name)
