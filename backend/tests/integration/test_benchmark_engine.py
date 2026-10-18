"""Benchmark engine against the real sandbox server: lifecycle, safety and resume.

Verdict expectations per workload (the TESTING_STRATEGY §6 table) live in
test_benchmark_eval_table.py. These assert verdicts and properties, never latencies.
"""

import threading

import pytest

from querycure.benchmark.engine import (
    FLOOR_SAMPLES,
    ApprovalMismatchError,
    ApprovedExperiment,
    run_experiment,
    score,
)
from querycure.core.errors import RunCancelledError, SandboxPolicyError
from querycure.domain.benchmark import TRANSPORT_DOMINATED_SHARE, CandidateArm
from querycure.sandbox.provisioner import SandboxProvisioner
from tests.integration.engine_helpers import (
    MemoryHooks,
    approve_all,
    arm,
    assert_verified_or_noisy,
    config,
)
from tests.integration.sandbox_fixtures import clone_names

pytestmark = pytest.mark.integration

ORDERS = "orders_ecommerce@v1:sf=0.1:seed=42"
RECENT = "SELECT * FROM orders WHERE customer_id = $1 ORDER BY created_at DESC LIMIT 20"
INDEX = arm("oc_000000000001", "create_index", ["CREATE INDEX ON orders (customer_id, created_at)"])


def _cfg(**kw: object):  # type: ignore[no-untyped-def]
    return config(ORDERS, RECENT, [INDEX], [("hot_customer", [1024]), ("regular", [7])], **kw)


def test_composite_index_is_verified_and_everything_is_cleaned_up(
    provisioner: SandboxProvisioner,
) -> None:
    cfg = _cfg()
    hooks = MemoryHooks()

    result = run_experiment(cfg, approve_all(cfg), provisioner=provisioner, hooks=hooks)

    verdict = result.verdicts[0]
    assert_verified_or_noisy(verdict)
    assert result.winner == (INDEX.arm if verdict.verdict == "verified" else None)
    primary = next(s for s in result.stats if s.param_set == "hot_customer")
    assert primary.speedup > 1.5  # direction is never in doubt, only the noise gate
    assert result.builds[0].ok
    assert result.builds[0].index_size_bytes > 0
    # Raw samples are integer nanoseconds, measured_runs per arm and param set.
    for m in result.measurements:
        assert len(m.latencies_ns) == 30
        assert all(isinstance(x, int) and x > 0 for x in m.latencies_ns)
    states = [s for s, _ in hooks.states]
    assert states[:2] == ["provisioning", "building"]
    assert states[-3:] == ["capturing_plans", "checking", "scoring"]
    assert hooks.env is not None
    assert hooks.env.pg_settings["jit"] == "off"
    assert {r.phase for r in hooks.records} == {"build", "measure", "plan"}
    plans = [r for r in hooks.records if r.phase == "plan"]
    assert all(r.plan is not None and r.buffers is not None for r in plans)
    assert clone_names() == []


def test_transport_floor_is_recorded_beside_and_never_inside_the_samples(
    provisioner: SandboxProvisioner,
) -> None:
    """BENCHMARK_ENGINE §4 step 7: the floor is diagnostic. Re-scoring the same persisted
    rows without it yields identical statistics and verdicts."""
    cfg = _cfg()
    hooks = MemoryHooks()

    result = run_experiment(cfg, approve_all(cfg), provisioner=provisioner, hooks=hooks)

    floor = result.transport_floor
    assert floor is not None
    assert floor.samples == 2 * FLOOR_SAMPLES
    assert floor.before_median_ns is not None
    assert floor.before_median_ns > 0
    assert floor.after_median_ns is not None
    assert floor.after_median_ns > 0
    fastest = min(m.median_ns for s in result.stats for m in (s.baseline, s.candidate))
    assert floor.share_of_fastest_arm == pytest.approx(floor.median_ns / fastest, rel=1e-3)
    assert floor.transport_dominated == (floor.share_of_fastest_arm >= TRANSPORT_DOMINATED_SHARE)
    # Samples are still exactly measured_runs per arm and param set: no round trip leaked in.
    assert all(len(m.latencies_ns) == 30 for m in result.measurements)
    builds = {b.arm: b for b in result.builds}
    rescored = score(cfg, builds, hooks.records, unique_keys={}, env_digest="x",
                     total=result.order_is_total)  # fmt: skip
    assert rescored.transport_floor is None
    assert rescored.stats == result.stats
    assert rescored.verdicts == result.verdicts


def test_unapproved_arm_executes_nothing(provisioner: SandboxProvisioner) -> None:
    cfg = _cfg()
    hooks = MemoryHooks()

    with pytest.raises(ApprovalMismatchError):
        run_experiment(
            cfg,
            ApprovedExperiment(approval_request_id="x", approved_sql={}),
            provisioner=provisioner,
            hooks=hooks,
        )

    assert hooks.states == []
    assert hooks.records == []
    assert clone_names() == []


