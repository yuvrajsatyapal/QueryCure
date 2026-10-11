"""Typed value -> JSON primitive conversion (REPLAY_ENGINE §2.1 rules 5-6). Formatting is explicit
here so Pydantic or stdlib upgrades cannot change canonical bytes."""

import base64
import datetime as dt
import enum
import uuid
from collections.abc import Mapping
from decimal import Decimal
from typing import Any

from pydantic import BaseModel

from querydoctor.replay.canonical.errors import CanonicalizationError


def _instant(value: dt.datetime) -> str:
    if value.tzinfo is None or value.utcoffset() is None:
        raise CanonicalizationError("naive datetime; timestamps must be timezone-aware")
    u = value.astimezone(dt.UTC)
    return (
        f"{u.year:04d}-{u.month:02d}-{u.day:02d}T"
        f"{u.hour:02d}:{u.minute:02d}:{u.second:02d}.{u.microsecond:06d}Z"
    )


def _decimal(value: Decimal) -> str:
    if not value.is_finite():
        raise CanonicalizationError("decimal must be finite")
    if value.is_zero():
        return "0"
    return format(value.normalize(), "f")


def to_canonical(value: Any) -> Any:
    if value is None or isinstance(value, bool | int | float | str):
        return value
    if isinstance(value, enum.Enum):
        return to_canonical(value.value)
    if isinstance(value, dt.datetime):
        return _instant(value)
    if isinstance(value, dt.date):
        return f"{value.year:04d}-{value.month:02d}-{value.day:02d}"
    if isinstance(value, uuid.UUID):
        return str(value)
    if isinstance(value, Decimal):
        return _decimal(value)
    if isinstance(value, bytes):
        return base64.urlsafe_b64encode(value).rstrip(b"=").decode("ascii")
    if isinstance(value, BaseModel):
        return to_canonical(value.model_dump(mode="python"))
    if isinstance(value, Mapping):
        if not all(isinstance(k, str) for k in value):
            raise CanonicalizationError("object keys must be strings")
        return {k: to_canonical(v) for k, v in value.items()}
    if isinstance(value, set | frozenset):
        raise CanonicalizationError("sets have no order; sort into a list explicitly")
    if isinstance(value, list | tuple):
        return [to_canonical(v) for v in value]
    raise CanonicalizationError(f"cannot canonicalize {type(value).__name__}")
