"""Profile `qc-row-v1`: result-row values for benchmark correctness fingerprints. FROZEN.

Each value becomes a token `tag (1 byte) ‖ len(payload) (8 bytes, big-endian) ‖ payload`;
the row hash is SHA-256 over the row's tokens in column order (REPLAY_ENGINE §2.2). Kinds are
chosen from the column's PostgreSQL type, never from the Python value (a JSON array and a
PostgreSQL array are both lists). Any change to these bytes needs a new profile.

| kind | tag | payload |
|---|---|---|
| NULL (any kind) | N | empty |
| int (int2/4/8, oid) | i | decimal |
| float (float4/8) | f | ECMAScript shortest round-trip; NaN, Infinity, -Infinity |
| numeric | n | canonical decimal (no exponent, no trailing zeros); NaN, Infinity, -Infinity |
| text (text, varchar, bpchar, name) | s | raw UTF-8 |
| timestamptz | T | UTC, `YYYY-MM-DDTHH:MM:SS.ffffffZ` |
| timestamp | t | same, without `Z` |
| date | d | `YYYY-MM-DD` |
| bool | b | `t` / `f` |
| bytea | x | lowercase hex |
| json, jsonb | j | qc-json-v1 of the parsed text; `o` + text outside its domain (ints > 2^53) |
| uuid | u | lowercase, hyphenated |
| `<kind>[]` | a | element count (8 bytes, big-endian) ‖ element tokens, recursively |
| other | o | PostgreSQL text output under the pinned session settings |
"""

import datetime as dt
import hashlib
import json
import math
import uuid
from collections.abc import Sequence
from decimal import Decimal
from typing import Any

from querycure.replay.canonical.errors import CanonicalizationError
from querycure.replay.canonical.json_v1 import _float, canonical_json

PROFILE = "qc-row-v1"
SCALAR_KINDS = frozenset(
    {
        "int",
        "float",
        "numeric",
        "text",
        "timestamptz",
        "timestamp",
        "date",
        "bool",
        "bytea",
        "json",
        "uuid",
        "other",
    }
)


def _token(tag: bytes, payload: bytes) -> bytes:
    return tag + len(payload).to_bytes(8, "big") + payload


def _float_text(value: float) -> str:
    if math.isnan(value):
        return "NaN"
    if math.isinf(value):
        return "Infinity" if value > 0 else "-Infinity"
    return _float(value)


def _numeric_text(value: Decimal) -> str:
    if value.is_nan():
        return "NaN"
    if value.is_infinite():
        return "Infinity" if value > 0 else "-Infinity"
    if value.is_zero():
        return "0"
    return format(value.normalize(), "f")


def _clock(value: dt.datetime) -> str:
    return (
        f"{value.year:04d}-{value.month:02d}-{value.day:02d}T"
        f"{value.hour:02d}:{value.minute:02d}:{value.second:02d}.{value.microsecond:06d}"
    )


def _scalar(kind: str, value: Any) -> tuple[bytes, str | bytes]:
    match kind:
        case "int":
            return b"i", str(int(value))
        case "float":
            return b"f", _float_text(float(value))
        case "numeric":
            return b"n", _numeric_text(Decimal(value))
        case "text" | "other":
            return (b"s" if kind == "text" else b"o"), str(value)
        case "timestamptz":
            if value.tzinfo is None or value.utcoffset() is None:
                raise ValueError("timestamptz value must be timezone-aware")
            return b"T", _clock(value.astimezone(dt.UTC)) + "Z"
        case "timestamp":
            return b"t", _clock(value)
        case "date":
            return b"d", f"{value.year:04d}-{value.month:02d}-{value.day:02d}"
        case "bool":
            return b"b", "t" if value else "f"
        case "bytea":
            return b"x", bytes(value).hex()
        case "json":
            if not isinstance(value, str):
                return b"j", canonical_json(value)
            try:
                return b"j", canonical_json(json.loads(value))
            except (CanonicalizationError, ValueError):
                return b"o", value  # e.g. integers beyond 2^53: hashed by their text form
        case "uuid":
            return b"u", str(uuid.UUID(str(value)))
    raise ValueError(f"unknown qc-row-v1 kind {kind!r}")


def encode_value(kind: str, value: Any) -> bytes:
    if kind.endswith("[]"):
        if value is None:
            return _token(b"N", b"")
        element = kind[:-2]
        items = b"".join(encode_value(element, v) for v in value)
        return _token(b"a", len(value).to_bytes(8, "big") + items)
    if kind not in SCALAR_KINDS:
        raise ValueError(f"unknown qc-row-v1 kind {kind!r}")
    if value is None:
        return _token(b"N", b"")
    tag, payload = _scalar(kind, value)
    return _token(tag, payload.encode("utf-8") if isinstance(payload, str) else payload)


def row_hash(kinds: Sequence[str], row: Sequence[Any]) -> bytes:
    if len(kinds) != len(row):
        raise ValueError("row width does not match its column kinds")
    h = hashlib.sha256()
    for kind, value in zip(kinds, row, strict=True):
        h.update(encode_value(kind, value))
    return h.digest()
