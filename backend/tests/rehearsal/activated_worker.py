"""A worker with the replay-outcome correction simulated, for the local browser rehearsal only.

Run by `frontend/playwright.rehearsal.config.ts` in place of `python -m querycure.worker`:

    uv run python -m tests.rehearsal.activated_worker

It is the production worker (same runner, handlers, replay handler, comparison, classifier,
finalization, sealing) with two test-only changes applied in this process before it starts:

1. `activation.activate`: report-builder@2 / report-md@2 current and the classifier deciding a
   completed replay's conclusion (the approved `_close` change, simulated).
2. The virtual benchmark clock (`tests/integration/virtual_clock.py`): every sample's duration
   comes from a seeded profile, so the rehearsal always reaches the scenario it names instead
   of whatever this host's noise decides. Investigation runs use CLEAN; the n-th experiment
   replay uses the n-th profile of `QC_REHEARSAL_REPLAY_PROFILES` (default `CLEAN,DRIFTED`:
   reproduced, then performance drift). The sandbox still builds indexes, runs every query and
   checks every row.

It refuses to start unless the metadata DB is local and the LLM is the offline stub. Nothing in
`querycure` imports it, and the Docker image does not contain `tests/`.
"""

import asyncio
import os
from typing import Any
from urllib.parse import urlparse

from querycure.jobs import handlers
from querycure.jobs.queue import Job
from querycure.worker import __main__ as worker_main
from tests.integration import virtual_clock as vc
from tests.rehearsal import activation

SEED = 7
LOCAL_HOSTS = {"127.0.0.1", "localhost", "::1"}


def _require_local() -> None:
    url = os.environ.get("DATABASE_URL", "")
    host = urlparse(url.replace("+asyncpg", "").replace("+psycopg", "")).hostname
    if host not in LOCAL_HOSTS:
        raise SystemExit(f"rehearsal worker: DATABASE_URL must be local, not {host!r}")
    if os.environ.get("LLM_PROVIDER") != "stub":
        raise SystemExit("rehearsal worker: LLM_PROVIDER must be stub (no model calls)")


def _replay_profiles() -> list[vc.Profile]:
    names = os.environ.get("QC_REHEARSAL_REPLAY_PROFILES", "CLEAN,DRIFTED").split(",")
    return [getattr(vc, n.strip()) for n in names if n.strip()]


def _install_clock() -> None:
    clock = vc.VirtualClock(vc.CLEAN, seed=SEED)
    profiles = _replay_profiles()
    replays = 0
    vc_time: Any = clock
    import querycure.benchmark.executor as executor

    executor.time = vc_time  # type: ignore[attr-defined]
    real_options = handlers.engine_options
    handlers.engine_options = lambda settings: clock.options(  # type: ignore[assignment]
        **{
            k: getattr(real_options(settings), k)
            for k in ("lease_timeout_seconds", "sandbox_image_digest", "container_runtime")
        }
    )
    real_build = handlers.build_handlers

    def build(services: Any) -> Any:
        built = real_build(services)

        def timed(kind: str, handle: Any) -> Any:
            async def run(job: Job) -> None:
                nonlocal replays
                if kind == "experiment_replay":
                    profile = profiles[min(replays, len(profiles) - 1)]
                    replays += 1
                    clock.use(profile, seed=SEED + replays)
                else:
                    clock.use(vc.CLEAN, seed=SEED)
                await handle(job)

            return run

        return {kind: timed(kind, handle) for kind, handle in built.items()}

    worker_main.build_handlers = build  # type: ignore[attr-defined]


def main() -> None:
    _require_local()
    activation.activate(setattr)
    _install_clock()
    asyncio.run(worker_main.main())


if __name__ == "__main__":
    main()
