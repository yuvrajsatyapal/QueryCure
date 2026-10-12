"""Sandbox DDL allowlist for optimization candidates (SECURITY §6.5, T3.8).

Exactly three statement forms, parsed by a strict hand-written grammar that fails closed:

    CREATE INDEX [IF NOT EXISTS] [name] ON [public.]table [USING method]
        (element [, ...]) [INCLUDE (column [, ...])] [WHERE predicate]
    CREATE STATISTICS [IF NOT EXISTS] [name] [(ndistinct|dependencies|mcv, ...)]
        ON column, column [, ...] FROM [public.]table
    ANALYZE [public.]table [(column [, ...])]

The table must be one the baseline query references. Comments, dollar quotes, escape strings,
storage parameters, tablespaces, UNIQUE and CONCURRENTLY are refused (the sandbox runs exactly
the approved text, non-concurrently). Index expressions and predicates go through the SELECT
validator (function denylist) and may not contain subqueries.

This is defense in depth: the statements run as qc_bench in a disposable clone after approval,
and qc_bench cannot reach programs, server files, roles or other databases (SECURITY §8).
"""

import re
from dataclasses import dataclass, field
from typing import Literal

import sqlglot
from sqlglot import exp

from querycure.core.errors import QueryCureError, SandboxPolicyError
from querycure.sql.parser import DIALECT
from querycure.sql.validator import ValidatedQuery, validate_select

DdlKind = Literal["create_index", "create_statistics", "analyze"]
MAX_DDL_PER_CANDIDATE = 4
MAX_STATEMENT_BYTES = 4_000
INDEX_METHODS = frozenset({"btree", "hash", "gin", "gist", "brin"})
STATISTICS_KINDS = frozenset({"ndistinct", "dependencies", "mcv"})

_TOKEN = re.compile(
    r"""
    (?P<ws>\s+)
  | (?P<comment>--|/\*)
  | (?P<dollar>\$)
  | (?P<escape>[EeUu]&?')
  | (?P<string>'(?:[^']|'')*')
  | (?P<quoted>"[^"]{1,63}")
  | (?P<word>[A-Za-z_][A-Za-z0-9_]*)
  | (?P<number>\d+(?:\.\d+)?)
  | (?P<punct>[(),;.])
  | (?P<op>[=<>!+\-*/%:|&~^@\#]+)
    """,
    re.VERBOSE,
)


def _deny(message: str) -> SandboxPolicyError:
    return SandboxPolicyError(message, details=[{"field": "ddl", "message": message}])


@dataclass(frozen=True)
class _Tok:
    kind: str
    text: str
    start: int
    end: int

    def word(self) -> str | None:
        return self.text.lower() if self.kind == "word" else None


def _tokenize(text: str) -> list[_Tok]:
    tokens: list[_Tok] = []
    pos = 0
    while pos < len(text):
        m = _TOKEN.match(text, pos)
        if m is None:
            raise _deny(f"Unexpected character {text[pos]!r} in DDL.")
        kind = m.lastgroup or ""
        if kind == "comment":
            raise _deny("Comments are not allowed in candidate DDL.")
        if kind == "dollar":
            raise _deny("Dollar quotes and parameters are not allowed in candidate DDL.")
        if kind == "escape":
            raise _deny("Escape and Unicode string syntax is not allowed in candidate DDL.")
        if kind != "ws":
            tokens.append(_Tok(kind, m.group(), m.start(), m.end()))
        pos = m.end()
    return tokens


@dataclass(frozen=True)
class AllowedDdl:
    kind: DdlKind
    table: str
    columns: list[str]
    statement: str  # the exact approved text, without a trailing semicolon


