"""Startup validation for hosted (non-local) profiles: a misconfigured deployment must refuse
to start rather than run with a wildcard CORS policy, plain-http origins or no database."""

import base64
import os
from typing import Any

import pytest
from pydantic import ValidationError

from querycure.api.main import create_app
from querycure.core.config import Profile, Settings, serving_problems

DB = "postgresql://qc_app:pw@db.example.dev/querycure"
TOKEN = "t" * 32


def demo(**overrides: Any) -> Settings:
    values: dict[str, Any] = {
        "profile": Profile.DEMO,
        "allow_private_targets": False,
        "master_key": base64.b64encode(os.urandom(32)).decode(),
        "database_url": DB,
        "cors_origins": ["https://app.example.dev"],
    }
    return Settings(_env_file=None, **(values | overrides))


def test_a_complete_demo_configuration_has_no_problems() -> None:
    settings = demo(
        public_api_url="https://api.example.dev",
        web_base_url="https://app.example.dev",
        cookie_domain=".example.dev",
        metrics_token=TOKEN,
    )
    assert serving_problems(settings) == []


@pytest.mark.parametrize(
    "origin",
    ["*", "http://app.example.dev", "https://app.example.dev/", "https://app.example.dev/x",
     "app.example.dev", "https://u:p@app.example.dev"],
)  # fmt: skip
def test_cors_origins_must_be_https_bare_origins(origin: str) -> None:
    with pytest.raises(ValidationError, match="CORS_ORIGINS"):
        demo(cors_origins=[origin])


def test_loopback_http_stays_allowed_for_the_local_demo_stack() -> None:
    settings = demo(cors_origins=["http://localhost:3300"], public_api_url="http://127.0.0.1:8300")
    assert serving_problems(settings) == []


def test_local_profile_is_unchanged() -> None:
    settings = Settings(_env_file=None, cors_origins=["*"], metrics_token="short")  # noqa: S106 - test value
    assert settings.cors_origins == ["*"]
    assert serving_problems(settings) == []


@pytest.mark.parametrize("name", ["public_api_url", "web_base_url"])
def test_public_urls_must_be_https_outside_loopback(name: str) -> None:
    with pytest.raises(ValidationError, match=name.upper()):
        demo(**{name: "http://api.example.dev"})


@pytest.mark.parametrize("value", ["https://example.dev", "example.dev:443", "example.dev/"])
def test_cookie_domain_is_a_bare_domain(value: str) -> None:
    with pytest.raises(ValidationError, match="COOKIE_DOMAIN"):
        demo(cookie_domain=value)


def test_a_short_metrics_token_is_refused() -> None:
    with pytest.raises(ValidationError, match="METRICS_TOKEN"):
        demo(metrics_token="m-token")  # noqa: S106 - test value


def test_the_web_origin_must_be_allowed_by_cors() -> None:
    with pytest.raises(ValidationError, match="WEB_BASE_URL"):
        demo(web_base_url="https://other.example.dev")


def test_serving_problems_name_every_missing_variable() -> None:
    problems = serving_problems(demo(database_url=None, cors_origins=[]))
    assert any("DATABASE_URL" in p for p in problems)
    assert any("CORS_ORIGINS" in p for p in problems)


def test_the_api_refuses_to_start_without_its_required_settings() -> None:
    with pytest.raises(RuntimeError, match="DATABASE_URL"):
        create_app(demo(database_url=None))
