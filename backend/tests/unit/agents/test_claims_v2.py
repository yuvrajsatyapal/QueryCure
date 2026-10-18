"""claims@2: evidence-specific grounding (ADR-0028).

claims@1 pools every measured figure of a run, so a speed-up measured for one candidate (or
one param set, or one experiment) validates a sentence about another. claims@2 binds each
clause to the subjects it names and checks it against those subjects' measurements only.

The figures are the 2026-10-17 real-model smoke run (`4c54fb8f`): the composite index on
hot_customer 3.62 -> 0.77 ms, 4.72x (3.40-5.67), and on regular_customer 3.19 -> 0.51 ms,
6.27x (5.22-7.40). The ANALYZE and single-column arms are invented, inconclusive comparators.
"""

import hashlib

import pytest

from querycure.agents import claims as claims_v1
from querycure.agents import claims_v2 as v2
from querycure.agents.claims import ActionRef, index_columns
from querycure.domain.investigation import Evidence

QUERY = "SELECT * FROM orders WHERE customer_id = $1 ORDER BY created_at DESC LIMIT 20"
COMPOSITE = "oc_aaaaaaaaaaa1"
ANALYZE_ARM = "oc_aaaaaaaaaaa2"
SINGLE = "oc_aaaaaaaaaaa3"
EXP1 = "1" * 64
EXP2 = "2" * 64


def _id(label: str) -> str:
    return "ev_" + hashlib.sha256(label.encode()).hexdigest()[:12]


def metric(
    arm: str, ps: str, speedup: float, lo: float, hi: float, base: float, cand: float,
    sha: str = EXP1,
) -> Evidence:  # fmt: skip
    return Evidence(
        id=_id(f"{arm}{ps}{sha}"),
        kind="benchmark_metric",
        artifact_sha256=sha,
        locator=f"/stats/{arm}/{ps}",
        summary="x",
        data={
            "arm": arm,
            "param_set": ps,
            "speedup": speedup,
            "ci_low": lo,
            "ci_high": hi,
            "baseline_median_ms": base,
            "candidate_median_ms": cand,
            "n_baseline": 30,
            "n_candidate": 30,
        },
        provenance="measured",
    )


def node(node_type: str, i: int = 0, ratio: float | None = None, direction: str | None = None):
    return Evidence(
        id=_id(f"node{i}{node_type}"),
        kind="plan_node",
        artifact_sha256="p" * 64,
        locator=f"/{i}",
        summary="x",
        data={
            "node_type": node_type,
            "estimate_error_ratio": ratio,
            "estimate_direction": direction,
            "inclusive_time_ms": 3.5,
        },
        provenance="measured",
    )


EVIDENCE = [
    node("Limit", 0),
    node("Sort", 1),
    node("Seq Scan", 2, ratio=12.0, direction="under"),
    metric(COMPOSITE, "hot_customer", 4.72, 3.40, 5.67, 3.62, 0.77),
    metric(COMPOSITE, "regular_customer", 6.27, 5.22, 7.40, 3.19, 0.51),
    metric(ANALYZE_ARM, "hot_customer", 1.02, 0.92, 1.12, 3.60, 3.53),
    metric(ANALYZE_ARM, "regular_customer", 0.99, 0.90, 1.08, 3.18, 3.21),
    metric(SINGLE, "hot_customer", 1.31, 1.05, 1.60, 3.61, 2.76, sha=EXP2),
]
ACTIONS = (
    ActionRef(COMPOSITE, "create_index",
              index_columns("CREATE INDEX ON orders (customer_id, created_at DESC)"), True),
    ActionRef(ANALYZE_ARM, "analyze_statistics", frozenset(), False),
    ActionRef(SINGLE, "create_index", index_columns("CREATE INDEX ON orders (customer_id)"), False),
)  # fmt: skip
VERDICTS = {
    COMPOSITE: "verified_with_noise_warning",
    ANALYZE_ARM: "inconclusive",
    SINGLE: "rejected",
}
PLANS = {
    COMPOSITE: frozenset({"limit", "index scan"}),
    ANALYZE_ARM: frozenset({"limit", "sort", "seq scan"}),
}


