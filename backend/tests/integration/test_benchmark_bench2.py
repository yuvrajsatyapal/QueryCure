"""bench@2 against the real sandbox server (ADR-0019): noisy fast queries, meaningful
regressions, no-benefit cases and misleadingly narrow confidence intervals.

Disturbances are injected through the engine's test seams (`noise`, `arm_noise`) inside the
timed region, so the statistics see them exactly like environment noise. Assertions are on
verdicts, reason codes and screens, never on latencies.
"""

import random
import time
from collections.abc import Callable

import pytest

from querycure.benchmark.engine import (
    EngineOptions,
    ReplicatedRun,
    run_experiment,
    run_replicated,
    score,
)
from querycure.benchmark.replication import REPLICATES
from querycure.domain.benchmark import CandidateArm, ExperimentConfig
from querycure.sandbox.provisioner import SandboxProvisioner
from querycure.workloads.registry import WORKLOADS
from tests.integration.engine_helpers import MemoryHooks, approve_all, arm, config
from tests.integration.sandbox_fixtures import clone_names

pytestmark = pytest.mark.integration

SF = "sf=0.1:seed=42"
COMPOSITE = arm(
    "oc_0000000000c1", "create_index", ["CREATE INDEX ON orders (customer_id, created_at)"]
)
USELESS = arm("oc_0000000000c2", "create_index", ["CREATE INDEX ON app_settings (key, value)"])
# Unused by the query: the plan stays a sequential scan of orders (milliseconds, low jitter).
NEUTRAL = arm("oc_0000000000c4", "create_index", ["CREATE INDEX ON orders (total)"])
REGRESSING = arm("oc_0000000000c3", "create_index", ["CREATE INDEX ON tickets (opened_at, id)"])


def _cfg(workload: str, candidate: CandidateArm, **kw: object) -> ExperimentConfig:
    q = WORKLOADS[workload].example_queries[0]
    return config(
        f"{workload}@v1:{SF}", q.sql, [candidate], [(p.name, list(p.values)) for p in q.param_sets],
        **kw,
    )  # fmt: skip


def _uniform_ms(high_ms: float, seed: int) -> Callable[[], None]:
    rng = random.Random(seed)

    def noise() -> None:
        time.sleep(rng.uniform(0, high_ms / 1000))

    return noise


def _replicated(
    provisioner: SandboxProvisioner, cfg: ExperimentConfig, options: EngineOptions
) -> tuple[ReplicatedRun, dict[int, MemoryHooks]]:
    hooks: dict[int, MemoryHooks] = {}

    def hooks_for(_: ExperimentConfig, index: int) -> MemoryHooks:
        hooks[index] = MemoryHooks()
        return hooks[index]

    run = run_replicated(
        cfg, approve_all(cfg), provisioner=provisioner, hooks_for=hooks_for, options=options
    )
    assert clone_names() == []
    return run, hooks


def test_noisy_fast_win_needs_three_agreeing_experiments(
    provisioner: SandboxProvisioner,
) -> None:
    """A 0-2 ms disturbance on every execution makes the sub-ms index arm fail gate 4b while
    the effect stays clearly separated. One experiment keeps its inconclusive verdict; the
    eligible arm is re-measured twice with new ids, seeds and clones.

    Measured on this host (PHASE_3_REPORT §4): most runs end verified_with_noise_warning, but
    between-experiment variation sometimes exceeds the iid CIs and the replicates disagree.
    Both are the designed outcomes; anything else (rejection, a clean verified label, a
    verified label with a CI below min_effect) is a failure.
    """
    cfg = _cfg("orders_ecommerce", COMPOSITE)

    run, _ = _replicated(provisioner, cfg, EngineOptions(noise=_uniform_ms(2.0, seed=11)))

    first = run.replicates[0].result
    (v,) = first.verdicts
    assert (v.verdict, v.gate, v.reasons[0].code) == ("inconclusive", 4, "insufficient_evidence")
    (screen,) = first.noise_screens
    assert screen.eligible, screen
    assert first.winner is None  # the existing result is kept for the single experiment
    assert run.replication is not None
    (rv,) = run.replication.verdicts
    if rv.verdict == "verified_with_noise_warning":
        assert len(run.replicates) == REPLICATES
        assert len({r.config.experiment_id for r in run.replicates}) == REPLICATES
        assert len({r.config.seed for r in run.replicates}) == REPLICATES
        assert rv.ci_low is not None
        assert rv.ci_low >= cfg.min_effect
        assert "independent experiments" in rv.reasons[0].detail
        assert run.winner == COMPOSITE.arm
    else:
        assert rv.verdict == "inconclusive", rv
        assert rv.reasons[0].code in ("replicates_disagree", "insufficient_evidence"), rv
        assert run.winner is None


