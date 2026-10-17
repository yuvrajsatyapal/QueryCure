"""ADR-0020: the worker records which path it benchmarks through, in the fingerprint."""

import pytest
from pydantic import ValidationError

from querycure.core.config import Settings
from querycure.jobs.handlers import engine_options


def test_host_worker_defaults_to_the_relay_path() -> None:
    settings = Settings(_env_file=None)  # type: ignore[call-arg]

    assert settings.bench_path == "docker-relay"
    assert engine_options(settings).container_runtime == "docker-relay"


def test_container_worker_records_the_in_network_path(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("QC_BENCH_PATH", "docker-network")

    settings = Settings(_env_file=None)  # type: ignore[call-arg]

    assert engine_options(settings).container_runtime == "docker-network"


def test_unknown_bench_path_is_refused(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("QC_BENCH_PATH", "somewhere")

    with pytest.raises(ValidationError):
        Settings(_env_file=None)  # type: ignore[call-arg]


def test_the_checkpointer_uses_the_direct_endpoint_not_the_pooler() -> None:
    from unittest.mock import MagicMock

    from pydantic import SecretStr

    from querycure.jobs.handlers import build_services

    pooled = "postgresql://qc_app:pw@ep-x-pooler.c-4.aws.neon.tech/db"
    direct = "postgresql://qc_app:pw@ep-x.c-4.aws.neon.tech/db"
    settings = Settings(
        _env_file=None, database_url=SecretStr(pooled), database_url_direct=SecretStr(direct),
        llm_provider="stub", feature_sandbox=False,
    )  # fmt: skip

    services = build_services(MagicMock(), settings)

    assert services.checkpoint_url == direct