def test_sql_changed_after_approval_executes_nothing(provisioner: SandboxProvisioner) -> None:
    approved_cfg = _cfg()
    tampered = approved_cfg.model_copy(
        update={
            "candidates": [
                INDEX.model_copy(update={"ddl": ["CREATE INDEX ON orders (customer_id)"]})
            ]
        }
    )
    hooks = MemoryHooks()

    with pytest.raises(ApprovalMismatchError):
        run_experiment(tampered, approve_all(approved_cfg), provisioner=provisioner, hooks=hooks)

    assert hooks.records == []


def test_ddl_outside_the_allowlist_is_refused_even_when_approved(
    provisioner: SandboxProvisioner,
) -> None:
    evil = CandidateArm(
        arm="oc_00000000000e", candidate_id=None, kind="create_index", ddl=["DROP TABLE orders"],
        query=None,
    )  # fmt: skip
    cfg = config(ORDERS, RECENT, [evil], [("hot", [1024])])
    hooks = MemoryHooks()

    with pytest.raises(SandboxPolicyError):
        run_experiment(cfg, approve_all(cfg), provisioner=provisioner, hooks=hooks)

    assert hooks.records == []
    assert clone_names() == []


def test_cancel_stops_within_one_block_and_drops_clones(provisioner: SandboxProvisioner) -> None:
    cfg = _cfg(measured_runs=60)
    hooks = MemoryHooks(cancel_after_blocks=2)

    with pytest.raises(RunCancelledError):
        run_experiment(cfg, approve_all(cfg), provisioner=provisioner, hooks=hooks)

    measured = [r for r in hooks.records if r.phase == "measure"]
    # Cancelled after the 2nd arm-block row: at most the rest of that block (one more arm).
    assert 2 <= len(measured) <= 3
    assert clone_names() == []


def test_cancel_interrupts_an_in_flight_query(provisioner: SandboxProvisioner) -> None:
    """A slow statement is cancelled mid-flight (pg cancel), not waited out."""
    slow = "SELECT count(*) FROM orders a, orders b WHERE a.id < $1 AND b.id < 100000"
    cfg = config(
        ORDERS,
        slow,
        [arm("oc_000000000002", "analyze_statistics", ["ANALYZE orders"])],
        [("big", [100000])],
        query_timeout_ms=60_000,
        warmup_runs=1,
    )
    hooks = MemoryHooks()
    timer = threading.Timer(3.0, hooks.cancel.set)
    timer.start()
    import time

    started = time.monotonic()
    with pytest.raises(RunCancelledError):
        run_experiment(cfg, approve_all(cfg), provisioner=provisioner, hooks=hooks)
    timer.cancel()

    assert time.monotonic() - started < 15
    assert clone_names() == []


def test_resume_measures_only_missing_blocks(provisioner: SandboxProvisioner) -> None:
    """A crash mid-measurement resumes at the first missing block (no duplicate rows)."""
    cfg = _cfg()
    hooks = MemoryHooks(cancel_after_blocks=3)
    with pytest.raises(RunCancelledError):
        run_experiment(cfg, approve_all(cfg), provisioner=provisioner, hooks=hooks)
    first_attempt = {r.key for r in hooks.records}
    hooks.cancel.clear()
    hooks.cancel_after_blocks = None

    result = run_experiment(cfg, approve_all(cfg), provisioner=provisioner, hooks=hooks)

    assert first_attempt <= {r.key for r in hooks.records}  # nothing re-measured or replaced
    assert all(len(m.latencies_ns) == 30 for m in result.measurements)
    assert clone_names() == []


def test_failed_ddl_is_rejected_and_other_arms_still_run(provisioner: SandboxProvisioner) -> None:
    bad = arm("oc_00000000000b", "create_index", ["CREATE INDEX ON orders (no_such_column)"])
    cfg = config(ORDERS, RECENT, [bad, INDEX], [("hot_customer", [1024])])
    hooks = MemoryHooks()

    result = run_experiment(cfg, approve_all(cfg), provisioner=provisioner, hooks=hooks)

    by_arm = {v.arm: v for v in result.verdicts}
    assert (by_arm[bad.arm].verdict, by_arm[bad.arm].reasons[0].code) == ("rejected", "ddl_failed")
    assert_verified_or_noisy(by_arm[INDEX.arm])
    assert len(next(m for m in result.measurements if m.arm == INDEX.arm).latencies_ns) == 30


def test_index_size_constraint_rejects(provisioner: SandboxProvisioner) -> None:
    cfg = _cfg(max_index_bytes=1024)

    result = run_experiment(cfg, approve_all(cfg), provisioner=provisioner, hooks=MemoryHooks())

    assert (result.verdicts[0].verdict, result.verdicts[0].reasons[0].code) == (
        "rejected",
        "constraint_violation",
    )
