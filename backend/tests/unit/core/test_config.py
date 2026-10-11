import base64
import os

import pytest
from pydantic import ValidationError

from querydoctor.core.config import Profile, Settings


def key() -> str:
    return base64.b64encode(os.urandom(32)).decode()


def test_defaults_are_local_profile(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("QD_PROFILE", raising=False)

    settings = Settings(_env_file=None)

    assert settings.profile is Profile.LOCAL
    assert settings.allow_private_targets is True
    assert settings.worker_concurrency == 2


def test_demo_profile_forbids_private_targets() -> None:
    with pytest.raises(ValidationError, match="ALLOW_PRIVATE_TARGETS"):
        Settings(_env_file=None, profile=Profile.DEMO, allow_private_targets=True, master_key=key())


def test_demo_profile_requires_master_key() -> None:
    with pytest.raises(ValidationError, match="QD_MASTER_KEY"):
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
    monkeypatch.setenv("QD_PROFILE", "local")
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
