"""D13 deterministic simulation of the bench@2 measurement schedule and verdict rules.

Each simulated experiment follows the engine exactly: warm-up runs per arm and param set, then
`build_schedule` blocks (or a counterbalanced variant), each arm running `runs` consecutive
samples. A global sample clock `t` drives time-dependent disturbances. The real
`compute_stats` / `assess` produce the bench@2 verdict; safeguards from rulesets.py are applied
on top of a clean `verified`. Every random draw is seeded from (cell, replicate index).

Usage: uv run python sim.py OUT.json [N] [--quick] [--procs=8]
"""

import json
import math
import multiprocessing as mp
import random
import sys
import uuid
from dataclasses import dataclass

from querycure.benchmark.correctness import CorrectnessOutcome
from querycure.benchmark.rules import CandidateEvidence, assess, compute_stats
from querycure.benchmark.schedule import build_schedule, derive_seed
from querycure.domain.benchmark import (
    ArmFingerprint,
    ArmMeasurement,
    BuildResult,
    CandidateArm,
    ExperimentConfig,
    ParamSetSpec,
)

from rulesets import make_rules, pooled_blocks

ARM = "oc_aaaaaaaaaaaa"
FP = ArmFingerprint(rows=20, multiset="m", ordered="o", truncated=False)
PS = ["hot", "cold"]
BASE_NS = {"hot": 3_400_000, "cold": 3_100_000}  # calibrated to the sf=0.1 seq scan
RULES = make_rules()


@dataclass(frozen=True)
class Noise:
    name: str
    sigma: float = 0.07          # iid lognormal sd (robust CV ~ 0.07)
    spike_p: float = 0.03        # heavy tail: occasional 1.3-2x sample
    drift_lin: float = 0.0       # log drift from start to end of the run
    step: float = 0.0            # log step at a uniform random time
    ar_sd: float = 0.0           # stationary sd of AR(1) correlated jitter
    ar_phi: float = 0.95
    burst_rate: float = 0.0      # bursts per sample
    burst_len: float = 8.0
    burst_mag: tuple[float, float] = (0.3, 0.9)
    asym_p: float = 0.0          # P(baseline segment of a block is delayed)
    asym_mag: float = 0.0        # log delay of a disturbed baseline segment
    asym_persist: float = 0.0    # log delay on every baseline sample (undetectable in-run)
    position: float = 0.0        # log penalty on the first segment of every block


NOISES = [
    Noise("iid"),
    Noise("drift_linear", drift_lin=0.30),
    Noise("drift_step", step=0.25),
    Noise("ar1_jitter", ar_sd=0.10),
    Noise("bursts", burst_rate=1 / 60),
    Noise("position", position=0.10),
    Noise("asym_p0.5_x1.3", asym_p=0.5, asym_mag=math.log(1.3)),
    Noise("asym_p0.83_x2", asym_p=5 / 6, asym_mag=math.log(2.0)),
    Noise("asym_persist_x1.15", asym_persist=math.log(1.15)),
]
EFFECTS = [1.0, 1.05, 1.10, 1.20, 1.50, 3.0]
# (label, block_size, counterbalanced)
SCHEDULES = [("bs5", 5, False), ("bs5_cb", 5, True), ("bs2", 2, False), ("bs1", 1, False), ("bs1_cb", 1, True)]


def _config(seed: int, block_size: int) -> ExperimentConfig:
    return ExperimentConfig.model_validate({
        "experiment_id": uuid.UUID(int=seed % 2**128),
        "workload_id": "orders_ecommerce@v1:sf=0.1:seed=42",
        "baseline_query": "SELECT 1",
        "candidates": [CandidateArm(arm=ARM, candidate_id=None, kind="create_index",
                                    ddl=["CREATE INDEX ON t (a)"], query=None)],
        "param_sets": [ParamSetSpec(name=p, values=[i]) for i, p in enumerate(PS)],
        "seed": seed % 2**53, "block_size": block_size,
    })


def _order(cfg: ExperimentConfig, counterbalanced: bool) -> list[tuple[str, int, tuple[str, ...], int]]:
    sched = build_schedule(["baseline", ARM], PS, measured_runs=cfg.measured_runs,
                           block_size=cfg.block_size, seed=cfg.seed)
    if not counterbalanced:
        return [(s.param_set, s.block, s.arm_order, s.runs) for s in sched]
    first = {s.param_set: s.arm_order for s in sched if s.block == 0}
    return [(s.param_set, s.block, first[s.param_set] if s.block % 2 == 0 else first[s.param_set][::-1], s.runs)
            for s in sched]


