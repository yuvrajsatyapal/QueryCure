"""The activation boundary of the replay outcome correction (REPLAY_OUTCOME_AUDIT §18.4).

Read-only, and not called by the worker or the API: it answers the two questions the cutover
needs before ADR-0032 is activated.

- `replay_contract`: which contract a replay was created under, fixed at creation. `legacy`
  means no snapshot marker and no snapshot links (started before the snapshot code was
  deployed); `snapshot` means it was started with them. A replay whose snapshot records are
  damaged or contradictory is `snapshot` too, so it fails closed and never passes for legacy.
- `in_flight_replays`: experiment replays whose run is not sealed yet, with their contract. A
  sealed run can no longer change (a later job claim is a no-op), whatever its attempt row says.
  Activation waits until no `legacy` replay is in flight (`python -m querycure.ops
  replay-cutover-check` exits 1 while one is).
"""

import uuid
from dataclasses import dataclass
from datetime import datetime
from typing import Literal

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

from querycure.replay.source_snapshot import SourceSnapshotError, load_source_snapshot

ReplayContract = Literal["legacy", "snapshot"]


async def replay_contract(conn: AsyncConnection, replay_run_id: uuid.UUID) -> ReplayContract:
    try:
        snapshot = await load_source_snapshot(conn, replay_run_id)
    except SourceSnapshotError:
        return "snapshot"
    return "legacy" if snapshot is None else "snapshot"


@dataclass(frozen=True)
class InFlightReplay:
    attempt_id: uuid.UUID
    replay_run_id: uuid.UUID
    attempt_status: str
    run_status: str
    created_at: datetime
    contract: ReplayContract


async def in_flight_replays(conn: AsyncConnection) -> list[InFlightReplay]:
    rows = (
        await conn.execute(
            text(
                "SELECT a.id, a.replay_run_id, a.status, r.status AS run_status, a.created_at "
                "FROM replay_attempts a JOIN investigation_runs r ON r.id = a.replay_run_id "
                "WHERE a.kind = 'experiment' AND a.deleted_at IS NULL "
                "AND r.finalized_at IS NULL ORDER BY a.created_at, a.id"
            ),
        )
    ).all()
    return [
        InFlightReplay(
            attempt_id=row.id,
            replay_run_id=row.replay_run_id,
            attempt_status=row.status,
            run_status=row.run_status,
            created_at=row.created_at,
            contract=await replay_contract(conn, row.replay_run_id),
        )
        for row in rows
    ]