@dataclass
class _Cursor:
    text: str
    toks: list[_Tok]
    i: int = 0

    def peek(self, offset: int = 0) -> _Tok | None:
        j = self.i + offset
        return self.toks[j] if j < len(self.toks) else None

    def peek_word(self, offset: int = 0) -> str | None:
        tok = self.peek(offset)
        return tok.word() if tok else None

    def take(self) -> _Tok:
        tok = self.peek()
        if tok is None:
            raise _deny("Statement ends unexpectedly.")
        self.i += 1
        return tok

    def accept(self, *words: str) -> bool:
        if all(self.peek_word(k) == w for k, w in enumerate(words)):
            self.i += len(words)
            return True
        return False

    def expect_punct(self, char: str, what: str) -> None:
        tok = self.take()
        if tok.text != char:
            raise _deny(f"Expected {what}, found {tok.text!r}.")

    def at_end(self) -> bool:
        return self.i >= len(self.toks)


def _identifier(tok: _Tok) -> str:
    if tok.kind == "word":
        return tok.text.lower()
    if tok.kind == "quoted":
        return tok.text[1:-1]
    raise _deny(f"Expected an identifier, found {tok.text!r}.")


_RESERVED = frozenset({"on", "using", "include", "where", "from", "if", "only"})


def _table(cur: _Cursor, allowed_tables: set[str]) -> str:
    if cur.peek_word() == "only":
        raise _deny("ONLY is not allowed in candidate DDL.")
    first = _identifier(cur.take())
    name = first
    if cur.peek() is not None and cur.peek().text == ".":  # type: ignore[union-attr]
        cur.take()
        if first != "public":
            raise _deny("Only tables in the public schema can be targeted.")
        name = _identifier(cur.take())
    if name not in allowed_tables:
        raise _deny(f"Table {name!r} is not referenced by the query under investigation.")
    return name


def _paren_items(cur: _Cursor) -> list[tuple[int, int]]:
    """Top-level comma-separated items of a parenthesized list, as token index ranges."""
    cur.expect_punct("(", "'('")
    items: list[tuple[int, int]] = []
    start, depth = cur.i, 0
    while True:
        tok = cur.peek()
        if tok is None:
            raise _deny("Unbalanced parentheses in candidate DDL.")
        if tok.text == "(":
            depth += 1
        elif tok.text == ")":
            if depth == 0:
                if cur.i == start:
                    raise _deny("Empty list in candidate DDL.")
                items.append((start, cur.i))
                cur.take()
                return items
            depth -= 1
        elif tok.text == "," and depth == 0:
            if cur.i == start:
                raise _deny("Empty list item in candidate DDL.")
            items.append((start, cur.i))
            start = cur.i + 1
        elif tok.text == ";":
            raise _deny("Unbalanced parentheses in candidate DDL.")
        cur.take()


def _slice(cur: _Cursor, start: int, end: int) -> str:
    return cur.text[cur.toks[start].start : cur.toks[end - 1].end]


def _check_expression(table: str, sql_text: str, *, what: str, where: bool) -> None:
    # Parsed and validated only, never executed: the probe reuses the SELECT validator.
    probe = (
        f"SELECT 1 FROM {table} WHERE {sql_text}"  # noqa: S608
        if where
        else f"SELECT {sql_text} FROM {table}"  # noqa: S608
    )
    try:
        validated = validate_select(probe)
    except QueryCureError as exc:
        raise _deny(f"{what} rejected: {exc.message}") from exc
    if validated.metadata.parameter_count:
        raise _deny(f"{what} must not contain parameters.")
    tree = sqlglot.parse_one(probe, read=DIALECT)
    if sum(1 for _ in tree.find_all(exp.Select)) > 1:
        raise _deny(f"{what} must not contain a subquery.")


_DIRECTION = frozenset({"asc", "desc"})


