"""Benchmark repeatability study (BENCHMARK_ENGINE §12): the same deterministic experiment,
measured in N independent sessions, summarized across sessions.

    uv run python -m querycure.benchmark.repeatability --sessions 8 --label before \
        --sandbox-url postgresql://qc_sandbox_admin:...@127.0.0.1:55432/sandbox_admin

Each session is a full `run_experiment` with its own experiment ID, seed and clones on the
`orders_ecommerce` workload: an arm with a real effect (the composite index) and a null arm
(an index the query never uses). Between-session spread of the medians, the per-session
robust CV and CI width, verdict agreement and runtime are what "repeatable" means here.

Local sandboxes only: the study creates and drops databases, so the URL host must be a
loopback address or the compose service name `sandbox-db` (the in-network worker container).
Nothing is persisted to the metadata DB, and no LLM is involved.
"""

import argparse
import json
import secrets
import statistics
import sys
import threading
import time
import uuid
from collections import Counter
from collections.abc import Sequence
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

from pydantic import SecretStr

from querycure.benchmark.engine import (
    ApprovedExperiment,
    BlockRecord,
    EngineOptions,
    run_experiment,
    run_replicated,
    sql_digest,
)
from querycure.domain.benchmark import (
    CandidateArm,
    EnvironmentFingerprint,
    ExperimentConfig,
    ParamSetSpec,
)
from querycure.sandbox.provisioner import SandboxProvisioner
from querycure.workloads.registry import WORKLOADS

LOCAL_SANDBOX_HOSTS = frozenset({"127.0.0.1", "localhost", "::1", "sandbox-db"})
WORKLOAD = "orders_ecommerce@v1:sf=0.1:seed=42"
EFFECT = CandidateArm(
    arm="oc_000000effec7", candidate_id=None, kind="create_index",
    ddl=["CREATE INDEX ON orders (customer_id, created_at)"], query=None,
)  # fmt: skip
NULL = CandidateArm(
    arm="oc_0000000a0011", candidate_id=None, kind="create_index",
    ddl=["CREATE INDEX ON orders (total)"], query=None,
)  # fmt: skip


@dataclass
class _Hooks:
    records: list[BlockRecord] = field(default_factory=list)
    env: EnvironmentFingerprint | None = None
    cancel: threading.Event = field(default_factory=threading.Event)

    def existing(self) -> list[BlockRecord]:
        return list(self.records)

    def persist(self, record: BlockRecord) -> None:
        self.records.append(record)

    def progress(self, state: str, **details: Any) -> None:
        pass

    def environment(self, env: EnvironmentFingerprint, env_digest: str) -> None:
        self.env = env

    def cancelled(self) -> bool:
        return self.cancel.is_set()


@dataclass(frozen=True)
class ArmSession:
    arm: str
    param_set: str
    baseline_median_ms: float
    candidate_median_ms: float
    baseline_robust_cv: float | None
    candidate_robust_cv: float | None
    speedup: float
    ci_low: float
    ci_high: float
    verdict: str
    reason: str | None


@dataclass(frozen=True)
class Session:
    index: int
    seed: int
    runtime_s: float
    arms: list[ArmSession]
    floor_median_ms: float | None = None
    floor_share: float | None = None
    # Replicated mode: the product's final status per arm after noise-screen replicates
    # (verified_with_noise_warning or inconclusive), else the approved experiment's verdict.
    final: dict[str, str] = field(default_factory=dict)
    experiments: int = 1


def check_local(url: str) -> None:
    host = urlsplit(url).hostname
    if host not in LOCAL_SANDBOX_HOSTS:
        raise SystemExit(
            f"refusing sandbox host {host!r}: the study creates and drops databases, so only "
            f"local sandboxes are allowed ({', '.join(sorted(LOCAL_SANDBOX_HOSTS))})"
        )


def study_config(seed: int, **overrides: Any) -> ExperimentConfig:
    query = WORKLOADS["orders_ecommerce"].example_queries[0]
    body: dict[str, Any] = {
        "experiment_id": uuid.uuid4(),
        "workload_id": WORKLOAD,
        "baseline_query": query.sql,
        "candidates": [EFFECT, NULL],
        "param_sets": [ParamSetSpec(name=p.name, values=list(p.values)) for p in query.param_sets],
        "seed": seed,
    }
    body.update(overrides)
    return ExperimentConfig.model_validate(body)


