"""Grounding wired into every LLM output boundary (ADR-0026), on run-2 shaped records."""

import uuid

from querycure.agents.candidates import judge_candidates
from querycure.agents.claims_v2 import ActionRef, claim_context, index_columns
from querycure.agents.nodes.write_report import model_failure
from querycure.agents.outputs import (
    AgentAnalysis,
    AuditNarrative,
    CandidateDraft,
    CandidateSet,
    ConcernDraft,
    FindingDraft,
    HypothesisDraft,
    HypothesisSet,
    judge_analysis,
    judge_audit,
    judge_hypotheses,
)
from querycure.domain.investigation import Evidence
from querycure.evidence.ids import evidence_id

RUN = uuid.UUID("2968ce49-cb65-416e-811b-0c6e4d613d4b")
QUERY = "SELECT * FROM orders WHERE customer_id = $1 ORDER BY created_at DESC LIMIT 20"


def _ev(kind: str, locator: str, data: dict[str, object], summary: str = "s") -> Evidence:
    return Evidence(
        id=evidence_id(RUN, kind, "a" * 64, locator),  # type: ignore[arg-type]
        kind=kind,  # type: ignore[arg-type]
        artifact_sha256="a" * 64,
        locator=locator,
        summary=summary,
        data=data,  # type: ignore[arg-type]
        provenance="measured",
    )


SEQ = _ev("plan_node", "/0/Plans/0/Plans/0", {"node_type": "Seq Scan", "relation": "orders"})
SORT = _ev("plan_node", "/0/Plans/0", {"node_type": "Sort", "total_cost": 2000.0})
TABLE = _ev(
    "table_stat",
    "/tables/0",
    {
        "table": "public.orders", "estimated_rows": 100000.0, "seq_scan": 0, "idx_scan": 0,
        "stats_origin": "sandbox_clone", "planner_stats": "present", "analyzed_columns": 5,
        "counters": "reset_by_clone", "freshness": "unknown",
    },
)  # fmt: skip
METRIC = _ev(
    "benchmark_metric",
    "/stats/oc_fcc7c344b33b/hot_customer",
    {
        "arm": "oc_fcc7c344b33b", "param_set": "hot_customer", "speedup": 2.955,
        "ci_low": 2.697, "ci_high": 3.398, "baseline_median_ms": 3.808,
        "candidate_median_ms": 1.289,
    },
)  # fmt: skip
PRE = [SEQ, SORT, TABLE]
KINDS = {e.id: e.kind for e in [*PRE, METRIC]}


def test_context_is_built_from_recorded_evidence_only() -> None:
    ctx = claim_context([*PRE, METRIC], query_sql=QUERY)

    assert ctx.plan_node_types == frozenset({"seq scan", "sort"})
    assert ctx.star_projection is True
    assert ctx.benchmarked
    assert (2.697, 3.398) in ctx.intervals
    assert 3.808 in ctx.latencies_ms
    assert ctx.stats.tables_known
    assert not ctx.stats.counters_live
    assert not ctx.stats.planner_stats_absent


def test_legacy_table_evidence_without_classification_is_not_judged() -> None:
    legacy = _ev("table_stat", "/tables/0", {"table": "public.orders", "last_analyze": None})
    assert not claim_context([legacy], query_sql=QUERY).stats.tables_known


def test_findings_lose_unsupported_sentences_and_unsupported_titles_drop_the_finding() -> None:
    output = AgentAnalysis(
        summary="A Seq Scan reads every row. The table has never been analyzed.",
        findings=[
            FindingDraft(
                title="Existing index not useful for this query",
                detail=(
                    "The only existing index is orders_pkey on the id column. It does not "
                    "assist the filter, and the table has never had an index scan "
                    "(0 index scans ever)."
                ),
                severity="medium",
                evidence_ids=[SEQ.id],
            ),
            FindingDraft(
                title="Table statistics show zero scans and never analyzed",
                detail="The table shows 0 seq scans and 0 index scans.",
                severity="low",
                evidence_ids=[TABLE.id],
            ),
        ],
    )

    cleaned, report = judge_analysis(output, KINDS, claim_context(PRE, query_sql=QUERY))

    assert [f.title for f in cleaned.findings] == ["Existing index not useful for this query"]
    assert cleaned.findings[0].detail == "The only existing index is orders_pkey on the id column."
    assert cleaned.summary == "A Seq Scan reads every row."
    assert report.claims_removed == 1
    assert report.removed == 0  # grounding never counts toward the citation retry
    assert not report.needs_retry