def _index_element(cur: _Cursor, table: str, start: int, end: int) -> str | None:
    toks = cur.toks[start:end]
    words = [t.word() for t in toks]
    if toks[0].kind in ("word", "quoted") and words[0] not in _RESERVED:
        rest = words[1:]
        while rest and rest[0] in _DIRECTION:
            rest = rest[1:]
        if rest[:2] in (["nulls", "first"], ["nulls", "last"]):
            rest = rest[2:]
        if not rest and toks[0].kind in ("word", "quoted"):
            return _identifier(toks[0])
    # An expression: `lower(col)` or `(expr)`, optionally followed by a direction.
    tail = end
    while tail > start and cur.toks[tail - 1].word() in (*_DIRECTION, "first", "last", "nulls"):
        tail -= 1
    _check_expression(table, _slice(cur, start, tail), what="Index expression", where=False)
    return None


def _create_index(cur: _Cursor, allowed: set[str]) -> AllowedDdl:
    if cur.accept("if", "not", "exists"):
        pass
    if cur.peek_word() != "on":
        _identifier(cur.take())  # index name
    if not cur.accept("on"):
        raise _deny("Expected ON after the index name.")
    table = _table(cur, allowed)
    if cur.accept("using"):
        method = cur.take().text.lower()
        if method not in INDEX_METHODS:
            raise _deny(f"Index method {method!r} is not allowed.")
    columns = [
        col
        for start, end in _paren_items(cur)
        if (col := _index_element(cur, table, start, end)) is not None
    ]
    if cur.accept("include"):
        for start, end in _paren_items(cur):
            if end - start != 1:
                raise _deny("INCLUDE accepts plain columns only.")
            _identifier(cur.toks[start])
    if cur.accept("where"):
        start = cur.i
        while not cur.at_end() and cur.peek().text != ";":  # type: ignore[union-attr]
            cur.take()
        if cur.i == start:
            raise _deny("Empty index predicate.")
        _check_expression(table, _slice(cur, start, cur.i), what="Index predicate", where=True)
    return AllowedDdl(kind="create_index", table=table, columns=columns, statement="")


def _create_statistics(cur: _Cursor, allowed: set[str]) -> AllowedDdl:
    cur.accept("if", "not", "exists")
    if cur.peek_word() not in ("on", None) and cur.peek().text != "(":  # type: ignore[union-attr]
        _identifier(cur.take())
    if cur.peek() is not None and cur.peek().text == "(":  # type: ignore[union-attr]
        for start, end in _paren_items(cur):
            kind = cur.toks[start].word()
            if end - start != 1 or kind not in STATISTICS_KINDS:
                raise _deny(f"Unknown statistics kind {_slice(cur, start, end)!r}.")
    if not cur.accept("on"):
        raise _deny("Expected ON in CREATE STATISTICS.")
    columns = [_identifier(cur.take())]
    while cur.peek() is not None and cur.peek().text == ",":  # type: ignore[union-attr]
        cur.take()
        columns.append(_identifier(cur.take()))
    if len(columns) < 2:
        raise _deny("Extended statistics need at least two columns.")
    if not cur.accept("from"):
        raise _deny("Expected FROM in CREATE STATISTICS.")
    table = _table(cur, allowed)
    return AllowedDdl(kind="create_statistics", table=table, columns=columns, statement="")


def _analyze(cur: _Cursor, allowed: set[str]) -> AllowedDdl:
    if cur.peek_word() == "verbose":
        raise _deny("ANALYZE VERBOSE is not allowed.")
    if cur.at_end() or cur.peek().text == ";":  # type: ignore[union-attr]
        raise _deny("ANALYZE needs a table referenced by the query.")
    table = _table(cur, allowed)
    columns: list[str] = []
    if cur.peek() is not None and cur.peek().text == "(":  # type: ignore[union-attr]
        for start, end in _paren_items(cur):
            if end - start != 1:
                raise _deny("ANALYZE accepts plain columns only.")
            columns.append(_identifier(cur.toks[start]))
    return AllowedDdl(kind="analyze", table=table, columns=columns, statement="")


