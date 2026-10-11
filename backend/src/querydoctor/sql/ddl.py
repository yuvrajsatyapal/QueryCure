"""Offline schema from DDL text (Mode A). DDL is parsed, never executed."""

import sqlglot
from pydantic import BaseModel, ConfigDict, Field
from sqlglot import exp
from sqlglot.errors import ParseError, TokenError

from querydoctor.core.errors import PayloadTooLargeError, SqlParseError
from querydoctor.sql.parser import DIALECT
from querydoctor.sql.validator import _pg_name

MAX_DDL_BYTES = 1024 * 1024
MAX_WARNINGS = 50


class DeclaredColumn(BaseModel):
    model_config = ConfigDict(frozen=True)

    name: str
    data_type: str | None
    not_null: bool


class DeclaredTable(BaseModel):
    schema_name: str | None
    name: str
    columns: list[DeclaredColumn]
    primary_key: list[str] = Field(default_factory=list)


class DeclaredIndex(BaseModel):
    model_config = ConfigDict(frozen=True)

    name: str
    table: str
    columns: list[str]
    unique: bool
    method: str | None
    predicate: str | None


class DeclaredSchema(BaseModel):
    tables: list[DeclaredTable]
    indexes: list[DeclaredIndex]
    warnings: list[str]


def _columns_of(node: exp.Expression) -> list[str]:
    return [
        name
        for e in node.expressions
        if (name := _pg_name(e if isinstance(e, exp.Identifier) else e.this))
    ]


def _table(create: exp.Create) -> DeclaredTable | None:
    schema = create.this
    if not isinstance(schema, exp.Schema) or not isinstance(schema.this, exp.Table):
        return None
    table = schema.this
    columns: list[DeclaredColumn] = []
    primary_key: list[str] = []
    for item in schema.expressions:
        if isinstance(item, exp.ColumnDef):
            name = _pg_name(item.this) or item.name
            constraints = [c.args.get("kind") for c in item.args.get("constraints") or []]
            is_pk = any(isinstance(k, exp.PrimaryKeyColumnConstraint) for k in constraints)
            not_null = is_pk or any(isinstance(k, exp.NotNullColumnConstraint) for k in constraints)
            kind = item.args.get("kind")
            columns.append(
                DeclaredColumn(
                    name=name,
                    data_type=kind.sql(dialect=DIALECT)
                    if isinstance(kind, exp.Expression)
                    else None,
                    not_null=not_null,
                )
            )
            if is_pk:
                primary_key.append(name)
        elif (pk := item.find(exp.PrimaryKey)) is not None:
            primary_key = _columns_of(pk)
    return DeclaredTable(
        schema_name=_pg_name(table.args.get("db")),
        name=_pg_name(table.this) or table.name,
        columns=columns,
        primary_key=primary_key,
    )


def _index(create: exp.Create) -> DeclaredIndex | None:
    index = create.this
    if not isinstance(index, exp.Index):
        return None
    params = index.args.get("params")
    columns = [c.sql(dialect=DIALECT) for c in params.args.get("columns", [])] if params else []
    where = params.args.get("where") if params else None
    using = params.args.get("using") if params else None
    table = index.args.get("table")
    return DeclaredIndex(
        name=index.name,
        table=table.sql(dialect=DIALECT) if isinstance(table, exp.Expression) else "",
        columns=columns,
        unique=bool(create.args.get("unique")),
        method=(using.sql(dialect=DIALECT) if isinstance(using, exp.Expression) else str(using))
        if using is not None
        else None,
        predicate=where.this.sql(dialect=DIALECT) if isinstance(where, exp.Where) else None,
    )


def parse_ddl(text: str) -> DeclaredSchema:
    if len(text.encode()) > MAX_DDL_BYTES:
        raise PayloadTooLargeError("DDL upload is larger than 1 MB.")
    try:
        statements = [s for s in sqlglot.parse(text, read=DIALECT) if s is not None]
    except (ParseError, TokenError) as exc:
        raise SqlParseError(
            "DDL could not be parsed.", details=[{"field": "ddl", "message": str(exc)[:300]}]
        ) from exc
    except RecursionError as exc:
        raise SqlParseError("DDL is nested too deeply to parse.") from exc
    if not statements:
        raise SqlParseError("DDL is empty.", details=[{"field": "ddl", "message": "no statements"}])
    tables: dict[tuple[str | None, str], DeclaredTable] = {}
    indexes: list[DeclaredIndex] = []
    warnings: list[str] = []
    for statement in statements:
        kind = str(statement.args.get("kind") or "").upper()
        handled = False
        if isinstance(statement, exp.Create) and kind == "TABLE":
            if (table := _table(statement)) is not None:
                tables[(table.schema_name, table.name)] = table
                handled = True
        elif isinstance(statement, exp.Create) and kind == "INDEX":
            if (index := _index(statement)) is not None:
                indexes.append(index)
                handled = True
        elif isinstance(statement, exp.Alter) and isinstance(statement.this, exp.Table):
            key = (_pg_name(statement.this.args.get("db")), _pg_name(statement.this.this) or "")
            pk = statement.find(exp.PrimaryKey)
            if pk is not None and key in tables:
                tables[key].primary_key = _columns_of(pk)
                handled = True
        if not handled and len(warnings) < MAX_WARNINGS:
            warnings.append(f"skipped {statement.key.upper()} statement")
    for table in tables.values():
        if table.primary_key:
            table.columns = [
                c.model_copy(update={"not_null": True}) if c.name in table.primary_key else c
                for c in table.columns
            ]
    return DeclaredSchema(tables=list(tables.values()), indexes=indexes, warnings=warnings)
