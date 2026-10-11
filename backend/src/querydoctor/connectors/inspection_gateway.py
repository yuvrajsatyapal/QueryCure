"""The only path to a user's target database (Mode B). SECURITY.md §4-5.

Layers enforced here: SSRF guard + pinned hostaddr (L5), allowlisted operations (L2),
hardened read-only sessions verified with SHOW (L3), role capability refusal (L4).
The SQL validator (L1) runs first, but nothing here assumes it is perfect.
"""

from collections.abc import AsyncIterator, Mapping
from contextlib import asynccontextmanager
from functools import cache
from importlib.resources import files
from typing import Any

import psycopg
from psycopg import errors as pg_errors
from psycopg import sql
from psycopg.rows import dict_row

from querydoctor.connectors.models import (
    ColumnStats,
    ExplainResult,
    GatewayLimits,
    IndexInfo,
    SchemaSnapshot,
    TableStats,
    TargetCapabilities,
    TargetConnection,
)
from querydoctor.connectors.ssrf_guard import TargetPolicy, resolve_target
from querydoctor.core.errors import (
    QueryDoctorError,
    RoleTooPrivilegedError,
    SqlNotAllowedError,
    TargetBlockedError,
    TargetPermissionError,
    TargetQueryError,
    TargetTimeoutError,
    TargetUnreachableError,
    ValidationFailedError,
)
from querydoctor.core.logging import get_logger
from querydoctor.sql.validator import SqlPolicy, TableRef, validate_select

log = get_logger("querydoctor.connectors.gateway")

APPLICATION_NAME = "querydoctor-inspector"
SEARCH_PATH = "pg_catalog, public"
GENERIC_PLAN_MIN_VERSION = 160000
_VERIFIED_SETTINGS = (
    "default_transaction_read_only",
    "statement_timeout",
    "lock_timeout",
    "idle_in_transaction_session_timeout",
    "search_path",
    "application_name",
)


@cache
def _template(name: str) -> str:
    # Trusted files shipped with the package; values are always passed as parameters.
    return files("querydoctor.connectors.catalog_queries").joinpath(name).read_text()


# Ordered (needle, reason) pairs matched against libpq's connect error text. Only the reason
# code leaves this module; the text itself names the host and user.
_CONNECT_FAILURES: tuple[tuple[str, str], ...] = (
    ("password authentication failed", "auth_failed"),
    ('role "', "auth_failed"),
    ('database "', "database_missing"),
    ("does not support ssl", "tls_unsupported"),
    ("ssl", "tls_failed"),
)

# Only failures past the network layer are explained to the user; refused vs timed out stays
# generic so the endpoint can't be used to map which ports answer.
_CONNECT_HINTS = {
    "auth_failed": "Authentication failed: check the username and password.",
    "database_missing": "The database does not exist on that server.",
    "tls_unsupported": (
        "The server does not support TLS. For a local-only server, set TLS to disable."
    ),
    "tls_failed": "The TLS handshake or certificate check failed.",
}


def connect_failure_reason(message: str) -> str:
    lowered = message.lower()
    for needle, reason in _CONNECT_FAILURES:
        if needle in lowered:
            return reason
    return "unreachable"


def _connect_error(exc: psycopg.Error) -> QueryDoctorError:
    reason = connect_failure_reason(str(exc))
    log.warning(
        "target_connect_failed",
        error_class=type(exc).__name__,
        reason=reason,
    )
    hint = _CONNECT_HINTS.get(reason)
    return TargetUnreachableError(
        "Could not connect to the target database.",
        details=[{"field": "connection", "message": hint}] if hint else None,
    )


def _map_error(exc: psycopg.Error) -> QueryDoctorError:
    """Translate driver errors without echoing connection details or credentials."""
    if isinstance(exc, pg_errors.ReadOnlySqlTransaction):
        return SqlNotAllowedError("The inspection session is read-only.")
    if isinstance(exc, pg_errors.QueryCanceled):
        return TargetTimeoutError("The inspection query exceeded its time limit.")
    if isinstance(exc, pg_errors.LockNotAvailable):
        return TargetTimeoutError("Timed out waiting for a lock on the target database.")
    if isinstance(exc, pg_errors.InsufficientPrivilege):
        return TargetPermissionError(
            "The connection's role lacks a required privilege.",
            details=[
                {
                    "field": "connection",
                    "message": exc.diag.message_primary or "permission denied",
                }
            ],
        )
    if isinstance(exc, psycopg.OperationalError):
        return TargetUnreachableError("Could not connect to the target database.")
    primary = exc.diag.message_primary if exc.diag else None
    return TargetQueryError(
        "PostgreSQL rejected the inspection query.",
        details=[{"field": "query", "message": primary or exc.__class__.__name__}],
    )


