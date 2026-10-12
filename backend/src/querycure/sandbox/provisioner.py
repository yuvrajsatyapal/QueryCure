"""Sandbox lifecycle: templates, clones, locking, orphan cleanup (ADR-0007, SECURITY §8).

Two roles on the sandbox server:
- the **admin** role (compose superuser) is used only here, by trusted code, to create and drop
  databases and to build templates from the deterministic workload generators;
- **qc_bench** (no superuser, no CREATEDB/CREATEROLE, no server-file or program privileges) owns
  every template object and clone, and is the only role that runs candidate DDL and benchmark
  queries. Candidate SQL never runs as the admin role.

One experiment measures at a time per server: a lease holds a session-level advisory lock on
the admin database, so a crashed worker's lock disappears with its connection. Every lease
first drops leftover clones, which can only be orphans while the lock is held.
"""

import hashlib
import time
import uuid
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from typing import Any

import psycopg
from psycopg import sql
from psycopg.conninfo import conninfo_to_dict, make_conninfo
from pydantic import SecretStr

from querycure.core.errors import SandboxUnavailableError
from querycure.core.logging import get_logger
from querycure.replay.canonical import canonical_json
from querycure.replay.digest import digest
from querycure.workloads.loader import load_workload, table_checksums
from querycure.workloads.registry import WORKLOADS, WorkloadRef

log = get_logger(__name__)

BENCH_ROLE = "qc_bench"
TEMPLATE_BUILDER = "tpl@1"  # bump when template preparation changes (new template names)
LOCK_KEY = 0x51435342  # "QCSB"
CLONE_PREFIX = "qc_clone_"
BUILD_PREFIX = "qc_tplbuild_"
TEMPLATE_PREFIX = "qc_tpl_"
# Planner/memory GUCs recorded in every EnvironmentFingerprint (REPLAY_ENGINE §9.3).
PINNED_SETTINGS = (
    "shared_buffers",
    "work_mem",
    "effective_cache_size",
    "random_page_cost",
    "seq_page_cost",
    "jit",
    "max_parallel_workers_per_gather",
    "default_statistics_target",
    "autovacuum",
)


class SandboxBusyError(SandboxUnavailableError):
    pass


@dataclass(frozen=True)
class Template:
    name: str
    workload_id: str
    data_digest: str


@dataclass(frozen=True)
class ServerEnvironment:
    pg_version: str
    pg_settings: dict[str, str]


def template_name(ref: WorkloadRef) -> str:
    h = hashlib.sha256(f"{ref}|{TEMPLATE_BUILDER}".encode()).hexdigest()[:16]
    return f"{TEMPLATE_PREFIX}{h}"


def clone_name(experiment_id: uuid.UUID, arm_index: int) -> str:
    return f"{CLONE_PREFIX}{experiment_id.hex[:12]}_{arm_index}"


