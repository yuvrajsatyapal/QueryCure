"""write_report grounding on real records (E2E audit O2, O7; ADR-0026).

Reproduces run 2: the pre-benchmark synthesis summary recommended "creating the index and
running ANALYZE" and an index-only scan; after the benchmark the composite index was
`verified_with_noise_warning` and ANALYZE `inconclusive`.
"""

import uuid
from types import SimpleNamespace
from typing import Any, cast

import pytest
from sqlalchemy.ext.asyncio import AsyncEngine

from querycure.agents.candidates import to_candidates
from querycure.agents.claims import CHECKER_VERSION
from querycure.agents.nodes.write_report import _reconcile_summary, model_failure
from querycure.agents.outputs import CandidateDraft, CandidateSet
from querycure.agents.runtime import RunContext
from querycure.agents.state import InvestigationState
from querycure.db.repositories.agents import call_outcomes
from querycure.db.repositories.optimization import insert_candidates, set_candidate_status
from querycure.domain.investigation import Evidence
from querycure.evidence.ids import evidence_id
from querycure.evidence.store import list_evidence, record_evidence
from querycure.replay import artifact_store as store
from tests.integration.test_investigation_graph import create_run

pytestmark = pytest.mark.integration

QUERY = "SELECT * FROM orders WHERE customer_id = $1 ORDER BY created_at DESC LIMIT 20"
SUMMARY = (
    "The query is slow because it performs a sequential scan on the orders table due to a "
    "missing index on customer_id. A composite index on (customer_id, created_at DESC) would "
    "allow an index\u2011only scan that returns rows already sorted. Creating the recommended "
    "index and running ANALYZE should resolve the performance issue."
)
HY = "hy_000000000001"


async def _seed(engine: AsyncEngine) -> tuple[uuid.UUID, str]:
    run_id = await create_run(engine, sql=QUERY, plan_file=None)
    drafts = [
        CandidateDraft(kind="create_index", addresses_hypotheses=[HY],
                       ddl=["CREATE INDEX ON orders (customer_id, created_at DESC)"],
                       expected_benefit="b"),
        CandidateDraft(kind="analyze_statistics", addresses_hypotheses=[HY],
                       ddl=["ANALYZE orders"], expected_benefit="b"),
    ]  # fmt: skip
    candidates = to_candidates(run_id, 0, CandidateSet(candidates=drafts, summary="s"))
    sha = "b" * 64
    metric = Evidence(
        id=evidence_id(run_id, "benchmark_metric", sha, "/stats/x/hot"),  # type: ignore[arg-type]
        kind="benchmark_metric",
        artifact_sha256=sha,
        locator="/stats/x/hot",
        summary="speedup 2.955x",
        data={"arm": candidates[0].key, "param_set": "hot", "speedup": 2.955,
              "ci_low": 2.697, "ci_high": 3.398},
        provenance="measured",
    )  # fmt: skip
    await record_evidence(engine, run_id, [metric])
    async with engine.begin() as conn:
        stored = await insert_candidates(conn, run_id, candidates)
        ids = {c.kind: c.id for c in stored}
        await set_candidate_status(
            conn, run_id, [cast(uuid.UUID, ids["create_index"])], "verified_with_noise_warning"
        )
        await set_candidate_status(
            conn, run_id, [cast(uuid.UUID, ids["analyze_statistics"])], "inconclusive"
        )
        art = await store.store_raw_sql(conn, QUERY)
    return run_id, art.sha256


async def test_summary_loses_the_unverified_analyze_and_the_impossible_index_only_scan(
    app_engine: AsyncEngine,
) -> None:
    run_id, query_sha = await _seed(app_engine)
    ctx = cast(RunContext, SimpleNamespace(run_id=run_id))
    state = cast(InvestigationState, {"query_sql_sha256": query_sha})

    async with app_engine.begin() as conn:
        evidence = await list_evidence(conn, run_id)
        summary, check = await _reconcile_summary(conn, ctx, state, evidence, SUMMARY)

    assert summary == (
        "The query is slow because it performs a sequential scan on the orders table due to a "
        "missing index on customer_id."
    )
    assert check is not None
    assert check["checker"] == CHECKER_VERSION
    assert len(check["removed_sentences"]) == 2
    assert any("ANALYZE" in p for p in check["problems"])
    assert any("index-only scan" in p for p in check["problems"])


async def test_nothing_is_reconciled_before_a_benchmark(app_engine: AsyncEngine) -> None:
    run_id = await create_run(app_engine, sql=QUERY, plan_file=None)
    ctx = cast(RunContext, SimpleNamespace(run_id=run_id))

    async with app_engine.begin() as conn:
        summary, check = await _reconcile_summary(conn, ctx, {}, [], SUMMARY)

    assert (summary, check) == (SUMMARY, None)


async def test_a_total_model_outage_gets_a_run_level_reason(
    app_engine: AsyncEngine, owner: Any
) -> None:
    run_id = await create_run(app_engine, sql=QUERY, plan_file=None)
    for i, (status, code) in enumerate(
        [("invalid_output", "LLM_INVALID_OUTPUT"), ("failed", "LLM_TIMEOUT")] * 2
    ):
        owner.execute(
            "INSERT INTO agent_executions (run_id, agent, node, invocation_key, attempt, "
            "prompt_version, model, requested_model, status, error) VALUES (%s, 'qa', 'qa', "
            "'qa:0', %s, 'p@1', 'm', 'm', %s, jsonb_build_object('code', %s::text))",
            (run_id, i + 1, status, code),
        )

    async with app_engine.connect() as conn:
        outcomes = await call_outcomes(conn, run_id)

    assert outcomes == {"LLM_INVALID_OUTPUT": 2, "LLM_TIMEOUT": 2}
    error = model_failure(outcomes)
    assert error is not None
    assert error["code"] == "MODEL_UNAVAILABLE"
