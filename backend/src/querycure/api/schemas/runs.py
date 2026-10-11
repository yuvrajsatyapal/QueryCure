import datetime as dt
import uuid
from typing import Any

from pydantic import BaseModel


class RunEvent(BaseModel):
    run_id: uuid.UUID
    seq: int
    ts: dt.datetime
    type: str
    payload: dict[str, Any]


class RunEventPage(BaseModel):
    items: list[RunEvent]
    next_cursor: str | None
