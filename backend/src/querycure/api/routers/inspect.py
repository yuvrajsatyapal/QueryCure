"""Mode A (offline) inspection: nothing here touches a user database."""

from fastapi import APIRouter, Depends, Request

from querycure.api.deps import ConnDep, CurrentUser
from querycure.api.rate_limit import rate_limit
from querycure.api.schemas.inspect import (
    InspectSchemaRequest,
    InspectSqlRequest,
    PlanInspection,
    SchemaInspection,
    SqlAnalysis,
)
from querycure.db.repositories import uploads
from querycure.plans.metrics import compute_metrics
from querycure.plans.parser import load_plan_document, parse_plan
from querycure.replay import artifact_store
from querycure.sql.ddl import parse_ddl
from querycure.sql.validator import SqlPolicy, validate_select

router = APIRouter(prefix="/inspect", tags=["inspect"])

_PLAN_BODY = {
    "requestBody": {
        "required": True,
        "content": {
            "application/json": {"schema": {"description": "EXPLAIN (FORMAT JSON) output"}}
        },
    }
}


@router.post("/sql", dependencies=[Depends(rate_limit("inspect"))])
async def inspect_sql(body: InspectSqlRequest, _user: CurrentUser) -> SqlAnalysis:
    query = validate_select(body.query, SqlPolicy(allow_user_functions=body.allow_user_functions))
    return SqlAnalysis(
        statement_type=query.statement_type, metadata=query.metadata, fingerprint=query.fingerprint
    )


@router.post("/plan", openapi_extra=_PLAN_BODY, dependencies=[Depends(rate_limit("inspect"))])
async def inspect_plan(request: Request, conn: ConnDep, user: CurrentUser) -> PlanInspection:
    document = load_plan_document(await request.body())
    tree = parse_plan(document)
    artifact = await artifact_store.store_json(
        conn, kind="plan_analyze" if tree.analyzed else "plan", value=document
    )
    await uploads.record_upload(conn, user_id=user.id, artifact_id=artifact.id, kind=artifact.kind)
    return PlanInspection(artifact_sha256=artifact.sha256, plan=tree, metrics=compute_metrics(tree))


@router.post("/schema", dependencies=[Depends(rate_limit("inspect"))])
async def inspect_schema(
    body: InspectSchemaRequest, conn: ConnDep, user: CurrentUser
) -> SchemaInspection:
    schema = parse_ddl(body.ddl)
    artifact = await artifact_store.store_json(conn, kind="schema_snapshot", value=schema)
    await uploads.record_upload(conn, user_id=user.id, artifact_id=artifact.id, kind=artifact.kind)
    return SchemaInspection(artifact_sha256=artifact.sha256, schema=schema)
