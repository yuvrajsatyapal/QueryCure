import hashlib

from pydantic import BaseModel, ConfigDict
from sqlglot import exp

from querycure.sql.parser import DIALECT


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