class SandboxProvisioner:
    def __init__(
        self,
        *,
        admin_url: SecretStr,
        bench_password: SecretStr,
        max_clones: int = 8,
        connect_timeout: int = 5,
    ) -> None:
        self._admin_url = admin_url
        self._bench_password = bench_password
        self.max_clones = max_clones
        self._connect_timeout = connect_timeout

    def _admin(self, dbname: str | None = None) -> psycopg.Connection[Any]:
        url = self._admin_url.get_secret_value()
        conninfo = make_conninfo(url, dbname=dbname) if dbname is not None else url
        return psycopg.connect(conninfo, autocommit=True, connect_timeout=self._connect_timeout)

    def bootstrap(self) -> None:
        """Idempotent: the bench role exists with exactly the intended (lack of) privileges."""
        with self._admin() as conn:
            exists = conn.execute("SELECT 1 FROM pg_roles WHERE rolname = %s", (BENCH_ROLE,))
            if exists.fetchone() is None:
                conn.execute(sql.SQL("CREATE ROLE {}").format(sql.Identifier(BENCH_ROLE)))
            conn.execute(
                sql.SQL(
                    "ALTER ROLE {} WITH LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOREPLICATION "
                    "NOBYPASSRLS CONNECTION LIMIT 16 PASSWORD {}"
                ).format(
                    sql.Identifier(BENCH_ROLE),
                    sql.Literal(self._bench_password.get_secret_value()),
                )
            )
            # Role-level ceilings; sessions also set their own, stricter values.
            conn.execute(
                sql.SQL("ALTER ROLE {} SET idle_in_transaction_session_timeout = '30s'").format(
                    sql.Identifier(BENCH_ROLE)
                )
            )

    def bench_conninfo(
        self, dbname: str, *, statement_timeout_ms: int = 10_000, lock_timeout_ms: int = 1_000
    ) -> dict[str, Any]:
        """Connection kwargs for qc_bench on one clone, with every session setting pinned so
        timing and qc-row-v1 text forms do not depend on server or role defaults."""
        info = conninfo_to_dict(self._admin_url.get_secret_value())
        options = " ".join(
            f"-c {name}={value}"
            for name, value in (
                ("statement_timeout", statement_timeout_ms),
                ("lock_timeout", lock_timeout_ms),
                ("idle_in_transaction_session_timeout", 10_000),
                ("jit", "off"),
                ("search_path", "public"),
                ("TimeZone", "UTC"),
                ("DateStyle", "ISO,MDY"),
                ("IntervalStyle", "postgres"),
                ("extra_float_digits", 1),
                ("bytea_output", "hex"),
            )
        )
        return {
            "host": info.get("host", "127.0.0.1"),
            "port": info.get("port", 5432),
            "dbname": dbname,
            "user": BENCH_ROLE,
            "password": self._bench_password.get_secret_value(),
            "options": options,
            "connect_timeout": self._connect_timeout,
            "application_name": "querycure-bench",
        }

    @contextmanager
    def lease(
        self,
        *,
        timeout_seconds: float,
        should_cancel: Callable[[], bool] | None = None,
        poll_seconds: float = 0.1,
    ) -> Iterator["SandboxLease"]:
        try:
            conn = self._admin()
        except psycopg.OperationalError as exc:
            raise SandboxUnavailableError("The sandbox server is not reachable.") from exc
        try:
            deadline = time.monotonic() + timeout_seconds
            while not conn.execute("SELECT pg_try_advisory_lock(%s)", (LOCK_KEY,)).fetchone()[0]:  # type: ignore[index]
                if should_cancel is not None and should_cancel():
                    raise SandboxBusyError("Cancelled while waiting for the sandbox.")
                if time.monotonic() >= deadline:
                    raise SandboxBusyError("The sandbox is busy with another experiment.")
                time.sleep(poll_seconds)
            lease = SandboxLease(self, conn)
            yield lease
        finally:
            conn.close()  # ends the session, which releases the advisory lock


