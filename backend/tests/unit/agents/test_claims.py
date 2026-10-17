"""Deterministic claim grounding (E2E audit 2026-10-17, issue O2/O3).

The run-2 texts below are the exact AI-written strings sealed in that run's report (model
`nvidia/nemotron-3-super-120b-a12b:free`), including the U+2011 non-breaking hyphens the model
used. The measured values are that run's stored experiment results.
"""

from querycure.agents.claims import (
    ActionRef,
    ClaimContext,
    StatsSupport,
    filter_text,
    index_columns,
    star_projection,
)

QUERY = "SELECT * FROM orders WHERE customer_id = $1 ORDER BY created_at DESC LIMIT 20"
COMPOSITE = "oc_fcc7c344b33b"
SINGLE_CUSTOMER = "oc_fd262a3ff007"
SINGLE_CREATED = "oc_2fe2493f9ef7"
ANALYZE_ARM = "oc_b3823040f745"

# (speedup, ci_low, ci_high) for every arm and param set across the run's three experiments.
RUN2_STATS = [
    (1.705, 1.209, 2.470),
    (1.072, 0.982, 1.394),
    (1.017, 0.923, 1.121),
    (1.033, 0.791, 1.283),
    (2.955, 2.697, 3.398),
    (3.474, 3.106, 5.449),
    (2.280, 1.954, 3.081),
    (3.656, 3.118, 4.559),
    (2.692, 2.278, 3.525),
    (3.448, 2.321, 4.899),
    (2.824, 1.879, 3.577),
    (3.411, 2.978, 4.800),
    (4.357, 2.982, 5.837),
    (3.658, 2.527, 5.835),
]
CLONE_STATS = StatsSupport(
    tables_known=True, planner_stats_absent=False, stale=False, freshness_known=False,
    counters_live=False,
)  # fmt: skip


def actions(verified: frozenset[str] = frozenset({COMPOSITE})) -> tuple[ActionRef, ...]:
    def ref(arm: str, kind: str, ddl: str) -> ActionRef:
        return ActionRef(arm=arm, kind=kind, columns=index_columns(ddl), verified=arm in verified)

    return (
        ref(COMPOSITE, "create_index",
            "CREATE INDEX IF NOT EXISTS idx_a ON orders (customer_id, created_at DESC)"),
        ref(SINGLE_CUSTOMER, "create_index", "CREATE INDEX idx_b ON orders (customer_id)"),
        ref(SINGLE_CREATED, "create_index", "CREATE INDEX idx_c ON orders (created_at DESC)"),
        ref(ANALYZE_ARM, "analyze_statistics", "ANALYZE orders"),
    )  # fmt: skip


def pre_benchmark(**overrides: object) -> ClaimContext:
    base: dict[str, object] = {
        "plan_node_types": frozenset({"limit", "sort", "seq scan"}),
        "star_projection": True,
        "stats": CLONE_STATS,
        "latencies_ms": (),
    }
    base.update(overrides)
    return ClaimContext(**base)  # type: ignore[arg-type]


def post_benchmark(**overrides: object) -> ClaimContext:
    ctx = pre_benchmark(
        benchmarked=True,
        speedups=tuple(s for s, _, _ in RUN2_STATS)
        + tuple(x for _, lo, hi in RUN2_STATS for x in (lo, hi)),
        intervals=tuple((lo, hi) for _, lo, hi in RUN2_STATS),
        actions=actions(),
        verdicts={COMPOSITE: "verified_with_noise_warning", SINGLE_CUSTOMER: "inconclusive",
                  SINGLE_CREATED: "inconclusive", ANALYZE_ARM: "inconclusive"},
    )  # fmt: skip
    return ClaimContext(**{**ctx.__dict__, **overrides})  # type: ignore[arg-type]


RUN2_SUMMARY = (
    "The query is slow because it performs a sequential scan on the orders table due to a "
    "missing index on customer_id, and then sorts the results because no index supports the "
    "ORDER BY created_at DESC. Low column correlations make single\u2011column indexes "
    "ineffective, so a composite index on (customer_id, created_at DESC) would allow an "
    "index\u2011only scan that returns rows already sorted and stops early thanks to LIMIT 20. "
    "Additionally, the table statistics are stale, which may affect planner estimates. "
    "Creating the recommended index and running ANALYZE should resolve the performance issue."
)
RUN2_AUDITOR = (
    "The benchmark found a verified speed\u2011up only for the composite index on (customer_id, "
    "created_at DESC) (oc_fcc7c344b33b), which showed 2.9\u20114.4\u00d7 median latency "
    "reductions on both hot and regular customer parameter sets. All other candidates\u2014"
    "single\u2011column indexes on created_at, customer_id, and an ANALYZE command\u2014remained "
    "inconclusive, with no demonstrated benefit and high variability in measurements."
)


# --- audit contradiction 1: ANALYZE recommended although its benchmark was inconclusive ---


def test_recommending_an_inconclusive_analyze_is_removed() -> None:
    out = filter_text(RUN2_SUMMARY, post_benchmark())

    assert "running ANALYZE" not in out.text
    assert any("ANALYZE" in p and "not verified" in p for p in out.problems)