def simulate(noise: Noise, effect: float, block_size: int, cb: bool, seed: int):
    cfg = _config(seed, block_size)
    rng = random.Random(derive_seed(seed, "noise"))
    order = _order(cfg, cb)
    warm = 2 * len(PS) * cfg.warmup_runs
    total = warm + sum(2 * r for *_, r in order)
    step_at = rng.uniform(0, total)
    state = {"ar": rng.gauss(0, noise.ar_sd), "burst_left": 0, "burst": 0.0, "t": 0}

    def draw(arm: str, ps: str, extra: float) -> int:
        t = state["t"]
        state["t"] += 1
        x = rng.gauss(0, noise.sigma)
        if rng.random() < noise.spike_p:
            x += math.log(rng.uniform(1.3, 2.0))
        x += noise.drift_lin * t / total + (noise.step if t >= step_at else 0.0)
        if noise.ar_sd:
            innov = noise.ar_sd * math.sqrt(1 - noise.ar_phi ** 2)
            state["ar"] = noise.ar_phi * state["ar"] + rng.gauss(0, innov)
            x += state["ar"]
        if noise.burst_rate:
            if state["burst_left"] <= 0 and rng.random() < noise.burst_rate:
                state["burst_left"] = 1 + int(rng.expovariate(1 / noise.burst_len))
                state["burst"] = rng.uniform(*noise.burst_mag)
            if state["burst_left"] > 0:
                x += state["burst"]
                state["burst_left"] -= 1
        if arm == "baseline":
            x += noise.asym_persist
        mu = BASE_NS[ps] / (effect if arm == ARM else 1.0)
        return max(1, int(mu * math.exp(x + extra)))

    for a in ("baseline", ARM):
        for ps in PS:
            for _ in range(cfg.warmup_runs):
                draw(a, ps, 0.0)
    lat: dict[tuple[str, str], list[int]] = {(a, p): [] for a in ("baseline", ARM) for p in PS}
    blocks: dict[str, dict[int, dict[str, list[int]]]] = {p: {} for p in PS}
    for ps, b, arm_order, runs in order:
        hit = rng.random() < noise.asym_p
        for pos, a in enumerate(arm_order):
            extra = (noise.asym_mag if (hit and a == "baseline") else 0.0) + (noise.position if pos == 0 else 0.0)
            seg = [draw(a, ps, extra) for _ in range(runs)]
            lat[(a, ps)].extend(seg)
            blocks[ps].setdefault(b, {})[a] = seg
    ev = CandidateEvidence(
        arm=cfg.candidates[0], build=BuildResult(arm=ARM, ok=True),
        baseline={p: ArmMeasurement(arm="baseline", param_set=p, latencies_ns=lat[("baseline", p)],
                                    failures=[], fingerprint=FP, consistent=True) for p in PS},
        candidate={p: ArmMeasurement(arm=ARM, param_set=p, latencies_ns=lat[(ARM, p)],
                                     failures=[], fingerprint=FP, consistent=True) for p in PS},
        correctness={p: CorrectnessOutcome("match") for p in PS},
        blocks={p: [(blocks[p][b]["baseline"], blocks[p][b][ARM]) for b in sorted(blocks[p])] for p in PS},
    )
    stats = compute_stats(ev, cfg)
    v, screen = assess(ev, cfg, stats, query_has_params=True, engine_version="bench@2")
    return v, screen, stats, ev


def outcome(noise: Noise, effect: float, block_size: int, cb: bool, seed: int) -> dict:
    v, screen, stats, ev = simulate(noise, effect, block_size, cb, seed)
    prim = ev.blocks["hot"]
    out = {"v": v.verdict, "gate": v.gate, "eligible": bool(screen and screen.eligible)}
    if v.verdict == "verified":
        keep = {}
        for name, rule in RULES.items():
            keep[name] = bool(rule(prim, seed))
            # The same rule on blocks re-pooled to 5 samples per arm (only differs for bs < 5).
            if block_size < 5:
                keep[name + "@pool5"] = bool(rule(pooled_blocks(prim, 5 // block_size), seed))
        out["keep"] = keep
    if out["eligible"]:
        # ADR-0019 §3 replication with two more independent experiments of the same noise model.
        cis = [(stats["hot"].ci_low, stats["hot"].ci_high)]
        ok = True
        for k in (1, 2):
            s2 = derive_seed(seed, "replicate", k)
            v2, sc2, st2, _ = simulate(noise, effect, block_size, cb, s2)
            if not (v2.verdict == "verified" or (v2.gate == 4 and sc2 and sc2.eligible)):
                ok = False
                break
            if any(s.ci_low < 0.95 for s in st2.values()):
                ok = False
                break
            cis.append((st2["hot"].ci_low, st2["hot"].ci_high))
        out["noise_warning"] = ok and max(l for l, _ in cis) <= min(h for _, h in cis)
    return out


def run_cell(args):
    noise, effect, label, bs, cb, n, base_seed = args
    rows = [outcome(noise, effect, bs, cb, derive_seed(base_seed, noise.name, effect, label, i)) for i in range(n)]
    return {"noise": noise.name, "effect": effect, "schedule": label, "n": n, "rows": rows}


def main() -> None:
    out = sys.argv[1]
    n = int(sys.argv[2]) if len(sys.argv) > 2 and sys.argv[2].isdigit() else 400
    quick = "--quick" in sys.argv
    cells = [(nz, e, lab, bs, cb, n, 20261013) for nz in NOISES for e in EFFECTS for lab, bs, cb in SCHEDULES]
    if quick:
        cells = cells[:: max(1, len(cells) // 6)]
    procs = int(next((a.split("=")[1] for a in sys.argv if a.startswith("--procs=")), "8"))
    with mp.Pool(procs) as pool:
        res = pool.map(run_cell, cells, chunksize=1)
    with open(out, "w") as f:
        json.dump(res, f)
    print("cells", len(res))


if __name__ == "__main__":
    main()
