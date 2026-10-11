import logging

import sqlglot
from sqlglot import exp
from sqlglot.errors import ParseError, TokenError

from querycure.core.errors import SqlNotAllowedError, SqlParseError

DIALECT = "postgres"

# sqlglot logs a warning when it falls back to an opaque Command node; we reject those anyway.
logging.getLogger("sqlglot").setLevel(logging.ERROR)


def _detail(message: str) -> list[dict[str, str]]:
    return [{"field": "query", "message": message}]


def parse_single(sql: str, *, max_bytes: int) -> exp.Expression:
    """Parse exactly one PostgreSQL statement. Anything ambiguous fails closed."""
    if len(sql.encode()) > max_bytes:
        raise SqlNotAllowedError(
            "Query is too large to inspect.", details=_detail(f"limit is {max_bytes} bytes")
        )
    try:
        statements = [s for s in sqlglot.parse(sql, read=DIALECT) if s is not None]
    except (ParseError, TokenError) as exc:
        raise SqlParseError("Query could not be parsed.", details=_detail(str(exc)[:300])) from exc
    except RecursionError as exc:
        raise SqlParseError("Query is nested too deeply to parse.") from exc
    if not statements:
        raise SqlParseError("Query is empty.", details=_detail("no statement found"))
    if len(statements) > 1:
        raise SqlNotAllowedError(
            "Only a single statement can be inspected.",
            details=_detail(f"found {len(statements)} statements"),
        )
    statement = statements[0]
    if not isinstance(statement, exp.Expression):
        raise SqlParseError("Query could not be parsed.", details=_detail("unsupported node"))
    return statement
