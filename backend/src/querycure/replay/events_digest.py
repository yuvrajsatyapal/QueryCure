"""`qc-events-v1` (REPLAY_ENGINE §2, §5): the digest of a run's content events 1..cutoff.

SHA-256 over the profile tag "qc-events-v1\\n" followed by, for seq = 1..cutoff in order,
qc-json-v1({seq, type, payload, created_at}) and a LF. A missing seq is an error, never a
silently shorter stream.
"""

import hashlib
import uuid

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

from querycure.core.errors import QueryCureError
from querycure.replay.canonical import canonical_json, to_canonical

PROFILE = "qc-events-v1"


class EventLogGapError(QueryCureError):
    code = "EVENT_LOG_GAP"
    status = 500


async def events_digest(conn: AsyncConnection, run_id: uuid.UUID, cutoff_seq: int) -> str:
    rows = await conn.execute(
        text(
            "SELECT seq, type, payload, created_at FROM investigation_events "
            "WHERE run_id = :run AND seq <= :cutoff ORDER BY seq"
        ),
        {"run": run_id, "cutoff": cutoff_seq},
    )
    h = hashlib.sha256((PROFILE + "\n").encode("ascii"))
    expected = 1
    for row in rows:
        if row.seq != expected:
            raise EventLogGapError(f"Event log gap: seq {expected} is missing.")
        record = {
            "seq": row.seq,
            "type": row.type,
            "payload": row.payload,
            "created_at": row.created_at,
        }
        h.update(canonical_json(to_canonical(record)))
        h.update(b"\n")
        expected += 1
    if expected != cutoff_seq + 1:
        raise EventLogGapError(f"Event log gap: seq {expected} is missing.")
    return "sha256:" + h.hexdigest()
