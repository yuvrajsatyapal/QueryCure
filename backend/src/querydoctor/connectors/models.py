import datetime as dt
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, SecretStr

from querydoctor.sql.validator import TableRef, ValidatedQuery

SslMode = Literal["disable", "require", "verify-ca", "verify-full"]


class TargetConnection(BaseModel):
    """Explicit fields only: never a raw DSN (no service files, no extra libpq options)."""

    model_config = ConfigDict(frozen=True)

    host: str
    port: int = 5432
    dbname: str = Field(min_length=1, max_length=63)
    username: str = Field(min_length=1, max_length=63)
    password: SecretStr
    sslmode: SslMode = "verify-full"


class GatewayLimits(BaseModel):
    model_config = ConfigDict(frozen=True)

    statement_timeout_ms: int = Field(default=5000, ge=1)
    lock_timeout_ms: int = Field(default=1000, ge=1)
    idle_in_transaction_timeout_ms: int = Field(default=10000, ge=1)
    connect_timeout_s: int = Field(default=5, ge=1)


class TargetCapabilities(BaseModel):
    model_config = ConfigDict(frozen=True)

    server_version_num: int
    server_version: str
    is_superuser: bool
    can_create_role: bool
    bypasses_rls: bool
    is_replication_role: bool
    can_read_all_stats: bool
    has_pg_stat_statements: bool
    ssl_in_use: bool
    owned_tables: int
    schemas: list[str]
    warnings: list[str] = Field(default_factory=list)


class ExplainResult(BaseModel):
    model_config = ConfigDict(frozen=True)

    plan_document: list[Any]
    validated: ValidatedQuery
    generic_plan: bool
    server_version_num: int


class TableStats(BaseModel):
    model_config = ConfigDict(frozen=True)

    schema_name: str
    name: str
    kind: str
    estimated_rows: float | None
    pages: int
    total_bytes: int
    n_live_tup: int | None
    n_dead_tup: int | None
    n_mod_since_analyze: int | None
    seq_scan: int | None
    idx_scan: int | None
    last_analyze: dt.datetime | None
    last_autoanalyze: dt.datetime | None


class ColumnStats(BaseModel):
    """Numeric planner statistics only — never value samples (T1.11)."""

    model_config = ConfigDict(frozen=True)

    schema_name: str
    table_name: str
    name: str
    data_type: str
    not_null: bool
    position: int
    null_frac: float | None
    n_distinct: float | None
    avg_width: int | None
    correlation: float | None


class IndexInfo(BaseModel):
    model_config = ConfigDict(frozen=True)

    schema_name: str
    table_name: str
    name: str
    definition: str
    is_unique: bool
    is_primary: bool
    is_valid: bool
    size_bytes: int
    idx_scan: int | None


class SchemaSnapshot(BaseModel):
    model_config = ConfigDict(frozen=True)

    tables: list[TableStats]
    columns: list[ColumnStats]
    indexes: list[IndexInfo]
    unresolved: list[TableRef]