class SandboxLease:
    """Admin operations, valid only while the advisory lock is held."""

    def __init__(self, provisioner: SandboxProvisioner, conn: psycopg.Connection[Any]) -> None:
        self._p = provisioner
        self._conn = conn

    def _databases(self, prefix: str) -> list[str]:
        rows = self._conn.execute(
            "SELECT datname FROM pg_database WHERE starts_with(datname, %s) ORDER BY datname",
            (prefix,),
        ).fetchall()
        return [r[0] for r in rows]

    def _drop(self, name: str) -> None:
        self._conn.execute(
            sql.SQL("DROP DATABASE IF EXISTS {} WITH (FORCE)").format(sql.Identifier(name))
        )

    def cleanup_orphans(self) -> list[str]:
        """Drop every clone and half-built template. Under the lock none can be in use."""
        names = [*self._databases(CLONE_PREFIX), *self._databases(BUILD_PREFIX)]
        for name in names:
            self._drop(name)
        if names:
            log.info("sandbox_orphans_dropped", count=len(names))
        return names

    def server_environment(self) -> ServerEnvironment:
        version = self._conn.execute("SHOW server_version_num").fetchone()
        settings: dict[str, str] = {}
        for name in PINNED_SETTINGS:
            row = self._conn.execute(sql.SQL("SHOW {}").format(sql.Identifier(name))).fetchone()
            settings[name] = str(row[0]) if row else ""
        return ServerEnvironment(
            pg_version=str(version[0]) if version else "", pg_settings=settings
        )

    def _template(self, name: str) -> Template | None:
        row = self._conn.execute(
            "SELECT shobj_description(oid, 'pg_database') FROM pg_database "
            "WHERE datname = %s AND datistemplate",
            (name,),
        ).fetchone()
        if row is None or not row[0]:
            return None
        workload_id, builder, data_digest = str(row[0]).split("|")
        if builder != TEMPLATE_BUILDER:
            return None
        return Template(name=name, workload_id=workload_id, data_digest=data_digest)

    def ensure_template(self, ref: WorkloadRef) -> Template:
        name = template_name(ref)
        existing = self._template(name)
        if existing is not None:
            return existing
        self._drop_template_named(name)  # a stale or unmarked database under the same name
        build = f"{BUILD_PREFIX}{name.removeprefix(TEMPLATE_PREFIX)}"
        self._drop(build)
        self._conn.execute(
            sql.SQL("CREATE DATABASE {} OWNER {}").format(
                sql.Identifier(build), sql.Identifier(BENCH_ROLE)
            )
        )
        tables = WORKLOADS[ref.name].tables
        with self._p._admin(build) as conn:
            # Objects belong to qc_bench so its candidate DDL (CREATE INDEX, ANALYZE) can run.
            conn.execute(sql.SQL("SET ROLE {}").format(sql.Identifier(BENCH_ROLE)))
            load_workload(conn, ref)
            for table in tables:
                # Clones inherit this: no background autovacuum/analyze during measurement.
                conn.execute(
                    sql.SQL(
                        "ALTER TABLE {} SET (autovacuum_enabled = false, "
                        "toast.autovacuum_enabled = false)"
                    ).format(sql.Identifier(table))
                )
            # Freeze + visibility map for stable index-only scans. No ANALYZE: statistics are
            # exactly what the workload generator left (stale_stats relies on that).
            conn.execute("VACUUM (FREEZE)")
            checksums = table_checksums(conn, tables)
        data_digest = digest(
            "qc-json-v1", canonical_json({"tables": checksums, "workload_id": str(ref)})
        )
        self._conn.execute(
            sql.SQL("ALTER DATABASE {} RENAME TO {}").format(
                sql.Identifier(build), sql.Identifier(name)
            )
        )
        self._conn.execute(
            sql.SQL("ALTER DATABASE {} WITH IS_TEMPLATE true ALLOW_CONNECTIONS false").format(
                sql.Identifier(name)
            )
        )
        self._conn.execute(
            sql.SQL("COMMENT ON DATABASE {} IS {}").format(
                sql.Identifier(name), sql.Literal(f"{ref}|{TEMPLATE_BUILDER}|{data_digest}")
            )
        )
        log.info("sandbox_template_built", workload=str(ref), template=name)
        return Template(name=name, workload_id=str(ref), data_digest=data_digest)

    def _drop_template_named(self, name: str) -> None:
        exists = self._conn.execute("SELECT 1 FROM pg_database WHERE datname = %s", (name,))
        if exists.fetchone() is None:
            return
        self._conn.execute(
            sql.SQL("ALTER DATABASE {} WITH IS_TEMPLATE false").format(sql.Identifier(name))
        )
        self._drop(name)

    def drop_template(self, ref: WorkloadRef) -> None:
        self._drop_template_named(template_name(ref))

    def create_clone(self, template: Template, experiment_id: uuid.UUID, arm_index: int) -> str:
        if len(self._databases(CLONE_PREFIX)) >= self._p.max_clones:
            raise SandboxBusyError("The sandbox clone limit is reached.")
        name = clone_name(experiment_id, arm_index)
        self._drop(name)
        # FILE_COPY: a file-level copy of the template, far faster than reloading data.
        self._conn.execute(
            sql.SQL("CREATE DATABASE {} TEMPLATE {} OWNER {} STRATEGY FILE_COPY").format(
                sql.Identifier(name), sql.Identifier(template.name), sql.Identifier(BENCH_ROLE)
            )
        )
        return name

    def drop_clone(self, name: str) -> None:
        if not name.startswith(CLONE_PREFIX):
            raise ValueError("only clones can be dropped")
        self._drop(name)