def test_never_analyzed_hypothesis_is_dropped_but_prospective_ones_stay() -> None:
    output = HypothesisSet(
        summary="",
        hypotheses=[
            HypothesisDraft(
                statement=(
                    "Table statistics are stale (never analyzed), which may lead to poor "
                    "planner estimates and suboptimal plan choice."
                ),
                category="stale_statistics", supporting_evidence=[TABLE.id],
                confidence="medium", uncertainty_notes="", verification_method="stats_refresh",
            ),
            HypothesisDraft(
                statement=(
                    "A composite index on (customer_id, created_at DESC) would allow an Index "
                    "Scan that returns rows already sorted."
                ),
                category="missing_index", supporting_evidence=[SEQ.id], confidence="high",
                uncertainty_notes="", verification_method="benchmark",
            ),
        ],
    )  # fmt: skip

    cleaned, report = judge_hypotheses(output, KINDS, claim_context(PRE, query_sql=QUERY))

    assert [h.category for h in cleaned.hypotheses] == ["missing_index"]
    assert report.claims_removed == 1


def test_candidate_prose_cannot_promise_an_impossible_index_only_scan() -> None:
    draft = CandidateDraft(
        kind="create_index",
        addresses_hypotheses=["hy_000000000001"],
        ddl=["CREATE INDEX ON orders (customer_id, created_at DESC)"],
        expected_benefit="Supports both filter and order, enabling index-only ordered scan.",
        risks=["Will be 5x faster on writes."],
    )
    cleaned, report = judge_candidates(
        CandidateSet(candidates=[draft], summary="s"),
        baseline=QUERY,
        hypothesis_keys={"hy_000000000001"},
        seen_digests=set(),
        max_candidates=4,
        claims=claim_context(PRE, query_sql=QUERY),
    )

    assert cleaned.candidates[0].expected_benefit == ""
    assert cleaned.candidates[0].risks == []
    assert cleaned.candidates[0].ddl  # the SQL itself is untouched
    assert len(report.claim_problems) == 2


def test_auditor_figures_must_match_measurements_and_verdicts() -> None:
    arms = frozenset({"oc_fcc7c344b33b", "oc_b3823040f745"})
    actions = [
        ActionRef("oc_fcc7c344b33b", "create_index",
                  index_columns("CREATE INDEX i ON orders (customer_id, created_at DESC)"), True),
        ActionRef("oc_b3823040f745", "analyze_statistics", frozenset(), False),
    ]  # fmt: skip
    ctx = claim_context(
        [*PRE, METRIC],
        query_sql=QUERY,
        actions=actions,
        verdicts={"oc_fcc7c344b33b": "verified_with_noise_warning",
                  "oc_b3823040f745": "inconclusive"},
    )  # fmt: skip
    output = AuditNarrative(
        summary=(
            "The composite index showed 2.9\u20114.4\u00d7 median latency reductions. "
            "It measured 2.95x (95% CI 2.70-3.40x) on hot_customer. "
            "Running ANALYZE is recommended as well."
        ),
        concerns=[
            ConcernDraft(arm="oc_b3823040f745", severity="info",
                         text="oc_b3823040f745 was verified at 9x.", evidence_ids=[METRIC.id]),
            ConcernDraft(arm="oc_fcc7c344b33b", severity="warning",
                         text="Measurements are noisy.", evidence_ids=[METRIC.id]),
        ],
    )  # fmt: skip

    cleaned, report = judge_audit(output, KINDS, arms, ctx)

    assert cleaned.summary == "It measured 2.95x (95% CI 2.70-3.40x) on hot_customer."
    assert [c.text for c in cleaned.concerns] == ["Measurements are noisy."]
    assert report.claims_removed == 1


def test_model_failure_names_the_causes_when_no_call_succeeded() -> None:
    error = model_failure({"LLM_INVALID_OUTPUT": 5, "LLM_TIMEOUT": 2})

    assert error is not None
    assert error["code"] == "MODEL_UNAVAILABLE"
    assert "5 invalid structured output, 2 timeout" in error["message"]
    assert error["details"] == [
        {"code": "LLM_INVALID_OUTPUT", "count": 5},
        {"code": "LLM_TIMEOUT", "count": 2},
    ]


def test_model_failure_is_silent_when_any_call_succeeded_or_none_was_made() -> None:
    assert model_failure({"succeeded": 1, "LLM_TIMEOUT": 4}) is None
    assert model_failure({"tool_call": 1, "LLM_TIMEOUT": 4}) is None
    assert model_failure({}) is None
