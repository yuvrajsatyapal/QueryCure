"""Same-machine experiment-replay variance (Phase 4, T4.7 acceptance and D9).

For each pair: run the orders_ecommerce composite-index experiment (the committed fixture's
config with a fresh id and the pair's seed), then replay it exactly as experiment replay does:
same config and seed, new experiment id, scored by the source rules (bench@2). The two results
are compared with `replay.comparison.compare_experiments` (margin 1.25, 2,000 resamples).

    cd backend && uv run python ../docs/engineering/analysis/replay_variance/measure.py \
        --sf 0.1 --pairs 4 --out ../docs/engineering/analysis/replay_variance/data

Needs the compose sandbox (relay on 127.0.0.1:55432). Real measurements only; no LLM.
"""

import argparse
import os
import secrets
import sys
import time
import uuid
from pathlib import Path

from pydantic import SecretStr

# QC_BACKEND lets the script run inside the worker container (backend mounted at /app).
BACKEND = (
    Path(os.environ["QC_BACKEND"])
    if "QC_BACKEND" in os.environ
    else Path(__file__).resolve().parents[4] / "backend"
)
sys.path.insert(0, str(BACKEND))

from querycure.benchmark.engine import EngineOptions, run_experiment  # noqa: E402
from querycure.benchmark.fixtures import load_prerecorded  # noqa: E402
from querycure.replay.canonical import canonical_json, to_canonical  # noqa: E402
from querycure.replay.comparison import compare_experiments  # noqa: E402
from querycure.sandbox.provisioner import SandboxProvisioner  # noqa: E402
from tests.integration.engine_helpers import MemoryHooks, approve_all  # noqa: E402

SANDBOX_URL = os.environ.get(
    "QC_TEST_SANDBOX_URL",
    "postgresql://qc_sandbox_admin:qc_local_dev_only@127.0.0.1:55432/sandbox_admin",
)
FIXTURE = BACKEND / "evals" / "fixtures" / "experiments" / "orders_ecommerce_sf1_composite_index.json"


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--sf", type=float, default=0.1)
    ap.add_argument("--pairs", type=int, default=4)
    ap.add_argument("--first-seed", type=int, default=1000)
    ap.add_argument("--runtime", default="docker-relay")
    ap.add_argument("--out", type=Path, required=True)
    args = ap.parse_args()
    args.out.mkdir(parents=True, exist_ok=True)

    base = load_prerecorded(FIXTURE).config
    workload = base.workload_id.replace("sf=1:", f"sf={args.sf:g}:")
    prov = SandboxProvisioner(admin_url=SecretStr(SANDBOX_URL),
                              bench_password=SecretStr(secrets.token_hex(16)))
    prov.bootstrap()
    options = EngineOptions(container_runtime=args.runtime)
    for i in range(args.pairs):
        seed = args.first_seed + i
        cfg = base.model_copy(update={"experiment_id": uuid.uuid4(), "seed": seed,
                                      "workload_id": workload})
        results = []
        for label, config in (("original", cfg),
                              ("replay", cfg.model_copy(update={"experiment_id": uuid.uuid4()}))):
            hooks = MemoryHooks()
            started = time.monotonic()
            result = run_experiment(config, approve_all(config), provisioner=prov, hooks=hooks,
                                    options=options)
            results.append((config, result, hooks.env, time.monotonic() - started))
            print(f"pair {i} {label}: {[v.verdict for v in result.verdicts]} "
                  f"{[(s.param_set, round(s.speedup, 2)) for s in result.stats]} "
                  f"{results[-1][3]:.0f}s", flush=True)
        (oc, orr, oe, _), (rc, rr, re_, _) = results
        cmp = compare_experiments(
            original_id=str(oc.experiment_id), replay_id=str(rc.experiment_id), config=oc,
            original=orr, replay=rr, original_env=oe, replay_env=re_,
            original_env_digest=None, replay_env_digest=None, replay_engine="bench@2",
        )
        print(f"pair {i}: {cmp['status']} {cmp['failure_code']} mode={cmp['comparison_mode']} "
              + "; ".join(f"{p['param_set']} {p['status']} D={p['drift'] or 0:.3f} "
                          f"[{p['drift_ci_low'] or 0:.3f}, {p['drift_ci_high'] or 0:.3f}]"
                          for p in cmp["pairs"]), flush=True)
        record = {"sf": args.sf, "seed": seed, "runtime": args.runtime,
                  "original": to_canonical(orr), "replay": to_canonical(rr),
                  "comparison": cmp}
        (args.out / f"sf{args.sf:g}_seed{seed}.json").write_bytes(
            canonical_json(to_canonical(record)))


if __name__ == "__main__":
    main()
