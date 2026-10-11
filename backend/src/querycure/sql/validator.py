"""Statement allowlist for SQL that QueryCure may EXPLAIN or benchmark.

This is defense in depth, not the security boundary (SECURITY.md §4.1): read-only sessions,
timeouts and role checks must hold even if a payload slips past this module.
"""

from typing import Literal

from pydantic import BaseModel, ConfigDict
from sqlglot import exp

from querycure.core.errors import SqlNotAllowedError
from querycure.sql.fingerprint import QueryFingerprint, fingerprint
from querycure.sql.parser import DIALECT, parse_single

_ALLOWED_ROOTS = (exp.Select, exp.SetOperation)
_FORBIDDEN_NODES: tuple[type[exp.Expression], ...] = (
    exp.Insert,
    exp.Update,
    exp.Delete,
    exp.Merge,
    exp.Create,
    exp.Drop,
    exp.Alter,
    exp.TruncateTable,
    exp.Copy,
    exp.Set,
    exp.Command,
    exp.Transaction,
    exp.Commit,
    exp.Rollback,
    exp.Grant,
    exp.Revoke,
)
_DENIED_FUNCTIONS = frozenset(
    {
        "set_config", "nextval", "setval", "lastval", "pg_notify", "pg_reload_conf",
        "pg_rotate_logfile", "pg_terminate_backend", "pg_cancel_backend", "pg_promote",
        "pg_switch_wal", "pg_stat_file", "pg_current_xact_id", "txid_current",
        "pg_import_system_collations",
    }
)  # fmt: skip
_DENIED_PREFIXES = (
    "pg_sleep", "dblink", "lo_", "pg_read_", "pg_ls_", "pg_advisory", "pg_file", "pg_logdir",
    "query_to_xml", "cursor_to_xml", "pg_create_", "pg_drop_", "pg_replication_", "pg_logical_",
    "pg_backup_", "pg_wal_replay_",
)  # fmt: skip
_SYSTEM_SCHEMA = "pg_catalog"


class SqlPolicy(BaseModel):
    model_config = ConfigDict(frozen=True)

    max_bytes: int = 100_000
    max_depth: int = 128
    # SECURITY.md §4.3: functions in user schemas run user code at plan time; off unless opted in.
    allow_user_functions: bool = False


class TableRef(BaseModel):
    model_config = ConfigDict(frozen=True)

    schema_name: str | None
    name: str


class ColumnRef(BaseModel):
    model_config = ConfigDict(frozen=True)

    table: str | None
    name: str


class QueryMetadata(BaseModel):
    model_config = ConfigDict(frozen=True)

    tables: list[TableRef]
    columns: list[ColumnRef]
    order_by: list[str]
    limit: int | None
    parameter_count: int
    functions: list[str]
    # Unqualified names SQLGlot does not recognize: may be user functions found via search_path,
    # so the gateway resolves them against pg_proc before EXPLAIN (SECURITY.md §4.3).
    functions_to_resolve: list[str]


class ValidatedQuery(BaseModel):
    model_config = ConfigDict(frozen=True)

    sql: str
    statement_type: Literal["select", "set_operation"]
    metadata: QueryMetadata
    fingerprint: QueryFingerprint


def _reject(message: str, reason: str) -> SqlNotAllowedError:
    return SqlNotAllowedError(message, details=[{"field": "query", "message": reason}])


def _function_name(node: exp.Func) -> str:
    return (node.name if isinstance(node, exp.Anonymous) else node.sql_name()).lower()


def _qualifier(node: exp.Func) -> str | None:
    parent = node.parent
    if isinstance(parent, exp.Dot) and parent.expression is node:
        return str(parent.this.name).lower()
    return None


def _check_functions(tree: exp.Expression, policy: SqlPolicy) -> tuple[list[str], list[str]]:
    names: list[str] = []
    to_resolve: set[str] = set()
    for func in tree.find_all(exp.Func):
        name = _function_name(func)
        qualifier = _qualifier(func)
        shown = f"{qualifier}.{name}" if qualifier else name
        if name in _DENIED_FUNCTIONS or name.startswith(_DENIED_PREFIXES):
            raise _reject("Query calls a function that is not allowed.", f"function {shown}")
        if qualifier and qualifier != _SYSTEM_SCHEMA and not policy.allow_user_functions:
            raise _reject(
                "Query calls a user-defined function; enable user functions to inspect it.",
                f"function {shown}",
            )
        names.append(shown)
        if isinstance(func, exp.Anonymous) and qualifier is None:
            to_resolve.add(name)
    return sorted(set(names)), sorted(to_resolve)


def _check_structure(tree: exp.Expression, policy: SqlPolicy) -> None:
    if not isinstance(tree, _ALLOWED_ROOTS):
        kind = tree.key.upper()
        raise _reject("Only a single SELECT statement can be inspected.", f"statement {kind}")
    for node in tree.walk():
        if isinstance(node, _FORBIDDEN_NODES):
            raise _reject(
                "Query contains a statement that can modify data or settings.",
                f"contains {node.key.upper()}",
            )
        if isinstance(node, exp.Select):
            if node.args.get("into"):
                raise _reject("SELECT INTO creates a table and is not allowed.", "SELECT INTO")
            if node.args.get("locks"):
                raise _reject("Row locking clauses are not allowed.", "row lock (FOR UPDATE/SHARE)")
        if node.depth > policy.max_depth:
            raise _reject("Query is nested too deeply.", f"depth exceeds {policy.max_depth}")


def _pg_name(node: exp.Expression | None) -> str | None:
    """PostgreSQL folds unquoted identifiers to lower case; quoted ones keep their case."""
    if not isinstance(node, exp.Identifier):
        return None
    return node.name if node.quoted else node.name.lower()


def _metadata(tree: exp.Expression, functions: list[str], to_resolve: list[str]) -> QueryMetadata:
    cte_names = {cte.alias_or_name for cte in tree.find_all(exp.CTE)}
    tables = sorted(
        {
            TableRef(schema_name=_pg_name(t.args.get("db")), name=_pg_name(t.this) or t.name)
            for t in tree.find_all(exp.Table)
            if not (t.name in cte_names and not t.db)
        },
        key=lambda t: (t.schema_name or "", t.name),
    )
    columns = sorted(
        {ColumnRef(table=c.table or None, name=c.name) for c in tree.find_all(exp.Column)},
        key=lambda c: (c.table or "", c.name),
    )
    order = tree.args.get("order")
    order_by = [o.sql(dialect=DIALECT) for o in order.expressions] if order else []
    limit_node = tree.args.get("limit")
    limit: int | None = None
    if isinstance(limit_node, exp.Limit) and isinstance(limit_node.expression, exp.Literal):
        value = limit_node.expression.this
        limit = int(value) if str(value).isdigit() else None
    params = {p.sql() for p in tree.find_all(exp.Parameter, exp.Placeholder)}
    return QueryMetadata(
        tables=tables,
        columns=columns,
        order_by=order_by,
        limit=limit,
        parameter_count=len(params),
        functions=functions,
        functions_to_resolve=to_resolve,
    )


def validate_select(sql: str, policy: SqlPolicy | None = None) -> ValidatedQuery:
    policy = policy or SqlPolicy()
    tree = parse_single(sql, max_bytes=policy.max_bytes)
    _check_structure(tree, policy)
    functions, to_resolve = _check_functions(tree, policy)
    return ValidatedQuery(
        sql=sql,
        statement_type="select" if isinstance(tree, exp.Select) else "set_operation",
        metadata=_metadata(tree, functions, to_resolve),
        fingerprint=fingerprint(tree),
    )
