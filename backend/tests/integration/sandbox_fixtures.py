"""Sandbox server fixtures: the compose `sandbox-db` through `sandbox-relay` (127.0.0.1:55432)."""

import os
import secrets
from collections.abc import Iterator

import psycopg
import pytest
from pydantic import SecretStr

from querycure.sandbox.provisioner import SandboxProvisioner

SANDBOX_URL = os.environ.get(
    "QC_TEST_SANDBOX_URL",
    "postgresql://qc_sandbox_admin:qc_local_dev_only@127.0.0.1:55432/sandbox_admin",
)


def sandbox_reachable() -> None:
    try:
        psycopg.connect(SANDBOX_URL, connect_timeout=3).close()
    except psycopg.OperationalError as exc:
        reason = f"sandbox DB not reachable ({exc.__class__.__name__}); run docker compose up"
        if os.environ.get("QC_REQUIRE_DB") == "1":
            pytest.fail(reason)
        pytest.skip(reason)


@pytest.fixture(scope="session")
def bench_password() -> str:
    return secrets.token_hex(16)


@pytest.fixture(scope="session")
def provisioner(bench_password: str) -> Iterator[SandboxProvisioner]:
    sandbox_reachable()
    prov = SandboxProvisioner(
        admin_url=SecretStr(SANDBOX_URL), bench_password=SecretStr(bench_password)
    )
    prov.bootstrap()
    yield prov
    with prov.lease(timeout_seconds=30) as lease:
        lease.cleanup_orphans()


def clone_names() -> list[str]:
    with psycopg.connect(SANDBOX_URL, autocommit=True) as conn:
        rows = conn.execute(
            "SELECT datname FROM pg_database WHERE datname LIKE 'qc\\_clone\\_%' ORDER BY 1"
        ).fetchall()
    return [r[0] for r in rows]
