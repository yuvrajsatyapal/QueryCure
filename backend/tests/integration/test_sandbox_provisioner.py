"""Sandbox provisioner against the real sandbox server (T3.2, ADR-0007)."""

import threading
import uuid

import psycopg
import pytest

from querycure.sandbox.provisioner import SandboxBusyError, SandboxProvisioner
from querycure.workloads.registry import WorkloadRef
from tests.integration.sandbox_fixtures import SANDBOX_URL, clone_names

pytestmark = pytest.mark.integration

REF = WorkloadRef.parse("orders_ecommerce@v1:sf=0.01:seed=42")


def test_template_is_built_once_and_reused(provisioner: SandboxProvisioner) -> None:
    with provisioner.lease(timeout_seconds=30) as lease:
        first = lease.ensure_template(REF)
        second = lease.ensure_template(REF)

    assert first == second
    assert first.name.startswith("qc_tpl_")
    assert len(first.data_digest) == 64
    with psycopg.connect(SANDBOX_URL, autocommit=True) as conn:
        row = conn.execute(
            "SELECT datistemplate, datallowconn, pg_get_userbyid(datdba) FROM pg_database "
            "WHERE datname = %s",
            (first.name,),
        ).fetchone()
    assert row == (True, False, "qc_bench")


def test_template_digest_is_deterministic_per_workload(provisioner: SandboxProvisioner) -> None:
    """Rebuilding from scratch yields the same data digest (replay precondition)."""
    with provisioner.lease(timeout_seconds=30) as lease:
        original = lease.ensure_template(REF)
        lease.drop_template(REF)
        rebuilt = lease.ensure_template(REF)

    assert rebuilt.data_digest == original.data_digest


def test_clone_has_the_template_data_owned_by_the_bench_role(
    provisioner: SandboxProvisioner,
) -> None:
    experiment = uuid.uuid4()
    with provisioner.lease(timeout_seconds=30) as lease:
        template = lease.ensure_template(REF)
        clone = lease.create_clone(template, experiment, 0)
        with psycopg.connect(**provisioner.bench_conninfo(clone)) as conn:
            orders = conn.execute("SELECT count(*) FROM orders").fetchone()
            owner = conn.execute(
                "SELECT pg_get_userbyid(relowner) FROM pg_class WHERE relname = 'orders'"
            ).fetchone()
            autovacuum = conn.execute(
                "SELECT reloptions FROM pg_class WHERE relname = 'orders'"
            ).fetchone()
            user = conn.execute("SELECT current_user").fetchone()
        lease.drop_clone(clone)

    assert orders == (10_000,)
    assert owner == ("qc_bench",)
    assert autovacuum is not None
    assert "autovacuum_enabled=false" in autovacuum[0]
    assert user == ("qc_bench",)
    assert clone not in clone_names()


def test_bench_session_is_pinned(provisioner: SandboxProvisioner) -> None:
    with provisioner.lease(timeout_seconds=30) as lease:
        clone = lease.create_clone(lease.ensure_template(REF), uuid.uuid4(), 0)
        with psycopg.connect(**provisioner.bench_conninfo(clone, statement_timeout_ms=1234)) as c:
            settings = {
                name: c.execute(f"SHOW {name}").fetchone()[0]  # type: ignore[index]
                for name in ("statement_timeout", "jit", "TimeZone", "DateStyle", "lock_timeout")
            }
        lease.drop_clone(clone)

    assert settings == {
        "statement_timeout": "1234ms",
        "jit": "off",
        "TimeZone": "UTC",
        "DateStyle": "ISO, MDY",
        "lock_timeout": "1s",
    }


def test_cleanup_drops_orphaned_clones(provisioner: SandboxProvisioner) -> None:
    """A crashed experiment leaves clones behind; the next lease removes them."""
    with provisioner.lease(timeout_seconds=30) as lease:
        template = lease.ensure_template(REF)
        lease.create_clone(template, uuid.uuid4(), 0)
        lease.create_clone(template, uuid.uuid4(), 1)
    assert len(clone_names()) == 2

    with provisioner.lease(timeout_seconds=30) as lease:
        dropped = lease.cleanup_orphans()

    assert len(dropped) == 2
    assert clone_names() == []


def test_only_one_lease_at_a_time(provisioner: SandboxProvisioner) -> None:
    holding = threading.Event()
    release = threading.Event()

    def hold() -> None:
        with provisioner.lease(timeout_seconds=30):
            holding.set()
            release.wait(10)

    holder = threading.Thread(target=hold)
    holder.start()
    holding.wait(10)
    try:
        with pytest.raises(SandboxBusyError), provisioner.lease(timeout_seconds=0.5):
            pass
    finally:
        release.set()
        holder.join()
    with provisioner.lease(timeout_seconds=5):
        pass  # released when the holder's session ended


def test_lease_waits_can_be_cancelled(provisioner: SandboxProvisioner) -> None:
    holding = threading.Event()
    release = threading.Event()

    def hold() -> None:
        with provisioner.lease(timeout_seconds=30):
            holding.set()
            release.wait(10)

    holder = threading.Thread(target=hold)
    holder.start()
    holding.wait(10)
    try:
        with (
            pytest.raises(SandboxBusyError, match=r"(?i)cancelled"),
            provisioner.lease(timeout_seconds=30, should_cancel=lambda: True),
        ):
            pass
    finally:
        release.set()
        holder.join()


def test_clone_limit_is_enforced(bench_password: str) -> None:
    from pydantic import SecretStr

    small = SandboxProvisioner(
        admin_url=SecretStr(SANDBOX_URL), bench_password=SecretStr(bench_password), max_clones=1
    )
    with small.lease(timeout_seconds=30) as lease:
        template = lease.ensure_template(REF)
        lease.create_clone(template, uuid.uuid4(), 0)
        with pytest.raises(SandboxBusyError, match="clone limit"):
            lease.create_clone(template, uuid.uuid4(), 1)
        lease.cleanup_orphans()


def test_environment_records_version_and_pinned_settings(
    provisioner: SandboxProvisioner,
) -> None:
    with provisioner.lease(timeout_seconds=30) as lease:
        env = lease.server_environment()

    assert env.pg_version.startswith("17")
    assert env.pg_settings["jit"] == "off"
    assert set(env.pg_settings) >= {
        "shared_buffers",
        "work_mem",
        "effective_cache_size",
        "random_page_cost",
        "max_parallel_workers_per_gather",
    }
