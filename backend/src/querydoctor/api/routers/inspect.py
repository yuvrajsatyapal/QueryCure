"""Mode A (offline) inspection: nothing here touches a user database."""

from fastapi import APIRouter, Request

from querydoctor.api.deps import ConnDep, CurrentUser
from querydoctor.api.schemas.inspect import (
    InspectSchemaRequest,
    InspectSqlRequest,
    PlanInspection,
    SchemaInspection,
    SqlAnalysis,
)
from querydoctor.plans.metrics import compute_metrics
from querydoctor.plans.parser import load_plan_document, parse_plan
from querydoctor.replay import artifact_store
from querydoctor.sql.ddl import parse_ddl
from querydoctor.sql.validator import SqlPolicy, validate_select

router = APIRouter(prefix="/inspect", tags=["inspect"])

_PLAN_BODY = {
    "requestBody": {
        "required": True,
        "content": {
            "application/json": {"schema": {"description": "EXPLAIN (FORMAT JSON) output"}}
        },
    }
}


@router.post("/sql")
async def inspect_sql(body: InspectSqlRequest, _user: CurrentUser) -> SqlAnalysis:
    query = validate_select(body.query, SqlPolicy(allow_user_functions=body.allow_user_functions))
    return SqlAnalysis(
        statement_type=query.statement_type, metadata=query.metadata, fingerprint=query.fingerprint
    )


@router.post("/plan", openapi_extra=_PLAN_BODY)
async def inspect_plan(request: Request, conn: ConnDep, _user: CurrentUser) -> PlanInspection:
    document = load_plan_document(await request.body())
    tree = parse_plan(document)
    artifact = await artifact_store.store_json(
        conn, kind="plan_analyze" if tree.analyzed else "plan", value=document
    )
    return PlanInspection(artifact_sha256=artifact.sha256, plan=tree, metrics=compute_metrics(tree))


@router.post("/schema")
async def inspect_schema(
    body: InspectSchemaRequest, conn: ConnDep, _user: CurrentUser
) -> SchemaInspection:
    schema = parse_ddl(body.ddl)
    artifact = await artifact_store.store_json(conn, kind="schema_snapshot", value=schema)
    return SchemaInspection(artifact_sha256=artifact.sha256, schema=schema)
