"""D13 data collection: run real bench@2 experiments against the sandbox server and save the
raw per-block samples, so alternative block rules can be re-scored offline.

Usage: uv run python collect.py OUT.jsonl SCENARIO SEEDS... [--block-size N] [--load]
Scenarios use the engine's own test seams (arm_noise) only for the injected, labelled effects.
"""

import json
import os
import subprocess
import sys
import time
import uuid

from pydantic import SecretStr

from querycure.benchmark.engine import EngineOptions, run_experiment
from querycure.benchmark.schedule import build_schedule
from querycure.sandbox.provisioner import SandboxProvisioner
from querycure.workloads.registry import WORKLOADS
from tests.integration.engine_helpers import MemoryHooks, approve_all, arm, config

URL = "postgresql://qc_sandbox_admin:qc_local_dev_only@127.0.0.1:55432/sandbox_admin"
COMPOSITE = arm("oc_0000000000c1", "create_index", ["CREATE INDEX ON orders (customer_id, created_at)"])
NEUTRAL = arm("oc_0000000000c4", "create_index", ["CREATE INDEX ON orders (total)"])
USELESS = arm("oc_0000000000c2", "create_index", ["CREATE INDEX ON app_settings (key, value)"])


def injected_baseline_delay(ms: float):
    """A genuine, known effect: the baseline arm is slower by a fixed `ms` on every sample."""
    def hook(a: str, ps: str, block: int) -> None:
        if a == "baseline":
            t = time.perf_counter() + ms / 1000
            while time.perf_counter() < t:
                pass
    return hook


SCEN = {
    # name: (workload, candidate, injected baseline delay ms or None)
    "neutral_scan": ("orders_ecommerce", NEUTRAL, None),
    "neutral_pk": ("no_benefit", USELESS, None),
    "genuine_large": ("orders_ecommerce", COMPOSITE, None),
    "genuine_moderate": ("orders_ecommerce", NEUTRAL, "moderate"),
}


def main() -> None:
    out, scen, *rest = sys.argv[1:]
    block_size = 5
    load = False
    seeds = []
    it = iter(rest)
    for a in it:
        if a == "--block-size":
            block_size = int(next(it))
        elif a == "--load":
            load = True
        else:
            seeds.append(int(a))
    workload, cand, delay = SCEN[scen]
    prov = SandboxProvisioner(admin_url=SecretStr(URL), bench_password=SecretStr(os.urandom(8).hex()))
    prov.bootstrap()
    q = WORKLOADS[workload].example_queries[0]
    loader = None
    if load:
        # Intermittent competing load on the same server (separate session, same template DB is
        # not touched): a seq-scan loop that runs ~1.5 s on, ~2.5 s off.
        loader = subprocess.Popen([sys.executable, os.path.join(os.path.dirname(__file__), "load.py")])
    try:
        for seed in seeds:
            cfg = config(f"{workload}@v1:sf=0.1:seed=42", q.sql, [cand],
                         [(p.name, list(p.values)) for p in q.param_sets],
                         seed=seed, block_size=block_size, experiment_id=uuid.uuid4())
            opts = EngineOptions(container_runtime="docker-relay")
            hook_delay = None
            if delay == "moderate":
                hook_delay = float(os.environ.get("D13_DELAY_MS", "1.0"))
                opts = EngineOptions(container_runtime="docker-relay", arm_noise=injected_baseline_delay(hook_delay))
            hooks = MemoryHooks()
            t0 = time.monotonic()
            res = run_experiment(cfg, approve_all(cfg), provisioner=prov, hooks=hooks, options=opts)
            dt = time.monotonic() - t0
            sched = build_schedule(["baseline", cand.arm], [p.name for p in cfg.param_sets],
                                   measured_runs=cfg.measured_runs, block_size=cfg.block_size, seed=cfg.seed)
            blocks = [
                {"arm": r.arm, "ps": r.param_set, "block": r.block, "lat": r.latencies_ns, "err": r.sample_errors}
                for r in hooks.records if r.phase == "measure"
            ]
            v = res.verdicts[0]
            rec = {
                "scenario": scen, "seed": seed, "block_size": block_size, "load": load,
                "injected_delay_ms": hook_delay, "workload": workload, "cand": cand.arm,
                "param_sets": [p.name for p in cfg.param_sets], "seconds": round(dt, 1),
                "order": [[s.param_set, s.block, list(s.arm_order)] for s in sched],
                "blocks": blocks,
                "verdict": [v.verdict, v.gate, v.reasons[0].code if v.reasons else None],
                "stats": [s.model_dump(mode="json") for s in res.stats],
                "screen": [s.model_dump(mode="json") for s in (res.noise_screens or [])],
            }
            with open(out, "a") as f:
                f.write(json.dumps(rec) + "\n")
            p = res.stats[0]
            print(scen, seed, block_size, load, rec["verdict"], f"{p.speedup:.3f} [{p.ci_low:.3f},{p.ci_high:.3f}]",
                  f"cv b={p.baseline.robust_cv:.2f} c={p.candidate.robust_cv:.2f}", f"{dt:.0f}s", flush=True)
    finally:
        if loader:
            loader.terminate()


if __name__ == "__main__":
    main()
