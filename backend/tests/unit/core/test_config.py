import base64
import os

import pytest
from pydantic import ValidationError

from querycure.core.config import Profile, Settings


def key() -> str:
    return base64.b64encode(os.urandom(32)).decode()


def test_defaults_are_local_profile(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("QC_PROFILE", raising=False)

    settings = Settings(_env_file=None)

    assert settings.profile is Profile.LOCAL
    assert settings.allow_private_targets is True
    assert settings.worker_concurrency == 2


def test_demo_profile_forbids_private_targets() -> None:
    with pytest.raises(ValidationError, match="ALLOW_PRIVATE_TARGETS"):
        Settings(_env_file=None, profile=Profile.DEMO, allow_private_targets=True, master_key=key())


def test_demo_profile_requires_master_key() -> None:
    with pytest.raises(ValidationError, match="QC_MASTER_KEY"):
        Settings(_env_file=None, profile=Profile.DEMO, allow_private_targets=False)


def test_demo_profile_defaults() -> None:
    settings = Settings(
        _env_file=None, profile=Profile.DEMO, allow_private_targets=False, master_key=key()
    )

    assert settings.worker_concurrency == 1
    assert settings.feature_live_inspection_public is False


def test_master_key_must_decode_to_32_bytes() -> None:
    with pytest.raises(ValidationError, match="32 bytes"):
        Settings(_env_file=None, master_key=base64.b64encode(b"short").decode())


def test_env_variables_are_read(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("QC_PROFILE", "local")
    monkeypatch.setenv("WORKER_CONCURRENCY", "3")
    monkeypatch.setenv("CORS_ORIGINS", '["http://localhost:3000"]')

    settings = Settings(_env_file=None)

    assert settings.worker_concurrency == 3
    assert settings.cors_origins == ["http://localhost:3000"]


def test_secrets_are_not_in_repr() -> None:
    k = key()
    settings = Settings(_env_file=None, master_key=k, database_url="postgresql://u:hunter2@h/db")

    assert k not in repr(settings)
    assert "hunter2" not in repr(settings)


def test_heartbeat_must_fit_twice_inside_the_lease() -> None:
    with pytest.raises(ValueError, match="WORKER_HEARTBEAT_SECONDS"):
        Settings(worker_lease_seconds=30, worker_heartbeat_seconds=15)


def test_worker_timing_defaults_are_consistent() -> None:
    settings = Settings()

    assert settings.worker_heartbeat_seconds * 2 < settings.worker_lease_seconds


def test_google_client_id_and_secret_must_be_set_together() -> None:
    with pytest.raises(ValidationError, match="GOOGLE_CLIENT_ID and GOOGLE_CLIENT_SECRET"):
        Settings(_env_file=None, google_client_id="abc.apps.googleusercontent.com")


def test_blank_google_secret_is_unset() -> None:
    settings = Settings(_env_file=None, google_client_secret="  ")  # noqa: S106 - blank on purpose

    assert settings.google_client_secret is None
    assert settings.google_login_enabled is False


def test_google_login_needs_https_public_urls_outside_local() -> None:
    with pytest.raises(ValidationError, match="PUBLIC_API_URL"):
        Settings(
            _env_file=None,
            profile=Profile.DEMO,
            allow_private_targets=False,
            master_key=key(),
            google_client_id="abc",
            google_client_secret="s",  # noqa: S106 - test value
            public_api_url="http://api.example.com",
            web_base_url="https://app.example.com",
        )


POOLED = "postgresql://qc_app:pw@ep-x-pooler.c-4.aws.neon.tech/db"
DIRECT = "postgresql://qc_app:pw@ep-x.c-4.aws.neon.tech/db"


def test_a_pooled_database_url_requires_a_direct_url_for_listen() -> None:
    with pytest.raises(ValidationError, match="DATABASE_URL_DIRECT"):
        Settings(_env_file=None, database_url=POOLED)


def test_a_pooled_database_url_with_a_direct_url_is_accepted() -> None:
    settings = Settings(_env_file=None, database_url=POOLED, database_url_direct=DIRECT)

    assert settings.direct_database_url() == DIRECT


def test_the_direct_url_must_not_be_a_pooled_endpoint() -> None:
    with pytest.raises(ValidationError, match="not a pooled"):
        Settings(_env_file=None, database_url=DIRECT, database_url_direct=POOLED)


def test_direct_url_falls_back_to_database_url_for_a_single_endpoint_setup() -> None:
    settings = Settings(_env_file=None, database_url=DIRECT)

    assert settings.direct_database_url() == DIRECT


def test_listen_url_prefers_the_direct_endpoint() -> None:
    from sqlalchemy.ext.asyncio import create_async_engine

    from querycure.api.deps import listen_url

    settings = Settings(_env_file=None, database_url=POOLED, database_url_direct=DIRECT)
    engine = create_async_engine(POOLED.replace("postgresql://", "postgresql+psycopg://"))

    assert listen_url(settings, engine) == DIRECT


def test_listen_url_falls_back_to_the_engine_url_when_none_is_configured() -> None:
    from sqlalchemy.ext.asyncio import create_async_engine

    from querycure.api.deps import listen_url

    engine = create_async_engine("postgresql+psycopg://u:pw@127.0.0.1:5432/d")

    assert listen_url(Settings(_env_file=None), engine) == "postgresql://u:pw@127.0.0.1:5432/d"


def test_an_empty_fallback_model_means_no_fallback(monkeypatch: pytest.MonkeyPatch) -> None:
    # .env.example ships `LLM_FALLBACK_MODEL=` (ADR-0026): empty must not fail the free guard.
    monkeypatch.setenv("LLM_FALLBACK_MODEL", "")
    assert Settings(_env_file=None).llm_fallback_model is None


def test_a_non_free_fallback_model_is_still_refused(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("LLM_FALLBACK_MODEL", "openai/gpt-5")
    with pytest.raises(ValueError, match="LLM_FALLBACK_MODEL"):
        Settings(_env_file=None)


@pytest.mark.parametrize(
    "field",
    [
        "SANDBOX_ADMIN_URL", "SANDBOX_BENCH_PASSWORD", "DATABASE_URL_DIRECT",
        "DATABASE_MIGRATION_URL", "DATABASE_RETENTION_URL", "OPENROUTER_API_KEY",
        "GEMINI_API_KEY", "GROQ_API_KEY",
    ],
)  # fmt: skip
def test_blank_optional_secrets_and_urls_are_unset(
    field: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    # 2026-10-18: SANDBOX_ADMIN_URL= became an empty URL, so the worker dialled the default
    # Unix socket instead of running without a sandbox.
    monkeypatch.setenv(field, "  ")
    settings = Settings(_env_file=None)
    assert getattr(settings, field.lower()) is None


def test_a_blank_master_key_still_fails_closed_in_the_demo_profile(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("QC_MASTER_KEY", "")
    with pytest.raises(ValueError, match="QC_MASTER_KEY"):
        Settings(_env_file=None, profile="demo", allow_private_targets=False)