def test_recommending_the_verified_index_is_kept() -> None:
    text = "Create the composite index on (customer_id, created_at DESC)."
    assert filter_text(text, post_benchmark()).text == text


def test_recommending_an_index_whose_columns_match_only_an_inconclusive_arm_is_removed() -> None:
    out = filter_text("Add an index on customer_id alone.", post_benchmark())
    assert out.text == ""


def test_describing_inconclusive_candidates_is_not_a_recommendation() -> None:
    text = "An ANALYZE command remained inconclusive."
    assert filter_text(text, post_benchmark()).text == text


def test_explain_analyze_is_not_an_analyze_recommendation() -> None:
    text = "Run EXPLAIN ANALYZE on staging to compare plans."
    assert filter_text(text, post_benchmark()).text == text


def test_actions_are_not_judged_before_anything_was_benchmarked() -> None:
    text = "Running ANALYZE could refresh the statistics."
    assert filter_text(text, pre_benchmark()).text == text


# --- audit contradiction 2: index-only scan claimed for SELECT * ---


def test_index_only_scan_for_select_star_is_removed_even_when_hedged() -> None:
    out = filter_text(RUN2_SUMMARY, pre_benchmark())

    assert "only scan" not in out.text.replace("\u2011", "-")
    assert any("index-only scan" in p for p in out.problems)
    assert out.text.startswith("The query is slow because it performs a sequential scan")


def test_index_only_scan_is_allowed_when_a_plan_shows_one() -> None:
    ctx = pre_benchmark(plan_node_types=frozenset({"index only scan"}))
    text = "The plan uses an Index Only Scan on orders."
    assert filter_text(text, ctx).text == text


def test_asserted_scan_type_absent_from_the_plan_is_removed() -> None:
    out = filter_text("The planner uses a Bitmap Heap Scan on orders.", pre_benchmark())
    assert out.text == ""


def test_prospective_scan_type_claim_is_kept() -> None:
    text = "A composite index would allow an Index Scan that returns rows already sorted."
    assert filter_text(text, pre_benchmark()).text == text


def test_scan_type_present_in_the_plan_is_kept() -> None:
    text = "The plan performs a Seq Scan over orders."
    assert filter_text(text, pre_benchmark()).text == text


def test_scan_types_are_hypothesis_tolerant_but_impossible_ones_are_not() -> None:
    ctx = pre_benchmark()
    assert filter_text("The planner picks an Index Scan.", ctx, mode="hypothesis").text != ""
    assert filter_text("It becomes an index-only scan.", ctx, mode="hypothesis").text == ""


# --- audit contradiction 3: speed-up figures not in the recorded measurements ---


def test_speedup_range_matching_no_stored_interval_is_removed() -> None:
    out = filter_text(RUN2_AUDITOR, post_benchmark())

    assert "4.4" not in out.text
    assert out.text.startswith("All other candidates")
    assert any("2.9" in p and "4.4" in p for p in out.problems)


def test_speedup_range_matching_a_stored_interval_is_kept() -> None:
    text = "The composite index measured 2.95x (95% CI 2.70-3.40x) on hot_customer."
    assert filter_text(text, post_benchmark()).text == text


def test_single_speedup_must_match_a_measured_value() -> None:
    assert filter_text("It is 2.95x faster.", post_benchmark()).text != ""
    assert filter_text("It is 7.5x faster.", post_benchmark()).text == ""
    assert filter_text("It is 3 times faster.", post_benchmark()).text != ""  # 3.0 ~ 2.98


def test_any_speedup_before_benchmarking_is_removed() -> None:
    assert filter_text("The index will make it 3x faster.", pre_benchmark()).text == ""


def test_percentage_improvements_must_derive_from_a_measured_speedup() -> None:
    ctx = post_benchmark()
    # 2.955x -> 66% less time
    assert filter_text("Latency drops by 66% faster on hot_customer.", ctx).text != ""
    assert filter_text("Latency is 90% faster.", ctx).text == ""


def test_estimate_error_ratios_are_not_speedups() -> None:
    ctx = pre_benchmark(ratios=(12.3,))
    text = "The planner underestimates the rows by 12.3x."
    assert filter_text(text, ctx).text == text


def test_latencies_must_match_recorded_timings() -> None:
    ctx = post_benchmark(latencies_ms=(3.808, 1.289))
    assert filter_text("The baseline median is 3.8 ms.", ctx).text != ""
    assert filter_text("The baseline median is about 4 ms.", ctx).text != ""
    assert filter_text("The baseline median is 42 ms.", ctx).text == ""


# --- verification status ---


def test_verified_claim_before_any_benchmark_is_removed() -> None:
    out = filter_text("The composite index has been verified to remove the sort.", pre_benchmark())
    assert out.text == ""


def test_verified_claim_about_an_inconclusive_arm_is_removed() -> None:
    out = filter_text("oc_b3823040f745 was verified in the sandbox.", post_benchmark())
    assert out.text == ""