def ctx(**kw: object) -> v2.ClaimContext:
    args: dict[str, object] = {
        "query_sql": QUERY, "actions": ACTIONS, "verdicts": VERDICTS, "candidate_plans": PLANS,
    }  # fmt: skip
    args.update(kw)
    return v2.claim_context(EVIDENCE, **args)  # type: ignore[arg-type]


def problems(text: str, c: v2.ClaimContext | None = None, mode: v2.Mode = "fact") -> list[str]:
    return v2.check_sentence(text, c or ctx(), mode=mode)


def kept(text: str, c: v2.ClaimContext | None = None) -> bool:
    return not problems(text, c)


def test_version_is_new_and_v1_is_frozen() -> None:
    assert v2.CHECKER_VERSION == "claims@2"
    assert claims_v1.CHECKER_VERSION == "claims@1"


# --- attribution: a figure must belong to the subject the clause names --------------------


@pytest.mark.parametrize(
    "text",
    [
        "Running ANALYZE made the query 4.72x faster.",  # composite's figure, ANALYZE's claim
        "The single-column index on customer_id gave a 6.27x speed-up.",
        f"{ANALYZE_ARM} achieved 4.72x on hot_customer.",
    ],
)
def test_one_candidates_speedup_cannot_support_another(text: str) -> None:
    # claims@1 accepts all of them: 4.72 and 6.27 are measured values somewhere in the run.
    assert claims_v1.check_sentence(text, claims_v1.claim_context(EVIDENCE, query_sql=QUERY)) == []
    assert problems(text)


def test_supported_attributed_speedups_survive() -> None:
    assert kept(
        "The composite index on (customer_id, created_at) was 4.72x faster on hot_customer."
    )
    assert kept(f"{COMPOSITE} reached 6.27x on regular_customer.")
    assert kept("ANALYZE changed nothing measurable (1.02x on hot_customer).")


def test_param_set_attribution() -> None:
    assert problems("On hot_customer the composite index was 6.27x faster.")
    assert kept("On regular_customer the composite index was 6.27x faster.")


def test_two_param_sets_cannot_be_mixed_into_one_interval() -> None:
    # 3.40 is hot_customer's lower bound and 7.40 regular_customer's upper bound.
    assert problems("The composite index is 3.40-7.40x faster.")
    assert kept("The composite index is 3.40-5.67x faster on hot_customer.")
    assert problems("The composite index is 3.40-5.67x faster on regular_customer.")


def test_interval_of_another_experiment_is_not_borrowed() -> None:
    assert problems("The composite index measured 1.05-1.60x.")
    assert kept("The customer_id index measured 1.05-1.60x but was rejected.")


def test_replication_range_counts_for_its_own_arm_only() -> None:
    c = ctx(replication_ranges={COMPOSITE: (3.40, 7.40)})
    assert kept("Across three experiments the composite index was 3.40-7.40x faster.", c)
    assert problems("Across three experiments ANALYZE was 3.40-7.40x faster.", c)


def test_clauses_bind_separately() -> None:
    assert kept("The composite index was 4.72x faster, while ANALYZE stayed at 1.02x.")
    assert problems("The composite index was 1.02x faster, while ANALYZE reached 4.72x.")


def test_unattributed_figures_fall_back_to_the_pooled_check() -> None:
    assert kept("The best candidate was 4.72x faster.")
    assert problems("The best candidate was 9.1x faster.")


# --- alternative wordings -------------------------------------------------------------------


