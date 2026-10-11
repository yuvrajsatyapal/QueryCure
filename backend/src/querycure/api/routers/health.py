from pathlib import Path

from alembic.config import Config
from alembic.script import ScriptDirectory
from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError

router = APIRouter(tags=["health"])
MIGRATIONS = Path(__file__).resolve().parents[4] / "migrations"


class HealthResponse(BaseModel):
    status: str


class ReadinessResponse(BaseModel):
    status: str
    database: str
    migrations: str


def _head_revision() -> str | None:
    cfg = Config()
    cfg.set_main_option("script_location", str(MIGRATIONS))
    return ScriptDirectory.from_config(cfg).get_current_head()


@router.get("/healthz")
async def healthz() -> HealthResponse:
    """Liveness only: the process is up."""
    return HealthResponse(status="ok")


@router.get("/readyz", response_model=ReadinessResponse)
async def readyz(request: Request) -> ReadinessResponse | JSONResponse:
    """Readiness: metadata DB reachable and migrated to head (API_DESIGN §2)."""
    engine = request.app.state.engine
    database, migrations = "unconfigured", "unknown"
    if engine is not None:
        try:
            async with engine.connect() as conn:
                current = (
                    await conn.execute(text("SELECT version_num FROM alembic_version"))
                ).scalar_one_or_none()
            database = "ok"
            migrations = "current" if current == _head_revision() else "behind"
        except SQLAlchemyError:
            database = "unreachable"
    ready = database == "ok" and migrations == "current"
    body = ReadinessResponse(
        status="ok" if ready else "not_ready", database=database, migrations=migrations
    )
    if ready:
        return body
    return JSONResponse(body.model_dump(), status_code=503)
