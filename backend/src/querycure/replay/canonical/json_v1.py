"""Profile `qc-json-v1`: RFC 8785 (JCS) plus QueryCure input restrictions. FROZEN.

Any change to the bytes this module produces requires a new profile (`qc-json-v2`); keep this file.
"""

import math
from decimal import Decimal
from typing import Any

from querycure.replay.canonical.errors import CanonicalizationError

PROFILE = "qc-json-v1"
MAX_SAFE_INTEGER = 2**53 - 1
_ESCAPES = {
    '"': '\\"',
    "\\": "\\\\",
    "\b": "\\b",
    "\f": "\\f",
    "\n": "\\n",
    "\r": "\\r",
    "\t": "\\t",
}


def _check_unicode(text: str) -> None:
    try:
        text.encode("utf-8")
    except UnicodeEncodeError as exc:
        raise CanonicalizationError("string contains a lone surrogate") from exc


def _string(text: str) -> str:
    _check_unicode(text)
    out = ['"']
    for ch in text:
        if ch in _ESCAPES:
            out.append(_ESCAPES[ch])
        elif ord(ch) < 0x20:
            out.append(f"\\u{ord(ch):04x}")
        else:
            out.append(ch)
    out.append('"')
    return "".join(out)


def _float(value: float) -> str:
    """ECMAScript Number::toString (RFC 8785 §3.2.2.3) from Python's shortest round-trip digits."""
    if not math.isfinite(value):
        raise CanonicalizationError("NaN and Infinity are not allowed")
    if value == 0:
        return "0"
    if value < 0:
        return "-" + _float(-value)
    _, digit_tuple, exponent = Decimal(repr(value)).as_tuple()
    if not isinstance(exponent, int):  # only NaN/Infinity have symbolic exponents
        raise CanonicalizationError("NaN and Infinity are not allowed")
    digits = list(digit_tuple)
    while len(digits) > 1 and digits[-1] == 0:
        digits.pop()
        exponent += 1
    text = "".join(map(str, digits))
    k = len(digits)
    n = exponent + k
    if k <= n <= 21:
        return text + "0" * (n - k)
    if 0 < n <= 21:
        return f"{text[:n]}.{text[n:]}"
    if -6 < n <= 0:
        return "0." + "0" * -n + text
    e = n - 1
    mantissa = text if k == 1 else f"{text[0]}.{text[1:]}"
    return f"{mantissa}e{'+' if e >= 0 else '-'}{abs(e)}"


def _serialize(value: Any, out: list[str]) -> None:
    if value is None:
        out.append("null")
    elif value is True:
        out.append("true")
    elif value is False:
        out.append("false")
    elif isinstance(value, int):
        if abs(value) > MAX_SAFE_INTEGER:
            raise CanonicalizationError("integers beyond ±(2^53-1) must be encoded as strings")
        out.append(str(value))
    elif isinstance(value, float):
        out.append(_float(value))
    elif isinstance(value, str):
        out.append(_string(value))
    elif isinstance(value, list):
        out.append("[")
        for i, item in enumerate(value):
            if i:
                out.append(",")
            _serialize(item, out)
        out.append("]")
    elif isinstance(value, dict):
        keys = list(value.keys())
        if not all(isinstance(k, str) for k in keys):
            raise CanonicalizationError("object keys must be strings")
        for key in keys:
            _check_unicode(key)
        out.append("{")
        for i, key in enumerate(sorted(keys, key=lambda k: k.encode("utf-16-be"))):
            if i:
                out.append(",")
            out.append(_string(key))
            out.append(":")
            _serialize(value[key], out)
        out.append("}")
    else:
        raise CanonicalizationError(
            f"{type(value).__name__} is not a JSON primitive; convert it with to_canonical() first"
        )


def canonical_json(value: Any) -> bytes:
    out: list[str] = []
    try:
        _serialize(value, out)
    except RecursionError as exc:
        raise CanonicalizationError("value is nested too deeply") from exc
    return "".join(out).encode("utf-8")