def validate_ddl(statement: str, *, allowed_tables: set[str]) -> AllowedDdl:
    if len(statement.encode()) > MAX_STATEMENT_BYTES:
        raise _deny("Candidate DDL statement is too long.")
    toks = _tokenize(statement)
    if not toks:
        raise _deny("Empty statement.")
    cur = _Cursor(statement, toks)
    first = cur.take().word()
    if first == "create":
        nxt = cur.peek_word()
        if nxt == "unique":
            raise _deny("UNIQUE indexes are not allowed (they constrain writes, not reads).")
        if cur.accept("index"):
            if cur.peek_word() == "concurrently":
                raise _deny(
                    "CONCURRENTLY is not used in the sandbox; propose the plain statement "
                    "(production rollout notes cover CONCURRENTLY)."
                )
            ddl = _create_index(cur, allowed_tables)
        elif cur.accept("statistics"):
            ddl = _create_statistics(cur, allowed_tables)
        else:
            raise _deny("This statement is not in the sandbox DDL allowlist.")
    elif first == "analyze":
        ddl = _analyze(cur, allowed_tables)
    else:
        raise _deny("This statement is not in the sandbox DDL allowlist.")
    end = cur.i
    if not cur.at_end():
        tok = cur.take()
        if tok.text != ";":
            raise _deny(f"Unexpected {tok.text!r} after the statement.")
        if not cur.at_end():
            raise _deny("Candidate DDL must be a single statement.")
    text = statement[: toks[end - 1].end].strip()
    return AllowedDdl(kind=ddl.kind, table=ddl.table, columns=ddl.columns, statement=text)


@dataclass(frozen=True)
class ValidatedCandidate:
    kind: str
    ddl: list[AllowedDdl] = field(default_factory=list)
    query: ValidatedQuery | None = None


_DDL_KIND_FOR = {
    "create_index": {"create_index"},
    "analyze_statistics": {"analyze"},
    "extended_statistics": {"create_statistics", "analyze"},
}


def validate_candidate(
    *, kind: str, ddl: list[str], query: str | None, baseline: str
) -> ValidatedCandidate:
    """The whole candidate: allowlisted DDL of the matching kind, or a SELECT rewrite."""
    base = validate_select(baseline)
    tables = {t.name for t in base.metadata.tables if t.schema_name in (None, "public")}
    if len(ddl) > MAX_DDL_PER_CANDIDATE:
        raise _deny(f"A candidate may have at most {MAX_DDL_PER_CANDIDATE} DDL statements.")
    if kind == "query_rewrite":
        if ddl:
            raise _deny("A query_rewrite candidate has no DDL.")
        if not query:
            raise _deny("A query_rewrite candidate needs the rewritten query.")
        try:
            rewritten = validate_select(query)
        except QueryCureError as exc:
            raise _deny(f"The rewrite must be a single SELECT: {exc.message}") from exc
        if rewritten.metadata.parameter_count != base.metadata.parameter_count:
            raise _deny("The rewrite must take the same parameters as the original query.")
        return ValidatedCandidate(kind=kind, query=rewritten)
    if kind not in _DDL_KIND_FOR:
        raise _deny(f"Unknown candidate kind {kind!r}.")
    if query is not None:
        raise _deny(f"A {kind} candidate runs the original query; it has no rewrite.")
    if not ddl:
        raise _deny(f"A {kind} candidate needs DDL; it has no DDL.")
    validated = [validate_ddl(s, allowed_tables=tables) for s in ddl]
    allowed = _DDL_KIND_FOR[kind]
    for item in validated:
        if item.kind not in allowed:
            raise _deny(f"A {kind} candidate cannot contain {item.kind} statements.")
    if kind == "extended_statistics":
        stats_tables = {d.table for d in validated if d.kind == "create_statistics"}
        analyzed = {d.table for d in validated if d.kind == "analyze"}
        if not stats_tables or not stats_tables <= analyzed or validated[-1].kind != "analyze":
            raise _deny("Extended statistics only take effect after ANALYZE of the same table.")
    return ValidatedCandidate(kind=kind, ddl=validated)