class InspectionGateway:
    def __init__(
        self, conn: psycopg.AsyncConnection[Any], capabilities: TargetCapabilities
    ) -> None:
        self._conn = conn
        self._capabilities = capabilities

    @classmethod
    @asynccontextmanager
    async def open(
        cls,
        target: TargetConnection,
        *,
        policy: TargetPolicy,
        limits: GatewayLimits | None = None,
    ) -> AsyncIterator["InspectionGateway"]:
        limits = limits or GatewayLimits()
        if target.sslmode == "disable" and not policy.allow_private:
            raise TargetBlockedError(
                "TLS is required for this deployment.",
                details=[{"field": "sslmode", "message": "disable is only allowed locally"}],
            )
        resolved = await resolve_target(target.host, target.port, policy=policy)
        try:
            conn = await psycopg.AsyncConnection.connect(
                host=resolved.host,
                hostaddr=resolved.hostaddr,
                port=resolved.port,
                dbname=target.dbname,
                user=target.username,
                password=target.password.get_secret_value(),
                sslmode=target.sslmode,
                connect_timeout=limits.connect_timeout_s,
                application_name=APPLICATION_NAME,
                autocommit=True,
            )
        except psycopg.Error as exc:
            raise _connect_error(exc) from None
        try:
            await cls._harden(conn, limits)
            gateway = cls(conn, await cls._read_capabilities(conn))
            gateway._refuse_privileged_roles()
            yield gateway
        except psycopg.Error as exc:
            raise _map_error(exc) from None
        finally:
            await conn.close()

    @staticmethod
    async def _harden(conn: psycopg.AsyncConnection[Any], limits: GatewayLimits) -> None:
        settings = {
            "default_transaction_read_only": "on",
            "statement_timeout": f"{limits.statement_timeout_ms}ms",
            "lock_timeout": f"{limits.lock_timeout_ms}ms",
            "idle_in_transaction_session_timeout": f"{limits.idle_in_transaction_timeout_ms}ms",
            "search_path": SEARCH_PATH,
        }
        for name, value in settings.items():
            await conn.execute(
                sql.SQL("SELECT set_config({}, {}, false)").format(
                    sql.Literal(name), sql.Literal(value)
                )
            )
        await conn.set_read_only(True)
        # Verify instead of trusting: poolers or server config can silently ignore settings.
        actual = await _show(conn)
        if actual["default_transaction_read_only"] != "on" or actual["search_path"] != SEARCH_PATH:
            raise TargetBlockedError("The target did not accept the read-only session settings.")

    @staticmethod
    async def _read_capabilities(conn: psycopg.AsyncConnection[Any]) -> TargetCapabilities:
        async with conn.cursor(row_factory=dict_row) as cur:
            await cur.execute(_template("capabilities.sql"), {})
            row = await cur.fetchone()
        if row is None:
            raise TargetQueryError("Could not read the connection's role attributes.")
        warnings = []
        if row["owned_tables"]:
            warnings.append(f"role owns {row['owned_tables']} table(s); use a non-owner role")
        if row["is_replication_role"]:
            warnings.append("role has REPLICATION; a plain login role is enough")
        if not row["can_read_all_stats"]:
            warnings.append("role is not a member of pg_read_all_stats; workload views are limited")
        return TargetCapabilities(**row, warnings=warnings)

    def _refuse_privileged_roles(self) -> None:
        caps = self._capabilities
        reasons = [
            label
            for flag, label in (
                (caps.is_superuser, "SUPERUSER"),
                (caps.can_create_role, "CREATEROLE"),
                (caps.bypasses_rls, "BYPASSRLS"),
            )
            if flag
        ]
        if reasons:
            raise RoleTooPrivilegedError(
                "This role is too privileged for inspection; create a restricted role.",
                details=[{"field": "username", "message": f"role has {', '.join(reasons)}"}],
            )

    async def session_settings(self) -> dict[str, str]:
        return await _show(self._conn)

    async def capabilities(self) -> TargetCapabilities:
        return self._capabilities

    async def explain(self, query: str, *, sql_policy: SqlPolicy | None = None) -> ExplainResult:
        policy = sql_policy or SqlPolicy()
        validated = validate_select(query, policy)
        try:
            async with self._conn.transaction():
                await self._check_functions(validated.metadata.functions_to_resolve, policy)
                generic = validated.metadata.parameter_count > 0
                if generic and self._capabilities.server_version_num < GENERIC_PLAN_MIN_VERSION:
                    raise ValidationFailedError(
                        "Use literal values instead of $n parameters on PostgreSQL < 16.",
                        details=[
                            {"field": "query", "message": "GENERIC_PLAN needs PostgreSQL 16+"}
                        ],
                    )
                options = "FORMAT JSON, GENERIC_PLAN" if generic else "FORMAT JSON"
                # The query passed validation; it is concatenated, never executed outside EXPLAIN.
                statement = f"EXPLAIN ({options}) {validated.sql}"
                cur = await self._conn.execute(statement)
                row = await cur.fetchone()
        except psycopg.Error as exc:
            raise _map_error(exc) from None
        if row is None or not isinstance(row[0], list):
            raise TargetQueryError("EXPLAIN returned no plan.")
        return ExplainResult(
            plan_document=row[0],
            validated=validated,
            generic_plan=generic,
            server_version_num=self._capabilities.server_version_num,
        )

    async def _check_functions(self, names: list[str], policy: SqlPolicy) -> None:
        """Refuse unrecognized functions that resolve outside pg_catalog (SECURITY.md §4.3)."""
        if not names or policy.allow_user_functions:
            return
        async with self._conn.cursor(row_factory=dict_row) as cur:
            await cur.execute(_template("resolve_functions.sql"), {"names": names})
            resolved = {row["name"]: set(row["schemas"]) for row in await cur.fetchall()}
        for name in names:
            schemas = resolved.get(name, set())
            # search_path is pinned to pg_catalog first, so a pg_catalog function always wins.
            if schemas and "pg_catalog" not in schemas:
                shown = ", ".join(f"{schema}.{name}" for schema in sorted(schemas))
                raise SqlNotAllowedError(
                    "Query calls a user-defined function; enable user functions to inspect it.",
                    details=[{"field": "query", "message": f"function {shown}"}],
                )

    async def schema_snapshot(self, tables: list[TableRef]) -> SchemaSnapshot:
        try:
            async with self._conn.transaction(), self._conn.cursor(row_factory=dict_row) as cur:
                await cur.execute(
                    _template("resolve_tables.sql"),
                    {
                        "schemas": [t.schema_name for t in tables],
                        "names": [t.name for t in tables],
                    },
                )
                found = await cur.fetchall()
                oids = [row["oid"] for row in found]
                found_ords = {row["ord"] for row in found}
                unresolved = [t for i, t in enumerate(tables, start=1) if i not in found_ords]
                await cur.execute(_template("tables.sql"), {"oids": oids})
                table_rows = await cur.fetchall()
                await cur.execute(_template("columns.sql"), {"oids": oids})
                column_rows = await cur.fetchall()
                await cur.execute(_template("indexes.sql"), {"oids": oids})
                index_rows = await cur.fetchall()
        except psycopg.Error as exc:
            raise _map_error(exc) from None
        names = {row["oid"]: (row["schema_name"], row["name"]) for row in table_rows}
        return SchemaSnapshot(
            tables=[TableStats(**_without(row, "oid")) for row in table_rows],
            columns=[ColumnStats.model_validate(_with_owner(names, row)) for row in column_rows],
            indexes=[IndexInfo.model_validate(_with_owner(names, row)) for row in index_rows],
            unresolved=unresolved,
        )

    async def _unsafe_execute_for_tests(self, statement: str) -> None:
        """Runs raw SQL in a read-only transaction to prove layer-3 controls. Tests only."""
        try:
            async with self._conn.transaction():
                await self._conn.execute(statement)
        except psycopg.Error as exc:
            raise _map_error(exc) from None


async def _show(conn: psycopg.AsyncConnection[Any]) -> dict[str, str]:
    result = {}
    for name in _VERIFIED_SETTINGS:
        cur = await conn.execute(sql.SQL("SELECT current_setting({})").format(sql.Literal(name)))
        row = await cur.fetchone()
        result[name] = str(row[0]) if row else ""
    return result


def _without(row: Mapping[str, Any], key: str) -> dict[str, Any]:
    return {k: v for k, v in row.items() if k != key}


def _with_owner(names: Mapping[int, tuple[str, str]], row: Mapping[str, Any]) -> dict[str, Any]:
    schema_name, table_name = names[row["table_oid"]]
    return {"schema_name": schema_name, "table_name": table_name, **_without(row, "table_oid")}