def test_calling_a_verified_arm_inconclusive_is_a_contradiction() -> None:
    out = filter_text("oc_fcc7c344b33b remained inconclusive.", post_benchmark())
    assert out.text == ""


def test_hedged_verification_language_is_fine() -> None:
    text = "The effect should be verified by benchmarking."
    assert filter_text(text, pre_benchmark()).text == text


# --- statistics claims (O3) ---


def test_never_analyzed_is_contradicted_by_planner_statistics() -> None:
    hyp = (
        "Table statistics are stale (never analyzed), which may lead to poor planner "
        "estimates and suboptimal plan choice."
    )
    assert filter_text(hyp, pre_benchmark(), mode="hypothesis").text == ""


def test_reset_usage_counters_are_not_evidence() -> None:
    detail = (
        "The only existing index is orders_pkey on the id column. It does not assist the "
        "filter on customer_id or the ordering on created_at, and the table has never had an "
        "index scan (0 index scans ever)."
    )
    out = filter_text(detail, pre_benchmark())
    assert out.text == "The only existing index is orders_pkey on the id column."


def test_counters_are_usable_on_a_live_database() -> None:
    live = StatsSupport(
        tables_known=True, planner_stats_absent=False, stale=False, freshness_known=False,
        counters_live=True,
    )  # fmt: skip
    text = "The table shows 0 index scans."
    assert filter_text(text, pre_benchmark(stats=live)).text == text


def test_assertive_staleness_needs_evidence_but_a_hypothesis_may_propose_it() -> None:
    text = "The table statistics are stale."
    assert filter_text(text, pre_benchmark()).text == ""
    assert filter_text(text, pre_benchmark(), mode="hypothesis").text == text


def test_staleness_supported_by_evidence_is_kept() -> None:
    stale = StatsSupport(
        tables_known=True, planner_stats_absent=False, stale=True, freshness_known=True,
        counters_live=True,
    )  # fmt: skip
    text = "The table statistics are stale."
    assert filter_text(text, pre_benchmark(stats=stale)).text == text


def test_never_analyzed_is_kept_when_planner_statistics_are_absent() -> None:
    absent = StatsSupport(
        tables_known=True, planner_stats_absent=True, stale=False, freshness_known=True,
        counters_live=True,
    )  # fmt: skip
    text = "The orders table has never been analyzed."
    assert filter_text(text, pre_benchmark(stats=absent)).text == text


def test_without_table_statistics_nothing_is_judged() -> None:
    text = "The orders table has never been analyzed."
    ctx = pre_benchmark(stats=StatsSupport())
    assert filter_text(text, ctx).text == text


# --- helpers ---


def test_star_projection_detection() -> None:
    assert star_projection(QUERY) is True
    assert star_projection("SELECT id, total FROM orders WHERE customer_id = $1") is False
    assert star_projection("SELECT o.* FROM orders o") is True
    assert star_projection(None) is None
    assert star_projection("not sql at all ((") is None


def test_index_columns_parse_ddl() -> None:
    ddl = (
        'CREATE INDEX CONCURRENTLY IF NOT EXISTS "ix" ON public.orders '
        'USING btree ("Customer_Id", created_at DESC)'
    )
    assert index_columns(ddl) == frozenset({"customer_id", "created_at"})
    assert index_columns("ANALYZE orders") == frozenset()


def test_problems_and_removed_sentences_are_reported() -> None:
    out = filter_text(RUN2_SUMMARY, post_benchmark())
    assert len(out.removed) == 3
    assert out.text.endswith("ORDER BY created_at DESC.")


# --- false positives found on the recorded smoke evals (real model text, real plan values) ---


def test_truncated_estimate_ratios_are_supported() -> None:
    # pg17_canonical_hot_analyze: Sort estimate_error_ratio 270.81, Gather Merge 433.3
    ctx = pre_benchmark(ratios=(270.81, 433.3, 1.3), plan_node_types=frozenset({"sort"}))
    text = (
        "Gather Merge estimates 8,666 rows but sees only 20 (433\u00d7 overestimate). "
        "Sort estimates 4,333 rows but sees 16 per loop (270\u00d7 overestimate)."
    )
    assert filter_text(text, ctx).text == text
    assert filter_text("Sort node overestimates rows by 270\u00d7 despite LIMIT 20", ctx).text


def test_an_estimate_ratio_never_counts_as_a_speedup() -> None:
    ctx = pre_benchmark(ratios=(270.81,))
    assert filter_text("The index makes it 270x faster.", ctx).text == ""


def test_approximate_latencies_get_a_wider_tolerance() -> None:
    ctx = pre_benchmark(latencies_ms=(62.568, 68.722))
    text = "The query spends most of its time (\u224862\u202fms, 91% of runtime) in a scan."
    assert filter_text(text, ctx).text == text
    assert filter_text("It takes 62 ms.", ctx).text  # 0.9% off: rounding
    assert filter_text("It takes about 80 ms.", ctx).text == ""  # 16% beyond 68.7


def test_truncated_speedups_are_supported() -> None:
    assert filter_text("It is 2.9x faster.", post_benchmark()).text  # measured 2.955
