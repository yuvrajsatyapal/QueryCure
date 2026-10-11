import datetime as dt
import uuid
from typing import Any

from pydantic import BaseModel, ConfigDict
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection


class EventRecord(BaseModel):
    model_config = ConfigDict(frozen=True)

    run_id: uuid.UUID
    seq: int
    type: str
    payload: dict[str, Any]
    created_at: dt.datetime


async def list_events(
    conn: AsyncConnection, *, run_id: uuid.UUID, after_seq: int, limit: int
) -> list[EventRecord]:
    rows = await conn.execute(
        text(
            "SELECT run_id, seq, type, payload, created_at FROM investigation_events "
            "WHERE run_id = :run_id AND seq > :after ORDER BY seq LIMIT :limit"
        ),
        {"run_id": run_id, "after": after_seq, "limit": limit},
    )
    return [EventRecord.model_validate(r, from_attributes=True) for r in rows]