@pytest.mark.parametrize(
    ("text", "ok"),
    [
        ("The composite index gives a 4.72-fold improvement.", True),
        ("The composite index gives a 9-fold improvement.", False),
        ("The composite index cut latency by a factor of 4.72.", True),
        ("The composite index cut latency by a factor of 12.", False),
        ("The composite index delivered a speedup of 4.72 on hot_customer.", True),
        ("The composite index delivered a speedup of 8.5.", False),
        ("ANALYZE delivered a speed-up of 4.72.", False),
    ],
)
def test_alternative_speedup_wordings(text: str, ok: bool) -> None:
    assert kept(text) is ok, problems(text)


def test_alternative_wordings_before_any_benchmark() -> None:
    pre = v2.claim_context([node("Seq Scan")], query_sql=QUERY)
    assert problems("An index would give a 10-fold improvement.", pre)
    assert problems("The index should reduce latency by 90%.", pre)


@pytest.mark.parametrize(
    ("text", "ok"),
    [
        ("The composite index reduced latency by 79% on hot_customer.", True),  # 1 - 1/4.72
        ("The composite index reduced latency by 372%.", False),  # 4.72 - 1: not a reduction
        ("The composite index made it 372% faster on hot_customer.", True),
        ("The composite index cut query time by 95%.", False),
        ("ANALYZE reduced latency by 79%.", False),
    ],
)
def test_percentage_reduction_versus_multiplier(text: str, ok: bool) -> None:
    assert kept(text) is ok, problems(text)


@pytest.mark.parametrize(
    ("text", "ok"),
    [
        ("The composite index saves 2.85 ms per execution on hot_customer.", True),
        ("The composite index saves about 2.9 ms on hot_customer.", True),
        ("The composite index saves 3.62 ms per execution.", False),  # a median, not a saving
        ("ANALYZE saves 2.85 ms.", False),
    ],
)
def test_absolute_latency_savings(text: str, ok: bool) -> None:
    assert kept(text) is ok, problems(text)


@pytest.mark.parametrize(
    ("text", "ok"),
    [
        ("With the composite index, hot_customer drops from 3.62 ms to 0.77 ms.", True),
        ("With the composite index, hot_customer drops from 0.77 ms to 3.62 ms.", False),
        ("With the composite index, latency drops from 3.62 ms to 0.51 ms.", False),  # mixed
        ("Latency went 3.19 ms -> 0.51 ms on regular_customer.", True),
    ],
)
def test_latency_transitions_must_be_one_measurement(text: str, ok: bool) -> None:
    assert kept(text) is ok, problems(text)


# --- guarantees, status, recommendations ---------------------------------------------------


@pytest.mark.parametrize(
    ("text", "ok"),
    [
        ("The composite index guarantees faster queries in production.", False),
        ("This index will always be faster.", False),
        ("The benchmark cannot guarantee the same speed-up in production.", True),
        ("There is no guarantee that production data behaves the same.", True),
    ],
)
def test_guaranteed_improvement_claims(text: str, ok: bool) -> None:
    assert kept(text) is ok, problems(text)


@pytest.mark.parametrize(
    ("text", "ok"),
    [
        ("ANALYZE was verified by the benchmark.", False),
        ("Both the composite index and ANALYZE were verified.", False),
        ("The customer_id index was inconclusive.", False),  # it was rejected
        ("The customer_id index was rejected.", True),
        ("ANALYZE was inconclusive.", True),
        ("The composite index was rejected.", False),
        ("The composite index was verified, while ANALYZE remained inconclusive.", True),
        ("Of the candidates, only the composite index was verified.", True),
    ],
)
def test_optimization_status_must_match_the_named_subject(text: str, ok: bool) -> None:
    assert kept(text) is ok, problems(text)


def test_noise_warning_cannot_be_called_clean() -> None:
    assert problems("The composite index was cleanly verified with no noise concerns.")
    assert kept("The composite index was verified with a noise warning.")


