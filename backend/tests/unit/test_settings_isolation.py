"""Tests never read the developer's `.env`: it can point at a hosted database (Neon)."""

import ast
from pathlib import Path

TESTS = Path(__file__).parents[1]


def _settings_calls_reading_env_file() -> list[str]:
    offenders = []
    for path in sorted(TESTS.rglob("*.py")):
        for node in ast.walk(ast.parse(path.read_text())):
            if not isinstance(node, ast.Call):
                continue
            name = getattr(node.func, "id", getattr(node.func, "attr", None))
            if name != "Settings":
                continue
            keywords = {k.arg for k in node.keywords}
            # `None` is a `**kwargs` splat; its dict is checked where it is built.
            if "_env_file" not in keywords and None not in keywords:
                offenders.append(f"{path.relative_to(TESTS)}:{node.lineno}")
    return offenders


def test_every_settings_in_tests_ignores_the_env_file() -> None:
    assert _settings_calls_reading_env_file() == []
