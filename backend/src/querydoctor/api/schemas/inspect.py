from pydantic import BaseModel, ConfigDict, Field

from querydoctor.plans.metrics import NodeMetrics
from querydoctor.plans.models import PlanTree
from querydoctor.sql.ddl import MAX_DDL_BYTES, DeclaredSchema
from querydoctor.sql.fingerprint import QueryFingerprint
from querydoctor.sql.validator import QueryMetadata


class InspectSqlRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    query: str = Field(min_length=1, max_length=100_000)
    allow_user_functions: bool = False


class SqlAnalysis(BaseModel):
    statement_type: str
    metadata: QueryMetadata
    fingerprint: QueryFingerprint


class InspectSchemaRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    ddl: str = Field(min_length=1, max_length=MAX_DDL_BYTES)


class PlanInspection(BaseModel):
    artifact_sha256: str
    plan: PlanTree
    metrics: list[NodeMetrics]


class SchemaInspection(BaseModel):
    artifact_sha256: str
    schema_: DeclaredSchema = Field(alias="schema", serialization_alias="schema")

    model_config = ConfigDict(populate_by_name=True)
