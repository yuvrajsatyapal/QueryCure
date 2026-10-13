"""Re-score the real-PostgreSQL experiments in real.jsonl with bench@2 and each D13 safeguard,
and estimate the disturbance structure (between-block spread, order/position effect, drift)."""

import collections
import json
import math
import statistics
import sys
import uuid

from querycure.benchmark.correctness import CorrectnessOutcome
from querycure.benchmark.rules import CandidateEvidence, assess, compute_stats
from querycure.domain.benchmark import (
    ArmFingerprint, ArmMeasurement, BuildResult, CandidateArm, ExperimentConfig, ParamSetSpec,
)

from rulesets import block_log_ratios, make_rules, pooled_blocks

FP = ArmFingerprint(rows=20, multiset="m", ordered="o", truncated=False)
RULES = make_rules()


def wilson(k: int, n: int) -> str:
    if n == 0:
        return "n/a"
    z = 1.96
    p = k / n
    d = 1 + z * z / n
    c = (p + z * z / (2 * n)) / d
    h = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / d
    return f"{100*p:5.1f}% [{100*max(0,c-h):.1f}, {100*min(1,c+h):.1f}]"


def evidence(r):
    arm = r["cand"]
    pss = r["param_sets"]
    cfg = ExperimentConfig.model_validate({
        "experiment_id": uuid.uuid4(), "workload_id": f"{r['workload']}@v1:sf=0.1:seed=42",
        "baseline_query": "SELECT 1",
        "candidates": [CandidateArm(arm=arm, candidate_id=None, kind="create_index", ddl=["CREATE INDEX ON t (a)"], query=None)],
        "param_sets": [ParamSetSpec(name=p, values=[1]) for p in pss], "seed": r["seed"], "block_size": r["block_size"],
    })
    by = collections.defaultdict(dict)
    lat = collections.defaultdict(list)
    for b in r["blocks"]:
        by[b["ps"]][(b["block"], b["arm"])] = b["lat"]
    for (ps, a), _ in []:
        pass
    blocks = {}
    for ps in pss:
        nb = sorted({k[0] for k in by[ps]})
        blocks[ps] = [(by[ps].get((i, "baseline"), []), by[ps].get((i, arm), [])) for i in nb]
        for bb, cc in blocks[ps]:
            lat[("baseline", ps)] += bb
            lat[(arm, ps)] += cc
    ev = CandidateEvidence(
        arm=cfg.candidates[0], build=BuildResult(arm=arm, ok=True),
        baseline={p: ArmMeasurement(arm="baseline", param_set=p, latencies_ns=lat[("baseline", p)], failures=[], fingerprint=FP, consistent=True) for p in pss},
        candidate={p: ArmMeasurement(arm=arm, param_set=p, latencies_ns=lat[(arm, p)], failures=[], fingerprint=FP, consistent=True) for p in pss},
        correctness={p: CorrectnessOutcome("match") for p in pss}, blocks=blocks,
    )
    return cfg, ev


def main() -> None:
    recs = [json.loads(l) for l in open(sys.argv[1])]
    groups = collections.defaultdict(list)
    for r in recs:
        groups[(r["scenario"], r["injected_delay_ms"], r["block_size"], r["load"])].append(r)
    for key in sorted(groups, key=str):
        rs = groups[key]
        tally = collections.Counter()
        keep = collections.Counter()
        nver = 0
        sds, pos, speed = [], [], []
        mism = 0
        for r in rs:
            cfg, ev = evidence(r)
            stats = compute_stats(ev, cfg)
            v, screen = assess(ev, cfg, stats, query_has_params=True, engine_version="bench@2")
            if [v.verdict, v.gate, v.reasons[0].code if v.reasons else None] != r["verdict"]:
                mism += 1
            tally[(v.verdict, v.gate)] += 1
            if screen and screen.eligible:
                tally["eligible"] += 1
            prim = ev.blocks[cfg.param_sets[0].name]
            speed.append(stats[cfg.param_sets[0].name].speedup)
            lr = block_log_ratios(prim if r["block_size"] == 5 else pooled_blocks(prim, 5 // r["block_size"]))
            if len(lr) > 2:
                sds.append(statistics.stdev(lr))
            # order effect: log(first segment median / second segment median), sign-adjusted per arm
            if r["block_size"] == 5:
                orders = {(ps, b): o for ps, b, o in r["order"]}
                for (i, (bb, cc)) in enumerate(prim):
                    o = orders[(cfg.param_sets[0].name, i)]
                    first_base = o[0] == "baseline"
                    lrr = math.log(statistics.median(bb) / statistics.median(cc))
                    pos.append(lrr if first_base else -lrr)  # >0: the arm running first is slower
            if v.verdict == "verified":
                nver += 1
                for name, rule in RULES.items():
                    keep[name] += rule(prim, r["seed"])
                    if r["block_size"] < 5:
                        keep[name + "@pool5"] += rule(pooled_blocks(prim, 5 // r["block_size"]), r["seed"])
        n = len(rs)
        print(f"\n== {key} n={n} (verdict mismatches vs stored: {mism})")
        print("  verdicts:", dict(tally))
        print(f"  median speedup {statistics.median(speed):.3f}; between-block log-ratio sd (5-sample blocks) "
              f"median {statistics.median(sds):.3f} p90 {sorted(sds)[int(0.9*len(sds))]:.3f}")
        if pos:
            m = statistics.fmean(pos)
            se = statistics.stdev(pos) / math.sqrt(len(pos))
            print(f"  order effect (first segment slower, log): {m:+.4f} ± {1.96*se:.4f}")
        print(f"  bench@2 verified: {wilson(nver, n)}")
        for name in sorted(keep):
            print(f"    {name:24s} keeps verified: {wilson(keep[name], n)}")


if __name__ == "__main__":
    main()
