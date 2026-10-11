import datetime as dt
import uuid
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, SecretStr

from querydoctor.connectors.models import SslMode, TargetCapabilities
from querydoctor.db.repositories.connections import ConnectionRecord
from querydoctor.plans.metrics import NodeMetrics
from querydoctor.plans.models import PlanTree
from querydoctor.sql.fingerprint import QueryFingerprint
from querydoctor.sql.validator import QueryMetadata

Environment = Literal["development", "staging", "production"]
Purpose = Literal["inspection", "sandbox"]


class CreateConnectionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=1, max_length=100)
    host: str = Field(min_length=1, max_length=253)
    port: int = Field(default=5432, ge=1, le=65535)
    dbname: str = Field(min_length=1, max_length=63)
    username: str = Field(min_length=1, max_length=63)
    password: SecretStr = Field(min_length=1, max_length=1024)
    sslmode: SslMode = "verify-full"
    environment: Environment
    purpose: Purpose = "inspection"


class ConnectionSummary(BaseModel):
    id: uuid.UUID
    name: str
    host: str
    port: int
    dbname: str
    username: str
    sslmode: str
    environment: str
    purpose: str
    has_password: bool
    capabilities: dict[str, Any] | None
    last_tested_at: dt.datetime | None
    last_test_status: str | None
    created_at: dt.datetime

    @classmethod
    def from_record(cls, record: ConnectionRecord) -> "ConnectionSummary":
        return cls(
            **record.model_dump(
                exclude={"user_id", "password_ciphertext", "password_nonce", "key_version"}
            ),
            has_password=record.password_ciphertext is not None,
        )


class ConnectionList(BaseModel):
    items: list[ConnectionSummary]
    next_cursor: str | None = None


class ConnectionTestResponse(BaseModel):
    status: Literal["ok"]
    capabilities: TargetCapabilities
    warnings: list[str]


class ExplainRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    query: str = Field(min_length=1, max_length=100_000)
    allow_user_functions: bool = False


class QueryInfo(BaseModel):
    statement_type: str
    fingerprint: QueryFingerprint
    metadata: QueryMetadata


class ExplainResponse(BaseModel):
    plan: PlanTree
    metrics: list[NodeMetrics]
    generic_plan: bool
    query: QueryInfo
