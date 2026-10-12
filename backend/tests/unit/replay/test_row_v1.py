"""qc-row-v1 golden vectors (REPLAY_ENGINE §2.2). A failing vector means the profile changed:
the fix is a new profile, never an edit."""

import datetime as dt
import hashlib
import uuid
from decimal import Decimal

import pytest

from querycure.replay.canonical.row_v1 import encode_value, row_hash


def _token(tag: bytes, payload: bytes) -> bytes:
    return tag + len(payload).to_bytes(8, "big") + payload


@pytest.mark.parametrize(
    ("kind", "value", "tag", "payload"),
    [
        ("int", 42, b"i", b"42"),
        ("int", -7, b"i", b"-7"),
        ("float", 0.1, b"f", b"0.1"),
        ("float", 1e21, b"f", b"1e+21"),
        ("float", 1.5e-7, b"f", b"1.5e-7"),
        ("float", 2.0, b"f", b"2"),
        ("float", -0.0, b"f", b"0"),
        ("float", float("nan"), b"f", b"NaN"),
        ("float", float("inf"), b"f", b"Infinity"),
        ("float", float("-inf"), b"f", b"-Infinity"),
        ("numeric", Decimal("12.50"), b"n", b"12.5"),
        ("numeric", Decimal("0.00"), b"n", b"0"),
        ("numeric", Decimal("1E+3"), b"n", b"1000"),
        ("numeric", Decimal("NaN"), b"n", b"NaN"),
        ("text", "é\x00x", b"s", "é\x00x".encode()),
        ("text", "", b"s", b""),
        (
            "timestamptz",
            dt.datetime(2026, 1, 1, 5, 30, tzinfo=dt.timezone(dt.timedelta(hours=5, minutes=30))),
            b"T",
            b"2026-01-01T00:00:00.000000Z",
        ),
        ("timestamp", dt.datetime(2026, 1, 2, 3, 4, 5, 6), b"t", b"2026-01-02T03:04:05.000006"),
        ("date", dt.date(2026, 3, 9), b"d", b"2026-03-09"),
        ("bool", True, b"b", b"t"),
        ("bool", False, b"b", b"f"),
        ("bytea", b"\x00\xff", b"x", b"00ff"),
        ("json", {"b": 1, "a": [True, None]}, b"j", b'{"a":[true,null],"b":1}'),
        (
            "uuid",
            uuid.UUID("A0EEBC99-9C0B-4EF8-BB6D-6BB9BD380A11"),
            b"u",
            b"a0eebc99-9c0b-4ef8-bb6d-6bb9bd380a11",
        ),
        ("other", "1 day 02:00:00", b"o", b"1 day 02:00:00"),
    ],
)
def test_scalar_tokens(kind: str, value: object, tag: bytes, payload: bytes) -> None:
    assert encode_value(kind, value) == _token(tag, payload)


def test_null_is_distinct_from_every_value() -> None:
    null = encode_value("text", None)

    assert null == _token(b"N", b"")
    assert null != encode_value("text", "")
    assert null != encode_value("text", "NULL")


def test_arrays_are_recursive_with_a_count() -> None:
    inner = _token(b"i", b"1") + _token(b"N", b"")
    expected = _token(b"a", (2).to_bytes(8, "big") + inner)

    assert encode_value("int[]", [1, None]) == expected


def test_length_prefix_prevents_concatenation_collisions() -> None:
    assert row_hash(["text", "text"], ("ab", "c")) != row_hash(["text", "text"], ("a", "bc"))


def test_row_hash_golden_vector() -> None:
    row = (1024, "paid", Decimal("19.90"), None)
    kinds = ["int", "text", "numeric", "timestamptz"]
    expected = hashlib.sha256(
        _token(b"i", b"1024") + _token(b"s", b"paid") + _token(b"n", b"19.9") + _token(b"N", b"")
    ).digest()

    assert row_hash(kinds, row) == expected
    assert expected.hex() == "31cb7572764a58b6b4538c8b530d0c7a68016fc43ff407fba18b3cd25d61577e"


def test_naive_timestamptz_is_refused() -> None:
    with pytest.raises(ValueError, match="timezone"):
        encode_value("timestamptz", dt.datetime(2026, 1, 1))


def test_unknown_kind_is_refused() -> None:
    with pytest.raises(ValueError, match="kind"):
        encode_value("money", "1.00")


def test_json_text_is_parsed_and_canonicalized() -> None:
    assert encode_value("json", '{"b": 1, "a": 2.50}') == _token(b"j", b'{"a":2.5,"b":1}')


def test_json_beyond_the_canonical_domain_falls_back_to_text() -> None:
    raw = '{"big": 9007199254740993}'

    assert encode_value("json", raw) == _token(b"o", raw.encode())
