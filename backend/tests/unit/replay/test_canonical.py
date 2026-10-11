import datetime as dt
import enum
import hashlib
import json
import struct
import uuid
from decimal import Decimal
from pathlib import Path
from typing import Any

import pytest

from querydoctor.replay.canonical import (
    CanonicalizationError,
    canonical_json,
    canonical_raw,
    canonical_text,
    to_canonical,
)
from querydoctor.replay.digest import digest

FIXTURES = Path(__file__).parents[2] / "fixtures" / "canonical"


def vectors(name: str) -> list[dict[str, Any]]:
    data: list[dict[str, Any]] = json.loads((FIXTURES / name).read_text())["vectors"]
    return data


def hex_to_float(bits: str) -> float:
    value: float = struct.unpack(">d", bytes.fromhex(bits))[0]
    return value


# --- qd-json-v1 golden vectors -------------------------------------------------------


@pytest.mark.parametrize("case", vectors("qd_json_v1.json"), ids=lambda c: c["name"])
def test_json_golden_vectors(case: dict[str, Any]) -> None:
    out = canonical_json(json.loads(case["input"]))

    assert out == case["canonical"].encode()
    assert digest("qd-json-v1", out) == case["digest"]


@pytest.mark.parametrize(
    ("bits", "expected"), json.loads((FIXTURES / "rfc8785_numbers.json").read_text())["vectors"]
)
def test_rfc8785_number_serialization(bits: str, expected: str | None) -> None:
    value = hex_to_float(bits)
    if expected is None:
        with pytest.raises(CanonicalizationError):
            canonical_json(value)
    else:
        assert canonical_json(value) == expected.encode()


def test_lone_surrogates_are_rejected() -> None:
    with pytest.raises(CanonicalizationError):
        canonical_json({"k": "\ud800"})
    with pytest.raises(CanonicalizationError):
        canonical_json({"\udfff": 1})


@pytest.mark.parametrize("value", [2**53, -(2**53), 10**30])
def test_integers_beyond_2_53_must_be_strings(value: int) -> None:
    with pytest.raises(CanonicalizationError, match="2\\^53"):
        canonical_json(value)


@pytest.mark.parametrize(
    "value",
    [
        dt.datetime(2026, 1, 1, tzinfo=dt.UTC),
        uuid.uuid4(),
        Decimal("1.5"),
        {1, 2},
        (1, 2),
        b"x",
        object(),
    ],
)
def test_canonicalizer_accepts_only_json_primitives(value: Any) -> None:
    with pytest.raises(CanonicalizationError):
        canonical_json({"v": value})


def test_non_string_keys_are_rejected() -> None:
    with pytest.raises(CanonicalizationError):
        canonical_json({1: "a"})


def test_bool_is_not_treated_as_integer() -> None:
    assert canonical_json([True, False, None]) == b"[true,false,null]"


def test_output_is_independent_of_dict_insertion_order() -> None:
    assert canonical_json({"b": 1, "a": 2}) == canonical_json({"a": 2, "b": 1})


# --- typed encoders (rules 5-6) ------------------------------------------------------


class Color(enum.StrEnum):
    RED = "red"


def test_typed_values_encode_per_spec() -> None:
    out = to_canonical(
        {
            "at": dt.datetime(2026, 10, 11, 12, 0, 0, 5, tzinfo=dt.UTC),
            "at_offset": dt.datetime(
                2026, 10, 11, 14, 0, tzinfo=dt.timezone(dt.timedelta(hours=2))
            ),
            "day": dt.date(2026, 10, 11),
            "id": uuid.UUID("6F9619FF-8B86-D011-B42D-00CF4FC964FF"),
            "color": Color.RED,
            "amounts": [Decimal("12.500"), Decimal("0E-5"), Decimal("-0"), Decimal("1E+3")],
            "blob": b"\xff\xfe",
            "pair": (1, 2),
        }
    )

    assert out == {
        "at": "2026-10-11T12:00:00.000005Z",
        "at_offset": "2026-10-11T12:00:00.000000Z",
        "day": "2026-10-11",
        "id": "6f9619ff-8b86-d011-b42d-00cf4fc964ff",
        "color": "red",
        "amounts": ["12.5", "0", "0", "1000"],
        "blob": "__4",
        "pair": [1, 2],
    }


def test_naive_datetime_is_rejected() -> None:
    with pytest.raises(CanonicalizationError, match="naive"):
        to_canonical(dt.datetime(2026, 1, 1))


def test_sets_are_rejected_because_order_is_undefined() -> None:
    with pytest.raises(CanonicalizationError, match="sort"):
        to_canonical({"ids": {"a", "b"}})


def test_pydantic_models_encode_through_python_values() -> None:
    from pydantic import BaseModel

    class Snapshot(BaseModel):
        taken_at: dt.datetime
        rows: int
        note: str | None = None

    out = to_canonical(Snapshot(taken_at=dt.datetime(2026, 1, 1, tzinfo=dt.UTC), rows=3))

    assert out == {"note": None, "rows": 3, "taken_at": "2026-01-01T00:00:00.000000Z"}


# --- qd-text-v1 / qd-raw-v1 ----------------------------------------------------------


@pytest.mark.parametrize("case", vectors("qd_text_v1.json"), ids=lambda c: c["name"])
def test_text_golden_vectors(case: dict[str, Any]) -> None:
    out = canonical_text(case["input"])

    assert out == case["canonical"].encode()
    assert digest("qd-text-v1", out) == case["digest"]


def test_text_rejects_bom_and_surrogates() -> None:
    with pytest.raises(CanonicalizationError):
        canonical_text("﻿report")
    with pytest.raises(CanonicalizationError):
        canonical_text("bad \ud800")


@pytest.mark.parametrize("case", vectors("qd_raw_v1.json"), ids=lambda c: c["name"])
def test_raw_golden_vectors(case: dict[str, Any]) -> None:
    out = canonical_raw(case["input"].encode())

    assert out == case["input"].encode()
    assert digest("qd-raw-v1", out) == case["digest"]


@pytest.mark.parametrize("data", [b"\xff\xfe", b"\xef\xbb\xbfSELECT 1", b"SELECT '\xed\xa0\x80'"])
def test_raw_rejects_invalid_utf8_bom_and_encoded_surrogates(data: bytes) -> None:
    with pytest.raises(CanonicalizationError):
        canonical_raw(data)


# --- digest ---------------------------------------------------------------------------


def test_digest_is_profile_tagged_sha256() -> None:
    body = b"{}"

    assert digest("qd-json-v1", body) == hashlib.sha256(b"qd-json-v1\n{}").hexdigest()
    assert digest("qd-json-v1", body) != digest("qd-raw-v1", body)


def test_digest_rejects_unknown_profile() -> None:
    with pytest.raises(CanonicalizationError, match="unknown profile"):
        digest("qd-json-v9", b"{}")