def run_session(
    provisioner: SandboxProvisioner,
    index: int,
    seed: int,
    options: EngineOptions,
    *,
    replicated: bool = False,
    **cfg: Any,
) -> tuple[Session, EnvironmentFingerprint | None]:
    config = study_config(seed, **cfg)
    approved = ApprovedExperiment(
        approval_request_id=f"repeatability-{index}",
        approved_sql={a.arm: sql_digest(a) for a in config.candidates},
    )
    hooks = _Hooks()
    started = time.monotonic()
    final: dict[str, str] = {}
    experiments = 1
    if replicated:
        run = run_replicated(
            config, approved, provisioner=provisioner, hooks_for=lambda _c, _i: hooks
            if _i == 0 else _Hooks(), options=options,
        )  # fmt: skip
        result = run.replicates[0].result
        experiments = len(run.replicates)
        final = {v.arm: v.verdict for v in result.verdicts}
        if run.replication is not None:
            final.update({v.arm: v.verdict for v in run.replication.verdicts})
    else:
        result = run_experiment(
            config, approved, provisioner=provisioner, hooks=hooks, options=options
        )
        final = {v.arm: v.verdict for v in result.verdicts}
    runtime = time.monotonic() - started
    verdicts = {v.arm: v for v in result.verdicts}
    arms = [
        ArmSession(
            arm=s.arm,
            param_set=s.param_set,
            baseline_median_ms=s.baseline.median_ns / 1e6,
            candidate_median_ms=s.candidate.median_ns / 1e6,
            baseline_robust_cv=s.baseline.robust_cv,
            candidate_robust_cv=s.candidate.robust_cv,
            speedup=s.speedup,
            ci_low=s.ci_low,
            ci_high=s.ci_high,
            verdict=verdicts[s.arm].verdict,
            reason=verdicts[s.arm].reasons[0].code if verdicts[s.arm].reasons else None,
        )
        for s in result.stats
    ]
    floor = result.transport_floor
    return Session(
        index=index,
        seed=seed,
        runtime_s=runtime,
        arms=arms,
        floor_median_ms=floor.median_ns / 1e6 if floor else None,
        floor_share=floor.share_of_fastest_arm if floor else None,
        final=final,
        experiments=experiments,
    ), hooks.env


def _spread(values: Sequence[float]) -> dict[str, float | None]:
    if not values:
        return {"n": 0, "median": None, "min": None, "max": None, "between_session_robust_cv": None}
    median = statistics.median(values)
    rcv: float | None = None
    if len(values) >= 2 and median > 0:
        q1, _, q3 = statistics.quantiles(values, n=4, method="inclusive")
        rcv = (q3 - q1) / (1.349 * median)
    return {
        "n": len(values),
        "median": median,
        "min": min(values),
        "max": max(values),
        "between_session_robust_cv": rcv,
    }


def summarize(sessions: Sequence[Session]) -> dict[str, Any]:
    """Across-session distributions per (arm, param set)."""
    keys = sorted({(a.arm, a.param_set) for s in sessions for a in s.arms})
    out: dict[str, Any] = {}
    for arm, ps in keys:
        rows = [a for s in sessions for a in s.arms if (a.arm, a.param_set) == (arm, ps)]
        widths = [(a.ci_high - a.ci_low) / a.speedup for a in rows if a.speedup > 0]
        out[f"{arm}/{ps}"] = {
            "baseline_median_ms": _spread([a.baseline_median_ms for a in rows]),
            "candidate_median_ms": _spread([a.candidate_median_ms for a in rows]),
            "speedup": _spread([a.speedup for a in rows]),
            "within_session_robust_cv": _spread(
                [max(a.baseline_robust_cv or 0.0, a.candidate_robust_cv or 0.0) for a in rows]
            ),
            "relative_ci_width": _spread(widths),
            "verdicts": dict(Counter(f"{a.verdict}:{a.reason}" for a in rows)),
        }
    finals = {
        arm: dict(Counter(s.final.get(arm, "missing") for s in sessions))
        for arm in sorted({a for s in sessions for a in s.final})
    }
    return {
        "sessions": len(sessions),
        "runtime_s": _spread([s.runtime_s for s in sessions]),
        "experiments_per_session": _spread([float(s.experiments) for s in sessions]),
        "transport_floor_ms": _spread([s.floor_median_ms for s in sessions if s.floor_median_ms]),
        "floor_share_of_fastest_arm": _spread(
            [s.floor_share for s in sessions if s.floor_share is not None]
        ),
        "final_status": finals,
        "arms": out,
    }


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m querycure.benchmark.repeatability")
    parser.add_argument("--sandbox-url", required=True)
    parser.add_argument("--sessions", type=int, default=8)
    parser.add_argument("--label", default="study")
    parser.add_argument("--path", default="docker-relay", help="recorded measurement path")
    parser.add_argument("--out", type=Path, default=None, help="write the JSON report here")
    parser.add_argument("--seed", type=int, default=20261018)
    parser.add_argument(
        "--replicated", action="store_true",
        help="run the product flow: noise-screen replicates (up to 3 experiments per session)",
    )  # fmt: skip
    args = parser.parse_args(argv)
    check_local(args.sandbox_url)
    provisioner = SandboxProvisioner(
        admin_url=SecretStr(args.sandbox_url), bench_password=SecretStr(secrets.token_hex(16))
    )
    provisioner.bootstrap()
    options = EngineOptions(container_runtime=args.path, time_budget_seconds=600)
    sessions: list[Session] = []
    env: EnvironmentFingerprint | None = None
    for i in range(args.sessions):
        session, env = run_session(
            provisioner, i, args.seed + i, options, replicated=args.replicated
        )
        sessions.append(session)
        effect = next(a for a in session.arms if a.arm == EFFECT.arm)
        print(
            f"session {i}: {session.runtime_s:.1f}s {effect.param_set} "
            f"{effect.baseline_median_ms:.3f}->{effect.candidate_median_ms:.3f} ms "
            f"{effect.speedup:.2f}x [{effect.ci_low:.2f},{effect.ci_high:.2f}] {effect.verdict} "
            f"final={session.final.get(EFFECT.arm)} floor={session.floor_median_ms}",
            file=sys.stderr,
        )
    report = {
        "label": args.label,
        "workload": WORKLOAD,
        "path": args.path,
        "environment": env.model_dump() if env else None,
        "summary": summarize(sessions),
        "raw": [asdict(s) for s in sessions],
    }
    text = json.dumps(report, indent=2, default=str)
    if args.out:
        args.out.write_text(text + "\n")
    print(text)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
