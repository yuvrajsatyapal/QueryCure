import hashlib

from pydantic import BaseModel, ConfigDict
from sqlglot import exp

from querycure.core.errors import QueryCureError
from querycure.sql.parser import DIALECT, parse_single

_MATCH_MAX_BYTES = 100_000


class QueryFingerprint(BaseModel):
    """Groups similar queries. Metadata only, never artifact identity (REPLAY_ENGINE §2.2)."""

    model_config = ConfigDict(frozen=True)

    normalized_sql: str
    digest: str


def _literal_to_placeholder(node: exp.Expression) -> exp.Expression:
    if isinstance(node, exp.Literal):
        return exp.Placeholder()
    return node


def fingerprint(tree: exp.Expression) -> QueryFingerprint:
    normalized = tree.copy().transform(_literal_to_placeholder)
    text = normalized.sql(dialect=DIALECT, normalize=True, comments=False)
    return QueryFingerprint(normalized_sql=text, digest=hashlib.sha256(text.encode()).hexdigest())


def _value_to_placeholder(node: exp.Expression) -> exp.Expression:
    if isinstance(node, exp.Literal | exp.Parameter | exp.Placeholder):
        return exp.Placeholder()
    return node


def match_key(sql: str) -> str | None:
    """Text for matching a query against `pg_stat_statements`, whose normalised text has `$n`
    where the user's query may have literals. None when the text does not parse (e.g. it was
    truncated): an unmatched statement is ignored rather than guessed at."""
    try:
        tree = parse_single(sql, max_bytes=_MATCH_MAX_BYTES)
    except QueryCureError:
        return None
    normalized = tree.copy().transform(_value_to_placeholder)
    return normalized.sql(dialect=DIALECT, normalize=True, comments=False)
