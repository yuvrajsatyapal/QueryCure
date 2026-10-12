"""Result correctness: fingerprints and comparison rules (BENCHMARK_ENGINE §5).

Matching fingerprints show equivalence *on the tested data*, never formal SQL equivalence.
"""

import hashlib
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any, Literal

import sqlglot
from psycopg.postgres import types as pg_types
from sqlglot import exp

from querycure.replay.canonical.row_v1 import PROFILE, row_hash
from querycure.sql.parser import DIALECT

ROW_PROFILE = PROFILE

_KIND_BY_TYPE = {
    "int2": "int",
    "int4": "int",
    "int8": "int",
    "oid": "int",
    "float4": "float",
    "float8": "float",
    "numeric": "numeric",
    "text": "text",
    "varchar": "text",
    "bpchar": "text",
    "name": "text",
    "timestamptz": "timestamptz",
    "timestamp": "timestamp",
    "date": "date",
    "bool": "bool",
    "bytea": "bytea",
    "json": "json",
    "jsonb": "json",
    "uuid": "uuid",
}


def _oid_kinds() -> dict[int, str]:
    kinds: dict[int, str] = {}
    for name, kind in _KIND_BY_TYPE.items():
        info = pg_types.get(name)
        if info is None:  # pragma: no cover - psycopg always registers these
            continue
        kinds[info.oid] = kind
        if kind != "json":  # json arrays are loaded as text and hashed as `other`
            kinds[info.array_oid] = f"{kind}[]"
    return kinds


KIND_BY_OID = _oid_kinds()


def kinds_for_oids(oids: Iterable[int]) -> list[str]:
    """Column kinds for qc-row-v1. Anything unlisted is loaded as text and hashed as `other`."""
    return [KIND_BY_OID.get(oid, "other") for oid in oids]


@dataclass(frozen=True)
class Fingerprint:
    rows: int
    multiset: str  # SHA-256 over sorted row hashes
    ordered: str  # SHA-256 over row hashes in result order
    truncated: bool  # more rows than the hash cap: only `rows` is exact


@dataclass
class Fingerprinter:
    """Streams rows into both fingerprints; fetch cost is part of the measurement."""

    kinds: Sequence[str]
    cap: int
    _rows: int = 0
    _hashes: list[bytes] = field(default_factory=list)
    _ordered: Any = field(default_factory=hashlib.sha256)

    def add(self, row: Sequence[Any]) -> None:
        self._rows += 1
        if self._rows > self.cap:
            return
        digest = row_hash(self.kinds, row)
        self._hashes.append(digest)
        self._ordered.update(digest)

    def result(self) -> Fingerprint:
        multiset = hashlib.sha256(b"".join(sorted(self._hashes))).hexdigest()
        return Fingerprint(
            rows=self._rows,
            multiset=multiset,
            ordered=self._ordered.hexdigest(),
            truncated=self._rows > self.cap,
        )


CorrectnessStatus = Literal["match", "mismatch", "inconclusive"]


@dataclass(frozen=True)
class CorrectnessOutcome:
    status: CorrectnessStatus
    reason: str | None = None  # result_mismatch | nondeterministic_order | result_too_large
    detail: str = ""


def compare_results(
    baseline: Fingerprint,
    candidate: Fingerprint,
    *,
    has_order: bool,
    has_limit: bool,
    total: bool,
) -> CorrectnessOutcome:
    if baseline.truncated or candidate.truncated:
        return CorrectnessOutcome(
            "inconclusive", "result_too_large", "result exceeds the row hash cap"
        )
    if baseline.rows == candidate.rows and baseline.multiset == candidate.multiset:
        if has_order and total and baseline.ordered != candidate.ordered:
            return CorrectnessOutcome(
                "mismatch",
                "result_mismatch",
                "same rows in a different order under a total ORDER BY",
            )
        return CorrectnessOutcome("match")
    if has_order and has_limit and not total:
        # LIMIT over a non-total ORDER BY may legitimately pick different tied rows.
        return CorrectnessOutcome(
            "inconclusive", "nondeterministic_order", "ORDER BY with ties under LIMIT"
        )
    detail = (
        f"row count {baseline.rows} vs {candidate.rows}"
        if baseline.rows != candidate.rows
        else "same row count, different rows"
    )
    return CorrectnessOutcome("mismatch", "result_mismatch", detail)


def _order_column(node: exp.Expression) -> exp.Column | None:
    inner = node.this if isinstance(node, exp.Ordered) else node
    return inner if isinstance(inner, exp.Column) else None


def order_is_total(sql: str, unique_keys: Mapping[str, Sequence[Sequence[str]]]) -> bool:
    """True only when provable: one base table and its ORDER BY covers a unique key.

    Conservative by design: an unprovable total order means a reordering with equal multisets
    is accepted, and different rows under LIMIT are `inconclusive` rather than `rejected`.
    """
    try:
        tree = sqlglot.parse_one(sql, read=DIALECT)
    except (sqlglot.errors.ParseError, sqlglot.errors.TokenError):
        return False
    order = tree.args.get("order")
    if not isinstance(tree, exp.Select) or order is None or tree.args.get("joins"):
        return False
    tables = list(tree.find_all(exp.Table))
    if len(tables) != 1:
        return False
    table = tables[0]
    names = {table.name, table.alias_or_name}
    columns = {
        col.name
        for node in order.expressions
        if (col := _order_column(node)) is not None and (not col.table or col.table in names)
    }
    return any(key and set(key) <= columns for key in unique_keys.get(table.name, ()))