@pytest.mark.parametrize(
    ("text", "ok"),
    [
        ("Do not create the composite index on (customer_id, created_at).", False),
        ("The composite index is not recommended.", False),
        ("Avoid running ANALYZE as a fix; it was inconclusive.", True),
        ("Create the composite index and run ANALYZE, although ANALYZE was inconclusive.", False),
        ("Create the composite index; ANALYZE was inconclusive.", True),
    ],
)
def test_contradictory_recommendations(text: str, ok: bool) -> None:
    assert kept(text) is ok, problems(text)


# --- plans: baseline versus candidate -------------------------------------------------------


@pytest.mark.parametrize(
    ("text", "ok"),
    [
        ("The baseline plan uses an Index Scan.", False),  # only the candidate plan has one
        ("The baseline plan uses a Seq Scan.", True),
        ("With the composite index the plan uses an Index Scan.", True),
        ("With the composite index the plan uses a Bitmap Heap Scan.", False),
        ("The optimized plan replaces the Seq Scan with an Index Scan.", True),
    ],
)
def test_baseline_and_candidate_plans_are_not_confused(text: str, ok: bool) -> None:
    assert kept(text) is ok, problems(text)


def test_the_baselines_measured_plan_is_baseline_evidence() -> None:
    c = ctx(candidate_plans={**PLANS, "baseline": frozenset({"bitmap heap scan"})})
    assert kept("The baseline plan uses a Bitmap Heap Scan.", c)
    assert problems("The baseline plan uses an Index Scan.", c)


def test_without_candidate_plans_claims_v1_scan_rule_applies() -> None:
    c = ctx(candidate_plans={})
    assert problems("With the composite index the plan uses an Index Scan.", c)


# --- statistics conclusions -----------------------------------------------------------------


@pytest.mark.parametrize(
    ("text", "ok"),
    [
        ("The planner underestimates the rows of the sequential scan by 12x.", True),
        ("The planner overestimates the rows of the sequential scan.", False),
        ("The row estimates are accurate.", False),
    ],
)
def test_estimate_conclusions(text: str, ok: bool) -> None:
    assert kept(text) is ok, problems(text)


def test_fresh_statistics_claim_contradicts_stale_evidence() -> None:
    stale = Evidence(
        id=_id("t"), kind="table_stat", artifact_sha256=None, locator="/t/orders", summary="x",
        data={"planner_stats": "present", "counters": "live", "freshness": "stale"},
        provenance="measured",
    )  # fmt: skip
    c = v2.claim_context([stale, node("Seq Scan")], query_sql=QUERY)
    assert problems("The table statistics are up to date.", c)
    assert kept("The table statistics are stale.", c)


# --- filter_text keeps claims@1's contract --------------------------------------------------


def test_filter_text_removes_whole_sentences_only() -> None:
    text = (
        "The composite index was 4.72x faster on hot_customer. "
        "Running ANALYZE made it 4.72x faster. "
        "The baseline plan uses a Seq Scan."
    )
    out = v2.filter_text(text, ctx())
    assert out.text == (
        "The composite index was 4.72x faster on hot_customer. The baseline plan uses a Seq Scan."
    )
    assert out.removed == ["Running ANALYZE made it 4.72x faster."]
    assert out.problems
    assert "ANALYZE" in out.problems[0]


def test_pre_benchmark_prose_unchanged_from_v1_for_plain_text() -> None:
    """Analyst prose with no subject, figure or status passes both versions identically."""
    pre1 = claims_v1.claim_context([node("Seq Scan")], query_sql=QUERY)
    pre2 = v2.claim_context([node("Seq Scan")], query_sql=QUERY)
    for text in (
        "The query scans orders sequentially and sorts the result.",
        "A composite index on (customer_id, created_at) could avoid the sort.",
        "The sequential scan reads every row of orders.",
        "An index-only scan is impossible here.",
    ):
        assert bool(claims_v1.check_sentence(text, pre1)) == bool(v2.check_sentence(text, pre2))
