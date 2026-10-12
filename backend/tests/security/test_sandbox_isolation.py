"""Sandbox privilege controls (SECURITY §8, T12): even SQL that slipped past the DDL allowlist
runs as qc_bench, which cannot reach programs, server files, other roles or new databases."""

import uuid
from collections.abc import Iterator

import psycopg
import pytest

from querycure.sandbox.provisioner import SandboxProvisioner
from querycure.workloads.registry import WorkloadRef

pytestmark = pytest.mark.integration


@pytest.fixture
def bench(provisioner: SandboxProvisioner) -> Iterator[psycopg.Connection]:
    with provisioner.lease(timeout_seconds=30) as lease:
        template = lease.ensure_template(WorkloadRef.parse("no_benefit@v1:sf=0.2:seed=42"))
        clone = lease.create_clone(template, uuid.uuid4(), 0)
        with psycopg.connect(**provisioner.bench_conninfo(clone), autocommit=True) as conn:
            yield conn
        lease.drop_clone(clone)


@pytest.mark.parametrize(
    "statement",
    [
        "COPY app_settings FROM PROGRAM 'curl -s http://169.254.169.254/'",
        "COPY app_settings TO PROGRAM 'sh -c id'",
        "COPY app_settings FROM '/etc/passwd'",
        "SELECT pg_read_file('/etc/passwd')",
        "SELECT pg_ls_dir('.')",
        "CREATE DATABASE escape_db",
        "CREATE ROLE escape_role",
        "ALTER SYSTEM SET jit = on",
        "CREATE EXTENSION dblink",
        # The lease's admin session is open while the fixture runs.
        "SELECT pg_terminate_backend(pid) FROM pg_stat_activity WHERE usename = 'qc_sandbox_admin'",
        "SET session_authorization = qc_sandbox_admin",
        "SET ROLE qc_sandbox_admin",
    ],
)
def test_bench_role_cannot_escape(bench: psycopg.Connection, statement: str) -> None:
    with pytest.raises(
        (
            psycopg.errors.InsufficientPrivilege,
            psycopg.errors.UndefinedFile,
            psycopg.errors.FeatureNotSupported,
        )
    ):
        bench.execute(statement)


def test_bench_role_attributes(bench: psycopg.Connection) -> None:
    row = bench.execute(
        "SELECT rolsuper, rolcreatedb, rolcreaterole, rolreplication, rolbypassrls "
        "FROM pg_roles WHERE rolname = current_user"
    ).fetchone()

    assert row == (False, False, False, False, False)


def test_bench_role_has_no_server_program_or_file_roles(bench: psycopg.Connection) -> None:
    row = bench.execute(
        "SELECT pg_has_role(current_user, 'pg_execute_server_program', 'MEMBER'), "
        "pg_has_role(current_user, 'pg_read_server_files', 'MEMBER'), "
        "pg_has_role(current_user, 'pg_write_server_files', 'MEMBER')"
    ).fetchone()

    assert row == (False, False, False)
