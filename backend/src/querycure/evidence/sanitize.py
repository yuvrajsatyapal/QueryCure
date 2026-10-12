"""Rendering untrusted names and text into evidence summaries and prompts (SECURITY §6.2)."""

import math
import re
from collections.abc import Mapping

_PLAIN_IDENT = re.compile(r"^[a-z_][a-z0-9_$]*$")
_CONTROL = re.compile("[\\x00-\\x1f\\x7f-\\x9f\\u2028\\u2029]")
MAX_IDENT_CHARS = 63
MAX_TEXT_CHARS = 200
MAX_ARG_KEYS = 10
MAX_ARG_ITEMS = 20
MAX_ARG_KEY_CHARS = 64

ArgScalar = str | int | float | bool | None
ArgValue = ArgScalar | list[ArgScalar]


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


def _clean_scalar(value: object) -> ArgScalar:
    if value is None or isinstance(value, bool | int):
        return value
    if isinstance(value, float) and math.isfinite(value):
        return value
    return clean_text(value if isinstance(value, str) else str(value))


def clean_args(args: Mapping[str, object]) -> dict[str, ArgValue]:
    """Model-supplied tool arguments as persisted: bounded, text cleaned, JSON types kept.

    Keeping numbers and lists (rather than stringifying everything) lets an audit re-validate
    the stored arguments against the tool's input model. Every bound sits above the tools' own
    limits, so clipping never turns invalid arguments into valid ones. No tool takes nested
    objects, so those are flattened to text.
    """
    cleaned: dict[str, ArgValue] = {}
    for key, value in list(args.items())[:MAX_ARG_KEYS]:
        name = clean_text(str(key), MAX_ARG_KEY_CHARS)
        if isinstance(value, list):
            cleaned[name] = [
                _clean_scalar(v if not isinstance(v, list | dict) else str(v))
                for v in value[:MAX_ARG_ITEMS]
            ]
        else:
            cleaned[name] = _clean_scalar(value)
    return cleaned
