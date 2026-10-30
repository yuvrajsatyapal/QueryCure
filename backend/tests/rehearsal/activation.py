"""The simulated replay-outcome activation (Workstream 5), test code only.

The approved activation (REPLAY_OUTCOME_AUDIT §16.5) is one change in `_close`: load the source
snapshot, classify, and finalize with the classifier's conclusion while report-builder@2 /
report-md@2 are current. Until it is approved, tests reach that path by patching the same two
seams in-process: the registry's current builder and renderer, and `finalize_run` as
`experiment_replay` sees it. Nothing here is importable from `querycure` (the package never
depends on `tests`, and the Docker image copies `src` only), so production execution cannot
take this path.
"""

import dataclasses
import json
import uuid
from collections.abc import Callable
from typing import Any

from sqlalchemy import text

from querycure.replay import experiment_replay
from querycure.replay.artifact_store import get_artifact
from querycure.replay.outcome import classify_replay_outcome
from querycure.replay.source_snapshot import SourceSnapshotError, load_source_snapshot
from querycure.reports import registry

SetAttr = Callable[[Any, str, Any], None]


def classifying_finalize(real_finalize: Any) -> Any:
    """`finalize_run` whose completed replay conclusion comes from the classifier."""

    async def finalize(conn: Any, run_id: uuid.UUID, conclusion: Any, **kw: Any) -> Any:
        if conclusion.final_status.value != "completed":
            return await real_finalize(conn, run_id, conclusion, **kw)
        try:
            snapshot = await load_source_snapshot(conn, run_id)
        except SourceSnapshotError:
            snapshot = None  # an unusable snapshot counts as none (§16.5 step 2)
        sha = (
            await conn.execute(
                text(
                    "SELECT a.sha256 FROM run_artifacts ra JOIN artifacts a ON a.id = "
                    "ra.artifact_id WHERE ra.run_id = :r AND ra.role = 'replay.comparison'"
                ),
                {"r": run_id},
            )
        ).scalar_one_or_none()
        stored = None if sha is None else await get_artifact(conn, sha)
        cmp = None if stored is None else json.loads(stored.content)
        c = classify_replay_outcome(snapshot, cmp)
        return await real_finalize(
            conn,
            run_id,
            dataclasses.replace(
                conclusion,
                final_status=c.run_status,
                outcome=c.outcome,
                replay_basis=c.as_basis(),
            ),
            **kw,
        )

    return finalize


def activate(setattr: SetAttr) -> None:
    """Apply the simulated activation through `setattr` (pytest's `monkeypatch.setattr`, or
    the builtin in the rehearsal worker process)."""
    setattr(registry, "CURRENT_BUILDER", "report-builder@2")
    setattr(registry, "CURRENT_RENDERER", "report-md@2")
    setattr(experiment_replay, "finalize_run", classifying_finalize(experiment_replay.finalize_run))
