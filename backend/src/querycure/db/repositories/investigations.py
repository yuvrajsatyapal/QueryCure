import uuid

from pydantic import BaseModel, ConfigDict
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

from querycure.core.errors import InvalidStateError


class RunInputs(BaseModel):
    """What the worker needs to start a run: references only, read at intake."""

    model_config = ConfigDict(frozen=True)

    run_id: uuid.UUID
    investigation_id: uuid.UUID
    user_id: uuid.UUID
    objective: str
    modes: list[str]
    connection_id: uuid.UUID | None
    workload_id: str | None
    artifacts: dict[str, str]  # role -> sha256, e.g. "input.query" -> digest


async def get_run_inputs(conn: AsyncConnection, run_id: uuid.UUID) -> RunInputs:
    row = (
        await conn.execute(
            text(
                "SELECT r.id AS run_id, i.id AS investigation_id, i.user_id, i.objective, i.modes, "
                "i.connection_id, i.workload_id FROM investigation_runs r "
                "JOIN investigations i ON i.id = r.investigation_id WHERE r.id = :id"
            ),
            {"id": run_id},
        )
    ).first()
    if row is None:
        raise InvalidStateError("Run not found.")
    roles = await conn.execute(
        text(
            "SELECT ra.role, a.sha256 FROM run_artifacts ra "
            "JOIN artifacts a ON a.id = ra.artifact_id "
            "WHERE ra.run_id = :id AND ra.role LIKE 'input.%' ORDER BY ra.role"
        ),
        {"id": run_id},
    )
    return RunInputs(
        **row._mapping,
        artifacts={r.role: r.sha256 for r in roles},
    )
