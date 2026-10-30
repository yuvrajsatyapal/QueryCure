"""The build before the ADR-0032 activation, for version-skew and rollback tests only.

Since the activation, production `_close` classifies snapshot-era replays and new reports
seal with report-builder@2 / report-md@2. Two cutover tests still need the *previous* build
in-process: an old worker sealing while the activated API serves (skew), and the code after
the activation commit is reverted (rollback, REPLAY_OUTCOME_AUDIT §17.10). That build sealed
every run with report-builder@1 / report-md@1 and every replay with its own winner-based
outcome, which is exactly what the activated code does for a `legacy` contract replay. So the
old build is reproduced by two settings: v1 current, and every replay's contract `legacy`.

It substitutes nothing on the activated path: it is only ever applied inside a
`monkeypatch.context()` that names the old build. Nothing in `querycure` imports it, and the
Docker image does not contain `tests/`.
"""

import uuid
from collections.abc import Callable
from typing import Any

from querycure.replay import cutover, experiment_replay
from querycure.replay.cutover import ReplayContract
from querycure.reports import registry

SetAttr = Callable[[Any, str, Any], None]


async def _always_legacy(conn: Any, replay_run_id: uuid.UUID) -> ReplayContract:
    return "legacy"


def deactivate(setattr: SetAttr) -> None:
    """Apply the pre-activation build through `setattr` (pytest's `monkeypatch.setattr`)."""
    setattr(registry, "CURRENT_BUILDER", registry.LEGACY_REPORT_VERSIONS.builder)
    setattr(registry, "CURRENT_RENDERER", registry.LEGACY_REPORT_VERSIONS.renderer)
    setattr(registry, "CURRENT_SCHEMA_VERSION", registry.LEGACY_REPORT_VERSIONS.schema_version)
    setattr(cutover, "replay_contract", _always_legacy)
    setattr(experiment_replay, "replay_contract", _always_legacy)