def test_no_benefit_under_noise_is_never_verified_and_not_replicated(
    provisioner: SandboxProvisioner,
) -> None:
    cfg = _cfg("no_benefit", USELESS)

    run, _ = _replicated(provisioner, cfg, EngineOptions(noise=_uniform_ms(2.0, seed=12)))

    (v,) = run.replicates[0].result.verdicts
    assert v.verdict != "verified"
    assert run.replication is None  # the screen's effect check fails: nothing to replicate
    assert len(run.replicates) == 1
    assert run.winner is None


def test_meaningful_regression_is_rejected_as_corroborated(
    provisioner: SandboxProvisioner,
) -> None:
    """index_regression: 4.6x faster for 'open', 5.5x slower for 'escalated' in every block."""
    cfg = _cfg("index_regression", REGRESSING)

    run, _ = _replicated(provisioner, cfg, EngineOptions())

    (v,) = run.replicates[0].result.verdicts
    assert (v.verdict, v.gate, v.reasons[0].code) == ("rejected", 5, "regression"), v
    assert "escalated" in v.reasons[0].detail
    assert "every block" in v.reasons[0].detail
    assert run.replication is None


def _late_blocks(target: str, delay_ms: float, spared: set[int]) -> Callable[[str, str, int], None]:
    """Delay one arm in every block except `spared`: an arm-specific disturbance."""

    def noise(arm_name: str, _ps: str, block: int) -> None:
        if arm_name == target and block not in spared:
            time.sleep(delay_ms / 1000)

    return noise


def test_regression_from_an_arm_specific_disturbance_is_not_decisive(
    provisioner: SandboxProvisioner,
) -> None:
    """Misleadingly narrow CI, harm side: an index the query never uses is delayed by 4 ms in
    15 of 20 blocks. The iid bootstrap CI sits far below max_regression and bench@1 rejects;
    bench@2 sees undisturbed blocks above max_regression and stays inconclusive.

    The protection is a sign test, so it is probabilistic. Measured on this host
    (PHASE_3_REPORT §6), a no-difference block of a ~4 ms scan falls below 0.95 about a third
    of the time, so 6 default blocks with one clean block corroborate a false regression often.
    Here 20 blocks of 2 leave 5 clean blocks: a chance of roughly 0.35^5 < 1% that all of
    them fall below 0.95.
    """
    cfg = _cfg("orders_ecommerce", NEUTRAL, measured_runs=40, block_size=2)
    hooks = MemoryHooks()
    spared = {b for b in range(20) if b % 4 == 0}

    result = run_experiment(
        cfg, approve_all(cfg), provisioner=provisioner, hooks=hooks,
        options=EngineOptions(arm_noise=_late_blocks(NEUTRAL.arm, 4.0, spared=spared)),
    )  # fmt: skip

    assert all(s.ci_high < cfg.max_regression for s in result.stats)  # the CI looks decisive
    (v2,) = result.verdicts
    assert (v2.verdict, v2.gate, v2.reasons[0].code) == ("inconclusive", 5, "insufficient_evidence")
    assert "not corroborated" in v2.reasons[0].detail
    builds = {b.arm: b for b in result.builds}
    rescored = score(cfg, builds, hooks.records, unique_keys={}, env_digest="x",
                     engine_version="bench@1")  # fmt: skip
    (v1,) = rescored.verdicts
    assert (v1.verdict, v1.reasons[0].code) == ("rejected", "regression")
    assert clone_names() == []


def test_win_from_an_arm_specific_disturbance_is_not_noise_verified(
    provisioner: SandboxProvisioner,
) -> None:
    """Misleadingly narrow CI, benefit side: the baseline is delayed by 3 ms in half the blocks,
    so a useless index looks faster with a CI above min_effect. Dispersion stops it at gate 4b,
    and the noise screen refuses it (the effect is absent in the spared blocks)."""
    cfg = _cfg("no_benefit", USELESS)

    run, _ = _replicated(
        provisioner, cfg, EngineOptions(arm_noise=_late_blocks("baseline", 3.0, spared={0, 2, 4}))
    )

    first = run.replicates[0].result
    (v,) = first.verdicts
    assert v.verdict == "inconclusive", v
    if v.gate == 4:
        (screen,) = first.noise_screens
        assert not screen.eligible
        # Half the baseline samples are undisturbed: Q1 sits in the fast mode, and the spared
        # blocks show no effect. Either check alone refuses the arm.
        assert {"blocks", "separation"} & {c.name for c in screen.checks if not c.passed}
    assert run.replication is None
    assert run.winner is None
