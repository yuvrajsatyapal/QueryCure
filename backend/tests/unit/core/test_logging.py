import io
import json

import pytest
from pydantic import SecretStr

from querydoctor.core.logging import configure_logging, get_logger

GOOGLE_KEY = "AIza" + "B" * 35
OPENROUTER_KEY = "sk-or-v1-" + "a" * 64


def emit(**fields: object) -> dict[str, object]:
    buf = io.StringIO()
    configure_logging(level="DEBUG", stream=buf)
    get_logger("test").info("event", **fields)
    line = buf.getvalue().strip().splitlines()[-1]
    parsed: dict[str, object] = json.loads(line)
    return parsed


@pytest.mark.parametrize(
    "key",
    [
        "password",
        "db_password",
        "api_key",
        "apiKey",
        "secret",
        "token",
        "authorization",
        "dsn",
        "master_key",
        "cookie",
        "credentials",
    ],
)
def test_sensitive_keys_are_redacted(key: str) -> None:
    out = emit(**{key: "hunter2"})

    assert out[key] == "[REDACTED]"
    assert "hunter2" not in json.dumps(out)


def test_nested_sensitive_keys_are_redacted() -> None:
    out = emit(conn={"host": "db", "password": "hunter2"}, items=[{"token": "t0k"}])

    assert out["conn"] == {"host": "db", "password": "[REDACTED]"}
    assert out["items"] == [{"token": "[REDACTED]"}]


@pytest.mark.parametrize(
    ("value", "leak"),
    [
        ("postgresql://alice:hunter2@db:5432/app", "hunter2"),
        ("postgres://alice:p%40ss@db/app?sslmode=require", "p%40ss"),
        (f"calling gemini with {GOOGLE_KEY}", GOOGLE_KEY),
        (f"key={OPENROUTER_KEY}", OPENROUTER_KEY),
        ("Authorization: Bearer abc.def.ghi", "abc.def.ghi"),
    ],
)
def test_secret_patterns_inside_values_are_masked(value: str, leak: str) -> None:
    out = emit(detail=value)

    assert leak not in json.dumps(out)


def test_dsn_mask_keeps_non_secret_parts() -> None:
    out = emit(detail="postgresql://alice:hunter2@db:5432/app")

    assert out["detail"] == "postgresql://alice:[REDACTED]@db:5432/app"


def test_secretstr_is_never_rendered() -> None:
    out = emit(note=SecretStr("hunter2"))

    assert "hunter2" not in json.dumps(out)


def test_exception_messages_are_redacted() -> None:
    buf = io.StringIO()
    configure_logging(level="DEBUG", stream=buf)
    try:
        raise RuntimeError("connect failed for postgresql://u:hunter2@h/db")
    except RuntimeError:
        get_logger("test").exception("boom")

    assert "hunter2" not in buf.getvalue()


def test_log_lines_carry_utc_timestamp_and_level() -> None:
    out = emit(run_id="r1")

    assert out["level"] == "info"
    assert str(out["timestamp"]).endswith("Z")
    assert out["run_id"] == "r1"
