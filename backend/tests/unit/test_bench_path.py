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
