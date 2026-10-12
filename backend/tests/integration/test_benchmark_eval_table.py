"""Benchmark-engine evaluation table (TESTING_STRATEGY §6, ROADMAP Phase 3 acceptance #1).

Hand-written candidates (no LLM) on the demo workloads at sf=0.1, real sandbox PostgreSQL,
spec-default thresholds. Assertions are on verdicts and reason codes, never on latencies.

Positive cases accept `inconclusive` only from the sample-quality gate (gate 4), the
documented noisy-hardware outcome (see engine_helpers.assert_verified_or_noisy). Negative cases
(mismatch, regression, no benefit) are strict.
"""

import random
import time

import pytest

from querycure.benchmark.engine import EngineOptions, run_experiment
from querycure.domain.benchmark import ExperimentResult, RuleVerdict
from querycure.sandbox.provisioner import SandboxProvisioner
from querycure.workloads.registry import WORKLOADS
from tests.integration.engine_helpers import (
    MemoryHooks,
    approve_all,
    arm,
    assert_verified_or_noisy,
    config,
)
from tests.integration.sandbox_fixtures import clone_names

pytestmark = pytest.mark.integration

SF = "sf=0.1:seed=42"


def _example(workload: str) -> tuple[str, list[tuple[str, list[object]]]]:
    query = WORKLOADS[workload].example_queries[0]
    return query.sql, [(p.name, list(p.values)) for p in query.param_sets]


def _run(
    provisioner: SandboxProvisioner,
    workload: str,
    candidates: list,  # type: ignore[type-arg]
    *,
    query: str | None = None,
    param_sets: list[tuple[str, list[object]]] | None = None,
    options: EngineOptions | None = None,
    **overrides: object,
) -> ExperimentResult:
    example_query, example_params = _example(workload)
    cfg = config(
        f"{workload}@v1:{SF}",
        query or example_query,
        candidates,
        param_sets or example_params,
        **overrides,
    )
    result = run_experiment(
        cfg, approve_all(cfg), provisioner=provisioner, hooks=MemoryHooks(), options=options
    )
    assert clone_names() == []
    return result


def _only(result: ExperimentResult) -> RuleVerdict:
    assert len(result.verdicts) == 1
    return result.verdicts[0]


def test_known_missing_index_is_verified(provisioner: SandboxProvisioner) -> None:
    result = _run(
        provisioner,
        "orders_ecommerce",
        [
            arm(
                "oc_0000000000a1",
                "create_index",
                ["CREATE INDEX ON orders (customer_id, created_at)"],
            )
        ],
    )

    assert_verified_or_noisy(_only(result))


def test_join_on_unindexed_key_is_verified(provisioner: SandboxProvisioner) -> None:
    result = _run(
        provisioner,
        "join_fanout",
        [arm("oc_0000000000a2", "create_index", ["CREATE INDEX ON posts (author_id)"])],
    )

    assert_verified_or_noisy(_only(result))


def test_cardinality_misestimate_fixed_by_analyze_is_verified(
    provisioner: SandboxProvisioner,
) -> None:
    result = _run(
        provisioner,
        "stale_stats",
        [arm("oc_0000000000a3", "analyze_statistics", ["ANALYZE events"])],
    )

    assert_verified_or_noisy(_only(result))


def test_no_beneficial_optimization_is_never_verified(provisioner: SandboxProvisioner) -> None:
    result = _run(
        provisioner,
        "no_benefit",
        [arm("oc_0000000000a4", "create_index", ["CREATE INDEX ON app_settings (key, value)"])],
    )

    verdict = _only(result)
    assert verdict.verdict in ("inconclusive", "rejected"), verdict
    if verdict.verdict == "rejected":
        assert verdict.reasons[0].code in ("no_improvement", "regression")
    assert result.winner is None


def test_slower_on_one_param_set_is_rejected_as_regression(
    provisioner: SandboxProvisioner,
) -> None:
    result = _run(
        provisioner,
        "index_regression",
        [arm("oc_0000000000a5", "create_index", ["CREATE INDEX ON tickets (opened_at, id)"])],
    )

    verdict = _only(result)
    assert (verdict.verdict, verdict.reasons[0].code) == ("rejected", "regression"), verdict
    assert "escalated" in verdict.reasons[0].detail
    open_stats = next(s for s in result.stats if s.param_set == "open")
    assert open_stats.ci_low > 1.0  # the index really helps the primary param set


def test_rewrite_that_changes_semantics_is_rejected(provisioner: SandboxProvisioner) -> None:
    rewrite = (
        "SELECT count(*) FROM accounts a WHERE NOT EXISTS "
        "(SELECT 1 FROM closed_regions c WHERE c.region_code = a.region_code)"
    )
    result = _run(
        provisioner, "rewrite_trap", [arm("oc_0000000000a6", "query_rewrite", query=rewrite)]
    )

    verdict = _only(result)
    assert (verdict.verdict, verdict.reasons[0].code) == ("rejected", "result_mismatch"), verdict


def test_limit_with_ties_is_nondeterministic_or_multiset_equal(
    provisioner: SandboxProvisioner,
) -> None:
    """ORDER BY a non-unique column + LIMIT: tied rows may legitimately differ."""
    query = "SELECT customer_id, status FROM orders WHERE customer_id = $1 ORDER BY status LIMIT 3"
    result = _run(
        provisioner,
        "orders_ecommerce",
        [arm("oc_0000000000a7", "create_index", ["CREATE INDEX ON orders (customer_id, status)"])],
        query=query,
        param_sets=[("hot_customer", [1024])],
    )

    verdict = _only(result)
    assert result.order_is_total is False
    if verdict.verdict != "verified":
        assert verdict.reasons[0].code in ("nondeterministic_order", "insufficient_evidence"), (
            verdict
        )


def test_noisy_environment_is_insufficient_evidence(provisioner: SandboxProvisioner) -> None:
    """Injected latency noise (test seam) on every execution: the noise gate must hold."""
    rng = random.Random(7)

    def noise() -> None:
        time.sleep(rng.uniform(0, 0.02))

    result = _run(
        provisioner,
        "orders_ecommerce",
        [
            arm(
                "oc_0000000000a8",
                "create_index",
                ["CREATE INDEX ON orders (customer_id, created_at)"],
            )
        ],
        options=EngineOptions(noise=noise),
        measured_runs=20,
    )

    verdict = _only(result)
    assert (verdict.verdict, verdict.gate, verdict.reasons[0].code) == (
        "inconclusive",
        4,
        "insufficient_evidence",
    ), verdict


def test_tournament_ranks_competing_candidates(provisioner: SandboxProvisioner) -> None:
    """Disagreeing hypotheses are settled by one experiment against a shared baseline."""
    composite = arm(
        "oc_0000000000b1", "create_index", ["CREATE INDEX ON orders (customer_id, created_at)"]
    )
    single = arm("oc_0000000000b2", "create_index", ["CREATE INDEX ON orders (customer_id)"])
    stats_only = arm("oc_0000000000b3", "analyze_statistics", ["ANALYZE orders"])

    result = _run(provisioner, "orders_ecommerce", [composite, single, stats_only])

    assert [e.rank for e in result.tournament] == [1, 2, 3]
    by_arm = {v.arm: v for v in result.verdicts}
    assert by_arm[stats_only.arm].verdict != "verified"  # statistics alone cannot add an index
    if result.winner is not None:
        assert result.winner in (composite.arm, single.arm)
        assert result.tournament[0].arm == result.winner
